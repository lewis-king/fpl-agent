"""Matched-world candidate-access, bench allocation and objective sensitivity.

Constraints define questions to test, not squad preferences to deploy. Every
proposal is a legal current transfer action and competes on the same simulations.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace

import numpy as np

from .weekly_actions import generate_weekly_actions
from .weekly_simulation import evaluate_action_paths


def policy_identity(action):
    return json.dumps(
        [
            action.action_id,
            [
                (
                    l.event,
                    l.lineup.starters,
                    l.lineup.captain,
                    l.lineup.vice_captain,
                    l.lineup.bench_order,
                )
                for l in action.lineups
            ],
        ]
    )


def subset_metrics(metrics, action_ids):
    # Regret is relative to the best member of THIS candidate set. Keeping
    # regrets from an expanded set would change the original risk comparison.
    result = {}
    for name, values in metrics.items():
        selected = [m for m in values if m.action_id in action_ids]
        best = max(m.mean_net_points for m in selected)
        result[name] = [replace(m, scenario_regret=best - m.mean_net_points) for m in selected]
    return result


def allocation_audit(actions, rows, *, events, selected_id, metrics, weights):
    by_key = {(int(r["event_number"]), int(r["element"])): r for r in rows}
    lookup = {name: {m.action_id: m for m in ms} for name, ms in metrics.items()}
    output = []
    for action in actions:
        lineup = action.lineups[0].lineup
        bench = list(lineup.bench_order)
        reserve_use = {
            p: [l.event for l in action.lineups if p in l.lineup.starters] for p in bench
        }
        weighted = sum(
            weights[name] * lookup[name][action.action_id].mean_delta_to_roll for name in weights
        )
        output.append(
            {
                "action_id": action.action_id,
                "published": action.action_id == selected_id,
                "transfers": [
                    {"out": t.outgoing_player_id, "in": t.incoming.player_id}
                    for t in action.action.transfers
                ],
                "hit_cost": action.incremental_points_cost,
                "bank_after": action.outcome.gameweek.bank / 10,
                "next_free_transfers": action.next_free_transfers,
                "current_bench_cost": sum(
                    float(by_key[(events[0], p)]["market_price"]) for p in bench
                )
                / 10,
                "current_squad_market_value": sum(
                    float(by_key[(events[0], p)]["market_price"])
                    for p in action.selected_player_ids
                )
                / 10,
                "current_xi_plus_captain_xp": action.lineups[0].projected_points,
                "captain": lineup.captain,
                "bench": bench,
                "bench_future_starts": reserve_use,
                "bench_with_no_planned_starts": [p for p, uses in reserve_use.items() if not uses],
                "weighted_gain_to_roll": weighted,
                "worst_world_gain": min(
                    lookup[name][action.action_id].mean_delta_to_roll for name in weights
                ),
            }
        )
    return sorted(output, key=lambda r: -r["weighted_gain_to_roll"])


def run_allocation_research(
    state,
    actions,
    rows,
    rules,
    worlds,
    weights,
    *,
    events,
    selected_id,
    terminal_curve=None,
    seconds=24.0,
    proposals_out=None,
):
    from .weekly_decision import synthesize_weekly_decision

    if set(worlds) != set(weights):
        raise ValueError("Allocation comparison requires every production world")
    started = time.monotonic()
    current = {int(r["element"]): r for r in rows if int(r["event_number"]) == events[0]}
    # Joint legal solves can release capital from a healthy expensive holding
    # and improve another position. Price is a constraint, never a points bonus.
    # The top two sale values define bounded search coverage, not forced sales.
    premium_holdings = sorted(
        (h for h in state.squad if h.position != "GK"),
        key=lambda h: (-h.selling_price, h.player_id),
    )[:2]
    definitions = [
        (f"sell_reinvest_{h.player_id}", {"required_outgoing_player_ids": (h.player_id,)})
        for h in premium_holdings
    ]
    definitions.extend(
        (f"bench_cap_{cap / 10:g}", {"bench_cost_cap": cap}) for cap in (160, 180, 200)
    )
    for position in ("FWD", "MID"):
        pool = [
            r for r in current.values() if r["position"] == position and r.get("can_select", True)
        ]
        if pool:
            target = max(pool, key=lambda r: (float(r["market_price"]), -int(r["element"])))
            definitions.append(
                (
                    f"premium_{position.lower()}_{target['element']}",
                    {"required_player_ids": (int(target["element"]),)},
                )
            )
    for world_name in ("component_raw", "component_anchored"):
        world = worlds[world_name]
        means = np.mean(np.where(world["played"], world["points"], 0), axis=0)
        indices = {player: i for i, player in enumerate(world["player_ids"])}
        event_index = {event: i for i, event in enumerate(events)}
        proposals = [
            dict(
                r,
                proposal_points=float(
                    means[event_index[int(r["event_number"])]][indices[int(r["element"])]]
                ),
            )
            for r in rows
        ]
        definitions.append(
            (
                f"{world_name}_candidate_access",
                {"proposal_rows": proposals, "score_field": "proposal_points"},
            )
        )
    proposals, diagnostics, family_by_id = [], [], {}
    existing_ids = {policy_identity(a): a.action_id for a in actions}
    for family, raw_kwargs in definitions:
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0:
            diagnostics.append({"family": family, "status": "budget_exhausted"})
            continue
        kwargs = dict(raw_kwargs)
        proposed_rows = kwargs.pop("proposal_rows", rows)
        trace = []
        candidates = generate_weekly_actions(
            state,
            proposed_rows,
            rules,
            events=events,
            max_total_transfers=2,
            max_paid_transfers=2,
            alternatives_per_transfer_count=1,
            protect_role_sale_routes=False,
            terminal_free_transfer_curve=terminal_curve,
            solver_time_limit_seconds=min(2.0, remaining / 3),
            search_diagnostics=trace,
            **kwargs,
        )
        diagnostics.append(
            {
                "family": family,
                "status": "unresolved"
                if any(t["status"] == "unresolved" for t in trace)
                else "feasible"
                if candidates
                else "infeasible_within_two_transfers",
                "attempts": trace,
                "candidates": len(candidates),
            }
        )
        for candidate in candidates:
            # Same roster may have a genuinely different XI/captain under an
            # alternative proposal objective; do not silently alias that action.
            identity = policy_identity(candidate)
            if identity in existing_ids:
                family_by_id.setdefault(existing_ids[identity], []).append(family)
                continue
            action_id = "S-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            if action_id not in family_by_id:
                proposals.append(
                    replace(
                        candidate,
                        action_id=action_id,
                        route_type="screened_" + candidate.route_type,
                    )
                )
                family_by_id[action_id] = []
            family_by_id[action_id].append(family)
    combined = [*actions, *proposals]
    if proposals_out is not None:
        proposals_out.extend(proposals)
    metrics = {
        name: evaluate_action_paths(combined, events=events, **world)[0]
        for name, world in worlds.items()
    }
    audit = allocation_audit(
        combined, rows, events=events, selected_id=selected_id, metrics=metrics, weights=weights
    )
    # Only the true unchanged benchmark is labelled roll. Restore the ordinary
    # paid/free classification for the exact production hit-promotion checks.
    sensitivity_actions = [
        replace(a, route_type=a.route_type.removeprefix("screened_"))
        if a.route_type != "screened_roll"
        else a
        for a in combined
    ]
    sensitivity = []
    base_metrics = subset_metrics(metrics, {a.action_id for a in actions})
    for weight in (0.0, 0.10, 0.25, 0.50):
        for pool, members, values in (
            ("original", actions, base_metrics),
            ("expanded_research", sensitivity_actions, metrics),
        ):
            decision = synthesize_weekly_decision(
                members,
                values,
                scenario_weights=weights,
                worst_case_weight=weight,
                event_rows=current,
            )
            sensitivity.append(
                {
                    "pool": pool,
                    "worst_case_weight": weight,
                    "selected_action_id": decision["selected_action_id"],
                    "gate": decision["promotion_gate"],
                    "tradeoff": decision["objective_tradeoff"],
                }
            )
    complete = all(d["status"] not in {"unresolved", "budget_exhausted"} for d in diagnostics)
    return {
        "version": "allocation_research_v2",
        "status": "ready_diagnostic" if complete else "incomplete_search",
        "decision_authority": False,
        "complete_requested_families": complete,
        "original_pool_complete": True,
        "expanded_pool_complete": complete,
        "families": diagnostics,
        "family_by_action_id": family_by_id,
        "actions": audit,
        "risk_weight_sensitivity": sensitivity,
        "new_proposals": len(proposals),
        "capital_release_targets": [
            {"player_id": h.player_id, "selling_price": h.selling_price,
             "market_price": h.current_price}
            for h in premium_holdings
        ],
        "transfer_bounds": {"max_total_transfers": 2, "max_paid_transfers": 2},
        "elapsed_seconds": time.monotonic() - started,
        "frozen_proposals": [
            {
                "action_id": a.action_id,
                "selected_player_ids": list(a.selected_player_ids),
                "incremental_points_cost": a.incremental_points_cost,
                "scored_lineup": {
                    "starter_player_ids": list(a.action.lineup.starters),
                    "bench_player_ids": list(a.action.lineup.bench_order),
                    "captain_player_id": a.action.lineup.captain,
                    "vice_captain_player_id": a.action.lineup.vice_captain,
                },
            }
            for a in proposals
        ],
        "same_production_worlds": True,
        "limitations": [
            "Bench caps are sensitivity cases, not historically selected optimal spending rules.",
            "Proposals are bounded to two current transfers; infeasible does not mean impossible with a Wildcard.",
            "Component candidate means contain the currently authorized bounded market layer, not pure bookmaker predictions.",
            "Research reuses selection worlds; no independent holdout or historical policy lift is claimed.",
            "Future starts do not measure all reserve value; autosub value is in the shared-world score.",
        ],
    }
