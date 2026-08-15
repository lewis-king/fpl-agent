from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb

from fplagent_data.http import sha256_file

from .appearance_role_challenger import ROLE_FEATURES, build_role_feature_table
from .horizon_decay_replay import (
    END_EVENT,
    PolicyConfig,
    _fixture_response_coefficients,
    _load_inputs,
    build_deadline_horizon_rows,
    run_policy_path,
)
from .market_transfer_replay import moving_block_mean_interval
from .models import TOP_K, _spearman, require_cuda
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules
from .transfer_value import load_terminal_free_transfer_curve

OUTPUT_DIR = MODEL_DATA / "lead_time_v1"
DATASET = OUTPUT_DIR / "lead-rows.parquet"
PREDICTIONS = OUTPUT_DIR / "predictions.parquet"
MODEL_FILE = OUTPUT_DIR / "models.joblib"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "lead-time-forecast-policy-replay.md"

TRAIN_SEASON = "2023-24"
SELECTION_SEASON = "2024-25"
TEST_SEASON = "2025-26"
SEASONS = (TRAIN_SEASON, SELECTION_SEASON, TEST_SEASON)
ORIGIN_EVENTS = tuple(range(1, END_EVENT + 1))
POSITIONS = ("GK", "DEF", "MID", "FWD")
BLEND_WEIGHTS = (0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0)
POLICY_CONFIG = PolicyConfig(8, 0.88)

ORIGIN_FEATURES = (
    "history_events",
    "player_days_since_last_event",
    "last_points",
    "form3_points",
    "form5_points",
    "form10_points",
    "form38_points",
    "last_minutes",
    "form3_minutes",
    "form5_minutes",
    "form10_minutes",
    "appearance_rate5",
    "start_rate5",
    "form5_goals",
    "form5_assists",
    "form5_xg",
    "form5_xa",
    "form10_goals",
    "form10_assists",
    "form10_xg",
    "form10_xa",
    "form38_goals",
    "form38_assists",
    "form38_xg",
    "form38_xa",
    "form38_minutes",
    "form5_bps",
    "form5_clean_sheets",
    "market_price",
    "ownership_percentile",
    "availability_chance",
    "penalty_order",
    "corner_order",
    "adjusted_team_attack",
    "adjusted_team_defence",
    "team_expected_goals",
    "team_expected_goals_against",
    "team_clean_sheet_probability",
    "team_promoted_prior",
    "team_rating_matches",
    "cold_start",
)

MODEL_FEATURES = (
    "baseline_expected_points",
    "origin_expected_points",
    "origin_p_play",
    "forecast_lead",
    "fixture_count",
    "home_fraction",
    "fixture_difficulty",
    *ORIGIN_FEATURES,
    *ROLE_FEATURES,
)


def _number(value: Any) -> float:
    return np.nan if value is None else float(value)


def _model_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray(
        [[_number(row.get(feature)) for feature in MODEL_FEATURES] for row in rows],
        dtype=np.float32,
    )


def _regressor(*, estimators: int, early_stopping: bool) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="reg:squarederror",
        eval_metric="rmse",
        n_estimators=estimators,
        learning_rate=0.035,
        max_depth=4,
        min_child_weight=10.0,
        subsample=0.85,
        colsample_bytree=0.82,
        reg_alpha=0.20,
        reg_lambda=8.0,
        tree_method="hist",
        device="cuda",
        random_state=20260823,
        n_jobs=8,
        early_stopping_rounds=40 if early_stopping else None,
    )


def decision_focus_mask(rows: list[dict[str, Any]]) -> np.ndarray:
    focus = np.zeros(len(rows), dtype=bool)
    grouped: dict[tuple[str, int, int, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[
            (
                str(row["season"]),
                int(row["origin_event"]),
                int(row["target_event"]),
                str(row["position"]),
            )
        ].append(index)
    for (_, _, _, position), indices in grouped.items():
        count = min(len(indices), 2 * TOP_K[position])
        points = sorted(
            indices,
            key=lambda index: (
                float(rows[index]["baseline_expected_points"]),
                -int(rows[index]["element"]),
            ),
        )[-count:]
        value = sorted(
            indices,
            key=lambda index: (
                float(rows[index]["baseline_expected_points"])
                / max(float(rows[index]["market_price"]), 1.0),
                -int(rows[index]["element"]),
            ),
        )[-count:]
        focus[np.asarray(sorted(set(points) | set(value)), dtype=np.int64)] = True
    return focus


def build_lead_dataset() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inputs = _load_inputs()
    coefficients = _fixture_response_coefficients(
        [row for row in inputs["forecasts"] if str(row["season"]) == TRAIN_SEASON],
        [row for row in inputs["features"] if str(row["season"]) == TRAIN_SEASON],
    )
    role_by_id = {
        int(row["row_id"]): row for row in build_role_feature_table().to_pylist()
    }
    output: list[dict[str, Any]] = []
    lineage = []
    for season in SEASONS:
        for origin in ORIGIN_EVENTS:
            horizon_rows, receipt = build_deadline_horizon_rows(
                season=season,
                origin_event=origin,
                horizon=8,
                end_event=min(38, origin + 7),
                forecast_by_event=inputs["forecast_by_event"],
                feature_by_key=inputs["feature_by_key"],
                fixture_by_snapshot=inputs["fixture_by_snapshot"],
                available_snapshots=inputs["available_snapshots"],
                coefficients=coefficients,
            )
            lineage.append({"season": season, **receipt})
            origin_forecast = {
                int(row["element"]): row
                for row in inputs["forecast_by_event"][(season, origin)]
            }
            for row in horizon_rows:
                target_event = int(row["event_number"])
                lead = target_event - origin
                if lead <= 0:
                    continue
                element = int(row["element"])
                origin_feature = inputs["feature_by_key"].get((season, origin, element))
                target_feature = inputs["feature_by_key"].get(
                    (season, target_event, element)
                )
                base = origin_forecast.get(element)
                if origin_feature is None or target_feature is None or base is None:
                    continue
                role = role_by_id[int(origin_feature["row_id"])]
                output.append(
                    {
                        "season": season,
                        "origin_event": origin,
                        "target_event": target_event,
                        "forecast_lead": lead,
                        "element": element,
                        "player_name": str(row["player_name"]),
                        "position": str(row["position"]),
                        "team_id": int(row["team_id"]),
                        "market_price": float(row["market_price"]),
                        "baseline_expected_points": float(row["expected_points"]),
                        "origin_expected_points": float(base["expected_points"]),
                        "origin_p_play": float(base["p_play"]),
                        "fixture_count": float(row["fixture_count"]),
                        "home_fraction": float(row["home_fraction"]),
                        "fixture_difficulty": float(row["fixture_difficulty"]),
                        "target_points": float(target_feature["target_points"]),
                        "target_minutes": float(target_feature["target_minutes"]),
                        **{
                            feature: origin_feature.get(feature)
                            for feature in ORIGIN_FEATURES
                        },
                        **{feature: role.get(feature) for feature in ROLE_FEATURES},
                    }
                )
    focus = decision_focus_mask(output)
    for index, selected in enumerate(focus):
        output[index]["decision_focus"] = bool(selected)
    return output, {
        "fixture_response_fit_season": TRAIN_SEASON,
        "fixture_response": coefficients,
        "snapshot_lineage": lineage,
        "maximum_snapshot_age_events": max(
            int(row["snapshot_age_events"]) for row in lineage
        ),
    }


def _group_spearman(
    rows: list[dict[str, Any]], actual: np.ndarray, predicted: np.ndarray
) -> float:
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(int(row["origin_event"]), int(row["target_event"]))].append(index)
    values = []
    for indices in grouped.values():
        if len(indices) < 3:
            continue
        local_actual = actual[indices]
        local_predicted = predicted[indices]
        if np.std(local_actual) < 1e-9 or np.std(local_predicted) < 1e-9:
            continue
        correlation = _spearman(local_actual, local_predicted)
        if correlation is not None:
            values.append(correlation)
    return float(np.mean(values)) if values else 0.0


def _top_k_points(rows: list[dict[str, Any]], actual: np.ndarray, predicted: np.ndarray) -> float:
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(int(row["origin_event"]), int(row["target_event"]))].append(index)
    values = []
    for indices in grouped.values():
        count = min(TOP_K[str(rows[indices[0]]["position"])], len(indices))
        selected = np.asarray(indices)[np.argsort(predicted[indices])[-count:]]
        values.append(float(actual[selected].mean()))
    return float(np.mean(values))


def _metrics(
    rows: list[dict[str, Any]], actual: np.ndarray, predicted: np.ndarray
) -> dict[str, float | int]:
    return {
        "rows": len(rows),
        "mae": float(np.mean(np.abs(actual - predicted))),
        "rmse": float(np.sqrt(np.mean(np.square(actual - predicted)))),
        "gameweek_spearman": _group_spearman(rows, actual, predicted),
        "top_k_actual_points": _top_k_points(rows, actual, predicted),
    }


def _fit_position(
    rows: list[dict[str, Any]], position: str
) -> tuple[dict[str, Any], list[dict[str, Any]], xgb.XGBRegressor]:
    local = [row for row in rows if row["position"] == position]
    matrix = _model_matrix(local)
    seasons = np.asarray([row["season"] for row in local], dtype=object)
    actual = np.asarray([row["target_points"] for row in local], dtype=np.float32)
    baseline = np.asarray(
        [row["baseline_expected_points"] for row in local], dtype=np.float32
    )
    focus = np.asarray([row["decision_focus"] for row in local], dtype=bool)
    train = seasons == TRAIN_SEASON
    selection_all = seasons == SELECTION_SEASON
    selection = selection_all & focus
    model = _regressor(estimators=800, early_stopping=True)
    model.fit(
        matrix[train],
        actual[train],
        eval_set=[(matrix[selection_all], actual[selection_all])],
        verbose=False,
    )
    raw_selection_all = np.clip(model.predict(matrix[selection_all]), 0.0, 15.0)
    raw_selection = raw_selection_all[focus[selection_all]]
    selection_rows = [row for row in local if row["season"] == SELECTION_SEASON and row["decision_focus"]]
    candidates = []
    for weight in BLEND_WEIGHTS:
        prediction = (
            (1.0 - weight) * baseline[selection] + weight * raw_selection
        )
        candidates.append(
            {
                "weight": weight,
                **_metrics(selection_rows, actual[selection], prediction),
            }
        )
    candidates.sort(
        key=lambda row: (
            -row["top_k_actual_points"],
            -row["gameweek_spearman"],
            row["mae"],
            row["weight"],
        )
    )
    selected = candidates[0]
    weight = float(selected["weight"])
    estimators = max(50, int(model.best_iteration) + 1)
    final_model = _regressor(estimators=estimators, early_stopping=False)
    final_train = np.isin(seasons, (TRAIN_SEASON, SELECTION_SEASON))
    final_model.fit(matrix[final_train], actual[final_train], verbose=False)
    test_all = seasons == TEST_SEASON
    raw_test_all = np.clip(final_model.predict(matrix[test_all]), 0.0, 15.0)

    predictions = []
    for season, indices, raw in (
        (SELECTION_SEASON, np.flatnonzero(selection_all), raw_selection_all),
        (TEST_SEASON, np.flatnonzero(test_all), raw_test_all),
    ):
        for offset, index in enumerate(indices):
            row = local[index]
            challenger = (1.0 - weight) * baseline[index] + weight * raw[offset]
            predictions.append(
                {
                    **{key: row[key] for key in (
                        "season",
                        "origin_event",
                        "target_event",
                        "forecast_lead",
                        "element",
                        "player_name",
                        "position",
                        "team_id",
                        "decision_focus",
                        "target_points",
                        "target_minutes",
                    )},
                    "baseline_expected_points": float(baseline[index]),
                    "raw_lead_expected_points": float(raw[offset]),
                    "challenger_expected_points": float(challenger),
                }
            )

    season_metrics = {}
    residual_by_lead = {}
    for season, raw in (
        (SELECTION_SEASON, raw_selection_all),
        (TEST_SEASON, raw_test_all),
    ):
        season_all = seasons == season
        mask = season_all & focus
        local_rows = [row for row in local if row["season"] == season and row["decision_focus"]]
        raw_focus = raw[focus[season_all]]
        challenger = (1.0 - weight) * baseline[mask] + weight * raw_focus
        season_metrics[season] = {
            "baseline": _metrics(local_rows, actual[mask], baseline[mask]),
            "challenger": _metrics(local_rows, actual[mask], challenger),
        }
        if season == SELECTION_SEASON:
            for lead in range(1, 8):
                lead_mask = np.asarray([int(row["forecast_lead"]) == lead for row in local_rows])
                residual_by_lead[str(lead)] = float(
                    np.std(actual[mask][lead_mask] - challenger[lead_mask])
                )
    ordered_sd = np.maximum.accumulate(
        [residual_by_lead[str(lead)] for lead in range(1, 8)]
    )
    residual_by_lead = {
        str(lead): float(ordered_sd[lead - 1]) for lead in range(1, 8)
    }
    selection_metrics = season_metrics[SELECTION_SEASON]
    test_metrics = season_metrics[TEST_SEASON]
    checks = {
        "nonzero_selection_weight": weight > 0.0,
        "selection_top_k_improves": (
            selection_metrics["challenger"]["top_k_actual_points"]
            > selection_metrics["baseline"]["top_k_actual_points"]
        ),
        "selection_mae_non_regression": (
            selection_metrics["challenger"]["mae"]
            <= selection_metrics["baseline"]["mae"]
        ),
        "frozen_top_k_improves": (
            test_metrics["challenger"]["top_k_actual_points"]
            > test_metrics["baseline"]["top_k_actual_points"]
        ),
        "frozen_mae_non_regression": (
            test_metrics["challenger"]["mae"] <= test_metrics["baseline"]["mae"]
        ),
        "frozen_rank_non_regression": (
            test_metrics["challenger"]["gameweek_spearman"]
            >= test_metrics["baseline"]["gameweek_spearman"]
        ),
    }
    selection_checks = {
        name: passed
        for name, passed in checks.items()
        if name.startswith("selection_") or name == "nonzero_selection_weight"
    }
    return (
        {
            "position": position,
            "selected_weight": weight,
            "selected_estimators": estimators,
            "selection_candidates": candidates,
            "metrics": season_metrics,
            "residual_sd_by_lead": residual_by_lead,
            "checks": checks,
            "selection_checks": selection_checks,
            "selection_passed": all(selection_checks.values()),
            "passed": all(checks.values()),
        },
        predictions,
        final_model,
    )


def apply_prediction_overrides(
    rows: list[dict[str, Any]],
    *,
    season: str,
    origin_event: int,
    prediction_by_key: dict[tuple[str, int, int, int], float],
    eligible_positions: tuple[str, ...],
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        target = int(row["event_number"])
        key = (season, origin_event, target, int(row["element"]))
        score = prediction_by_key.get(key)
        if target > origin_event and str(row["position"]) in eligible_positions and score is not None:
            output.append({**row, "expected_points": score, "robust_points": score})
        else:
            output.append(row)
    return output


def _adaptive_replay(
    *,
    inputs: dict[str, Any],
    coefficients: dict[str, dict[str, float | int]],
    predictions: list[dict[str, Any]],
    eligible_positions: tuple[str, ...],
) -> dict[str, Any]:
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers,
        rules=rules,
    )
    prediction_by_key = {
        (
            str(row["season"]),
            int(row["origin_event"]),
            int(row["target_event"]),
            int(row["element"]),
        ): float(row["challenger_expected_points"])
        for row in predictions
    }

    def transform(season: str, origin: int, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return apply_prediction_overrides(
            rows,
            season=season,
            origin_event=origin,
            prediction_by_key=prediction_by_key,
            eligible_positions=eligible_positions,
        )

    paths = {}
    for season in (SELECTION_SEASON, TEST_SEASON):
        paths[f"{season}:incumbent"] = run_policy_path(
            season=season,
            config=POLICY_CONFIG,
            inputs=inputs,
            coefficients=coefficients,
            terminal_curve=terminal_curve,
        )
        paths[f"{season}:challenger"] = run_policy_path(
            season=season,
            config=POLICY_CONFIG,
            inputs=inputs,
            coefficients=coefficients,
            terminal_curve=terminal_curve,
            row_transform=transform,
        )
    selection_delta = (
        paths[f"{SELECTION_SEASON}:challenger"]["net_points"]
        - paths[f"{SELECTION_SEASON}:incumbent"]["net_points"]
    )
    test_deltas = [
        challenger["net_points"] - incumbent["net_points"]
        for challenger, incumbent in zip(
            paths[f"{TEST_SEASON}:challenger"]["events"],
            paths[f"{TEST_SEASON}:incumbent"]["events"],
            strict=True,
        )
    ]
    interval = moving_block_mean_interval(
        test_deltas,
        block_length=2,
        seed=20260824,
    )
    checks = {
        "eligible_position_exists": bool(eligible_positions),
        "positive_selection_path": selection_delta > 0,
        "positive_frozen_test_path": sum(test_deltas) > 0,
        "frozen_test_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
    }
    return {
        "config": {
            "horizon": POLICY_CONFIG.horizon,
            "decay": POLICY_CONFIG.decay,
        },
        "checks": checks,
        "passed": all(checks.values()),
        "selection_total_delta": selection_delta,
        "frozen_test_total_delta": sum(test_deltas),
        "frozen_test_event_deltas": test_deltas,
        "frozen_test_interval": interval,
        "paths": paths,
        "terminal_transfer_curve_sha256": terminal_receipt.get("sha256"),
    }


def _render(result: dict[str, Any]) -> str:
    replay = result["adaptive_replay"]
    lines = [
        "# Lead-specific GW1–8 forecast challenger",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — statistically eligible positions: "
            f"{', '.join(result['eligible_positions']) or 'none'}. In a fresh decision at each "
            f"deadline, the challenger changed 2024/25 GW1–8 by "
            f"{replay['selection_total_delta']:+d} points and untouched 2025/26 GW1–8 by "
            f"{replay['frozen_test_total_delta']:+d}."
        ),
        "",
        (
            "Unlike the incumbent future-rate freeze used by the historical horizon calibration, "
            "this model is trained on player outcomes at each forecast distance. It receives only "
            "origin-deadline player/role information and the fixture schedule archived at or "
            "before that origin."
        ),
        "",
        "| Position | Blend | 2024/25 top-K Δ | 2025/26 top-K Δ | Gate |",
        "|---|---:|---:|---:|---|",
    ]
    for position in POSITIONS:
        row = result["positions"][position]
        selection = row["metrics"][SELECTION_SEASON]
        test = row["metrics"][TEST_SEASON]
        lines.append(
            f"| {position} | {row['selected_weight']:.2f} | "
            f"{selection['challenger']['top_k_actual_points'] - selection['baseline']['top_k_actual_points']:+.3f} | "
            f"{test['challenger']['top_k_actual_points'] - test['baseline']['top_k_actual_points']:+.3f} | "
            f"{'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Lead models are trained on 2023/24, tuned on 2024/25 and tested once on 2025/26.",
            "- Future fixture rows use only the latest archived snapshot at or before the decision.",
            "- The policy replay reoptimises the legal squad, XI, bench and captain every deadline.",
            (
                "- Passing this historical gate creates a bounded current-season shadow. It does "
                "not replace production until prospective receipts replicate the improvement."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_lead_time_challenger() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cuda = require_cuda()
    rows, lineage = build_lead_dataset()
    pq.write_table(pa.Table.from_pylist(rows), DATASET, compression="zstd")
    inputs = _load_inputs()
    coefficients = _fixture_response_coefficients(
        [row for row in inputs["forecasts"] if str(row["season"]) == TRAIN_SEASON],
        [row for row in inputs["features"] if str(row["season"]) == TRAIN_SEASON],
    )
    position_results = {}
    predictions = []
    models = {}
    for position in POSITIONS:
        local_result, local_predictions, model = _fit_position(rows, position)
        position_results[position] = local_result
        predictions.extend(local_predictions)
        models[position] = model
    # Position eligibility is frozen from the selection season. The untouched season may
    # validate or reject that already-declared set, but it must not choose the set it tests.
    eligible = tuple(
        position
        for position in POSITIONS
        if position_results[position]["selection_passed"]
    )
    replay = _adaptive_replay(
        inputs=inputs,
        coefficients=coefficients,
        predictions=predictions,
        eligible_positions=eligible,
    )
    pq.write_table(pa.Table.from_pylist(predictions), PREDICTIONS, compression="zstd")
    joblib.dump(
        {
            "version": 1,
            "features": MODEL_FEATURES,
            "eligible_positions": eligible,
            "positions": {
                position: {
                    "model": models[position],
                    "weight": position_results[position]["selected_weight"],
                    "residual_sd_by_lead": position_results[position]["residual_sd_by_lead"],
                }
                for position in POSITIONS
            },
        },
        MODEL_FILE,
        compress=3,
    )
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate_only",
        "verdict": (
            "PASS_HISTORICAL_HOLD_SHADOW"
            if replay["passed"]
            and all(position_results[position]["passed"] for position in eligible)
            else "RETAIN_INCUMBENT"
        ),
        "production_changed": False,
        "cuda": cuda,
        "eligible_positions": list(eligible),
        "features": list(MODEL_FEATURES),
        "positions": position_results,
        "adaptive_replay": replay,
        "lineage": lineage,
        "artifacts": {
            "dataset": str(DATASET),
            "dataset_sha256": sha256_file(DATASET),
            "predictions": str(PREDICTIONS),
            "predictions_sha256": sha256_file(PREDICTIONS),
            "model": str(MODEL_FILE),
            "model_sha256": sha256_file(MODEL_FILE),
        },
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
