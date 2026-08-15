from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .features import TRAINING_FEATURES
from .market_transfer_replay import (
    _score_gameweek,
    moving_block_mean_interval,
    refresh_holding_prices,
)
from .models import BACKTEST_FORECAST
from .paths import MODEL_DATA, REPORTS
from .rules import SquadRules, load_rules
from .season_state import (
    ActionBundle,
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    apply_action,
    default_chip_inventory,
)
from .tournament import _solve_static
from .transfer_value import ARTIFACT as TRANSFER_VALUE_ARTIFACT
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_actions import generate_weekly_actions

OUTPUT_DIR = MODEL_DATA / "horizon_decay_replay_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "horizon-decay-policy-replay.md"
FIXTURE_SNAPSHOTS = PROCESSED / "vaastav_deadlines" / "fixture_snapshots.parquet"

SELECTION_SEASONS = ("2023-24", "2024-25")
TEST_SEASON = "2025-26"
SEASONS = (*SELECTION_SEASONS, TEST_SEASON)
START_EVENT = 1
END_EVENT = 8
HORIZONS = (1, 3, 5, 8)
DECAYS = (0.70, 0.80, 0.88, 0.94, 1.00)
INCUMBENT_HORIZON = 8
INCUMBENT_DECAY = 0.88
HISTORICAL_MAX_FREE_TRANSFERS = {
    "2023-24": 2,
    "2024-25": 5,
    "2025-26": 5,
}


@dataclass(frozen=True)
class PolicyConfig:
    horizon: int
    decay: float

    @property
    def config_id(self) -> str:
        return f"h{self.horizon}-d{round(self.decay * 100):03d}"


def policy_grid(
    horizons: tuple[int, ...] = HORIZONS,
    decays: tuple[float, ...] = DECAYS,
) -> tuple[PolicyConfig, ...]:
    if not horizons or not decays:
        raise ValueError("The horizon/decay grid cannot be empty")
    if any(horizon < 1 for horizon in horizons):
        raise ValueError("Every horizon must be positive")
    if any(not 0.0 < decay <= 1.0 for decay in decays):
        raise ValueError("Every decay must be in (0, 1]")
    configs = [PolicyConfig(1, 1.0)] if 1 in horizons else []
    configs.extend(
        PolicyConfig(horizon, decay)
        for horizon in horizons
        if horizon != 1
        for decay in decays
    )
    return tuple(configs)


def _fixture_response_coefficients(
    forecast_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    *,
    ridge: float = 0.01,
) -> dict[str, dict[str, float | int]]:
    """Recover the incumbent model's fixture response without using outcomes.

    The historical forecast is only available one event ahead.  We estimate how
    that already-frozen model changes a player's per-fixture xP with venue and
    official difficulty, after demeaning within player-season.  Actual points are
    deliberately absent from this fit.
    """
    if ridge < 0.0:
        raise ValueError("ridge must be non-negative")
    feature_by_key = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in feature_rows
    }
    grouped: dict[str, dict[str, list[tuple[float, np.ndarray]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in forecast_rows:
        expected = float(row["expected_points"])
        key = (str(row["season"]), int(row["event_number"]), int(row["element"]))
        feature = feature_by_key.get(key)
        if feature is None or expected <= 0.05:
            continue
        fixture_count = float(feature.get("fixture_count") or 0.0)
        difficulty = feature.get("fixture_difficulty")
        if fixture_count <= 0.0 or difficulty is None:
            continue
        position = str(row["position"])
        player_season = f"{row['season']}:{row['element']}"
        target = math.log(expected / fixture_count + 0.05)
        vector = np.asarray(
            [
                float(feature.get("home_fraction") or 0.0) - 0.5,
                3.0 - float(difficulty),
            ],
            dtype=np.float64,
        )
        grouped[position][player_season].append((target, vector))

    output: dict[str, dict[str, float | int]] = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        targets: list[float] = []
        matrix: list[np.ndarray] = []
        for values in grouped[position].values():
            target_mean = float(np.mean([value[0] for value in values]))
            vector_mean = np.mean([value[1] for value in values], axis=0)
            for target, vector in values:
                targets.append(target - target_mean)
                matrix.append(vector - vector_mean)
        if len(targets) < 100:
            raise ValueError(f"Insufficient fixture-response rows for {position}")
        design = np.asarray(matrix, dtype=np.float64)
        observed = np.asarray(targets, dtype=np.float64)
        coefficients = np.linalg.solve(
            design.T @ design + ridge * np.eye(design.shape[1]),
            design.T @ observed,
        )
        output[position] = {
            "rows": len(targets),
            "player_seasons": len(grouped[position]),
            "home_coefficient": float(coefficients[0]),
            "easier_fixture_coefficient": float(coefficients[1]),
        }
    return output


def _fixture_multiplier(
    position: str,
    fixture_count: float,
    home_fraction: float,
    fixture_difficulty: float | None,
    coefficients: dict[str, dict[str, float | int]],
) -> float:
    if fixture_count <= 0.0:
        return 0.0
    difficulty = 3.0 if fixture_difficulty is None else fixture_difficulty
    position_coefficients = coefficients[position]
    exponent = (
        float(position_coefficients["home_coefficient"]) * (home_fraction - 0.5)
        + float(position_coefficients["easier_fixture_coefficient"])
        * (3.0 - difficulty)
    )
    return fixture_count * math.exp(exponent)


def _load_inputs(
    *,
    forecast_path: Path = BACKTEST_FORECAST,
    features_path: Path = TRAINING_FEATURES,
    fixture_path: Path = FIXTURE_SNAPSHOTS,
) -> dict[str, Any]:
    for path in (forecast_path, features_path, fixture_path):
        if not path.exists():
            raise FileNotFoundError(path)
    forecasts = [
        row
        for row in pq.read_table(forecast_path).to_pylist()
        if str(row["season"]) in SEASONS and row.get("market_price") is not None
    ]
    features = [
        row
        for row in pq.read_table(features_path).to_pylist()
        if str(row["season"]) in SEASONS
    ]
    fixtures = [
        row
        for row in pq.read_table(fixture_path).to_pylist()
        if str(row["season"]) in SEASONS and row.get("decision_event") is not None
    ]
    forecast_by_event: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in forecasts:
        forecast_by_event[(str(row["season"]), int(row["event_number"]))].append(row)
    feature_by_key = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in features
    }
    fixture_by_snapshot: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in fixtures:
        fixture_by_snapshot[(str(row["season"]), int(row["decision_event"]))].append(row)
    available_snapshots = {
        season: sorted(event for candidate, event in fixture_by_snapshot if candidate == season)
        for season in SEASONS
    }
    for season in SEASONS:
        expected_events = list(range(START_EVENT, END_EVENT + 1))
        missing_forecasts = [
            event for event in expected_events if (season, event) not in forecast_by_event
        ]
        if missing_forecasts:
            raise ValueError(f"Missing deadline forecasts for {season}: {missing_forecasts}")
        if not available_snapshots[season] or available_snapshots[season][0] > START_EVENT:
            raise ValueError(f"No safe opening fixture snapshot for {season}")
    return {
        "forecasts": forecasts,
        "features": features,
        "forecast_by_event": dict(forecast_by_event),
        "feature_by_key": feature_by_key,
        "fixture_by_snapshot": dict(fixture_by_snapshot),
        "available_snapshots": available_snapshots,
        "paths": {
            "forecast": forecast_path,
            "features": features_path,
            "fixtures": fixture_path,
        },
    }


def _schedule_at_origin(
    *,
    season: str,
    origin_event: int,
    fixture_by_snapshot: dict[tuple[str, int], list[dict[str, Any]]],
    available_snapshots: dict[str, list[int]],
) -> tuple[dict[tuple[int, int], dict[str, float]], int]:
    eligible = [event for event in available_snapshots[season] if event <= origin_event]
    if not eligible:
        raise ValueError(f"No fixture snapshot at or before {season} GW{origin_event}")
    snapshot_event = max(eligible)
    aggregates: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"fixture_count": 0.0, "home_total": 0.0, "difficulty_total": 0.0}
    )
    for fixture in fixture_by_snapshot[(season, snapshot_event)]:
        if fixture.get("event") is None:
            continue
        event = int(fixture["event"])
        home = aggregates[(event, int(fixture["team_h"]))]
        home["fixture_count"] += 1.0
        home["home_total"] += 1.0
        home["difficulty_total"] += float(fixture.get("team_h_difficulty") or 3.0)
        away = aggregates[(event, int(fixture["team_a"]))]
        away["fixture_count"] += 1.0
        away["difficulty_total"] += float(fixture.get("team_a_difficulty") or 3.0)
    output = {}
    for key, row in aggregates.items():
        count = row["fixture_count"]
        output[key] = {
            "fixture_count": count,
            "home_fraction": row["home_total"] / count,
            "fixture_difficulty": row["difficulty_total"] / count,
        }
    return output, snapshot_event


def _prior_neutral_rate(
    *,
    season: str,
    element: int,
    origin_event: int,
    position: str,
    forecast_by_event: dict[tuple[str, int], list[dict[str, Any]]],
    feature_by_key: dict[tuple[str, int, int], dict[str, Any]],
    coefficients: dict[str, dict[str, float | int]],
) -> float:
    for event in range(origin_event - 1, 0, -1):
        forecast = next(
            (
                row
                for row in forecast_by_event.get((season, event), [])
                if int(row["element"]) == element
            ),
            None,
        )
        feature = feature_by_key.get((season, event, element))
        if forecast is None or feature is None:
            continue
        multiplier = _fixture_multiplier(
            position,
            float(feature.get("fixture_count") or 0.0),
            float(feature.get("home_fraction") or 0.0),
            None
            if feature.get("fixture_difficulty") is None
            else float(feature["fixture_difficulty"]),
            coefficients,
        )
        if multiplier > 0.0:
            return max(0.0, float(forecast["expected_points"]) / multiplier)
    return 0.0


def build_deadline_horizon_rows(
    *,
    season: str,
    origin_event: int,
    horizon: int,
    end_event: int,
    forecast_by_event: dict[tuple[str, int], list[dict[str, Any]]],
    feature_by_key: dict[tuple[str, int, int], dict[str, Any]],
    fixture_by_snapshot: dict[tuple[str, int], list[dict[str, Any]]],
    available_snapshots: dict[str, list[int]],
    coefficients: dict[str, dict[str, float | int]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if horizon < 1 or origin_event > end_event:
        raise ValueError("Invalid replay horizon")
    events = tuple(range(origin_event, min(end_event, origin_event + horizon - 1) + 1))
    base_rows = forecast_by_event[(season, origin_event)]
    schedule, snapshot_event = _schedule_at_origin(
        season=season,
        origin_event=origin_event,
        fixture_by_snapshot=fixture_by_snapshot,
        available_snapshots=available_snapshots,
    )
    output = []
    for base in base_rows:
        element = int(base["element"])
        position = str(base["position"])
        team_id = int(base["team_id"])
        feature = feature_by_key.get((season, origin_event, element), {})
        current_context = schedule.get((origin_event, team_id))
        if current_context is None:
            current_context = {
                "fixture_count": float(feature.get("fixture_count") or 0.0),
                "home_fraction": float(feature.get("home_fraction") or 0.0),
                "fixture_difficulty": (
                    3.0
                    if feature.get("fixture_difficulty") is None
                    else float(feature["fixture_difficulty"])
                ),
            }
        current_multiplier = _fixture_multiplier(
            position,
            current_context["fixture_count"],
            current_context["home_fraction"],
            current_context["fixture_difficulty"],
            coefficients,
        )
        if current_multiplier > 0.0:
            neutral_rate = max(0.0, float(base["expected_points"]) / current_multiplier)
        else:
            neutral_rate = _prior_neutral_rate(
                season=season,
                element=element,
                origin_event=origin_event,
                position=position,
                forecast_by_event=forecast_by_event,
                feature_by_key=feature_by_key,
                coefficients=coefficients,
            )
        for event in events:
            context = schedule.get(
                (event, team_id),
                {"fixture_count": 0.0, "home_fraction": 0.0, "fixture_difficulty": 3.0},
            )
            if event == origin_event:
                expected = float(base["expected_points"])
                target_points = float(base["target_points"])
                target_minutes = float(feature.get("target_minutes") or 0.0)
            else:
                expected = neutral_rate * _fixture_multiplier(
                    position,
                    context["fixture_count"],
                    context["home_fraction"],
                    context["fixture_difficulty"],
                    coefficients,
                )
                # Future outcomes must never enter an as-of-deadline decision row.
                target_points = 0.0
                target_minutes = 0.0
            output.append(
                {
                    **base,
                    "event_number": event,
                    "fixture_count": context["fixture_count"],
                    "home_fraction": context["home_fraction"],
                    "fixture_difficulty": context["fixture_difficulty"],
                    "expected_points": expected,
                    "robust_points": expected,
                    "target_points": target_points,
                    "target_minutes": target_minutes,
                    "can_select": True,
                    "removed": False,
                    "forecast_origin_event": origin_event,
                    "forecast_lead": event - origin_event,
                    "fixture_snapshot_event": snapshot_event,
                }
            )
    return output, {
        "origin_event": origin_event,
        "snapshot_event": snapshot_event,
        "snapshot_age_events": origin_event - snapshot_event,
    }


def _historical_rules(season: str) -> SquadRules:
    rules = load_rules()
    return replace(
        rules,
        max_free_transfers=HISTORICAL_MAX_FREE_TRANSFERS[season],
    )


def _initial_state(
    *,
    season: str,
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
    decay: float,
    rules: SquadRules,
) -> tuple[ManagerState, dict[str, Any]]:
    solution = _solve_static_from_rows(rows, events, decay, rules)
    current = {int(row["element"]): row for row in rows if int(row["event_number"]) == events[0]}
    selected = tuple(int(element) for element in solution["selected"])
    holdings = tuple(
        PlayerHolding(
            player_id=element,
            position=str(current[element]["position"]),
            team_id=int(current[element]["team_id"]),
            purchase_price=round(float(current[element]["market_price"])),
            current_price=round(float(current[element]["market_price"])),
            selling_price=round(float(current[element]["market_price"])),
        )
        for element in selected
    )
    lineup_row = solution["lineups"][events[0]]
    lineup = Lineup(
        starters=tuple(int(element) for element in lineup_row["starters"]),
        bench_order=tuple(int(element) for element in lineup_row["bench_order"]),
        captain=int(lineup_row["captain"]),
        vice_captain=int(lineup_row["vice_captain"]),
    )
    spend = sum(holding.purchase_price for holding in holdings)
    return (
        ManagerState(
            season=season,
            event=events[0],
            event_status=EventStatus.DEADLINE_OPEN,
            squad=holdings,
            bank=rules.budget - spend,
            # There is no bankable transfer during initial GW1 squad selection.
            # Applying the GW1 lineup creates exactly one free transfer for GW2.
            free_transfers=0,
            chips=default_chip_inventory(),
            lineup=lineup,
        ),
        solution,
    )


def _solve_static_from_rows(
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
    decay: float,
    rules: SquadRules,
) -> dict[str, Any]:
    by_player: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    meta: dict[int, dict[str, Any]] = {}
    for row in rows:
        element = int(row["element"])
        event = int(row["event_number"])
        by_player[element][event] = row
        meta[element] = row
    return _solve_static(
        dict(by_player),
        meta,
        events,
        rules,
        horizon_decay=decay,
        bench_weight=0.08,
    )


def _ensure_holdings(
    state: ManagerState,
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
) -> list[dict[str, Any]]:
    output = list(rows)
    present = {(int(row["event_number"]), int(row["element"])) for row in rows}
    for holding in state.squad:
        for event in events:
            if (event, holding.player_id) in present:
                continue
            output.append(
                {
                    "season": state.season,
                    "event_number": event,
                    "element": holding.player_id,
                    "player_name": f"Unavailable #{holding.player_id}",
                    "position": holding.position,
                    "team_id": holding.team_id,
                    "market_price": holding.current_price,
                    "target_points": 0.0,
                    "target_minutes": 0.0,
                    "expected_points": 0.0,
                    "robust_points": 0.0,
                    "p_play": 0.0,
                    "can_select": False,
                    "removed": True,
                    "forecast_origin_event": state.event,
                    "forecast_lead": event - state.event,
                    "fixture_snapshot_event": state.event,
                }
            )
    return output


def _names(ids: list[int], rows: list[dict[str, Any]]) -> list[str]:
    names = {int(row["element"]): str(row["player_name"]) for row in rows}
    return [names.get(element, f"#{element}") for element in ids]


def run_policy_path(
    *,
    season: str,
    config: PolicyConfig,
    inputs: dict[str, Any],
    coefficients: dict[str, dict[str, float | int]],
    terminal_curve: dict[int, float],
    end_event: int = END_EVENT,
    row_transform: Callable[
        [str, int, list[dict[str, Any]]], list[dict[str, Any]]
    ]
    | None = None,
) -> dict[str, Any]:
    rules = _historical_rules(season)
    curve = {bank: terminal_curve[bank] for bank in range(rules.max_free_transfers + 1)}
    state: ManagerState | None = None
    event_rows = []
    snapshot_ages = []
    for event in range(START_EVENT, end_event + 1):
        rows, snapshot = build_deadline_horizon_rows(
            season=season,
            origin_event=event,
            horizon=config.horizon,
            end_event=end_event,
            forecast_by_event=inputs["forecast_by_event"],
            feature_by_key=inputs["feature_by_key"],
            fixture_by_snapshot=inputs["fixture_by_snapshot"],
            available_snapshots=inputs["available_snapshots"],
            coefficients=coefficients,
        )
        if row_transform is not None:
            rows = row_transform(season, event, rows)
        snapshot_ages.append(snapshot["snapshot_age_events"])
        events = tuple(sorted({int(row["event_number"]) for row in rows}))
        current_rows = [row for row in rows if int(row["event_number"]) == event]
        if event == START_EVENT:
            state, solution = _initial_state(
                season=season,
                rows=rows,
                events=events,
                decay=config.decay,
                rules=rules,
            )
            gross = _score_gameweek(None, state, solution, current_rows)
            lineup = solution["lineups"][event]
            transfers: list[dict[str, Any]] = []
            route = "initial_squad"
            points_cost = 0
            selected = list(solution["selected"])
            outcome = apply_action(state, ActionBundle(event, state.lineup), rules)
            free_before = 0
            free_after = 1
            bank_after = state.bank
        else:
            if state is None:
                raise RuntimeError("Replay state was not initialized")
            state = refresh_holding_prices(state, current_rows)
            rows = _ensure_holdings(state, rows, events)
            current_rows = [row for row in rows if int(row["event_number"]) == event]
            actions = generate_weekly_actions(
                state,
                rows,
                rules,
                events=events,
                score_field="expected_points",
                horizon_decay=config.decay,
                alternatives_per_transfer_count=1,
                max_total_transfers=rules.max_free_transfers,
                max_paid_transfers=0,
                terminal_free_transfer_curve=curve,
            )
            if not actions:
                raise RuntimeError(f"No legal action for {season} GW{event} {config.config_id}")
            action = actions[0]
            gross = _score_gameweek(action, state, None, current_rows)
            lineup_item = action.lineups[0].lineup
            lineup = {
                "starters": list(lineup_item.starters),
                "bench_order": list(lineup_item.bench_order),
                "captain": lineup_item.captain,
                "vice_captain": lineup_item.vice_captain,
            }
            transfers = [
                {
                    "out": transfer.outgoing_player_id,
                    "out_name": _names([transfer.outgoing_player_id], current_rows)[0],
                    "in": transfer.incoming.player_id,
                    "in_name": _names([transfer.incoming.player_id], current_rows)[0],
                }
                for transfer in action.action.transfers
            ]
            route = action.route_type
            points_cost = action.incremental_points_cost
            selected = list(action.selected_player_ids)
            outcome = action.outcome
            free_before = state.free_transfers
            free_after = action.next_free_transfers
            bank_after = outcome.gameweek.bank
        event_rows.append(
            {
                "event": event,
                "route": route,
                "gross_points": gross,
                "points_cost": points_cost,
                "net_points": gross - points_cost,
                "transfers": transfers,
                "free_transfers_before": free_before,
                "free_transfers_after": free_after,
                "bank_after": bank_after,
                "selected": selected,
                "selected_names": _names(selected, current_rows),
                "starters": list(lineup["starters"]),
                "captain": int(lineup["captain"]),
                "captain_name": _names([int(lineup["captain"])], current_rows)[0],
                "fixture_snapshot_event": snapshot["snapshot_event"],
                "fixture_snapshot_age_events": snapshot["snapshot_age_events"],
            }
        )
        if event < end_event:
            if outcome.next_manager is None:
                raise RuntimeError(f"Unexpected terminal manager state after {season} GW{event}")
            state = outcome.next_manager
    return {
        "season": season,
        "config_id": config.config_id,
        "horizon": config.horizon,
        "decay": config.decay,
        "gross_points": sum(row["gross_points"] for row in event_rows),
        "points_cost": sum(row["points_cost"] for row in event_rows),
        "net_points": sum(row["net_points"] for row in event_rows),
        "transfers": sum(len(row["transfers"]) for row in event_rows),
        "rolls": sum(row["route"] == "roll" for row in event_rows),
        "maximum_fixture_snapshot_age_events": max(snapshot_ages),
        "events": event_rows,
    }


def _select_configuration(
    paths: dict[tuple[str, str], dict[str, Any]],
    configs: tuple[PolicyConfig, ...],
) -> tuple[PolicyConfig, list[dict[str, Any]]]:
    best_by_season = {
        season: max(paths[(season, config.config_id)]["net_points"] for config in configs)
        for season in SELECTION_SEASONS
    }
    rows = []
    for config in configs:
        values = {
            season: int(paths[(season, config.config_id)]["net_points"])
            for season in SELECTION_SEASONS
        }
        regrets = {season: best_by_season[season] - value for season, value in values.items()}
        mean_regret = float(np.mean(list(regrets.values())))
        worst_regret = float(max(regrets.values()))
        robust_regret = 0.80 * mean_regret + 0.20 * worst_regret
        rows.append(
            {
                "config_id": config.config_id,
                "horizon": config.horizon,
                "decay": config.decay,
                "selection_net_points": values,
                "selection_regrets": regrets,
                "selection_total_points": sum(values.values()),
                "mean_regret": mean_regret,
                "worst_regret": worst_regret,
                "robust_regret": robust_regret,
            }
        )
    rows.sort(
        key=lambda row: (
            row["robust_regret"],
            -row["selection_total_points"],
            row["horizon"],
            abs(row["decay"] - INCUMBENT_DECAY),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["selection_rank"] = rank
    selected_row = rows[0]
    selected = next(config for config in configs if config.config_id == selected_row["config_id"])
    return selected, rows


def _selection_neighbour_stability(
    selected: PolicyConfig,
    ranking: list[dict[str, Any]],
    *,
    maximum_total_point_gap: int = 8,
) -> dict[str, Any]:
    by_id = {str(row["config_id"]): row for row in ranking}
    horizon_index = HORIZONS.index(selected.horizon)
    decay_index = DECAYS.index(selected.decay)
    neighbours: list[PolicyConfig] = []
    for offset in (-1, 1):
        candidate_index = horizon_index + offset
        if 0 <= candidate_index < len(HORIZONS) and HORIZONS[candidate_index] != 1:
            neighbours.append(PolicyConfig(HORIZONS[candidate_index], selected.decay))
        candidate_index = decay_index + offset
        if 0 <= candidate_index < len(DECAYS):
            neighbours.append(PolicyConfig(selected.horizon, DECAYS[candidate_index]))
    selected_total = int(by_id[selected.config_id]["selection_total_points"])
    rows = []
    for neighbour in neighbours:
        row = by_id.get(neighbour.config_id)
        if row is None:
            continue
        gap = selected_total - int(row["selection_total_points"])
        rows.append(
            {
                "config_id": neighbour.config_id,
                "selection_total_point_gap": gap,
                "within_tolerance": gap <= maximum_total_point_gap,
            }
        )
    supported = sum(bool(row["within_tolerance"]) for row in rows)
    required = min(2, len(rows))
    return {
        "passed": supported >= required,
        "maximum_total_point_gap": maximum_total_point_gap,
        "required_supported_neighbours": required,
        "supported_neighbours": supported,
        "neighbours": rows,
    }


def _promotion_gate(
    *,
    selected: PolicyConfig,
    incumbent: PolicyConfig,
    paths: dict[tuple[str, str], dict[str, Any]],
    selection_stability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation_deltas = [
        paths[(season, selected.config_id)]["net_points"]
        - paths[(season, incumbent.config_id)]["net_points"]
        for season in SELECTION_SEASONS
    ]
    selected_test = paths[(TEST_SEASON, selected.config_id)]
    incumbent_test = paths[(TEST_SEASON, incumbent.config_id)]
    test_event_deltas = [
        selected_event["net_points"] - incumbent_event["net_points"]
        for selected_event, incumbent_event in zip(
            selected_test["events"], incumbent_test["events"], strict=True
        )
    ]
    interval = moving_block_mean_interval(
        test_event_deltas,
        block_length=2,
        samples=5_000,
        seed=20260821,
    )
    candidate_changed = selected.config_id != incumbent.config_id
    checks = {
        "candidate_differs_from_incumbent": candidate_changed,
        "positive_each_selection_season": all(delta > 0 for delta in validation_deltas),
        "selection_has_local_parameter_support": bool(
            selection_stability is not None and selection_stability["passed"]
        ),
        "positive_frozen_test_total": sum(test_event_deltas) > 0,
        "frozen_test_block_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
    }
    passed = candidate_changed and all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "selection_season_deltas": dict(zip(SELECTION_SEASONS, validation_deltas, strict=True)),
        "frozen_test_total_delta": sum(test_event_deltas),
        "frozen_test_mean_delta": float(np.mean(test_event_deltas)),
        "frozen_test_event_deltas": test_event_deltas,
        "frozen_test_moving_block_interval": interval,
        "selection_neighbour_stability": selection_stability,
    }


def _render(result: dict[str, Any]) -> str:
    selected = result["selected_configuration"]
    incumbent = result["incumbent_configuration"]
    gate = result["promotion_gate"]
    path_comparisons = []
    for season in SEASONS:
        selected_events = result["paths"][f"{season}:{selected['config_id']}"]["events"]
        incumbent_events = result["paths"][f"{season}:{incumbent['config_id']}"]["events"]
        selected_initial = set(selected_events[0]["selected_names"])
        incumbent_initial = set(incumbent_events[0]["selected_names"])
        matching_actions = sum(
            selected_event["transfers"] == incumbent_event["transfers"]
            for selected_event, incumbent_event in zip(
                selected_events, incumbent_events, strict=True
            )
        )
        path_comparisons.append(
            {
                "season": season,
                "initial_overlap": len(selected_initial & incumbent_initial),
                "selected_only": sorted(selected_initial - incumbent_initial),
                "incumbent_only": sorted(incumbent_initial - selected_initial),
                "matching_actions": matching_actions,
                "events": len(selected_events),
            }
        )
    lines = [
        "# Horizon and decay: rolling preseason policy replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — selection chose `{selected['config_id']}` "
            f"(horizon {selected['horizon']}, decay {selected['decay']:.2f}). "
            f"The incumbent is `{incumbent['config_id']}`. On the untouched "
            f"{TEST_SEASON} GW1–8 path the challenger changed realised ordinary-transfer "
            f"points by {gate['frozen_test_total_delta']:+.0f}."
        ),
        "",
        "This is the first outcome-based calibration of the planning horizon. It starts from a legal GW1 squad, reruns the decision at every deadline, carries squad value and the historically legal free-transfer bank, allows no hits or chips, and scores realised points with autosubs and captain fallback.",
        "",
        "GW1–8 is the evaluation window, not one frozen eight-week plan. At every gameweek the policy discards its old projection, ingests that deadline's out-of-fold forecast and latest known fixture schedule, then optimises again from the squad and free transfers it actually carried forward.",
        "",
        "## Selection grid",
        "",
        "| Rank | Configuration | 2023/24 | 2024/25 | Total | Robust regret | 2025/26 test |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    path_summaries = result["path_summaries"]
    for row in result["selection_ranking"]:
        test = path_summaries[f"{TEST_SEASON}:{row['config_id']}"]["net_points"]
        lines.append(
            f"| {row['selection_rank']} | `{row['config_id']}` | "
            f"{row['selection_net_points']['2023-24']} | "
            f"{row['selection_net_points']['2024-25']} | "
            f"{row['selection_total_points']} | {row['robust_regret']:.2f} | {test} |"
        )
    lines.extend(
        [
            "",
            "## Challenger versus incumbent",
            "",
            "| Season | Initial squad overlap | Same transfer actions | Challenger only | Incumbent only |",
            "|---|---:|---:|---|---|",
        ]
    )
    for row in path_comparisons:
        lines.append(
            f"| {row['season']} | {row['initial_overlap']}/15 | "
            f"{row['matching_actions']}/{row['events']} gameweeks | "
            f"{', '.join(row['selected_only']) or '—'} | "
            f"{', '.join(row['incumbent_only']) or '—'} |"
        )
    lines.extend(
        [
            "",
            "The challenger must win because its planning policy generalises, not because one opening player happened to outscore another in one selection season. Squad overlap and action agreement expose that fragility alongside the points table.",
            "",
            "## What is and is not learned",
            "",
            "- Horizon and decay are selected only from realised 2023/24 and 2024/25 GW1–8 ordinary-transfer paths. The 2025/26 path is untouched until the promotion gate.",
            "- Every current-event xP is an out-of-fold, deadline-safe forecast. Future player form, prices, availability and results are never copied backwards.",
            "- Future fixtures come from the latest archived fixture snapshot available at that deadline. Missing deadline snapshots are carried forward from an earlier snapshot, never filled from a later one.",
            "- Because the existing out-of-fold forecast is one-event ahead, future xP freezes the current player rate and applies only a fixture/venue response recovered from the incumbent model's predictions. That response fit never sees actual points.",
            "- This is a three-season opening-window sample. It is materially stronger than choosing 0.88 by judgment, but still too small to imply a universal football constant.",
            "- Wildcards, hits, future price forecasts and adaptive injury scenario trees are excluded. Their absence is why a configuration must pass the untouched season before receiving production authority.",
            "",
            "## Promotion rule",
            "",
        ]
    )
    for name, passed in gate["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend(
        [
            "",
            (
                "The production horizon may change only when every gate passes. Otherwise the result remains calibration evidence and the current 8/0.88 sensitivity portfolio stays in force."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_horizon_decay_replay(
    *,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
    created_at: str | None = None,
) -> dict[str, Any]:
    inputs = _load_inputs()
    coefficients = _fixture_response_coefficients(
        [
            row
            for row in inputs["forecasts"]
            if str(row["season"]) in SELECTION_SEASONS
        ],
        [
            row
            for row in inputs["features"]
            if str(row["season"]) in SELECTION_SEASONS
        ],
    )
    configs = policy_grid()
    incumbent = next(
        config
        for config in configs
        if config.horizon == INCUMBENT_HORIZON
        and math.isclose(config.decay, INCUMBENT_DECAY)
    )
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=5,
        rules=load_rules(),
    )
    paths: dict[tuple[str, str], dict[str, Any]] = {}
    total = len(SEASONS) * len(configs)
    completed = 0
    for season in SEASONS:
        for config in configs:
            paths[(season, config.config_id)] = run_policy_path(
                season=season,
                config=config,
                inputs=inputs,
                coefficients=coefficients,
                terminal_curve=terminal_curve,
            )
            completed += 1
            print(
                f"Horizon calibration: completed {completed}/{total} paths "
                f"({season} {config.config_id})",
                flush=True,
            )
    selected, ranking = _select_configuration(paths, configs)
    stability = _selection_neighbour_stability(selected, ranking)
    gate = _promotion_gate(
        selected=selected,
        incumbent=incumbent,
        paths=paths,
        selection_stability=stability,
    )
    verdict = "PROMOTE" if gate["passed"] else "RETAIN_INCUMBENT"
    production = selected if gate["passed"] else incumbent
    path_summaries = {
        f"{season}:{config_id}": {
            key: value
            for key, value in path.items()
            if key not in {"events"}
        }
        for (season, config_id), path in paths.items()
    }
    result = {
        "version": 1,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "status": "historically_calibrated" if gate["passed"] else "calibration_evidence",
        "production_changed": gate["passed"],
        "selected_configuration": {
            "config_id": selected.config_id,
            "horizon": selected.horizon,
            "decay": selected.decay,
        },
        "incumbent_configuration": {
            "config_id": incumbent.config_id,
            "horizon": incumbent.horizon,
            "decay": incumbent.decay,
        },
        "production_configuration": {
            "config_id": production.config_id,
            "horizon": production.horizon,
            "decay": production.decay,
        },
        "selection_seasons": list(SELECTION_SEASONS),
        "untouched_test_season": TEST_SEASON,
        "events": [START_EVENT, END_EVENT],
        "selection_ranking": ranking,
        "promotion_gate": gate,
        "fixture_response": coefficients,
        "path_summaries": path_summaries,
        "paths": {
            f"{season}:{config_id}": path
            for (season, config_id), path in paths.items()
        },
        "method": {
            "policy": "receding_horizon_ordinary_free_transfers",
            "initial_free_transfers": 0,
            "gw2_free_transfers": 1,
            "hits": False,
            "chips": False,
            "future_player_information": "frozen_at_origin_deadline",
            "future_fixture_information": "latest_archived_snapshot_at_or_before_deadline",
            "fixture_response_target": "out_of_fold_expected_points_only",
            "fixture_response_fit_seasons": list(SELECTION_SEASONS),
            "selection_objective": "80% mean season regret + 20% worst season regret",
        },
        "coverage": {
            season: {
                "fixture_snapshot_events": inputs["available_snapshots"][season],
                "maximum_snapshot_age_events": max(
                    path["maximum_fixture_snapshot_age_events"]
                    for (candidate, _), path in paths.items()
                    if candidate == season
                ),
                "historical_max_free_transfers": HISTORICAL_MAX_FREE_TRANSFERS[season],
            }
            for season in SEASONS
        },
        "artifacts": {
            "backtest_forecast": str(inputs["paths"]["forecast"]),
            "backtest_forecast_sha256": sha256_file(inputs["paths"]["forecast"]),
            "training_features": str(inputs["paths"]["features"]),
            "training_features_sha256": sha256_file(inputs["paths"]["features"]),
            "fixture_snapshots": str(inputs["paths"]["fixtures"]),
            "fixture_snapshots_sha256": sha256_file(inputs["paths"]["fixtures"]),
            "terminal_transfer_value": str(TRANSFER_VALUE_ARTIFACT),
            "terminal_transfer_value_sha256": sha256_file(TRANSFER_VALUE_ARTIFACT),
            "terminal_transfer_receipt_version": terminal_receipt.get("version"),
        },
        "limitations": [
            "Only three recent GW1-8 paths have complete enough point-in-time inputs.",
            "Future player forecasts freeze the origin player rate and vary only known fixtures.",
            "Ordinary free transfers are replayed; wildcards, hits and future prices are excluded.",
            "Overlapping football outcomes make eight event deltas a small serially correlated test.",
        ],
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render(result), encoding="utf-8")
    return result
