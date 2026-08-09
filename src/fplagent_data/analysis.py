from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .database import DATABASE
from .paths import DATA, ROOT, ensure_layout

ANALYSIS_DIR = DATA / "analysis"
FEATURES = ANALYSIS_DIR / "player_gameweek_features.parquet"
PREDICTIONS = ANALYSIS_DIR / "forecast_predictions.parquet"
METRICS = ANALYSIS_DIR / "historical_edge_metrics.json"
REPORT = ROOT / "reports" / "historical-edge.md"

TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
POSITIONS = ("GK", "DEF", "MID", "FWD")
BASE_FEATURES = (
    "fixture_count",
    "home_fraction",
    "history_gws",
    "last_points",
    "form3_points",
    "form5_points",
    "form10_points",
    "season_points",
    "last_minutes",
    "form3_minutes",
    "form5_minutes",
    "appearance_rate5",
    "lag_value",
    "log_lag_selected",
)
UNDERLYING_FEATURES = BASE_FEATURES + (
    "form5_threat",
    "form5_creativity",
    "form5_influence",
    "form5_bps",
    "form5_xgi",
    "form5_xgc",
    "form5_clean_sheets",
)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def build_feature_table(connection: duckdb.DuckDBPyConnection) -> int:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    output = _sql_path(FEATURES)
    connection.execute(
        f"""
        COPY (
            WITH player_events AS (
                SELECT
                    g.season,
                    g.element,
                    g.GW AS event,
                    any_value(g.name) AS player_name,
                    CASE
                        WHEN any_value(g.position) IN ('GK', 'GKP') THEN 'GK'
                        WHEN any_value(g.position) IN ('DEF', 'MID', 'FWD', 'AM')
                            THEN any_value(g.position)
                        WHEN any_value(p.element_type) = 1 THEN 'GK'
                        WHEN any_value(p.element_type) = 2 THEN 'DEF'
                        WHEN any_value(p.element_type) = 3 THEN 'MID'
                        WHEN any_value(p.element_type) = 4 THEN 'FWD'
                    END AS position,
                    any_value(g.team) AS team,
                    count(DISTINCT g.fixture) AS fixture_count,
                    avg(CASE WHEN g.was_home THEN 1.0 ELSE 0.0 END) AS home_fraction,
                    sum(g.total_points)::DOUBLE AS points,
                    sum(g.minutes)::DOUBLE AS minutes,
                    sum(coalesce(g.threat, 0))::DOUBLE AS threat,
                    sum(coalesce(g.creativity, 0))::DOUBLE AS creativity,
                    sum(coalesce(g.influence, 0))::DOUBLE AS influence,
                    sum(coalesce(g.bps, 0))::DOUBLE AS bps,
                    sum(coalesce(g.expected_goal_involvements, 0))::DOUBLE AS xgi,
                    sum(coalesce(g.expected_goals_conceded, 0))::DOUBLE AS xgc,
                    sum(coalesce(g.clean_sheets, 0))::DOUBLE AS clean_sheets,
                    max(g.value)::DOUBLE AS value,
                    max(g.selected)::DOUBLE AS selected,
                    max(g."xP")::DOUBLE AS current_xp_unsafe
                FROM vaastav_player_gameweeks g
                LEFT JOIN vaastav_players p
                    ON g.season = p.season AND g.element = p.id
                GROUP BY g.season, g.element, g.GW
            ), featured AS (
                SELECT
                    *,
                    row_number() OVER player_window - 1 AS history_gws,
                    lag(points) OVER player_window AS last_points,
                    avg(points) OVER player_3 AS form3_points,
                    avg(points) OVER player_5 AS form5_points,
                    avg(points) OVER player_10 AS form10_points,
                    avg(points) OVER player_history AS season_points,
                    lag(minutes) OVER player_window AS last_minutes,
                    avg(minutes) OVER player_3 AS form3_minutes,
                    avg(minutes) OVER player_5 AS form5_minutes,
                    avg(CASE WHEN minutes > 0 THEN 1.0 ELSE 0.0 END) OVER player_5
                        AS appearance_rate5,
                    avg(threat) OVER player_5 AS form5_threat,
                    avg(creativity) OVER player_5 AS form5_creativity,
                    avg(influence) OVER player_5 AS form5_influence,
                    avg(bps) OVER player_5 AS form5_bps,
                    avg(xgi) OVER player_5 AS form5_xgi,
                    avg(xgc) OVER player_5 AS form5_xgc,
                    avg(clean_sheets) OVER player_5 AS form5_clean_sheets,
                    lag(value) OVER player_window AS lag_value,
                    lag(selected) OVER player_window AS lag_selected,
                    lag(current_xp_unsafe) OVER player_window AS lag_xp
                FROM player_events
                WINDOW
                    player_window AS (PARTITION BY season, element ORDER BY event),
                    player_3 AS (
                        PARTITION BY season, element ORDER BY event
                        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                    ),
                    player_5 AS (
                        PARTITION BY season, element ORDER BY event
                        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                    ),
                    player_10 AS (
                        PARTITION BY season, element ORDER BY event
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    ),
                    player_history AS (
                        PARTITION BY season, element ORDER BY event
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    )
            )
            SELECT
                row_number() OVER (ORDER BY season, event, element) AS row_id,
                *,
                ln(1 + coalesce(lag_selected, 0)) AS log_lag_selected
            FROM featured
        ) TO '{output}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    return pq.ParquetFile(FEATURES).metadata.num_rows


def _floats(table: pa.Table, name: str) -> np.ndarray:
    return np.array(
        [np.nan if value is None else float(value) for value in table[name].to_pylist()],
        dtype=np.float64,
    )


def _strings(table: pa.Table, name: str) -> np.ndarray:
    return np.array(table[name].to_pylist(), dtype=object)


def _ridge_fit_predict(
    train: np.ndarray,
    target: np.ndarray,
    test: np.ndarray,
    alpha: float = 25.0,
) -> np.ndarray:
    medians = np.nanmedian(train, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    train = np.where(np.isfinite(train), train, medians)
    test = np.where(np.isfinite(test), test, medians)
    means = train.mean(axis=0)
    scales = train.std(axis=0)
    scales = np.where(scales > 1e-9, scales, 1.0)
    train = (train - means) / scales
    test = (test - means) / scales
    train = np.column_stack((np.ones(len(train)), train))
    test = np.column_stack((np.ones(len(test)), test))
    penalty = np.eye(train.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(train.T @ train + penalty, train.T @ target)
    return np.clip(test @ coefficients, 0.0, 30.0)


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranked = np.empty(len(values), dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < len(values):
        stop = start + 1
        while stop < len(values) and sorted_values[stop] == sorted_values[start]:
            stop += 1
        ranked[order[start:stop]] = (start + stop - 1) / 2.0
        start = stop
    return ranked


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    mask = np.isfinite(left) & np.isfinite(right)
    if mask.sum() < 3 or np.std(left[mask]) < 1e-12 or np.std(right[mask]) < 1e-12:
        return None
    return float(np.corrcoef(left[mask], right[mask])[0, 1])


def _evaluate(
    season: np.ndarray,
    event: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    test_season: str,
) -> dict[str, Any]:
    mask = (season == test_season) & np.isfinite(actual) & np.isfinite(predicted)
    actual = actual[mask]
    predicted = predicted[mask]
    events = event[mask]
    errors = predicted - actual
    spearman = []
    top15_points = []
    top15_returns = []
    captain_points = []
    for gameweek in sorted(set(events.tolist())):
        gw_mask = events == gameweek
        gw_actual = actual[gw_mask]
        gw_predicted = predicted[gw_mask]
        if len(gw_actual) < 15:
            continue
        spearman_value = _correlation(_rank(gw_predicted), _rank(gw_actual))
        if spearman_value is not None:
            spearman.append(spearman_value)
        top = np.argsort(gw_predicted)[-15:]
        top15_points.append(float(np.mean(gw_actual[top])))
        top15_returns.append(float(np.mean(gw_actual[top] >= 6)))
        captain_points.append(float(gw_actual[np.argmax(gw_predicted)]))
    return {
        "rows": len(actual),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "pearson": _correlation(predicted, actual),
        "mean_gameweek_spearman": float(np.mean(spearman)),
        "top15_mean_points": float(np.mean(top15_points)),
        "top15_six_plus_rate": float(np.mean(top15_returns)),
        "captain_mean_points": float(np.mean(captain_points)),
    }


def forecast_backtest(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[dict], list[dict], int]:
    escaped = _sql_path(FEATURES)
    columns = sorted(set(BASE_FEATURES + UNDERLYING_FEATURES))
    table = connection.execute(
        "SELECT row_id, season, element, event, player_name, position, points, "
        "current_xp_unsafe, form5_points, season_points, log_lag_selected, "
        "history_gws, form3_minutes, "
        + ", ".join(
            name
            for name in columns
            if name
            not in {
                "form5_points",
                "season_points",
                "log_lag_selected",
                "history_gws",
                "form3_minutes",
            }
        )
        + f" FROM read_parquet('{escaped}') ORDER BY row_id"
    ).fetch_arrow_table()
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _floats(table, "event")
    actual = _floats(table, "points")
    history = _floats(table, "history_gws")
    recent_minutes = _floats(table, "form3_minutes")
    eligible = (history >= 3) & (recent_minutes >= 30)

    feature_arrays = {name: _floats(table, name) for name in columns}
    predictions: dict[str, np.ndarray] = {
        "form5": _floats(table, "form5_points"),
        "season_average": _floats(table, "season_points"),
        "lagged_ownership": _floats(table, "log_lag_selected"),
        "current_xp_unsafe": _floats(table, "current_xp_unsafe"),
        "ridge_form": np.full(len(table), np.nan),
        "ridge_underlying": np.full(len(table), np.nan),
    }

    season_order = sorted(set(seasons.tolist()))
    for test_season in TEST_SEASONS:
        prior = {value for value in season_order if value < test_season}
        for position in POSITIONS:
            train_mask = eligible & np.isin(seasons, list(prior)) & (positions == position)
            test_mask = eligible & (seasons == test_season) & (positions == position)
            if train_mask.sum() < 100 or test_mask.sum() == 0:
                continue
            for name, features in (
                ("ridge_form", BASE_FEATURES),
                ("ridge_underlying", UNDERLYING_FEATURES),
            ):
                matrix = np.column_stack([feature_arrays[item] for item in features])
                predictions[name][test_mask] = _ridge_fit_predict(
                    matrix[train_mask], actual[train_mask], matrix[test_mask]
                )

    metrics = []
    for test_season in TEST_SEASONS:
        for model, values in predictions.items():
            evaluation_values = values.copy()
            evaluation_values[~eligible] = np.nan
            item = _evaluate(seasons, events, actual, evaluation_values, test_season)
            if model == "lagged_ownership":
                item["mae"] = None
                item["rmse"] = None
            item.update({"season": test_season, "model": model})
            metrics.append(item)

    signal_arrays = {
        "five_gw_points": feature_arrays["form5_points"],
        "season_points": feature_arrays["season_points"],
        "recent_minutes": feature_arrays["form3_minutes"],
        "appearance_rate": feature_arrays["appearance_rate5"],
        "lagged_price": feature_arrays["lag_value"],
        "lagged_ownership": feature_arrays["log_lag_selected"],
        "five_gw_threat": feature_arrays["form5_threat"],
        "five_gw_xgi": feature_arrays["form5_xgi"],
        "five_gw_bps": feature_arrays["form5_bps"],
    }
    by_signal: dict[str, list[dict]] = {name: [] for name in signal_arrays}
    for test_season in TEST_SEASONS:
        for name, values in signal_arrays.items():
            evaluation_values = values.copy()
            evaluation_values[~eligible] = np.nan
            by_signal[name].append(
                _evaluate(seasons, events, actual, evaluation_values, test_season)
            )
    signal_metrics = [
        {
            "signal": name,
            "mean_gameweek_spearman": float(
                np.mean([item["mean_gameweek_spearman"] for item in evaluations])
            ),
            "top15_mean_points": float(
                np.mean([item["top15_mean_points"] for item in evaluations])
            ),
            "captain_mean_points": float(
                np.mean([item["captain_mean_points"] for item in evaluations])
            ),
        }
        for name, evaluations in by_signal.items()
    ]
    signal_metrics.sort(key=lambda item: item["mean_gameweek_spearman"], reverse=True)

    output_rows = []
    wanted = np.isin(seasons, list(TEST_SEASONS)) & eligible
    row_ids = table["row_id"].to_pylist()
    elements = table["element"].to_pylist()
    players = table["player_name"].to_pylist()
    for index in np.flatnonzero(wanted):
        output_rows.append(
            {
                "row_id": row_ids[index],
                "season": seasons[index],
                "event": int(events[index]),
                "element": elements[index],
                "player_name": players[index],
                "position": positions[index],
                "actual_points": actual[index],
                **{
                    f"prediction_{name}": (
                        float(values[index]) if np.isfinite(values[index]) else None
                    )
                    for name, values in predictions.items()
                },
            }
        )
    prediction_table = pa.Table.from_pylist(output_rows)
    pq.write_table(prediction_table, PREDICTIONS, compression="zstd")
    return metrics, signal_metrics, prediction_table.num_rows


def _one(connection: duckdb.DuckDBPyConnection, query: str) -> tuple:
    return connection.execute(query).fetchone()


def outcome_metrics(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    population = _one(
        connection,
        """
        SELECT count(*), avg(points), median(points), stddev_pop(points),
               avg(projected_points), avg(overperformance_points),
               corr(projected_points, points)
        FROM solio_manager_outcomes
        """,
    )
    active = _one(
        connection,
        """
        SELECT count(*), avg(points), median(points), avg(projected_points),
               avg(overperformance_points)
        FROM solio_manager_outcomes WHERE active
        """,
    )
    elite = _one(
        connection,
        """
        SELECT count(*), avg(s.points), avg(s.projected_points),
               avg(s.overperformance_points), median(s.projected_rank),
               count(*) FILTER (WHERE s.projected_rank <= 100),
               count(*) FILTER (WHERE s.projected_rank <= 1000),
               count(*) FILTER (WHERE s.projected_rank <= 10000),
               count(*) FILTER (WHERE s.overperformance_points < 0)
        FROM solio_manager_outcomes s
        JOIN fpl_genius_managers g USING (manager_id)
        """,
    )
    projected_elite = _one(
        connection,
        """
        SELECT median(s.overall_rank),
               quantile_cont(s.overall_rank, 0.25),
               quantile_cont(s.overall_rank, 0.75),
               count(*) FILTER (WHERE s.overall_rank <= 100),
               count(*) FILTER (WHERE s.overall_rank <= 1000),
               count(*) FILTER (WHERE s.overall_rank <= 10000),
               avg(s.overperformance_points)
        FROM solio_manager_outcomes s
        JOIN solio_leaderboards l USING (manager_id)
        WHERE l.scope = 'all' AND l.board = 'proj'
        """,
    )
    actual_gap = elite[1] - active[1]
    projected_gap = elite[2] - active[3]
    variance_gap = elite[3] - active[4]
    return {
        "population": {
            "managers": population[0],
            "mean_points": population[1],
            "median_points": population[2],
            "points_sd": population[3],
            "mean_projected_points": population[4],
            "mean_overperformance": population[5],
            "projected_actual_correlation": population[6],
        },
        "active": {
            "managers": active[0],
            "mean_points": active[1],
            "median_points": active[2],
            "mean_projected_points": active[3],
            "mean_overperformance": active[4],
        },
        "elite_actual_top100": {
            "managers": elite[0],
            "mean_points": elite[1],
            "mean_projected_points": elite[2],
            "mean_overperformance": elite[3],
            "median_projected_rank": elite[4],
            "projected_top100": elite[5],
            "projected_top1000": elite[6],
            "projected_top10000": elite[7],
            "negative_overperformance": elite[8],
            "gap_to_active_points": actual_gap,
            "gap_from_projected_quality": projected_gap,
            "gap_from_overperformance": variance_gap,
            "projected_share_of_gap": projected_gap / actual_gap,
        },
        "elite_projected_top100": {
            "median_actual_rank": projected_elite[0],
            "actual_rank_q25": projected_elite[1],
            "actual_rank_q75": projected_elite[2],
            "actual_top100": projected_elite[3],
            "actual_top1000": projected_elite[4],
            "actual_top10000": projected_elite[5],
            "mean_overperformance": projected_elite[6],
        },
    }


def decision_metrics(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    captain = _one(
        connection,
        """
        SELECT count(*),
               count(*) FILTER (WHERE captain = comparison_captain),
               count(*) FILTER (WHERE captain != comparison_captain),
               avg(realised_edge) FILTER (WHERE captain != comparison_captain),
               median(realised_edge) FILTER (WHERE captain != comparison_captain),
               sum(realised_edge) FILTER (WHERE captain != comparison_captain),
               count(*) FILTER (
                   WHERE captain != comparison_captain AND realised_edge > 0
               ),
               count(*) FILTER (
                   WHERE captain != comparison_captain AND realised_edge < 0
               )
        FROM fpl_genius_captaincy
        """,
    )
    transfer = _one(
        connection,
        """
        SELECT count(*), avg(forward_alpha_1gw), avg(forward_alpha_3gw),
               avg(forward_alpha_5gw),
               avg(forward_alpha_3gw) FILTER (WHERE transfer_cost > 0),
               avg(forward_alpha_3gw) FILTER (WHERE transfer_cost = 0),
               count(*) FILTER (WHERE forward_alpha_3gw > 0),
               count(*) FILTER (WHERE forward_alpha_3gw = 0),
               count(*) FILTER (WHERE forward_alpha_3gw < 0)
        FROM fpl_genius_transfers
        """,
    )
    manager = _one(
        connection,
        """
        WITH transfers AS (
            SELECT manager_id, count(*) AS moves, sum(transfer_cost) AS hit_cost
            FROM fpl_genius_transfers GROUP BY manager_id
        ), rolls AS (
            SELECT manager_id, count(*) AS rolled
            FROM fpl_genius_receipts
            WHERE decision_type = 'squad_value' AND action_label = 'Rolled the transfer'
            GROUP BY manager_id
        )
        SELECT avg(moves), median(moves), min(moves), max(moves),
               avg(hit_cost), median(hit_cost), max(hit_cost),
               avg(rolled), median(rolled), min(rolled), max(rolled)
        FROM transfers JOIN rolls USING (manager_id)
        """,
    )
    hit = _one(
        connection,
        """
        SELECT count(*),
               sum(CASE WHEN action_label LIKE 'Spent 4 %' THEN 4 ELSE 8 END)
        FROM fpl_genius_receipts WHERE decision_type = 'hit'
        """,
    )
    chips = connection.execute(
        """
        SELECT action_label, count(*)
        FROM fpl_genius_receipts WHERE decision_type = 'chip'
        GROUP BY action_label ORDER BY action_label
        """
    ).fetchall()
    return {
        "captaincy": {
            "decisions": captain[0],
            "template": captain[1],
            "deviations": captain[2],
            "deviation_mean_edge": captain[3],
            "deviation_median_edge": captain[4],
            "deviation_total_edge_non_additive": captain[5],
            "deviation_wins": captain[6],
            "deviation_losses": captain[7],
        },
        "transfers": {
            "moves": transfer[0],
            "mean_alpha_1gw": transfer[1],
            "mean_alpha_3gw": transfer[2],
            "mean_alpha_5gw": transfer[3],
            "paid_mean_alpha_3gw": transfer[4],
            "free_mean_alpha_3gw": transfer[5],
            "positive_3gw": transfer[6],
            "zero_3gw": transfer[7],
            "negative_3gw": transfer[8],
            "mean_moves_per_manager": manager[0],
            "median_moves_per_manager": manager[1],
            "min_moves_per_manager": manager[2],
            "max_moves_per_manager": manager[3],
            "mean_hit_cost_per_manager": manager[4],
            "median_hit_cost_per_manager": manager[5],
            "max_hit_cost_per_manager": manager[6],
            "mean_rolls_per_manager": manager[7],
            "median_rolls_per_manager": manager[8],
            "min_rolls_per_manager": manager[9],
            "max_rolls_per_manager": manager[10],
            "hit_events": hit[0],
            "hit_points": hit[1],
        },
        "chips": dict(chips),
    }


def supporting_metrics(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    paul = _one(
        connection,
        """
        WITH managers AS (
            SELECT overall_rank,
                   cast(json_extract(record_json, '$.Cap_Fail') AS DOUBLE) cap_fail,
                   cast(json_extract(record_json, '$.Total_Cap_Pts') AS DOUBLE) captain_points,
                   cast(json_extract(record_json, '$.Total_Transfers') AS DOUBLE) transfers,
                   cast(json_extract(record_json, '$.Total_Hits') AS DOUBLE) hits,
                   cast(json_extract(record_json, '$."Bench Points"') AS DOUBLE) bench_points
            FROM supporting_paul_top50
        )
        SELECT avg(cap_fail), avg(captain_points), avg(transfers), avg(hits),
               avg(bench_points), corr(overall_rank, captain_points),
               corr(overall_rank, transfers), corr(overall_rank, hits),
               corr(overall_rank, bench_points),
               avg(captain_points) FILTER (WHERE overall_rank <= 10),
               avg(captain_points) FILTER (WHERE overall_rank > 40),
               avg(hits) FILTER (WHERE overall_rank <= 10),
               avg(hits) FILTER (WHERE overall_rank > 40)
        FROM managers
        """,
    )
    titan = _one(
        connection,
        """
        WITH managers AS (
            SELECT manager,
                   max("or") FILTER (WHERE gw = 38) final_rank,
                   sum(pb) bench_points,
                   sum(tm) transfers,
                   sum(tc) transfer_cost,
                   avg("£") squad_value,
                   any_value(experience) experience
            FROM supporting_titan_managers GROUP BY manager
        )
        SELECT count(*), min(final_rank), median(final_rank), max(final_rank),
               corr(final_rank, bench_points), corr(final_rank, transfers),
               corr(final_rank, transfer_cost), corr(final_rank, squad_value),
               corr(final_rank, experience)
        FROM managers
        """,
    )
    vaastav = _one(
        connection,
        "SELECT avg(team_value), min(team_value), max(team_value) "
        "FROM vaastav_top_manager_gameweeks",
    )
    pick_rows = connection.execute(
        """
        WITH returns AS (
            SELECT season, element, GW, sum(total_points) AS points
            FROM vaastav_player_gameweeks GROUP BY ALL
        ), positions AS (
            SELECT season, id,
                   CASE element_type WHEN 1 THEN 'GK' WHEN 2 THEN 'DEF'
                        WHEN 3 THEN 'MID' WHEN 4 THEN 'FWD' END AS position
            FROM vaastav_players
        )
        SELECT p.team_id, p.gw, p.multiplier, r.points, positions.position, g.chip
        FROM vaastav_top_manager_picks p
        JOIN returns r
          ON p.season = r.season AND p.player_id = r.element AND p.gw = r.GW
        JOIN positions
          ON p.season = positions.season AND p.player_id = positions.id
        JOIN vaastav_top_manager_gameweeks g
          ON p.team_id = g.team_id AND p.gw = g.gw
        ORDER BY p.team_id, p.gw, p.position
        """
    ).fetchall()
    pick_groups: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for row in pick_rows:
        pick_groups[(row[0], row[1])].append(row)
    captain_regret = []
    bench_regret = []
    for picks in pick_groups.values():
        captains = [row for row in picks if row[2] > 1]
        if captains:
            captain = max(captains, key=lambda row: row[2])
            captain_regret.append(
                (captain[2] - 1) * (max(row[3] for row in picks) - captain[3])
            )
        if picks[0][5] == "bboost":
            continue
        by_position: dict[str, list[float]] = defaultdict(list)
        for row in picks:
            by_position[row[4]].append(row[3])
        for values in by_position.values():
            values.sort(reverse=True)
        best = -math.inf
        for defenders in range(3, 6):
            for midfielders in range(2, 6):
                forwards = 10 - defenders - midfielders
                if not 1 <= forwards <= 3:
                    continue
                best = max(
                    best,
                    by_position["GK"][0]
                    + sum(by_position["DEF"][:defenders])
                    + sum(by_position["MID"][:midfielders])
                    + sum(by_position["FWD"][:forwards]),
                )
        actual = sum(row[3] for row in picks if row[2] > 0)
        bench_regret.append(best - actual)
    return {
        "paul_2019_20_top50": {
            "mean_captain_failures": paul[0],
            "mean_captain_points": paul[1],
            "mean_transfers": paul[2],
            "mean_hit_points": paul[3],
            "mean_bench_points": paul[4],
            "rank_corr_captain_points": paul[5],
            "rank_corr_transfers": paul[6],
            "rank_corr_hits": paul[7],
            "rank_corr_bench_points": paul[8],
            "top10_mean_captain_points": paul[9],
            "bottom10_mean_captain_points": paul[10],
            "top10_mean_hits": paul[11],
            "bottom10_mean_hits": paul[12],
        },
        "titan_2022_23": {
            "managers": titan[0],
            "best_rank": titan[1],
            "median_rank": titan[2],
            "worst_rank": titan[3],
            "rank_corr_bench_points": titan[4],
            "rank_corr_transfers": titan[5],
            "rank_corr_transfer_cost": titan[6],
            "rank_corr_squad_value": titan[7],
            "rank_corr_experience": titan[8],
        },
        "vaastav_2019_20_top10": {
            "mean_weekly_team_value": vaastav[0],
            "min_weekly_team_value": vaastav[1],
            "max_weekly_team_value": vaastav[2],
            "captain_observations": len(captain_regret),
            "mean_hindsight_captain_regret": float(np.mean(captain_regret)),
            "median_hindsight_captain_regret": float(np.median(captain_regret)),
            "captain_was_squad_top_scorer_rate": float(
                np.mean(np.array(captain_regret) == 0)
            ),
            "lineup_observations_excluding_bench_boost": len(bench_regret),
            "mean_hindsight_lineup_regret": float(np.mean(bench_regret)),
            "median_hindsight_lineup_regret": float(np.median(bench_regret)),
            "hindsight_best_lineup_rate": float(np.mean(np.array(bench_regret) == 0)),
        },
    }


def _fmt(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{decimals}f}"


def _model_table(backtests: list[dict]) -> str:
    lines = [
        "| Season | Signal/model | MAE | GW rank corr. | Top-15 pts/player | Captain pts |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "ridge_form": "Ridge: lagged form + availability",
        "ridge_underlying": "Ridge: + lagged underlying stats",
        "form5": "Five-GW points average",
        "season_average": "Season-to-date points average",
        "lagged_ownership": "Lagged ownership (ranking only)",
        "current_xp_unsafe": "Current-row FPL xP (unsafe diagnostic)",
    }
    for item in backtests:
        lines.append(
            f"| {item['season']} | {labels[item['model']]} | "
            f"{_fmt(item['mae'], 3)} | {_fmt(item['mean_gameweek_spearman'], 3)} | "
            f"{_fmt(item['top15_mean_points'], 2)} | "
            f"{_fmt(item['captain_mean_points'], 2)} |"
        )
    return "\n".join(lines)


def _signal_table(signals: list[dict]) -> str:
    labels = {
        "five_gw_points": "Five-GW points",
        "season_points": "Season-to-date points",
        "recent_minutes": "Three-GW minutes",
        "appearance_rate": "Five-GW appearance rate",
        "lagged_price": "Lagged price",
        "lagged_ownership": "Lagged ownership",
        "five_gw_threat": "Five-GW threat",
        "five_gw_xgi": "Five-GW xGI",
        "five_gw_bps": "Five-GW BPS",
    }
    lines = [
        "| Lagged signal | Mean GW rank correlation | Top-15 pts/player |",
        "| --- | ---: | ---: |",
    ]
    for item in signals:
        lines.append(
            f"| {labels[item['signal']]} | "
            f"{_fmt(item['mean_gameweek_spearman'], 3)} | "
            f"{_fmt(item['top15_mean_points'], 2)} |"
        )
    return "\n".join(lines)


def write_report(metrics: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    outcomes = metrics["outcomes"]
    elite = outcomes["elite_actual_top100"]
    projected = outcomes["elite_projected_top100"]
    decisions = metrics["decisions"]
    captain = decisions["captaincy"]
    transfers = decisions["transfers"]
    paul = metrics["supporting"]["paul_2019_20_top50"]
    titan = metrics["supporting"]["titan_2022_23"]
    vaastav = metrics["supporting"]["vaastav_2019_20_top10"]
    content = f"""# FPLAgent historical edge study

Generated {metrics['generated_at']}. This is an evidence audit, not a claim that historical
correlations guarantee a future finish. All figures are reproducible with `uv run fpl-data analyse`.

## Executive answer

The data rejects both comforting extremes. Winning is neither pure luck nor a collection of
clever differentials. The repeatable foundation is consistently selecting high expected-point
routes, preserving optionality, and evaluating transfers over multiple gameweeks. Extreme final
ranks additionally require favourable realised variance.

The exact 2025/26 top 100 averaged **{_fmt(elite['mean_points'])} points**, against
**{_fmt(outcomes['active']['mean_points'])}** for the 3.53m active-manager population. Of that
{_fmt(elite['gap_to_active_points'])}-point gap, {_fmt(elite['gap_from_projected_quality'])}
points ({elite['projected_share_of_gap']:.0%}) came from Solio's projected quality of the weekly
picks and {_fmt(elite['gap_from_overperformance'])} from finishing above projection. Only
{elite['projected_top100']} of the actual top 100 were themselves projected top-100 managers;
their median projected rank was {_fmt(elite['median_projected_rank'], 0)}.

The reverse view is healthier for product design: the 100 best projected managers had a median
actual rank of **{_fmt(projected['median_actual_rank'], 0)}**; {projected['actual_top10000']}%
finished inside the top 10k and {projected['actual_top1000']}% inside the top 1k. A process can
produce a formidable finish distribution without being able to promise the single realised winner.

## What strong managers actually did

### Captaincy: deviation was selective, not the objective

Across 3,800 top-100 captain decisions, the model comparator and manager agreed
{captain['template']:,} times ({captain['template'] / captain['decisions']:.1%}). Managers deviated
{captain['deviations']:,} times. Those deviations won {captain['deviation_wins']:,} and lost
{captain['deviation_losses']:,}, with a realised mean edge of
{_fmt(captain['deviation_mean_edge'])} points.

That is descriptive survivorship evidence: this cohort was selected because it finished top 100,
so its successful captain deviations cannot be treated as a prospective causal return. The usable
lesson is narrower: do not reward rarity. Recommend a non-template captain only when the forecast
distribution independently gives that player the better risk-adjusted score.

The independent 2019/20 top-ten picks reinforce how noisy hindsight is. Their captain happened to
be the highest-scoring player in their own 15 only
{vaastav['captain_was_squad_top_scorer_rate']:.1%} of 380 manager-weeks; the mean hindsight gap was
{_fmt(vaastav['mean_hindsight_captain_regret'])} points. Excluding Bench Boost weeks, they fielded
the hindsight-best legal XI only {vaastav['hindsight_best_lineup_rate']:.1%} of the time, with
{_fmt(vaastav['mean_hindsight_lineup_regret'])} points of mean lineup regret. That oracle was not
available at the deadline. We should judge captain and bench calls against the **pre-deadline
forecast distribution**, never whether the benched player later hauled.

### Transfers: horizon and restraint both matter

The cohort rolled a transfer a mean **{_fmt(transfers['mean_rolls_per_manager'])} weeks** each
(range {_fmt(transfers['min_rolls_per_manager'], 0)}–{_fmt(transfers['max_rolls_per_manager'], 0)}).
Their recorded moves produced mean player-in minus player-out returns of
{_fmt(transfers['mean_alpha_1gw'])}, {_fmt(transfers['mean_alpha_3gw'])}, and
{_fmt(transfers['mean_alpha_5gw'])} points over one, three, and five gameweeks. The widening edge
supports planning transfers across horizons rather than chasing only the next fixture.

There were only {transfers['hit_events']} paid-hit events ({transfers['hit_points']} points of
cost) among 100 managers. Paid moves show {_fmt(transfers['paid_mean_alpha_3gw'])} mean three-GW
gross alpha versus {_fmt(transfers['free_mean_alpha_3gw'])} for free moves, but this is again
selected-on-success evidence and the gross comparison does not license indiscriminate hits. A hit
must clear its cost under uncertainty and improve the multi-week squad state.

### Counts are not a strategy

The independent 2019/20 top-50 archive averaged {_fmt(paul['mean_transfers'])} transfers and
{_fmt(paul['mean_hit_points'])} hit points. Within that already elite sample, transfer count had
almost no relationship with rank (r={paul['rank_corr_transfers']:.3f}); captain points were more
favourable but still weak (rank r={paul['rank_corr_captain_points']:.3f}). The top ten actually
took more hits on average than ranks 41–50 ({_fmt(paul['top10_mean_hits'])} vs
{_fmt(paul['bottom10_mean_hits'])}). This does **not** mean hits help—it means decision quality
dominates a blanket rule about activity.

The 27-manager Titan cohort tells a similar cautionary story. Final rank correlated
{titan['rank_corr_squad_value']:.3f} with average squad value and
{titan['rank_corr_transfer_cost']:.3f} with transfer cost (lower rank is better), while experience
was essentially unrelated ({titan['rank_corr_experience']:.3f}). These are small observational
samples; squad value and bench points also proxy a generally successful squad and are not causal
targets by themselves.

### Budget: cash is a constraint, not a score

The 2019/20 top ten averaged a weekly team value of £{_fmt(vaastav['mean_weekly_team_value'])}m,
and higher average squad value was associated with better rank in the small Titan cohort. That
supports auditing the old app's habit of leaving money unused, but it does not justify a blanket
“spend everything” rule. Bank is valuable when it unlocks a later transfer or avoids a hit. The
engine must calculate **unused-budget opportunity cost**: the expected multi-horizon gain of the
best legal upgrade currently declined. Cash is suspicious only when that gain exceeds the option
value of keeping it.

## Leakage-safe player forecast baseline

Each historical player-fixture record was first aggregated to player/gameweek so double-gameweek
returns remain one decision target. Every predictor is lagged: prior points, minutes, appearance
rate, price, ownership, ICT/BPS and expected-stat form. The model never sees same-gameweek goals,
minutes, transfers, ownership or results. Players needed at least three prior observations and a
30-minute recent average. Separate ridge models were fitted by position using only seasons before
the test season.

{_model_table(metrics['forecast_backtests'])}

This is a **benchmark**, not the production model. Its purpose is to make future XGBoost/RF/ensemble
work beat a fixed, time-ordered baseline. `current_xp_unsafe` is deliberately included only as a
leakage diagnostic because Vaastav documents that the field may have been captured after matches.
It is forbidden as a production feature. The ridge model improves gameweek ranking materially over
raw five-GW form in every test season. Adding rolling expected/ICT statistics does **not** improve
the ranking consistently, so a naive “more stats” model has failed its first audition. The next
candidate needs nonlinear interactions, explicit opponent strength and a proper minutes/appearance
model—not cosmetic feature accumulation. OpenFPL independently supports position-specific public
data ensembles and prospective season isolation, but our implementation must beat these local
baselines on untouched future gameweeks.

Top-15 and captain columns are ranking diagnostics over eligible players, not scores from a legal,
budget-constrained squad. They intentionally separate forecast quality from the optimizer that we
will test next. Eligibility removes the opening three observations, so each season reports up to
35 evaluated gameweeks.

### Which individual signals survived?

{_signal_table(metrics['signal_backtests'])}

Minutes and appearance history are essential for estimating whether points are available at all,
but do not rank upside alone. Price and ownership are useful market priors, not objectives. Recent
points/BPS/threat carry signal, while the raw xGI aggregate has too little stable incremental value
in this linear setup to justify calling it an edge. These variables remain candidates for a
nonlinear, position-specific model with opponent and minutes interactions.

## Evidence classification

| Finding | Status | Product consequence |
| --- | --- | --- |
| Better projected weekly picks strongly improve finish distribution | Strong, population-scale but one season/model | Expected points remains the default objective |
| Extreme top-100 outcomes contain substantial positive variance | Strong descriptive evidence | Communicate ranges; do not overfit winner quirks |
| Transfer edge is larger over 3–5 GWs than one GW | Useful selected-cohort evidence | Optimize several horizons and replan each deadline |
| Strong managers frequently roll | Descriptive but consistent with option value | “No move” must be a first-class action |
| Differential captains worked in the realised top 100 | Hindsight-selected, non-causal | Never add a differential bonus by default |
| More transfers or hits cause better ranks | Unsupported | Score the move, not activity |
| Current-row historical xP is safe | Rejected by source timing | Ban it; allow only timestamped pre-deadline forecasts |
| Bench points should simply be minimized | Unsupported/confounded | Value squad resilience, then optimize lineup separately |

## What the historical corpus cannot solve by itself

This baseline deliberately starts after three player observations, so it is not a GW1 model.
Preseason needs a separate cold-start layer joining players across seasons by stable player code,
carrying prior-league performance, promoted-team strength, expected minutes, injuries/suspensions
and likely roles. New signings without Premier League history need league-strength translation and
wider uncertainty. Deadline news and predicted lineups must be timestamped independently; an LLM
may summarize attributable reports, but it must never invent or numerically override the structured
availability model.

Rule eras also need explicit treatment. The 2025/26 outcomes include defensive contributions and
two copies of several chips, while older seasons do not. Raw historical points remain useful labels
for the rules actually played, but a 2026/27 optimizer must use the normalized current scoring and
chip tables rather than blindly extrapolating old positional value.

## Backtestable policy v0

For every deadline, the engine should generate legal action bundles—roll; free transfers; paid
transfers; captain/vice; bench and formation; chip variants—and simulate them over 1, 3, 5 and 8
gameweeks. The primary score is expected total FPL points, including captain multiplier, autosub
probability, hit cost, banked-transfer option value and chip opportunity cost.

Uncertainty is represented with outcome distributions, not a fixed “differential” bonus. Default
risk targets maximum expected points with a downside constraint. Mini-league context may alter the
utility curve late in the season: leaders reduce avoidable covariance and tail risk; materially
trailing managers can accept higher variance when the expected-point sacrifice is bounded. Overall
points strength remains the prior, as requested—the mini-league opponent is context, not the main
game.

A recommendation is allowed only if it records a pre-deadline receipt containing the data snapshot,
model version, predicted distribution, chosen action, best rejected alternative and why. Those
receipts become the prospective dataset that the public historical record cannot provide.

## Non-negotiable evaluation gates

1. Season-forward splits only; no random train/test rows.
2. Features must have an `available_at` timestamp earlier than the FPL deadline.
3. Compare against roll, five-GW form, ownership, official safe forecast when available, and the
   prior production model.
4. Report MAE/RMSE **and** decision metrics: captain regret, transfer net gain, top-k high-return
   recall, squad points, chip value and rank-distribution simulation.
5. Lock an untouched 2026/27 prospective holdout. Do not tune on Lewis's realised results.
6. Promote only on repeated improvement across seasons/positions and no material downside-tail
   regression.

## Sources and limitations

- [Solio EOS](https://eos.solioanalytics.com/) defines projected points as its model expectation
  from each manager's weekly picks. It is a third-party retrospective evidence layer, not truth.
- [Vaastav's data dictionary](https://github.com/vaastav/Fantasy-Premier-League/blob/master/DATA_DICTIONARY.md)
  explicitly warns that historical `xP` timing may be post-match.
- [OpenFPL](https://arxiv.org/abs/2508.09992) reports prospective 2024/25 performance from
  position-specific public-data ensembles, supporting it as a benchmark direction—not as proof
  that our implementation will inherit its results.
- Top-manager action datasets are selected on final performance. They reveal behaviours worth
  testing, but cannot estimate an unbiased causal advantage without a contemporaneous control
  cohort.
- Complete all-manager decision histories do not exist publicly across old seasons. The mandatory
  2026/27 collector must therefore preserve our own and opt-in users' public pre-deadline states.
"""
    REPORT.write_text(content, encoding="utf-8")


def run() -> dict[str, Any]:
    ensure_layout()
    if not DATABASE.exists():
        raise FileNotFoundError("DuckDB catalog missing; run `fpl-data catalog` first")
    connection = duckdb.connect(str(DATABASE))
    try:
        feature_rows = build_feature_table(connection)
        forecast_metrics, signal_metrics, prediction_rows = forecast_backtest(connection)
        metrics = {
            "generated_at": datetime.now(UTC).isoformat(),
            "feature_rows": feature_rows,
            "prediction_rows": prediction_rows,
            "outcomes": outcome_metrics(connection),
            "decisions": decision_metrics(connection),
            "supporting": supporting_metrics(connection),
            "forecast_backtests": forecast_metrics,
            "signal_backtests": signal_metrics,
        }
    finally:
        connection.close()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(metrics)
    return {
        "feature_rows": feature_rows,
        "prediction_rows": prediction_rows,
        "metrics": str(METRICS.relative_to(ROOT)),
        "report": str(REPORT.relative_to(ROOT)),
    }
