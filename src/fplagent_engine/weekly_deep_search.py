"""Wider weekly roster search and exact fixed-roster configuration search.

Selection is frozen before either independent validation sample is generated.
Holdout winners never replace the selection winner: they can only validate or
reject it. Current calibrated forecasts/risk coefficients/chip authority do not
change. This is not an adaptive future-transfer or full-season optimum claim.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, replace
from itertools import pairwise
from pathlib import Path

import highspy
import numpy as np

from .current_squad_audit import _formation
from .exact_configuration import configuration_frontier, fused_score_candidates
from .season_state import Lineup, apply_action
from .weekly_actions import EventLineup, generate_weekly_actions
from .weekly_simulation import evaluate_action_paths

VERSION = "weekly_deep_search_v1"
DEPTHS = (4, 8, 16, 32)
SELECTION_SEEDS = (202609091, 202609092)
VALIDATION_SEEDS = ((202609093, 202609094), (202609095, 202609096))
VALIDATION_SAMPLES = 25_000
MAX_HOLDOUT_REGRET = 0.05
MAX_WORLD_LOSS = 0.05


def sample_worlds(rows, events, *, seeds, samples=25_000, component_forecast_path=None):
    """Same current production distributions, fresh seeds, no training or publication."""
    from .component_models import CURRENT_COMPONENT_FORECAST
    from .component_simulator import (
        COMPONENT_BACKTEST_METRICS,
        GOAL_MODEL_FILE,
        calibrate_empirical_components,
        predict_current_goal_rates,
        simulate_component_outcomes,
    )
    from .market_odds import apply_current_market_decision_rates
    from .tournament import _simulate_player_outcomes, calibrate_residuals
    from .weekly_actions import _forecast_grid

    if seeds[0] == seeds[1] or samples < 1_000:
        raise ValueError("Independent family seeds and sufficient samples are required")
    if not GOAL_MODEL_FILE.is_file():
        raise ValueError(
            "Deep audit requires the existing production goal model; never train implicitly"
        )
    by_player, meta = _forecast_grid(rows, events)
    ids = sorted(by_player)
    points, plays = _simulate_player_outcomes(
        ids, events, by_player, calibrate_residuals(), samples, seeds[0]
    )
    rates, _ = predict_current_goal_rates(by_player, events, persist=False)
    rates, market = apply_current_market_decision_rates(rates, events=events)
    component_ids, raw, anchored, component_plays, _, component_diagnostics = (
        simulate_component_outcomes(
            by_player,
            events,
            rates,
            calibrate_empirical_components(),
            samples,
            seeds[1],
            component_forecast_path=component_forecast_path or CURRENT_COMPONENT_FORECAST,
        )
    )
    raw_weight = float(
        json.loads(COMPONENT_BACKTEST_METRICS.read_text())["blend_selection"]["selected_raw_weight"]
    )
    weights = {
        "residual": 0.5,
        "component_anchored": 0.5 * (1 - raw_weight),
        "component_raw": 0.5 * raw_weight,
    }
    worlds = {
        name: {
            "player_ids": player_ids,
            "points": scores,
            "played": appearances,
            "player_meta": meta,
            "events": events,
        }
        for name, player_ids, scores, appearances in (
            ("residual", ids, points, plays),
            ("component_anchored", component_ids, anchored, component_plays),
            ("component_raw", component_ids, raw, component_plays),
        )
    }
    return (
        worlds,
        weights,
        {
            "seeds": seeds,
            "samples_per_family": samples,
            "market": market,
            "component": component_diagnostics,
        },
    )


def score(actions, worlds, events):
    metrics, totals = {}, {}
    for name, world in worlds.items():
        metrics[name], totals[name] = evaluate_action_paths(
            actions,
            events=events,
            score_candidates=fused_score_candidates,
            **{k: v for k, v in world.items() if k != "events"},
        )
    return metrics, totals


def joint_configuration(frontiers, *, weights, reference, constant, decay=0.88,
                        worst_case_weight=0.25):
    """Globally solve the fixed-roster five-event mean/regret configuration problem.

    Each event's complete non-dominated frontier is retained. The MILP searches
    their Cartesian product; it does not greedily optimise each GW's regret.
    """
    if not 0 <= worst_case_weight <= 1:
        raise ValueError("Risk weight must lie in [0, 1]")
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("mip_rel_gap", 1e-8)
    h.setOptionValue("time_limit", 30.0)
    sizes = [len(f["means"]) for f in frontiers]
    variables = h.addVariables(
        sum(sizes), lb=0, ub=1, type=highspy.HighsVarType.kInteger, out_array=True
    )
    worst = h.addVariable(lb=0)
    offsets = np.cumsum([0, *sizes])
    means = np.concatenate([f["means"] * decay**e for e, f in enumerate(frontiers)])
    for start, stop in pairwise(offsets):
        h.addConstr(sum(variables[start:stop]) == 1)
    for w in range(3):
        h.addConstr(
            reference[w] - constant - sum(means[i, w] * variables[i] for i in range(len(means)))
            <= worst
        )
    utility = means @ np.asarray(weights)
    h.minimize(-(1 - worst_case_weight) * sum(utility[i] * variables[i] for i in range(len(means)))
               + worst_case_weight * worst)
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"Unresolved joint configuration solve: {h.getModelStatus()}")
    return [
        next(i - start for i in range(start, stop) if h.val(variables[i]) > 0.5)
        for start, stop in pairwise(offsets)
    ]


def configured_action(root, choices, frontiers, state, rows, rules, events):
    current = {(int(r["event_number"]), int(r["element"])): r for r in rows}
    meta = {p: current[(events[0], p)] for p in root.selected_player_ids}
    lineups = []
    for event, choice, frontier in zip(events, choices, frontiers, strict=True):
        xi, bench, captain, vice = frontier["configurations"][choice]
        lineup = Lineup(tuple(xi), tuple(bench), captain, vice)
        xp = sum(float(current[(event, p)][root.score_field]) for p in xi)
        xp += float(current[(event, captain)][root.score_field])
        lineups.append(EventLineup(event, lineup, _formation(xi, meta), xp))
    bundle = replace(root.action, lineup=lineups[0].lineup)
    outcome = apply_action(state, bundle, rules)
    gross = sum(
        0.88**i
        * (
            item.projected_points
            + 0.08
            * sum(
                float(current[(item.event, p)][root.score_field]) for p in item.lineup.bench_order
            )
        )
        for i, item in enumerate(lineups)
    )
    identity = json.dumps([root.action_id, [asdict(l.lineup) for l in lineups]], sort_keys=True)
    return replace(
        root,
        action_id="D-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
        parent_action_id=root.action_id,
        lineups=tuple(lineups),
        action=bundle,
        outcome=outcome,
        gross_horizon_utility=gross,
        decision_utility=gross - root.incremental_points_cost + root.terminal_transfer_value,
        route_type="configuration_roll" if root.route_type == "roll" else root.route_type,
    )


def validation_gate(selection, actions, metrics, totals, *, weights, incumbent_id, selected_id):
    """One pre-frozen winner, checked without selecting on holdout outcomes."""
    from .weekly_decision import synthesize_weekly_decision

    current = selection["event_rows"]
    decision = synthesize_weekly_decision(
        actions, metrics, scenario_weights=weights, event_rows=current
    )
    ranking = {r["action_id"]: r for r in decision["admissible_ranking"]}
    selected_regret = ranking.get(selected_id, {}).get("robust_regret")
    best = min((r["robust_regret"] for r in ranking.values()), default=float("inf"))
    index = {a.action_id: i for i, a in enumerate(actions)}
    changes = {}
    for name, values in totals.items():
        delta = values[:, index[selected_id]] - values[:, index[incumbent_id]]
        se = float(delta.std(ddof=1) / np.sqrt(len(delta)))
        changes[name] = {
            "mean": float(delta.mean()),
            "mc95_low": float(delta.mean() - 1.96 * se),
            "mc95_high": float(delta.mean() + 1.96 * se),
            "samples": len(delta),
        }
    weighted_mean = sum(weights[n] * r["mean"] for n, r in changes.items())
    # Conservative bound: add weighted family SEs, do not pretend raw/anchored
    # component samples are independent.
    weighted_low = sum(weights[n] * r["mc95_low"] for n, r in changes.items())
    checks = {
        "selected_clears_existing_gates": selected_id in ranking,
        "within_fixed_holdout_regret_tolerance": selected_regret is not None
        and selected_regret - best <= MAX_HOLDOUT_REGRET,
        "no_material_world_loss_to_incumbent": all(
            r["mean"] >= -MAX_WORLD_LOSS for r in changes.values()
        ),
        "positive_paired_weighted_gain_to_incumbent": selected_id == incumbent_id
        or weighted_low > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "holdout_leader": decision["selected_action_id"],
        "frozen_selection": selected_id,
        "selected_regret_gap": None if selected_regret is None else selected_regret - best,
        "weighted_gain": weighted_mean,
        "conservative_weighted_mc95_low": weighted_low,
        "per_world_changes": changes,
    }


def run_deep_search(
    state,
    rows,
    rules,
    events,
    terminal_curve,
    *,
    incumbent_id,
    component_forecast_path=None,
    progress=None,
    output=None,
):
    """Complete audit. Returns the frozen selection and promotion evidence, never publishes."""
    from .weekly_decision import synthesize_weekly_decision

    started = time.monotonic()
    receipt = {
        "version": VERSION,
        "status": "running",
        "decision_authority": False,
        "specification": {
            "depths": DEPTHS,
            "selection_seeds": SELECTION_SEEDS,
            "validation_seeds": VALIDATION_SEEDS,
            "samples_per_family": VALIDATION_SAMPLES,
            "risk_weight": 0.25,
            "max_holdout_regret": MAX_HOLDOUT_REGRET,
            "max_world_loss_to_incumbent": MAX_WORLD_LOSS,
            "objective": "unchanged 0.75 weighted mean regret + 0.25 worst-world regret",
            "scope": "wider legal current-transfer rosters; exhaustive fixed-roster horizon configurations; no future transfer recourse",
        },
        "depth_searches": [],
        "configurations": [],
        "holdouts": [],
    }

    def update(message):
        receipt["progress"] = message
        receipt["elapsed_seconds"] = time.monotonic() - started
        if output is not None:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(receipt, indent=2, default=str) + "\n")
            tmp.replace(path)
        if progress:
            progress(message)

    update("Starting predeclared deeper weekly audit")
    by_id, memberships = {}, {}
    for depth in DEPTHS:
        trace = []
        actions = generate_weekly_actions(
            state,
            rows,
            rules,
            events=events,
            alternatives_per_transfer_count=depth,
            terminal_free_transfer_curve=terminal_curve,
            solver_time_limit_seconds=10,
            search_diagnostics=trace,
        )
        complete = all(r["status"] != "unresolved" for r in trace)
        receipt["depth_searches"].append(
            {"depth": depth, "actions": len(actions), "complete": complete, "attempts": trace}
        )
        if not complete:
            raise RuntimeError(f"Depth {depth} roster search incomplete; no claim of convergence")
        by_id.update({a.action_id: a for a in actions})
        memberships[depth] = {a.action_id for a in actions}
        update(f"Roster depth {depth}: {len(actions)} distinct legal routes")
    roots = list(by_id.values())
    if incumbent_id not in by_id:
        raise ValueError(
            "Current published action absent from reproduced search; cannot compare frozen inputs"
        )
    receipt["root_count"] = len(roots)
    update("Generating fresh selection worlds")
    worlds, weights, simulation = sample_worlds(
        rows,
        events,
        seeds=SELECTION_SEEDS,
        samples=VALIDATION_SAMPLES,
        component_forecast_path=component_forecast_path,
    )
    receipt["selection_simulation"] = simulation
    base_metrics, _ = score(roots, worlds, events)
    event_rows = {int(r["element"]): r for r in rows if int(r["event_number"]) == events[0]}
    from .allocation_research import subset_metrics

    receipt["depth_convergence"] = []
    for depth, ids in memberships.items():
        result = synthesize_weekly_decision(
            [a for a in roots if a.action_id in ids],
            subset_metrics(base_metrics, ids),
            scenario_weights=weights,
            event_rows=event_rows,
        )
        receipt["depth_convergence"].append(
            {
                "depth": depth,
                "selected": result["selected_action_id"],
                "tradeoff": result["objective_tradeoff"],
            }
        )
    frontiers = {}
    for i, root in enumerate(roots):
        frontier = [
            configuration_frontier(root.selected_player_ids, event, worlds, rules)
            for event in events
        ]
        frontiers[root.action_id] = frontier
        receipt["configurations"].append(
            {
                "root_action_id": root.action_id,
                "events": [
                    {k: v for k, v in f.items() if k not in ("means", "configurations")}
                    for f in frontier
                ],
            }
        )
        update(f"Exact configurations: {i + 1}/{len(roots)} rosters, all {len(events)} events")
    constants = {r.action_id: r.terminal_transfer_value - r.incremental_points_cost for r in roots}
    reference = np.max(
        [
            sum(0.88**i * f["means"].max(axis=0) for i, f in enumerate(frontiers[r.action_id]))
            + constants[r.action_id]
            for r in roots
        ],
        axis=0,
    )
    options = list(roots)
    for root in roots:
        fs = frontiers[root.action_id]
        choices = [
            joint_configuration(
                fs,
                weights=list(weights.values()),
                reference=reference,
                constant=constants[root.action_id],
            )
        ]
        for objective in (np.asarray(list(weights.values())), *np.eye(3)):
            choices.append([int(np.argmax(f["means"] @ objective)) for f in fs])
        options.extend(
            configured_action(root, choice, fs, state, rows, rules, events) for choice in choices
        )
    options = list({a.action_id: a for a in options}.values())
    # All roll configurations are scored fairly. Choose one roll comparator on
    # selection data, then freeze it for both holdouts; no retrospective relabel.
    initial_roll = next(r for r in roots if r.route_type == "roll")
    roll_options = [
        a
        for a in options
        if a.action_id == initial_roll.action_id or a.parent_action_id == initial_roll.action_id
    ]
    roll_metrics, _ = score(roll_options, worlds, events)
    roll_best = synthesize_weekly_decision(
        roll_options, roll_metrics, scenario_weights=weights, event_rows=event_rows
    )["selected_action_id"]
    options = [
        replace(a, route_type="roll")
        if a.action_id == roll_best
        else replace(a, route_type="configuration_roll")
        if a.route_type == "roll"
        else a
        for a in options
    ]
    metrics, _ = score(options, worlds, events)
    selection = synthesize_weekly_decision(
        options, metrics, scenario_weights=weights, event_rows=event_rows
    )
    selected_id = selection["selected_action_id"]
    receipt["selection"] = selection
    receipt["roll_comparator"] = roll_best
    # All pre-generated policies stay in both holdouts: no outcome-driven shortlist.
    receipt["frozen_policy_ids"] = [a.action_id for a in options]
    receipt["frozen_policy_sha256"] = hashlib.sha256(
        json.dumps([asdict(a) for a in options], sort_keys=True, default=str).encode()
    ).hexdigest()
    update(
        f"Selection frozen: {selected_id}, {len(options)} policies; starting two independent holdouts"
    )
    del worlds, frontiers
    for seeds in VALIDATION_SEEDS:
        holdout_worlds, holdout_weights, holdout_diagnostics = sample_worlds(
            rows,
            events,
            seeds=seeds,
            samples=VALIDATION_SAMPLES,
            component_forecast_path=component_forecast_path,
        )
        if weights != holdout_weights:
            raise RuntimeError("World weights changed during audit")
        holdout_metrics, holdout_totals = score(options, holdout_worlds, events)
        gate = validation_gate(
            {"event_rows": event_rows},
            options,
            holdout_metrics,
            holdout_totals,
            weights=weights,
            incumbent_id=incumbent_id,
            selected_id=selected_id,
        )
        receipt["holdouts"].append(
            {
                "seeds": seeds,
                "samples_per_family": VALIDATION_SAMPLES,
                "simulation": holdout_diagnostics,
                **gate,
            }
        )
        del holdout_worlds, holdout_totals
        update(
            f"Independent holdout {len(receipt['holdouts'])}/2: {'pass' if gate['passed'] else 'reject'}"
        )
    receipt["promotion_ready"] = all(r["passed"] for r in receipt["holdouts"])
    receipt["status"] = "completed"
    receipt["decision"] = "promote" if receipt["promotion_ready"] else "retain_incumbent"
    receipt["options"] = [asdict(a) for a in options]
    update("Deep audit complete; " + receipt["decision"])
    return receipt, options, metrics, weights
