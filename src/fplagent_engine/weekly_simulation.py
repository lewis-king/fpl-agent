from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .season_state import ChipType
from .tournament import _score_candidates
from .weekly_actions import EvaluatedAction


@dataclass(frozen=True)
class ActionPathMetric:
    action_id: str
    route_type: str
    mean_net_points: float
    median_net_points: float
    p10_net_points: float
    p90_net_points: float
    downside_cvar10: float
    standard_deviation: float
    mean_rank: float
    top_action_probability: float
    mean_delta_to_roll: float
    delta_to_roll_95ci_low: float
    delta_to_roll_95ci_high: float
    beat_roll_probability: float
    tie_roll_probability: float
    incremental_points_cost: int
    total_points_cost: int
    scenario_regret: float


def _candidate_payload(action: EvaluatedAction) -> dict:
    payload = {
        "candidate_id": action.action_id,
        "selected": list(action.selected_player_ids),
        "lineups": {
            str(item.event): {
                "starters": list(item.lineup.starters),
                "bench_order": list(item.lineup.bench_order),
                "captain": item.lineup.captain,
                "vice_captain": item.lineup.vice_captain,
            }
            for item in action.lineups
        },
    }
    if action.event_squads:
        payload["planned_squads"] = {
            str(event): list(selected) for event, selected in action.event_squads
        }
    return payload


def evaluate_action_paths(
    actions: list[EvaluatedAction],
    *,
    player_ids: list[int],
    events: tuple[int, ...],
    points: np.ndarray,
    played: np.ndarray,
    player_meta: dict[int, dict],
    horizon_decay: float = 0.88,
    score_candidates=None,
) -> tuple[list[ActionPathMetric], np.ndarray]:
    if not actions:
        raise ValueError("At least one weekly action is required")
    if points.shape != played.shape:
        raise ValueError("points and played arrays must have the same shape")
    expected_shape = (points.shape[0], len(events), len(player_ids))
    if points.shape != expected_shape:
        raise ValueError(f"simulation arrays have shape {points.shape}; expected {expected_shape}")
    if not 0.0 < horizon_decay <= 1.0:
        raise ValueError("horizon_decay must be in (0, 1]")
    roll_indices = [index for index, action in enumerate(actions) if action.route_type == "roll"]
    if len(roll_indices) != 1:
        raise ValueError("Weekly action evaluation requires exactly one roll comparator")
    candidates = [_candidate_payload(action) for action in actions]
    event_scores = (score_candidates or _score_candidates)(
        candidates,
        player_ids,
        events,
        points,
        played,
        player_meta,
    ).astype(np.float64)
    global_index = {element: index for index, element in enumerate(player_ids)}
    event_index = {event: index for index, event in enumerate(events)}
    for action_index, action in enumerate(actions):
        chip_events = list(action.planned_chips)
        if action.action.chip is not None:
            chip_events.insert(0, (action.action.event, action.action.chip))
        if len({event for event, _ in chip_events}) != len(chip_events):
            raise ValueError("Planned chips collide in one event")
        lineups = {item.event: item.lineup for item in action.lineups}
        squads = dict(action.event_squads)
        for event, chip in chip_events:
            if event not in event_index:
                raise ValueError("Chip action event is outside the simulation horizon")
            if chip not in {ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN}:
                continue  # WC/FH are represented by their exact event squads.
            offset = event_index[event]
            lineup = lineups[event]
            captain = global_index[lineup.captain]
            vice = global_index[lineup.vice_captain]
            captain_bonus = np.where(
                played[:, offset, captain],
                points[:, offset, captain],
                np.where(played[:, offset, vice], points[:, offset, vice], 0),
            )
            if chip == ChipType.TRIPLE_CAPTAIN:
                event_scores[:, action_index, offset] += captain_bonus
                continue
            squad_indices = [
                global_index[element] for element in squads.get(event, action.selected_player_ids)
            ]
            all_squad_points = np.sum(
                points[:, offset, squad_indices] * played[:, offset, squad_indices], axis=1
            )
            event_scores[:, action_index, offset] = all_squad_points + captain_bonus
    weights = np.asarray(
        [horizon_decay ** (event - events[0]) for event in events], dtype=np.float64
    )
    totals = np.sum(event_scores * weights[None, None, :], axis=2)
    for index, action in enumerate(actions):
        totals[:, index] -= float(action.incremental_points_cost)
        if len({event for event, _ in action.future_points_costs}) != len(
            action.future_points_costs
        ):
            raise ValueError("Duplicate future hit event")
        for event, cost in action.future_points_costs:
            if event <= events[0] or event not in event_index or cost < 0 or cost % 4:
                raise ValueError("Future hits must be legal costs at a later evaluated event")
            totals[:, index] -= horizon_decay ** (event - events[0]) * cost
        totals[:, index] += float(action.terminal_transfer_value)

    roll = totals[:, roll_indices[0]]
    order = np.argsort(-totals, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(len(totals))[:, None], order] = np.arange(1, len(actions) + 1)
    scenario_best_mean = float(totals.mean(axis=0).max())
    metrics = []
    for index, action in enumerate(actions):
        values = totals[:, index]
        threshold = float(np.quantile(values, 0.10))
        downside = values[values <= threshold]
        delta = values - roll
        standard_error = float(delta.std(ddof=1) / math.sqrt(len(delta))) if len(delta) > 1 else 0.0
        metrics.append(
            ActionPathMetric(
                action_id=action.action_id,
                route_type=action.route_type,
                mean_net_points=float(values.mean()),
                median_net_points=float(np.median(values)),
                p10_net_points=threshold,
                p90_net_points=float(np.quantile(values, 0.90)),
                downside_cvar10=float(downside.mean()),
                standard_deviation=float(values.std(ddof=1)) if len(values) > 1 else 0.0,
                mean_rank=float(ranks[:, index].mean()),
                top_action_probability=float(np.mean(ranks[:, index] == 1)),
                mean_delta_to_roll=float(delta.mean()),
                delta_to_roll_95ci_low=float(delta.mean() - 1.96 * standard_error),
                delta_to_roll_95ci_high=float(delta.mean() + 1.96 * standard_error),
                beat_roll_probability=float(np.mean(delta > 0)),
                tie_roll_probability=float(np.mean(delta == 0)),
                incremental_points_cost=action.incremental_points_cost,
                total_points_cost=action.total_points_cost,
                scenario_regret=scenario_best_mean - float(values.mean()),
            )
        )
    metrics.sort(key=lambda item: (item.scenario_regret, item.action_id))
    return metrics, totals


def combine_scenario_regret(
    scenario_metrics: dict[str, list[ActionPathMetric]],
    *,
    scenario_weights: dict[str, float],
    worst_case_weight: float = 0.25,
) -> list[dict]:
    if set(scenario_metrics) != set(scenario_weights):
        raise ValueError("Scenario metrics and weights must have identical names")
    if any(weight < 0.0 for weight in scenario_weights.values()) or not math.isclose(
        sum(scenario_weights.values()), 1.0, abs_tol=1e-9
    ):
        raise ValueError("Scenario weights must be non-negative and sum to one")
    if not 0.0 <= worst_case_weight <= 1.0:
        raise ValueError("worst_case_weight must be in [0, 1]")
    by_scenario = {
        name: {metric.action_id: metric for metric in metrics}
        for name, metrics in scenario_metrics.items()
    }
    action_sets = [set(metrics) for metrics in by_scenario.values()]
    if not action_sets or any(action_set != action_sets[0] for action_set in action_sets[1:]):
        raise ValueError("Every simulation scenario must contain the same action IDs")
    action_ids = action_sets[0]
    if not action_ids:
        raise ValueError("Simulation scenarios contain no actions")
    rows = []
    for action_id in sorted(action_ids):
        regrets = {
            name: metrics[action_id].scenario_regret for name, metrics in by_scenario.items()
        }
        weighted = sum(scenario_weights[name] * regrets[name] for name in regrets)
        worst = max(regrets.values())
        rows.append(
            {
                "action_id": action_id,
                "scenario_regrets": regrets,
                "weighted_mean_regret": weighted,
                "worst_scenario_regret": worst,
                "robust_regret": (1.0 - worst_case_weight) * weighted + worst_case_weight * worst,
            }
        )
    rows.sort(key=lambda row: (row["robust_regret"], row["action_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows
