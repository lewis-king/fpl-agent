"""Stateful three-world policy ablation with exact configurations and fresh holdout.

Research only. No live data refresh, publication, or automatic promotion. Risks
apply to BOTH configuration and route selection; each arm owns its actual state.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .component_simulator import PLAYER_GAMEWEEKS
from .distribution_policy_audit import remap_score_shapes
from .historical_worlds import (
    COMPONENT_OOF,
    HISTORICAL_TEAMS,
    TRANSFER_VALUE_ARTIFACT,
    WEIGHTS,
    PrefixWorlds,
    origin_cutoff,
)
from .horizon_decay_replay import _historical_rules, _initial_state, _load_inputs
from .market_transfer_replay import moving_block_mean_interval
from .rules import POSITIONS_PATH, RULES_PATH
from .sequential_policy_replay import (
    SequentialConfig,
    expanded_candidates,
    origin_simulation_rows,
    search,
)
from .simulation_calibration import deadline_calibration
from .tournament import HISTORICAL_FIXTURES
from .weekly_configuration import optimise_configurations, paired_validation, score_configurations
from .weekly_continuation_replay import (
    _record,
    prefix_coefficients,
    prepare_deadline,
    reprice_state,
)
from .weekly_decision import synthesize_weekly_decision
from .weekly_policy_research import compose_plan, guard_future_transfers

RISKS = {"baseline": .25, "premium_reinvestment": .25, "risk_0": 0.,
         "risk_010": .1, "risk_050": .5, "guarded_recourse": .25, "score_shape": .25}
ARMS = tuple(RISKS)


def choose(actions, metrics, rows, event, risk):
    return synthesize_weekly_decision(
        actions, metrics, scenario_weights=WEIGHTS, worst_case_weight=risk,
        event_rows={int(r["element"]): r for r in rows if r["event_number"] == event})


def freeze_and_validate(actions, selection, validation, rows, events, risk):
    metrics, _ = score_configurations(actions, selection, events=events)
    picked = choose(actions, metrics, rows, events[0], risk)["selected_action_id"]
    holdout, _ = score_configurations(actions, validation, events=events)
    gate = choose(actions, holdout, rows, events[0], risk)["selection_audit"]["gates_by_action"][picked]
    winner = next(a for a in actions if a.action_id == picked)
    roll = next(a for a in actions if a.route_type == "roll")
    return winner if gate["passed"] else roll, {
        "frozen_selection": picked, "validation_gate": gate,
        "holdout_reselection": False, "fallback": None if gate["passed"] else roll.action_id}


def configured_choice(actions, state, rows, rules, selection, validation, events, risk, cache):
    # Freeze the unrefined fallback BEFORE reading validation outcomes too.
    original, original_gate = freeze_and_validate(actions, selection, validation, rows, events, risk)
    configured, audit = optimise_configurations(
        actions, state, rows, rules, selection, WEIGHTS, events=events,
        worst_case_weight=risk, frontier_cache=cache)
    winner, selection_gate = freeze_and_validate(configured, selection, validation, rows, events, risk)
    _, before = score_configurations(actions, validation, events=events)
    _, after = score_configurations(configured, validation, events=events)
    idx = next(i for i, a in enumerate(configured) if a.action_id == winner.action_id)
    validation_audit = paired_validation(before, after, WEIGHTS, idx)
    same = actions[idx].lineups == configured[idx].lineups
    # Match the production transaction: a rejected refinement keeps the original
    # full decision, not a hybrid roster with a separately chosen validation XI.
    accepted = (same or validation_audit["monte_carlo_95_low"] > 0) and all(
        gain >= -0.05 for gain in validation_audit["world_gains"].values())
    final = winner if accepted else original
    return final, {
        "configuration_risk": risk, "route_risk": risk,
        "configuration_validation": validation_audit, "configuration_accepted": accepted,
        "original_gate": original_gate, "configured_gate": selection_gate,
        "possible_configurations": audit["possible_configurations"],
        "unique_frontiers": audit["unique_frontiers"],
        "configuration_hash": audit["frozen_configuration_sha256"],
    }, configured if accepted else actions


def recourse_choice(actions, rows, rules, events, config, curve, selection, validation):
    plans, branches = [], {}
    for root in actions:
        children, _ = search(root.outcome.next_manager,
                             [r for r in rows if r["event_number"] in events[1:]],
                             rules, events[1:], config, curve)
        hold = next(a for a in children if a.route_type == "roll")
        # Preserve the hold at EVERY root. Never infer future benefit by comparing
        # one root's transfer with another root's fixed roster.
        best = min(children, key=lambda a: (-a.decision_utility, a.action_id))
        for child in (hold,) if best == hold else (hold, best):
            plan = compose_plan(root, child, rows, rules=rules, decay=config.decay)
            plans.append(plan)
            branches[plan.action_id] = {"no_future_transfer": not child.action.transfers,
                                        "next_incremental_points_cost": child.incremental_points_cost}
    combined = [*actions, *plans]
    metrics, totals = score_configurations(combined, selection, events=events)
    indices = {a.action_id: i for i, a in enumerate(combined)}
    frontier, guards = guard_future_transfers(plans, branches, metrics, totals, indices, WEIGHTS)
    roll = next(a.action_id for a in actions if a.route_type == "roll")
    frontier = [replace(a, route_type="roll" if a.parent_action_id == roll
                        else a.route_type.removeprefix("planned_")) for a in frontier]
    winner, audit = freeze_and_validate(frontier, selection, validation, rows, events, .25)
    vm, vt = score_configurations(combined, validation, events=events)
    _, vg = guard_future_transfers(plans, branches, vm, vt, indices, WEIGHTS)
    passed = next(g["passed"] for g in vg if g["plan_id"] == winner.action_id)
    if passed:
        root = next(a for a in actions if a.action_id == winner.parent_action_id)
    else:
        root, _ = freeze_and_validate(actions, selection, validation, rows, events, .25)
    return root, {**audit, "future_holdout_passed": passed, "selection_guards": guards,
                  "validation_guards": vg, "executed_root": root.action_id,
                  "future_search": "one scalar best child plus hold per exact root; no future news oracle"}


def season_replay(inputs, fixtures, season, config, progress):
    coefficients, training_seasons = prefix_coefficients(inputs, season)
    prefix = PrefixWorlds.fit(inputs, season, fixtures, progress)
    rules = _historical_rules(season)
    records, states = {a: [] for a in ARMS}, {}
    lineage, calibration = [], []
    for event in range(1, config.end_event + 1):
        rows, outcomes, snapshot = prepare_deadline(inputs, season, event, config, coefficients)
        rows = origin_simulation_rows(rows)
        events = tuple(sorted({int(r["event_number"]) for r in rows}))
        current = [r for r in rows if r["event_number"] == event]
        if event == 1:
            initial, solution = _initial_state(season=season, rows=rows, events=events,
                                               decay=config.decay, rules=rules)
            record, next_state = _record(initial, None, solution, outcomes, snapshot, rows, [], None)
            for arm in ARMS:
                records[arm].append(record)
                states[arm] = next_state
        else:
            dated = inputs["fixture_by_snapshot"][(season, snapshot["snapshot_event"])]
            rows, components, goals, provenance = prefix.prepare(inputs, rows, dated, event)
            seed = config.seed + int(season[:4]) * 1000 + event * 20
            progress({"season": season, "event": event, "stage": "sampling three selection and three untouched validation worlds"})
            selection, validation = [prefix.sample(rows, dated, components, goals, events=events,
                                                   samples=config.samples, seed=seed + offset)[0]
                                     for offset in (0, 2)]
            changed = []
            for worlds, offset in ((selection, 4), (validation, 5)):
                shape, audit = remap_score_shapes(worlds["residual"], rows, prefix.shapes,
                                                  events=events, seed=seed + offset)
                changed.append({**worlds, "residual": shape})
                lineage.append({**provenance, "shape": audit, "draw_seed": seed + offset})
            searches, cache, shape_cache, configured_cache = {}, {}, {}, {}
            for arm in ARMS:
                state = reprice_state(states[arm], current)
                if state not in searches:
                    searches[state] = search(state, rows, rules, events, config, prefix.terminal_curve)
                actions, trace = searches[state]
                extra = {}
                if arm == "premium_reinvestment":
                    actions, extra["capital_search"] = expanded_candidates(
                        state, actions, rows, rules, events, config, prefix.terminal_curve)
                sw, vw = changed if arm == "score_shape" else (selection, validation)
                key = (state, tuple(a.action_id for a in actions), RISKS[arm], arm == "score_shape")
                if arm == "guarded_recourse":
                    # Do not use an earlier holdout decision to choose the set
                    # of configurations searched by this separate hypothesis.
                    configured, configuration_audit = optimise_configurations(
                        actions, state, rows, rules, sw, WEIGHTS, events=events,
                        worst_case_weight=.25, frontier_cache=cache)
                    winner, extra["recourse"] = recourse_choice(
                        configured, rows, rules, events, config, prefix.terminal_curve, sw, vw)
                    _, before = score_configurations(actions, vw, events=events)
                    _, after = score_configurations(configured, vw, events=events)
                    idx = next(i for i, a in enumerate(actions) if a.action_id == winner.action_id)
                    paired = paired_validation(before, after, WEIGHTS, idx)
                    accepted = (actions[idx].lineups == configured[idx].lineups
                                or paired["monte_carlo_95_low"] > 0) and all(
                                    gain >= -.05 for gain in paired["world_gains"].values())
                    if not accepted:
                        winner, _ = freeze_and_validate(actions, sw, vw, rows, events, .25)
                    diagnostic = {"configuration_validation": paired,
                                  "configuration_accepted": accepted,
                                  "configuration_hash": configuration_audit["frozen_configuration_sha256"]}
                elif key not in configured_cache:
                    configured_cache[key] = configured_choice(
                        actions, state, rows, rules, sw, vw, events, RISKS[arm],
                        shape_cache if arm == "score_shape" else cache)
                if arm != "guarded_recourse":
                    winner, diagnostic, configured = configured_cache[key]
                record, states[arm] = _record(state, winner, None, outcomes, snapshot, rows, trace,
                                              {**diagnostic, **extra})
                records[arm].append(record)
                progress({"season": season, "event": event, "arm": arm,
                          "net_points": sum(r["net_points"] for r in records[arm]),
                          "executed_root": winner.action_id})
            # Outcome labels enter only this post-choice scoring stage, never
            # configuration search, scenario generation or branch ranking.
            calibration.append({"event": event, "cohorts": deadline_calibration(
                {**validation, "score_shape_residual": changed[1]["residual"]}, outcomes,
                records["baseline"][-1])})
        progress({"season": season, "event": event, "stage": "event complete",
                  "totals": {a: sum(r["net_points"] for r in rs) for a, rs in records.items()}})
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
            "fixture_response_training": training_seasons, "simulation_lineage": lineage,
            "paths": paths, "comparisons": comparisons, "distribution_calibration": calibration}


def run_replay(output, config=None, progress=None, *, experiment=None, season_runner=None):
    config = config or SequentialConfig()
    config.validate()
    if config.decay != .88:
        raise ValueError("Exact configuration replay currently matches the .88 production decay")
    if output.exists():
        raise FileExistsError("Research output cannot overwrite an earlier experiment")
    inputs = _load_inputs()
    inputs["paths"].update(residual_fixtures=HISTORICAL_FIXTURES,
                          historical_team_codes=HISTORICAL_TEAMS,
                          empirical_components=PLAYER_GAMEWEEKS, component_oof=COMPONENT_OOF,
                          terminal_curve=TRANSFER_VALUE_ARTIFACT, rules=RULES_PATH, positions=POSITIONS_PATH)
    code = {str(p): sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    script = Path(__file__).resolve().parents[2] / "scripts/replay_multiworld_policies.py"
    code[str(script)] = sha256_file(script)
    if experiment and experiment.get("runner_script"):
        extra_script = Path(__file__).resolve().parents[2] / experiment["runner_script"]
        code[str(extra_script)] = sha256_file(extra_script)
    sources = {str(p): sha256_file(p) for p in inputs["paths"].values()}
    payload = asdict(config)
    result = {"version": "multiworld_policy_replay_v1", "status": "running", "decision_authority": False,
              "created_at": datetime.now(UTC).isoformat(), "config": payload,
              "config_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
              "source_hashes": sources, "code_hashes": code, "risk_by_arm": RISKS,
              "preregistered_screen": "Positive net-points delta in BOTH complete GW1-10 folds; necessary not sufficient for promotion.",
              "scope": "Three production samplers, exact legal fixed-roster configurations, prefix empirical/goal/minute fits, nonzero prefix FT value; bounded roster/recourse search, NOT a complete historical production replication.",
              "limitations": ["No chip timing or retrospective lineup/market feeds in this ordinary-transfer experiment.",
                              "One optimal scalar roster per transfer count, max two transfers and two paid transfers.",
                              "Guarded continuation uses origin forecasts and prices, not an oracle of next week's news.",
                              "10k-path research holdout is smaller than production's 100k configuration holdout.",
                              "Season scoring regimes differ; raw component DC prior is unavailable before 2025/26.",
                              "These seasons are already inspected development folds; passing does not prove prospective lift."],
              "folds": []}
    arms = ARMS
    if experiment is not None:
        if season_runner is None:
            raise ValueError("A registered experiment requires its season runner")
        result.update(experiment)
        arms = tuple(experiment["risk_by_arm"])
        if arms[0] != "baseline":
            raise ValueError("The first registered arm must be baseline")
        result["experiment_sha256"] = hashlib.sha256(
            json.dumps(experiment, sort_keys=True).encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def checkpoint(item=None):
        if item:
            result["progress"] = item
        result["elapsed_seconds"] = time.monotonic() - started
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False, default=str) + "\n")
        temporary.replace(output)
        if item and progress:
            progress(item)

    checkpoint()
    try:
        # Check EVERY origin before expensive simulations, including missing
        # same-event snapshots. Never silently turn stale prices into exact quotes.
        preflight = []
        for season in config.seasons:
            for event in range(2, config.end_event + 1):
                features = {int(r["element"]): inputs["feature_by_key"][(season, event, int(r["element"]))]
                            for r in inputs["forecast_by_event"][(season, event)]}
                snapshot = max(e for e in inputs["available_snapshots"][season] if e <= event)
                cutoff, coverage = origin_cutoff(features, inputs["fixture_by_snapshot"][(season, snapshot)], event)
                preflight.append({"season": season, "event": event, "snapshot_event": snapshot,
                                  "observed_before": cutoff.isoformat(), **coverage})
        result["archive_preflight"] = preflight
        checkpoint({"stage": "archive time boundaries checked for all replay origins"})
        fixtures = pq.read_table(HISTORICAL_FIXTURES).to_pylist()
        for season in config.seasons:
            result["folds"].append((season_runner or season_replay)(
                inputs, fixtures, season, config, checkpoint))
            checkpoint()
        if any(sha256_file(Path(p)) != h for p, h in {**sources, **code}.items()):
            raise RuntimeError("Code or data changed during the frozen experiment")
        complete = config.end_event == 10 and set(config.seasons) == {"2024-25", "2025-26"}
        result["historical_screens"] = {arm: complete and all(
            f["comparisons"][arm]["net_points_delta"] > 0 for f in result["folds"]) for arm in arms[1:]}
        result.update(status="completed", hashes_stable=True, promotion="requires_explicit_review_not_automatic")
    except (Exception, KeyboardInterrupt) as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        checkpoint()
    return result
