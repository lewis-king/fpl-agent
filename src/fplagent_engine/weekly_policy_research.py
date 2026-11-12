"""Shared-world, stateful policy diagnostics. Nothing here can promote itself.

Plans are chosen from origin forecasts before any sampled outcomes are seen.
They are open-loop two-deadline projections, not clairvoyant stochastic policies.
The next real deadline must replan. Unpriced retained chip inventory is explicit.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, replace

import numpy as np

from .allocation_research import subset_metrics
from .rules import SquadRules
from .season_state import ChipType, apply_action
from .weekly_actions import (
    EvaluatedAction,
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from .weekly_simulation import combine_scenario_regret, evaluate_action_paths


def compose_plan(
    root: EvaluatedAction,
    child: EvaluatedAction,
    rows: list[dict],
    *,
    rules: SquadRules,
    decay=0.88,
):
    if root.outcome.next_manager is None or child.action.event != root.action.event + 1:
        raise ValueError("A continuation must start at the next deadline")
    if root.outcome.next_manager.event != child.action.event:
        raise ValueError("Incoherent next manager event")
    if apply_action(root.outcome.next_manager, child.action, rules) != child.outcome:
        raise ValueError("Future action was not generated from this root's exact manager state")
    current = {int(r["element"]): r for r in rows if int(r["event_number"]) == root.action.event}
    lineup = root.lineups[0].lineup
    score = root.score_field
    bench_weight = 1.0 if root.action.chip == ChipType.BENCH_BOOST else 0.08
    captain_copies = 2 if root.action.chip == ChipType.TRIPLE_CAPTAIN else 1
    current_value = sum(float(current[p][score]) for p in lineup.starters)
    current_value += captain_copies * float(current[lineup.captain][score])
    current_value += bench_weight * sum(float(current[p][score]) for p in lineup.bench_order)
    gross = current_value + decay * child.gross_horizon_utility
    future_costs = ((child.action.event, child.incremental_points_cost), *child.future_points_costs)
    chips = tuple(
        (child.action.event, child.action.chip) for _ in [0] if child.action.chip is not None
    )
    future_squads = child.event_squads or tuple(
        (lineup.event, child.selected_player_ids) for lineup in child.lineups
    )
    identity = f"{root.action_id}:{child.action_id}:{root.action.event}:{child.action.event}"
    return replace(
        root,
        action_id="P-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
        route_type="planned_" + root.route_type,
        parent_action_id=root.action_id,
        lineups=(root.lineups[0], *child.lineups),
        event_squads=((root.action.event, root.selected_player_ids), *future_squads),
        future_points_costs=future_costs,
        planned_chips=(*chips, *child.planned_chips),
        terminal_free_transfers=child.terminal_free_transfers,
        terminal_transfer_value=decay * child.terminal_transfer_value,
        gross_horizon_utility=gross,
        decision_utility=gross
        - root.incremental_points_cost
        - sum(decay ** (event - root.action.event) * cost for event, cost in future_costs)
        + decay * child.terminal_transfer_value,
    )


def build_policy_plans(
    ordinary: list[EvaluatedAction],
    chip_roots: list[EvaluatedAction],
    rows: list[dict],
    rules: SquadRules,
    *,
    events: tuple[int, ...],
    selected_id: str,
    terminal_curve: dict[int, float] | None = None,
    maximum_ordinary_roots: int = 4,
    time_budget: float = 40.0,
    solver_seconds: float = 2.0,
) -> tuple[list[EvaluatedAction], dict]:
    if len(events) < 2:
        return [], {"status": "no_future_deadline", "decision_authority": False}
    if maximum_ordinary_roots < 2 or time_budget <= 0 or solver_seconds <= 0:
        raise ValueError("Invalid policy-research bounds")
    if any(k.startswith(("target_", "realized_")) for r in rows for k in r):
        raise ValueError("Outcomes are forbidden in policy planning")
    by_id = {a.action_id: a for a in ordinary}
    roll = next(a for a in ordinary if a.route_type == "roll")
    root_ids = list(dict.fromkeys([selected_id, roll.action_id, *by_id]))[:maximum_ordinary_roots]
    roots = [by_id[action_id] for action_id in root_ids]
    for chip in ChipType:
        candidates = [a for a in chip_roots if a.action.chip == chip]
        if candidates:
            roots.append(
                min(
                    candidates,
                    key=lambda a: (
                        -a.gross_horizon_utility + a.incremental_points_cost,
                        a.action_id,
                    ),
                )
            )
    started = time.monotonic()
    plans, branches, failures = [], [], []
    future_rows = [dict(r) for r in rows if int(r["event_number"]) in events[1:]]
    for root in roots:
        remaining = time_budget - (time.monotonic() - started)
        if remaining <= 0:
            failures.append({"root": root.action_id, "reason": "total budget exhausted"})
            break
        next_state = root.outcome.next_manager
        if next_state is None or next_state.event != events[1]:
            raise ValueError("Root has no coherent future state")
        trace: list[dict] = []
        limit = min(solver_seconds, remaining / 6)
        children = generate_weekly_actions(
            next_state,
            future_rows,
            rules,
            events=events[1:],
            score_field=root.score_field,
            max_total_transfers=2,
            max_paid_transfers=1,
            alternatives_per_transfer_count=1,
            terminal_free_transfer_curve=terminal_curve,
            protect_role_sale_routes=False,
            solver_time_limit_seconds=limit,
            search_diagnostics=trace,
        )
        team_children = generate_team_chip_shadow_actions(
            next_state, children, future_rows, rules, events=events[1:]
        )
        squad_children = generate_squad_chip_shadow_actions(
            next_state,
            future_rows,
            rules,
            events=events[1:],
            score_field=root.score_field,
            alternatives_per_chip=1,
            terminal_free_transfer_curve=terminal_curve,
            solver_time_limit_seconds=limit,
            search_diagnostics=trace,
        )
        if any(t["status"] == "unresolved" for t in trace) or not any(
            a.route_type == "roll" for a in children
        ):
            failures.append(
                {"root": root.action_id, "reason": "incomplete child search", "trace": trace}
            )
            continue
        # Retain a frontier over future chip inventory. Never collapse different
        # remaining chip sets to a single falsely valued scalar winner.
        chosen_children = []
        for chip in (None, *ChipType):
            group = [
                a for a in (*children, *team_children, *squad_children) if a.action.chip == chip
            ]
            if not group:
                continue
            child = min(
                group,
                key=lambda a: (
                    -(
                        a.gross_horizon_utility
                        - a.incremental_points_cost
                        + a.terminal_transfer_value
                    ),
                    a.action_id,
                ),
            )
            chosen_children.append(child)
            # A future hit must beat doing nothing at that SAME future state,
            # not just look attractive relative to an unrelated present move.
            if chip is None:
                future_roll = next(a for a in children if a.route_type == "roll")
                if child.action_id != future_roll.action_id:
                    chosen_children.append(future_roll)
        for child in chosen_children:
            chip = child.action.chip
            plan = compose_plan(root, child, rows, rules=rules)
            plans.append(plan)
            branches.append(
                {
                    "plan_id": plan.action_id,
                    "root_action_id": root.action_id,
                    "current_chip": root.action.chip.value if root.action.chip else None,
                    "next_chip": chip.value if chip else None,
                    "next_action_id": child.action_id,
                    "next_incremental_points_cost": child.incremental_points_cost,
                    "no_future_transfer": not child.action.transfers and chip is None,
                    "next_transfers": [
                        {
                            "out": t.outgoing_player_id,
                            "in": t.incoming.player_id,
                            "price": t.incoming.current_price,
                        }
                        for t in child.action.transfers
                    ],
                    "next_bank_before": next_state.bank,
                    "next_free_transfers_before": next_state.free_transfers,
                    "bank_after_next": child.outcome.gameweek.bank,
                    "free_transfers_after_next": child.next_free_transfers,
                    "chips_after_next": [asdict(c) for c in child.outcome.next_manager.chips]
                    if child.outcome.next_manager
                    else [],
                    "next_selected": list(child.selected_player_ids),
                    "event_squads": dict(plan.event_squads),
                    "event_lineups": [asdict(l) for l in plan.lineups],
                    "future_points_costs": list(plan.future_points_costs),
                    "terminal_ft_value": plan.terminal_transfer_value,
                    "search_trace": trace,
                }
            )
    complete = not failures and len({b["root_action_id"] for b in branches}) == len(roots)
    return plans, {
        "version": "shared_world_policy_plans_v2",
        "decision_authority": False,
        "status": "ready_diagnostic" if complete else "incomplete_diagnostic",
        "complete_requested_roots": complete,
        "root_ids": [r.action_id for r in roots],
        "omitted_ordinary_roots": len(ordinary) - len(root_ids),
        "branches": branches,
        "failures": failures,
        "elapsed_seconds": time.monotonic() - started,
        "assumptions": [
            "Origin forecasts and flat prices; no sampled future outcome is visible to a choice.",
            "One screened future route per chip inventory plus an exact no-transfer continuation per root.",
            "Future lineup and transfer plans are projections, to be reconsidered next deadline.",
            "Residual chip inventory is not fully priced; raw WC/FH gains cannot authorize spending.",
        ],
    }


def guard_future_transfers(plans, branches, metrics, totals, index, weights):
    """Apply ordinary after-cost transfer gates at each projected next state.

    This is still selection-sample research, not prospective timing authority.
    Always retain the no-future-transfer route; do not equate a rejected hit with
    an impossible first action or discard that first action altogether.
    """
    roots = sorted({p.parent_action_id for p in plans})
    central = max(weights, key=weights.get)
    chosen, audit = [], []
    for root in roots:
        members = [p for p in plans if p.parent_action_id == root]
        holds = [p for p in members if branches[p.action_id]["no_future_transfer"]]
        if len(holds) != 1:
            raise ValueError("Every root requires exactly one no-transfer future comparator")
        hold = holds[0]
        admissible = []
        for plan in members:
            delta = {
                name: values[:, index[plan.action_id]] - values[:, index[hold.action_id]]
                for name, values in totals.items()
            }
            central_delta = delta[central]
            if len(central_delta) < 2:
                raise ValueError("Future-transfer comparison needs repeated paths")
            means = {name: float(values.mean()) for name, values in delta.items()}
            weighted = sum(weights[name] * means[name] for name in weights)
            lower = float(central_delta.mean() - 1.96 * central_delta.std(ddof=1)
                          / np.sqrt(len(central_delta)))
            paid = branches[plan.action_id]["next_incremental_points_cost"] > 0
            checks = {
                "positive_weighted_gain": weighted > 0,
                "no_material_world_reversal": min(means.values()) >= -0.25,
                "central_paired_lower_bound": lower > -0.05,
            }
            if paid:
                checks.update({
                    "paid_positive_every_world": min(means.values()) > 0,
                    "paid_lower_bound_positive": lower > 0,
                    "paid_beats_future_roll": float(np.mean(central_delta > 0)) >= 0.55,
                })
            passed = plan == hold or all(checks.values())
            if passed:
                admissible.append(plan)
            audit.append({"plan_id": plan.action_id, "root_action_id": root,
                          "comparator": hold.action_id, "passed": passed,
                          "is_hold": plan == hold, "checks": checks,
                          "weighted_delta": weighted, "world_deltas": means,
                          "central_lower_bound": lower})
        rebased = subset_metrics(metrics, {p.action_id for p in admissible})
        ranking = combine_scenario_regret(rebased, scenario_weights=weights)
        chosen.append(next(p for p in admissible if p.action_id == ranking[0]["action_id"]))
    return chosen, audit


def score_policy_plans(
    ordinary: list[EvaluatedAction],
    plans: list[EvaluatedAction],
    receipt: dict,
    worlds: dict[str, dict],
    weights: dict[str, float],
    *,
    events: tuple[int, ...],
    selected_id: str,
    event_rows: dict[int, dict],
) -> dict:
    from .weekly_decision import synthesize_weekly_decision

    if not plans or not receipt.get("complete_requested_roots"):
        return receipt
    if set(worlds) != set(weights):
        raise ValueError("Policy comparison must use every production world")
    combined = [*ordinary, *plans]
    metrics, totals = {}, {}
    for name, world in worlds.items():
        metrics[name], totals[name] = evaluate_action_paths(combined, events=events, **world)
    index = {a.action_id: i for i, a in enumerate(combined)}
    branches = {b["plan_id"]: dict(b) for b in receipt["branches"]}
    for action in plans:
        row = branches[action.action_id]
        row["scenario_delta_to_published_fixed_plan"] = {
            name: float((values[:, index[action.action_id]] - values[:, index[selected_id]]).mean())
            for name, values in totals.items()
        }
        row["weighted_raw_delta"] = sum(
            weights[name] * delta
            for name, delta in row["scenario_delta_to_published_fixed_plan"].items()
        )
    ordinary_plans = [a for a in plans if a.action.chip is None and not a.planned_chips]
    ordinary_plans, future_gate_audit = guard_future_transfers(
        ordinary_plans, branches, metrics, totals, index, weights
    )
    rolls = {a.action_id for a in ordinary if a.route_type == "roll"}
    planning_actions = [
        replace(
            a,
            route_type="roll"
            if a.parent_action_id in rolls
            else a.route_type.removeprefix("planned_"),
        )
        for a in ordinary_plans
    ]
    planning_metrics = {}
    for name, world in worlds.items():
        planning_metrics[name], _ = evaluate_action_paths(planning_actions, events=events, **world)
    # Exactly the production regret weights and first-action promotion checks;
    # historical lift and the future-hit policy are NOT inferred from this call.
    choice = synthesize_weekly_decision(
        planning_actions, planning_metrics, scenario_weights=weights, event_rows=event_rows
    )
    winner = next(a for a in planning_actions if a.action_id == choice["selected_action_id"])
    return {
        **receipt,
        "branches": list(branches.values()),
        "same_production_worlds": True,
        "simulation_counts": {
            name: int(world["points"].shape[0]) for name, world in worlds.items()
        },
        "future_transfer_gates": future_gate_audit,
        "ordinary_continuation": {
            "selected_plan_id": winner.action_id,
            "selected_first_action_id": winner.parent_action_id,
            "published_first_action_id": selected_id,
            "first_action_changed": winner.parent_action_id != selected_id,
            "selection_audit": choice["selection_audit"],
            "promotion_gate": choice["promotion_gate"],
            "decision_authority": False,
            "missing_evidence": "Production-matched historical sequential replay and prospective multiweek lift; future-hit/option-value validation.",
        },
        "joint_chips": {
            "highest_raw_upside_plan_id": max(
                branches, key=lambda key: branches[key]["weighted_raw_delta"]
            ),
            "operational_recommendation": None,
            "decision_authority": False,
            "retained_inventory_status": "unpriced_unvalidated",
            "interpretation": "Frontier of legal chip sequences and exact state restoration, not a chip timing recommendation.",
        },
    }
