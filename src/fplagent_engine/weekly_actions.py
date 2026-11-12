from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import highspy

from .capital_efficiency import expected_minutes, player_action_role_risk
from .rules import SquadRules
from .season_state import (
    ActionBundle,
    ActionOutcome,
    ChipStatus,
    ChipType,
    Lineup,
    ManagerState,
    MarketPlayer,
    Transfer,
    apply_action,
)


@dataclass(frozen=True)
class EventLineup:
    event: int
    lineup: Lineup
    formation: str
    projected_points: float


@dataclass(frozen=True)
class EvaluatedAction:
    action_id: str
    route_type: str
    score_field: str
    selected_player_ids: tuple[int, ...]
    action: ActionBundle
    outcome: ActionOutcome
    lineups: tuple[EventLineup, ...]
    gross_horizon_utility: float
    incremental_points_cost: int
    total_points_cost: int
    next_free_transfers: int | None
    terminal_free_transfers: int | None
    terminal_transfer_value: float
    decision_utility: float
    parent_action_id: str | None = None
    chip_current_proxy_uplift: float = 0.0
    retained_chip_proxy_value: float = 0.0
    chip_horizon_complete: bool = False
    event_squads: tuple[tuple[int, tuple[int, ...]], ...] = ()
    protected_counterfactuals: tuple[str, ...] = ()
    future_points_costs: tuple[tuple[int, int], ...] = ()
    planned_chips: tuple[tuple[int, ChipType], ...] = ()


class WeeklySolveError(RuntimeError):
    """An unsolved search is not evidence that a legal route cannot exist."""

    def __init__(self, status: highspy.HighsModelStatus, scope: str):
        self.status = str(status)
        self.proven_infeasible = status == highspy.HighsModelStatus.kInfeasible
        super().__init__(f"No solved {scope} weekly action: {status}")


def _terminal_value_curve(
    maximum: int,
    *,
    scalar_value: float,
    curve: dict[int, float] | None,
) -> dict[int, float]:
    if scalar_value < 0.0:
        raise ValueError("terminal_free_transfer_value must be non-negative")
    if curve is not None and scalar_value != 0.0:
        raise ValueError("Provide either a terminal transfer scalar or curve, not both")
    values = (
        {bank: float(bank) * scalar_value for bank in range(maximum + 1)}
        if curve is None
        else {int(bank): float(value) for bank, value in curve.items()}
    )
    if set(values) != set(range(maximum + 1)):
        raise ValueError(f"Terminal transfer curve must contain banks 0 through {maximum}")
    if values[0] != 0.0 or any(value < 0.0 for value in values.values()):
        raise ValueError("Terminal transfer curve must start at zero and remain non-negative")
    if any(values[bank] < values[bank - 1] for bank in range(1, maximum + 1)):
        raise ValueError("Terminal transfer curve must be non-decreasing")
    return values


def _forecast_grid(
    rows: list[dict[str, Any]], events: tuple[int, ...]
) -> tuple[dict[int, dict[int, dict[str, Any]]], dict[int, dict[str, Any]]]:
    by_player: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    meta: dict[int, dict[str, Any]] = {}
    for row in rows:
        event = int(row["event_number"])
        if event not in events:
            continue
        element = int(row["element"])
        by_player[element][event] = row
        meta[element] = row
    incomplete = {
        element: sorted(set(events) - set(event_rows))
        for element, event_rows in by_player.items()
        if set(event_rows) != set(events)
    }
    if incomplete:
        raise ValueError(f"Weekly forecast grid is incomplete: {incomplete}")
    if not by_player:
        raise ValueError("Weekly forecast grid is empty")
    return dict(by_player), meta


def _lineup_from_solution(
    *,
    event: int,
    selected: list[int],
    starters: list[int],
    captain: int,
    score_field: str,
    by_player: dict[int, dict[int, dict[str, Any]]],
    meta: dict[int, dict[str, Any]],
) -> EventLineup:
    vice = max(
        (element for element in starters if element != captain),
        key=lambda element: (
            float(by_player[element][event][score_field]),
            float(by_player[element][event].get("p_play", 1.0)),
        ),
    )
    bench = set(selected) - set(starters)
    reserve_goalkeepers = sorted(
        element for element in bench if str(meta[element]["position"]) == "GK"
    )
    outfield = sorted(
        (element for element in bench if str(meta[element]["position"]) != "GK"),
        key=lambda element: (
            float(by_player[element][event][score_field]),
            float(by_player[element][event].get("p_play", 1.0)),
        ),
        reverse=True,
    )
    lineup = Lineup(
        starters=tuple(starters),
        bench_order=(*outfield, *reserve_goalkeepers),
        captain=captain,
        vice_captain=vice,
    )
    points = sum(float(by_player[element][event][score_field]) for element in starters)
    points += float(by_player[captain][event][score_field])
    formation = "-".join(
        str(sum(str(meta[element]["position"]) == position for element in starters))
        for position in ("DEF", "MID", "FWD")
    )
    return EventLineup(event, lineup, formation, points)


def _solve_exact_transfer_count(
    state: ManagerState,
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
    rules: SquadRules,
    *,
    transfer_count: int | None,
    score_field: str,
    horizon_decay: float,
    bench_autosub_weight: float,
    excluded_squads: tuple[frozenset[int], ...] = (),
    required_outgoing_player_ids: tuple[int, ...] = (),
    solver_time_limit_seconds: float = 120.0,
    required_player_ids: tuple[int, ...] = (),
    bench_cost_cap: int | None = None,
    bench_weight_by_event: Mapping[int, float] | None = None,
    captain_weight_by_event: Mapping[int, float] | None = None,
) -> tuple[tuple[int, ...], tuple[EventLineup, ...], float]:
    # Planned team chips change what a squad is worth in their week: a Bench
    # Boost counts the whole bench, a Triple Captain counts the captain again.
    bench_weight_by_event = dict(bench_weight_by_event or {})
    captain_weight_by_event = dict(captain_weight_by_event or {})
    if any(not 0.0 <= w <= 1.0 for w in bench_weight_by_event.values()) or any(
        not 1.0 <= w <= 2.0 for w in captain_weight_by_event.values()
    ):
        raise ValueError("Planned-chip weights are out of range")
    if transfer_count is not None and (transfer_count < 0 or transfer_count > rules.squad_size):
        raise ValueError("transfer_count is outside squad bounds")
    if not 0.0 < horizon_decay <= 1.0:
        raise ValueError("horizon_decay must be in (0, 1]")
    if not 0.0 <= bench_autosub_weight <= 1.0:
        raise ValueError("bench_autosub_weight must be in [0, 1]")
    if not math.isfinite(solver_time_limit_seconds) or solver_time_limit_seconds <= 0:
        raise ValueError("solver_time_limit_seconds must be finite and positive")
    by_player, meta = _forecast_grid(rows, events)
    initial = {player.player_id: player for player in state.squad}
    if not set(initial) <= set(by_player):
        missing = sorted(set(initial) - set(by_player))
        raise ValueError(f"Current squad players are missing from the forecast: {missing}")
    action_event = min(events)
    eligible = set()
    for element, row in meta.items():
        if not bool(row.get("can_select", True)) or bool(row.get("removed", False)):
            continue
        current_event_row = by_player[element][action_event]
        if (
            element not in initial
            and player_action_role_risk(
                element,
                current_event_row,
                row,
                action="incoming",
            )
            is not None
        ):
            continue
        eligible.add(element)
    players = sorted(eligible | set(initial))
    if not set(required_player_ids) <= set(players):
        raise WeeklySolveError(highspy.HighsModelStatus.kInfeasible, "required-player")
    if bench_cost_cap is not None and (bench_cost_cap < 0 or bench_cost_cap != int(bench_cost_cap)):
        raise ValueError("Bench cap must be non-negative integer tenths")
    incoming_players = [element for element in players if element not in initial]
    if transfer_count is not None and transfer_count > len(incoming_players):
        raise ValueError("Not enough selectable players for the requested transfer count")
    player_index = {element: index for index, element in enumerate(players)}
    event_index = {event: index for index, event in enumerate(events)}
    n_players = len(players)
    n_events = len(events)

    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    highs.setOptionValue("random_seed", 19)
    highs.setOptionValue("mip_rel_gap", 1e-8)
    highs.setOptionValue("time_limit", solver_time_limit_seconds)
    integer = highspy.HighsVarType.kInteger
    selected_vars = highs.addVariables(n_players, lb=0, ub=1, type=integer, out_array=True)
    starter_vars = highs.addVariables(
        n_players * n_events, lb=0, ub=1, type=integer, out_array=True
    )
    captain_vars = highs.addVariables(
        n_players * n_events, lb=0, ub=1, type=integer, out_array=True
    )

    def selected_var(element: int):
        return selected_vars[player_index[element]]

    def starter_var(element: int, event: int):
        return starter_vars[player_index[element] * n_events + event_index[event]]

    def captain_var(element: int, event: int):
        return captain_vars[player_index[element] * n_events + event_index[event]]

    highs.addConstr(sum(selected_var(element) for element in players) == rules.squad_size)
    for element in required_player_ids:
        highs.addConstr(selected_var(element) == 1)
    if bench_cost_cap is not None:
        highs.addConstr(
            sum(
                float(meta[element]["market_price"])
                * (selected_var(element) - starter_var(element, action_event))
                for element in players
            )
            <= bench_cost_cap
        )
    unknown_required = sorted(set(required_outgoing_player_ids) - set(initial))
    if unknown_required:
        raise ValueError(
            f"Required outgoing players are not in the current squad: {unknown_required}"
        )
    for element in required_outgoing_player_ids:
        highs.addConstr(selected_var(element) == 0)
    if transfer_count is not None:
        highs.addConstr(
            sum(selected_var(element) for element in incoming_players) == transfer_count
        )
    for position, count in rules.squad_positions.items():
        highs.addConstr(
            sum(
                selected_var(element)
                for element in players
                if str(meta[element]["position"]) == position
            )
            == count
        )
    for team_id in sorted({int(meta[element]["team_id"]) for element in players}):
        club_cap = rules.club_limit
        if transfer_count == 0 and state.club_overflow_allowed:
            club_cap = max(club_cap, sum(h.team_id == team_id for h in state.squad))
        highs.addConstr(
            sum(
                selected_var(element)
                for element in players
                if int(meta[element]["team_id"]) == team_id
            )
            <= club_cap
        )
    purchase_cost = sum(
        float(meta[element]["market_price"]) * selected_var(element) for element in incoming_players
    )
    sale_proceeds = sum(
        float(holding.selling_price) * (1 - selected_var(element))
        for element, holding in initial.items()
    )
    highs.addConstr(purchase_cost <= state.bank + sale_proceeds)
    for excluded in excluded_squads:
        highs.addConstr(
            sum(selected_var(element) for element in excluded if element in player_index)
            <= rules.squad_size - 1
        )

    objective = 0
    first_event = min(events)
    for event in events:
        highs.addConstr(sum(starter_var(element, event) for element in players) == 11)
        highs.addConstr(sum(captain_var(element, event) for element in players) == 1)
        for element in players:
            highs.addConstr(starter_var(element, event) <= selected_var(element))
            highs.addConstr(captain_var(element, event) <= starter_var(element, event))
        for position in rules.squad_positions:
            starters_at_position = sum(
                starter_var(element, event)
                for element in players
                if str(meta[element]["position"]) == position
            )
            highs.addConstr(starters_at_position >= rules.minimum_starters[position])
            highs.addConstr(starters_at_position <= rules.maximum_starters[position])
        weight = horizon_decay ** (event - first_event)
        for element in players:
            if score_field not in by_player[element][event]:
                raise ValueError(f"Forecast is missing {score_field} for player {element}")
            score = float(by_player[element][event][score_field])
            objective += weight * score * starter_var(element, event)
            objective += (
                weight
                * captain_weight_by_event.get(event, 1.0)
                * score
                * captain_var(element, event)
            )
            objective += (
                weight
                * bench_weight_by_event.get(event, bench_autosub_weight)
                * score
                * (selected_var(element) - starter_var(element, event))
            )
    highs.maximize(objective)
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        scope = f"{transfer_count}-transfer" if transfer_count is not None else "unlimited-transfer"
        raise WeeklySolveError(highs.getModelStatus(), scope)

    selected = sorted(element for element in players if highs.val(selected_var(element)) > 0.5)
    lineups = []
    for event in events:
        starters = sorted(
            element for element in players if highs.val(starter_var(element, event)) > 0.5
        )
        captain = next(
            element for element in players if highs.val(captain_var(element, event)) > 0.5
        )
        lineups.append(
            _lineup_from_solution(
                event=event,
                selected=selected,
                starters=starters,
                captain=captain,
                score_field=score_field,
                by_player=by_player,
                meta=meta,
            )
        )
    return tuple(selected), tuple(lineups), float(highs.getObjectiveValue())


def _transfers_for_selected(
    state: ManagerState,
    selected: tuple[int, ...],
    meta: dict[int, dict[str, Any]],
) -> tuple[Transfer, ...]:
    initial = {player.player_id: player for player in state.squad}
    outgoing_by_position: dict[str, list[int]] = defaultdict(list)
    incoming_by_position: dict[str, list[int]] = defaultdict(list)
    for element, holding in initial.items():
        if element not in selected:
            outgoing_by_position[holding.position].append(element)
    for element in selected:
        if element not in initial:
            incoming_by_position[str(meta[element]["position"])].append(element)
    transfers: list[Transfer] = []
    for position in sorted(outgoing_by_position):
        outgoing = sorted(outgoing_by_position[position])
        incoming = sorted(incoming_by_position[position])
        if len(outgoing) != len(incoming):
            raise RuntimeError("Optimized squad does not preserve positional transfer balance")
        transfers.extend(
            Transfer(
                outgoing_player_id=old,
                incoming=MarketPlayer(
                    player_id=new,
                    position=position,
                    team_id=int(meta[new]["team_id"]),
                    current_price=round(float(meta[new]["market_price"])),
                ),
            )
            for old, new in zip(outgoing, incoming, strict=True)
        )
    return tuple(transfers)


def _route_type(transfer_count: int, free_transfers: int) -> str:
    if transfer_count == 0:
        return "roll"
    if transfer_count > free_transfers:
        return "paid_transfer"
    if transfer_count == 1:
        return "one_free_transfer"
    return "multi_free_transfer"


def generate_weekly_actions(
    state: ManagerState,
    rows: list[dict[str, Any]],
    rules: SquadRules,
    *,
    events: tuple[int, ...],
    score_field: str = "robust_points",
    horizon_decay: float = 0.88,
    bench_autosub_weight: float = 0.08,
    alternatives_per_transfer_count: int = 4,
    max_total_transfers: int = 5,
    max_paid_transfers: int = 2,
    terminal_free_transfer_value: float = 0.0,
    terminal_free_transfer_curve: dict[int, float] | None = None,
    solver_time_limit_seconds: float = 120.0,
    protect_role_sale_routes: bool = True,
    search_diagnostics: list[dict[str, Any]] | None = None,
    required_player_ids: tuple[int, ...] = (),
    required_outgoing_player_ids: tuple[int, ...] = (),
    bench_cost_cap: int | None = None,
    bench_weight_by_event: Mapping[int, float] | None = None,
    captain_weight_by_event: Mapping[int, float] | None = None,
) -> list[EvaluatedAction]:
    expected_events = tuple(range(state.event, state.event + len(events)))
    if not events or events != expected_events:
        raise ValueError("events must be a contiguous horizon starting at the manager event")
    if alternatives_per_transfer_count < 1:
        raise ValueError("alternatives_per_transfer_count must be positive")
    if max_total_transfers < 0 or max_paid_transfers < 0:
        raise ValueError("transfer limits must be non-negative")
    if set(required_outgoing_player_ids) - {h.player_id for h in state.squad}:
        raise ValueError("Required outgoing players must be held in the current squad")
    if set(required_outgoing_player_ids) & set(required_player_ids):
        raise ValueError("A player cannot be both required and sold")
    transfer_curve = _terminal_value_curve(
        rules.max_free_transfers,
        scalar_value=terminal_free_transfer_value,
        curve=terminal_free_transfer_curve,
    )
    by_player, meta = _forecast_grid(rows, events)
    action_event = min(events)
    maximum = min(
        rules.squad_size,
        max_total_transfers,
        state.free_transfers + max_paid_transfers,
    )
    evaluations: list[EvaluatedAction] = []

    def record_search(count: int, required: tuple[int, ...], error: RuntimeError | None):
        if search_diagnostics is not None:
            search_diagnostics.append(
                {
                    "transfer_count": count,
                    "required_outgoing_player_ids": list(required),
                    "status": "optimal"
                    if error is None
                    else (
                        "infeasible"
                        if isinstance(error, WeeklySolveError) and error.proven_infeasible
                        else "unresolved"
                    ),
                    "solver_status": None if error is None else str(error),
                }
            )

    def build_evaluation(
        selected: tuple[int, ...],
        lineups: tuple[EventLineup, ...],
        gross: float,
        *,
        transfer_count: int,
        protected_counterfactuals: tuple[str, ...] = (),
    ) -> EvaluatedAction:
        transfers = _transfers_for_selected(state, selected, meta)
        action = ActionBundle(
            event=state.event,
            lineup=lineups[0].lineup,
            transfers=transfers,
        )
        outcome = apply_action(state, action, rules)
        next_free_transfers = (
            outcome.next_manager.free_transfers if outcome.next_manager is not None else None
        )
        terminal_free_transfers = (
            min(
                rules.max_free_transfers,
                next_free_transfers + len(events) - 1,
            )
            if next_free_transfers is not None
            else None
        )
        terminal_value = (
            transfer_curve[terminal_free_transfers] * horizon_decay ** len(events)
            if terminal_free_transfers is not None
            else 0.0
        )
        decision_utility = gross - outcome.gameweek.incremental_points_cost + terminal_value
        encoded = ",".join(map(str, selected)).encode()
        action_id = f"A-{hashlib.sha1(encoded).hexdigest()[:10]}-{transfer_count}"
        return EvaluatedAction(
            action_id=action_id,
            route_type=_route_type(transfer_count, state.free_transfers),
            score_field=score_field,
            selected_player_ids=selected,
            action=action,
            outcome=outcome,
            lineups=lineups,
            gross_horizon_utility=gross,
            incremental_points_cost=outcome.gameweek.incremental_points_cost,
            total_points_cost=outcome.gameweek.points_cost,
            next_free_transfers=next_free_transfers,
            terminal_free_transfers=terminal_free_transfers,
            terminal_transfer_value=terminal_value,
            decision_utility=decision_utility,
            protected_counterfactuals=protected_counterfactuals,
        )

    for transfer_count in range(maximum + 1):
        excluded: list[frozenset[int]] = []
        for _ in range(alternatives_per_transfer_count):
            try:
                selected, lineups, gross = _solve_exact_transfer_count(
                    state,
                    rows,
                    events,
                    rules,
                    transfer_count=transfer_count,
                    score_field=score_field,
                    horizon_decay=horizon_decay,
                    bench_autosub_weight=bench_autosub_weight,
                    bench_weight_by_event=bench_weight_by_event,
                    captain_weight_by_event=captain_weight_by_event,
                    excluded_squads=tuple(excluded),
                    solver_time_limit_seconds=solver_time_limit_seconds,
                    required_player_ids=required_player_ids,
                    required_outgoing_player_ids=required_outgoing_player_ids,
                    bench_cost_cap=bench_cost_cap,
                )
            except RuntimeError as exc:
                record_search(transfer_count, required_outgoing_player_ids, exc)
                break
            record_search(transfer_count, required_outgoing_player_ids, None)
            selected_set = frozenset(selected)
            excluded.append(selected_set)
            evaluations.append(
                build_evaluation(
                    selected,
                    lineups,
                    gross,
                    transfer_count=transfer_count,
                )
            )

    # Protect exact sale counterfactuals for severe retained role risks.  The top-N
    # squad alternatives for a transfer count can all spend moves on the XI and
    # omit a structurally different route that removes a dead squad slot.  These
    # counterfactuals participate in the same simulations and robust ranking as
    # ordinary candidates; the label only records why they were retained.
    action_event_rows = {
        element: event_rows[action_event] for element, event_rows in by_player.items()
    }
    severe_role_watches = []
    for holding in state.squad:
        element = int(holding.player_id)
        row = action_event_rows[element]
        if str(row.get("position") or holding.position) == "GK":
            continue
        consensus = str(row.get("live_participation_consensus") or "")
        minutes = expected_minutes(row)
        play_probability = float(row.get("p_play") or 0.0)
        latest_zero = float(row.get("last_minutes") or 0.0) <= 0.0
        if (
            (consensus in {"predicted_bench_consensus", "single_source_bench"} and latest_zero)
            or play_probability < 0.50
            or minutes < 25.0
        ):
            severe_role_watches.append(element)

    for element in sorted(severe_role_watches) if protect_role_sale_routes else ():
        required_exits = tuple(sorted({*required_outgoing_player_ids, element}))
        for transfer_count in range(1, maximum + 1):
            excluded: list[frozenset[int]] = []
            for _ in range(alternatives_per_transfer_count):
                try:
                    selected, lineups, gross = _solve_exact_transfer_count(
                        state,
                        rows,
                        events,
                        rules,
                        transfer_count=transfer_count,
                        score_field=score_field,
                        horizon_decay=horizon_decay,
                        bench_autosub_weight=bench_autosub_weight,
                        bench_weight_by_event=bench_weight_by_event,
                        captain_weight_by_event=captain_weight_by_event,
                        excluded_squads=tuple(excluded),
                        required_outgoing_player_ids=required_exits,
                        solver_time_limit_seconds=solver_time_limit_seconds,
                        required_player_ids=required_player_ids,
                        bench_cost_cap=bench_cost_cap,
                    )
                except RuntimeError as exc:
                    record_search(transfer_count, required_exits, exc)
                    break
                record_search(transfer_count, required_exits, None)
                excluded.append(frozenset(selected))
                evaluations.append(
                    build_evaluation(
                        selected,
                        lineups,
                        gross,
                        transfer_count=transfer_count,
                        protected_counterfactuals=(f"retained-role-sale:{element}",),
                    )
                )

    deduplicated: dict[tuple[int, ...], EvaluatedAction] = {}
    for evaluation in evaluations:
        key = evaluation.selected_player_ids
        incumbent = deduplicated.get(key)
        if incumbent is None:
            deduplicated[key] = evaluation
            continue
        labels = tuple(
            sorted(
                set(incumbent.protected_counterfactuals) | set(evaluation.protected_counterfactuals)
            )
        )
        if labels != incumbent.protected_counterfactuals:
            deduplicated[key] = EvaluatedAction(
                **{
                    **incumbent.__dict__,
                    "protected_counterfactuals": labels,
                }
            )
    evaluations = list(deduplicated.values())
    evaluations.sort(key=lambda item: (-item.decision_utility, item.action_id))
    return evaluations


def generate_squad_chip_shadow_actions(
    state: ManagerState,
    rows: list[dict[str, Any]],
    rules: SquadRules,
    *,
    events: tuple[int, ...],
    score_field: str = "robust_points",
    horizon_decay: float = 0.88,
    bench_autosub_weight: float = 0.08,
    alternatives_per_chip: int = 4,
    terminal_free_transfer_value: float = 0.0,
    terminal_free_transfer_curve: dict[int, float] | None = None,
    solver_time_limit_seconds: float = 120.0,
    search_diagnostics: list[dict[str, Any]] | None = None,
    wildcard_squad: tuple[int, ...] | None = None,
) -> list[EvaluatedAction]:
    """Search exact permanent Wildcard and temporary Free Hit squads as shadows.

    ``wildcard_squad`` pins the Wildcard to the fifteen players the full-half
    planner chose by simulation; the search then only sets lineups. If that
    squad is no longer buildable the ordinary search runs instead.
    """
    expected_events = tuple(range(state.event, state.event + len(events)))
    if not events or events != expected_events:
        raise ValueError("events must be a contiguous horizon starting at the manager event")
    if alternatives_per_chip < 1:
        raise ValueError("alternatives_per_chip must be positive")
    if not 0.0 < horizon_decay <= 1.0:
        raise ValueError("horizon_decay must be in (0, 1]")
    if not 0.0 <= bench_autosub_weight <= 1.0:
        raise ValueError("bench_autosub_weight must be in [0, 1]")
    half = 1 if state.event <= 19 else 2
    available = {
        slot.chip
        for slot in state.chips
        if slot.half == half and slot.status == ChipStatus.AVAILABLE
    }
    squad_chips = available & {ChipType.WILDCARD, ChipType.FREE_HIT}
    if state.event == 1:
        squad_chips.clear()
    if state.previous_chip == ChipType.FREE_HIT and state.previous_chip_event == state.event - 1:
        squad_chips.discard(ChipType.FREE_HIT)
    if not squad_chips:
        return []

    transfer_curve = _terminal_value_curve(
        rules.max_free_transfers,
        scalar_value=terminal_free_transfer_value,
        curve=terminal_free_transfer_curve,
    )
    _, meta = _forecast_grid(rows, events)
    original_squad = tuple(sorted(player.player_id for player in state.squad))
    horizon_complete = max(events) >= (19 if half == 1 else 38)
    evaluations: list[EvaluatedAction] = []
    for chip in sorted(squad_chips, key=lambda item: item.value):
        excluded: list[frozenset[int]] = []
        pinned = tuple(wildcard_squad or ()) if chip == ChipType.WILDCARD else ()
        for _ in range(alternatives_per_chip):
            try:
                if chip == ChipType.WILDCARD:
                    wildcard_solve = partial(
                        _solve_exact_transfer_count,
                        state,
                        rows,
                        events,
                        rules,
                        transfer_count=None,
                        score_field=score_field,
                        horizon_decay=horizon_decay,
                        bench_autosub_weight=bench_autosub_weight,
                        excluded_squads=tuple(excluded),
                        solver_time_limit_seconds=solver_time_limit_seconds,
                    )
                    try:
                        selected, lineups, gross = wildcard_solve(required_player_ids=pinned)
                    except RuntimeError:
                        if not pinned:
                            raise
                        pinned = ()
                        selected, lineups, gross = wildcard_solve()
                    event_squads = tuple((event, selected) for event in events)
                else:
                    selected, current_lineups, current_gross = _solve_exact_transfer_count(
                        state,
                        rows,
                        (state.event,),
                        rules,
                        transfer_count=None,
                        score_field=score_field,
                        horizon_decay=horizon_decay,
                        bench_autosub_weight=bench_autosub_weight,
                        excluded_squads=tuple(excluded),
                        solver_time_limit_seconds=solver_time_limit_seconds,
                    )
                    future_lineups: tuple[EventLineup, ...] = ()
                    future_gross = 0.0
                    if len(events) > 1:
                        restored, future_lineups, future_gross = _solve_exact_transfer_count(
                            state,
                            rows,
                            events[1:],
                            rules,
                            transfer_count=0,
                            score_field=score_field,
                            horizon_decay=horizon_decay,
                            bench_autosub_weight=bench_autosub_weight,
                            solver_time_limit_seconds=solver_time_limit_seconds,
                        )
                        if restored != original_squad:
                            raise RuntimeError("Free Hit future squad was not restored")
                    lineups = (*current_lineups, *future_lineups)
                    gross = current_gross + horizon_decay * future_gross
                    event_squads = (
                        (state.event, selected),
                        *((event, original_squad) for event in events[1:]),
                    )
            except RuntimeError as exc:
                if search_diagnostics is not None:
                    search_diagnostics.append(
                        {
                            "chip": chip.value,
                            "status": "infeasible"
                            if isinstance(exc, WeeklySolveError) and exc.proven_infeasible
                            else "unresolved",
                            "solver_status": str(exc),
                        }
                    )
                break
            if search_diagnostics is not None:
                search_diagnostics.append({"chip": chip.value, "status": "optimal"})
            excluded.append(frozenset(selected))
            last_alternative = bool(pinned)
            transfers = _transfers_for_selected(state, selected, meta)
            action = ActionBundle(
                event=state.event,
                lineup=lineups[0].lineup,
                transfers=transfers,
                chip=chip,
            )
            outcome = apply_action(state, action, rules)
            next_free_transfers = (
                outcome.next_manager.free_transfers if outcome.next_manager is not None else None
            )
            terminal_free_transfers = (
                min(
                    rules.max_free_transfers,
                    next_free_transfers + len(events) - 1,
                )
                if next_free_transfers is not None
                else None
            )
            terminal_value = (
                transfer_curve[terminal_free_transfers] * horizon_decay ** len(events)
                if terminal_free_transfers is not None
                else 0.0
            )
            encoded = f"{chip.value}:".encode() + ",".join(map(str, selected)).encode()
            action_id = f"C-{hashlib.sha1(encoded).hexdigest()[:10]}-{chip.value}"
            evaluations.append(
                EvaluatedAction(
                    action_id=action_id,
                    route_type=chip.value,
                    score_field=score_field,
                    selected_player_ids=selected,
                    action=action,
                    outcome=outcome,
                    lineups=lineups,
                    gross_horizon_utility=gross,
                    incremental_points_cost=outcome.gameweek.incremental_points_cost,
                    total_points_cost=outcome.gameweek.points_cost,
                    next_free_transfers=next_free_transfers,
                    terminal_free_transfers=terminal_free_transfers,
                    terminal_transfer_value=terminal_value,
                    decision_utility=gross + terminal_value,
                    chip_horizon_complete=horizon_complete,
                    event_squads=event_squads,
                )
            )
            if last_alternative:
                break
    evaluations.sort(key=lambda item: (-item.decision_utility, item.action_id))
    return evaluations


def generate_team_chip_shadow_actions(
    state: ManagerState,
    actions: list[EvaluatedAction],
    rows: list[dict[str, Any]],
    rules: SquadRules,
    *,
    events: tuple[int, ...],
    bench_autosub_weight: float = 0.08,
) -> list[EvaluatedAction]:
    """Create exact BB/TC scoring variants without making them selectable yet."""
    if not 0.0 <= bench_autosub_weight <= 1.0:
        raise ValueError("bench_autosub_weight must be in [0, 1]")
    if not actions:
        return []
    by_player, _ = _forecast_grid(rows, events)
    half = 1 if state.event <= 19 else 2
    half_end = 19 if half == 1 else 38
    available = {
        slot.chip
        for slot in state.chips
        if slot.half == half and slot.status == ChipStatus.AVAILABLE
    }
    team_chips = available & {ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN}
    variants = []
    for base in actions:
        if base.action.chip is not None:
            continue
        score_field = base.score_field
        opportunities: dict[ChipType, list[tuple[int, float]]] = {
            ChipType.BENCH_BOOST: [],
            ChipType.TRIPLE_CAPTAIN: [],
        }
        for event_lineup in base.lineups:
            event = event_lineup.event
            if event > half_end:
                continue
            lineup = event_lineup.lineup
            opportunities[ChipType.TRIPLE_CAPTAIN].append(
                (event, float(by_player[lineup.captain][event][score_field]))
            )
            bench_proxy = (1.0 - bench_autosub_weight) * sum(
                float(by_player[element][event][score_field]) for element in lineup.bench_order
            )
            opportunities[ChipType.BENCH_BOOST].append((event, bench_proxy))
        horizon_complete = max(events) >= half_end
        for chip in sorted(team_chips, key=lambda item: item.value):
            current_values = [value for event, value in opportunities[chip] if event == state.event]
            if len(current_values) != 1:
                raise ValueError(f"No unique {chip.value} proxy for event {state.event}")
            future_values = [value for event, value in opportunities[chip] if event > state.event]
            current_uplift = current_values[0]
            retained_value = max(future_values, default=0.0)
            action = ActionBundle(
                event=base.action.event,
                lineup=base.action.lineup,
                transfers=base.action.transfers,
                chip=chip,
            )
            outcome = apply_action(state, action, rules)
            variants.append(
                EvaluatedAction(
                    action_id=f"{base.action_id}-{chip.value}",
                    route_type=f"{base.route_type}+{chip.value}",
                    score_field=base.score_field,
                    selected_player_ids=base.selected_player_ids,
                    action=action,
                    outcome=outcome,
                    lineups=base.lineups,
                    gross_horizon_utility=base.gross_horizon_utility + current_uplift,
                    incremental_points_cost=base.incremental_points_cost,
                    total_points_cost=base.total_points_cost,
                    next_free_transfers=(
                        outcome.next_manager.free_transfers
                        if outcome.next_manager is not None
                        else None
                    ),
                    terminal_free_transfers=base.terminal_free_transfers,
                    terminal_transfer_value=base.terminal_transfer_value,
                    decision_utility=(base.decision_utility + current_uplift - retained_value),
                    parent_action_id=base.action_id,
                    chip_current_proxy_uplift=current_uplift,
                    retained_chip_proxy_value=retained_value,
                    chip_horizon_complete=horizon_complete,
                )
            )
    variants.sort(key=lambda item: (-item.decision_utility, item.action_id))
    return variants
