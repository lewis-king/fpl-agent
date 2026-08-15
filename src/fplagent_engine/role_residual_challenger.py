from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.special import logit
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from fplagent_data.http import sha256_file

from .appearance_policy_replay import _candidate_payload
from .appearance_role_challenger import ROLE_FEATURES, build_role_feature_table
from .features import TRAINING_FEATURES
from .market_transfer_replay import moving_block_mean_interval
from .models import BACKTEST_FORECAST, TOP_K
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules
from .tournament import _score_candidates

OUTPUT_DIR = MODEL_DATA / "role_residual_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
PREDICTIONS = OUTPUT_DIR / "predictions.parquet"
REPORT = REPORTS / "role-residual-policy-replay.md"

TRAIN_SEASON = "2023-24"
SELECTION_SEASON = "2024-25"
TEST_SEASON = "2025-26"
SEASONS = (TRAIN_SEASON, SELECTION_SEASON, TEST_SEASON)
POSITIONS = ("GK", "DEF", "MID", "FWD")
REGULARIZATION = (0.01, 0.1, 1.0, 10.0)
BLEND_WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
RATIO_BOUNDS = (0.60, 1.25)

BASE_FEATURES = (
    "history_events",
    "player_days_since_last_event",
    "last_minutes",
    "form3_minutes",
    "form5_minutes",
    "form10_minutes",
    "appearance_rate5",
    "start_rate5",
    "availability_chance",
    "cold_start",
)


def _float(value: Any) -> float:
    return np.nan if value is None else float(value)


def _design_row(
    forecast: dict[str, Any],
    feature: dict[str, Any],
    role: dict[str, Any],
) -> list[float]:
    champion = float(np.clip(float(forecast["p_play"]), 1e-5, 1.0 - 1e-5))
    return [
        float(logit(champion)),
        *(_float(feature.get(name)) for name in BASE_FEATURES),
        *(_float(role.get(name)) for name in ROLE_FEATURES),
    ]


def decision_focus_mask(rows: list[dict[str, Any]]) -> np.ndarray:
    """Mark players likely to affect a legal squad, XI, bench or captain decision."""
    focus = np.zeros(len(rows), dtype=bool)
    grouped: dict[tuple[str, int, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(str(row["season"]), int(row["event_number"]), str(row["position"]))].append(
            index
        )
    for (_, _, position), indices in grouped.items():
        count = min(len(indices), 2 * TOP_K[position])
        by_points = sorted(
            indices,
            key=lambda index: (
                float(rows[index]["champion_expected_points"]),
                -int(rows[index]["element"]),
            ),
        )[-count:]
        by_value = sorted(
            indices,
            key=lambda index: (
                float(rows[index]["champion_expected_points"])
                / max(float(rows[index]["market_price"]), 1.0),
                -int(rows[index]["element"]),
            ),
        )[-count:]
        focus[np.asarray(sorted(set(by_points) | set(by_value)), dtype=np.int64)] = True
    return focus


def _load_rows() -> list[dict[str, Any]]:
    features = [
        row
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in SEASONS
    ]
    feature_by_key = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in features
    }
    role_by_id = {
        int(row["row_id"]): row for row in build_role_feature_table().to_pylist()
    }
    output = []
    for forecast in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(forecast["season"])
        if season not in SEASONS or forecast.get("market_price") is None:
            continue
        key = (season, int(forecast["event_number"]), int(forecast["element"]))
        feature = feature_by_key.get(key)
        if feature is None:
            continue
        output.append(
            {
                "season": season,
                "event_number": key[1],
                "element": key[2],
                "player_name": str(forecast["player_name"]),
                "position": str(forecast["position"]),
                "team_id": int(forecast["team_id"]),
                "market_price": float(forecast["market_price"]),
                "champion_p_play": float(forecast["p_play"]),
                "champion_expected_points": float(forecast["expected_points"]),
                "target_played": float(feature["target_minutes"]) > 0.0,
                "target_minutes": float(feature["target_minutes"]),
                "target_points": float(feature["target_points"]),
                "design": _design_row(
                    forecast,
                    feature,
                    role_by_id[int(feature["row_id"])],
                ),
            }
        )
    focus = decision_focus_mask(output)
    for index, selected in enumerate(focus):
        output[index]["decision_focus"] = bool(selected)
    return output


def _model(c: float) -> Pipeline:
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        LogisticRegression(C=c, max_iter=1_000),
    )


def _probability_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    return {
        "rows": len(actual),
        "brier": float(brier_score_loss(actual, predicted)),
        "log_loss": float(log_loss(actual, predicted)),
    }


def adjusted_expected_points(
    expected_points: float,
    champion_p_play: float,
    challenger_p_play: float,
    *,
    ratio_bounds: tuple[float, float] = RATIO_BOUNDS,
) -> float:
    ratio = challenger_p_play / max(champion_p_play, 0.01)
    return expected_points * float(np.clip(ratio, *ratio_bounds))


def _calibrate_position(
    rows: list[dict[str, Any]], position: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    local = [row for row in rows if row["position"] == position]
    design = np.asarray([row["design"] for row in local], dtype=np.float64)
    seasons = np.asarray([row["season"] for row in local], dtype=object)
    actual = np.asarray([row["target_played"] for row in local], dtype=bool)
    champion = np.asarray([row["champion_p_play"] for row in local], dtype=np.float64)
    focus = np.asarray([row["decision_focus"] for row in local], dtype=bool)
    train = seasons == TRAIN_SEASON
    selection = (seasons == SELECTION_SEASON) & focus
    frozen = (seasons == TEST_SEASON) & focus
    candidates = []
    selection_predictions: dict[float, np.ndarray] = {}
    for c in REGULARIZATION:
        model = _model(c)
        model.fit(design[train], actual[train])
        selection_predictions[c] = model.predict_proba(design[seasons == SELECTION_SEASON])[:, 1]
        raw = selection_predictions[c][focus[seasons == SELECTION_SEASON]]
        baseline = champion[selection]
        target = actual[selection]
        for weight in BLEND_WEIGHTS:
            prediction = (1.0 - weight) * baseline + weight * raw
            candidates.append(
                {
                    "regularization": c,
                    "weight": weight,
                    **_probability_metrics(target, prediction),
                }
            )
    candidates.sort(
        key=lambda row: (row["brier"], row["log_loss"], row["weight"], row["regularization"])
    )
    selected = candidates[0]
    c = float(selected["regularization"])
    weight = float(selected["weight"])
    selection_raw = selection_predictions[c]
    final_model = _model(c)
    final_model.fit(design[np.isin(seasons, (TRAIN_SEASON, SELECTION_SEASON))], actual[np.isin(seasons, (TRAIN_SEASON, SELECTION_SEASON))])
    frozen_raw = final_model.predict_proba(design[seasons == TEST_SEASON])[:, 1]

    prediction_rows = []
    for season, raw_predictions in (
        (SELECTION_SEASON, selection_raw),
        (TEST_SEASON, frozen_raw),
    ):
        indices = np.flatnonzero(seasons == season)
        for offset, index in enumerate(indices):
            row = local[index]
            challenger = (1.0 - weight) * champion[index] + weight * raw_predictions[offset]
            prediction_rows.append(
                {
                    **{key: row[key] for key in (
                        "season",
                        "event_number",
                        "element",
                        "player_name",
                        "position",
                        "team_id",
                        "market_price",
                        "target_points",
                        "target_minutes",
                        "decision_focus",
                    )},
                    "champion_p_play": float(champion[index]),
                    "challenger_p_play": float(challenger),
                    "champion_expected_points": float(row["champion_expected_points"]),
                    "challenger_expected_points": adjusted_expected_points(
                        float(row["champion_expected_points"]),
                        float(champion[index]),
                        float(challenger),
                    ),
                }
            )

    metrics = {}
    for season, mask, raw_predictions in (
        (SELECTION_SEASON, selection, selection_raw[focus[seasons == SELECTION_SEASON]]),
        (TEST_SEASON, frozen, frozen_raw[focus[seasons == TEST_SEASON]]),
    ):
        challenger = (1.0 - weight) * champion[mask] + weight * raw_predictions
        metrics[season] = {
            "champion": _probability_metrics(actual[mask], champion[mask]),
            "challenger": _probability_metrics(actual[mask], challenger),
        }
    checks = {
        "nonzero_selection_weight": weight > 0.0,
        "selection_brier_improves": (
            metrics[SELECTION_SEASON]["challenger"]["brier"]
            < metrics[SELECTION_SEASON]["champion"]["brier"]
        ),
        "selection_log_loss_improves": (
            metrics[SELECTION_SEASON]["challenger"]["log_loss"]
            < metrics[SELECTION_SEASON]["champion"]["log_loss"]
        ),
        "frozen_brier_improves": (
            metrics[TEST_SEASON]["challenger"]["brier"]
            < metrics[TEST_SEASON]["champion"]["brier"]
        ),
        "frozen_log_loss_improves": (
            metrics[TEST_SEASON]["challenger"]["log_loss"]
            < metrics[TEST_SEASON]["champion"]["log_loss"]
        ),
    }
    return (
        {
            "position": position,
            "selected_regularization": c,
            "selected_weight": weight,
            "selection_candidates": candidates,
            "metrics": metrics,
            "checks": checks,
            "passed": all(checks.values()),
        },
        prediction_rows,
    )


def _policy_replay(
    predictions: list[dict[str, Any]], eligible_positions: tuple[str, ...]
) -> dict[str, Any]:
    rules = load_rules()
    by_prediction = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in predictions
    }
    feature_by_key = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in (SELECTION_SEASON, TEST_SEASON)
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for raw in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(raw["season"])
        if season not in (SELECTION_SEASON, TEST_SEASON) or raw.get("market_price") is None:
            continue
        key = (season, int(raw["event_number"]), int(raw["element"]))
        feature = feature_by_key[key]
        prediction = by_prediction[key]
        grouped[(season, key[1])].append(
            {
                **raw,
                "market_price": round(float(raw["market_price"])),
                "target_points": float(feature["target_points"]),
                "target_minutes": float(feature["target_minutes"]),
                "champion_expected_points": float(raw["expected_points"]),
                "challenger_expected_points": (
                    float(prediction["challenger_expected_points"])
                    if str(raw["position"]) in eligible_positions
                    else float(raw["expected_points"])
                ),
                "can_select": True,
                "removed": False,
            }
        )
    events = []
    for (season, event), rows in sorted(grouped.items()):
        champion_rows = [
            {**row, "expected_points": row["champion_expected_points"]} for row in rows
        ]
        challenger_rows = [
            {**row, "expected_points": row["challenger_expected_points"]} for row in rows
        ]
        champion_solution = _solve(champion_rows, [event], rules=rules)
        challenger_solution = _solve(challenger_rows, [event], rules=rules)
        player_ids = sorted(int(row["element"]) for row in rows)
        by_id = {int(row["element"]): row for row in rows}
        points = np.asarray(
            [[[by_id[element]["target_points"] for element in player_ids]]], dtype=np.int16
        )
        played = np.asarray(
            [[[by_id[element]["target_minutes"] > 0 for element in player_ids]]], dtype=bool
        )
        scores = _score_candidates(
            [
                _candidate_payload(champion_solution, event),
                _candidate_payload(challenger_solution, event),
            ],
            player_ids,
            (event,),
            points,
            played,
            by_id,
        )[0, :, 0]
        events.append(
            {
                "season": season,
                "event": event,
                "champion_points": int(scores[0]),
                "challenger_points": int(scores[1]),
                "delta": int(scores[1] - scores[0]),
                "squad_overlap": len(
                    set(champion_solution["selected"]) & set(challenger_solution["selected"])
                ),
                "same_squad": set(champion_solution["selected"])
                == set(challenger_solution["selected"]),
            }
        )
    selection_deltas = [
        row["delta"] for row in events if row["season"] == SELECTION_SEASON
    ]
    test_deltas = [row["delta"] for row in events if row["season"] == TEST_SEASON]
    interval = moving_block_mean_interval(test_deltas, seed=20260822)
    checks = {
        "eligible_position_exists": bool(eligible_positions),
        "positive_selection_total": sum(selection_deltas) > 0,
        "positive_frozen_test_total": sum(test_deltas) > 0,
        "frozen_test_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
    }
    return {
        "eligible_positions": list(eligible_positions),
        "checks": checks,
        "passed": all(checks.values()),
        "selection_total_delta": sum(selection_deltas),
        "frozen_test_total_delta": sum(test_deltas),
        "frozen_test_interval": interval,
        "exact_squad_rate": float(np.mean([row["same_squad"] for row in events])),
        "mean_squad_overlap": float(np.mean([row["squad_overlap"] for row in events])),
        "events": events,
    }


def _render(result: dict[str, Any]) -> str:
    policy = result["policy_replay"]
    lines = [
        "# Competitive-role residual challenger",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — statistically eligible positions: "
            f"{', '.join(result['eligible_positions']) or 'none'}. The exact legal-squad replay "
            f"changed 2024/25 by {policy['selection_total_delta']:+d} points and the untouched "
            f"2025/26 season by {policy['frozen_test_total_delta']:+d} points."
        ),
        "",
        (
            "This residual model starts from the production play probability. It may only correct "
            "systematic errors associated with competitive role persistence, and it is assessed "
            "on the union of high-points and high-value candidates most likely to affect a "
            "decision."
        ),
        "",
        "| Position | Weight | 2024/25 Brier Δ | 2025/26 Brier Δ | Statistical gate |",
        "|---|---:|---:|---:|---|",
    ]
    for position in POSITIONS:
        row = result["positions"][position]
        selection = row["metrics"][SELECTION_SEASON]
        test = row["metrics"][TEST_SEASON]
        lines.append(
            f"| {position} | {row['selected_weight']:.2f} | "
            f"{selection['challenger']['brier'] - selection['champion']['brier']:+.5f} | "
            f"{test['challenger']['brier'] - test['champion']['brier']:+.5f} | "
            f"{'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Authority boundary",
            "",
            (
                "A probability improvement is only permission to run the legal policy replay. "
                "Production changes only if every policy gate passes; otherwise the current "
                "minutes and appearance model remains authoritative."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_role_residual_challenger() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_rows()
    position_results = {}
    predictions = []
    for position in POSITIONS:
        result, local_predictions = _calibrate_position(rows, position)
        position_results[position] = result
        predictions.extend(local_predictions)
    eligible = tuple(
        position for position in POSITIONS if position_results[position]["passed"]
    )
    policy = _policy_replay(predictions, eligible)
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate_only",
        "verdict": "PROMOTE" if policy["passed"] else "RETAIN_INCUMBENT",
        "production_changed": False,
        "eligible_positions": list(eligible),
        "decision_focus": "union of top 2K expected-points and value candidates per event/position",
        "ratio_bounds": list(RATIO_BOUNDS),
        "positions": position_results,
        "policy_replay": policy,
        "artifacts": {
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "backtest_forecast": str(BACKTEST_FORECAST),
            "backtest_forecast_sha256": sha256_file(BACKTEST_FORECAST),
        },
    }
    pq.write_table(pa.Table.from_pylist(predictions), PREDICTIONS, compression="zstd")
    result["artifacts"]["predictions"] = str(PREDICTIONS)
    result["artifacts"]["predictions_sha256"] = sha256_file(PREDICTIONS)
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
