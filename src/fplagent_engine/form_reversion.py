from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .features import TRAINING_FEATURES
from .market_transfer_replay import moving_block_mean_interval, run_policy_season
from .models import BACKTEST_FORECAST
from .paths import MODEL_DATA, REPORTS
from .rules import load_rules
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_simulation import evaluate_action_paths

OUTPUT_DIR = MODEL_DATA / "form_reversion_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "form-reversion-policy-replay.md"

VALIDATION_SEASON = "2024-25"
TEST_SEASON = "2025-26"
POLICY_SEASONS = (VALIDATION_SEASON, TEST_SEASON)
CORRECTION_WEIGHTS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25)
POSITIONS = ("GK", "DEF", "MID", "FWD")
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 20260818


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    candidate = float(value)
    return candidate if np.isfinite(candidate) else default


def _quantile_summary(features_path: Path) -> list[dict[str, Any]]:
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        WITH ordered AS (
            SELECT
                *,
                avg(target_points) OVER (
                    PARTITION BY season, element ORDER BY event_number
                    ROWS BETWEEN CURRENT ROW AND 2 FOLLOWING
                ) AS forward3_points,
                count(target_points) OVER (
                    PARTITION BY season, element ORDER BY event_number
                    ROWS BETWEEN CURRENT ROW AND 2 FOLLOWING
                ) AS forward3_count,
                avg(target_points) OVER (
                    PARTITION BY season, element ORDER BY event_number
                    ROWS BETWEEN CURRENT ROW AND 4 FOLLOWING
                ) AS forward5_points,
                count(target_points) OVER (
                    PARTITION BY season, element ORDER BY event_number
                    ROWS BETWEEN CURRENT ROW AND 4 FOLLOWING
                ) AS forward5_count
            FROM read_parquet('{_sql_path(features_path)}')
        ), eligible AS (
            SELECT
                *,
                form3_points - form10_points AS recent_points_delta
            FROM ordered
            WHERE history_events >= 10
              AND appearance_rate5 >= 0.8
              AND form10_minutes >= 60
              AND fixture_count = 1
              AND event_number BETWEEN 6 AND 33
              AND form3_points IS NOT NULL
              AND form10_points IS NOT NULL
              AND forward3_count = 3
              AND forward5_count = 5
        ), ranked AS (
            SELECT
                *,
                ntile(5) OVER (
                    PARTITION BY season, position
                    ORDER BY recent_points_delta, element, event_number
                ) AS streak_quintile
            FROM eligible
        )
        SELECT
            position,
            streak_quintile,
            count(*) AS rows,
            avg(form3_points) AS recent_three_points,
            avg(form10_points) AS longer_ten_points,
            avg(target_points) AS next_event_points,
            avg(forward3_points) AS forward_three_points,
            avg(forward5_points) AS forward_five_points,
            avg(target_minutes) AS next_event_minutes
        FROM ranked
        GROUP BY position, streak_quintile
        ORDER BY position, streak_quintile
        """
    ).fetchall()
    connection.close()
    columns = (
        "position",
        "streak_quintile",
        "rows",
        "recent_three_points",
        "longer_ten_points",
        "next_event_points",
        "forward_three_points",
        "forward_five_points",
        "next_event_minutes",
    )
    output = [dict(zip(columns, row, strict=True)) for row in rows]
    for item in output:
        item["streak_quintile"] = int(item["streak_quintile"])
        item["rows"] = int(item["rows"])
        for name in columns[3:]:
            item[name] = float(item[name])
    return output


def _aggregate_quintiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value_fields = (
        "recent_three_points",
        "longer_ten_points",
        "next_event_points",
        "forward_three_points",
        "forward_five_points",
        "next_event_minutes",
    )
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["streak_quintile"])].append(row)
    output = []
    for quintile, members in sorted(grouped.items()):
        total = sum(int(member["rows"]) for member in members)
        aggregate: dict[str, Any] = {"streak_quintile": quintile, "rows": total}
        for field in value_fields:
            aggregate[field] = sum(
                int(member["rows"]) * float(member[field]) for member in members
            ) / total
        output.append(aggregate)
    return output


def _demeaned_regression_rows(features_path: Path) -> dict[str, np.ndarray]:
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        SELECT
            season,
            event_number,
            position,
            target_points,
            form10_points,
            form3_points - form10_points AS recent_points_delta,
            form10_minutes,
            team_expected_goals,
            availability_chance
        FROM read_parquet('{_sql_path(features_path)}')
        WHERE history_events >= 10
          AND appearance_rate5 >= 0.8
          AND form10_minutes >= 60
          AND fixture_count = 1
          AND event_number BETWEEN 6 AND 35
          AND form3_points IS NOT NULL
          AND form10_points IS NOT NULL
          AND team_expected_goals IS NOT NULL
          AND availability_chance IS NOT NULL
        ORDER BY season, event_number, position, element
        """
    ).fetchall()
    connection.close()
    seasons = np.asarray([str(row[0]) for row in rows], dtype=object)
    events = np.asarray([int(row[1]) for row in rows], dtype=np.int16)
    positions = np.asarray([str(row[2]) for row in rows], dtype=object)
    target = np.asarray([float(row[3]) for row in rows], dtype=np.float64)
    matrix = np.asarray([row[4:] for row in rows], dtype=np.float64)
    groups = np.asarray(
        [f"{season}|{event}|{position}" for season, event, position in zip(
            seasons, events, positions, strict=True
        )],
        dtype=object,
    )
    for group in np.unique(groups):
        selected = groups == group
        target[selected] -= target[selected].mean()
        matrix[selected] -= matrix[selected].mean(axis=0)
    return {
        "season": seasons,
        "event": events,
        "position": positions,
        "target": target,
        "matrix": matrix,
    }


def _fit_regression(target: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if len(target) <= matrix.shape[1]:
        raise ValueError("Form-persistence regression has insufficient rows")
    return np.linalg.lstsq(matrix, target, rcond=None)[0]


def _cluster_bootstrap_interval(
    data: dict[str, np.ndarray], *, samples: int, seed: int
) -> dict[str, float | int]:
    target = data["target"]
    matrix = data["matrix"]
    clusters = np.asarray(
        [f"{season}|{event}" for season, event in zip(
            data["season"], data["event"], strict=True
        )],
        dtype=object,
    )
    labels = np.unique(clusters)
    xtx = []
    xty = []
    for label in labels:
        selected = clusters == label
        local = matrix[selected]
        xtx.append(local.T @ local)
        xty.append(local.T @ target[selected])
    xtx_array = np.asarray(xtx)
    xty_array = np.asarray(xty)
    rng = np.random.default_rng(seed)
    estimates = np.empty(samples, dtype=np.float64)
    for offset in range(samples):
        sampled = rng.integers(0, len(labels), size=len(labels))
        coefficients = np.linalg.lstsq(
            xtx_array[sampled].sum(axis=0),
            xty_array[sampled].sum(axis=0),
            rcond=None,
        )[0]
        estimates[offset] = coefficients[1]
    return {
        "clusters": len(labels),
        "samples": samples,
        "seed": seed,
        "p025": float(np.quantile(estimates, 0.025)),
        "median": float(np.median(estimates)),
        "p975": float(np.quantile(estimates, 0.975)),
    }


def _persistence_regression(features_path: Path) -> dict[str, Any]:
    data = _demeaned_regression_rows(features_path)
    names = (
        "longer_ten_points",
        "recent_points_delta",
        "longer_ten_minutes",
        "team_expected_goals",
        "availability_chance",
    )
    coefficients = _fit_regression(data["target"], data["matrix"])
    by_position = {}
    for position in POSITIONS:
        selected = data["position"] == position
        local = _fit_regression(data["target"][selected], data["matrix"][selected])
        by_position[position] = {
            "rows": int(selected.sum()),
            "coefficients": {
                name: float(value) for name, value in zip(names, local, strict=True)
            },
            "recent_points_persistence": float(local[1]),
        }
    return {
        "rows": len(data["target"]),
        "fixed_effects": "season x event x position demeaning",
        "coefficients": {
            name: float(value) for name, value in zip(names, coefficients, strict=True)
        },
        "recent_points_persistence": float(coefficients[1]),
        "recent_points_regression_fraction": float(1.0 - coefficients[1]),
        "cluster_bootstrap_95ci": _cluster_bootstrap_interval(
            data,
            samples=BOOTSTRAP_SAMPLES,
            seed=BOOTSTRAP_SEED,
        ),
        "by_position": by_position,
    }


def _process_confirmation(features_path: Path) -> list[dict[str, Any]]:
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        WITH ordered AS (
            SELECT
                *,
                avg(target_points) OVER (
                    PARTITION BY season, element ORDER BY event_number
                    ROWS BETWEEN CURRENT ROW AND 4 FOLLOWING
                ) AS forward5_points,
                count(target_points) OVER (
                    PARTITION BY season, element ORDER BY event_number
                    ROWS BETWEEN CURRENT ROW AND 4 FOLLOWING
                ) AS forward5_count
            FROM read_parquet('{_sql_path(features_path)}')
        ), eligible AS (
            SELECT
                *,
                form3_points - form10_points AS recent_points_delta,
                (form5_xg + form5_xa) * 90 / nullif(form5_minutes, 0) AS xgi_per_90
            FROM ordered
            WHERE history_events >= 10
              AND appearance_rate5 >= 0.8
              AND form10_minutes >= 60
              AND fixture_count = 1
              AND event_number BETWEEN 6 AND 31
              AND position IN ('MID', 'FWD')
              AND form3_points IS NOT NULL
              AND form10_points IS NOT NULL
              AND form5_xg IS NOT NULL
              AND form5_xa IS NOT NULL
              AND forward5_count = 5
        ), ranked AS (
            SELECT
                *,
                ntile(5) OVER (
                    PARTITION BY season, position
                    ORDER BY recent_points_delta, element, event_number
                ) AS streak_quintile,
                ntile(2) OVER (
                    PARTITION BY season, event_number, position
                    ORDER BY xgi_per_90, element
                ) AS process_half
            FROM eligible
        )
        SELECT
            CASE WHEN streak_quintile = 5 THEN 'hot' ELSE 'cold' END AS streak,
            CASE WHEN process_half = 2 THEN 'strong_process' ELSE 'weak_process' END
                AS process,
            count(*) AS rows,
            avg(form3_points) AS recent_three_points,
            avg(form10_points) AS longer_ten_points,
            avg(target_points) AS next_event_points,
            avg(forward5_points) AS forward_five_points,
            avg(xgi_per_90) AS xgi_per_90
        FROM ranked
        WHERE streak_quintile IN (1, 5)
        GROUP BY streak, process
        ORDER BY streak, process
        """
    ).fetchall()
    connection.close()
    columns = (
        "streak",
        "process",
        "rows",
        "recent_three_points",
        "longer_ten_points",
        "next_event_points",
        "forward_five_points",
        "xgi_per_90",
    )
    output = [dict(zip(columns, row, strict=True)) for row in rows]
    for item in output:
        item["rows"] = int(item["rows"])
        for name in columns[3:]:
            item[name] = float(item[name])
    return output


def _historical_audit(features_path: Path) -> dict[str, Any]:
    position_rows = _quantile_summary(features_path)
    aggregate = _aggregate_quintiles(position_rows)
    regression = _persistence_regression(features_path)
    process = _process_confirmation(features_path)
    hot = next(row for row in aggregate if row["streak_quintile"] == 5)
    cold = next(row for row in aggregate if row["streak_quintile"] == 1)
    checks = {
        "aggregate_recent_points_persistence_below_0_25": (
            regression["recent_points_persistence"] < 0.25
        ),
        "bootstrap_upper_bound_below_0_25": (
            regression["cluster_bootstrap_95ci"]["p975"] < 0.25
        ),
        "every_position_persistence_below_0_25": all(
            row["recent_points_persistence"] < 0.25
            for row in regression["by_position"].values()
        ),
        "hot_forward_five_below_recent_three": (
            hot["forward_five_points"] < hot["recent_three_points"]
        ),
        "cold_forward_five_above_recent_three": (
            cold["forward_five_points"] > cold["recent_three_points"]
        ),
    }
    return {
        "sample_contract": {
            "history_events_minimum": 10,
            "appearance_rate5_minimum": 0.8,
            "form10_minutes_minimum": 60,
            "single_fixture_events_only": True,
            "lagged_features_only": True,
        },
        "aggregate_streak_quintiles": aggregate,
        "position_streak_quintiles": position_rows,
        "persistence_regression": regression,
        "process_confirmation": process,
        "checks": checks,
        "classification": (
            "strong_mean_reversion_observed" if all(checks.values()) else "mixed_evidence"
        ),
    }


def _process_percentiles(rows: list[dict[str, Any]]) -> dict[int, float]:
    groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for row in rows:
        position = str(row["position"])
        if position not in {"MID", "FWD"}:
            continue
        minutes = _float(row.get("form5_minutes"))
        xg = row.get("form5_xg")
        xa = row.get("form5_xa")
        if minutes <= 0.0 or xg is None or xa is None:
            continue
        process = (_float(xg) + _float(xa)) * 90.0 / minutes
        groups[position].append((int(row["element"]), process))
    output: dict[int, float] = {}
    for members in groups.values():
        ordered = sorted(members, key=lambda item: (item[1], item[0]))
        denominator = max(len(ordered) - 1, 1)
        for rank, (element, _) in enumerate(ordered):
            output[element] = rank / denominator
    return output


def build_form_reversion_shadow_scores(
    rows: list[dict[str, Any]],
    *,
    results_path: Path = RESULTS_JSON,
) -> tuple[dict[tuple[int, int], float], dict[str, Any]]:
    """Build paired shadow means without giving the challenger decision authority."""
    if not results_path.is_file():
        return {}, {"status": "not_available", "reason": "replay artifact is missing"}
    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, {"status": "not_available", "reason": f"replay artifact is unreadable: {exc}"}
    if payload.get("verdict") not in {"HOLD_SHADOW", "PASS_SHADOW"}:
        return {}, {
            "status": "not_available",
            "reason": f"replay verdict {payload.get('verdict')!r} is not shadow-eligible",
        }
    artifacts = payload.get("artifacts", {})
    expected_features = artifacts.get("training_features_sha256")
    expected_oof = artifacts.get("incumbent_oof_sha256")
    if (
        expected_features != sha256_file(TRAINING_FEATURES)
        or expected_oof != sha256_file(BACKTEST_FORECAST)
    ):
        return {}, {"status": "not_available", "reason": "replay lineage is stale"}
    replay = payload["sequential_replay"]
    score_field = str(replay["selected_score_field"])
    weight = float(replay["selected_correction_weight"])
    if score_field not in {
        "points_reversion_expected_points",
        "process_reversion_expected_points",
    } or not 0.0 < weight <= 1.0:
        return {}, {"status": "not_available", "reason": "replay selected no valid correction"}

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["event_number"])].append(row)
    scores: dict[tuple[int, int], float] = {}
    adjustments = []
    for event, event_rows in grouped.items():
        percentiles = _process_percentiles(event_rows)
        for row in event_rows:
            element = int(row["element"])
            expected = float(row["expected_points"])
            form3 = row.get("form3_points")
            form10 = row.get("form10_points")
            streak = (
                float(np.clip(float(form3) - float(form10), -3.0, 3.0))
                if form3 is not None and form10 is not None
                else 0.0
            )
            signal = streak
            percentile = percentiles.get(element)
            if score_field == "process_reversion_expected_points" and percentile is not None:
                signal = (
                    streak * (1.0 - percentile)
                    if streak >= 0.0
                    else streak * percentile
                )
            adjusted = expected - weight * signal
            scores[(event, element)] = adjusted
            adjustments.append(adjusted - expected)
    return scores, {
        "status": "ready_shadow",
        "decision_authority": False,
        "score_field": score_field,
        "correction_weight": weight,
        "artifact": str(results_path),
        "artifact_sha256": sha256_file(results_path),
        "player_event_scores": len(scores),
        "mean_adjustment": float(np.mean(adjustments)) if adjustments else 0.0,
        "maximum_absolute_adjustment": (
            float(np.max(np.abs(adjustments))) if adjustments else 0.0
        ),
    }


def evaluate_form_reversion_shadow(
    actions: list[Any],
    rows: list[dict[str, Any]],
    *,
    player_ids: list[int],
    events: tuple[int, ...],
    points: np.ndarray,
    played: np.ndarray,
    player_meta: dict[int, dict[str, Any]],
    horizon_decay: float,
    results_path: Path = RESULTS_JSON,
) -> dict[str, Any]:
    scores, diagnostics = build_form_reversion_shadow_scores(
        rows,
        results_path=results_path,
    )
    if not scores:
        return diagnostics
    shifts = np.zeros((len(events), len(player_ids)), dtype=np.float64)
    by_event = {event: offset for offset, event in enumerate(events)}
    by_player = {element: offset for offset, element in enumerate(player_ids)}
    expected = {
        (int(row["event_number"]), int(row["element"])): float(row["expected_points"])
        for row in rows
        if int(row["event_number"]) in by_event and int(row["element"]) in by_player
    }
    for key, adjusted in scores.items():
        event, element = key
        if event in by_event and element in by_player and key in expected:
            shifts[by_event[event], by_player[element]] = adjusted - expected[key]
    metrics, _ = evaluate_action_paths(
        actions,
        player_ids=player_ids,
        events=events,
        points=points.astype(np.float64) + shifts[None, :, :],
        played=played,
        player_meta=player_meta,
        horizon_decay=horizon_decay,
    )
    leader = min(metrics, key=lambda item: (item.scenario_regret, item.action_id))
    return {
        **diagnostics,
        "leader_action_id": leader.action_id,
        "leader_route_type": leader.route_type,
        "metrics_by_action": {item.action_id: asdict(item) for item in metrics},
    }


def _enrich_replay_rows() -> dict[tuple[str, int], list[dict[str, Any]]]:
    features = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in POLICY_SEASONS
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for raw in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(raw["season"])
        if season not in POLICY_SEASONS:
            continue
        key = (season, int(raw["event_number"]), int(raw["element"]))
        feature = features.get(key)
        if feature is None or raw.get("market_price") is None:
            continue
        xp = float(raw["expected_points"])
        form3 = feature.get("form3_points")
        form10 = feature.get("form10_points")
        streak = (
            float(np.clip(float(form3) - float(form10), -3.0, 3.0))
            if form3 is not None and form10 is not None
            else 0.0
        )
        row = {
            **raw,
            "market_price": round(float(raw["market_price"])),
            "target_points": float(raw["target_points"]),
            "target_minutes": float(feature["target_minutes"]),
            "xp_expected_points": xp,
            "form3_points": _float(form3, xp),
            "form10_points": _float(form10, xp),
            "recent_points_delta": streak,
            "form5_xg": feature.get("form5_xg"),
            "form5_xa": feature.get("form5_xa"),
            "form5_minutes": feature.get("form5_minutes"),
            "p_play": float(raw.get("p_play", 1.0)),
            "can_select": True,
            "removed": False,
        }
        grouped[(season, int(raw["event_number"]))].append(row)
    for (season, event), rows in grouped.items():
        percentiles = _process_percentiles(rows)
        for row in rows:
            streak = float(row["recent_points_delta"])
            percentile = percentiles.get(int(row["element"]))
            if percentile is None:
                unsupported = streak
            elif streak >= 0.0:
                unsupported = streak * (1.0 - percentile)
            else:
                unsupported = streak * percentile
            xp = float(row["xp_expected_points"])
            row["points_reversion_expected_points"] = xp - streak
            row["process_reversion_expected_points"] = xp - unsupported
            row["naive_form_expected_points"] = max(float(row["form3_points"]), 0.0)
            row["process_percentile"] = percentile
    for season in POLICY_SEASONS:
        events = sorted(event for candidate, event in grouped if candidate == season)
        if events != list(range(1, 39)):
            raise ValueError(f"Form replay requires events 1-38 for {season}: {events}")
    return dict(grouped)


def _path_diagnostics(
    path: dict[str, Any], grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> dict[str, Any]:
    season = str(path["season"])
    event_rows = {int(row["event"]): row for row in path["events"]}
    short_exits = 0
    three_event_deltas = []
    for event, record in event_rows.items():
        for transfer in record["transfers"]:
            outgoing = int(transfer["out"])
            incoming = int(transfer["in"])
            for later in range(event + 1, min(event + 2, 38) + 1):
                if any(
                    int(candidate["out"]) == incoming
                    for candidate in event_rows[later]["transfers"]
                ):
                    short_exits += 1
                    break
            delta = 0.0
            observed = 0
            for future in range(event, min(event + 2, 38) + 1):
                by_id = {
                    int(row["element"]): row for row in grouped[(season, future)]
                }
                if incoming in by_id and outgoing in by_id:
                    delta += float(by_id[incoming]["target_points"])
                    delta -= float(by_id[outgoing]["target_points"])
                    observed += 1
            if observed:
                three_event_deltas.append(delta)
    transfer_count = int(path["transfers"])
    return {
        "transfers": transfer_count,
        "rolls": int(path["rolls"]),
        "short_horizon_exits_within_two_events": short_exits,
        "short_horizon_exit_rate": short_exits / transfer_count if transfer_count else 0.0,
        "three_event_transfer_comparisons": len(three_event_deltas),
        "positive_three_event_transfer_rate": (
            float(np.mean(np.asarray(three_event_deltas) > 0.0))
            if three_event_deltas
            else 0.0
        ),
        "mean_three_event_incoming_minus_outgoing": (
            float(np.mean(three_event_deltas)) if three_event_deltas else 0.0
        ),
    }


def _run_replay(
    grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> dict[str, Any]:
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers,
        rules=rules,
    )
    score_fields = (
        "points_reversion_expected_points",
        "process_reversion_expected_points",
    )
    validation: dict[tuple[str, float], dict[str, Any]] = {}
    for score_field in score_fields:
        for weight in CORRECTION_WEIGHTS:
            validation[(score_field, weight)] = run_policy_season(
                season=VALIDATION_SEASON,
                policy=score_field,
                grouped=grouped,
                market_weight=weight,
                rules=rules,
                terminal_curve=terminal_curve,
                score_field=score_field,
            )
    selected_field, selected_weight = max(
        validation,
        key=lambda key: (
            validation[key]["net_points"],
            -key[1],
            key[0] == "process_reversion_expected_points",
        ),
    )
    incumbent_validation = validation[(selected_field, 0.0)]
    incumbent_validation = {**incumbent_validation, "policy": "incumbent_xp"}
    selected_validation = validation[(selected_field, selected_weight)]
    incumbent_test = run_policy_season(
        season=TEST_SEASON,
        policy="incumbent_xp",
        grouped=grouped,
        market_weight=0.0,
        rules=rules,
        terminal_curve=terminal_curve,
        score_field=selected_field,
    )
    selected_test = run_policy_season(
        season=TEST_SEASON,
        policy=selected_field,
        grouped=grouped,
        market_weight=selected_weight,
        rules=rules,
        terminal_curve=terminal_curve,
        score_field=selected_field,
    )
    naive_paths = {
        season: run_policy_season(
            season=season,
            policy="naive_form",
            grouped=grouped,
            market_weight=1.0,
            rules=rules,
            terminal_curve=terminal_curve,
            score_field="naive_form_expected_points",
        )
        for season in POLICY_SEASONS
    }
    paths = {
        f"{VALIDATION_SEASON}:incumbent_xp": incumbent_validation,
        f"{VALIDATION_SEASON}:selected_reversion": selected_validation,
        f"{VALIDATION_SEASON}:naive_form": naive_paths[VALIDATION_SEASON],
        f"{TEST_SEASON}:incumbent_xp": incumbent_test,
        f"{TEST_SEASON}:selected_reversion": selected_test,
        f"{TEST_SEASON}:naive_form": naive_paths[TEST_SEASON],
    }
    validation_delta = selected_validation["net_points"] - incumbent_validation["net_points"]
    test_event_deltas = [
        challenger["net_points"] - incumbent["net_points"]
        for challenger, incumbent in zip(
            selected_test["events"], incumbent_test["events"], strict=True
        )
    ]
    interval = moving_block_mean_interval(test_event_deltas, seed=20260819)
    test_delta = int(sum(test_event_deltas))
    checks = {
        "nonzero_correction_selected_on_validation": selected_weight > 0.0,
        "positive_validation_sequential_total": validation_delta > 0,
        "positive_frozen_test_sequential_total": test_delta > 0,
        "frozen_test_block_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
    }
    return {
        "selected_score_field": selected_field,
        "selected_correction_weight": selected_weight,
        "weight_calibration": [
            {
                "score_field": field,
                "correction_weight": weight,
                "net_points": path["net_points"],
                "gross_points": path["gross_points"],
                "points_cost": path["points_cost"],
                "transfers": path["transfers"],
                "rolls": path["rolls"],
            }
            for (field, weight), path in sorted(validation.items())
        ],
        "gate": {
            "passed": all(checks.values()),
            "checks": checks,
            "validation_total_delta": validation_delta,
            "frozen_test_total_delta": test_delta,
            "frozen_test_mean_delta": test_delta / 38.0,
            "frozen_test_moving_block_interval": interval,
        },
        "terminal_free_transfer_value": terminal_receipt,
        "path_diagnostics": {
            key: _path_diagnostics(path, grouped) for key, path in paths.items()
        },
        "paths": paths,
    }


def _render(result: dict[str, Any]) -> str:
    audit = result["historical_audit"]
    replay = result["sequential_replay"]
    gate = replay["gate"]
    regression = audit["persistence_regression"]
    lines = [
        "# Form persistence and mean-reversion policy replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — the lagged historical audit classifies the evidence as "
            f"`{audit['classification']}`. Only "
            f"{regression['recent_points_persistence']:.1%} of a recent three-versus-ten-event "
            "points deviation carries into the next event after the declared controls."
        ),
        "",
        (
            f"Validation selected `{replay['selected_score_field']}` at a "
            f"{replay['selected_correction_weight']:.0%} correction. The untouched {TEST_SEASON} "
            f"continuous path changed by {gate['frozen_test_total_delta']:+d} net points "
            f"({gate['frozen_test_mean_delta']:+.3f}/GW), with a four-event moving-block "
            f"interval of {gate['frozen_test_moving_block_interval']['p025']:+.3f} to "
            f"{gate['frozen_test_moving_block_interval']['p975']:+.3f}/GW. Production is unchanged."
        ),
        "",
        "## Lagged form cohorts",
        "",
        "| Quintile | Prior 3 | Prior 10 | Next | Next 3 | Next 5 | Rows |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in audit["aggregate_streak_quintiles"]:
        lines.append(
            f"| {row['streak_quintile']} | {row['recent_three_points']:.2f} | "
            f"{row['longer_ten_points']:.2f} | {row['next_event_points']:.2f} | "
            f"{row['forward_three_points']:.2f} | {row['forward_five_points']:.2f} | "
            f"{row['rows']} |"
        )
    lines.extend(
        [
            "",
            "## Underlying-process confirmation (xG era, MID/FWD)",
            "",
            "| Streak | Process | Prior 3 | Prior 10 | Next | Next 5 | xGI/90 | Rows |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in audit["process_confirmation"]:
        lines.append(
            f"| {row['streak']} | {row['process']} | {row['recent_three_points']:.2f} | "
            f"{row['longer_ten_points']:.2f} | {row['next_event_points']:.2f} | "
            f"{row['forward_five_points']:.2f} | {row['xgi_per_90']:.3f} | "
            f"{row['rows']} |"
        )
    lines.extend(
        [
            "",
            "## Sequential policy paths",
            "",
            "| Season | Policy | Gross | Cost | Net | Transfers | Rolls | Short exits |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for season in POLICY_SEASONS:
        for policy in ("incumbent_xp", "selected_reversion", "naive_form"):
            key = f"{season}:{policy}"
            path = replay["paths"][key]
            diagnostic = replay["path_diagnostics"][key]
            lines.append(
                f"| {season} | {policy} | {path['gross_points']} | {path['points_cost']} | "
                f"{path['net_points']} | {path['transfers']} | {path['rolls']} | "
                f"{diagnostic['short_horizon_exits_within_two_events']} |"
            )
    lines.extend(
        [
            "",
            "## Promotion contract",
            "",
            "- Every form feature is lagged before the evaluated deadline; current-event outcomes are labels only.",
            "- Correction type and strength are selected on 2024/25 continuous net points only. The 2025/26 path is untouched until the final gate.",
            "- The replay carries the legal squad, bank, purchase/selling prices, free transfers, hits, XI, bench and captain through all 38 events.",
            "- Naive recent-points chasing is retained as a behavioural comparator, not a candidate.",
            "- Even a passing historical challenger remains shadow-only until prospective 2026/27 receipts confirm it; this command cannot change production forecasts or decisions.",
            "",
        ]
    )
    return "\n".join(lines)


def run_form_reversion_challenger(
    *,
    features_path: Path = TRAINING_FEATURES,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not features_path.is_file():
        raise FileNotFoundError(f"Training features missing: {features_path}")
    input_identity = {
        "training_features_sha256": sha256_file(features_path),
        "incumbent_oof_sha256": (
            sha256_file(BACKTEST_FORECAST) if BACKTEST_FORECAST.is_file() else None
        ),
        "implementation_sha256": sha256_file(Path(__file__)),
        "validation_season": VALIDATION_SEASON,
        "test_season": TEST_SEASON,
        "correction_weights": list(CORRECTION_WEIGHTS),
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }
    if (
        created_at is None
        and features_path.resolve() == TRAINING_FEATURES.resolve()
        and results_path.is_file()
        and report_path.is_file()
    ):
        try:
            cached = json.loads(results_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, dict) and cached.get("input_identity") == input_identity:
            return {**cached, "reused": True}
    if features_path.resolve() != TRAINING_FEATURES.resolve():
        historical = _historical_audit(features_path)
        result = {
            "version": 1,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "verdict": "AUDIT_ONLY",
            "status": "shadow",
            "production_changed": False,
            "input_identity": input_identity,
            "historical_audit": historical,
            "artifacts": {
                "training_features": str(features_path),
                "training_features_sha256": sha256_file(features_path),
            },
        }
    else:
        historical = _historical_audit(features_path)
        grouped = _enrich_replay_rows()
        replay = _run_replay(grouped)
        passed = historical["classification"] == "strong_mean_reversion_observed" and replay[
            "gate"
        ]["passed"]
        positive_but_uncertain = (
            replay["selected_correction_weight"] > 0.0
            and replay["gate"]["validation_total_delta"] > 0
            and replay["gate"]["frozen_test_total_delta"] > 0
        )
        result = {
            "version": 1,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "verdict": (
                "PASS_SHADOW"
                if passed
                else "HOLD_SHADOW"
                if positive_but_uncertain
                else "REJECT_POLICY"
            ),
            "status": "shadow",
            "production_changed": False,
            "input_identity": input_identity,
            "historical_audit": historical,
            "sequential_replay": replay,
            "artifacts": {
                "training_features": str(features_path),
                "training_features_sha256": sha256_file(features_path),
                "incumbent_oof": str(BACKTEST_FORECAST),
                "incumbent_oof_sha256": sha256_file(BACKTEST_FORECAST),
            },
        }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = results_path.with_suffix(results_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(results_path)
    if "sequential_replay" in result:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_render(result), encoding="utf-8")
    return result
