"""Stateful, prefix-fitted residual-world policy experiment; never publishes.

This deliberately does not call the live three-world sampler: its goal models,
component calibration and market feeds are not historical prefix artifacts.
Historical results here cannot authorize production risk weights or chip timing.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .distribution_policy_audit import remap_score_shapes
from .horizon_decay_replay import _historical_rules, _initial_state, _load_inputs
from .market_transfer_replay import moving_block_mean_interval
from .rules import POSITIONS_PATH, RULES_PATH
from .score_shape import fit_shapes
from .tournament import (
    HISTORICAL_FIXTURES,
    POSITIONS,
    _simulate_player_outcomes,
    calibrate_residuals,
)
from .weekly_actions import _forecast_grid, generate_weekly_actions
from .weekly_continuation_replay import (
    ReplayConfig,
    _record,
    prefix_coefficients,
    prepare_deadline,
    reprice_state,
)
from .weekly_decision import synthesize_weekly_decision
from .weekly_policy_research import compose_plan, guard_future_transfers
from .weekly_simulation import evaluate_action_paths

ARMS = ("baseline", "premium_reinvestment", "guarded_recourse", "score_shape")
WEIGHTS = {"residual": 1.0}


@dataclass(frozen=True)
class SequentialConfig:
    seasons: tuple[str, ...] = ("2024-25", "2025-26")
    end_event: int = 10
    horizon: int = 5
    decay: float = 0.88
    samples: int = 10_000
    solver_seconds: float = 5.0
    seed: int = 202610217

    def validate(self):
        ReplayConfig(seasons=self.seasons, end_event=self.end_event, horizon=self.horizon,
                     decay=self.decay, solver_seconds=self.solver_seconds).validate()
        if self.samples < 1_000 or self.samples > 100_000 or self.seed < 0:
            raise ValueError("Invalid sequential simulation sample/seed bounds")


def fit_prefix(inputs, season, historical_fixtures):
    """All empirical outcome fitting ends before the evaluated season."""
    training = []
    for forecast in inputs["forecasts"]:
        if str(forecast["season"]) >= season:
            continue
        key = (forecast["season"], int(forecast["event_number"]), int(forecast["element"]))
        feature = inputs["feature_by_key"][key]
        training.append({**forecast, "target_minutes": feature["target_minutes"],
                         "fixture_count": feature["fixture_count"]})
    fixtures = [r for r in historical_fixtures if str(r["season"]) < season]
    residual = calibrate_residuals(rows=training, fixture_rows=fixtures)
    shapes = fit_shapes(training, before_season=season)
    return residual, shapes


def origin_simulation_rows(rows):
    """Do not carry a current-GW conditional mean into a different fixture week."""
    result = []
    if any(k.startswith(("target_", "realized_")) for r in rows for k in r):
        raise ValueError("Historical labels cannot enter policy simulation")
    for row in rows:
        probability = float(row["p_play"]) if row["fixture_count"] else 0.0
        mean = float(row["expected_points"]) if row["fixture_count"] else 0.0
        if not math.isfinite(mean) or not 0 <= probability <= 1 or (not probability and mean):
            raise ValueError("Incoherent historical appearance/points forecast")
        # This opening-window replay has no validated multi-fixture residual
        # sampler. Do not silently treat a double as one normal score draw.
        if row["fixture_count"] > 1:
            raise ValueError("Double-gameweek simulation is outside this isolated replay")
        result.append({**row, "p_play": probability, "expected_points": mean,
                       "robust_points": mean,
                       "conditional_points_if_playing": mean / probability if probability else 0})
    return result


def deadline_world(rows, fixtures, calibration, *, events, samples, seed):
    by_player, meta = _forecast_grid(rows, events)
    fixture_map = {e: [] for e in events}
    for fixture in fixtures:
        event = fixture.get("event")
        if event is not None and int(event) in fixture_map:
            fixture_map[int(event)].append((int(fixture["team_h"]), int(fixture["team_a"])))
    ids = sorted(by_player)
    points, played = _simulate_player_outcomes(
        ids, events, by_player, calibration, samples, seed, fixture_map=fixture_map,
        # Today's positional shrinkage was selected after these seasons. Unit
        # scale is the explicitly shared, untuned historical ablation instead.
        residual_scales={position: 1.0 for position in POSITIONS},
    )
    return {"player_ids": ids, "player_meta": meta, "points": points, "played": played}


def search(state, rows, rules, events, config, curve, **constraints):
    trace = []
    actions = generate_weekly_actions(
        state, rows, rules, events=events, score_field="expected_points",
        horizon_decay=config.decay, alternatives_per_transfer_count=1,
        max_total_transfers=2, max_paid_transfers=2,
        terminal_free_transfer_curve=curve, protect_role_sale_routes=False,
        solver_time_limit_seconds=config.solver_seconds, search_diagnostics=trace,
        **constraints,
    )
    if any(t["status"] == "unresolved" for t in trace):
        raise RuntimeError(f"Unresolved historical candidate solve: {trace}")
    if not constraints and not any(a.route_type == "roll" for a in actions):
        raise RuntimeError("Historical search requires a solved roll comparator")
    return actions, trace


def score(actions, world, events, decay):
    metrics, totals = evaluate_action_paths(actions, events=events, horizon_decay=decay, **world)
    return {"residual": metrics}, {"residual": totals}


def select_frozen(actions, selection, validation, rows, events, decay):
    """Freeze one choice; validation may reject to roll, never choose its own winner."""
    metrics, _ = score(actions, selection, events, decay)
    current = {int(r["element"]): r for r in rows if r["event_number"] == events[0]}
    choice = synthesize_weekly_decision(actions, metrics, scenario_weights=WEIGHTS,
                                        event_rows=current)
    chosen = next(a for a in actions if a.action_id == choice["selected_action_id"])
    roll = next(a for a in actions if a.route_type == "roll")
    holdout, _ = score(actions, validation, events, decay)
    check = synthesize_weekly_decision(actions, holdout, scenario_weights=WEIGHTS,
                                      event_rows=current)
    accepted = check["selection_audit"]["gates_by_action"][chosen.action_id]["passed"]
    evidence = next(m for m in holdout["residual"] if m.action_id == chosen.action_id)
    if chosen != roll:
        accepted = accepted and evidence.delta_to_roll_95ci_low > 0
    return chosen if accepted else roll, {
        "selection_choice": chosen.action_id, "validation_accepted": accepted,
        "validation_delta_to_roll": evidence.mean_delta_to_roll,
        "validation_mc95_low": evidence.delta_to_roll_95ci_low,
        "fallback": None if accepted else roll.action_id,
    }


def expanded_candidates(state, actions, rows, rules, events, config, curve):
    expanded = {a.action_id: a for a in actions}
    audit = []
    holdings = sorted((h for h in state.squad if h.position != "GK"),
                      key=lambda h: (-h.selling_price, h.player_id))[:2]
    for holding in holdings:
        candidates, trace = search(
            state, rows, rules, events, config, curve,
            required_outgoing_player_ids=(holding.player_id,),
        )
        expanded.update({a.action_id: a for a in candidates})
        audit.append({"required_sale": holding.player_id, "candidates": len(candidates),
                      "search": trace})
    return list(expanded.values()), audit


def recourse_choice(actions, rows, rules, events, config, curve, selection, validation):
    """Exact root state, ordinary next-week actions, then execute only the root."""
    plans, branches = [], {}
    for root in actions:
        children, _ = search(root.outcome.next_manager,
                             [r for r in rows if r["event_number"] in events[1:]],
                             rules, events[1:], config, curve)
        hold = next(a for a in children if a.route_type == "roll")
        best = min(children, key=lambda a: (-a.decision_utility, a.action_id))
        for child in (hold,) if best == hold else (hold, best):
            plan = compose_plan(root, child, rows, rules=rules, decay=config.decay)
            plans.append(plan)
            branches[plan.action_id] = {
                "no_future_transfer": not child.action.transfers,
                "next_incremental_points_cost": child.incremental_points_cost,
            }
    combined = [*actions, *plans]
    metrics, totals = score(combined, selection, events, config.decay)
    index = {a.action_id: i for i, a in enumerate(combined)}
    frontier, guard_audit = guard_future_transfers(plans, branches, metrics, totals, index, WEIGHTS)
    roll_id = next(a.action_id for a in actions if a.route_type == "roll")
    frozen_frontier = [replace(p, route_type="roll" if p.parent_action_id == roll_id
                               else p.route_type.removeprefix("planned_")) for p in frontier]
    winner, audit = select_frozen(frozen_frontier, selection, validation, rows, events, config.decay)
    # Recheck the *frozen* future branch against its own future hold on fresh
    # paths. A failed imagined continuation cannot justify today's action.
    vm, vt = score(combined, validation, events, config.decay)
    _, validation_guards = guard_future_transfers(plans, branches, vm, vt, index, WEIGHTS)
    future_pass = next(g["passed"] for g in validation_guards if g["plan_id"] == winner.action_id)
    if future_pass:
        root = next(a for a in actions if a.action_id == winner.parent_action_id)
    else:
        root, _ = select_frozen(actions, selection, validation, rows, events, config.decay)
    return root, {**audit, "future_guard_passed": future_pass,
                  "selection_future_guards": guard_audit,
                  "validation_future_guards": validation_guards,
                  "plan_id": winner.action_id, "executed_root_id": root.action_id}


def paired_season(inputs, historical_fixtures, season, config, progress=None):
    coefficients, training_seasons = prefix_coefficients(inputs, season)
    residual, shapes = fit_prefix(inputs, season, historical_fixtures)
    rules = _historical_rules(season)
    curve = {i: 0.0 for i in range(rules.max_free_transfers + 1)}
    records, states = {a: [] for a in ARMS}, {}
    shape_audits = []
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
            fixtures = inputs["fixture_by_snapshot"][(season, snapshot["snapshot_event"])]
            seed = config.seed + int(season[:4]) * 1000 + event * 10
            selection, validation = [deadline_world(rows, fixtures, residual, events=events,
                                                    samples=config.samples, seed=seed + i)
                                     for i in (0, 1)]
            transformed = []
            for world, offset in ((selection, 2), (validation, 3)):
                changed, audit = remap_score_shapes(world, rows, shapes, events=events,
                                                    seed=seed + offset)
                transformed.append(changed)
                shape_audits.append({"event": event, "draw": "selection" if offset == 2 else "validation",
                                     **audit})
            searches = {}
            for arm in ARMS:
                state = reprice_state(states[arm], current)
                if state not in searches:
                    searches[state] = search(state, rows, rules, events, config, curve)
                actions, trace = searches[state]
                extra = {}
                if arm == "premium_reinvestment":
                    actions, extra["capital_search"] = expanded_candidates(
                        state, actions, rows, rules, events, config, curve)
                if arm == "guarded_recourse":
                    winner, diagnostic = recourse_choice(actions, rows, rules, events, config,
                                                         curve, selection, validation)
                else:
                    sw, vw = transformed if arm == "score_shape" else (selection, validation)
                    winner, diagnostic = select_frozen(actions, sw, vw, rows, events, config.decay)
                record, next_state = _record(state, winner, None, outcomes, snapshot, rows, trace,
                                             {**diagnostic, **extra})
                records[arm].append(record)
                states[arm] = next_state
                if progress:
                    progress({"season": season, "event": event, "arm": arm,
                              "net_points": sum(r["net_points"] for r in records[arm]),
                              "completed_arm_events": sum(len(rs) for rs in records.values())})
        if progress:
            progress({"season": season, "event": event, "arm": "all_complete",
                      "totals": {a: sum(r["net_points"] for r in rs) for a, rs in records.items()}})
    paths = {a: {"events": rs, "net_points": sum(r["net_points"] for r in rs),
                 "points_cost": sum(r["points_cost"] for r in rs),
                 "transfers": sum(len(r["transfers"]) for r in rs)} for a, rs in records.items()}
    comparisons = {}
    for arm in ARMS[1:]:
        deltas = [a["net_points"] - b["net_points"]
                  for a, b in zip(records[arm][1:], records["baseline"][1:], strict=True)]
        comparisons[arm] = {
            "net_points_delta": sum(deltas), "event_deltas": deltas,
            "mean_delta_block_interval": moving_block_mean_interval(
                deltas, block_length=min(4, len(deltas)), samples=5000, seed=49019),
        }
    return {"season": season, "training_seasons": training_seasons,
            "fixture_coefficients": coefficients, "residual_training_rows": residual.rows,
            "terminal_curve": curve, "rules": asdict(rules), "shape_audits": shape_audits,
            "paths": paths, "comparisons": comparisons}


def run_replay(output: Path, config: SequentialConfig | None = None, progress=None):
    config = config or SequentialConfig()
    config.validate()
    if output.exists():
        raise FileExistsError("Historical experiment receipts cannot be overwritten")
    inputs = _load_inputs()
    inputs["paths"]["residual_training_fixtures"] = HISTORICAL_FIXTURES
    inputs["paths"].update(rules=RULES_PATH, positions=POSITIONS_PATH)
    fixtures = pq.read_table(HISTORICAL_FIXTURES).to_pylist()
    code = {str(p): sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    script = Path(__file__).resolve().parents[2] / "scripts" / "replay_sequential_policies.py"
    code[str(script)] = sha256_file(script)
    sources = {str(p): sha256_file(p) for p in inputs["paths"].values()}
    payload = asdict(config)
    result = {
        "version": "sequential_residual_policy_replay_v2", "status": "running",
        "created_at": datetime.now(UTC).isoformat(), "decision_authority": False,
        "config": payload, "config_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "effective_rules": {s: asdict(_historical_rules(s)) for s in config.seasons},
        "source_hashes": sources, "code_hashes": code, "arms": ARMS,
        "preregistered_screen": "Positive net-points delta in BOTH complete GW1-10 seasons; diagnostic only.",
        "limitations": [
            "Residual world only: NOT a matched full production three-world replay.",
            "Unit residual scales and zero FT terminal value in every arm; no test-season tuning.",
            "Historical OOF means and dated fixtures; future horizons reconstructed at each origin.",
            "Only ordinary transfers; excludes chip timing, full configuration search and DGWs.",
            "One optimal scalar candidate per transfer count, plus specified premium-sale routes.",
            "Replans every deadline but next-deadline branches use flat prices and origin forecasts.",
            "Both recent seasons have been inspected in other research: not pristine holdouts.",
            "Monte Carlo validation is model-conditional; it does not prove forecast calibration.",
            "Risk weights cannot be identified with one world and are not tested here.",
        ], "folds": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def checkpoint(item=None):
        if item is not None:
            result["progress"] = item
        result["elapsed_seconds"] = time.monotonic() - started
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        temporary.replace(output)
        if item is not None and progress:
            progress(item)

    checkpoint()  # Freeze config, seeds and inputs before scoring the first fold.
    try:
        for season in config.seasons:
            result["folds"].append(paired_season(inputs, fixtures, season, config, checkpoint))
            checkpoint()
        if any(sha256_file(Path(p)) != digest for p, digest in {**sources, **code}.items()):
            raise RuntimeError("Replay inputs or code changed while the experiment was running")
        complete = config.end_event == 10 and set(config.seasons) == {"2024-25", "2025-26"}
        result["historical_screens"] = {
            arm: complete and all(f["comparisons"][arm]["net_points_delta"] > 0 for f in result["folds"])
            for arm in ARMS[1:]
        }
        result.update(status="completed", promotion="retain_production_policy",
                      hashes_stable=True)
    except (Exception, KeyboardInterrupt) as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        checkpoint()
    return result
