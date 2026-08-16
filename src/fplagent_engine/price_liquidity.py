from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file
from fplagent_data.market_telemetry import CURRENT_FEATURES as CURRENT_MARKET_FEATURES
from fplagent_data.market_telemetry import PRICE_OUTCOMES

from .paths import MODEL_DATA, REPORTS
from .season_state import calculated_selling_price

VERSION = "price_liquidity_scenarios_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
OOF_PREDICTIONS = OUTPUT_DIR / "rolling-price-forecasts.parquet"
CURRENT_FORECAST = OUTPUT_DIR / "current-price-forecasts.parquet"
RESULTS = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "price-liquidity-scenarios.md"
TIMING_OUTCOMES = OUTPUT_DIR / "prospective-timing-outcomes.json"
CLASSES = ("fall", "none", "rise")
MINIMUM_TRAIN_NIGHTS = 3
MINIMUM_GATE_NIGHTS = 14
FEATURES = (
    "price_change_percent",
    "selected_by_percent",
    "net_transfer_velocity_per_hour",
    "price_before",
    "chance_this_round",
)


def _matrix(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    def feature_value(row: Mapping[str, Any], feature: str) -> float:
        value = (
            row.get("now_cost")
            if feature == "price_before" and row.get("price_before") is None
            else row.get(feature)
        )
        if value is None:
            return 100.0 if feature == "chance_this_round" else 0.0
        return float(value)

    return np.asarray(
        [[feature_value(row, feature) for feature in FEATURES] for row in rows],
        dtype=np.float64,
    )


def multiclass_brier(
    probabilities: np.ndarray, actual: Sequence[str], classes: Sequence[str] = CLASSES
) -> float:
    labels = np.asarray([[float(value == candidate) for candidate in classes] for value in actual])
    return float(np.mean(np.sum(np.square(probabilities - labels), axis=1)))


def _aligned_probabilities(model: LogisticRegression, matrix: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(matrix)
    output = np.zeros((len(matrix), len(CLASSES)), dtype=np.float64)
    for source_index, label in enumerate(model.classes_):
        output[:, CLASSES.index(str(label))] = raw[:, source_index]
    return output


def build_price_oof(
    *, outcomes_path: Path = PRICE_OUTCOMES, output_path: Path = OOF_PREDICTIONS
) -> dict[str, Any]:
    rows = pq.read_table(outcomes_path).to_pylist()
    boundaries = sorted({str(row["boundary_at"]) for row in rows})
    predictions: list[dict[str, Any]] = []
    folds = []
    for index in range(MINIMUM_TRAIN_NIGHTS, len(boundaries)):
        boundary = boundaries[index]
        training_boundaries = set(boundaries[:index])
        train = [row for row in rows if str(row["boundary_at"]) in training_boundaries]
        test = [row for row in rows if str(row["boundary_at"]) == boundary]
        if len({str(row["actual_direction"]) for row in train}) < 2:
            continue
        scaler = StandardScaler()
        train_x = scaler.fit_transform(_matrix(train))
        test_x = scaler.transform(_matrix(test))
        model = LogisticRegression(
            C=0.5,
            class_weight="balanced",
            max_iter=1_000,
            random_state=20260815,
        )
        model.fit(train_x, [str(row["actual_direction"]) for row in train])
        probability = _aligned_probabilities(model, test_x)
        counts = {
            label: sum(str(row["actual_direction"]) == label for row in train) for label in CLASSES
        }
        base = np.asarray([counts[label] / len(train) for label in CLASSES])
        for row, values in zip(test, probability, strict=True):
            predictions.append(
                {
                    **dict(row),
                    "p_fall": float(values[0]),
                    "p_none": float(values[1]),
                    "p_rise": float(values[2]),
                    "base_p_fall": float(base[0]),
                    "base_p_none": float(base[1]),
                    "base_p_rise": float(base[2]),
                    "training_nights": index,
                }
            )
        folds.append(
            {
                "boundary_at": boundary,
                "training_nights": index,
                "training_max_boundary": boundaries[index - 1],
                "test_rows": len(test),
                "passed": boundaries[index - 1] < boundary,
            }
        )
    write_table(pa.Table.from_pylist(predictions), output_path)
    return {
        "rows": len(predictions),
        "folds": folds,
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }


def build_current_price_forecast(
    *,
    outcomes_path: Path = PRICE_OUTCOMES,
    current_features_path: Path = CURRENT_MARKET_FEATURES,
    output_path: Path = CURRENT_FORECAST,
) -> dict[str, Any]:
    outcomes = pq.read_table(outcomes_path).to_pylist()
    current = pq.read_table(current_features_path).to_pylist()
    nights = len({str(row["boundary_at"]) for row in outcomes})
    if (
        nights < MINIMUM_TRAIN_NIGHTS
        or not current
        or len({str(row["actual_direction"]) for row in outcomes}) < 2
    ):
        return {"status": "not_ready", "nights": nights, "rows": 0}
    scaler = StandardScaler()
    model = LogisticRegression(
        C=0.5,
        class_weight="balanced",
        max_iter=1_000,
        random_state=20260815,
    )
    model.fit(
        scaler.fit_transform(_matrix(outcomes)),
        [str(row["actual_direction"]) for row in outcomes],
    )
    probabilities = _aligned_probabilities(model, scaler.transform(_matrix(current)))
    rows = [
        {
            "element": int(row["element"]),
            "player_name": str(row["player_name"]),
            "feature_at": str(row["feature_at"]),
            "now_cost": int(row["now_cost"]),
            "p_fall": float(values[0]),
            "p_none": float(values[1]),
            "p_rise": float(values[2]),
            "training_nights": nights,
        }
        for row, values in zip(current, probabilities, strict=True)
    ]
    write_table(pa.Table.from_pylist(rows), output_path)
    return {
        "status": "ready_shadow",
        "nights": nights,
        "rows": len(rows),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "feature_at": max(row["feature_at"] for row in rows),
    }


def selling_price_after_move(purchase_price: int, current_price: int, direction: str) -> int:
    delta = 1 if direction == "rise" else -1 if direction == "fall" else 0
    return calculated_selling_price(purchase_price, max(1, current_price + delta))


def affordability_scenario(
    transfers: Sequence[Mapping[str, Any]],
    *,
    bank: int,
    price_probabilities: Mapping[int, Mapping[str, float]],
) -> dict[str, Any]:
    """Enumerate one-night price scenarios for a proposed legal transfer route."""
    states = [(1.0, int(bank), [])]
    for transfer in transfers:
        outgoing = int(transfer["outgoing_player_id"])
        incoming = int(transfer["incoming_player_id"])
        outgoing_probability = price_probabilities.get(outgoing, {})
        incoming_probability = price_probabilities.get(incoming, {})
        expanded = []
        for probability, scenario_bank, history in states:
            for outgoing_direction in CLASSES:
                for incoming_direction in CLASSES:
                    joint = (
                        probability
                        * float(outgoing_probability.get(f"p_{outgoing_direction}", 0.0))
                        * float(incoming_probability.get(f"p_{incoming_direction}", 0.0))
                    )
                    if joint <= 0.0:
                        continue
                    sale_now = calculated_selling_price(
                        int(transfer["purchase_price"]), int(transfer["outgoing_current_price"])
                    )
                    sale_later = selling_price_after_move(
                        int(transfer["purchase_price"]),
                        int(transfer["outgoing_current_price"]),
                        outgoing_direction,
                    )
                    buy_delta = (
                        1
                        if incoming_direction == "rise"
                        else -1
                        if incoming_direction == "fall"
                        else 0
                    )
                    next_bank = scenario_bank + (sale_later - sale_now) - buy_delta
                    expanded.append(
                        (
                            joint,
                            next_bank,
                            [
                                *history,
                                {
                                    "outgoing": outgoing,
                                    "incoming": incoming,
                                    "outgoing_direction": outgoing_direction,
                                    "incoming_direction": incoming_direction,
                                },
                            ],
                        )
                    )
        states = expanded
    total_probability = sum(row[0] for row in states)
    if total_probability <= 0.0:
        raise ValueError("price scenario has no probability mass")
    return {
        "scenarios": len(states),
        "forced_affordability_loss_probability": float(
            sum(probability for probability, scenario_bank, _ in states if scenario_bank < 0)
            / total_probability
        ),
        "expected_bank_after_wait": float(
            sum(probability * scenario_bank for probability, scenario_bank, _ in states)
            / total_probability
        ),
        "p10_bank_after_wait": int(
            sorted(states, key=lambda row: row[1])[
                next(
                    index
                    for index, cumulative in enumerate(
                        np.cumsum(
                            [
                                row[0] / total_probability
                                for row in sorted(states, key=lambda value: value[1])
                            ]
                        )
                    )
                    if cumulative >= 0.10
                )
            ][1]
        ),
    }


def simulate_price_paths(
    transfers: Sequence[Mapping[str, Any]],
    *,
    bank: int,
    price_probabilities: Mapping[int, Mapping[str, float]],
    nights: int = 3,
    simulations: int = 20_000,
    seed: int = 20_260_815,
) -> dict[str, Any]:
    """Simulate multi-night affordability while keeping team value non-authoritative.

    The current price model is a one-night transition model, so its probabilities are
    reapplied on each path. This is deliberately exposed in the result contract: once
    enough observations exist, a state-dependent transition model can replace it
    without changing the weekly decision interface.
    """
    if not 1 <= nights <= 14:
        raise ValueError("nights must be in [1, 14]")
    if simulations < 1_000:
        raise ValueError("simulations must be at least 1,000")
    if not transfers:
        return {
            "nights": nights,
            "simulations": simulations,
            "forced_affordability_loss_probability": 0.0,
            "expected_bank_after_wait": float(bank),
            "p10_bank_after_wait": int(bank),
            "transition_assumption": "stationary independent player directions",
        }

    rng = np.random.default_rng(seed)
    future_bank = np.full(simulations, int(bank), dtype=np.int64)
    direction_delta = np.asarray([-1, 0, 1], dtype=np.int64)
    for transfer in transfers:
        outgoing = int(transfer["outgoing_player_id"])
        incoming = int(transfer["incoming_player_id"])
        outgoing_probability = price_probabilities.get(outgoing)
        incoming_probability = price_probabilities.get(incoming)
        if outgoing_probability is None or incoming_probability is None:
            raise ValueError(
                f"price probabilities are missing transfer players {outgoing}/{incoming}"
            )
        outgoing_p = np.asarray(
            [float(outgoing_probability.get(f"p_{label}", 0.0)) for label in CLASSES]
        )
        incoming_p = np.asarray(
            [float(incoming_probability.get(f"p_{label}", 0.0)) for label in CLASSES]
        )
        if not np.isclose(outgoing_p.sum(), 1.0) or not np.isclose(incoming_p.sum(), 1.0):
            raise ValueError("each player's price probabilities must sum to one")

        outgoing_price = np.full(
            simulations, int(transfer["outgoing_current_price"]), dtype=np.int64
        )
        incoming_delta = np.zeros(simulations, dtype=np.int64)
        for _ in range(nights):
            outgoing_price = np.maximum(
                1,
                outgoing_price + rng.choice(direction_delta, size=simulations, p=outgoing_p),
            )
            incoming_delta += rng.choice(direction_delta, size=simulations, p=incoming_p)
        sale_now = calculated_selling_price(
            int(transfer["purchase_price"]),
            int(transfer["outgoing_current_price"]),
        )
        sale_later = np.asarray(
            [
                calculated_selling_price(int(transfer["purchase_price"]), int(current_price))
                for current_price in outgoing_price
            ],
            dtype=np.int64,
        )
        future_bank += sale_later - sale_now - incoming_delta

    return {
        "nights": nights,
        "simulations": simulations,
        "seed": seed,
        "forced_affordability_loss_probability": float(np.mean(future_bank < 0)),
        "expected_bank_after_wait": float(np.mean(future_bank)),
        "p10_bank_after_wait": int(np.quantile(future_bank, 0.10, method="inverted_cdf")),
        "p50_bank_after_wait": int(np.quantile(future_bank, 0.50, method="inverted_cdf")),
        "p90_bank_after_wait": int(np.quantile(future_bank, 0.90, method="inverted_cdf")),
        "transition_assumption": "stationary independent player directions",
    }


def score_net_points_timing(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored = []
    for row in rows:
        decision = str(row["predicted_timing"])
        if decision not in {"move_now", "wait"}:
            raise ValueError("predicted_timing must be move_now or wait")
        selected = float(row[f"realized_{decision}_net_points"])
        alternative = float(
            row[f"realized_{'wait' if decision == 'move_now' else 'move_now'}_net_points"]
        )
        scored.append({**dict(row), "realized_policy_delta": selected - alternative})
    deltas = [float(row["realized_policy_delta"]) for row in scored]
    return {
        "events": len(scored),
        "total_net_points_delta": float(sum(deltas)),
        "mean_net_points_delta": float(np.mean(deltas)) if deltas else None,
        "non_negative_event_floor": bool(deltas) and min(deltas) >= 0.0,
        "rows": scored,
    }


def run_price_liquidity_calibration(
    *,
    outcomes_path: Path = PRICE_OUTCOMES,
    oof_path: Path = OOF_PREDICTIONS,
    timing_path: Path = TIMING_OUTCOMES,
    results_path: Path = RESULTS,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if not outcomes_path.is_file():
        build = {"rows": 0, "folds": [], "output": str(oof_path), "output_sha256": None}
        predictions: list[dict[str, Any]] = []
    else:
        build = build_price_oof(outcomes_path=outcomes_path, output_path=oof_path)
        predictions = pq.read_table(oof_path).to_pylist() if build["rows"] else []
    if predictions:
        actual = [str(row["actual_direction"]) for row in predictions]
        probabilities = np.asarray(
            [[row["p_fall"], row["p_none"], row["p_rise"]] for row in predictions]
        )
        base = np.asarray(
            [[row["base_p_fall"], row["base_p_none"], row["base_p_rise"]] for row in predictions]
        )
        model_brier = multiclass_brier(probabilities, actual)
        base_brier = multiclass_brier(base, actual)
        model_logloss = float(log_loss(actual, probabilities, labels=list(CLASSES)))
        base_logloss = float(log_loss(actual, base, labels=list(CLASSES)))
        nights = len({str(row["boundary_at"]) for row in predictions})
    else:
        model_brier = base_brier = model_logloss = base_logloss = None
        nights = 0
    timing_rows = []
    if timing_path.is_file():
        value = json.loads(timing_path.read_text(encoding="utf-8"))
        timing_rows = list(value.get("rows") or []) if isinstance(value, dict) else []
    timing = score_net_points_timing(timing_rows)
    current_forecast = (
        build_current_price_forecast(
            outcomes_path=outcomes_path,
            output_path=CURRENT_FORECAST,
        )
        if outcomes_path.is_file() and CURRENT_MARKET_FEATURES.is_file()
        else {"status": "not_ready", "rows": 0}
    )
    checks = {
        "fourteen_timestamp_safe_nights": nights >= MINIMUM_GATE_NIGHTS,
        "price_brier_beats_prior": model_brier is not None and model_brier < base_brier,
        "price_logloss_beats_prior": model_logloss is not None and model_logloss < base_logloss,
        "six_prospective_timing_decisions": timing["events"] >= 6,
        "positive_realized_net_points": timing["total_net_points_delta"] > 0.0,
        "non_negative_timing_event_floor": timing["non_negative_event_floor"],
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "passed": all(checks.values()),
        "checks": checks,
        "price_forecast": {
            "nights": nights,
            "rows": len(predictions),
            "multiclass_brier": model_brier,
            "prior_brier": base_brier,
            "log_loss": model_logloss,
            "prior_log_loss": base_logloss,
            "build": build,
            "current": current_forecast,
        },
        "net_points_policy": timing,
        "production_authority": False,
        "promotion_target": "realized net FPL points; team value is diagnostic only",
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# Future price and liquidity scenarios",
                "",
                f"**Timestamp-safe nights:** {nights}  ",
                f"**Prospective timing decisions:** {timing['events']}  ",
                f"**Gate:** {'PASS TO REVIEW' if result['passed'] else 'HOLD SHADOW'}",
                "",
                "The model forecasts rise/flat/fall probabilities and propagates exact FPL selling-price mechanics into affordability scenarios.",
                "Promotion is decided only by realized net points from frozen move-now/wait decisions, never by team value alone.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result
