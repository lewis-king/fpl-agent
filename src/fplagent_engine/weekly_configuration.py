"""Production fixed-roster XI/bench/C/VC refinement, with untouched validation.

This does not activate the rejected wider-roster research selector. Transfer
proposals, forecasts, risk weights and chip authority are unchanged. All legal
configurations of each proposed event squad are searched on selection worlds;
the final route is frozen before an independent holdout can accept or reject it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from fplagent_data.http import sha256_file

from .exact_configuration import configuration_frontier, fused_score_candidates
from .rules import validate_lineup
from .season_state import ChipType, Lineup, apply_action
from .weekly_actions import EvaluatedAction, EventLineup
from .weekly_deep_search import joint_configuration, sample_worlds
from .weekly_simulation import evaluate_action_paths

VERSION = "weekly_configuration_v1"
SELECTION_MIN_SAMPLES = 50_000
VALIDATION_SEEDS = (2026101601, 2026101602)
VALIDATION_SAMPLES = 100_000
MAX_WORLD_LOSS = 0.05
HORIZON_DECAY = 0.88


def same_lineup(left, right):
    # Starting-player display order has no scoring significance.
    return (
        set(left.starters) == set(right.starters)
        and left.bench_order == right.bench_order
        and left.captain == right.captain
        and left.vice_captain == right.vice_captain
    )


def configuration_identity(actions: list[EvaluatedAction]) -> str:
    payload = [
        {
            "action_id": a.action_id,
            "squad": a.selected_player_ids,
            "event_squads": a.event_squads,
            "action": asdict(a.action),
            "lineups": [asdict(item) for item in a.lineups],
            "planned_chips": a.planned_chips,
        }
        for a in actions
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _chip_events(action):
    chips = dict(action.planned_chips)
    if len(chips) != len(action.planned_chips):
        raise ValueError("Duplicate planned chip event")
    if action.action.chip is not None:
        if action.action.event in chips:
            raise ValueError("Current and planned chips collide")
        chips[action.action.event] = action.action.chip
    return chips


def _replace_configuration(root, choices, frontiers, state, rows, rules, events):
    grid = {(int(r["event_number"]), int(r["element"])): r for r in rows}
    squads = dict(root.event_squads)
    lineups = []
    gross = 0.0
    opportunities = {ChipType.BENCH_BOOST: [], ChipType.TRIPLE_CAPTAIN: []}
    for event, choice, frontier in zip(events, choices, frontiers, strict=True):
        xi, bench, captain, vice = frontier["configurations"][choice]
        lineup = Lineup(tuple(sorted(xi)), tuple(bench), captain, vice)
        selected = squads.get(event, root.selected_player_ids)
        squad_rows = [{**grid[(event, p)], "element": p} for p in selected]
        validate_lineup(
            squad_rows,
            lineup.starters,
            lineup.bench_order,
            lineup.captain,
            lineup.vice_captain,
            rules,
        )
        points = sum(float(grid[(event, p)][root.score_field]) for p in xi)
        points += float(grid[(event, captain)][root.score_field])
        formation = "-".join(
            str(sum(grid[(event, p)]["position"] == pos for p in xi))
            for pos in ("DEF", "MID", "FWD")
        )
        lineups.append(EventLineup(event, lineup, formation, points))
        bench_points = sum(float(grid[(event, p)][root.score_field]) for p in bench)
        gross += HORIZON_DECAY ** (event - events[0]) * (points + 0.08 * bench_points)
        opportunities[ChipType.BENCH_BOOST].append(0.92 * bench_points)
        opportunities[ChipType.TRIPLE_CAPTAIN].append(
            float(grid[(event, captain)][root.score_field])
        )
    bundle = replace(root.action, lineup=lineups[0].lineup)
    outcome = apply_action(state, bundle, rules)
    uplift, retained = root.chip_current_proxy_uplift, root.retained_chip_proxy_value
    if bundle.chip in opportunities:
        values = opportunities[bundle.chip]
        uplift = values[0]
        half_end = 19 if events[0] <= 19 else 38
        retained = max(
            (v for e, v in zip(events[1:], values[1:], strict=True) if e <= half_end), default=0.0
        )
        gross += uplift
    # Keep route identities and chip-parent links. Receipt hashes bind the
    # configurations; these existing IDs have always identified roster routes.
    return replace(
        root,
        action=bundle,
        outcome=outcome,
        lineups=tuple(lineups),
        gross_horizon_utility=gross,
        decision_utility=gross
        - root.incremental_points_cost
        + root.terminal_transfer_value
        - retained,
        chip_current_proxy_uplift=uplift,
        retained_chip_proxy_value=retained,
    )


def optimise_configurations(
    actions,
    state,
    rows,
    rules,
    worlds,
    weights,
    *,
    events,
    progress: Callable[[str], None] | None = None,
    worst_case_weight: float = 0.25,
    frontier_cache: dict | None = None,
):
    """Search every route fairly, including roll, BB/TC and restored FH squads.

    A fixed roster's joint horizon uses the existing 0.25 worst-world regret
    objective. Its reference is its own attainable frontier, never an unrelated
    unsafe or rejected transfer/chip route. Final route comparison retains the
    existing admissible-only reference and safety gates.
    """
    if (
        set(weights) != set(worlds)
        or not math.isclose(sum(weights.values()), 1.0)
        or any(not math.isfinite(w) or w < 0 for w in weights.values())
    ):
        raise ValueError("Configuration worlds and normalised weights must match")
    if events != tuple(range(state.event, state.event + len(events))) or not events:
        raise ValueError("Configuration horizon must start at the manager's actionable event")
    ordered_worlds = {name: {**worlds[name], "events": events} for name in weights}
    # Worlds must remain immutable while cached. Scope by array identity and
    # world ordering: a new generation or a reordered comparison cannot borrow
    # an old frontier, while risk-grid comparisons can reuse the same worlds.
    cache: dict[tuple, dict] = {} if frontier_cache is None else frontier_cache
    world_scope = (events, repr(rules), tuple(
        (name, id(worlds[name]["points"]), id(worlds[name]["played"]),
         tuple(worlds[name]["player_ids"])) for name in weights))
    refined, evidence = [], []
    for index, root in enumerate(actions):
        if tuple(item.event for item in root.lineups) != events:
            raise ValueError("Candidate lineup horizon differs from configuration horizon")
        squads, chips = dict(root.event_squads), _chip_events(root)
        frontiers = []
        for event in events:
            selected = tuple(sorted(squads.get(event, root.selected_player_ids)))
            chip = chips.get(event)
            scoring_chip = chip if chip in {ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN} else None
            key = (world_scope, selected, event, scoring_chip)
            if key not in cache:
                cache[key] = configuration_frontier(
                    selected, event, ordered_worlds, rules, chip=scoring_chip
                )
            frontiers.append(cache[key])
        reference = sum(
            HORIZON_DECAY**i * frontier["means"].max(axis=0) for i, frontier in enumerate(frontiers)
        )
        choices = joint_configuration(
            frontiers,
            weights=list(weights.values()),
            reference=reference,
            constant=0.0,
            decay=HORIZON_DECAY,
            worst_case_weight=worst_case_weight,
        )
        configured = _replace_configuration(root, choices, frontiers, state, rows, rules, events)
        refined.append(configured)
        evidence.append(
            {
                "action_id": root.action_id,
                "changed_events": [
                    e
                    for e, old, new in zip(events, root.lineups, configured.lineups, strict=True)
                    if not same_lineup(old.lineup, new.lineup)
                ],
                "original_lineups": [asdict(item) for item in root.lineups],
                "selected_lineups": [asdict(item) for item in configured.lineups],
                "events": [
                    {k: v for k, v in f.items() if k not in {"means", "configurations"}}
                    for f in frontiers
                ],
            }
        )
        if progress:
            progress(f"Simulation lineups: {index + 1}/{len(actions)} routes configured")
    return refined, {
        "version": VERSION,
        "status": "selection_frozen",
        "scope": "unchanged roster candidates; exact fixed-roster XI, bench, C/VC for every horizon event",
        "objective": f"joint fixed-roster horizon: {1 - worst_case_weight:g} weighted mean regret + {worst_case_weight:g} worst-world regret",
        "worst_case_weight": worst_case_weight,
        "horizon_decay": HORIZON_DECAY,
        "scenario_weights": dict(weights),
        "candidate_count": len(actions),
        "unique_frontiers": len(cache),
        "possible_configurations": sum(f["possible_configurations"] for f in cache.values()),
        "selection_samples": {n: len(w["points"]) for n, w in worlds.items()},
        "original_configuration_sha256": configuration_identity(actions),
        "frozen_configuration_sha256": configuration_identity(refined),
        "candidates": evidence,
        "model_parameters_changed": False,
        "roster_search_expanded": False,
    }


def score_configurations(actions, worlds, *, events):
    metrics, totals = {}, {}
    for name, world in worlds.items():
        metrics[name], totals[name] = evaluate_action_paths(
            actions,
            events=events,
            score_candidates=fused_score_candidates,
            **{k: v for k, v in world.items() if k != "events"},
        )
    return metrics, totals


def paired_validation(original_totals, refined_totals, weights, index):
    """Paired Monte Carlo error, preserving raw/anchored component covariance.

    This quantifies integration noise, NOT forecast/model uncertainty. The
    residual family is independent; the two component worlds share samples.
    """
    deltas = {n: refined_totals[n][:, index] - original_totals[n][:, index] for n in weights}
    if any(len(d) < 2 or not np.isfinite(d).all() for d in deltas.values()):
        raise ValueError("Holdout comparisons need finite paired samples")
    if len(deltas["component_anchored"]) != len(deltas["component_raw"]):
        raise ValueError("Paired component worlds must share sample counts")
    residual = weights["residual"] * deltas["residual"]
    component = (
        weights["component_anchored"] * deltas["component_anchored"]
        + weights["component_raw"] * deltas["component_raw"]
    )
    mean = float(residual.mean() + component.mean())
    se = float(
        np.sqrt(residual.var(ddof=1) / len(residual) + component.var(ddof=1) / len(component))
    )
    return {
        "weighted_gain": mean,
        "monte_carlo_standard_error": se,
        "monte_carlo_95_low": mean - 1.96 * se,
        "monte_carlo_95_high": mean + 1.96 * se,
        "world_gains": {n: float(d.mean()) for n, d in deltas.items()},
        "interpretation": "Paired sampling uncertainty only; not model confidence or observed points lift.",
    }


def validate_configurations(
    originals,
    refined,
    rows,
    *,
    events,
    weights,
    selected_ids,
    component_forecast_path,
    selection_seeds,
    sampler=sample_worlds,
):
    """Validate the preselected ordinary/chip routes; never pick a holdout winner."""
    if set(selection_seeds) & set(VALIDATION_SEEDS):
        raise ValueError("Configuration selection and validation seeds overlap")
    if [a.action_id for a in originals] != [a.action_id for a in refined]:
        raise ValueError("Configuration refinement must preserve roster routes and ordering")
    frozen_hash = configuration_identity(refined)
    ids = list(dict.fromkeys(selected_ids))
    known = {a.action_id: i for i, a in enumerate(refined)}
    if not ids or not set(ids) <= set(known):
        raise ValueError("Frozen selection is missing from configuration candidates")
    worlds, holdout_weights, simulation = sampler(
        rows,
        events,
        seeds=VALIDATION_SEEDS,
        samples=VALIDATION_SAMPLES,
        component_forecast_path=component_forecast_path,
    )
    if weights != holdout_weights:
        raise ValueError("Configuration model weights changed before holdout")
    _, original_totals = score_configurations(originals, worlds, events=events)
    _, refined_totals = score_configurations(refined, worlds, events=events)
    comparisons = []
    for action_id in ids:
        index = known[action_id]
        same = all(
            same_lineup(a.lineup, b.lineup)
            for a, b in zip(originals[index].lineups, refined[index].lineups, strict=True)
        )
        paired = paired_validation(original_totals, refined_totals, weights, index)
        checks = {
            "positive_paired_gain_or_unchanged": same or paired["monte_carlo_95_low"] > 0.0,
            "no_material_model_world_loss": all(
                g >= -MAX_WORLD_LOSS for g in paired["world_gains"].values()
            ),
        }
        comparisons.append(
            {
                "action_id": action_id,
                "unchanged": same,
                **paired,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    if configuration_identity(refined) != frozen_hash:
        raise RuntimeError("Frozen configuration changed during validation")
    return {
        "passed": all(c["passed"] for c in comparisons),
        "selected_ids_frozen_before_holdout": ids,
        "frozen_configuration_sha256": frozen_hash,
        "seeds": list(VALIDATION_SEEDS),
        "samples_per_family": VALIDATION_SAMPLES,
        "maximum_world_loss": MAX_WORLD_LOSS,
        "comparisons": comparisons,
        "simulation": simulation,
        "holdout_reselection": False,
        "failure_policy": "retain original configurations and original selection; never substitute a holdout winner",
    }


def select_validated_configurations(
    actions,
    state,
    rows,
    rules,
    worlds,
    weights,
    metrics,
    totals,
    *,
    events,
    selector,
    component_forecast_path,
    selection_seeds,
    progress=None,
):
    """Production transaction: configure -> select -> freeze -> validate -> accept/fallback.

    The callback receives only selection samples, never holdout data. A failure
    restores the entire original decision, not a new winner picked on validation.
    """
    from .component_simulator import COMPONENT_BACKTEST_METRICS, GOAL_MODEL_FILE
    from .market_odds import (
        BETFAIR_CALIBRATION_RESULTS,
        CURRENT_MARKET_RATES,
        CURRENT_MARKET_RECEIPT,
    )

    source_paths = (
        Path(component_forecast_path),
        GOAL_MODEL_FILE,
        COMPONENT_BACKTEST_METRICS,
        CURRENT_MARKET_RATES,
        CURRENT_MARKET_RECEIPT,
        BETFAIR_CALIBRATION_RESULTS,
    )

    def source_hashes():
        return {str(p): sha256_file(p) if p.is_file() else None for p in source_paths}

    sources_before = source_hashes()
    original_result, original_base_metrics = selector(actions, metrics, totals)
    refined, audit = optimise_configurations(
        actions,
        state,
        rows,
        rules,
        worlds,
        weights,
        events=events,
        progress=progress,
    )
    refined_metrics, refined_totals = score_configurations(refined, worlds, events=events)
    result, base_metrics = selector(refined, refined_metrics, refined_totals)
    frozen_ids = [result["selected_action_id"]]
    if result["chip_strategy"].get("operational_recommendation") not in {None, "no_chip"}:
        frozen_ids.append(result["chip_strategy"]["recommended_action_id"])
    if progress:
        progress("Simulation lineups: selection frozen; checking independent holdout")
    validation = validate_configurations(
        actions,
        refined,
        rows,
        events=events,
        weights=weights,
        selected_ids=frozen_ids,
        component_forecast_path=component_forecast_path,
        selection_seeds=selection_seeds,
    )
    if source_hashes() != sources_before:
        raise RuntimeError(
            "Configuration evidence changed during selection/holdout; rerun one coherent generation"
        )
    audit["input_hashes"] = sources_before
    audit.update(
        validation=validation,
        selection_seeds=list(selection_seeds),
        original_selected_action_id=original_result["selected_action_id"],
        frozen_selected_action_id=result["selected_action_id"],
    )
    if validation["passed"]:
        actions, metrics, totals = refined, refined_metrics, refined_totals
        audit["status"] = "validated"
        audit["message"] = (
            "XI, bench and captaincy were simulation-optimised before route selection and "
            "the frozen selection passed independent validation. Small gains are close calls, "
            "not proof of a clear football advantage."
        )
    else:
        result, base_metrics = original_result, original_base_metrics
        audit["status"] = "retained_original"
        audit["message"] = (
            "Deeper lineup changes did not pass independent validation. The original "
            "configuration and selection were retained; no holdout winner was substituted."
        )
    audit["published_configuration_sha256"] = configuration_identity(actions)
    if progress:
        progress("Simulation lineups: " + audit["status"])
    return actions, metrics, totals, result, base_metrics, audit


def _squad_chip_execution_plan(result, chosen, rows):
    """Bind a Wildcard/Free Hit to its own exact squad, XI, bench and captaincy.

    A squad chip has no ordinary transfer parent: its transfers are the
    rebuild itself, at zero points cost.
    """
    strategy = result["chip_strategy"]
    chip = strategy["operational_recommendation"]
    if chosen.action.chip.value != chip:
        raise ValueError("Squad-chip execution plan does not match its recommendation")
    shadow = next(
        (
            row
            for row in (result.get("squad_chip_shadow") or {}).get("candidates", [])
            if row.get("action_id") == chosen.action_id
        ),
        None,
    )
    if shadow is None:
        raise ValueError("Recommended squad chip is missing from the squad-chip shadow")
    if chosen.total_points_cost:
        raise ValueError("A squad-chip rebuild cannot carry a points hit")
    grid = {(int(r["event_number"]), int(r["element"])): r for r in rows}
    lineups = [
        {
            "event": item.event,
            "formation": item.formation,
            "projected_points": item.projected_points,
            "starter_player_ids": list(item.lineup.starters),
            "bench_player_ids": list(item.lineup.bench_order),
            "captain_player_id": item.lineup.captain,
            "vice_captain_player_id": item.lineup.vice_captain,
        }
        for item in chosen.lineups
    ]
    first = lineups[0]
    event = chosen.action.event
    return {
        "action_id": chosen.action_id,
        "route_type": chip,
        "transfers": list(shadow["transfers"]),
        "transfer_count": len(shadow["transfers"]),
        "incremental_points_cost": 0,
        "total_points_cost": 0,
        "next_free_transfers": chosen.next_free_transfers,
        "terminal_free_transfers": chosen.terminal_free_transfers,
        "decision_utility": chosen.decision_utility,
        "gross_horizon_utility": chosen.gross_horizon_utility,
        **{k: v for k, v in first.items() if k not in {"event", "projected_points"}},
        "configuration_action_id": chosen.action_id,
        "chip": chip,
        "event_lineups": lineups,
        "selected_player_ids": list(chosen.selected_player_ids),
        "captain_name": str(
            grid[(event, first["captain_player_id"])].get("player_name")
            or f"#{first['captain_player_id']}"
        ),
        "vice_captain_name": str(
            grid[(event, first["vice_captain_player_id"])].get("player_name")
            or f"#{first['vice_captain_player_id']}"
        ),
        "squad_chip_metrics": shadow.get("scenario_metrics"),
        "projection_basis": "scalar player forecast sum for the rebuilt squad; not a simulation mean",
        "comparison_basis": (
            "versus the best ordinary route in shared simulations; timing chosen by the "
            "full-half planner or the expiry rule"
        ),
    }


def execution_plan(result, actions, rows):
    """Bind a recommended BB/TC to its exact configured lineup and transfer route.

    The ordinary benchmark remains intact for audit. Clients must not combine
    its lineup with a chip whose configuration or transfer parent is different.
    """
    strategy = result["chip_strategy"]
    chip = strategy.get("operational_recommendation")
    if chip in {None, "no_chip"}:
        return None
    by_id = {a.action_id: a for a in actions}
    chosen = by_id[strategy["recommended_action_id"]]
    if chosen.action.chip in {ChipType.WILDCARD, ChipType.FREE_HIT}:
        return _squad_chip_execution_plan(result, chosen, rows)
    if chosen.action.chip not in {ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN}:
        raise ValueError("This release has no execution path for this chip")
    if chosen.action.chip.value != chip or chosen.parent_action_id not in by_id:
        raise ValueError("Chip execution plan does not match its ordinary transfer parent")
    parent = by_id[chosen.parent_action_id]
    if chosen.action.transfers != parent.action.transfers:
        raise ValueError("Chip execution transfers differ from its declared parent")
    summary = next(s for s in result["action_summaries"] if s["action_id"] == parent.action_id)
    grid = {(int(r["event_number"]), int(r["element"])): r for r in rows}
    lineups = []
    for item in chosen.lineups:
        points = item.projected_points
        if item.event == chosen.action.event:
            extra = item.lineup.bench_order if chip == "bench_boost" else (item.lineup.captain,)
            points += sum(float(grid[(item.event, p)][chosen.score_field]) for p in extra)
        lineups.append(
            {
                "event": item.event,
                "formation": item.formation,
                "projected_points": points,
                "starter_player_ids": list(item.lineup.starters),
                "bench_player_ids": list(item.lineup.bench_order),
                "captain_player_id": item.lineup.captain,
                "vice_captain_player_id": item.lineup.vice_captain,
            }
        )
    first = lineups[0]
    return {
        **summary,
        **{k: v for k, v in first.items() if k not in {"event", "projected_points"}},
        "configuration_action_id": chosen.action_id,
        "chip": chip,
        "event_lineups": lineups,
        "captain_name": str(
            grid[(chosen.action.event, first["captain_player_id"])].get("player_name")
            or f"#{first['captain_player_id']}"
        ),
        "vice_captain_name": str(
            grid[(chosen.action.event, first["vice_captain_player_id"])].get("player_name")
            or f"#{first['vice_captain_player_id']}"
        ),
        "projection_basis": "scalar player forecast sum with the selected chip; not a simulation mean",
        "comparison_basis": "ordinary transfer metrics exclude chip; joint chip value is recorded separately",
    }
