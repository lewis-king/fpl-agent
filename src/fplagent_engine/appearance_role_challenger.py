from __future__ import annotations

import itertools
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .appearance_audit import _selectable_rows
from .appearance_challenger import (
    _decision_metrics,
    _probability_metrics,
)
from .appearance_policy_replay import _candidate_payload, policy_replay_gate
from .features import MODEL_FEATURES, TRAINING_FEATURES
from .models import (
    BACKTEST_FORECAST,
    SEEDS,
    TOP_K,
    _classifier,
    _matrix,
    _numeric,
    _season_weights,
    _strings,
    require_cuda,
)
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules
from .tournament import _score_candidates

OUTPUT_DIR = MODEL_DATA / "appearance_role_v1"
METRICS = OUTPUT_DIR / "metrics.json"
PREDICTIONS = OUTPUT_DIR / "predictions.parquet"
REPLAY = OUTPUT_DIR / "policy-replay.json"
REPORT = REPORTS / "appearance-role-challenger.md"
REPLAY_REPORT = REPORTS / "appearance-role-policy-replay.md"
TEST_SEASONS = ("2024-25", "2025-26")
POSITIONS = ("GK", "DEF", "MID", "FWD")

ROLE_FEATURES = (
    "role_appearance_rate10",
    "role_appearance_rate38",
    "role_start_rate3",
    "role_start_rate10",
    "role_start_rate38",
    "role_full_match_rate5",
    "role_full_match_rate10",
    "role_minutes_sd5",
    "role_minutes_sd10",
    "role_minutes_min5",
    "role_minutes_max5",
)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def build_role_feature_table(path: Path = TRAINING_FEATURES) -> pa.Table:
    """Build leakage-safe role features from outcomes strictly before each row."""
    connection = duckdb.connect()
    try:
        relation = connection.sql(
            f"""
            WITH rolling AS (
                SELECT
                    row_id,
                    player_days_since_last_event,
                    last_minutes,
                    avg(CASE WHEN target_minutes > 0 THEN 1.0 ELSE 0.0 END)
                        OVER role_10 AS role_appearance_rate10,
                    avg(CASE WHEN target_minutes > 0 THEN 1.0 ELSE 0.0 END)
                        OVER role_38 AS role_appearance_rate38,
                    avg(CASE WHEN target_minutes >= 60 THEN 1.0 ELSE 0.0 END)
                        OVER role_3 AS role_start_rate3,
                    avg(CASE WHEN target_minutes >= 60 THEN 1.0 ELSE 0.0 END)
                        OVER role_10 AS role_start_rate10,
                    avg(CASE WHEN target_minutes >= 60 THEN 1.0 ELSE 0.0 END)
                        OVER role_38 AS role_start_rate38,
                    avg(CASE WHEN target_minutes >= 90 THEN 1.0 ELSE 0.0 END)
                        OVER role_5 AS role_full_match_rate5,
                    avg(CASE WHEN target_minutes >= 90 THEN 1.0 ELSE 0.0 END)
                        OVER role_10 AS role_full_match_rate10,
                    stddev_pop(target_minutes) OVER role_5 AS role_minutes_sd5,
                    stddev_pop(target_minutes) OVER role_10 AS role_minutes_sd10,
                    min(target_minutes) OVER role_5 AS role_minutes_min5,
                    max(target_minutes) OVER role_5 AS role_minutes_max5
                FROM read_parquet('{_sql_path(path)}')
                WINDOW
                    role_3 AS (
                        PARTITION BY player_code ORDER BY season, event_number
                        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                    ),
                    role_5 AS (
                        PARTITION BY player_code ORDER BY season, event_number
                        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                    ),
                    role_10 AS (
                        PARTITION BY player_code ORDER BY season, event_number
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    ),
                    role_38 AS (
                        PARTITION BY player_code ORDER BY season, event_number
                        ROWS BETWEEN 38 PRECEDING AND 1 PRECEDING
                    )
            )
            SELECT
                row_id,
                role_appearance_rate10,
                role_appearance_rate38,
                role_start_rate3,
                role_start_rate10,
                role_start_rate38,
                role_full_match_rate5,
                role_full_match_rate10,
                role_minutes_sd5,
                role_minutes_sd10,
                role_minutes_min5,
                role_minutes_max5,
                CASE WHEN player_days_since_last_event >= 45 THEN 1.0 ELSE 0.0 END
                    AS role_season_boundary,
                CASE
                    WHEN player_days_since_last_event >= 45
                    THEN coalesce(role_start_rate38, 0.0)
                    ELSE 0.0
                END AS role_regular_before_boundary,
                CASE
                    WHEN player_days_since_last_event >= 45
                     AND coalesce(last_minutes, 0.0) = 0.0
                     AND coalesce(role_start_rate38, 0.0) >= 0.70
                    THEN 1.0 ELSE 0.0
                END AS role_isolated_rest_before_boundary
            FROM rolling
            ORDER BY row_id
            """
        )
        return relation.to_arrow_table()
    finally:
        connection.close()


def align_role_matrix(base: pa.Table, role: pa.Table) -> np.ndarray:
    row_ids = np.asarray(base["row_id"].to_pylist(), dtype=np.int64)
    role_ids = np.asarray(role["row_id"].to_pylist(), dtype=np.int64)
    expected = np.arange(1, base.num_rows + 1, dtype=np.int64)
    if not np.array_equal(role_ids, expected):
        raise ValueError("role feature rows must be contiguous and ordered by row_id")
    if len(np.unique(row_ids)) != base.num_rows or row_ids.min() != 1 or row_ids.max() != base.num_rows:
        raise ValueError("base feature row_id values must be a complete unique range")
    return _matrix(role, ROLE_FEATURES)[row_ids - 1]


def role_adjusted_play_probability(
    champion: np.ndarray | float,
    baseline_model: np.ndarray | float,
    role_model: np.ndarray | float,
) -> np.ndarray:
    """Transfer only the role feature's odds effect onto the production champion."""
    champion_values = np.clip(np.asarray(champion, dtype=float), 1e-5, 1.0 - 1e-5)
    baseline_values = np.clip(np.asarray(baseline_model, dtype=float), 1e-5, 1.0 - 1e-5)
    role_values = np.clip(np.asarray(role_model, dtype=float), 1e-5, 1.0 - 1e-5)
    champion_logit = np.log(champion_values / (1.0 - champion_values))
    evidence_log_odds = np.log(role_values / (1.0 - role_values)) - np.log(
        baseline_values / (1.0 - baseline_values)
    )
    return 1.0 / (1.0 + np.exp(-(champion_logit + evidence_log_odds)))


def role_statistical_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "two_forward_slices": len(rows) == len(TEST_SEASONS),
        "play_brier_wins": all(row["role"]["play_brier"] < row["baseline"]["play_brier"] for row in rows),
        "play_log_loss_wins": all(
            row["role"]["play_log_loss"] < row["baseline"]["play_log_loss"] for row in rows
        ),
        "multiclass_log_loss_wins": all(
            row["role"]["multiclass_log_loss"]
            < row["baseline"]["multiclass_log_loss"]
            for row in rows
        ),
        "minutes_mae_wins": all(
            row["role"]["expected_minutes_mae"]
            < row["baseline"]["expected_minutes_mae"]
            for row in rows
        ),
        "points_mae_non_regression": all(
            row["challenger_decision"]["points_mae"]
            <= row["champion_decision"]["points_mae"] + 0.01
            for row in rows
        ),
        "top_k_non_regression": all(
            row["challenger_decision"]["top_k_actual_points"]
            >= row["champion_decision"]["top_k_actual_points"] - 0.025
            for row in rows
        ),
        "rank_non_regression": all(
            row["challenger_decision"]["gameweek_spearman"]
            >= row["champion_decision"]["gameweek_spearman"] - 0.01
            for row in rows
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run_role_appearance_challenger() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cuda = require_cuda()
    table = pq.read_table(TRAINING_FEATURES)
    role_table = build_role_feature_table()
    baseline_matrix = _matrix(table, MODEL_FEATURES)
    role_matrix = np.column_stack(
        [baseline_matrix, align_role_matrix(table, role_table)]
    ).astype(np.float32)
    rows = table.to_pylist()
    seasons = _strings(table, "season").astype(str)
    positions = _strings(table, "position").astype(str)
    events = _numeric(table, "event_number").astype(np.int16)
    elements = _numeric(table, "element").astype(np.int32)
    minute_classes = _numeric(table, "minutes_class").astype(np.int32)
    target_minutes = _numeric(table, "target_minutes")
    target_points = _numeric(table, "target_points")
    candidate = _selectable_rows()
    candidate_keys = {
        (str(season), int(event), int(element))
        for season, event, element in zip(
            candidate["season"],
            candidate["event_number"],
            candidate["element"],
            strict=True,
        )
    }
    champion = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
    }
    season_order = sorted(set(seasons.tolist()))
    validations: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []

    for test_season in TEST_SEASONS:
        prior = [season for season in season_order if season < test_season]
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        for position in POSITIONS:
            train = np.isin(seasons, training_seasons) & (positions == position)
            validation = (seasons == validation_season) & (positions == position)
            test = (seasons == test_season) & (positions == position)
            baseline_model = _classifier(SEEDS[0], 900, early_stopping=True)
            role_model = _classifier(SEEDS[0], 900, early_stopping=True)
            baseline_model.fit(
                baseline_matrix[train],
                minute_classes[train],
                sample_weight=_season_weights(seasons, train),
                eval_set=[(baseline_matrix[validation], minute_classes[validation])],
                verbose=False,
            )
            role_model.fit(
                role_matrix[train],
                minute_classes[train],
                sample_weight=_season_weights(seasons, train),
                eval_set=[(role_matrix[validation], minute_classes[validation])],
                verbose=False,
            )
            indices = np.asarray(
                [
                    index
                    for index in np.flatnonzero(test)
                    if (test_season, int(events[index]), int(elements[index]))
                    in candidate_keys
                    and (test_season, int(events[index]), int(elements[index])) in champion
                ],
                dtype=np.int64,
            )
            baseline_probabilities = baseline_model.predict_proba(baseline_matrix[indices])
            role_probabilities = role_model.predict_proba(role_matrix[indices])
            baseline_play = baseline_probabilities[:, 1:].sum(axis=1)
            role_play = role_probabilities[:, 1:].sum(axis=1)
            champion_play = np.asarray(
                [
                    float(champion[(test_season, int(events[index]), int(elements[index]))]["p_play"])
                    for index in indices
                ]
            )
            champion_points = np.asarray(
                [
                    float(
                        champion[(test_season, int(events[index]), int(elements[index]))][
                            "expected_points"
                        ]
                    )
                    for index in indices
                ]
            )
            adjusted_play = role_adjusted_play_probability(
                champion_play, baseline_play, role_play
            )
            adjusted_points = champion_points * adjusted_play / np.clip(
                champion_play, 0.01, 1.0
            )
            test_events = events[indices]
            validation_row = {
                "test_season": test_season,
                "validation_season": validation_season,
                "position": position,
                "rows": len(indices),
                "baseline": _probability_metrics(
                    minute_classes[indices], target_minutes[indices], baseline_probabilities
                ),
                "role": _probability_metrics(
                    minute_classes[indices], target_minutes[indices], role_probabilities
                ),
                "champion_decision": _decision_metrics(
                    events=test_events,
                    actual_points=target_points[indices],
                    expected_points=champion_points,
                    top_k=TOP_K[position],
                ),
                "challenger_decision": _decision_metrics(
                    events=test_events,
                    actual_points=target_points[indices],
                    expected_points=adjusted_points,
                    top_k=TOP_K[position],
                ),
            }
            validations.append(validation_row)
            for offset, index in enumerate(indices):
                prediction_rows.append(
                    {
                        "season": test_season,
                        "event_number": int(events[index]),
                        "element": int(elements[index]),
                        "player_name": str(rows[index]["player_name"]),
                        "position": position,
                        "baseline_model_p_play": float(baseline_play[offset]),
                        "role_model_p_play": float(role_play[offset]),
                        "champion_p_play": float(champion_play[offset]),
                        "challenger_p_play": float(adjusted_play[offset]),
                        "champion_expected_points": float(champion_points[offset]),
                        "challenger_expected_points": float(adjusted_points[offset]),
                        "target_points": float(target_points[index]),
                        "target_minutes": float(target_minutes[index]),
                    }
                )

    position_gate = {}
    for position in POSITIONS:
        selected = [row for row in validations if row["position"] == position]
        position_gate[position] = role_statistical_gate(selected)
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate_only",
        "production_changed": False,
        "cuda": cuda,
        "role_features": list(ROLE_FEATURES),
        "test_seasons": list(TEST_SEASONS),
        "validations": validations,
        "position_gate": position_gate,
        "positions_pending_policy_replay": [
            position for position in POSITIONS if position_gate[position]["passed"]
        ],
        "source_artifacts": {
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "backtest_forecast": str(BACKTEST_FORECAST),
            "backtest_forecast_sha256": sha256_file(BACKTEST_FORECAST),
        },
    }
    pq.write_table(pa.Table.from_pylist(prediction_rows), PREDICTIONS, compression="zstd")
    result["predictions"] = {
        "path": str(PREDICTIONS),
        "rows": len(prediction_rows),
        "sha256": sha256_file(PREDICTIONS),
    }
    METRICS.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render_challenger_report(result), encoding="utf-8")
    return result


def _score_policy_subset(
    subset: tuple[str, ...],
    predictions: dict[tuple[str, int, int], dict[str, Any]],
    feature_rows: dict[tuple[str, int, int], dict[str, Any]],
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    rules = load_rules()
    event_results = []
    for (season, event), champion_rows in sorted(grouped.items()):
        challenger_rows = []
        for row in champion_rows:
            output = dict(row)
            key = (season, event, int(row["element"]))
            if str(row["position"]) in subset and key in predictions:
                prediction = predictions[key]
                output["p_play"] = float(prediction["challenger_p_play"])
                output["expected_points"] = float(prediction["challenger_expected_points"])
            challenger_rows.append(output)
        champion_solution = _solve(champion_rows, [event], rules=rules)
        challenger_solution = _solve(challenger_rows, [event], rules=rules)
        player_ids = sorted(int(row["element"]) for row in champion_rows)
        actual = {
            player: feature_rows[(season, event, player)] for player in player_ids
        }
        points = np.asarray(
            [[[actual[player]["target_points"] for player in player_ids]]], dtype=np.int16
        )
        played = np.asarray(
            [[[actual[player]["target_minutes"] > 0 for player in player_ids]]], dtype=bool
        )
        candidates = [
            _candidate_payload(champion_solution, event),
            _candidate_payload(challenger_solution, event),
        ]
        scores = _score_candidates(
            candidates, player_ids, (event,), points, played, {int(row["element"]): row for row in champion_rows}
        )[0, :, 0]
        champion_selected = set(champion_solution["selected"])
        challenger_selected = set(challenger_solution["selected"])
        event_results.append(
            {
                "season": season,
                "event": event,
                "champion_points": int(scores[0]),
                "challenger_points": int(scores[1]),
                "calibrated_minus_raw_points": int(scores[1] - scores[0]),
                "squad_overlap": len(champion_selected & challenger_selected),
                "same_squad": champion_selected == challenger_selected,
                "champion_captain": int(champion_solution["lineups"][event]["captain"]),
                "challenger_captain": int(
                    challenger_solution["lineups"][event]["captain"]
                ),
            }
        )
    gate = policy_replay_gate(event_results)
    return {
        "positions": list(subset),
        "gate": gate,
        "exact_squad_rate": float(np.mean([row["same_squad"] for row in event_results])),
        "same_captain_rate": float(
            np.mean(
                [
                    row["champion_captain"] == row["challenger_captain"]
                    for row in event_results
                ]
            )
        ),
        "mean_squad_overlap": float(
            np.mean([row["squad_overlap"] for row in event_results])
        ),
        "events": event_results,
    }


def run_role_appearance_policy_replay() -> dict[str, Any]:
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    if sha256_file(PREDICTIONS) != metrics["predictions"]["sha256"]:
        raise ValueError("role appearance predictions do not match their metrics receipt")
    statistical_positions = tuple(
        position for position in POSITIONS if metrics["position_gate"][position]["passed"]
    )
    predictions = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(PREDICTIONS).to_pylist()
    }
    feature_rows = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in TEST_SEASONS
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(row["season"])
        if season not in TEST_SEASONS:
            continue
        market_price = row.get("market_price")
        if market_price is None or float(market_price) <= 0.0:
            continue
        key = (season, int(row["event_number"]), int(row["element"]))
        if key not in feature_rows:
            raise ValueError(f"role policy replay is missing evidence for {key}")
        grouped[(season, int(row["event_number"]))].append(row)

    subset_results = []
    for length in range(1, len(statistical_positions) + 1):
        for subset in itertools.combinations(statistical_positions, length):
            subset_results.append(
                _score_policy_subset(subset, predictions, feature_rows, grouped)
            )
    passing = [row for row in subset_results if row["gate"]["passed"]]
    selected = max(
        passing,
        key=lambda row: (row["gate"]["mean_delta"], len(row["positions"])),
        default=None,
    )
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate_only",
        "production_changed": False,
        "statistical_positions": list(statistical_positions),
        "subsets": subset_results,
        "selected_subset": selected["positions"] if selected else [],
        "promotion_ready": selected is not None,
        "source_artifacts": {
            "metrics": str(METRICS),
            "metrics_sha256": sha256_file(METRICS),
            "predictions": str(PREDICTIONS),
            "predictions_sha256": sha256_file(PREDICTIONS),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "backtest_forecast_sha256": sha256_file(BACKTEST_FORECAST),
        },
    }
    REPLAY.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPLAY_REPORT.write_text(_render_replay_report(result), encoding="utf-8")
    return result


def _render_challenger_report(result: dict[str, Any]) -> str:
    lines = [
        "# Preseason role appearance challenger",
        "",
        f"**Built:** {result['created_at']}  ",
        "**Production changed:** no",
        "",
        (
            "The challenger adds longer-horizon role and minute stability to the minute "
            "classifier. Every rolling feature uses outcomes strictly before the predicted row; "
            "there are no player-specific boosts. Explicit season-boundary interactions were "
            "rejected in feature ablation rather than retained after they regressed the first "
            "forward goalkeeper slice."
        ),
        "",
        "| Position | Statistical gate |",
        "| --- | --- |",
    ]
    for position in POSITIONS:
        lines.append(
            f"| {position} | {'PASS' if result['position_gate'][position]['passed'] else 'REJECT'} |"
        )
    lines.extend(
        [
            "",
            "| Season | Pos | Play Brier | Role Brier | Minutes MAE | Role MAE | xP MAE Δ |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result["validations"]:
        lines.append(
            f"| {row['test_season']} | {row['position']} | "
            f"{row['baseline']['play_brier']:.4f} | {row['role']['play_brier']:.4f} | "
            f"{row['baseline']['expected_minutes_mae']:.2f} | "
            f"{row['role']['expected_minutes_mae']:.2f} | "
            f"{row['challenger_decision']['points_mae'] - row['champion_decision']['points_mae']:+.3f} |"
        )
    lines.extend(
        [
            "",
            "A statistical pass is only permission to run legal squad policy replay, not promotion.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_replay_report(result: dict[str, Any]) -> str:
    lines = [
        "# Preseason role appearance policy replay",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Statistical positions:** {', '.join(result['statistical_positions']) or 'none'}  ",
        f"**Promotion ready:** {'yes' if result['promotion_ready'] else 'no'}",
        "",
        "| Applied positions | Mean points Δ | 95% interval | Season floor | Gate |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in result["subsets"]:
        gate = row["gate"]
        lines.append(
            f"| {', '.join(row['positions'])} | {gate['mean_delta']:+.3f} | "
            f"[{gate['delta_95ci_low']:+.3f}, {gate['delta_95ci_high']:+.3f}] | "
            f"{min(gate['season_mean_delta'].values()):+.3f} | "
            f"{'PASS' if gate['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            (
                "No production artifact changes unless a subset passes both the statistical and "
                "paired legal-squad gates."
            ),
            "",
        ]
    )
    return "\n".join(lines)
