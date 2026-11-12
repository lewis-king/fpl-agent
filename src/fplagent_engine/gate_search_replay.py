"""Preregistered gate/search factorial. Research only; never changes live policy.

Common random numbers, prefix-only fits, separate carried portfolios. Validation
can accept/reject a frozen choice, never re-rank candidates using holdout scores.
"""
from __future__ import annotations

from .historical_worlds import WEIGHTS, PrefixWorlds
from .horizon_decay_replay import _historical_rules, _initial_state
from .market_transfer_replay import moving_block_mean_interval
from .multiworld_policy_replay import configured_choice, freeze_and_validate, run_replay
from .sequential_policy_replay import origin_simulation_rows, search
from .weekly_actions import generate_weekly_actions
from .weekly_configuration import optimise_configurations, paired_validation, score_configurations
from .weekly_continuation_replay import (
    _record,
    prefix_coefficients,
    prepare_deadline,
    reprice_state,
)
from .weekly_decision import selected_incoming_role_risks

ARMS = ("baseline", "configuration_mean_gate", "broad_incumbent", "points_first", "broad_points_first")
SPEC = {
    "version": "gate_search_factorial_v1",
    "runner_script": "scripts/replay_gate_search.py",
    "risk_by_arm": {a: (0. if "points_first" in a else .25) for a in ARMS},
    "scope": "Five preregistered arms: incumbent, remove configuration world-veto only, wider incumbent, mean objective/gates, wider mean objective/gates. No news or outcome oracle.",
    "arm_definitions": {
        "baseline": "Existing risk .25, production route and configuration gates; one roster/transfer count.",
        "configuration_mean_gate": "Only remove configuration per-world -.05 veto. Keep weighted MC lower bound >0, risk .25, production route gates.",
        "broad_incumbent": "Existing gates/risk; four rosters/transfer count plus protected sales of two most expensive outfield holdings.",
        "points_first": "Risk 0 for configuration and route; positive covariance-aware weighted MC lower bound after costs, no world veto or win-frequency threshold. Incoming role checks retained.",
        "broad_points_first": "Same points-first policy on the wider pool.",
    },
    "preregistered_screen": "Positive net-points delta in BOTH complete GW1-10 folds; necessary not sufficient. These are previously inspected development folds, not independent confirmation.",
    "limitations": [
        "No historical Scout forecasts, chip timing, dated bookmaker or lineup feeds.",
        "Broad remains bounded: max two transfers (two paid), four scalar rosters/count plus two protected premium exits; not exhaustive production search.",
        "Paired MC intervals measure integration noise, not forecast confidence.",
        "The same xP anchors 95% of the world weights; worlds are not independent forecasters.",
        "Existing archive gaps, lagged prices and early-season-only evaluation remain.",
        "Do not tune arms after inspecting outcomes; no automatic live promotion.",
    ],
}


def broad_search(state, rows, rules, events, config, curve):
    # Include the narrow pool literally, so this is an expansion, not replacement.
    base, trace = search(state, rows, rules, events, config, curve)
    candidates = {a.action_id: a for a in base}
    holdings = sorted((h for h in state.squad if h.position != "GK"),
                      key=lambda h: (-h.selling_price, h.player_id))[:2]
    scopes = [{}, *({"required_outgoing_player_ids": (h.player_id,)} for h in holdings)]
    for constraints in scopes:
        attempts = []
        extra = generate_weekly_actions(
            state, rows, rules, events=events, score_field="expected_points",
            horizon_decay=config.decay, alternatives_per_transfer_count=4,
            max_total_transfers=2, max_paid_transfers=2,
            terminal_free_transfer_curve=curve, protect_role_sale_routes=False,
            solver_time_limit_seconds=config.solver_seconds, search_diagnostics=attempts,
            **constraints)
        if any(t["status"] == "unresolved" for t in attempts):
            raise RuntimeError("Unresolved broad historical search; cannot treat a timeout as no alternative")
        trace.extend(attempts)
        candidates.update({a.action_id: a for a in extra})
    return list(candidates.values()), trace


def mean_gate(actions, totals, index, rows, event):
    roll = next(i for i, a in enumerate(actions) if a.route_type == "roll")
    reference = {n: values[:, [roll]].repeat(len(actions), axis=1) for n, values in totals.items()}
    audit = paired_validation(reference, totals, WEIGHTS, index)
    risks = selected_incoming_role_risks(actions[index], {
        int(r["element"]): r for r in rows if r["event_number"] == event})
    return {**audit, "incoming_role_risks": risks,
            "passed": not risks and (index == roll or audit["monte_carlo_95_low"] > 0)}


def freeze_mean(actions, selection, validation, rows, events):
    _, st = score_configurations(actions, selection, events=events)
    gates = [mean_gate(actions, st, i, rows, events[0]) for i in range(len(actions))]
    chosen = min((i for i, gate in enumerate(gates) if gate["passed"]),
                 key=lambda i: (-gates[i]["weighted_gain"], actions[i].action_id))
    # This index is frozen before scoring validation. No validation winner lookup.
    _, vt = score_configurations(actions, validation, events=events)
    gate = mean_gate(actions, vt, chosen, rows, events[0])
    roll = next(a for a in actions if a.route_type == "roll")
    return actions[chosen] if gate["passed"] else roll, {
        "frozen_selection": actions[chosen].action_id, "validation_gate": gate,
        "holdout_reselection": False, "fallback": None if gate["passed"] else roll.action_id,
        "selection_gates": {a.action_id: g for a, g in zip(actions, gates, strict=True)}}


def relaxed_configuration(actions, state, rows, rules, selection, validation, events, cache, *, mean_policy):
    risk = 0. if mean_policy else .25

    def freeze(items):
        if mean_policy:
            return freeze_mean(items, selection, validation, rows, events)
        return freeze_and_validate(items, selection, validation, rows, events, risk)

    original, original_gate = freeze(actions)
    configured, audit = optimise_configurations(
        actions, state, rows, rules, selection, WEIGHTS, events=events,
        worst_case_weight=risk, frontier_cache=cache)
    winner, gate = freeze(configured)
    _, before = score_configurations(actions, validation, events=events)
    _, after = score_configurations(configured, validation, events=events)
    idx = next(i for i, a in enumerate(configured) if a.action_id == winner.action_id)
    paired = paired_validation(before, after, WEIGHTS, idx)
    accepted = actions[idx].lineups == configured[idx].lineups or paired["monte_carlo_95_low"] > 0
    return winner if accepted else original, {
        "configuration_risk": risk, "route_risk": risk,
        "configuration_validation": paired, "configuration_accepted": accepted,
        "original_gate": original_gate, "configured_gate": gate,
        "configuration_hash": audit["frozen_configuration_sha256"],
        "world_veto": False,
    }


def season_replay(inputs, fixtures, season, config, progress):
    coefficients, training = prefix_coefficients(inputs, season)
    prefix = PrefixWorlds.fit(inputs, season, fixtures, progress)
    rules = _historical_rules(season)
    records, states, lineage = {a: [] for a in ARMS}, {}, []
    for event in range(1, config.end_event + 1):
        rows, outcomes, snapshot = prepare_deadline(inputs, season, event, config, coefficients)
        rows = origin_simulation_rows(rows)
        events = tuple(sorted({int(r["event_number"]) for r in rows}))
        if event == 1:
            initial, solution = _initial_state(season=season, rows=rows, events=events,
                                               decay=config.decay, rules=rules)
            record, next_state = _record(initial, None, solution, outcomes, snapshot, rows, [], None)
            for arm in ARMS:
                records[arm].append(record)
                states[arm] = next_state
            continue
        dated = inputs["fixture_by_snapshot"][(season, snapshot["snapshot_event"])]
        rows, components, goals, provenance = prefix.prepare(inputs, rows, dated, event)
        lineage.append(provenance)
        seed = config.seed + int(season[:4]) * 1000 + event * 20
        selection, validation = [prefix.sample(rows, dated, components, goals, events=events,
                                               samples=config.samples, seed=seed + offset)[0]
                                 for offset in (0, 2)]
        current = [r for r in rows if r["event_number"] == event]
        searches, cache = {}, {}
        for arm in ARMS:
            state = reprice_state(states[arm], current)
            broad = arm.startswith("broad_")
            key = (state, broad)
            if key not in searches:
                searches[key] = (broad_search if broad else search)(
                    state, rows, rules, events, config, prefix.terminal_curve)
            actions, trace = searches[key]
            if arm in {"baseline", "broad_incumbent"}:
                winner, audit, _ = configured_choice(
                    actions, state, rows, rules, selection, validation, events, .25, cache)
            else:
                winner, audit = relaxed_configuration(
                    actions, state, rows, rules, selection, validation, events, cache,
                    mean_policy="points_first" in arm)
            record, states[arm] = _record(state, winner, None, outcomes, snapshot, rows, trace,
                                          {**audit, "candidate_count": len(actions)})
            records[arm].append(record)
            progress({"season": season, "event": event, "arm": arm, "candidates": len(actions),
                      "net_points": sum(r["net_points"] for r in records[arm]),
                      "executed_root": winner.action_id})
    paths = {a: {"events": rs, "net_points": sum(r["net_points"] for r in rs),
                 "points_cost": sum(r["points_cost"] for r in rs),
                 "transfers": sum(len(r["transfers"]) for r in rs)} for a, rs in records.items()}
    comparisons = {}
    for arm in ARMS[1:]:
        deltas = [a["net_points"] - b["net_points"]
                  for a, b in zip(records[arm][1:], records["baseline"][1:], strict=True)]
        comparisons[arm] = {"net_points_delta": sum(deltas), "event_deltas": deltas,
                            "block_mean_interval": moving_block_mean_interval(
                                deltas, block_length=min(4, len(deltas)), samples=5000, seed=49019)}
    return {"season": season, "provenance": prefix.provenance, "terminal_curve": prefix.terminal_curve,
            "fixture_response_training": training, "simulation_lineage": lineage,
            "paths": paths, "comparisons": comparisons}


def run_experiment(output, config=None, progress=None):
    return run_replay(output, config, progress, experiment=SPEC, season_runner=season_replay)
