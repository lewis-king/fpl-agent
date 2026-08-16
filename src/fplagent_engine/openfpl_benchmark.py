from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file

from .features import POSITIONS, TRAINING_FEATURES
from .matched_policy import matched_legal_policy_replay
from .models import BACKTEST_FORECAST, TEST_SEASONS, _matrix, _numeric, _strings
from .paths import MODEL_DATA, REPORTS

VERSION = "openfpl_method_matched_benchmark_v1"
OUTPUT_DIR = MODEL_DATA / "external_forecast_benchmark_v1"
OOF_FORECAST = OUTPUT_DIR / "rolling-forecasts.parquet"
BUILD_RECEIPT = OUTPUT_DIR / "build-receipt.json"
RESULTS = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "openfpl-matched-benchmark.md"

OPENFPL_REPOSITORY = "https://github.com/daniegr/OpenFPL"
OPENFPL_COMMIT = "ad055ba7270145ce8ecc1f19581423493b1357e7"
OPENFPL_PAPER = "https://arxiv.org/abs/2508.09992"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _candidate_specs(seed: int) -> list[tuple[str, dict[str, Any]]]:
    """Published OpenFPL model families with a deterministic compact search grid."""
    return [
        (
            "random_forest",
            {
                "n_estimators": 350,
                "max_depth": depth,
                "min_samples_leaf": leaf,
                "max_features": feature_fraction,
                "n_jobs": -1,
                "random_state": seed + offset,
            },
        )
        for offset, (depth, leaf, feature_fraction) in enumerate(
            (
                (8, 4, 0.65),
                (10, 6, 1.00),
                (12, 4, 0.75),
                (16, 6, 0.80),
                (20, 8, 0.90),
                (None, 10, 0.70),
            )
        )
    ] + [
        (
            "xgboost",
            {
                "objective": "reg:squarederror",
                "n_estimators": estimators,
                "learning_rate": rate,
                "max_depth": depth,
                "min_child_weight": 8,
                "subsample": 0.82,
                "colsample_bytree": 0.82,
                "reg_lambda": 6.0,
                "tree_method": "hist",
                "n_jobs": 8,
                "random_state": seed + 100 + offset,
            },
        )
        for offset, (estimators, rate, depth) in enumerate(
            (
                (350, 0.05, 2),
                (400, 0.04, 3),
                (550, 0.035, 4),
                (700, 0.03, 4),
                (550, 0.025, 5),
                (800, 0.02, 5),
            )
        )
    ]


def _fit_predict(
    family: str,
    parameters: dict[str, Any],
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
) -> np.ndarray:
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    transformed_train = imputer.fit_transform(train_x)
    transformed_validation = imputer.transform(validation_x)
    if family == "random_forest":
        model = RandomForestRegressor(**parameters)
    elif family == "xgboost":
        model = xgb.XGBRegressor(**parameters)
    else:
        raise ValueError(f"unknown OpenFPL family {family}")
    model.fit(transformed_train, train_y)
    return np.asarray(model.predict(transformed_validation), dtype=np.float64)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "bias_actual_minus_prediction": float(np.mean(actual - predicted)),
    }


def build_openfpl_method_oof(
    *,
    training_path: Path = TRAINING_FEATURES,
    incumbent_path: Path = BACKTEST_FORECAST,
    output_path: Path = OOF_FORECAST,
    top_models: int = 10,
    seed: int = 26_082,
    receipt_path: Path = BUILD_RECEIPT,
    progress: Any = None,
) -> dict[str, Any]:
    """Reproduce OpenFPL's position-specific RF/XGBoost median ensemble.

    This is a method reproduction, not a claim that the released 2024/25 weights can
    consume our schema. The outer folds are deliberately identical to FPLAgent's
    chronological holdouts, which is the only fair comparison for this project.
    """
    table = pq.read_table(training_path)
    matrix = _matrix(table)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    target = _numeric(table, "target_points").astype(np.float64)
    source_rows = table.to_pylist()
    incumbent = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(incumbent_path).to_pylist()
    }
    season_order = sorted(set(seasons.tolist()))
    output: list[dict[str, Any]] = []
    fold_receipts = []
    specs = _candidate_specs(seed)
    if not 1 <= top_models <= len(specs):
        raise ValueError(f"top_models must be in [1, {len(specs)}]")
    for test_season in TEST_SEASONS:
        prior = [value for value in season_order if value < test_season]
        if len(prior) < 2:
            continue
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        for position in POSITIONS:
            training = np.isin(seasons, training_seasons) & (positions == position)
            validation = (seasons == validation_season) & (positions == position)
            testing = (seasons == test_season) & (positions == position)
            if training.sum() < 200 or validation.sum() < 50 or testing.sum() < 50:
                continue
            ranked = []
            for family, parameters in specs:
                predictions = _fit_predict(
                    family,
                    parameters,
                    matrix[training],
                    target[training],
                    matrix[validation],
                )
                ranked.append(
                    (
                        float(mean_absolute_error(target[validation], predictions)),
                        family,
                        parameters,
                    )
                )
            selected = sorted(ranked, key=lambda row: row[0])[:top_models]
            train_and_validation = training | validation
            test_predictions = [
                _fit_predict(
                    family,
                    parameters,
                    matrix[train_and_validation],
                    target[train_and_validation],
                    matrix[testing],
                )
                for _, family, parameters in selected
            ]
            median_prediction = np.median(np.vstack(test_predictions), axis=0)
            test_indices = np.flatnonzero(testing)
            for local_index, source_index in enumerate(test_indices):
                row = source_rows[int(source_index)]
                key = (test_season, int(row["event_number"]), int(row["element"]))
                champion = incumbent.get(key)
                if champion is None:
                    raise ValueError(f"incumbent forecast is missing matched key {key}")
                output.append(
                    {
                        "season": test_season,
                        "event_number": int(row["event_number"]),
                        "element": int(row["element"]),
                        "player_name": str(row.get("player_name") or row["element"]),
                        "position": position,
                        "team_id": int(row["team_id"]),
                        "market_price": (
                            float(row["market_price"])
                            if row.get("market_price") is not None
                            else None
                        ),
                        "target_points": float(row["target_points"]),
                        "expected_points": float(champion["expected_points"]),
                        "openfpl_expected_points": float(median_prediction[local_index]),
                    }
                )
            fold_receipts.append(
                {
                    "test_season": test_season,
                    "position": position,
                    "training_seasons": training_seasons,
                    "validation_season": validation_season,
                    "training_rows": int(training.sum()),
                    "validation_rows": int(validation.sum()),
                    "test_rows": int(testing.sum()),
                    "selected_models": [
                        {"family": family, "validation_mae": mae, "parameters": parameters}
                        for mae, family, parameters in selected
                    ],
                }
            )
            if progress is not None:
                progress(
                    "OpenFPL method fit: completed "
                    f"{test_season} {position} ({len(fold_receipts)}/"
                    f"{len(TEST_SEASONS) * len(POSITIONS)})"
                )
    output.sort(key=lambda row: (row["season"], row["event_number"], row["element"]))
    write_table(pa.Table.from_pylist(output), output_path)
    receipt = {
        "rows": len(output),
        "folds": fold_receipts,
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def run_openfpl_matched_benchmark(
    *,
    oof_path: Path = OOF_FORECAST,
    results_path: Path = RESULTS,
    report_path: Path = REPORT,
    build_receipt_path: Path = BUILD_RECEIPT,
    rebuild: bool = False,
    top_models: int = 10,
    progress: Any = None,
) -> dict[str, Any]:
    build = (
        build_openfpl_method_oof(
            output_path=oof_path,
            top_models=top_models,
            receipt_path=build_receipt_path,
            progress=progress,
        )
        if rebuild or not oof_path.is_file()
        else json.loads(build_receipt_path.read_text(encoding="utf-8"))
    )
    if build.get("output_sha256") != sha256_file(oof_path):
        raise ValueError("OpenFPL OOF bytes do not match the build receipt; use --rebuild")
    rows = pq.read_table(oof_path).to_pylist()
    actual = np.asarray([row["target_points"] for row in rows], dtype=np.float64)
    champion = np.asarray([row["expected_points"] for row in rows], dtype=np.float64)
    benchmark = np.asarray([row["openfpl_expected_points"] for row in rows], dtype=np.float64)
    overall = {"fplagent": _metrics(actual, champion), "openfpl": _metrics(actual, benchmark)}
    by_position = {}
    for position in POSITIONS:
        selected = np.asarray([row["position"] == position for row in rows])
        by_position[position] = {
            "rows": int(selected.sum()),
            "fplagent": _metrics(actual[selected], champion[selected]),
            "openfpl": _metrics(actual[selected], benchmark[selected]),
        }
    policy = matched_legal_policy_replay(
        rows,
        champion_field="expected_points",
        challenger_field="openfpl_expected_points",
        progress=progress,
    )
    checks = {
        "identical_complete_player_event_rows": len(rows) == build["rows"] and bool(rows),
        "chronological_outer_folds": bool(build.get("folds"))
        and all(
            all(
                value < fold["validation_season"] < fold["test_season"]
                for value in fold["training_seasons"]
            )
            for fold in build.get("folds") or []
        ),
        "fplagent_mae_not_worse": overall["fplagent"]["mae"] <= overall["openfpl"]["mae"],
        "fplagent_legal_points_not_worse": policy["total_delta"] <= 0.0,
    }
    passed = all(checks.values())
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "summary": (
            f"FPLAgent MAE {overall['fplagent']['mae']:.3f} vs OpenFPL-method "
            f"{overall['openfpl']['mae']:.3f}; OpenFPL legal-policy delta "
            f"{policy['total_delta']:+.1f}."
        ),
        "checks": checks,
        "forecast_metrics": overall,
        "by_position": by_position,
        "legal_policy": policy,
        "build": build,
        "provenance": {
            "paper": OPENFPL_PAPER,
            "repository": OPENFPL_REPOSITORY,
            "repository_commit": OPENFPL_COMMIT,
            "license": "MIT",
            "reproduction_scope": (
                "Published position-specific Random Forest/XGBoost median-ensemble method, "
                "retrained on FPLAgent features and identical chronological folds. Released "
                "weights are not relabelled as compatible with this feature schema."
            ),
        },
        "production_authority": False,
    }
    _atomic_json(results_path, result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    season_rows = [
        (
            f"| {season} | {values['events']} | {values['total_delta']:+.1f} | "
            f"{values['wins']} | {values['ties']} | {values['losses']} |"
        )
        for season, values in policy["by_season"].items()
    ]
    report_path.write_text(
        "\n".join(
            [
                "# Matched OpenFPL-method benchmark",
                "",
                f"**Built:** {result['created_at']}  ",
                f"**Gate:** {'PASS' if passed else 'NOT YET'}  ",
                "**Production authority:** none",
                "",
                result["summary"],
                "",
                (
                    f"The benchmark contains {len(build['folds'])} position/season folds, "
                    f"{len(rows):,} matched player-deadline forecasts and "
                    f"{policy['matched_events']} legal event decisions."
                ),
                "",
                "| Model | MAE | RMSE |",
                "|---|---:|---:|",
                f"| FPLAgent | {overall['fplagent']['mae']:.4f} | {overall['fplagent']['rmse']:.4f} |",
                f"| OpenFPL method | {overall['openfpl']['mae']:.4f} | {overall['openfpl']['rmse']:.4f} |",
                "",
                "| Season | Events | OpenFPL − FPLAgent points | OpenFPL wins | Ties | Losses |",
                "|---|---:|---:|---:|---:|---:|",
                *season_rows,
                "",
                "The same player-deadline rows feed the same legal £100m squad, XI, bench and captain solver.",
                "The external model is a method reproduction pinned to the public repository commit; it is not a renamed internal baseline or a claim that released weights fit our schema.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result
