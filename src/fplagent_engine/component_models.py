from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import xgboost as xgb
from scipy.stats import rankdata
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file

from .features import CURRENT_FEATURES, MODEL_FEATURES, TRAINING_FEATURES
from .models import CURRENT_FORECAST, require_cuda
from .paths import ARTIFACTS, FEATURES, FORECASTS, MODEL_DATA, ensure_engine_layout

MODEL_DIR = ARTIFACTS / "component_v2"
TARGETS_FILE = FEATURES / "player_components.parquet"
MODEL_FILE = MODEL_DIR / "models.joblib"
METRICS_FILE = MODEL_DIR / "metrics.json"
CURRENT_COMPONENT_FORECAST = FORECASTS / "2026-27-preseason-components.parquet"
CURRENT_COMPONENT_FORECAST_MANIFEST = (
    FORECASTS / "2026-27-preseason-components-manifest.json"
)
BPS_PRIORS = MODEL_DATA / "bps_2026_27_v1" / "current-player-bonus-priors.parquet"
BPS_METRICS = MODEL_DATA / "bps_2026_27_v1" / "metrics.json"

POSITIONS = ("GK", "DEF", "MID", "FWD")
POSITION_FEATURES = tuple(f"position_{position.lower()}" for position in POSITIONS)
COMPONENT_FEATURES = (*MODEL_FEATURES, *POSITION_FEATURES)
TEST_SEASONS = ("2024-25", "2025-26")

COMPONENTS = {
    "goals": {"target": "target_goals", "baseline": "form5_goals"},
    "assists": {"target": "target_assists", "baseline": "form5_assists"},
    "bonus": {"target": "target_bonus", "baseline": "prior_form5_bonus"},
    "saves": {"target": "target_saves", "baseline": "prior_form5_saves"},
}


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def build_component_targets() -> dict[str, Any]:
    ensure_engine_layout()
    TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""
            COPY (
                WITH outcomes AS (
                    SELECT
                        season,
                        element,
                        GW AS event_number,
                        sum(goals_scored)::DOUBLE AS target_goals,
                        sum(assists)::DOUBLE AS target_assists,
                        sum(bonus)::DOUBLE AS target_bonus,
                        sum(saves)::DOUBLE AS target_saves,
                        sum(bps)::DOUBLE AS target_bps,
                        sum(clean_sheets)::DOUBLE AS target_clean_sheets,
                        sum(goals_conceded)::DOUBLE AS target_goals_conceded,
                        sum(yellow_cards)::DOUBLE AS target_yellow_cards,
                        sum(red_cards)::DOUBLE AS target_red_cards,
                        sum(own_goals)::DOUBLE AS target_own_goals,
                        sum(penalties_missed)::DOUBLE AS target_penalties_missed,
                        sum(penalties_saved)::DOUBLE AS target_penalties_saved,
                        sum(CASE
                            WHEN position = 'DEF' AND defensive_contribution >= 10 THEN 1
                            WHEN position IN ('MID', 'FWD')
                                 AND defensive_contribution >= 12 THEN 1
                            ELSE 0 END)::DOUBLE AS target_dc_awards
                    FROM read_parquet(
                        '{_sql_path(Path("data/processed/vaastav/player_gameweeks.parquet"))}'
                    )
                    GROUP BY season, element, GW
                ), joined AS (
                    SELECT f.*, o.target_goals, o.target_assists, o.target_bonus,
                           o.target_saves, o.target_bps, o.target_clean_sheets,
                           o.target_goals_conceded, o.target_yellow_cards,
                           o.target_red_cards, o.target_own_goals,
                           o.target_penalties_missed, o.target_penalties_saved,
                           o.target_dc_awards
                    FROM read_parquet('{_sql_path(TRAINING_FEATURES)}') f
                    JOIN outcomes o
                      ON f.season = o.season
                     AND f.element = o.element
                     AND f.event_number = o.event_number
                )
                SELECT *,
                    avg(target_bonus) OVER component_5 AS prior_form5_bonus,
                    avg(target_saves) OVER component_5 AS prior_form5_saves,
                    avg(target_bps) OVER component_5 AS prior_form5_raw_bps,
                    avg(target_dc_awards) OVER component_5 AS prior_form5_dc_awards
                FROM joined
                WINDOW component_5 AS (
                    PARTITION BY player_code ORDER BY season, event_number
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                )
            ) TO '{_sql_path(TARGETS_FILE)}'
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
    finally:
        connection.close()
    table = pq.read_table(TARGETS_FILE)
    return {
        "rows": table.num_rows,
        "columns": table.num_columns,
        "path": str(TARGETS_FILE),
        "sha256": sha256_file(TARGETS_FILE),
    }


def _numeric(table: pa.Table, name: str) -> np.ndarray:
    return (
        pc.cast(table[name], pa.float32(), safe=False)
        .combine_chunks()
        .to_numpy(zero_copy_only=False)
    )


def _strings(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(table[name].to_pylist(), dtype=object)


def _matrix(table: pa.Table) -> np.ndarray:
    numeric = [_numeric(table, name) for name in MODEL_FEATURES]
    positions = _strings(table, "position")
    one_hot = [(positions == position).astype(np.float32) for position in POSITIONS]
    return np.column_stack([*numeric, *one_hot]).astype(np.float32, copy=False)


def _model(seed: int) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="count:poisson",
        eval_metric="poisson-nloglik",
        n_estimators=450,
        learning_rate=0.035,
        max_depth=4,
        min_child_weight=20.0,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.15,
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


def _top_decile_capture(actual: np.ndarray, predicted: np.ndarray) -> float:
    selected = predicted >= np.quantile(predicted, 0.90)
    return float(actual[selected].sum() / max(actual.sum(), 1.0))


def _component_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    baseline: np.ndarray,
    events: np.ndarray,
) -> dict[str, Any]:
    predicted = np.clip(predicted, 1e-6, 20.0)
    baseline = np.clip(baseline, 1e-6, 20.0)
    return {
        "rows": len(actual),
        "events": len(np.unique(events)),
        "actual_mean": float(actual.mean()),
        "predicted_mean": float(predicted.mean()),
        "baseline_mean": float(baseline.mean()),
        "model_mae": float(mean_absolute_error(actual, predicted)),
        "baseline_mae": float(mean_absolute_error(actual, baseline)),
        "model_poisson_deviance": float(mean_poisson_deviance(actual, predicted)),
        "baseline_poisson_deviance": float(mean_poisson_deviance(actual, baseline)),
        "model_event_spearman": _event_spearman(events, actual, predicted),
        "baseline_event_spearman": _event_spearman(events, actual, baseline),
        "model_top_decile_capture": _top_decile_capture(actual, predicted),
        "baseline_top_decile_capture": _top_decile_capture(actual, baseline),
    }


def train_component_models(*, force_targets: bool = False, seed: int = 20260802) -> dict:
    ensure_engine_layout()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if force_targets or not TARGETS_FILE.exists():
        target_build = build_component_targets()
    else:
        target_build = {
            "path": str(TARGETS_FILE),
            "sha256": sha256_file(TARGETS_FILE),
            "rows": pq.ParquetFile(TARGETS_FILE).metadata.num_rows,
        }
    cuda = require_cuda()
    table = pq.read_table(TARGETS_FILE)
    matrix = _matrix(table)
    seasons = _strings(table, "season")
    events = _numeric(table, "event_number").astype(np.int16)
    availability = np.clip(_numeric(table, "availability_chance") / 100.0, 0.0, 1.0)
    split_metrics: dict[str, Any] = {}
    oof_rows: list[dict[str, Any]] = []
    component_passes: dict[str, list[bool]] = {name: [] for name in COMPONENTS}
    metadata = table.select(
        ["season", "event_number", "element", "player_name", "position", "team_id"]
    ).to_pylist()
    for test_season in TEST_SEASONS:
        training = seasons < test_season
        testing = seasons == test_season
        split_metrics[test_season] = {}
        for offset, (name, spec) in enumerate(COMPONENTS.items()):
            actual = np.nan_to_num(_numeric(table, spec["target"]), nan=0.0)
            baseline_raw = _numeric(table, spec["baseline"])
            baseline = np.nan_to_num(baseline_raw, nan=0.0) * availability
            component_model = _model(seed + 100 * offset + int(test_season[:4]))
            component_model.fit(matrix[training], actual[training], verbose=False)
            predicted = np.clip(component_model.predict(matrix[testing]), 1e-6, 20.0)
            metrics = _component_metrics(
                actual[testing], predicted, baseline[testing], events[testing]
            )
            improved = bool(
                metrics["model_poisson_deviance"] < metrics["baseline_poisson_deviance"]
                and metrics["model_event_spearman"] >= metrics["baseline_event_spearman"] - 0.01
            )
            metrics["passed"] = improved
            split_metrics[test_season][name] = metrics
            component_passes[name].append(improved)
            for local_offset, global_index in enumerate(np.flatnonzero(testing)):
                oof_rows.append(
                    {
                        **metadata[int(global_index)],
                        "component": name,
                        "actual": float(actual[global_index]),
                        "predicted": float(predicted[local_offset]),
                        "baseline": float(baseline[global_index]),
                    }
                )
    promoted = {name: bool(all(component_passes[name])) for name in COMPONENTS}
    final_models = {}
    for offset, (name, spec) in enumerate(COMPONENTS.items()):
        actual = np.nan_to_num(_numeric(table, spec["target"]), nan=0.0)
        component_model = _model(seed + 1_000 + 100 * offset)
        component_model.fit(matrix, actual, verbose=False)
        final_models[name] = component_model
    bundle = {
        "version": "component_event_v2",
        "created_at": datetime.now(UTC).isoformat(),
        "features": COMPONENT_FEATURES,
        "components": final_models,
        "promoted": promoted,
        "seed": seed,
        "gpu": cuda,
    }
    joblib.dump(bundle, MODEL_FILE, compress=3)
    pq.write_table(
        pa.Table.from_pylist(oof_rows), MODEL_DIR / "rolling-backtest.parquet", compression="zstd"
    )
    gate = {
        "component_passes": promoted,
        "promoted_components": [name for name, passed in promoted.items() if passed],
        "passed": bool(promoted["goals"] and promoted["assists"]),
        "minimum_required": ["goals", "assists"],
    }
    metrics = {
        "version": 1,
        "engine": bundle["version"],
        "created_at": bundle["created_at"],
        "cuda": cuda,
        "target_build": target_build,
        "features": list(COMPONENT_FEATURES),
        "training_rows": table.num_rows,
        "season_forward": split_metrics,
        "gate": gate,
        "artifact": str(MODEL_FILE),
        "artifact_sha256": sha256_file(MODEL_FILE),
    }
    METRICS_FILE.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metrics


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _component_forecast_inputs() -> dict[str, str | None]:
    return {
        "features_sha256": sha256_file(CURRENT_FEATURES),
        "direct_forecast_sha256": sha256_file(CURRENT_FORECAST),
        "component_model_sha256": sha256_file(MODEL_FILE),
        "bps_priors_sha256": sha256_file(BPS_PRIORS) if BPS_PRIORS.is_file() else None,
        "bps_metrics_sha256": sha256_file(BPS_METRICS) if BPS_METRICS.is_file() else None,
    }


def _reusable_component_forecast(inputs: dict[str, str | None]) -> dict[str, Any] | None:
    if (
        not CURRENT_COMPONENT_FORECAST.is_file()
        or not CURRENT_COMPONENT_FORECAST_MANIFEST.is_file()
    ):
        return None
    try:
        manifest = json.loads(
            CURRENT_COMPONENT_FORECAST_MANIFEST.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("manifest_version") != 1 or manifest.get("inputs") != inputs:
        return None
    if manifest.get("forecast_sha256") != sha256_file(CURRENT_COMPONENT_FORECAST):
        return None
    result = manifest.get("result")
    if not isinstance(result, dict):
        return None
    return {**result, "reused": True}


def forecast_components(*, force: bool = False) -> dict[str, Any]:
    if not MODEL_FILE.exists():
        raise FileNotFoundError("Component models missing; run fplagent train-component-events")
    if not CURRENT_FEATURES.is_file() or not CURRENT_FORECAST.is_file():
        raise FileNotFoundError("Current features and direct forecast are required")
    inputs = _component_forecast_inputs()
    if not force:
        reused = _reusable_component_forecast(inputs)
        if reused is not None:
            return reused
    bundle = joblib.load(MODEL_FILE)
    features = pq.read_table(CURRENT_FEATURES)
    forecast = pq.read_table(CURRENT_FORECAST)
    if features.num_rows != forecast.num_rows:
        raise ValueError("Current feature and forecast grids have different row counts")
    feature_keys = list(
        zip(
            features["event_number"].to_pylist(),
            features["element"].to_pylist(),
            strict=True,
        )
    )
    forecast_keys = list(
        zip(
            forecast["event_number"].to_pylist(),
            forecast["element"].to_pylist(),
            strict=True,
        )
    )
    if feature_keys != forecast_keys:
        raise ValueError("Current feature and direct forecast row order does not match")
    matrix = _matrix(features)
    output = forecast.select(
        [
            "season",
            "event_number",
            "element",
            "player_code",
            "player_name",
            "position",
            "team_id",
            "p_dnp",
            "p_1_59",
            "p_60_89",
            "p_90_or_more",
            "p_play",
            "expected_points",
            "snapshot_at",
            "model_created_at",
            "model_version",
            "forecast_created_at",
        ]
    ).to_pylist()
    direct_forecast_sha256 = sha256_file(CURRENT_FORECAST)
    component_model_sha256 = sha256_file(MODEL_FILE)
    component_forecast_created_at = datetime.now(UTC).isoformat()
    predictions = {
        name: np.clip(model.predict(matrix), 0.0, 20.0)
        for name, model in bundle["components"].items()
    }
    bps_promoted = False
    bps_priors: dict[int, float] = {}
    if BPS_PRIORS.exists() and BPS_METRICS.exists():
        bps_metrics = json.loads(BPS_METRICS.read_text(encoding="utf-8"))
        bps_promoted = bool(bps_metrics.get("promoted"))
        if bps_promoted:
            bps_priors = {
                int(row["element"]): float(row["bonus_delta_per_appearance"])
                for row in pq.read_table(BPS_PRIORS).to_pylist()
            }
    short_minutes = 28.0
    medium_minutes = 75.0
    for index, row in enumerate(output):
        row["component_model_created_at"] = str(bundle["created_at"])
        row["component_model_version"] = str(bundle["version"])
        row["component_forecast_created_at"] = component_forecast_created_at
        row["direct_forecast_sha256"] = direct_forecast_sha256
        row["component_model_sha256"] = component_model_sha256
        row["expected_minutes"] = float(
            row["p_1_59"] * short_minutes
            + row["p_60_89"] * medium_minutes
            + row["p_90_or_more"] * 90.0
        )
        for name in COMPONENTS:
            prediction = float(predictions[name][index])
            if name == "bonus":
                row["raw_expected_bonus"] = prediction
                adjustment = (
                    float(row["p_play"]) * bps_priors.get(int(row["element"]), 0.0)
                    if bps_promoted
                    else 0.0
                )
                prediction = max(prediction + adjustment, 0.0)
                row["bps_2026_27_bonus_adjustment"] = float(adjustment)
                row["bps_2026_27_promoted"] = bps_promoted
            row[f"expected_{name}"] = prediction
            row[f"{name}_model_promoted"] = bool(bundle["promoted"][name])
    write_table(pa.Table.from_pylist(output), CURRENT_COMPONENT_FORECAST)
    result = {
        "rows": len(output),
        "path": str(CURRENT_COMPONENT_FORECAST),
        "sha256": sha256_file(CURRENT_COMPONENT_FORECAST),
        "promoted": bundle["promoted"],
        "bps_2026_27_promoted": bps_promoted,
        "model_sha256": component_model_sha256,
        "direct_forecast_sha256": direct_forecast_sha256,
        "snapshot_at": str(output[0]["snapshot_at"]),
        "component_forecast_created_at": component_forecast_created_at,
        "reused": False,
    }
    _atomic_json(
        CURRENT_COMPONENT_FORECAST_MANIFEST,
        {
            "manifest_version": 1,
            "inputs": inputs,
            "forecast_sha256": sha256_file(CURRENT_COMPONENT_FORECAST),
            "result": result,
        },
    )
    return result
