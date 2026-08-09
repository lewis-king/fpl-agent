from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb
from scipy.special import softmax
from scipy.stats import rankdata
from sklearn.metrics import (
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

from fplagent_data.http import sha256_file

from .features import MODEL_FEATURES, POSITIONS, TRAINING_FEATURES
from .market_policy_replay import _score_solutions
from .market_transfer_replay import moving_block_mean_interval, run_policy_season
from .models import BACKTEST_FORECAST, TOP_K, _matrix, _numeric, _strings, require_cuda
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .rules import load_rules
from .transfer_value import load_terminal_free_transfer_curve

OUTPUT_DIR = MODEL_DATA / "return_distribution_v1"
OOF_FORECAST = OUTPUT_DIR / "rolling-return-distribution.parquet"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "return-distribution-challenger.md"

TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
POLICY_SEASONS = ("2024-25", "2025-26")
MODEL_VERSION = "return_distribution_v1_three_band_temperature"
CLASS_NAMES = ("under_5", "return_5_9", "haul_10_plus")
TEMPERATURE_GRID = (0.60, 0.75, 0.90, 1.00, 1.15, 1.35, 1.60)
BLEND_WEIGHTS = (0.0, 0.25, 0.50, 0.75, 1.0)
SEEDS = (131, 389)


def return_class(points: np.ndarray) -> np.ndarray:
    """Map realised FPL scores to decision-relevant return bands."""
    values = np.asarray(points, dtype=np.float32)
    return np.where(values >= 10.0, 2, np.where(values >= 5.0, 1, 0)).astype(np.int32)


def temperature_scale(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    if temperature <= 0.0:
        raise ValueError("temperature must be positive")
    clipped = np.clip(np.asarray(probabilities, dtype=np.float64), 1e-9, 1.0)
    return softmax(np.log(clipped) / temperature, axis=1)


def choose_temperature(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """Choose one conservative calibration parameter on the prior season only."""
    candidates = [
        (log_loss(labels, temperature_scale(probabilities, value), labels=[0, 1, 2]), value)
        for value in TEMPERATURE_GRID
    ]
    return float(min(candidates)[1])


def _classifier(seed: int) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        n_estimators=900,
        learning_rate=0.035,
        max_depth=4,
        min_child_weight=12.0,
        subsample=0.84,
        colsample_bytree=0.84,
        reg_alpha=0.15,
        reg_lambda=8.0,
        tree_method="hist",
        device="cuda",
        random_state=seed,
        n_jobs=8,
        early_stopping_rounds=50,
    )


def _weighted_class_means(
    points: np.ndarray, labels: np.ndarray, season_years: np.ndarray
) -> np.ndarray:
    newest = int(season_years.max())
    weights = np.power(0.94, newest - season_years).astype(np.float64)
    means = []
    for label in range(3):
        selected = labels == label
        if selected.sum() < 25:
            raise ValueError(f"Insufficient training rows for return class {label}")
        means.append(float(np.average(points[selected], weights=weights[selected])))
    return np.asarray(means, dtype=np.float64)


def _build_oof() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    table = pq.read_table(TRAINING_FEATURES)
    matrix = _matrix(table)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    points = _numeric(table, "target_points")
    labels = return_class(points)
    season_order = sorted(set(seasons.tolist()))
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
            "target_minutes",
        ]
    ).to_pylist()
    rows: list[dict[str, Any]] = []
    fits: list[dict[str, Any]] = []
    for test_season in TEST_SEASONS:
        prior = [season for season in season_order if season < test_season]
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        for position in POSITIONS:
            train = np.isin(seasons, training_seasons) & (positions == position)
            validation = (seasons == validation_season) & (positions == position)
            test = (seasons == test_season) & (positions == position)
            if train.sum() < 1_000 or validation.sum() < 100 or test.sum() < 100:
                raise ValueError(
                    f"Insufficient chronological rows for {test_season} {position}: "
                    f"{train.sum()}/{validation.sum()}/{test.sum()}"
                )
            validation_probabilities = []
            test_probabilities = []
            iterations = []
            for seed in SEEDS:
                model = _classifier(seed)
                model.fit(
                    matrix[train],
                    labels[train],
                    eval_set=[(matrix[validation], labels[validation])],
                    verbose=False,
                )
                validation_probabilities.append(model.predict_proba(matrix[validation]))
                test_probabilities.append(model.predict_proba(matrix[test]))
                iterations.append(int(model.best_iteration or 0))
            raw_validation = np.mean(validation_probabilities, axis=0)
            temperature = choose_temperature(raw_validation, labels[validation])
            probability = temperature_scale(np.mean(test_probabilities, axis=0), temperature)
            training_years = np.asarray([int(str(value)[:4]) for value in seasons[train]])
            class_means = _weighted_class_means(points[train], labels[train], training_years)
            expected = probability @ class_means
            fits.append(
                {
                    "test_season": test_season,
                    "validation_season": validation_season,
                    "training_seasons": training_seasons,
                    "position": position,
                    "training_rows": int(train.sum()),
                    "validation_rows": int(validation.sum()),
                    "test_rows": int(test.sum()),
                    "temperature": temperature,
                    "class_means": {
                        name: float(value) for name, value in zip(CLASS_NAMES, class_means, strict=True)
                    },
                    "best_iterations": iterations,
                }
            )
            for local_index, global_index in enumerate(np.flatnonzero(test)):
                row = dict(metadata[int(global_index)])
                row.update(
                    {
                        "p_under_5": float(probability[local_index, 0]),
                        "p_return_5_9": float(probability[local_index, 1]),
                        "p_haul_10_plus": float(probability[local_index, 2]),
                        "return_distribution_expected_points": float(expected[local_index]),
                        "calibration_temperature": temperature,
                    }
                )
                rows.append(row)
    if len(rows) != pq.read_table(BACKTEST_FORECAST).num_rows:
        raise RuntimeError(
            "Return-distribution OOF coverage does not match the direct forecast backtest"
        )
    return rows, fits


def _spearman(actual: np.ndarray, predicted: np.ndarray) -> float:
    if len(actual) < 3 or np.std(actual) < 1e-12 or np.std(predicted) < 1e-12:
        return float("nan")
    return float(
        np.corrcoef(
            rankdata(actual, method="average"), rankdata(predicted, method="average")
        )[0, 1]
    )


def _event_spearman(events: np.ndarray, actual: np.ndarray, predicted: np.ndarray) -> float:
    values = []
    for event in np.unique(events):
        selected = events == event
        value = _spearman(actual[selected], predicted[selected])
        if np.isfinite(value):
            values.append(value)
    return float(np.mean(values))


def _top_k_points(
    events: np.ndarray, actual: np.ndarray, predicted: np.ndarray, top_k: int
) -> float:
    values = []
    for event in np.unique(events):
        indices = np.flatnonzero(events == event)
        selected = indices[np.argsort(predicted[indices])[-top_k:]]
        values.append(float(actual[selected].mean()))
    return float(np.mean(values))


def _safe_auc(labels: np.ndarray, predicted: np.ndarray) -> float | None:
    if labels.min() == labels.max():
        return None
    return float(roc_auc_score(labels, predicted))


def _forecast_metrics(
    merged: list[dict[str, Any]], score_field: str, *, include_probabilities: bool = False
) -> list[dict[str, Any]]:
    output = []
    for season in TEST_SEASONS:
        for position in POSITIONS:
            rows = [
                row
                for row in merged
                if row["season"] == season and row["position"] == position
            ]
            actual = np.asarray([row["target_points"] for row in rows], dtype=np.float64)
            predicted = np.asarray([row[score_field] for row in rows], dtype=np.float64)
            events = np.asarray([row["event_number"] for row in rows], dtype=np.int16)
            metric: dict[str, Any] = {
                "season": season,
                "position": position,
                "rows": len(rows),
                "mae": float(mean_absolute_error(actual, predicted)),
                "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
                "event_spearman": _event_spearman(events, actual, predicted),
                "top_k_actual_points": _top_k_points(
                    events, actual, predicted, TOP_K[position]
                ),
            }
            if include_probabilities:
                p_return = np.asarray(
                    [row["p_return_5_9"] + row["p_haul_10_plus"] for row in rows]
                )
                p_haul = np.asarray([row["p_haul_10_plus"] for row in rows])
                is_return = (actual >= 5.0).astype(np.int8)
                is_haul = (actual >= 10.0).astype(np.int8)
                metric.update(
                    {
                        "return_5_plus_brier": float(np.mean(np.square(p_return - is_return))),
                        "return_5_plus_auc": _safe_auc(is_return, p_return),
                        "haul_10_plus_brier": float(np.mean(np.square(p_haul - is_haul))),
                        "haul_10_plus_auc": _safe_auc(is_haul, p_haul),
                    }
                )
            output.append(metric)
    return output


def _merge_oof(distribution_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    challenger = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in distribution_rows
    }
    merged = []
    for row in pq.read_table(BACKTEST_FORECAST).to_pylist():
        key = (str(row["season"]), int(row["event_number"]), int(row["element"]))
        candidate = challenger.get(key)
        if candidate is None:
            raise RuntimeError(f"Missing return-distribution prediction for {key}")
        merged.append(
            {
                **row,
                "target_minutes": float(candidate["target_minutes"]),
                "p_under_5": float(candidate["p_under_5"]),
                "p_return_5_9": float(candidate["p_return_5_9"]),
                "p_haul_10_plus": float(candidate["p_haul_10_plus"]),
                "return_distribution_expected_points": float(
                    candidate["return_distribution_expected_points"]
                ),
            }
        )
    return merged


def _group_policy_rows(
    merged: list[dict[str, Any]],
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in merged:
        season = str(row["season"])
        if season not in TEST_SEASONS or row.get("market_price") is None:
            continue
        grouped[(season, int(row["event_number"]))].append(
            {
                **row,
                "market_price": round(float(row["market_price"])),
                "target_points": float(row["target_points"]),
                "target_minutes": float(row["target_minutes"]),
                "xp_expected_points": float(row["expected_points"]),
                "return_distribution_expected_points": float(
                    row["return_distribution_expected_points"]
                ),
                "can_select": True,
                "removed": False,
            }
        )
    for season in TEST_SEASONS:
        events = sorted(event for candidate, event in grouped if candidate == season)
        if events != list(range(1, 39)):
            raise ValueError(f"Return policy replay needs events 1-38 for {season}: {events}")
    return grouped


def _sequential_replay(
    grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> tuple[float, dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers, rules=rules
    )
    incumbent_validation = run_policy_season(
        season="2024-25",
        policy="incumbent_xp",
        grouped=grouped,
        market_weight=0.0,
        rules=rules,
        terminal_curve=terminal_curve,
    )
    validation_candidates = {
        weight: run_policy_season(
            season="2024-25",
            policy="return_distribution_challenger",
            grouped=grouped,
            market_weight=weight,
            rules=rules,
            terminal_curve=terminal_curve,
            score_field="return_distribution_expected_points",
        )
        for weight in BLEND_WEIGHTS
    }
    selected_weight = max(
        BLEND_WEIGHTS,
        key=lambda weight: (validation_candidates[weight]["net_points"], -weight),
    )
    paths = {
        ("2024-25", "incumbent_xp"): incumbent_validation,
        ("2024-25", "return_distribution_challenger"): validation_candidates[
            selected_weight
        ],
    }
    for season in ("2025-26",):
        paths[(season, "incumbent_xp")] = run_policy_season(
            season=season,
            policy="incumbent_xp",
            grouped=grouped,
            market_weight=0.0,
            rules=rules,
            terminal_curve=terminal_curve,
        )
        paths[(season, "return_distribution_challenger")] = run_policy_season(
            season=season,
            policy="return_distribution_challenger",
            grouped=grouped,
            market_weight=selected_weight,
            rules=rules,
            terminal_curve=terminal_curve,
            score_field="return_distribution_expected_points",
        )
    receipt = {
        "weights": [
            {
                "weight": weight,
                "gross_points": validation_candidates[weight]["gross_points"],
                "points_cost": validation_candidates[weight]["points_cost"],
                "net_points": validation_candidates[weight]["net_points"],
                "transfers": validation_candidates[weight]["transfers"],
                "rolls": validation_candidates[weight]["rolls"],
            }
            for weight in BLEND_WEIGHTS
        ],
        "selected_weight": selected_weight,
        "terminal_free_transfer_curve": terminal_receipt,
    }
    return selected_weight, receipt, paths


def _independent_replay(
    grouped: dict[tuple[str, int], list[dict[str, Any]]], weight: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rules = load_rules()
    event_rows = []
    for (season, event), rows in sorted(grouped.items()):
        incumbent = _solve(rows, [event], rules=rules)
        candidate_rows = [
            {
                **row,
                "expected_points": (
                    weight * row["return_distribution_expected_points"]
                    + (1.0 - weight) * row["xp_expected_points"]
                ),
            }
            for row in rows
        ]
        challenger = _solve(candidate_rows, [event], rules=rules)
        incumbent_score, challenger_score = _score_solutions(
            [("incumbent", incumbent), ("challenger", challenger)], rows, event
        )
        event_rows.append(
            {
                "season": season,
                "event": event,
                "incumbent_points": incumbent_score,
                "challenger_points": challenger_score,
                "delta": challenger_score - incumbent_score,
                "same_squad": set(incumbent["selected"]) == set(challenger["selected"]),
                "same_captain": (
                    incumbent["lineups"][event]["captain"]
                    == challenger["lineups"][event]["captain"]
                ),
                "squad_overlap": len(
                    set(incumbent["selected"]) & set(challenger["selected"])
                ),
            }
        )
    summary = {}
    for season in TEST_SEASONS:
        selected = [row for row in event_rows if row["season"] == season]
        deltas = np.asarray([row["delta"] for row in selected], dtype=np.float64)
        summary[season] = {
            "events": len(selected),
            "incumbent_points": sum(row["incumbent_points"] for row in selected),
            "challenger_points": sum(row["challenger_points"] for row in selected),
            "total_delta": int(deltas.sum()),
            "mean_delta": float(deltas.mean()),
            "same_squad_rate": float(np.mean([row["same_squad"] for row in selected])),
            "same_captain_rate": float(np.mean([row["same_captain"] for row in selected])),
            "mean_squad_overlap": float(np.mean([row["squad_overlap"] for row in selected])),
        }
    return event_rows, summary


def _decision_role_audit(
    grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> dict[str, Any]:
    rules = load_rules()
    result = {}
    for season in TEST_SEASONS:
        captain_actual = []
        best_starter_actual = []
        starter_actual = []
        bench_actual = []
        for event in range(1, 39):
            rows = grouped[(season, event)]
            solution = _solve(rows, [event], rules=rules)
            by_id = {int(row["element"]): row for row in rows}
            lineup = solution["lineups"][event]
            starters = [int(element) for element in lineup["starters"]]
            bench = [int(element) for element in lineup["bench_order"]]
            captain = int(lineup["captain"])
            captain_actual.append(float(by_id[captain]["target_points"]))
            best_starter_actual.append(
                max(float(by_id[element]["target_points"]) for element in starters)
            )
            starter_actual.extend(float(by_id[element]["target_points"]) for element in starters)
            bench_actual.extend(float(by_id[element]["target_points"]) for element in bench)
        result[season] = {
            "captain_actual_mean": float(np.mean(captain_actual)),
            "best_starter_actual_mean": float(np.mean(best_starter_actual)),
            "captain_oracle_headroom_per_gw": float(
                np.mean(np.asarray(best_starter_actual) - np.asarray(captain_actual))
            ),
            "starter_actual_mean": float(np.mean(starter_actual)),
            "bench_actual_mean": float(np.mean(bench_actual)),
        }
    return result


def _gate(
    selected_weight: float,
    paths: dict[tuple[str, str], dict[str, Any]],
    independent: dict[str, Any],
) -> dict[str, Any]:
    validation_delta = (
        paths[("2024-25", "return_distribution_challenger")]["net_points"]
        - paths[("2024-25", "incumbent_xp")]["net_points"]
    )
    challenger_events = paths[("2025-26", "return_distribution_challenger")]["events"]
    incumbent_events = paths[("2025-26", "incumbent_xp")]["events"]
    deltas = [
        challenger["net_points"] - incumbent["net_points"]
        for challenger, incumbent in zip(challenger_events, incumbent_events, strict=True)
    ]
    interval = moving_block_mean_interval(deltas, seed=20260809)
    test_delta = int(sum(deltas))
    checks = {
        "nonzero_weight_selected_on_validation": selected_weight > 0.0,
        "positive_validation_sequential_total": validation_delta > 0,
        "positive_frozen_test_sequential_total": test_delta > 0,
        "frozen_test_block_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
        "positive_frozen_test_independent_total": independent["2025-26"]["total_delta"] > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "validation_sequential_total_delta": validation_delta,
        "frozen_test_sequential_total_delta": test_delta,
        "frozen_test_sequential_mean_delta": test_delta / 38.0,
        "frozen_test_moving_block_interval": interval,
        "frozen_test_independent_total_delta": independent["2025-26"]["total_delta"],
        "frozen_test_independent_mean_delta": independent["2025-26"]["mean_delta"],
    }


def _render(result: dict[str, Any]) -> str:
    gate = result["gate"]
    lines = [
        "# Distribution-aware player-return challenger",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — validation selected a "
            f"{result['selected_challenger_weight']:.0%} return-distribution blend. The "
            f"untouched 2025/26 continuous transfer path changed by "
            f"{gate['frozen_test_sequential_total_delta']:+d} net points "
            f"({gate['frozen_test_sequential_mean_delta']:+.3f}/GW), with a four-GW "
            f"moving-block 95% interval of "
            f"{gate['frozen_test_moving_block_interval']['p025']:+.3f} to "
            f"{gate['frozen_test_moving_block_interval']['p975']:+.3f}/GW."
        ),
        "",
        "The candidate predicts three directly decision-relevant outcome bands—under five points, a 5–9 point return and a 10+ haul—then reconstructs expectation using class means learned only from seasons before the test deadline. It is an independent signal blended with the existing appearance × conditional-points xP model.",
        "",
        "## Why this target",
        "",
        "The incumbent ranks the broad player pool well, but discrimination compresses after the optimiser has already selected 15 good options. That leaves material XI and captain headroom even when squad selection is sound.",
        "",
        "| Season | Captain actual | Best starter actual | Captain headroom | Starter mean | Bench mean |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for season, row in result["decision_role_audit"].items():
        lines.append(
            f"| {season} | {row['captain_actual_mean']:.2f} | "
            f"{row['best_starter_actual_mean']:.2f} | "
            f"{row['captain_oracle_headroom_per_gw']:.2f} | "
            f"{row['starter_actual_mean']:.2f} | {row['bench_actual_mean']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Validation-only blend selection",
            "",
            "| Weight | Gross | Hits cost | Net | Transfers | Rolls |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["weight_calibration"]["weights"]:
        lines.append(
            f"| {row['weight']:.2f} | {row['gross_points']} | {row['points_cost']} | "
            f"{row['net_points']} | {row['transfers']} | {row['rolls']} |"
        )
    lines.extend(
        [
            "",
            "## Continuous season paths",
            "",
            "| Season | Policy | Gross | Hits cost | Net | Transfers | Rolls |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for season in POLICY_SEASONS:
        for policy in ("incumbent_xp", "return_distribution_challenger"):
            row = result["paths"][f"{season}:{policy}"]
            lines.append(
                f"| {season} | {policy} | {row['gross_points']} | {row['points_cost']} | "
                f"{row['net_points']} | {row['transfers']} | {row['rolls']} |"
            )
    lines.extend(
        [
            "",
            "## Independent legal squad replay",
            "",
            "| Season | Incumbent | Challenger | Delta/GW | Same squad | Same captain |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for season, row in result["independent_replay"].items():
        lines.append(
            f"| {season} | {row['incumbent_points']} | {row['challenger_points']} | "
            f"{row['mean_delta']:+.3f} | {row['same_squad_rate']:.1%} | "
            f"{row['same_captain_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Promotion contract",
            "",
            "- Architecture and calibration are season-forward: each OOF forecast trains before its prior-season validation block and never sees its test season.",
            "- The blend weight is selected on the 2024/25 continuous transfer path only. The 2025/26 path is untouched until the final gate.",
            "- Promotion requires positive validation, positive frozen sequential and independent totals, and a moving-block downside bound above -0.10 points/GW.",
            "- A failed challenger remains a research artifact and cannot alter the live forecast, squad, lineup, captain or transfer policy.",
            "",
        ]
    )
    return "\n".join(lines)


def run_return_distribution_challenger() -> dict[str, Any]:
    require_cuda()
    distribution_rows, fits = _build_oof()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(distribution_rows), OOF_FORECAST, compression="zstd")
    merged = _merge_oof(distribution_rows)
    grouped = _group_policy_rows(merged)
    incumbent_metrics = _forecast_metrics(merged, "expected_points")
    challenger_metrics = _forecast_metrics(
        merged, "return_distribution_expected_points", include_probabilities=True
    )
    role_audit = _decision_role_audit(grouped)
    selected_weight, calibration, paths = _sequential_replay(grouped)
    for row in merged:
        row["blended_return_expected_points"] = (
            selected_weight * float(row["return_distribution_expected_points"])
            + (1.0 - selected_weight) * float(row["expected_points"])
        )
    blended_metrics = _forecast_metrics(merged, "blended_return_expected_points")
    independent_events, independent = _independent_replay(grouped, selected_weight)
    gate = _gate(selected_weight, paths, independent)
    positive_but_uncertain = (
        selected_weight > 0.0
        and gate["validation_sequential_total_delta"] > 0
        and gate["frozen_test_sequential_total_delta"] > 0
        and gate["frozen_test_independent_total_delta"] > 0
    )
    verdict = (
        "PROMOTE"
        if gate["passed"]
        else "HOLD_SHADOW"
        if positive_but_uncertain
        else "REJECT"
    )
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "status": "production-candidate" if gate["passed"] else "shadow",
        "selected_challenger_weight": selected_weight,
        "model_contract": {
            "model_version": MODEL_VERSION,
            "classes": list(CLASS_NAMES),
            "features": list(MODEL_FEATURES),
            "seeds": list(SEEDS),
            "temperature_grid": list(TEMPERATURE_GRID),
            "validation_season": "2024-25",
            "frozen_test_season": "2025-26",
        },
        "fits": fits,
        "forecast_metrics": {
            "incumbent_xp": incumbent_metrics,
            "raw_return_distribution": challenger_metrics,
            "selected_blend": blended_metrics,
        },
        "decision_role_audit": role_audit,
        "weight_calibration": calibration,
        "gate": gate,
        "independent_replay": independent,
        "independent_events": independent_events,
        "paths": {f"{season}:{policy}": path for (season, policy), path in paths.items()},
        "artifacts": {
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "incumbent_oof": str(BACKTEST_FORECAST),
            "incumbent_oof_sha256": sha256_file(BACKTEST_FORECAST),
            "challenger_oof": str(OOF_FORECAST),
            "challenger_oof_sha256": sha256_file(OOF_FORECAST),
        },
    }
    temporary = RESULTS_JSON.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS_JSON)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
