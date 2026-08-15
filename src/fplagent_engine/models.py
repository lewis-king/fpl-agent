from __future__ import annotations

import hashlib
import json
import os
import subprocess
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import xgboost as xgb
from scipy.stats import rankdata
from sklearn.metrics import log_loss, mean_absolute_error, mean_squared_error

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file

from .appearance_calibration import (
    CALIBRATION_FILE,
    calibrate_minute_probabilities,
    load_appearance_calibration,
)
from .features import (
    CURRENT_FEATURES,
    MODEL_FEATURES,
    POSITIONS,
    TRAINING_FEATURES,
    assert_independent_forecast_features,
)
from .paths import ARTIFACTS, FORECASTS, ensure_engine_layout

MODEL_DIR = ARTIFACTS / "forecast_v2"
MODEL_FILE = MODEL_DIR / "models.joblib"
METRICS_FILE = MODEL_DIR / "metrics.json"
CANDIDATE_METRICS_FILE = MODEL_DIR / "candidate-metrics.json"
CURRENT_FORECAST = FORECASTS / "2026-27-preseason.parquet"
CURRENT_FORECAST_MANIFEST = FORECASTS / "2026-27-preseason-manifest.json"
BACKTEST_FORECAST = FORECASTS / "rolling-backtest.parquet"

TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
SEEDS = (17, 43)
SEASON_DECAY = float(os.environ.get("FPLAGENT_SEASON_DECAY", "1.0"))
TOP_K = {"GK": 5, "DEF": 15, "MID": 15, "FWD": 8}


def _numeric(table: pa.Table, name: str) -> np.ndarray:
    column = pc.cast(table[name], pa.float32(), safe=False).combine_chunks()
    return column.to_numpy(zero_copy_only=False)


def _strings(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(table[name].to_pylist(), dtype=object)


def _matrix(table: pa.Table, feature_names: tuple[str, ...] = MODEL_FEATURES) -> np.ndarray:
    assert_independent_forecast_features(feature_names)
    return np.column_stack([_numeric(table, name) for name in feature_names]).astype(
        np.float32, copy=False
    )


def _gpu_name() -> str:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def require_cuda() -> dict[str, str]:
    """Fail unless the installed XGBoost wheel performs a real CUDA fit."""
    gpu = _gpu_name()
    features = np.asarray([[0.0], [1.0], [2.0], [3.0]], dtype=np.float32)
    target = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = xgb.XGBRegressor(
            n_estimators=2,
            max_depth=2,
            tree_method="hist",
            device="cuda",
            random_state=7,
        )
        model.fit(features, target, verbose=False)
    warning_text = "\n".join(str(item.message) for item in caught)
    config = json.loads(model.get_booster().save_config())
    device = config["learner"]["generic_param"]["device"]
    if not device.startswith("cuda") or "No visible GPU" in warning_text:
        raise RuntimeError(
            "CUDA was requested but XGBoost did not retain a CUDA device: "
            f"device={device!r}, warnings={warning_text!r}"
        )
    return {
        "gpu": gpu,
        "xgboost": xgb.__version__,
        "xgboost_device": device,
    }


def _regressor(seed: int, estimators: int, early_stopping: bool) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="reg:squarederror",
        eval_metric="rmse",
        n_estimators=estimators,
        learning_rate=0.035,
        max_depth=5,
        min_child_weight=8.0,
        subsample=0.82,
        colsample_bytree=0.82,
        reg_alpha=0.15,
        reg_lambda=6.0,
        tree_method="hist",
        device="cuda",
        random_state=seed,
        n_jobs=8,
        early_stopping_rounds=50 if early_stopping else None,
    )


def _classifier(seed: int, estimators: int, early_stopping: bool) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=4,
        eval_metric="mlogloss",
        n_estimators=estimators,
        learning_rate=0.04,
        max_depth=4,
        min_child_weight=8.0,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.1,
        reg_lambda=6.0,
        tree_method="hist",
        device="cuda",
        random_state=seed,
        n_jobs=8,
        early_stopping_rounds=40 if early_stopping else None,
    )


def _spearman(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 3 or np.std(left) < 1e-9 or np.std(right) < 1e-9:
        return None
    # Average ranks are essential here: FPL points and rolling-form baselines
    # contain many ties. Breaking them by row order creates a falsely strong
    # rank correlation because both arrays share that arbitrary ordering.
    left_rank = rankdata(left, method="average")
    right_rank = rankdata(right, method="average")
    return float(np.corrcoef(left_rank, right_rank)[0, 1])


def _gameweek_spearman(events: np.ndarray, actual: np.ndarray, predicted: np.ndarray) -> float:
    values = []
    for event in np.unique(events):
        mask = events == event
        value = _spearman(actual[mask], predicted[mask])
        if value is not None:
            values.append(value)
    return float(np.mean(values)) if values else float("nan")


def _season_weights(seasons: np.ndarray, selected: np.ndarray) -> np.ndarray:
    years = np.asarray([int(str(season)[:4]) for season in seasons[selected]])
    return np.power(SEASON_DECAY, years.max() - years).astype(np.float32)


def _predict_hurdle(
    points_model: xgb.XGBRegressor,
    minutes_model: xgb.XGBClassifier,
    matrix: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    probability = minutes_model.predict_proba(matrix)
    conditional = points_model.predict(matrix)
    expected = probability[:, 1:].sum(axis=1) * conditional
    return probability, conditional, expected


def _availability_adjusted_form(form5: np.ndarray, availability: np.ndarray) -> np.ndarray:
    return form5 * np.clip(availability / 100.0, 0.0, 1.0)


def _blend(raw: np.ndarray, baseline: np.ndarray, model_weight: float) -> np.ndarray:
    output = raw.copy()
    available = np.isfinite(baseline)
    output[available] = model_weight * raw[available] + (1.0 - model_weight) * baseline[available]
    return output


def _choose_blend_weight(
    events: np.ndarray,
    actual: np.ndarray,
    raw: np.ndarray,
    baseline: np.ndarray,
) -> float:
    candidates = []
    for weight in np.linspace(0.0, 1.0, 21):
        predicted = _blend(raw, baseline, float(weight))
        candidates.append(
            (
                _gameweek_spearman(events, actual, predicted),
                -(mean_squared_error(actual, predicted) ** 0.5),
                float(weight),
            )
        )
    return max(candidates)[2]


def _mean_top_k_points(
    events: np.ndarray, actual: np.ndarray, predicted: np.ndarray, top_k: int
) -> float:
    values = []
    for event in np.unique(events):
        mask = np.flatnonzero(events == event)
        selected = mask[np.argsort(predicted[mask])[-top_k:]]
        values.append(float(actual[selected].mean()))
    return float(np.mean(values))


def _backtest(
    matrix: np.ndarray,
    seasons: np.ndarray,
    positions: np.ndarray,
    events: np.ndarray,
    target_points: np.ndarray,
    target_minutes: np.ndarray,
    minute_classes: np.ndarray,
    form5: np.ndarray,
    availability: np.ndarray,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    season_order = sorted(set(seasons.tolist()))
    for test_season in TEST_SEASONS:
        prior = [season for season in season_order if season < test_season]
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        if not training_seasons:
            continue
        for position in POSITIONS:
            train = np.isin(seasons, training_seasons) & (positions == position)
            validation = (seasons == validation_season) & (positions == position)
            test = (seasons == test_season) & (positions == position)
            train_played = train & (target_minutes > 0)
            validation_played = validation & (target_minutes > 0)
            if train_played.sum() < 500 or test.sum() < 100:
                continue

            points_model = _regressor(SEEDS[0], 1200, early_stopping=True)
            points_model.fit(
                matrix[train_played],
                target_points[train_played],
                sample_weight=_season_weights(seasons, train_played),
                eval_set=[(matrix[validation_played], target_points[validation_played])],
                verbose=False,
            )
            minutes_model = _classifier(SEEDS[0], 900, early_stopping=True)
            minutes_model.fit(
                matrix[train],
                minute_classes[train],
                sample_weight=_season_weights(seasons, train),
                eval_set=[(matrix[validation], minute_classes[validation])],
                verbose=False,
            )
            probability, _, expected = _predict_hurdle(points_model, minutes_model, matrix[test])
            play_probability = probability[:, 1:].sum(axis=1)
            baseline = _availability_adjusted_form(form5[test], availability[test])
            raw_expected = expected
            actual = target_points[test]
            baseline_for_metrics = np.nan_to_num(baseline, nan=0.0)
            top_k = TOP_K[position]
            test_events = events[test]
            gw1 = test_events == 1
            played_actual = (target_minutes[test] > 0).astype(np.float32)
            result = {
                "season": test_season,
                "position": position,
                "rows": int(test.sum()),
                "blend_model_weight": 1.0,
                "mae": float(mean_absolute_error(actual, expected)),
                "rmse": float(mean_squared_error(actual, expected) ** 0.5),
                "mean_gameweek_spearman": _gameweek_spearman(events[test], actual, expected),
                "top_k": top_k,
                "top_k_actual_points": _mean_top_k_points(events[test], actual, expected, top_k),
                "raw_mae": float(mean_absolute_error(actual, raw_expected)),
                "raw_rmse": float(mean_squared_error(actual, raw_expected) ** 0.5),
                "raw_mean_gameweek_spearman": _gameweek_spearman(
                    events[test], actual, raw_expected
                ),
                "raw_top_k_actual_points": _mean_top_k_points(
                    events[test], actual, raw_expected, top_k
                ),
                "form5_mae": float(mean_absolute_error(actual, baseline_for_metrics)),
                "form5_rmse": float(mean_squared_error(actual, baseline_for_metrics) ** 0.5),
                "form5_mean_gameweek_spearman": _gameweek_spearman(
                    events[test], actual, baseline_for_metrics
                ),
                "form5_top_k_actual_points": _mean_top_k_points(
                    events[test], actual, baseline_for_metrics, top_k
                ),
                "play_brier": float(np.mean(np.square(play_probability - played_actual))),
                "gw1_mae": float(mean_absolute_error(actual[gw1], expected[gw1])),
                "gw1_mean_spearman": _spearman(actual[gw1], expected[gw1]),
                "gw1_top_k_actual_points": _mean_top_k_points(
                    test_events[gw1], actual[gw1], expected[gw1], top_k
                ),
                "gw1_form5_mae": float(mean_absolute_error(actual[gw1], baseline_for_metrics[gw1])),
                "gw1_form5_mean_spearman": _spearman(actual[gw1], baseline_for_metrics[gw1]),
                "gw1_form5_top_k_actual_points": _mean_top_k_points(
                    test_events[gw1],
                    actual[gw1],
                    baseline_for_metrics[gw1],
                    top_k,
                ),
                "gw1_play_brier": float(
                    np.mean(np.square(play_probability[gw1] - played_actual[gw1]))
                ),
                "minutes_log_loss": float(
                    log_loss(minute_classes[test], probability, labels=[0, 1, 2, 3])
                ),
                "points_best_iteration": int(
                    points_model.best_iteration
                    if points_model.best_iteration is not None
                    else points_model.n_estimators - 1
                ),
                "minutes_best_iteration": int(
                    minutes_model.best_iteration
                    if minutes_model.best_iteration is not None
                    else minutes_model.n_estimators - 1
                ),
            }
            results.append(result)
            for global_index, predicted, reference, play in zip(
                np.flatnonzero(test),
                expected,
                baseline_for_metrics,
                play_probability,
                strict=True,
            ):
                predictions.append(
                    {
                        "row_index": int(global_index),
                        "expected_points": float(predicted),
                        "form5_expected_points": float(reference),
                        "p_play": float(play),
                    }
                )
    return results, predictions


def train() -> dict[str, Any]:
    ensure_engine_layout()
    if not TRAINING_FEATURES.exists():
        raise FileNotFoundError("Training features missing; run fplagent prepare first")
    gpu = require_cuda()
    table = pq.read_table(TRAINING_FEATURES)
    matrix = _matrix(table)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _numeric(table, "event_number").astype(np.int16)
    target_points = _numeric(table, "target_points")
    target_minutes = _numeric(table, "target_minutes")
    minute_classes = _numeric(table, "minutes_class").astype(np.int32)
    form5 = _numeric(table, "form5_points")
    availability = _numeric(table, "availability_chance")

    backtests, backtest_predictions = _backtest(
        matrix,
        seasons,
        positions,
        events,
        target_points,
        target_minutes,
        minute_classes,
        form5,
        availability,
    )
    best_points = [item["points_best_iteration"] for item in backtests]
    best_minutes = [item["minutes_best_iteration"] for item in backtests]
    backtest_gate = {
        "slices": len(backtests),
        "mae_wins_vs_form5": sum(item["mae"] < item["form5_mae"] for item in backtests),
        "rank_wins_vs_form5": sum(
            item["mean_gameweek_spearman"] >= item["form5_mean_gameweek_spearman"]
            for item in backtests
        ),
        "top_k_wins_vs_form5": sum(
            item["top_k_actual_points"] >= item["form5_top_k_actual_points"] for item in backtests
        ),
        "gw1_top_k_wins_vs_form5": sum(
            item["gw1_top_k_actual_points"] >= item["gw1_form5_top_k_actual_points"]
            for item in backtests
        ),
        "mean_gw1_top_k_lift": float(
            np.mean(
                [
                    item["gw1_top_k_actual_points"] - item["gw1_form5_top_k_actual_points"]
                    for item in backtests
                ]
            )
        ),
        "mean_top_k_lift": float(
            np.mean(
                [
                    item["top_k_actual_points"] - item["form5_top_k_actual_points"]
                    for item in backtests
                ]
            )
        ),
    }
    backtest_gate["passed"] = (
        backtest_gate["slices"] == 12
        and backtest_gate["mae_wins_vs_form5"] >= 10
        and backtest_gate["rank_wins_vs_form5"] >= 6
        and backtest_gate["top_k_wins_vs_form5"] >= 10
        and backtest_gate["mean_top_k_lift"] > 0
        and backtest_gate["gw1_top_k_wins_vs_form5"] >= 7
        and backtest_gate["mean_gw1_top_k_lift"] > 0
    )
    if not backtest_gate["passed"]:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        CANDIDATE_METRICS_FILE.write_text(
            json.dumps(
                {"backtest_gate": backtest_gate, "backtests": backtests},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            "Forecast model failed the historical decision gate: "
            + json.dumps(backtest_gate, sort_keys=True)
        )
    metadata = table.select(
        [
            "season",
            "event_number",
            "element",
            "player_name",
            "position",
            "team_id",
            "market_price",
            "target_points",
        ]
    ).to_pylist()
    backtest_rows = []
    for prediction in backtest_predictions:
        row = dict(metadata[prediction.pop("row_index")])
        row.update(prediction)
        backtest_rows.append(row)
    pq.write_table(pa.Table.from_pylist(backtest_rows), BACKTEST_FORECAST, compression="zstd")
    point_estimators = max(250, int(np.median(best_points)) + 1) if best_points else 600
    minute_estimators = max(200, int(np.median(best_minutes)) + 1) if best_minutes else 450

    blend_weights = dict.fromkeys(POSITIONS, 1.0)
    bundle: dict[str, Any] = {
        "version": "forecast_v3_opponent_adjusted",
        "created_at": datetime.now(UTC).isoformat(),
        "features": MODEL_FEATURES,
        "gpu": gpu,
        "positions": {},
    }
    for position in POSITIONS:
        selected = positions == position
        played = selected & (target_minutes > 0)
        if played.sum() < 500:
            raise ValueError(f"Insufficient played rows for {position}: {played.sum()}")
        point_models = []
        minute_models = []
        for seed in SEEDS:
            point_model = _regressor(seed, point_estimators, early_stopping=False)
            point_model.fit(
                matrix[played],
                target_points[played],
                sample_weight=_season_weights(seasons, played),
                verbose=False,
            )
            minute_model = _classifier(seed, minute_estimators, early_stopping=False)
            minute_model.fit(
                matrix[selected],
                minute_classes[selected],
                sample_weight=_season_weights(seasons, selected),
                verbose=False,
            )
            point_models.append(point_model)
            minute_models.append(minute_model)
        bundle["positions"][position] = {
            "point_models": point_models,
            "minute_models": minute_models,
            "training_rows": int(selected.sum()),
            "played_rows": int(played.sum()),
            "blend_model_weight": blend_weights[position],
        }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_FILE, compress=3)
    summary = {
        "model_version": bundle["version"],
        "created_at": bundle["created_at"],
        "gpu": gpu,
        "training_rows": len(table),
        "feature_count": len(MODEL_FEATURES),
        "point_estimators": point_estimators,
        "minute_estimators": minute_estimators,
        "season_decay": SEASON_DECAY,
        "blend_model_weights": blend_weights,
        "backtests": backtests,
        "backtest_gate": backtest_gate,
        "artifact": str(MODEL_FILE),
        "artifact_sha256": sha256_file(MODEL_FILE),
    }
    METRICS_FILE.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _metadata_hash(table: pa.Table) -> str:
    digest = hashlib.sha256()
    for name in ("snapshot_at", "element", "event_number"):
        digest.update(str(table[name].to_pylist()).encode())
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _current_forecast_inputs() -> dict[str, str | None]:
    from .attacking_chance_challenger import current_attacking_chance_inputs
    from .market_feature_challenger import current_market_feature_inputs
    from .understat_challenger import current_understat_inputs

    return {
        "features_sha256": sha256_file(CURRENT_FEATURES),
        "model_sha256": sha256_file(MODEL_FILE),
        "appearance_calibration_sha256": (
            sha256_file(CALIBRATION_FILE) if CALIBRATION_FILE.is_file() else None
        ),
        **current_attacking_chance_inputs(),
        **current_market_feature_inputs(),
        **current_understat_inputs(),
    }


def _reusable_current_forecast(inputs: dict[str, str | None]) -> dict[str, Any] | None:
    if not CURRENT_FORECAST.is_file() or not CURRENT_FORECAST_MANIFEST.is_file():
        return None
    try:
        manifest = json.loads(CURRENT_FORECAST_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("manifest_version") != 1 or manifest.get("inputs") != inputs:
        return None
    if manifest.get("forecast_sha256") != sha256_file(CURRENT_FORECAST):
        return None
    result = manifest.get("result")
    if not isinstance(result, dict):
        return None
    return {**result, "reused": True}


def forecast(*, force: bool = False) -> dict[str, Any]:
    ensure_engine_layout()
    if not MODEL_FILE.exists():
        raise FileNotFoundError("Model artifact missing; run fplagent train first")
    if not CURRENT_FEATURES.exists():
        raise FileNotFoundError("Current features missing; run fplagent prepare first")
    inputs = _current_forecast_inputs()
    if not force:
        reused = _reusable_current_forecast(inputs)
        if reused is not None:
            return reused
    require_cuda()
    bundle = joblib.load(MODEL_FILE)
    table = pq.read_table(CURRENT_FEATURES)
    feature_names = tuple(bundle["features"])
    missing = sorted(set(feature_names) - set(table.column_names))
    if missing:
        raise RuntimeError(f"Forecast feature contract is missing columns: {missing}")
    matrix = _matrix(table, feature_names)
    positions = _strings(table, "position")
    form5 = _numeric(table, "form5_points")
    availability = _numeric(table, "availability_chance")
    rows = table.to_pylist()
    forecast_created_at = datetime.now(UTC).isoformat()
    for position in POSITIONS:
        selected = np.flatnonzero(positions == position)
        models = bundle["positions"][position]
        conditional = np.vstack(
            [model.predict(matrix[selected]) for model in models["point_models"]]
        )
        probabilities = np.stack(
            [model.predict_proba(matrix[selected]) for model in models["minute_models"]]
        )
        raw_mean_probability = probabilities.mean(axis=0)
        raw_play_probability = raw_mean_probability[:, 1:].sum(axis=1)
        raw_samples = conditional * probabilities[:, :, 1:].sum(axis=2)
        raw_candidate_expected = raw_samples.mean(axis=0)
        appearance_calibrated = np.zeros(len(selected), dtype=bool)
        local_events = np.asarray([int(rows[row_index]["event_number"]) for row_index in selected])
        for event in np.unique(local_events):
            event_indices = np.flatnonzero(local_events == event)
            points_candidates = event_indices[
                np.argsort(raw_candidate_expected[event_indices])[-TOP_K[position] :]
            ]
            local_prices = np.asarray(
                [max(float(rows[selected[index]]["market_price"]), 1.0) for index in event_indices]
            )
            value_candidates = event_indices[
                np.argsort(raw_candidate_expected[event_indices] / local_prices)[-TOP_K[position] :]
            ]
            candidate_indices = np.unique(np.concatenate([points_candidates, value_candidates]))
            calibrated, applied = calibrate_minute_probabilities(
                probabilities[:, candidate_indices, :], position
            )
            probabilities[:, candidate_indices, :] = calibrated
            appearance_calibrated[candidate_indices] = applied
        mean_probability = probabilities.mean(axis=0)
        play_probability = mean_probability[:, 1:].sum(axis=1)
        samples = conditional * probabilities[:, :, 1:].sum(axis=2)
        raw_expected = samples.mean(axis=0)
        baseline = _availability_adjusted_form(form5[selected], availability[selected])
        blend_weight = float(models["blend_model_weight"])
        expected = _blend(raw_expected, baseline, blend_weight)
        disagreement = np.where(np.isfinite(baseline), np.abs(raw_expected - baseline), 0.0)
        model_sd = samples.std(axis=0) + 0.25 * (1.0 - blend_weight) * disagreement
        for local_index, row_index in enumerate(selected):
            history = float(rows[row_index].get("history_events") or 0.0)
            cold = float(rows[row_index].get("cold_start") or 0.0)
            epistemic = float(model_sd[local_index] + 0.65 * cold + 0.2 * (history < 5))
            rows[row_index].update(
                {
                    "conditional_points_if_playing": float(conditional[:, local_index].mean()),
                    "raw_model_expected_points": float(raw_expected[local_index]),
                    "baseline_expected_points": (
                        float(baseline[local_index]) if np.isfinite(baseline[local_index]) else None
                    ),
                    "blend_model_weight": blend_weight,
                    "raw_p_play": float(raw_play_probability[local_index]),
                    "p_dnp": float(mean_probability[local_index, 0]),
                    "p_1_59": float(mean_probability[local_index, 1]),
                    "p_60_89": float(mean_probability[local_index, 2]),
                    "p_90_or_more": float(mean_probability[local_index, 3]),
                    "p_play": float(play_probability[local_index]),
                    "appearance_calibration_applied": bool(appearance_calibrated[local_index]),
                    "expected_points": float(expected[local_index]),
                    "model_sd": float(model_sd[local_index]),
                    "epistemic_uncertainty": epistemic,
                    "robust_points": float(expected[local_index] - 0.15 * epistemic),
                    "model_version": bundle["version"],
                    "model_created_at": bundle["created_at"],
                    "forecast_created_at": forecast_created_at,
                }
            )
    from .market_feature_challenger import apply_current_market_feature_policy

    rows, market_feature_policy = apply_current_market_feature_policy(
        table,
        rows,
        phase=str(inputs["market_feature_phase"]),
    )
    from .attacking_chance_challenger import apply_current_attacking_chance_policy

    rows, attacking_chance_policy = apply_current_attacking_chance_policy(table, rows)
    from .understat_challenger import apply_current_understat_policy

    rows, understat_policy = apply_current_understat_policy(table, rows)
    output = pa.Table.from_pylist(rows)
    write_table(output, CURRENT_FORECAST)
    result = {
        "rows": len(rows),
        "events": sorted(set(output["event_number"].to_pylist())),
        "players": len(set(output["element"].to_pylist())),
        "forecast": str(CURRENT_FORECAST),
        "model_version": bundle["version"],
        "forecast_created_at": forecast_created_at,
        "model_sha256": sha256_file(MODEL_FILE),
        "snapshot_hash": _metadata_hash(table),
        "appearance_calibration": (load_appearance_calibration() or {"promoted_positions": []})[
            "promoted_positions"
        ],
        "market_feature_policy": market_feature_policy,
        "attacking_chance_policy": attacking_chance_policy,
        "understat_policy": understat_policy,
        "reused": False,
    }
    _atomic_json(
        CURRENT_FORECAST_MANIFEST,
        {
            "manifest_version": 1,
            "inputs": inputs,
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
            "result": result,
        },
    )
    return result
