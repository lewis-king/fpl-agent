from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb
from scipy.stats import poisson, rankdata
from sklearn.metrics import mean_absolute_error, mean_squared_error

from fplagent_data.http import sha256_file

from .component_models import (
    MODEL_DIR as COMPONENT_MODEL_DIR,
)
from .component_models import (
    TARGETS_FILE,
    _matrix,
    _numeric,
    _strings,
)
from .component_simulator import (
    CS_POINTS,
    GOAL_POINTS,
    _goal_regressor,
    _historical_goal_rows,
    calibrate_empirical_components,
)
from .market_odds import MARKET_RECEIPT, historical_market_goal_rates
from .models import BACKTEST_FORECAST, require_cuda
from .paths import MODEL_DATA, REPORTS

OUTPUT_DIR = MODEL_DATA / "component_backtest_v1"
OOF_FORECAST = OUTPUT_DIR / "rolling-player-components.parquet"
METRICS_JSON = OUTPUT_DIR / "metrics.json"
REPORT = REPORTS / "component-player-backtest.md"
TEST_SEASONS = ("2024-25", "2025-26")
TOP_K = {"GK": 5, "DEF": 15, "MID": 15, "FWD": 8}


def _minutes_classifier(seed: int) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=4,
        eval_metric="mlogloss",
        n_estimators=500,
        learning_rate=0.04,
        max_depth=4,
        min_child_weight=20.0,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.10,
        reg_lambda=8.0,
        tree_method="hist",
        device="cuda",
        random_state=seed,
        n_jobs=8,
    )


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return float("nan")
    return float(
        np.corrcoef(rankdata(left, method="average"), rankdata(right, method="average"))[0, 1]
    )


def _event_spearman(events: np.ndarray, actual: np.ndarray, predicted: np.ndarray) -> float:
    values = []
    for event in np.unique(events):
        selected = events == event
        value = _spearman(actual[selected], predicted[selected])
        if np.isfinite(value):
            values.append(value)
    return float(np.mean(values)) if values else float("nan")


def _top_k_actual(
    events: np.ndarray,
    positions: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
) -> tuple[float, dict[str, float]]:
    by_position: dict[str, list[float]] = defaultdict(list)
    for event in np.unique(events):
        for position, top_k in TOP_K.items():
            indices = np.flatnonzero((events == event) & (positions == position))
            if len(indices) < top_k:
                continue
            chosen = indices[np.argsort(predicted[indices])[-top_k:]]
            by_position[position].append(float(actual[chosen].mean()))
    output = {position: float(np.mean(values)) for position, values in by_position.items()}
    return float(np.mean(list(output.values()))), output


def _expected_floor_poisson(rate: np.ndarray, divisor: int, maximum: int = 20) -> np.ndarray:
    rate = np.clip(rate, 0.0, 15.0)
    output = np.zeros_like(rate, dtype=np.float64)
    for count in range(divisor, maximum + 1):
        output += (count // divisor) * poisson.pmf(count, rate)
    return output


def _oof_goal_rates() -> tuple[
    dict[tuple[str, int, int], float], dict[tuple[str, int, int], float]
]:
    metadata, seasons, target, matrix = _historical_goal_rows()
    team_rate = {}
    opponent_rate = {}
    for test_season in TEST_SEASONS:
        training = seasons < test_season
        testing = seasons == test_season
        medians = np.nanmedian(matrix[training], axis=0)
        training_matrix = np.where(np.isnan(matrix[training]), medians, matrix[training])
        testing_matrix = np.where(np.isnan(matrix[testing]), medians, matrix[testing])
        model = _goal_regressor(303_000 + int(test_season[:4]))
        model.fit(training_matrix, target[training], verbose=False)
        predicted = np.clip(model.predict(testing_matrix), 0.05, 6.0)
        fixture_sides: dict[tuple[str, int], list[tuple[int, float, int]]] = defaultdict(list)
        for local_offset, global_index in enumerate(np.flatnonzero(testing)):
            row = metadata[int(global_index)]
            key = (str(row["season"]), int(row["event"]), int(row["team_id"]))
            rate = float(predicted[local_offset])
            team_rate[key] = rate
            fixture_sides[(str(row["season"]), int(row["fixture_id"]))].append(
                (int(row["team_id"]), rate, int(row["event"]))
            )
        for (season, _), sides in fixture_sides.items():
            if len(sides) != 2:
                continue
            left, right = sides
            opponent_rate[(season, left[2], left[0])] = right[1]
            opponent_rate[(season, right[2], right[0])] = left[1]
    return team_rate, opponent_rate


def _component_oof() -> dict[tuple[str, int, int], dict[str, float]]:
    rows = pq.read_table(COMPONENT_MODEL_DIR / "rolling-backtest.parquet").to_pylist()
    output: dict[tuple[str, int, int], dict[str, float]] = defaultdict(dict)
    for row in rows:
        key = (str(row["season"]), int(row["event_number"]), int(row["element"]))
        output[key][str(row["component"])] = float(row["predicted"])
    return output


def _xp_oof() -> dict[tuple[str, int, int], float]:
    return {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row["expected_points"]
        )
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
    }


def _metrics(
    events: np.ndarray,
    positions: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
) -> dict[str, Any]:
    top_k, by_position = _top_k_actual(events, positions, actual, predicted)
    return {
        "rows": len(actual),
        "predicted_mean": float(predicted.mean()),
        "actual_mean": float(actual.mean()),
        "bias": float(np.mean(predicted - actual)),
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
        "event_spearman": _event_spearman(events, actual, predicted),
        "top_k_actual_points": top_k,
        "top_k_actual_by_position": by_position,
    }


def _reconstruct_expected_points(
    *,
    test_season: str,
    selected_rows: list[dict[str, Any]],
    selected_probabilities: np.ndarray,
    expected_minutes: np.ndarray,
    p_play: np.ndarray,
    appearance_points: np.ndarray,
    predicted_goals: np.ndarray,
    predicted_assists: np.ndarray,
    predicted_bonus: np.ndarray,
    predicted_saves: np.ndarray,
    empirical: Any,
    team_goal_rate: dict[tuple[str, int, int], float],
    opponent_goal_rate: dict[tuple[str, int, int], float],
) -> dict[str, np.ndarray]:
    group_indices: dict[tuple[int, int], list[int]] = defaultdict(list)
    for offset, row in enumerate(selected_rows):
        group_indices[(int(row["event_number"]), int(row["team_id"]))].append(offset)
    normalized_goals = np.zeros(len(selected_rows))
    normalized_assists = np.zeros(len(selected_rows))
    for (event, team_id), indices in group_indices.items():
        index_array = np.asarray(indices, dtype=np.int64)
        rate = team_goal_rate[(test_season, event, team_id)]
        normalized_goals[index_array] = (
            rate * predicted_goals[index_array] / max(predicted_goals[index_array].sum(), 1e-9)
        )
        normalized_assists[index_array] = (
            rate
            * empirical.assist_per_goal
            * predicted_assists[index_array]
            / max(predicted_assists[index_array].sum(), 1e-9)
        )
    positions = np.asarray([str(row["position"]) for row in selected_rows])
    opponent_rates = np.asarray(
        [
            opponent_goal_rate[
                (test_season, int(row["event_number"]), int(row["team_id"]))
            ]
            for row in selected_rows
        ]
    )
    clean_sheet_points = np.asarray([CS_POINTS[position] for position in positions]) * (
        selected_probabilities[:, 2] * np.exp(-opponent_rates * 75.0 / 90.0)
        + selected_probabilities[:, 3] * np.exp(-opponent_rates)
    )
    conceded_points = np.zeros(len(selected_rows))
    defensive = np.isin(positions, ["GK", "DEF"])
    for class_index, minute_fraction in ((1, 28 / 90), (2, 75 / 90), (3, 1.0)):
        conceded_points[defensive] -= selected_probabilities[defensive, class_index] * (
            _expected_floor_poisson(opponent_rates[defensive] * minute_fraction, divisor=2)
        )
    conditional_saves = predicted_saves / np.maximum(p_play, 0.005)
    save_points = np.where(
        positions == "GK",
        p_play * _expected_floor_poisson(conditional_saves, divisor=3),
        0.0,
    )
    dc_points = np.zeros(len(selected_rows))
    for offset, position in enumerate(positions):
        if position == "GK":
            continue
        for class_index in (1, 2, 3):
            dc_points[offset] += (
                2.0
                * selected_probabilities[offset, class_index]
                * empirical.dc_probability.get((position, class_index), 0.0)
            )
    discipline = (
        np.asarray(
            [
                -empirical.yellow_rate90[position]
                - 3.0 * empirical.red_rate90[position]
                - 2.0 * empirical.own_goal_rate90[position]
                - 2.0 * empirical.penalty_miss_rate90[position]
                for position in positions
            ]
        )
        * expected_minutes
        / 90.0
    )
    expected = (
        appearance_points
        + normalized_goals * np.asarray([GOAL_POINTS[position] for position in positions])
        + normalized_assists * 3.0
        + clean_sheet_points
        + conceded_points
        + save_points
        + predicted_bonus
        + dc_points
        + discipline
    )
    return {
        "expected": expected,
        "goals": normalized_goals,
        "assists": normalized_assists,
        "clean_sheet": clean_sheet_points,
        "conceded": conceded_points,
        "saves": save_points,
        "defensive_contributions": dc_points,
        "discipline": discipline,
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Season-forward player-component backtest",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{'PASS' if result['gate']['passed'] else 'FAIL'}** — validation selected raw "
            f"weight {result['blend_selection']['selected_raw_weight']:.2f}; on the untouched "
            f"2025/26 test this produced {result['blend_selection']['test_top_k_actual_points']:.3f} "
            f"top-k actual points versus {result['blend_selection']['test_xp_top_k_actual_points']:.3f} "
            "for incumbent xP."
        ),
        "",
        "## Season-forward results",
        "",
        "| Season | Forecast | MAE | Event Spearman | Top-k actual | Bias |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for season in TEST_SEASONS:
        for name in ("component", "market_component", "xp"):
            row = result["season_forward"][season][name]
            lines.append(
                f"| {season} | {name} | {row['mae']:.3f} | "
                f"{row['event_spearman']:.3f} | {row['top_k_actual_points']:.3f} | "
                f"{row['bias']:+.3f} |"
            )
    lines.extend(
        [
            "",
            "## Blend selection",
            "",
            "The raw/xP blend weight was chosen only on 2024/25 top-k realised points, then frozen for 2025/26. This avoids choosing a compromise after seeing the test season.",
            "",
            "| Raw weight | 2024/25 top-k actual | 2025/26 top-k actual |",
            "|---:|---:|---:|",
        ]
    )
    for row in result["blend_selection"]["weights"]:
        lines.append(
            f"| {row['raw_weight']:.2f} | {row['validation_top_k_actual_points']:.3f} | "
            f"{row['test_top_k_actual_points']:.3f} |"
        )
    market = result["market_challenger"]
    lines.extend(
        [
            "",
            "## Pre-closing market challenger",
            "",
            (
                f"Validation selected market-component weight "
                f"{market['selected_raw_weight']:.2f}. Its untouched 2025/26 top-k actual "
                f"score was {market['test_top_k_actual_points']:.3f}, versus "
                f"{market['test_xp_top_k_actual_points']:.3f} for incumbent xP. It remains "
                "shadow-only pending an exact legal policy replay and a current deadline-safe feed."
            ),
            "",
            "## Scope and limitations",
            "",
            "This is a deadline-safe expected-value reconstruction, not a replay using known match outcomes. Team goal rates, minutes classes and player event components are independently fit before each test season. Goals and assists are normalized to predicted team totals; clean sheets and concessions come from opponent Poisson rates. Goal timing, exact BPS ties and defensive-contribution micro-events remain approximations.",
            "",
        ]
    )
    return "\n".join(lines)


def run_component_player_backtest(seed: int = 20260802) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cuda = require_cuda()
    table = pq.read_table(TARGETS_FILE)
    matrix = _matrix(table)
    seasons = _strings(table, "season")
    minute_classes = _numeric(table, "minutes_class").astype(np.int32)
    team_goal_rate, opponent_goal_rate = _oof_goal_rates()
    market_team_goal_rate, market_opponent_goal_rate = historical_market_goal_rates()
    component_oof = _component_oof()
    xp_oof = _xp_oof()
    empirical = calibrate_empirical_components()
    rows = table.to_pylist()
    output_rows = []

    for split_offset, test_season in enumerate(TEST_SEASONS):
        training = seasons < test_season
        testing = seasons == test_season
        minutes_model = _minutes_classifier(seed + 700 + split_offset)
        minutes_model.fit(matrix[training], minute_classes[training], verbose=False)
        probabilities = minutes_model.predict_proba(matrix[testing])
        test_indices = np.flatnonzero(testing)
        usable_local = []
        for local_offset, global_index in enumerate(test_indices):
            row = rows[int(global_index)]
            key = (test_season, int(row["event_number"]), int(row["element"]))
            team_key = (test_season, int(row["event_number"]), int(row["team_id"]))
            if (
                float(row["fixture_count"]) == 1.0
                and key in component_oof
                and key in xp_oof
                and team_key in team_goal_rate
                and team_key in opponent_goal_rate
                and team_key in market_team_goal_rate
                and team_key in market_opponent_goal_rate
            ):
                usable_local.append(local_offset)
        usable_local_array = np.asarray(usable_local, dtype=np.int64)
        global_indices = test_indices[usable_local_array]
        selected_rows = [rows[int(index)] for index in global_indices]
        selected_probabilities = probabilities[usable_local_array]
        expected_minutes = (
            selected_probabilities[:, 1] * 28.0
            + selected_probabilities[:, 2] * 75.0
            + selected_probabilities[:, 3] * 90.0
        )
        p_play = selected_probabilities[:, 1:].sum(axis=1)
        appearance_points = (
            selected_probabilities[:, 1]
            + 2.0 * selected_probabilities[:, 2]
            + 2.0 * selected_probabilities[:, 3]
        )
        predicted_goals = np.asarray(
            [
                component_oof[(test_season, int(row["event_number"]), int(row["element"]))]["goals"]
                for row in selected_rows
            ]
        )
        predicted_assists = np.asarray(
            [
                component_oof[(test_season, int(row["event_number"]), int(row["element"]))][
                    "assists"
                ]
                for row in selected_rows
            ]
        )
        predicted_bonus = np.asarray(
            [
                component_oof[(test_season, int(row["event_number"]), int(row["element"]))]["bonus"]
                for row in selected_rows
            ]
        )
        predicted_saves = np.asarray(
            [
                component_oof[(test_season, int(row["event_number"]), int(row["element"]))]["saves"]
                for row in selected_rows
            ]
        )
        internal = _reconstruct_expected_points(
            test_season=test_season,
            selected_rows=selected_rows,
            selected_probabilities=selected_probabilities,
            expected_minutes=expected_minutes,
            p_play=p_play,
            appearance_points=appearance_points,
            predicted_goals=predicted_goals,
            predicted_assists=predicted_assists,
            predicted_bonus=predicted_bonus,
            predicted_saves=predicted_saves,
            empirical=empirical,
            team_goal_rate=team_goal_rate,
            opponent_goal_rate=opponent_goal_rate,
        )
        market = _reconstruct_expected_points(
            test_season=test_season,
            selected_rows=selected_rows,
            selected_probabilities=selected_probabilities,
            expected_minutes=expected_minutes,
            p_play=p_play,
            appearance_points=appearance_points,
            predicted_goals=predicted_goals,
            predicted_assists=predicted_assists,
            predicted_bonus=predicted_bonus,
            predicted_saves=predicted_saves,
            empirical=empirical,
            team_goal_rate=market_team_goal_rate,
            opponent_goal_rate=market_opponent_goal_rate,
        )
        for offset, row in enumerate(selected_rows):
            key = (test_season, int(row["event_number"]), int(row["element"]))
            output_rows.append(
                {
                    "season": test_season,
                    "event_number": int(row["event_number"]),
                    "element": int(row["element"]),
                    "player_name": row["player_name"],
                    "position": row["position"],
                    "team_id": int(row["team_id"]),
                    "target_points": float(row["target_points"]),
                    "component_expected_points": float(internal["expected"][offset]),
                    "market_component_expected_points": float(market["expected"][offset]),
                    "xp_expected_points": xp_oof[key],
                    "expected_minutes": float(expected_minutes[offset]),
                    "p_play": float(p_play[offset]),
                    "expected_goals": float(internal["goals"][offset]),
                    "expected_assists": float(internal["assists"][offset]),
                    "market_expected_goals": float(market["goals"][offset]),
                    "market_expected_assists": float(market["assists"][offset]),
                    "expected_bonus": float(predicted_bonus[offset]),
                    "appearance_points": float(appearance_points[offset]),
                    "clean_sheet_points": float(internal["clean_sheet"][offset]),
                    "conceded_points": float(internal["conceded"][offset]),
                    "save_points": float(internal["saves"][offset]),
                    "dc_points": float(internal["defensive_contributions"][offset]),
                    "discipline_points": float(internal["discipline"][offset]),
                }
            )
    pq.write_table(pa.Table.from_pylist(output_rows), OOF_FORECAST, compression="zstd")
    season_forward = {}
    arrays_by_season = {}
    for season in TEST_SEASONS:
        season_rows = [row for row in output_rows if row["season"] == season]
        events = np.asarray([row["event_number"] for row in season_rows])
        positions = np.asarray([row["position"] for row in season_rows])
        actual = np.asarray([row["target_points"] for row in season_rows])
        component = np.asarray([row["component_expected_points"] for row in season_rows])
        market_component = np.asarray(
            [row["market_component_expected_points"] for row in season_rows]
        )
        xp = np.asarray([row["xp_expected_points"] for row in season_rows])
        season_forward[season] = {
            "component": _metrics(events, positions, actual, component),
            "market_component": _metrics(events, positions, actual, market_component),
            "xp": _metrics(events, positions, actual, xp),
        }
        arrays_by_season[season] = (
            events,
            positions,
            actual,
            component,
            market_component,
            xp,
        )
    validation = arrays_by_season["2024-25"]
    testing = arrays_by_season["2025-26"]
    weight_rows = []
    for raw_weight in np.linspace(0.0, 1.0, 21):
        validation_prediction = raw_weight * validation[3] + (1.0 - raw_weight) * validation[5]
        test_prediction = raw_weight * testing[3] + (1.0 - raw_weight) * testing[5]
        validation_top, _ = _top_k_actual(
            validation[0], validation[1], validation[2], validation_prediction
        )
        test_top, _ = _top_k_actual(testing[0], testing[1], testing[2], test_prediction)
        weight_rows.append(
            {
                "raw_weight": float(raw_weight),
                "validation_top_k_actual_points": validation_top,
                "test_top_k_actual_points": test_top,
            }
        )
    selected_weight = max(
        weight_rows,
        key=lambda row: (row["validation_top_k_actual_points"], -row["raw_weight"]),
    )
    xp_test_top = next(row for row in weight_rows if row["raw_weight"] == 0.0)[
        "test_top_k_actual_points"
    ]
    market_weight_rows = []
    for raw_weight in np.linspace(0.0, 1.0, 21):
        validation_prediction = raw_weight * validation[4] + (1.0 - raw_weight) * validation[5]
        test_prediction = raw_weight * testing[4] + (1.0 - raw_weight) * testing[5]
        validation_top, _ = _top_k_actual(
            validation[0], validation[1], validation[2], validation_prediction
        )
        test_top, _ = _top_k_actual(
            testing[0], testing[1], testing[2], test_prediction
        )
        market_weight_rows.append(
            {
                "raw_weight": float(raw_weight),
                "validation_top_k_actual_points": validation_top,
                "test_top_k_actual_points": test_top,
            }
        )
    selected_market_weight = max(
        market_weight_rows,
        key=lambda row: (row["validation_top_k_actual_points"], -row["raw_weight"]),
    )
    gate = {
        "selected_weight_beats_xp_on_test_top_k": (
            selected_weight["test_top_k_actual_points"] >= xp_test_top
        ),
        "component_event_models_available": True,
    }
    gate["passed"] = bool(all(gate.values()))
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "cuda": cuda,
        "season_forward": season_forward,
        "blend_selection": {
            "validation_season": "2024-25",
            "test_season": "2025-26",
            "selected_raw_weight": selected_weight["raw_weight"],
            "validation_top_k_actual_points": selected_weight["validation_top_k_actual_points"],
            "test_top_k_actual_points": selected_weight["test_top_k_actual_points"],
            "test_xp_top_k_actual_points": xp_test_top,
            "weights": weight_rows,
        },
        "market_challenger": {
            "status": "shadow",
            "validation_season": "2024-25",
            "test_season": "2025-26",
            "selected_raw_weight": selected_market_weight["raw_weight"],
            "validation_top_k_actual_points": selected_market_weight[
                "validation_top_k_actual_points"
            ],
            "test_top_k_actual_points": selected_market_weight["test_top_k_actual_points"],
            "test_xp_top_k_actual_points": xp_test_top,
            "weights": market_weight_rows,
            "gate": {
                "selected_weight_beats_xp_on_test_top_k": (
                    selected_market_weight["test_top_k_actual_points"] >= xp_test_top
                ),
                "legal_policy_replay_required": True,
                "current_deadline_safe_feed_required": True,
            },
        },
        "gate": gate,
        "artifacts": {
            "targets_sha256": sha256_file(TARGETS_FILE),
            "component_oof_sha256": sha256_file(COMPONENT_MODEL_DIR / "rolling-backtest.parquet"),
            "xp_oof_sha256": sha256_file(BACKTEST_FORECAST),
            "market_goal_rate_receipt_sha256": sha256_file(MARKET_RECEIPT),
            "output_sha256": sha256_file(OOF_FORECAST),
        },
    }
    METRICS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
