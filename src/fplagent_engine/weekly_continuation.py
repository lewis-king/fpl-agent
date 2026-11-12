"""Bounded two-stage legal transfer lookahead; never grants production authority.

The first action is fixed before any scenario is revealed. Each next-deadline
branch can then choose its own legal transfers using only that branch's forecast
and prices. The default is an unchanged-information, flat-price projection, NOT
a trained forecast of future news. No realised outcomes enter this evaluator.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .rules import SquadRules
from .weekly_actions import EvaluatedAction, generate_weekly_actions


@dataclass(frozen=True)
class ContinuationScenario:
    name: str
    weight: float
    information_event: int
    forecast_rows: list[dict[str, Any]]


def _canonical_assumption(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"decimal": str(value)} if value.is_finite() else None
    if isinstance(value, (datetime, date)):
        return {"iso8601": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _canonical_assumption(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_assumption(item) for item in value]
    return value


def _fingerprint(rows: list[dict[str, Any]], score_field: str) -> str:
    # Include every supplied assumption: selection consumes role/price metadata
    # as well as the objective field. Nullable feature NaNs have one canonical
    # representation; consumed numeric inputs are validated by the solver.
    payload = {
        "score_field": score_field,
        "rows": [
            _canonical_assumption(row)
            for row in sorted(rows, key=lambda r: (int(r["event_number"]), int(r["element"])))
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def evaluate_weekly_continuation(
    actions: list[EvaluatedAction],
    rows: list[dict[str, Any]],
    rules: SquadRules,
    *,
    events: tuple[int, ...],
    selected_action_id: str,
    ranked_action_ids: list[str] | None = None,
    scenarios: list[ContinuationScenario] | None = None,
    horizon_decay: float = 0.88,
    bench_autosub_weight: float = 0.08,
    terminal_free_transfer_curve: dict[int, float] | None = None,
    maximum_roots: int = 4,
    maximum_future_transfers: int = 2,
    maximum_future_paid_transfers: int = 1,
    time_budget_seconds: float = 12.0,
    solver_time_limit_seconds: float = 1.0,
) -> dict[str, Any]:
    """Compare a bounded set of fixed-now actions with next-deadline recourse.

    Utility is the existing deterministic screening objective (including its
    bench proxy), NOT a calibrated simulated points gain. Small scenario sets
    are sensitivity tests, not estimated probabilities. Do not promote from
    this receipt without a matched sequential policy replay and scored outcomes.
    """
    if not events or events != tuple(range(events[0], events[0] + len(events))):
        raise ValueError("Continuation events must be contiguous")
    if not 0 < horizon_decay <= 1 or not 0 <= bench_autosub_weight <= 1:
        raise ValueError("Invalid continuation horizon or bench weight")
    if maximum_roots < 2 or maximum_future_transfers < 0 or maximum_future_paid_transfers < 0:
        raise ValueError("Invalid continuation search bounds")
    if any(
        not math.isfinite(x) or x <= 0 for x in (time_budget_seconds, solver_time_limit_seconds)
    ):
        raise ValueError("Continuation time limits must be finite and positive")
    base = {
        "version": "weekly_continuation_v1",
        "decision_authority": False,
        "operational_action_id": selected_action_id,
        "events": list(events),
        "method": "fixed first action; scenario-conditioned next-deadline legal transfers",
        "score_basis": "deterministic forecast utility, including bench proxy and terminal FT value",
        "probabilities_calibrated": False,
        "limitations": [
            "Restricted first-action and future-transfer candidate sets; not a global optimum.",
            "Transfers after the next deadline still use a fixed-roster continuation approximation.",
            "Default scenario has flat prices and no new role information; not a price/news prediction.",
            "No independent simulation holdout or historical net-points promotion is implied.",
        ],
    }
    if len(events) < 2:
        return {**base, "status": "no_future_deadline", "candidates": []}
    by_id = {action.action_id: action for action in actions}
    rolls = [a for a in actions if a.route_type == "roll"]
    if len(by_id) != len(actions) or len(rolls) != 1 or selected_action_id not in by_id:
        raise ValueError(
            "Continuation requires unique roots, the selected action and exactly one roll"
        )
    if any(a.action.event != events[0] for a in actions):
        raise ValueError("Root action event differs from continuation horizon")
    ranking = ranked_action_ids or [a.action_id for a in actions]
    if set(ranking) != set(by_id) or len(ranking) != len(by_id):
        raise ValueError("Continuation ranking must contain exactly the supplied roots")
    root_ids = list(dict.fromkeys([selected_action_id, rolls[0].action_id, *ranking]))[
        :maximum_roots
    ]
    future_events = events[1:]
    supplied_scenarios = scenarios is not None
    worlds = (
        scenarios
        if scenarios is not None
        else [
            ContinuationScenario(
                "unchanged_information_flat_prices",
                1.0,
                future_events[0],
                [dict(row) for row in rows if int(row["event_number"]) in future_events],
            )
        ]
    )
    if (
        not worlds
        or len({s.name for s in worlds}) != len(worlds)
        or any(not math.isfinite(s.weight) or s.weight < 0 for s in worlds)
        or not math.isclose(sum(s.weight for s in worlds), 1.0)
    ):
        raise ValueError("Continuation scenario names must be unique and weights must sum to one")
    if any(s.information_event != future_events[0] for s in worlds):
        raise ValueError("Scenario information must become available at the next deadline")
    for world in worlds:
        identity_by_player = {}
        keys = [(int(r["element"]), int(r["event_number"])) for r in world.forecast_rows]
        if len(keys) != len(set(keys)) or {ev for _, ev in keys} != set(future_events):
            raise ValueError("Scenario forecast must have unique rows across the future horizon")
        for row in world.forecast_rows:
            if any(k.startswith(("target_", "realized_")) for k in row):
                raise ValueError("Realised labels are forbidden in continuation scenarios")
            price = float(row["market_price"])
            if not math.isfinite(price) or price <= 0 or price != round(price):
                raise ValueError("Scenario prices must be positive integer tenths")
            identity = (price, str(row["position"]), int(row["team_id"]))
            player = int(row["element"])
            if identity_by_player.setdefault(player, identity) != identity:
                raise ValueError(
                    "Scenario catalog must use next-deadline prices and identity throughout"
                )
    started = time.monotonic()
    results = []
    failures = []
    exhausted = False
    for root_id in root_ids:
        root = by_id[root_id]
        if root.action.chip is not None:
            raise ValueError("This continuation evaluator currently accepts ordinary roots only")
        next_state = root.outcome.next_manager
        if next_state is None or next_state.event != future_events[0]:
            raise ValueError("Root has no coherent next-deadline manager state")
        current_rows = {int(r["element"]): r for r in rows if int(r["event_number"]) == events[0]}
        lineup = root.lineups[0].lineup
        field = root.score_field
        current_value = sum(float(current_rows[p][field]) for p in lineup.starters)
        current_value += float(current_rows[lineup.captain][field])
        current_value += bench_autosub_weight * sum(
            float(current_rows[p][field]) for p in lineup.bench_order
        )
        current_value -= root.incremental_points_cost  # Prior committed hits are sunk.
        branches = []
        for world in worlds:
            if world.weight == 0:
                continue
            remaining = time_budget_seconds - (time.monotonic() - started)
            if remaining <= 0:
                exhausted = True
                break
            catalog = {
                int(r["element"]): r
                for r in world.forecast_rows
                if int(r["event_number"]) == future_events[0]
            }
            if not {p.player_id for p in next_state.squad} <= catalog.keys():
                raise ValueError(
                    "Scenario omits a retained player; missing is not sold or unavailable"
                )
            holdings = tuple(
                holding.with_current_price(int(catalog[holding.player_id]["market_price"]))
                for holding in next_state.squad
            )
            # Catalog identity changes need their own explicit legal-state
            # handling; don't silently relabel a club/position in a scenario.
            if any(
                str(catalog[h.player_id]["position"]) != h.position
                or int(catalog[h.player_id]["team_id"]) != h.team_id
                for h in holdings
            ):
                raise ValueError("Scenario changes a holding's club or position")
            branch_state = replace(next_state, squad=holdings)
            max_count = min(
                maximum_future_transfers,
                branch_state.free_transfers + maximum_future_paid_transfers,
            )
            # Bound the ENTIRE subsearch even if some exact transfer counts
            # prove infeasible. Do not spawn unbounded role-sale neighbours.
            limit = min(solver_time_limit_seconds, remaining / (max_count + 1))
            search_diagnostics: list[dict[str, Any]] = []
            children = generate_weekly_actions(
                branch_state,
                world.forecast_rows,
                rules,
                events=future_events,
                score_field=field,
                horizon_decay=horizon_decay,
                bench_autosub_weight=bench_autosub_weight,
                alternatives_per_transfer_count=1,
                max_total_transfers=maximum_future_transfers,
                max_paid_transfers=maximum_future_paid_transfers,
                terminal_free_transfer_curve=terminal_free_transfer_curve,
                protect_role_sale_routes=False,
                solver_time_limit_seconds=limit,
                search_diagnostics=search_diagnostics,
            )
            unresolved = [d for d in search_diagnostics if d["status"] == "unresolved"]
            if unresolved:
                failures.append({
                    "root": root_id,
                    "scenario": world.name,
                    "reason": "A future transfer search did not finish; not proven infeasible.",
                    "search_diagnostics": search_diagnostics,
                })
                continue
            future_roll = next((a for a in children if a.route_type == "roll"), None)
            if future_roll is None:
                failures.append(
                    {
                        "root": root_id,
                        "scenario": world.name,
                        "reason": "No solved legal roll comparator within the solver budget.",
                    }
                )
                continue
            best = min(
                children, key=lambda a: (-a.decision_utility, len(a.action.transfers), a.action_id)
            )
            branches.append(
                {
                    "scenario": world.name,
                    "weight": world.weight,
                    "forecast_sha256": _fingerprint(world.forecast_rows, field),
                    "next_free_transfers_before_action": branch_state.free_transfers,
                    "bank_before_action": branch_state.bank,
                    "next_action_id": best.action_id,
                    "transfers": [
                        {
                            "outgoing_player_id": t.outgoing_player_id,
                            "incoming_player_id": t.incoming.player_id,
                            "incoming_price": t.incoming.current_price,
                        }
                        for t in best.action.transfers
                    ],
                    "next_incremental_points_cost": best.incremental_points_cost,
                    "bank_after_action": best.outcome.gameweek.bank,
                    "free_transfers_after_action": best.next_free_transfers,
                    "planned_selected_player_ids": list(best.selected_player_ids),
                    "planned_event_lineups": [
                        {
                            "event": item.event,
                            "starter_player_ids": list(item.lineup.starters),
                            "bench_player_ids": list(item.lineup.bench_order),
                            "captain_player_id": item.lineup.captain,
                            "vice_captain_player_id": item.lineup.vice_captain,
                        }
                        for item in best.lineups
                    ],
                    "solved_transfer_counts": sorted({len(a.action.transfers) for a in children}),
                    "requested_transfer_counts": list(range(max_count + 1)),
                    "search_diagnostics": search_diagnostics,
                    "root_value_with_recourse": current_value
                    + horizon_decay * best.decision_utility,
                    "root_value_without_recourse": current_value
                    + horizon_decay * future_roll.decision_utility,
                    "recourse_uplift": horizon_decay
                    * (best.decision_utility - future_roll.decision_utility),
                }
            )
        if len(branches) == sum(w.weight > 0 for w in worlds):
            results.append(
                {
                    "action_id": root_id,
                    "next_free_transfers": root.next_free_transfers,
                    "legacy_terminal_transfer_value": root.terminal_transfer_value,
                    "weighted_value": sum(
                        b["weight"] * b["root_value_with_recourse"] for b in branches
                    ),
                    "weighted_value_without_recourse": sum(
                        b["weight"] * b["root_value_without_recourse"] for b in branches
                    ),
                    "branches": branches,
                }
            )
        if exhausted:
            break
    complete = len(results) == len(root_ids)
    results.sort(key=lambda r: (-r["weighted_value"], r["action_id"]))
    selected = next((r for r in results if r["action_id"] == selected_action_id), None)
    roll = next((r for r in results if r["action_id"] == rolls[0].action_id), None)
    for row in results:
        row["delta_to_selected"] = (
            row["weighted_value"] - selected["weighted_value"] if selected else None
        )
        row["delta_to_roll"] = row["weighted_value"] - roll["weighted_value"] if roll else None
    return {
        **base,
        "status": "ready_diagnostic" if complete else "incomplete_diagnostic",
        "complete_root_comparison": complete,
        "scenario_source": "caller_supplied_sensitivity"
        if supplied_scenarios
        else "current_frozen_forecasts",
        "requested_root_ids": root_ids,
        "omitted_root_count": len(actions) - len(root_ids),
        "candidates": results,
        "shadow_preference": results[0]["action_id"] if complete else None,
        "failures": failures,
        "time_budget_exhausted": exhausted,
        "elapsed_seconds": time.monotonic() - started,
    }
