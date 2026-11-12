"""Mid-season refit test: does the points model lag the 2025-26 scoring rules?

The season-forward backtest under-forecast 2025-26 defenders by about half a
point a match, the first season with defensive-contribution points. Production
now trains on that season with the same weight as each of nine older ones.

Split, fixed before evaluation: train on every season to 2024-25 plus 2025-26
GW1-19, test on 2025-26 GW20-38. Every arm shares the minutes model, seeds and
tree settings. Only the points model's sample weights or inputs change.
Research only: nothing here is loaded by normal forecasts.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from fplagent_engine.acceleration import xgboost_infer
from fplagent_engine.features import MODEL_FEATURES, TRAINING_FEATURES
from fplagent_engine.models import (
    SEEDS,
    TOP_K,
    _classifier,
    _matrix,
    _mean_top_k_points,
    _numeric,
    _regressor,
    _strings,
    require_cuda,
)

ERA_SEASON = "2025-26"
SPLIT_EVENT = 19
POSITIONS = ("GK", "DEF", "MID", "FWD")
ESTIMATORS = 250


def season_to_date(seasons, elements, events, points, minutes):
    """Per-row means of this season's earlier events only (NaN before any)."""
    order = np.lexsort((events, elements, seasons))
    mean_points = np.full(len(order), np.nan, dtype=np.float32)
    mean_minutes = np.full(len(order), np.nan, dtype=np.float32)
    count = np.zeros(len(order), dtype=np.float32)
    totals = defaultdict(lambda: [0.0, 0.0, 0])
    for i in order:
        key = (seasons[i], elements[i])
        p, m, n = totals[key]
        if n:
            mean_points[i], mean_minutes[i] = p / n, m / n
        count[i] = n
        if np.isfinite(points[i]) and np.isfinite(minutes[i]):
            totals[key] = [p + points[i], m + minutes[i], n + 1]
    return mean_points, mean_minutes, count


def run(output: Path) -> dict:
    require_cuda()
    table = pq.read_table(TRAINING_FEATURES)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _numeric(table, "event_number").astype(np.int16)
    elements = _numeric(table, "element").astype(np.int64)
    points = _numeric(table, "target_points")
    minutes = _numeric(table, "target_minutes")
    classes = _numeric(table, "minutes_class").astype(np.int32)
    price = _numeric(table, "market_price")
    base = _matrix(table)
    era = (seasons >= ERA_SEASON).astype(np.float32)
    years = np.asarray([int(str(s)[:4]) for s in seasons])
    s2d = season_to_date(seasons, elements, events, points, minutes)

    in_era = seasons == ERA_SEASON
    train_all = (seasons < ERA_SEASON) | (in_era & (events <= SPLIT_EVENT))
    test_all = in_era & (events > SPLIT_EVENT)

    def decay(rate):
        return lambda mask: np.power(rate, years[mask].max() - years[mask]).astype(np.float32)

    def era_weight(factor):
        return lambda mask: np.where(era[mask] > 0, factor, 1.0).astype(np.float32)

    with_era = np.column_stack([base, era])
    with_s2d = np.column_stack([base, *s2d])
    arms = {
        "incumbent_equal_weight": (base, decay(1.0)),
        "season_decay_0.8": (base, decay(0.8)),
        "season_decay_0.6": (base, decay(0.6)),
        "era_weight_x3": (base, era_weight(3.0)),
        "era_weight_x6": (base, era_weight(6.0)),
        "era_flag": (with_era, decay(1.0)),
        "era_flag_weight_x3": (with_era, era_weight(3.0)),
        "season_to_date_features": (with_s2d, decay(1.0)),
        "season_to_date_era_weight_x3": (with_s2d, era_weight(3.0)),
    }
    predictions = {name: np.full(len(points), np.nan, dtype=np.float64) for name in arms}
    for position in POSITIONS:
        train = train_all & (positions == position)
        test = test_all & (positions == position)
        played = train & (minutes > 0)
        probability = np.zeros(int(test.sum()))
        for seed in SEEDS:
            model = _classifier(seed, ESTIMATORS, early_stopping=False)
            model.fit(base[train], classes[train], verbose=False)
            probability += xgboost_infer(model, base[test], method="predict_proba")[:, 1:].sum(
                axis=1
            ) / len(SEEDS)
        for name, (matrix, weights) in arms.items():
            conditional = np.zeros(int(test.sum()))
            for seed in SEEDS:
                model = _regressor(seed, ESTIMATORS, early_stopping=False)
                model.fit(matrix[played], points[played], sample_weight=weights(played),
                          verbose=False)
                conditional += xgboost_infer(model, matrix[test]) / len(SEEDS)
            predictions[name][test] = probability * conditional
        print(f"{position}: {int(played.sum())} played training rows, {int(test.sum())} test rows",
              flush=True)

    def summary(name):
        predicted = predictions[name]
        rows = {}
        for position in (*POSITIONS, "ALL"):
            mask = test_all if position == "ALL" else test_all & (positions == position)
            likely = mask & (predictions["incumbent_equal_weight"] >= 2.5)
            entry = {
                "rows": int(mask.sum()),
                "mae": float(np.mean(np.abs(points[mask] - predicted[mask]))),
                "bias_actual_minus_forecast": float(np.mean(points[mask] - predicted[mask])),
                "likely_starter_rows": int(likely.sum()),
                "likely_starter_bias": float(np.mean(points[likely] - predicted[likely])),
            }
            if position != "ALL":
                entry["top_k_actual_points"] = _mean_top_k_points(
                    events[mask], points[mask], predicted[mask], TOP_K[position]
                )
            rows[position] = entry
        rows["top_k_total"] = float(sum(
            rows[p]["top_k_actual_points"] * TOP_K[p] for p in POSITIONS
        ))
        premium = test_all & (price >= 100) & (predictions["incumbent_equal_weight"] >= 2.5)
        rows["premium_10m_plus"] = {
            "rows": int(premium.sum()),
            "forecast": float(predicted[premium].mean()),
            "actual": float(points[premium].mean()),
        }
        # An XI-shaped pick each week: best 1 GK, 4 DEF, 4 MID, 2 FWD by forecast.
        shape = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
        rows["xi_shape_points_per_week"] = float(sum(
            _mean_top_k_points(events[m], points[m], predicted[m], k) * k
            for p, k in shape.items()
            for m in [test_all & (positions == p)]
        ))
        return rows

    result = {
        "version": "rule_era_refit_v1",
        "decision_authority": False,
        "definition": {
            "train": f"all seasons before {ERA_SEASON} plus {ERA_SEASON} GW1-{SPLIT_EVENT}",
            "test": f"{ERA_SEASON} GW{SPLIT_EVENT + 1}-38",
            "features": len(MODEL_FEATURES),
            "estimators": ESTIMATORS,
            "seeds": list(SEEDS),
        },
        "arms": {name: summary(name) for name in arms},
        "limitations": [
            "One held-out half season; arms were compared on it, so the winner is optimistic.",
            "Top-k and XI-shape picks ignore price, club limits and transfers.",
            "The minutes model is shared and unchanged across arms.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("data/model/rule_era_refit_v1/results.json"))
    out = run(parser.parse_args().output)
    print(f"{'arm':<32}{'MAE':>7}{'bias':>7}{'DEF bias':>9}{'prem fc/act':>13}{'top-k':>8}{'XI/wk':>7}")
    for name, rows in out["arms"].items():
        prem = rows["premium_10m_plus"]
        print(f"{name:<32}{rows['ALL']['mae']:>7.3f}{rows['ALL']['bias_actual_minus_forecast']:>7.3f}"
              f"{rows['DEF']['likely_starter_bias']:>9.2f}"
              f"{prem['forecast']:>7.2f}/{prem['actual']:<5.2f}{rows['top_k_total']:>8.1f}"
              f"{rows['xi_shape_points_per_week']:>7.1f}")
