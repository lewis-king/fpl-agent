from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import joblib
import numpy as np
import pyarrow.parquet as pq
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, mean_absolute_error

from fplagent_data.http import sha256_file

from .appearance_audit import _selectable_rows
from .features import MODEL_FEATURES, TRAINING_FEATURES
from .models import (
    BACKTEST_FORECAST,
    SEEDS,
    TOP_K,
    _classifier,
    _gameweek_spearman,
    _matrix,
    _mean_top_k_points,
    _season_weights,
    require_cuda,
)
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

OUTPUT_DIR = MODEL_DATA / "appearance_challenger_v2"
ARTIFACT = OUTPUT_DIR / "candidate.json"
PREDICTIONS = OUTPUT_DIR / "prediction-bundles.joblib"
REPORT = REPORTS / "appearance-challenger-v2.md"
TEST_SEASONS = ("2024-25", "2025-26")
POSITIONS = ("GK", "DEF", "MID", "FWD")
REPRESENTATIVE_MINUTES = np.asarray([0.0, 28.0, 75.0, 90.0])
METHODS = ("play_logistic", "temperature", "two_stage_temperature")


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(float), 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def anchor_play_probability(probabilities: np.ndarray, p_play: np.ndarray) -> np.ndarray:
    """Use champion P(play) while retaining the four-class model's conditional shares."""
    raw = np.clip(np.asarray(probabilities, dtype=float), 1e-9, 1.0)
    champion_play = np.clip(np.asarray(p_play, dtype=float), 1e-6, 1.0 - 1e-6)
    shares = raw[:, 1:]
    shares /= shares.sum(axis=1, keepdims=True)
    output = np.column_stack([1.0 - champion_play, shares * champion_play[:, None]])
    output /= output.sum(axis=1, keepdims=True)
    return output


def _temperature(probabilities: np.ndarray, value: float) -> np.ndarray:
    logits = np.log(np.clip(probabilities, 1e-9, 1.0)) / float(value)
    logits -= logits.max(axis=1, keepdims=True)
    output = np.exp(logits)
    return output / output.sum(axis=1, keepdims=True)


def fit_temperature(probabilities: np.ndarray, actual_class: np.ndarray) -> float:
    labels = sorted(set(np.asarray(actual_class, dtype=int).tolist()))
    if len(labels) < 2:
        return 1.0

    def objective(value: float) -> float:
        return float(
            log_loss(
                actual_class,
                _temperature(probabilities, value),
                labels=list(range(probabilities.shape[1])),
            )
        )

    result = minimize_scalar(objective, bounds=(0.25, 4.0), method="bounded")
    return float(result.x) if result.success else 1.0


def fit_calibrator(
    method: str, probabilities: np.ndarray, actual_class: np.ndarray
) -> dict[str, Any]:
    if method not in METHODS:
        raise ValueError(f"unsupported appearance challenger method {method}")
    actual = np.asarray(actual_class, dtype=int)
    if method == "temperature":
        return {"method": method, "temperature": fit_temperature(probabilities, actual)}
    play_probability = probabilities[:, 1:].sum(axis=1)
    played = (actual > 0).astype(int)
    model = LogisticRegression(C=1.0, max_iter=2_000)
    model.fit(_logit(play_probability), played)
    result: dict[str, Any] = {
        "method": method,
        "play": {
            "coefficient": float(model.coef_[0, 0]),
            "intercept": float(model.intercept_[0]),
        },
    }
    if method == "two_stage_temperature":
        selected = actual > 0
        conditional = probabilities[selected, 1:]
        conditional /= conditional.sum(axis=1, keepdims=True)
        result["conditional_temperature"] = fit_temperature(
            conditional, actual[selected] - 1
        )
    return result


def apply_calibrator(probabilities: np.ndarray, calibrator: dict[str, Any]) -> np.ndarray:
    method = str(calibrator["method"])
    raw = np.asarray(probabilities, dtype=float)
    if method == "temperature":
        return _temperature(raw, float(calibrator["temperature"]))
    if method not in {"play_logistic", "two_stage_temperature"}:
        raise ValueError(f"unsupported appearance challenger method {method}")
    raw_play = np.clip(raw[:, 1:].sum(axis=1), 1e-6, 1.0 - 1e-6)
    play = calibrator["play"]
    adjusted_play = 1.0 / (
        1.0
        + np.exp(
            -(
                float(play["intercept"])
                + float(play["coefficient"]) * _logit(raw_play).ravel()
            )
        )
    )
    conditional = raw[:, 1:] / raw_play[:, None]
    if method == "two_stage_temperature":
        conditional = _temperature(
            conditional, float(calibrator["conditional_temperature"])
        )
    output = np.column_stack([1.0 - adjusted_play, conditional * adjusted_play[:, None]])
    output /= output.sum(axis=1, keepdims=True)
    return output


def _probability_metrics(
    actual_class: np.ndarray,
    target_minutes: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, float | int]:
    actual = np.asarray(actual_class, dtype=int)
    played = (actual > 0).astype(float)
    p_play = probabilities[:, 1:].sum(axis=1)
    one_hot = np.eye(4)[actual]
    expected_minutes = probabilities @ REPRESENTATIVE_MINUTES
    return {
        "rows": len(actual),
        "play_brier": float(np.mean(np.square(p_play - played))),
        "play_log_loss": float(log_loss(played, p_play, labels=[0, 1])),
        "multiclass_brier": float(np.mean(np.square(probabilities - one_hot).sum(axis=1))),
        "multiclass_log_loss": float(log_loss(actual, probabilities, labels=[0, 1, 2, 3])),
        "expected_minutes_mae": float(mean_absolute_error(target_minutes, expected_minutes)),
        "play_probability_bias": float(p_play.mean() - played.mean()),
    }


def _decision_metrics(
    *,
    events: np.ndarray,
    actual_points: np.ndarray,
    expected_points: np.ndarray,
    top_k: int,
) -> dict[str, float]:
    return {
        "points_mae": float(mean_absolute_error(actual_points, expected_points)),
        "gameweek_spearman": _gameweek_spearman(events, actual_points, expected_points),
        "top_k_actual_points": _mean_top_k_points(
            events, actual_points, expected_points, top_k
        ),
        "top_1_actual_points": _mean_top_k_points(events, actual_points, expected_points, 1),
    }


def method_gate(validations: list[dict[str, Any]], method: str) -> dict[str, Any]:
    rows = [row for row in validations if row["method"] == method]
    checks = {
        "forward_slices": len(rows) == len(TEST_SEASONS),
        "play_brier_wins": all(row["challenger"]["play_brier"] < row["raw"]["play_brier"] for row in rows),
        "play_log_loss_wins": all(row["challenger"]["play_log_loss"] < row["raw"]["play_log_loss"] for row in rows),
        "multiclass_brier_wins": all(row["challenger"]["multiclass_brier"] < row["raw"]["multiclass_brier"] for row in rows),
        "multiclass_log_loss_wins": all(row["challenger"]["multiclass_log_loss"] < row["raw"]["multiclass_log_loss"] for row in rows),
        "minutes_mae_wins": all(row["challenger"]["expected_minutes_mae"] < row["raw"]["expected_minutes_mae"] for row in rows),
        "points_mae_non_regression": all(row["challenger_decision"]["points_mae"] <= row["raw_decision"]["points_mae"] + 0.01 for row in rows),
        "top_k_non_regression": all(row["challenger_decision"]["top_k_actual_points"] >= row["raw_decision"]["top_k_actual_points"] - 0.01 for row in rows),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _candidate_keys() -> set[tuple[str, int, int]]:
    selected = _selectable_rows()
    return {
        (str(season), int(event), int(element))
        for season, event, element in zip(
            selected["season"],
            selected["event_number"],
            selected["element"],
            strict=True,
        )
    }


def _champion_predictions() -> dict[tuple[str, int, int], dict[str, float]]:
    return {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): {
            "p_play": float(row["p_play"]),
            "expected_points": float(row["expected_points"]),
        }
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Four-class appearance challenger",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Candidate rows:** {result['candidate_pool_rows']:,}  ",
        "**Production calibration changed:** no",
        "",
        (
            "The challenger calibrates DNP, 1–59, 60–89 and 90+ probabilities under two strict "
            "season-forward tests. The current champion P(play) is retained as the raw anchor, so "
            "this experiment measures calibration rather than a silently different classifier."
        ),
        "",
        "## Position decisions",
        "",
        "| Position | Selected method | Gate |",
        "| --- | --- | --- |",
    ]
    for position in POSITIONS:
        row = result["position_gate"][position]
        lines.append(
            f"| {position} | {row.get('selected_method') or 'none'} | "
            f"{'PASS' if row['promoted'] else 'REJECT'} |"
        )
    lines.extend(
        [
            "",
            "## Forward slices",
            "",
            "| Season | Pos | Method | Play Brier | Multi log loss | Minutes MAE | xP MAE |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result["validations"]:
        lines.append(
            f"| {row['test_season']} | {row['position']} | {row['method']} | "
            f"{row['challenger']['play_brier']:.4f} | "
            f"{row['challenger']['multiclass_log_loss']:.4f} | "
            f"{row['challenger']['expected_minutes_mae']:.2f} | "
            f"{row['challenger_decision']['points_mae']:.3f} |"
        )
    lines.extend(
        [
            "",
            (
                "No calibrator is copied into the production artifact by this audit. A passing "
                "position must still survive frozen squad, XI, bench and captain replay before "
                "promotion."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_appearance_challenger() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cuda = require_cuda()
    table = pq.read_table(TRAINING_FEATURES)
    matrix = _matrix(table, MODEL_FEATURES)
    rows = table.to_pylist()
    seasons = np.asarray(table["season"].to_pylist(), dtype=str)
    positions = np.asarray(table["position"].to_pylist(), dtype=str)
    minute_classes = np.asarray(table["minutes_class"].to_pylist(), dtype=int)
    target_minutes = np.asarray(table["target_minutes"].to_pylist(), dtype=float)
    target_points = np.asarray(table["target_points"].to_pylist(), dtype=float)
    candidate_keys = _candidate_keys()
    champion = _champion_predictions()
    season_order = sorted(set(seasons.tolist()))
    validations: list[dict[str, Any]] = []
    final_bundles: dict[str, dict[str, Any]] = {}

    for test_season in TEST_SEASONS:
        prior = [season for season in season_order if season < test_season]
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        for position in POSITIONS:
            train = np.isin(seasons, training_seasons) & (positions == position)
            validation = (seasons == validation_season) & (positions == position)
            test = (seasons == test_season) & (positions == position)
            model = _classifier(SEEDS[0], 900, early_stopping=True)
            model.fit(
                matrix[train],
                minute_classes[train],
                sample_weight=_season_weights(seasons, train),
                eval_set=[(matrix[validation], minute_classes[validation])],
                verbose=False,
            )

            validation_indices = np.flatnonzero(validation)
            test_indices = np.flatnonzero(test)
            validation_indices = np.asarray(
                [
                    index
                    for index in validation_indices
                    if (validation_season, int(rows[index]["event_number"]), int(rows[index]["element"]))
                    in candidate_keys
                ],
                dtype=int,
            )
            test_indices = np.asarray(
                [
                    index
                    for index in test_indices
                    if (test_season, int(rows[index]["event_number"]), int(rows[index]["element"]))
                    in candidate_keys
                ],
                dtype=int,
            )
            if not len(validation_indices) or not len(test_indices):
                raise ValueError(f"appearance candidate pool is empty for {test_season} {position}")

            def champion_values(indices: np.ndarray, field: str) -> np.ndarray:
                return np.asarray(
                    [
                        champion[
                            (
                                str(rows[index]["season"]),
                                int(rows[index]["event_number"]),
                                int(rows[index]["element"]),
                            )
                        ][field]
                        for index in indices
                    ],
                    dtype=float,
                )

            validation_raw = anchor_play_probability(
                model.predict_proba(matrix[validation_indices]),
                champion_values(validation_indices, "p_play"),
            )
            test_p_play = champion_values(test_indices, "p_play")
            test_raw = anchor_play_probability(
                model.predict_proba(matrix[test_indices]), test_p_play
            )
            raw_probability_metrics = _probability_metrics(
                minute_classes[test_indices], target_minutes[test_indices], test_raw
            )
            raw_expected_points = champion_values(test_indices, "expected_points")
            conditional_points = raw_expected_points / np.clip(test_p_play, 0.01, 1.0)
            test_events = np.asarray(
                [int(rows[index]["event_number"]) for index in test_indices], dtype=int
            )
            raw_decision = _decision_metrics(
                events=test_events,
                actual_points=target_points[test_indices],
                expected_points=raw_expected_points,
                top_k=TOP_K[position],
            )
            for method in METHODS:
                calibrator = fit_calibrator(
                    method,
                    validation_raw,
                    minute_classes[validation_indices],
                )
                calibrated = apply_calibrator(test_raw, calibrator)
                calibrated_expected_points = conditional_points * calibrated[:, 1:].sum(axis=1)
                validations.append(
                    {
                        "test_season": test_season,
                        "validation_season": validation_season,
                        "position": position,
                        "method": method,
                        "rows": len(test_indices),
                        "calibrator": calibrator,
                        "raw": raw_probability_metrics,
                        "challenger": _probability_metrics(
                            minute_classes[test_indices],
                            target_minutes[test_indices],
                            calibrated,
                        ),
                        "raw_decision": raw_decision,
                        "challenger_decision": _decision_metrics(
                            events=test_events,
                            actual_points=target_points[test_indices],
                            expected_points=calibrated_expected_points,
                            top_k=TOP_K[position],
                        ),
                    }
                )
            if test_season == TEST_SEASONS[-1]:
                final_bundles[position] = {
                    "probabilities": test_raw,
                    "actual_class": minute_classes[test_indices],
                    "rows": len(test_indices),
                }

    position_gate: dict[str, Any] = {}
    candidate_calibrators: dict[str, Any] = {}
    for position in POSITIONS:
        position_rows = [row for row in validations if row["position"] == position]
        gates = {method: method_gate(position_rows, method) for method in METHODS}
        passed = [method for method in METHODS if gates[method]["passed"]]
        selected_method = min(
            passed,
            key=lambda method: np.mean(
                [
                    row["challenger"]["multiclass_log_loss"]
                    for row in position_rows
                    if row["method"] == method
                ]
            ),
            default=None,
        )
        position_gate[position] = {
            "promoted": selected_method is not None,
            "selected_method": selected_method,
            "methods": gates,
        }
        if selected_method is not None:
            bundle = final_bundles[position]
            candidate_calibrators[position] = {
                **fit_calibrator(
                    selected_method,
                    bundle["probabilities"],
                    bundle["actual_class"],
                ),
                "training_season": TEST_SEASONS[-1],
                "training_rows": int(bundle["rows"]),
            }

    result = {
        "version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate_only",
        "production_calibration_changed": False,
        "cuda": cuda,
        "scope": "top expected-points or value candidates per position and event",
        "representative_minutes": REPRESENTATIVE_MINUTES.tolist(),
        "methods": list(METHODS),
        "candidate_pool_rows": len(candidate_keys),
        "position_gate": position_gate,
        "promoted_positions_pending_policy_replay": [
            position for position in POSITIONS if position_gate[position]["promoted"]
        ],
        "candidate_calibrators": candidate_calibrators,
        "validations": validations,
        "source_artifacts": {
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "backtest_forecast": str(BACKTEST_FORECAST),
            "backtest_forecast_sha256": sha256_file(BACKTEST_FORECAST),
        },
    }
    ARTIFACT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    joblib.dump(final_bundles, PREDICTIONS)
    REPORT.write_text(_render_report(result), encoding="utf-8")
    return result
