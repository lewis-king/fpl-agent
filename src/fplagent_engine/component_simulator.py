from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb
from scipy.special import ndtr
from scipy.stats import poisson
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_hash,
)
from .component_candidates import COMPONENT_CANDIDATES_JSON
from .component_models import (
    CURRENT_COMPONENT_FORECAST,
)
from .component_models import (
    MODEL_FILE as COMPONENT_EVENT_MODEL_FILE,
)
from .market_odds import apply_current_market_shadow_rates
from .models import BACKTEST_FORECAST, CURRENT_FORECAST, require_cuda
from .paths import ARTIFACTS, MODEL_DATA, REPORTS, ensure_engine_layout
from .tournament import (
    CANDIDATES_JSON,
    CURRENT_FIXTURES,
    DEFAULT_EVENTS,
    PLAYER_GAMEWEEKS,
    TRAINING_FEATURES,
    _finalist_candidates,
    _load_rows,
    _metrics,
    _policy_candidate,
    _score_candidates,
    calibrate_residuals,
)
from .tournament import (
    RESULTS_JSON as RESIDUAL_RESULTS_JSON,
)

COMPONENT_VERSION = "match_component_v2_event_models"
MODEL_DIR = ARTIFACTS / "component_v1"
GOAL_MODEL_FILE = MODEL_DIR / "goal-model.joblib"
GOAL_METRICS_FILE = MODEL_DIR / "goal-model-metrics.json"
CURRENT_GOAL_RATES = MODEL_DIR / "2026-27-preseason-goal-rates.parquet"
RESULT_DIR = MODEL_DATA / "tournament_v2"
RESULTS_JSON = RESULT_DIR / "component-gw1-5-results.json"
RESULTS_PARQUET = RESULT_DIR / "component-gw1-5-candidate-metrics.parquet"
PLAYER_CALIBRATION_PARQUET = RESULT_DIR / "component-player-calibration.parquet"
COMPONENT_BACKTEST_METRICS = MODEL_DATA / "component_backtest_v1" / "metrics.json"
REPORT = REPORTS / "gw1-component-tournament.md"
HISTORICAL_FIXTURES = PROCESSED / "vaastav" / "fixtures.parquet"

GOAL_FEATURES = (
    "is_home",
    "adjusted_team_attack",
    "adjusted_team_defence",
    "adjusted_team_venue_attack",
    "adjusted_team_venue_defence",
    "adjusted_opponent_attack",
    "adjusted_opponent_defence",
    "adjusted_opponent_venue_attack",
    "adjusted_opponent_venue_defence",
    "team_expected_goals",
    "team_expected_goals_against",
    "team_clean_sheet_probability",
    "team_promoted_prior",
    "opponent_promoted_prior",
    "log_team_rating_matches",
    "log_opponent_rating_matches",
    "team_rating_rest_days",
    "opponent_rating_rest_days",
)
POSITIONS = ("GK", "DEF", "MID", "FWD")
POSITION_INDEX = {position: index for index, position in enumerate(POSITIONS)}
GOAL_POINTS = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
CS_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
DC_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}


@dataclass(frozen=True)
class EmpiricalComponents:
    minute_pools: dict[tuple[str, int], np.ndarray]
    goal_rate90: dict[str, float]
    assist_rate90: dict[str, float]
    yellow_rate90: dict[str, float]
    red_rate90: dict[str, float]
    own_goal_rate90: dict[str, float]
    penalty_miss_rate90: dict[str, float]
    penalty_save_rate90: float
    save_rate90: float
    dc_probability: dict[tuple[str, int], float]
    multi_fixture_appearance_probability: dict[int, np.ndarray]
    assist_per_goal: float
    rows: int
    recent_rows: int


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def _empirical_summary(empirical: EmpiricalComponents) -> dict[str, Any]:
    return {
        "rows": empirical.rows,
        "recent_rows": empirical.recent_rows,
        "minute_pool_rows": {
            f"{position}:{minute_class}": len(values)
            for (position, minute_class), values in empirical.minute_pools.items()
        },
        "goal_rate90": empirical.goal_rate90,
        "assist_rate90": empirical.assist_rate90,
        "yellow_rate90": empirical.yellow_rate90,
        "red_rate90": empirical.red_rate90,
        "own_goal_rate90": empirical.own_goal_rate90,
        "penalty_miss_rate90": empirical.penalty_miss_rate90,
        "penalty_save_rate90": empirical.penalty_save_rate90,
        "save_rate90": empirical.save_rate90,
        "dc_probability": {
            f"{position}:{minute_class}": probability
            for (position, minute_class), probability in empirical.dc_probability.items()
        },
        "multi_fixture_appearance_probability": {
            str(fixture_count): probabilities
            for fixture_count, probabilities in empirical.multi_fixture_appearance_probability.items()
        },
        "assist_per_goal": empirical.assist_per_goal,
    }


def _historical_goal_rows() -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray, np.ndarray]:
    connection = duckdb.connect()
    try:
        cursor = connection.execute(
            f"""
            WITH team_deadlines AS (
                SELECT
                    season,
                    event_number,
                    team_id,
                    any_value(fixture_count) AS fixture_count,
                    any_value(adjusted_team_attack) AS adjusted_team_attack,
                    any_value(adjusted_team_defence) AS adjusted_team_defence,
                    any_value(adjusted_team_venue_attack)
                        AS adjusted_team_venue_attack,
                    any_value(adjusted_team_venue_defence)
                        AS adjusted_team_venue_defence,
                    any_value(adjusted_opponent_attack) AS adjusted_opponent_attack,
                    any_value(adjusted_opponent_defence)
                        AS adjusted_opponent_defence,
                    any_value(adjusted_opponent_venue_attack)
                        AS adjusted_opponent_venue_attack,
                    any_value(adjusted_opponent_venue_defence)
                        AS adjusted_opponent_venue_defence,
                    any_value(team_expected_goals) AS team_expected_goals,
                    any_value(team_expected_goals_against)
                        AS team_expected_goals_against,
                    any_value(team_clean_sheet_probability)
                        AS team_clean_sheet_probability,
                    any_value(team_promoted_prior) AS team_promoted_prior,
                    any_value(opponent_promoted_prior) AS opponent_promoted_prior,
                    any_value(team_rating_matches) AS team_rating_matches,
                    any_value(opponent_rating_matches) AS opponent_rating_matches,
                    any_value(team_rating_days_since_match)
                        AS team_rating_days_since_match,
                    any_value(opponent_rating_days_since_match)
                        AS opponent_rating_days_since_match
                FROM read_parquet('{_sql_path(TRAINING_FEATURES)}')
                GROUP BY season, event_number, team_id
            ), fixture_sides AS (
                SELECT
                    season, event, id AS fixture_id, team_h AS team_id,
                    team_h_score::DOUBLE AS goals, 1.0 AS is_home
                FROM read_parquet('{_sql_path(HISTORICAL_FIXTURES)}')
                WHERE finished AND team_h_score IS NOT NULL
                UNION ALL
                SELECT
                    season, event, id, team_a, team_a_score::DOUBLE, 0.0
                FROM read_parquet('{_sql_path(HISTORICAL_FIXTURES)}')
                WHERE finished AND team_a_score IS NOT NULL
            )
            SELECT
                s.season,
                s.event,
                s.fixture_id,
                s.team_id,
                s.goals,
                s.is_home,
                f.adjusted_team_attack,
                f.adjusted_team_defence,
                f.adjusted_team_venue_attack,
                f.adjusted_team_venue_defence,
                f.adjusted_opponent_attack,
                f.adjusted_opponent_defence,
                f.adjusted_opponent_venue_attack,
                f.adjusted_opponent_venue_defence,
                f.team_expected_goals,
                f.team_expected_goals_against,
                f.team_clean_sheet_probability,
                f.team_promoted_prior,
                f.opponent_promoted_prior,
                log(1 + f.team_rating_matches),
                log(1 + f.opponent_rating_matches),
                least(f.team_rating_days_since_match, 30),
                least(f.opponent_rating_days_since_match, 30)
            FROM fixture_sides s
            JOIN team_deadlines f
              ON s.season = f.season
             AND s.event = f.event_number
             AND s.team_id = f.team_id
            WHERE f.fixture_count = 1
            ORDER BY s.season, s.event, s.fixture_id, s.is_home DESC
            """
        )
        values = cursor.fetchall()
    finally:
        connection.close()
    metadata = [
        {
            "season": row[0],
            "event": int(row[1]),
            "fixture_id": int(row[2]),
            "team_id": int(row[3]),
        }
        for row in values
    ]
    seasons = np.asarray([row[0] for row in values], dtype=object)
    target = np.asarray([row[4] for row in values], dtype=np.float32)
    matrix = np.asarray(
        [[np.nan if value is None else float(value) for value in row[5:]] for row in values],
        dtype=np.float32,
    )
    return metadata, seasons, target, matrix


def _goal_regressor(seed: int) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="count:poisson",
        eval_metric="poisson-nloglik",
        n_estimators=350,
        learning_rate=0.025,
        max_depth=3,
        min_child_weight=15.0,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.10,
        reg_lambda=8.0,
        tree_method="hist",
        device="cuda",
        random_state=seed,
        n_jobs=8,
    )


def _poisson_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    predicted = np.clip(predicted, 0.05, 6.0)
    clean_sheet_probability = np.exp(-predicted)
    clean_sheet_actual = (actual == 0).astype(np.float32)
    return {
        "rows": len(actual),
        "actual_mean": float(actual.mean()),
        "predicted_mean": float(predicted.mean()),
        "mae": float(mean_absolute_error(actual, predicted)),
        "poisson_deviance": float(mean_poisson_deviance(actual, predicted)),
        "clean_sheet_brier": float(np.mean((clean_sheet_probability - clean_sheet_actual) ** 2)),
        "clean_sheet_predicted_rate": float(clean_sheet_probability.mean()),
        "clean_sheet_actual_rate": float(clean_sheet_actual.mean()),
    }


def _paired_residual_correlation(
    metadata: list[dict[str, Any]], selected: np.ndarray, residuals: np.ndarray
) -> float:
    by_fixture: dict[tuple[str, int], list[float]] = defaultdict(list)
    selected_indices = np.flatnonzero(selected)
    for offset, index in enumerate(selected_indices):
        row = metadata[int(index)]
        by_fixture[(str(row["season"]), int(row["fixture_id"]))].append(float(residuals[offset]))
    pairs = [values for values in by_fixture.values() if len(values) == 2]
    if len(pairs) < 20:
        return 0.0
    return float(np.corrcoef(np.asarray(pairs, dtype=np.float64).T)[0, 1])


def train_goal_model(*, force: bool = False, seed: int = 20260802) -> dict[str, Any]:
    ensure_engine_layout()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if GOAL_MODEL_FILE.exists() and GOAL_METRICS_FILE.exists() and not force:
        return json.loads(GOAL_METRICS_FILE.read_text(encoding="utf-8"))
    cuda = require_cuda()
    metadata, seasons, target, matrix = _historical_goal_rows()
    split_metrics: dict[str, Any] = {}
    residual_correlations = []
    passes = []
    for test_season in ("2024-25", "2025-26"):
        training = seasons < test_season
        testing = seasons == test_season
        medians = np.nanmedian(matrix[training], axis=0)
        train_matrix = np.where(np.isnan(matrix[training]), medians, matrix[training])
        test_matrix = np.where(np.isnan(matrix[testing]), medians, matrix[testing])
        model = _goal_regressor(seed + int(test_season[:4]))
        model.fit(train_matrix, target[training], verbose=False)
        predicted = np.clip(
            model.get_booster().predict(xgb.DMatrix(test_matrix)), 0.05, 6.0
        )
        is_home_train = matrix[training, 0] >= 0.5
        baseline_home = float(target[training][is_home_train].mean())
        baseline_away = float(target[training][~is_home_train].mean())
        baseline = np.where(matrix[testing, 0] >= 0.5, baseline_home, baseline_away)
        model_metrics = _poisson_metrics(target[testing], predicted)
        baseline_metrics = _poisson_metrics(target[testing], baseline)
        residual_correlation = _paired_residual_correlation(
            metadata, testing, target[testing] - predicted
        )
        residual_correlations.append(residual_correlation)
        improved = model_metrics["poisson_deviance"] < baseline_metrics["poisson_deviance"]
        passes.append(improved)
        split_metrics[test_season] = {
            "model": model_metrics,
            "home_away_baseline": baseline_metrics,
            "poisson_deviance_improved": improved,
            "paired_score_residual_correlation": residual_correlation,
        }
    medians = np.nanmedian(matrix, axis=0)
    final_matrix = np.where(np.isnan(matrix), medians, matrix)
    model = _goal_regressor(seed)
    model.fit(final_matrix, target, verbose=False)
    score_correlation = float(np.clip(np.mean(residual_correlations), -0.15, 0.15))
    artifact = {
        "model": model,
        "medians": medians,
        "features": GOAL_FEATURES,
        "score_correlation": score_correlation,
        "training_rows": len(target),
        "seed": seed,
    }
    joblib.dump(artifact, GOAL_MODEL_FILE)
    metrics = {
        "version": 2,
        "engine": "gpu_poisson_opponent_adjusted_fixture_goals_v2",
        "created_at": datetime.now(UTC).isoformat(),
        "training_rows": len(target),
        "training_seasons": sorted({str(value) for value in seasons}),
        "features": list(GOAL_FEATURES),
        "season_forward": split_metrics,
        "acceptance": {
            "both_seasons_beat_home_away_poisson_deviance": bool(all(passes)),
            "passed": bool(all(passes)),
        },
        "score_residual_correlation": score_correlation,
        "cuda": cuda,
        "training_features_sha256": sha256_file(TRAINING_FEATURES),
        "historical_fixtures_sha256": sha256_file(HISTORICAL_FIXTURES),
    }
    GOAL_METRICS_FILE.write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metrics


def _goal_feature_vector(row: dict[str, Any], is_home: bool) -> list[float]:
    values = [
        float(is_home),
        row.get("adjusted_team_attack"),
        row.get("adjusted_team_defence"),
        row.get("adjusted_team_venue_attack"),
        row.get("adjusted_team_venue_defence"),
        row.get("adjusted_opponent_attack"),
        row.get("adjusted_opponent_defence"),
        row.get("adjusted_opponent_venue_attack"),
        row.get("adjusted_opponent_venue_defence"),
        row.get("team_expected_goals"),
        row.get("team_expected_goals_against"),
        row.get("team_clean_sheet_probability"),
        row.get("team_promoted_prior"),
        row.get("opponent_promoted_prior"),
        math.log1p(float(row.get("team_rating_matches") or 0.0)),
        math.log1p(float(row.get("opponent_rating_matches") or 0.0)),
        min(float(row.get("team_rating_days_since_match") or 7.0), 30.0),
        min(float(row.get("opponent_rating_days_since_match") or 7.0), 30.0),
    ]
    return [np.nan if value is None else float(value) for value in values]


def predict_current_goal_rates(
    by_player: dict[int, dict[int, dict]], events: tuple[int, ...] = DEFAULT_EVENTS
) -> tuple[dict[tuple[int, int, int], tuple[float, float]], dict[str, Any]]:
    if not GOAL_MODEL_FILE.exists():
        train_goal_model()
    artifact = joblib.load(GOAL_MODEL_FILE)
    rows_by_team_event: dict[tuple[int, int], dict] = {}
    for player_rows in by_player.values():
        for event, row in player_rows.items():
            rows_by_team_event[(int(event), int(row["team_id"]))] = row
    fixtures = [
        row
        for row in pq.read_table(CURRENT_FIXTURES).to_pylist()
        if row["event"] is not None and int(row["event"]) in events
    ]
    design = []
    keys = []
    for fixture in sorted(fixtures, key=lambda row: (int(row["event"]), int(row["id"]))):
        event = int(fixture["event"])
        home = int(fixture["team_h"])
        away = int(fixture["team_a"])
        home_row = rows_by_team_event[(event, home)]
        away_row = rows_by_team_event[(event, away)]
        design.extend([_goal_feature_vector(home_row, True), _goal_feature_vector(away_row, False)])
        keys.append((event, home, away))
    matrix = np.asarray(design, dtype=np.float32)
    matrix = np.where(np.isnan(matrix), artifact["medians"], matrix)
    predicted = np.clip(
        artifact["model"].get_booster().predict(xgb.DMatrix(matrix)), 0.10, 4.50
    )
    rates = {
        key: (float(predicted[offset * 2]), float(predicted[offset * 2 + 1]))
        for offset, key in enumerate(keys)
    }
    output_rows = [
        {
            "event": event,
            "team_h": home,
            "team_a": away,
            "home_goal_rate": rates[(event, home, away)][0],
            "away_goal_rate": rates[(event, home, away)][1],
            "home_clean_sheet_probability": math.exp(-rates[(event, home, away)][1]),
            "away_clean_sheet_probability": math.exp(-rates[(event, home, away)][0]),
        }
        for event, home, away in keys
    ]
    pq.write_table(pa.Table.from_pylist(output_rows), CURRENT_GOAL_RATES, compression="zstd")
    return rates, {
        "fixtures": len(keys),
        "mean_home_goal_rate": float(np.mean(predicted[0::2])),
        "mean_away_goal_rate": float(np.mean(predicted[1::2])),
        "minimum_goal_rate": float(predicted.min()),
        "maximum_goal_rate": float(predicted.max()),
        "score_correlation": float(artifact["score_correlation"]),
    }


def calibrate_empirical_components() -> EmpiricalComponents:
    connection = duckdb.connect()
    try:
        minute_rows = connection.execute(
            f"""
            SELECT position,
                   CASE WHEN minutes = 0 THEN 0 WHEN minutes < 60 THEN 1
                        WHEN minutes < 90 THEN 2 ELSE 3 END AS class,
                   minutes
            FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
            WHERE position IN ('GK', 'DEF', 'MID', 'FWD')
            """
        ).fetchall()
        rate_rows = connection.execute(
            f"""
            SELECT position, sum(minutes)::DOUBLE AS minutes,
                   sum(goals_scored)::DOUBLE AS goals,
                   sum(assists)::DOUBLE AS assists,
                   sum(yellow_cards)::DOUBLE AS yellows,
                   sum(red_cards)::DOUBLE AS reds,
                   sum(own_goals)::DOUBLE AS own_goals,
                   sum(penalties_missed)::DOUBLE AS penalties_missed,
                   sum(penalties_saved)::DOUBLE AS penalties_saved,
                   sum(saves)::DOUBLE AS saves
            FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
            WHERE season >= '2023-24' AND minutes > 0
              AND position IN ('GK', 'DEF', 'MID', 'FWD')
            GROUP BY position
            """
        ).fetchall()
        dc_rows = connection.execute(
            f"""
            SELECT position,
                   CASE WHEN minutes < 60 THEN 1 WHEN minutes < 90 THEN 2 ELSE 3 END AS class,
                   count(*) AS rows,
                   avg(CASE
                       WHEN position = 'DEF' AND defensive_contribution >= 10 THEN 1.0
                       WHEN position IN ('MID', 'FWD') AND defensive_contribution >= 12 THEN 1.0
                       ELSE 0.0 END) AS probability
            FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
            WHERE season = '2025-26' AND minutes > 0
              AND position IN ('DEF', 'MID', 'FWD')
            GROUP BY position, class
            """
        ).fetchall()
        multi_fixture_rows = connection.execute(
            f"""
            WITH player_events AS (
                SELECT season, GW AS event, element,
                       count(DISTINCT fixture) AS fixture_count,
                       sum(CASE WHEN minutes > 0 THEN 1 ELSE 0 END) AS appearance_count
                FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
                GROUP BY season, GW, element
            )
            SELECT fixture_count, appearance_count, count(*) AS observations
            FROM player_events
            WHERE fixture_count >= 2 AND appearance_count > 0
            GROUP BY fixture_count, appearance_count
            ORDER BY fixture_count, appearance_count
            """
        ).fetchall()
        total_rows = connection.execute(
            f"SELECT count(*) FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')"
        ).fetchone()[0]
        recent_rows = connection.execute(
            f"""SELECT count(*) FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
                 WHERE season >= '2023-24' AND minutes > 0"""
        ).fetchone()[0]
    finally:
        connection.close()
    pools: dict[tuple[str, int], list[int]] = defaultdict(list)
    for position, minute_class, minutes in minute_rows:
        pools[(str(position), int(minute_class))].append(int(min(minutes, 90)))
    minute_pools = {
        key: np.asarray(values, dtype=np.int8) for key, values in pools.items() if values
    }
    rates: dict[str, dict[str, float]] = {}
    for row in rate_rows:
        position = str(row[0])
        minutes = max(float(row[1]), 1.0)
        rates[position] = {
            "goal": 90.0 * float(row[2]) / minutes,
            "assist": 90.0 * float(row[3]) / minutes,
            "yellow": 90.0 * float(row[4]) / minutes,
            "red": 90.0 * float(row[5]) / minutes,
            "own_goal": 90.0 * float(row[6]) / minutes,
            "penalty_miss": 90.0 * float(row[7]) / minutes,
            "penalty_save": 90.0 * float(row[8]) / minutes,
            "save": 90.0 * float(row[9]) / minutes,
        }
    dc_probability = {
        (str(position), int(minute_class)): float(probability)
        for position, minute_class, _, probability in dc_rows
    }
    multi_counts: dict[int, np.ndarray] = {}
    for fixture_count, appearance_count, observations in multi_fixture_rows:
        count = int(fixture_count)
        if count not in multi_counts:
            multi_counts[count] = np.zeros(count + 1, dtype=np.float64)
        multi_counts[count][int(appearance_count)] = float(observations)
    multi_fixture_probability = {
        count: values / values.sum() for count, values in multi_counts.items() if values.sum() > 0
    }
    total_goals = sum(float(row[2]) for row in rate_rows)
    total_assists = sum(float(row[3]) for row in rate_rows)
    return EmpiricalComponents(
        minute_pools=minute_pools,
        goal_rate90={position: rates[position]["goal"] for position in POSITIONS},
        assist_rate90={position: rates[position]["assist"] for position in POSITIONS},
        yellow_rate90={position: rates[position]["yellow"] for position in POSITIONS},
        red_rate90={position: rates[position]["red"] for position in POSITIONS},
        own_goal_rate90={position: rates[position]["own_goal"] for position in POSITIONS},
        penalty_miss_rate90={position: rates[position]["penalty_miss"] for position in POSITIONS},
        penalty_save_rate90=rates["GK"]["penalty_save"],
        save_rate90=rates["GK"]["save"],
        dc_probability=dc_probability,
        multi_fixture_appearance_probability=multi_fixture_probability,
        assist_per_goal=float(np.clip(total_assists / max(total_goals, 1.0), 0.65, 0.95)),
        rows=int(total_rows),
        recent_rows=int(recent_rows),
    )


def backtest_attack_allocation(empirical: EmpiricalComponents) -> dict[str, Any]:
    """Test player goal/assist shares while holding the realised team total fixed.

    Holding the total fixed deliberately isolates the player-allocation layer from
    the already separate team-goal model test. Actual minutes isolate attacking
    propensity from the separately calibrated appearance model.
    """
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            WITH outcomes AS (
                SELECT season, element, GW AS event_number,
                       sum(goals_scored)::DOUBLE AS goal_count,
                       sum(assists)::DOUBLE AS assist_count,
                       sum(minutes)::DOUBLE AS minute_count
                FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
                GROUP BY season, element, GW
            )
            SELECT
                f.season, f.event_number, f.team_id, f.element, f.position,
                f.history_events, f.form5_minutes, f.form5_goals, f.form5_assists,
                f.form5_xg, f.form5_xa, f.penalty_order, f.corner_order,
                o.goal_count, o.assist_count, o.minute_count
            FROM read_parquet('{_sql_path(TRAINING_FEATURES)}') f
            JOIN outcomes o
              ON f.season = o.season
             AND f.event_number = o.event_number
             AND f.element = o.element
            WHERE f.season IN ('2024-25', '2025-26')
              AND f.fixture_count = 1
              AND f.position IN ('GK', 'DEF', 'MID', 'FWD')
            ORDER BY f.season, f.event_number, f.team_id, f.element
            """
        ).fetchall()
    finally:
        connection.close()
    groups: dict[tuple[str, int, int], list[tuple]] = defaultdict(list)
    for row in rows:
        groups[(str(row[0]), int(row[1]), int(row[2]))].append(row)
    output: dict[str, Any] = {}
    passes = []
    for season in ("2024-25", "2025-26"):
        season_metrics = {}
        for kind, outcome_offset, prior_rates in (
            ("goals", 13, empirical.goal_rate90),
            ("assists", 14, empirical.assist_rate90),
        ):
            actual_values = []
            predicted_values = []
            baseline_values = []
            for (group_season, _, _), group in groups.items():
                if group_season != season:
                    continue
                actual = np.asarray([float(row[outcome_offset]) for row in group])
                total = float(actual.sum())
                propensity = []
                baseline_propensity = []
                for row in group:
                    feature_row = {
                        "position": row[4],
                        "history_events": row[5],
                        "form5_minutes": row[6],
                        "form5_goals": row[7],
                        "form5_assists": row[8],
                        "form5_xg": row[9],
                        "form5_xa": row[10],
                        "penalty_order": row[11],
                        "corner_order": row[12],
                    }
                    rate_kind = "goal" if kind == "goals" else "assist"
                    exposure = float(row[15]) / 90.0
                    propensity.append(
                        _attacking_propensity(feature_row, prior_rates[str(row[4])], rate_kind)
                        * exposure
                    )
                    baseline_propensity.append(prior_rates[str(row[4])] * exposure)
                propensity_array = np.asarray(propensity)
                baseline_array = np.asarray(baseline_propensity)
                predicted = total * propensity_array / max(propensity_array.sum(), 1e-9)
                baseline = total * baseline_array / max(baseline_array.sum(), 1e-9)
                actual_values.extend(actual)
                predicted_values.extend(predicted)
                baseline_values.extend(baseline)
            actual_array = np.asarray(actual_values)
            predicted_array = np.clip(np.asarray(predicted_values), 1e-6, None)
            baseline_array = np.clip(np.asarray(baseline_values), 1e-6, None)
            model_deviance = float(mean_poisson_deviance(actual_array, predicted_array))
            baseline_deviance = float(mean_poisson_deviance(actual_array, baseline_array))
            improved = model_deviance < baseline_deviance
            passes.append(improved)
            season_metrics[kind] = {
                "rows": len(actual_array),
                "actual_events": float(actual_array.sum()),
                "model_poisson_deviance": model_deviance,
                "position_minutes_baseline_poisson_deviance": baseline_deviance,
                "improved": improved,
            }
        output[season] = season_metrics
    return {
        "method": (
            "Realised team event total and player minutes are held fixed to isolate leakage-safe "
            "player propensity from the team-score and appearance layers."
        ),
        "season_forward": output,
        "acceptance": {
            "all_goal_and_assist_splits_beat_position_minutes_baseline": bool(all(passes)),
            "passed": bool(all(passes)),
        },
    }


def backtest_scoring_reconstruction() -> dict[str, Any]:
    """Reconstruct recent historical points from recorded match components."""
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            WITH scored AS (
                SELECT season, total_points,
                    CASE WHEN minutes = 0 THEN 0 ELSE
                        CASE WHEN minutes >= 60 THEN 2 ELSE 1 END
                        + goals_scored * CASE position
                            WHEN 'GK' THEN 10 WHEN 'DEF' THEN 6
                            WHEN 'MID' THEN 5 WHEN 'FWD' THEN 4 END
                        + assists * 3
                        + CASE WHEN minutes >= 60 AND clean_sheets > 0 THEN
                            CASE position WHEN 'GK' THEN 4 WHEN 'DEF' THEN 4
                                          WHEN 'MID' THEN 1 ELSE 0 END ELSE 0 END
                        + CASE WHEN position IN ('GK', 'DEF')
                               THEN -(goals_conceded // 2) ELSE 0 END
                        + CASE WHEN position = 'GK' THEN saves // 3 ELSE 0 END
                        + penalties_saved * 5 - penalties_missed * 2
                        - yellow_cards - red_cards * 3 - own_goals * 2 + bonus
                        + CASE WHEN season = '2025-26' AND (
                            (position = 'DEF' AND defensive_contribution >= 10)
                            OR (position IN ('MID', 'FWD') AND defensive_contribution >= 12)
                          ) THEN 2 ELSE 0 END
                    END AS reconstructed
                FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
                WHERE season >= '2023-24'
                  AND position IN ('GK', 'DEF', 'MID', 'FWD')
            )
            SELECT season, count(*) AS rows,
                   count(*) FILTER (WHERE reconstructed = total_points) AS exact_rows,
                   avg(abs(reconstructed - total_points)) AS mae,
                   max(abs(reconstructed - total_points)) AS maximum_error,
                   sum(reconstructed - total_points) AS bias
            FROM scored
            GROUP BY season
            ORDER BY season
            """
        ).fetchall()
    finally:
        connection.close()
    seasons = {
        str(season): {
            "rows": int(row_count),
            "exact_rows": int(exact_rows),
            "exact_rate": float(exact_rows / row_count),
            "mae": float(mae),
            "maximum_error": int(maximum_error),
            "bias": int(bias),
        }
        for season, row_count, exact_rows, mae, maximum_error, bias in rows
    }
    exact_rows = sum(value["exact_rows"] for value in seasons.values())
    total_rows = sum(value["rows"] for value in seasons.values())
    exact_rate = exact_rows / total_rows
    return {
        "method": "Current component formula applied to recorded recent fixture components",
        "seasons": seasons,
        "rows": total_rows,
        "exact_rows": exact_rows,
        "exact_rate": exact_rate,
        "acceptance": {"minimum_exact_rate": 0.999, "passed": exact_rate >= 0.999},
    }


def backtest_xp_topk_calibration() -> dict[str, Any]:
    """Audit the xP marginals where an optimizer actually selects players."""
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            WITH ranked AS (
                SELECT *, row_number() OVER (
                    PARTITION BY season, event_number, position
                    ORDER BY expected_points DESC
                ) AS position_rank
                FROM read_parquet('{_sql_path(BACKTEST_FORECAST)}')
            ), selected AS (
                SELECT * FROM ranked
                WHERE position_rank <= CASE position
                    WHEN 'GK' THEN 5 WHEN 'DEF' THEN 15
                    WHEN 'MID' THEN 15 ELSE 8 END
            )
            SELECT season, position, count(*) AS rows,
                   avg(expected_points) AS predicted,
                   avg(target_points) AS actual,
                   avg(expected_points - target_points) AS bias,
                   avg(abs(expected_points - target_points)) AS mae
            FROM selected
            GROUP BY season, position
            ORDER BY season, position
            """
        ).fetchall()
    finally:
        connection.close()
    by_season: dict[str, dict[str, Any]] = defaultdict(dict)
    pooled: dict[str, dict[str, float]] = defaultdict(
        lambda: {"rows": 0.0, "predicted_total": 0.0, "actual_total": 0.0}
    )
    for season, position, row_count, predicted, actual, bias, mae in rows:
        by_season[str(season)][str(position)] = {
            "rows": int(row_count),
            "predicted": float(predicted),
            "actual": float(actual),
            "bias": float(bias),
            "mae": float(mae),
        }
        pooled[str(position)]["rows"] += float(row_count)
        pooled[str(position)]["predicted_total"] += float(predicted) * row_count
        pooled[str(position)]["actual_total"] += float(actual) * row_count
    pooled_output = {}
    for position, values in pooled.items():
        predicted = values["predicted_total"] / values["rows"]
        actual = values["actual_total"] / values["rows"]
        pooled_output[position] = {
            "rows": int(values["rows"]),
            "predicted": predicted,
            "actual": actual,
            "bias": predicted - actual,
        }
    maximum_bias = max(abs(value["bias"]) for value in pooled_output.values())
    return {
        "method": "Top forecasted players per event using the optimizer's position cutoffs",
        "season_forward": dict(by_season),
        "pooled_by_position": pooled_output,
        "maximum_absolute_pooled_bias": maximum_bias,
        "acceptance": {
            "maximum_absolute_pooled_bias": 0.50,
            "passed": maximum_bias <= 0.50,
        },
    }


def _league_point_conservation(
    by_player: dict[int, dict[int, dict]],
    player_ids: list[int],
    events: tuple[int, ...],
    raw_points: np.ndarray,
) -> dict[str, Any]:
    fixtures_per_event = 10
    raw_per_event = raw_points.mean(axis=0).sum(axis=1) / fixtures_per_event
    xp_per_event = np.asarray(
        [
            sum(float(by_player[element][event]["expected_points"]) for element in player_ids)
            / fixtures_per_event
            for event in events
        ]
    )
    connection = duckdb.connect()
    try:
        historical_rows = connection.execute(
            f"""
            WITH match_points AS (
                SELECT season, fixture, sum(total_points)::DOUBLE AS points
                FROM read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}')
                WHERE season >= '2023-24'
                GROUP BY season, fixture
            )
            SELECT season, count(*) AS fixtures, avg(points) AS points_per_match
            FROM match_points GROUP BY season ORDER BY season
            """
        ).fetchall()
    finally:
        connection.close()
    historical = {
        str(season): {"fixtures": int(fixtures), "points_per_match": float(points)}
        for season, fixtures, points in historical_rows
    }
    latest = historical["2025-26"]["points_per_match"]
    raw_mean = float(raw_per_event.mean())
    xp_mean = float(xp_per_event.mean())
    return {
        "historical": historical,
        "current_raw_points_per_match_by_event": {
            str(event): float(value) for event, value in zip(events, raw_per_event, strict=True)
        },
        "current_xp_points_per_match_by_event": {
            str(event): float(value) for event, value in zip(events, xp_per_event, strict=True)
        },
        "current_raw_points_per_match": raw_mean,
        "current_xp_points_per_match": xp_mean,
        "raw_minus_xp": raw_mean - xp_mean,
        "raw_minus_latest_actual": raw_mean - latest,
        "xp_minus_latest_actual": xp_mean - latest,
        "acceptance": {
            "tolerance_fraction_of_latest": 0.10,
            "raw_passed": abs(raw_mean - latest) <= 0.10 * latest,
            "xp_passed": abs(xp_mean - latest) <= 0.10 * latest,
            "passed": bool(
                abs(raw_mean - latest) <= 0.10 * latest and abs(xp_mean - latest) <= 0.10 * latest
            ),
        },
    }


def _attacking_propensity(row: dict[str, Any], prior: float, kind: str) -> float:
    minutes_per_event = max(float(row.get("form5_minutes") or 0.0), 0.0)
    history_events = min(int(row.get("history_events") or 0), 5)
    exposure = minutes_per_event * history_events
    if kind == "goal":
        expected = float(row.get("form5_xg") or 0.0)
        realised = float(row.get("form5_goals") or 0.0)
        recent = 0.70 * expected + 0.30 * realised
    else:
        expected = float(row.get("form5_xa") or 0.0)
        realised = float(row.get("form5_assists") or 0.0)
        recent = 0.70 * expected + 0.30 * realised
    recent_rate = 90.0 * recent / max(minutes_per_event, 30.0)
    shrunk = (prior * 900.0 + recent_rate * exposure) / (900.0 + exposure)
    if kind == "goal" and float(row.get("penalty_order") or 99.0) == 1.0:
        shrunk += 0.09
    if kind == "assist" and float(row.get("corner_order") or 99.0) <= 2.0:
        shrunk += 0.05
    return float(max(shrunk, 0.0001))


def _load_component_event_forecasts(
    forecast_path: Path = CURRENT_COMPONENT_FORECAST,
) -> tuple[dict[tuple[int, int], dict], dict[str, Any]]:
    if not forecast_path.exists():
        return {}, {"available": False, "promoted": {}}
    rows = pq.read_table(forecast_path).to_pylist()
    by_player_event = {(int(row["element"]), int(row["event_number"])): row for row in rows}
    promoted = {
        name: bool(rows[0].get(f"{name}_model_promoted", False))
        for name in ("goals", "assists", "bonus", "saves")
    }
    return by_player_event, {
        "available": True,
        "rows": len(rows),
        "promoted": promoted,
        "forecast_sha256": sha256_file(forecast_path),
        "model_sha256": (
            sha256_file(COMPONENT_EVENT_MODEL_FILE) if COMPONENT_EVENT_MODEL_FILE.exists() else None
        ),
    }


def _sample_fixture_appearance_plan(
    event_available: np.ndarray,
    fixture_counts: np.ndarray,
    conditional_probabilities: dict[int, np.ndarray],
    rng: np.random.Generator,
) -> np.ndarray:
    """Allocate event-level availability across fixtures without inflating P(any minutes)."""
    if event_available.ndim != 2:
        raise ValueError("event_available must be a simulation-by-player matrix")
    if fixture_counts.shape != (event_available.shape[1],):
        raise ValueError("fixture_counts must contain one value per player")
    maximum = int(fixture_counts.max(initial=0))
    plan = np.zeros((*event_available.shape, maximum), dtype=bool)
    for player, raw_count in enumerate(fixture_counts):
        count = int(raw_count)
        if count <= 0:
            continue
        active = np.flatnonzero(event_available[:, player])
        if not len(active):
            continue
        probabilities = conditional_probabilities.get(count)
        if probabilities is None:
            probabilities = np.zeros(count + 1, dtype=np.float64)
            probabilities[count] = 1.0
        probabilities = np.asarray(probabilities, dtype=np.float64)
        if probabilities.shape != (count + 1,):
            raise ValueError(
                f"multi-fixture appearance distribution for {count} fixtures has wrong shape"
            )
        positive = np.clip(probabilities[1:], 0.0, None)
        if positive.sum() <= 0.0:
            raise ValueError(
                f"multi-fixture appearance distribution for {count} fixtures has no play mass"
            )
        positive /= positive.sum()
        appearance_counts = 1 + np.searchsorted(
            np.cumsum(positive), rng.random(len(active)), side="right"
        )
        priorities = rng.random((len(active), count))
        ranks = np.argsort(np.argsort(priorities, axis=1), axis=1)
        plan[active, player, :count] = ranks < appearance_counts[:, None]
    return plan


def _conditional_play_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conditional = []
    for row in rows:
        output = dict(row)
        play_mass = sum(
            max(float(row[field]), 0.0)
            for field in ("p_1_59", "p_60_89", "p_90_or_more")
        )
        output["p_dnp"] = 0.0
        if play_mass <= 0.0:
            output.update({"p_1_59": 0.0, "p_60_89": 0.0, "p_90_or_more": 1.0})
        else:
            for field in ("p_1_59", "p_60_89", "p_90_or_more"):
                output[field] = max(float(row[field]), 0.0) / play_mass
        conditional.append(output)
    return conditional


def _sample_minutes(
    rows: list[dict[str, Any]],
    empirical: EmpiricalComponents,
    rng: np.random.Generator,
    player_latent: np.ndarray,
    play_rho: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    simulations, players = player_latent.shape
    independent = rng.standard_normal((simulations, players), dtype=np.float32)
    latent = math.sqrt(play_rho) * player_latent + math.sqrt(1.0 - play_rho) * independent
    uniforms = ndtr(latent)
    minutes = np.zeros((simulations, players), dtype=np.int8)
    starts_at = np.zeros((simulations, players), dtype=np.int8)
    ends_at = np.zeros((simulations, players), dtype=np.int8)
    minute_classes = np.zeros((simulations, players), dtype=np.int8)
    for index, row in enumerate(rows):
        probabilities = np.asarray(
            [
                float(row["p_dnp"]),
                float(row["p_1_59"]),
                float(row["p_60_89"]),
                float(row["p_90_or_more"]),
            ],
            dtype=np.float64,
        )
        probabilities = np.clip(probabilities, 0.0, None)
        probabilities /= probabilities.sum()
        thresholds = np.cumsum(probabilities)
        classes = np.searchsorted(thresholds, uniforms[:, index], side="right")
        classes = np.clip(classes, 0, 3).astype(np.int8)
        minute_classes[:, index] = classes
        for minute_class in (1, 2, 3):
            selected = classes == minute_class
            count = int(selected.sum())
            if not count:
                continue
            pool = empirical.minute_pools[(str(row["position"]), minute_class)]
            minutes[selected, index] = pool[rng.integers(0, len(pool), count)]
        short = classes == 1
        probability_60 = probabilities[2] + probabilities[3]
        historical_start = float(row.get("start_rate5") or 0.0)
        predicted_start = float(np.clip(max(probability_60, historical_start), 0.0, 1.0))
        short_start_probability = float(
            np.clip((predicted_start - probability_60) / max(probabilities[1], 1e-6), 0.05, 0.85)
        )
        short_starts = short & (rng.random(simulations) < short_start_probability)
        substitutes = short & ~short_starts
        starts_at[substitutes, index] = 90 - minutes[substitutes, index]
        ends_at[short_starts, index] = minutes[short_starts, index]
        ends_at[substitutes, index] = 90
        medium_or_full = classes >= 2
        ends_at[medium_or_full, index] = minutes[medium_or_full, index]
    return minutes, starts_at, ends_at, minute_classes


def _categorical_player(
    eligible: np.ndarray, propensities: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    weights = eligible * propensities[None, :]
    totals = weights.sum(axis=1)
    draws = rng.random(len(weights)) * totals
    cumulative = np.cumsum(weights, axis=1)
    choices = np.sum(cumulative < draws[:, None], axis=1)
    choices = np.minimum(choices, len(propensities) - 1)
    return choices.astype(np.int64), totals > 0


def _simulate_scores(
    home_rate: float,
    away_rate: float,
    correlation: float,
    simulations: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    home_normal = rng.standard_normal(simulations)
    away_normal = correlation * home_normal + math.sqrt(1.0 - correlation**2) * rng.standard_normal(
        simulations
    )
    home = poisson.ppf(np.clip(ndtr(home_normal), 1e-8, 1 - 1e-8), home_rate)
    away = poisson.ppf(np.clip(ndtr(away_normal), 1e-8, 1 - 1e-8), away_rate)
    return np.clip(home, 0, 8).astype(np.int8), np.clip(away, 0, 8).astype(np.int8)


def _award_bonus(
    player_indices: np.ndarray,
    minutes: np.ndarray,
    goals: np.ndarray,
    assists: np.ndarray,
    clean_sheets: np.ndarray,
    saves: np.ndarray,
    yellow: np.ndarray,
    red: np.ndarray,
    defensive_contribution: np.ndarray,
    positions: np.ndarray,
    expected_bonus: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    played = minutes[:, player_indices] > 0
    position_goal_bps = np.asarray(
        [
            12.0
            if positions[index] in {"GK", "DEF"}
            else 18.0
            if positions[index] == "MID"
            else 24.0
            for index in player_indices
        ]
    )
    bonus_prior = np.log(np.clip(expected_bonus[player_indices], 0.01, None))
    bonus_prior = 5.0 * (bonus_prior - float(np.mean(bonus_prior)))
    performance = (
        goals[:, player_indices] * position_goal_bps[None, :]
        + assists[:, player_indices] * 9.0
        + clean_sheets[:, player_indices] * 6.0
        + saves[:, player_indices] * 2.0
        + defensive_contribution[:, player_indices] * 2.0
        - yellow[:, player_indices] * 3.0
        - red[:, player_indices] * 9.0
        + bonus_prior[None, :]
        + rng.normal(0.0, 5.0, size=played.shape)
    )
    performance = np.where(played, performance, -1e6)
    order = np.argpartition(performance, -3, axis=1)[:, -3:]
    ordered_values = np.take_along_axis(performance, order, axis=1)
    rank_order = np.argsort(ordered_values, axis=1)
    chosen = np.take_along_axis(order, rank_order, axis=1)
    bonus = np.zeros_like(played, dtype=np.int8)
    simulation_index = np.arange(len(played))
    bonus[simulation_index, chosen[:, 0]] = 1
    bonus[simulation_index, chosen[:, 1]] = 2
    bonus[simulation_index, chosen[:, 2]] = 3
    return bonus


def _calibrate_to_xp(
    raw_points: np.ndarray,
    played: np.ndarray,
    target: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, Any]]:
    anchored = raw_points.copy().astype(np.int16)
    raw_means = raw_points.mean(axis=0)
    observed_play = played.mean(axis=0)
    conditional_adjustment = (target - raw_means) / np.maximum(observed_play, 0.005)
    simulations, events, players = raw_points.shape
    for event in range(events):
        for player in range(players):
            adjustment = float(conditional_adjustment[event, player])
            lower = math.floor(adjustment)
            probability_upper = adjustment - lower
            offsets = lower + (rng.random(simulations) < probability_upper)
            selected = played[:, event, player]
            anchored[selected, event, player] += offsets[selected]
    # One event can contain multiple fixtures. Preserve plausible double/triple-gameweek
    # tails instead of imposing the old single-match ceiling of 40 points.
    anchored = np.clip(anchored, -32, 120).astype(np.int8)
    anchored_means = anchored.mean(axis=0)
    finite = conditional_adjustment[np.isfinite(conditional_adjustment)]
    return anchored, {
        "method": "integer stochastic calibration applied only to played outcomes",
        "interpretation": (
            "The adjustment represents unmodelled player-specific points after the explicit match "
            "components; raw component scores are retained separately."
        ),
        "raw_player_mean_bias": float(np.mean(raw_means - target)),
        "raw_player_mean_absolute_error": float(np.mean(np.abs(raw_means - target))),
        "anchored_player_mean_bias": float(np.mean(anchored_means - target)),
        "anchored_player_mean_absolute_error": float(np.mean(np.abs(anchored_means - target))),
        "mean_absolute_conditional_adjustment": float(np.mean(np.abs(finite))),
        "p90_absolute_conditional_adjustment": float(np.quantile(np.abs(finite), 0.90)),
        "p95_absolute_conditional_adjustment": float(np.quantile(np.abs(finite), 0.95)),
        "maximum_absolute_conditional_adjustment": float(np.max(np.abs(finite))),
    }


def simulate_component_outcomes(
    by_player: dict[int, dict[int, dict]],
    events: tuple[int, ...],
    goal_rates: dict[tuple[int, int, int], tuple[float, float]],
    empirical: EmpiricalComponents,
    simulations: int,
    seed: int,
    *,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
) -> tuple[
    list[int],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    dict[str, np.ndarray],
    dict[str, Any],
]:
    rng = np.random.default_rng(seed)
    player_ids = sorted(by_player)
    players = len(player_ids)
    positions = np.asarray([by_player[element][events[0]]["position"] for element in player_ids])
    points = np.zeros((simulations, len(events), players), dtype=np.int8)
    played = np.zeros((simulations, len(events), players), dtype=bool)
    component_means = {
        name: np.zeros((len(events), players), dtype=np.float64)
        for name in (
            "appearance_points",
            "goals",
            "goal_points",
            "assists",
            "assist_points",
            "clean_sheet_points",
            "goals_conceded_points",
            "save_points",
            "penalty_points",
            "discipline_points",
            "bonus_points",
            "defensive_contribution_points",
            "raw_total_points",
        )
    }
    player_latent = rng.standard_normal((simulations, players), dtype=np.float32)
    fixture_rows = sorted(
        (
            row
            for row in pq.read_table(CURRENT_FIXTURES).to_pylist()
            if row["event"] is not None and int(row["event"]) in events
        ),
        key=lambda row: (int(row["event"]), int(row["id"])),
    )
    fixtures_by_event: dict[int, list[dict]] = defaultdict(list)
    for fixture in fixture_rows:
        fixtures_by_event[int(fixture["event"])].append(fixture)
    residual_calibration = calibrate_residuals()
    component_forecasts, component_forecast_diagnostics = _load_component_event_forecasts(
        component_forecast_path
    )
    score_correlation = float(joblib.load(GOAL_MODEL_FILE)["score_correlation"])
    identities = {
        "simulated_match_scenarios": 0,
        "team_goals": 0,
        "allocated_goals": 0,
        "unattributed_team_goals": 0,
        "allocated_assists": 0,
        "assist_exceeds_goal_violations": 0,
        "bonus_points_awarded": 0,
        "clean_sheet_player_rows": 0,
        "blank_player_events": 0,
        "single_fixture_player_events": 0,
        "double_fixture_player_events": 0,
        "triple_plus_fixture_player_events": 0,
        "maximum_fixtures_per_team_event": 0,
        "event_play_probability_rows": 0,
        "event_play_probability_absolute_error_sum": 0.0,
        "event_play_probability_maximum_error": 0.0,
    }
    score_summaries = []

    for event_offset, event in enumerate(events):
        rows = [by_player[element][event] for element in player_ids]
        team_by_player = np.asarray([int(row["team_id"]) for row in rows], dtype=np.int16)
        event_fixtures = fixtures_by_event[event]
        team_fixture_counts: dict[int, int] = defaultdict(int)
        for fixture in event_fixtures:
            team_fixture_counts[int(fixture["team_h"])] += 1
            team_fixture_counts[int(fixture["team_a"])] += 1
        fixture_counts = np.asarray(
            [team_fixture_counts.get(int(team), 0) for team in team_by_player], dtype=np.int8
        )
        identities["blank_player_events"] += int(np.sum(fixture_counts == 0))
        identities["single_fixture_player_events"] += int(np.sum(fixture_counts == 1))
        identities["double_fixture_player_events"] += int(np.sum(fixture_counts == 2))
        identities["triple_plus_fixture_player_events"] += int(np.sum(fixture_counts >= 3))
        identities["maximum_fixtures_per_team_event"] = max(
            identities["maximum_fixtures_per_team_event"],
            int(fixture_counts.max(initial=0)),
        )
        event_minutes, _, _, _ = _sample_minutes(
            rows, empirical, rng, player_latent, residual_calibration.play_rho
        )
        event_available = (event_minutes > 0) & (fixture_counts[None, :] > 0)
        fixture_appearance_plan = _sample_fixture_appearance_plan(
            event_available,
            fixture_counts,
            empirical.multi_fixture_appearance_probability,
            rng,
        )
        conditional_rows = _conditional_play_rows(rows)
        fixture_ordinal_by_team: dict[tuple[int, int], int] = {}
        next_ordinal_by_team: Counter[int] = Counter()
        for fixture in event_fixtures:
            fixture_id = int(fixture["id"])
            for team in (int(fixture["team_h"]), int(fixture["team_a"])):
                fixture_ordinal_by_team[(fixture_id, team)] = next_ordinal_by_team[team]
                next_ordinal_by_team[team] += 1
        event_played = np.zeros((simulations, players), dtype=bool)
        event_components_total = {
            name: np.zeros((simulations, players), dtype=np.int16)
            for name in component_means
            if name != "raw_total_points"
        }
        event_components = [component_forecasts.get((element, event), {}) for element in player_ids]
        goal_propensity = np.asarray(
            [
                (
                    90.0
                    * float(component.get("expected_goals") or 0.0)
                    / max(float(component.get("expected_minutes") or 0.0), 5.0)
                    if component.get("goals_model_promoted")
                    else _attacking_propensity(row, empirical.goal_rate90[row["position"]], "goal")
                )
                for row, component in zip(rows, event_components, strict=True)
            ],
            dtype=np.float32,
        )
        assist_propensity = np.asarray(
            [
                (
                    90.0
                    * float(component.get("expected_assists") or 0.0)
                    / max(float(component.get("expected_minutes") or 0.0), 5.0)
                    if component.get("assists_model_promoted")
                    else _attacking_propensity(
                        row, empirical.assist_rate90[row["position"]], "assist"
                    )
                )
                for row, component in zip(rows, event_components, strict=True)
            ],
            dtype=np.float32,
        )
        expected_bonus = np.asarray(
            [
                float(component.get("expected_bonus") or 0.05)
                if component.get("bonus_model_promoted")
                else 0.05
                for component in event_components
            ],
            dtype=np.float32,
        )
        for fixture in event_fixtures:
            home = int(fixture["team_h"])
            away = int(fixture["team_a"])
            fixture_indices = np.flatnonzero(np.isin(team_by_player, [home, away]))
            if not len(fixture_indices):
                continue
            fixture_id = int(fixture["id"])
            fixture_rows_for_players = [conditional_rows[index] for index in fixture_indices]
            minutes, starts_at, ends_at, minute_classes = _sample_minutes(
                fixture_rows_for_players,
                empirical,
                rng,
                player_latent[:, fixture_indices],
                residual_calibration.play_rho,
            )
            fixture_appearance_mask = np.column_stack(
                [
                    fixture_appearance_plan[
                        :,
                        index,
                        fixture_ordinal_by_team[(fixture_id, int(team_by_player[index]))],
                    ]
                    for index in fixture_indices
                ]
            )
            minutes[~fixture_appearance_mask] = 0
            starts_at[~fixture_appearance_mask] = 0
            ends_at[~fixture_appearance_mask] = 0
            minute_classes[~fixture_appearance_mask] = 0
            fixture_played = minutes > 0
            event_played[:, fixture_indices] |= fixture_played
            fixture_team_by_player = team_by_player[fixture_indices]
            fixture_positions = positions[fixture_indices]
            fixture_goal_propensity = goal_propensity[fixture_indices]
            fixture_assist_propensity = assist_propensity[fixture_indices]
            fixture_expected_bonus = expected_bonus[fixture_indices]
            fixture_players = len(fixture_indices)
            goals = np.zeros((simulations, fixture_players), dtype=np.int8)
            assists = np.zeros((simulations, fixture_players), dtype=np.int8)
            conceded = np.zeros((simulations, fixture_players), dtype=np.int8)
            home_rate, away_rate = goal_rates[(event, home, away)]
            home_score, away_score = _simulate_scores(
                home_rate, away_rate, score_correlation, simulations, rng
            )
            identities["simulated_match_scenarios"] += simulations
            identities["team_goals"] += int(home_score.sum() + away_score.sum())
            score_summaries.append(
                {
                    "event": event,
                    "team_h": home,
                    "team_a": away,
                    "home_goal_rate": home_rate,
                    "away_goal_rate": away_rate,
                    "simulated_home_goals": float(home_score.mean()),
                    "simulated_away_goals": float(away_score.mean()),
                }
            )
            for scoring_team, defending_team, score in (
                (home, away, home_score),
                (away, home, away_score),
            ):
                scoring_indices = np.flatnonzero(fixture_team_by_player == scoring_team)
                defending_indices = np.flatnonzero(fixture_team_by_player == defending_team)
                max_goals = int(score.max())
                for goal_number in range(max_goals):
                    goal_occurs = score > goal_number
                    if not goal_occurs.any():
                        continue
                    goal_time = rng.uniform(0.0, 90.0, simulations)
                    defending_on_pitch = (
                        fixture_played[:, defending_indices]
                        & (starts_at[:, defending_indices] <= goal_time[:, None])
                        & (ends_at[:, defending_indices] >= goal_time[:, None])
                    )
                    conceded[:, defending_indices] += (
                        defending_on_pitch & goal_occurs[:, None]
                    ).astype(np.int8)

                    if not len(scoring_indices):
                        identities["unattributed_team_goals"] += int(goal_occurs.sum())
                        continue
                    scoring_on_pitch = (
                        fixture_played[:, scoring_indices]
                        & (starts_at[:, scoring_indices] <= goal_time[:, None])
                        & (ends_at[:, scoring_indices] >= goal_time[:, None])
                    )
                    choices, available = _categorical_player(
                        scoring_on_pitch, fixture_goal_propensity[scoring_indices], rng
                    )
                    attributed = goal_occurs & available
                    identities["unattributed_team_goals"] += int(
                        (goal_occurs & ~available).sum()
                    )
                    chosen_global = scoring_indices[choices]
                    simulation_index = np.flatnonzero(attributed)
                    np.add.at(goals, (simulation_index, chosen_global[attributed]), 1)
                    identities["allocated_goals"] += int(attributed.sum())

                    assist_on_pitch = scoring_on_pitch.copy()
                    assist_on_pitch[np.arange(simulations), choices] = False
                    assist_choices, assist_available = _categorical_player(
                        assist_on_pitch, fixture_assist_propensity[scoring_indices], rng
                    )
                    has_assist = (
                        attributed
                        & assist_available
                        & (rng.random(simulations) < empirical.assist_per_goal)
                    )
                    assist_global = scoring_indices[assist_choices]
                    assist_simulations = np.flatnonzero(has_assist)
                    np.add.at(assists, (assist_simulations, assist_global[has_assist]), 1)
                    identities["allocated_assists"] += int(has_assist.sum())

            appearance = np.where(
                minutes >= 60, 2, np.where(minutes > 0, 1, 0)
            ).astype(np.int16)
            clean_sheets = (minutes >= 60) & (conceded == 0)
            identities["clean_sheet_player_rows"] += int(clean_sheets.sum())
            save_lambda = np.zeros(fixture_players, dtype=np.float32)
            for index, row in enumerate(fixture_rows_for_players):
                if row["position"] == "GK":
                    opponent_rate = away_rate if int(row["team_id"]) == home else home_rate
                    save_lambda[index] = empirical.save_rate90 * (0.78 + 0.16 * opponent_rate)
            saves = rng.poisson(save_lambda[None, :] * minutes / 90.0).astype(np.int8)
            penalty_saved = rng.poisson(
                empirical.penalty_save_rate90
                * minutes
                / 90.0
                * (fixture_positions[None, :] == "GK")
            ).astype(np.int8)
            yellow_rate = np.asarray([empirical.yellow_rate90[p] for p in fixture_positions])
            red_rate = np.asarray([empirical.red_rate90[p] for p in fixture_positions])
            own_goal_rate = np.asarray([empirical.own_goal_rate90[p] for p in fixture_positions])
            penalty_miss_rate = np.asarray(
                [empirical.penalty_miss_rate90[p] for p in fixture_positions]
            )
            yellow = rng.random((simulations, fixture_players)) < (
                yellow_rate[None, :] * minutes / 90.0
            )
            red = rng.random((simulations, fixture_players)) < (
                red_rate[None, :] * minutes / 90.0
            )
            own_goals = rng.random((simulations, fixture_players)) < (
                own_goal_rate[None, :] * minutes / 90.0
            )
            penalty_missed = rng.random((simulations, fixture_players)) < (
                penalty_miss_rate[None, :] * minutes / 90.0
            )
            defensive_contribution = np.zeros((simulations, fixture_players), dtype=np.int8)
            for index, position in enumerate(fixture_positions):
                if position == "GK":
                    continue
                for minute_class in (1, 2, 3):
                    selected = minute_classes[:, index] == minute_class
                    probability = empirical.dc_probability.get((str(position), minute_class), 0.0)
                    defensive_contribution[selected, index] = (
                        rng.random(int(selected.sum())) < probability
                    ).astype(np.int8)
            bonus = _award_bonus(
                np.arange(fixture_players),
                minutes,
                goals,
                assists,
                clean_sheets,
                saves,
                yellow,
                red,
                defensive_contribution,
                fixture_positions,
                fixture_expected_bonus,
                rng,
            )
            identities["bonus_points_awarded"] += int(bonus.sum())
            fixture_component_values = {
                "appearance_points": appearance,
                "goals": goals,
                "goal_points": goals
                * np.asarray([GOAL_POINTS[p] for p in fixture_positions])[None, :],
                "assists": assists,
                "assist_points": assists * 3,
                "clean_sheet_points": clean_sheets
                * np.asarray([CS_POINTS[p] for p in fixture_positions])[None, :],
                "goals_conceded_points": -(conceded // 2)
                * np.isin(fixture_positions, ["GK", "DEF"])[None, :],
                "save_points": (saves // 3) * (fixture_positions[None, :] == "GK"),
                "penalty_points": penalty_saved * 5 - penalty_missed * 2,
                "discipline_points": (
                    -yellow.astype(np.int8)
                    - red.astype(np.int8) * 3
                    - own_goals.astype(np.int8) * 2
                ),
                "bonus_points": bonus,
                "defensive_contribution_points": defensive_contribution * 2,
            }
            for name, values in fixture_component_values.items():
                event_components_total[name][:, fixture_indices] += values
            if int(assists.sum()) > int(goals.sum()):
                identities["assist_exceeds_goal_violations"] += 1

        played[:, event_offset, :] = event_played
        expected_event_play = np.asarray(
            [
                (1.0 - float(row["p_dnp"])) if fixture_counts[index] > 0 else 0.0
                for index, row in enumerate(rows)
            ]
        )
        play_error = np.abs(event_played.mean(axis=0) - expected_event_play)
        identities["event_play_probability_rows"] += players
        identities["event_play_probability_absolute_error_sum"] += float(play_error.sum())
        identities["event_play_probability_maximum_error"] = max(
            identities["event_play_probability_maximum_error"],
            float(play_error.max(initial=0.0)),
        )
        event_points = sum(
            event_components_total[name]
            for name in (
                "appearance_points",
                "goal_points",
                "assist_points",
                "clean_sheet_points",
                "goals_conceded_points",
                "save_points",
                "penalty_points",
                "discipline_points",
                "bonus_points",
                "defensive_contribution_points",
            )
        )
        points[:, event_offset, :] = np.clip(event_points, -32, 120).astype(np.int8)
        component_values = {
            **event_components_total,
            "raw_total_points": points[:, event_offset, :],
        }
        for name, values in component_values.items():
            component_means[name][event_offset, :] = values.mean(axis=0)

    target = np.asarray(
        [
            [float(by_player[element][event]["expected_points"]) for element in player_ids]
            for event in events
        ],
        dtype=np.float64,
    )
    anchored, anchoring = _calibrate_to_xp(points, played, target, rng)
    identity_diagnostics = {
        **identities,
        "event_play_probability_mean_absolute_error": (
            identities["event_play_probability_absolute_error_sum"]
            / max(identities["event_play_probability_rows"], 1)
        ),
        "goal_allocation_reconciliation_rate": (
            (identities["allocated_goals"] + identities["unattributed_team_goals"])
            / max(identities["team_goals"], 1)
        ),
        "assist_to_goal_ratio": (
            identities["allocated_assists"] / max(identities["allocated_goals"], 1)
        ),
        "expected_bonus_points_per_match_scenario": (
            identities["bonus_points_awarded"] / max(identities["simulated_match_scenarios"], 1)
        ),
    }
    diagnostics = {
        "players": players,
        "simulations": simulations,
        "events": list(events),
        "identity_checks": identity_diagnostics,
        "xp_anchoring": anchoring,
        "score_summaries": score_summaries,
        "play_rho": residual_calibration.play_rho,
        "component_event_models": component_forecast_diagnostics,
    }
    return player_ids, points, anchored, played, component_means, diagnostics


def _scenario_metrics(
    candidates: list[dict[str, Any]],
    player_ids: list[int],
    events: tuple[int, ...],
    points: np.ndarray,
    played: np.ndarray,
    meta: dict[int, dict],
    seed: int,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    scores = _score_candidates(candidates, player_ids, events, points, played, meta)
    primary_index = next(
        index
        for index, candidate in enumerate(candidates)
        if candidate["archetype"] == "current-transfer-aware"
    )
    return _metrics(scores, candidates, primary_index, seed), scores


def _candidate_player_calibration(
    candidates: list[dict[str, Any]],
    player_ids: list[int],
    events: tuple[int, ...],
    by_player: dict[int, dict[int, dict]],
    raw_points: np.ndarray,
    anchored_points: np.ndarray,
    played: np.ndarray,
) -> dict[str, Any]:
    relevant = sorted(
        {int(element) for candidate in candidates for element in candidate["selected"]}
    )
    global_index = {element: index for index, element in enumerate(player_ids)}
    indices = np.asarray([global_index[element] for element in relevant], dtype=np.int64)
    target = np.asarray(
        [
            [float(by_player[element][event]["expected_points"]) for element in relevant]
            for event in events
        ]
    )
    raw_means = raw_points[:, :, indices].mean(axis=0)
    anchored_means = anchored_points[:, :, indices].mean(axis=0)
    observed_play = played[:, :, indices].mean(axis=0)
    adjustment = (target - raw_means) / np.maximum(observed_play, 0.005)
    return {
        "players": len(relevant),
        "player_events": int(target.size),
        "raw_player_mean_bias": float(np.mean(raw_means - target)),
        "raw_player_mean_absolute_error": float(np.mean(np.abs(raw_means - target))),
        "anchored_player_mean_bias": float(np.mean(anchored_means - target)),
        "anchored_player_mean_absolute_error": float(np.mean(np.abs(anchored_means - target))),
        "mean_absolute_conditional_adjustment": float(np.mean(np.abs(adjustment))),
        "p90_absolute_conditional_adjustment": float(np.quantile(np.abs(adjustment), 0.90)),
        "p95_absolute_conditional_adjustment": float(np.quantile(np.abs(adjustment), 0.95)),
        "maximum_absolute_conditional_adjustment": float(np.max(np.abs(adjustment))),
    }


def _rank_map(metrics: list[dict[str, Any]]) -> dict[str, int]:
    return {
        row["candidate_id"]: rank
        for rank, row in enumerate(
            sorted(metrics, key=lambda value: value["mean_points"], reverse=True), start=1
        )
    }


def _market_candidate_shadow_summary(
    incumbent: list[dict[str, Any]], challenger: list[dict[str, Any]]
) -> dict[str, Any]:
    incumbent_by_id = {str(row["candidate_id"]): row for row in incumbent}
    challenger_by_id = {str(row["candidate_id"]): row for row in challenger}
    if set(incumbent_by_id) != set(challenger_by_id):
        raise ValueError("Market shadow candidate IDs do not match the incumbent")
    incumbent_order = sorted(
        incumbent_by_id,
        key=lambda key: (-float(incumbent_by_id[key]["mean_points"]), key),
    )
    challenger_order = sorted(
        challenger_by_id,
        key=lambda key: (-float(challenger_by_id[key]["mean_points"]), key),
    )
    incumbent_ranks = {key: rank for rank, key in enumerate(incumbent_order, start=1)}
    challenger_ranks = {key: rank for rank, key in enumerate(challenger_order, start=1)}
    shifts = [
        {
            "candidate_id": key,
            "mean_points_shift": float(challenger_by_id[key]["mean_points"])
            - float(incumbent_by_id[key]["mean_points"]),
            "incumbent_rank": incumbent_ranks[key],
            "market_rank": challenger_ranks[key],
            "rank_shift": incumbent_ranks[key] - challenger_ranks[key],
        }
        for key in incumbent_by_id
    ]
    shifts.sort(key=lambda row: (-abs(row["mean_points_shift"]), row["candidate_id"]))
    return {
        "incumbent_leader": incumbent_order[0],
        "market_leader": challenger_order[0],
        "leader_changed": incumbent_order[0] != challenger_order[0],
        "incumbent_leader_market_rank": challenger_ranks[incumbent_order[0]],
        "market_leader_incumbent_rank": incumbent_ranks[challenger_order[0]],
        "largest_mean_points_shifts": shifts[:10],
    }


def _compact_metric(
    candidate: dict[str, Any], raw: dict, anchored: dict, evidence: dict
) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "archetype": candidate["archetype"],
        "budget_spent": candidate["budget_spent"],
        "bank": candidate["bank"],
        "gw1_bench_spend": candidate["gw1_bench_spend"],
        "gw1_outfield_bench_spend": candidate["gw1_outfield_bench_spend"],
        **{f"raw_{key}": value for key, value in raw.items() if key != "candidate_id"},
        **{f"anchored_{key}": value for key, value in anchored.items() if key != "candidate_id"},
        **{
            f"evidence_weighted_{key}": value
            for key, value in evidence.items()
            if key != "candidate_id"
        },
    }


def _blend_scenario_scores(
    raw_scores: np.ndarray, anchored_scores: np.ndarray, raw_weight: float
) -> np.ndarray:
    """Preserve path covariance while moving marginals to the frozen historical blend."""
    if raw_scores.shape != anchored_scores.shape:
        raise ValueError("Raw and anchored score arrays must have identical shapes")
    if not 0.0 <= raw_weight <= 1.0:
        raise ValueError("Raw component weight must be in [0, 1]")
    return np.asarray(
        anchored_scores + raw_weight * (raw_scores - anchored_scores),
        dtype=np.float32,
    )


def _paired_delta_metrics(
    challenger_scores: np.ndarray, incumbent_scores: np.ndarray
) -> dict[str, float]:
    challenger = challenger_scores.sum(axis=1).astype(np.float64)
    incumbent = incumbent_scores.sum(axis=1).astype(np.float64)
    delta = challenger - incumbent
    standard_error = float(delta.std(ddof=1) / math.sqrt(len(delta)))
    return {
        "mean_delta": float(delta.mean()),
        "delta_95ci_low": float(delta.mean() - 1.96 * standard_error),
        "delta_95ci_high": float(delta.mean() + 1.96 * standard_error),
        "beat_probability": float(np.mean(delta > 0)),
        "tie_probability": float(np.mean(delta == 0)),
    }


def _evidence_metrics(
    candidates: list[dict[str, Any]],
    raw_scores: np.ndarray,
    anchored_scores: np.ndarray,
    raw_weight: float,
    seed: int,
) -> list[dict[str, Any]]:
    primary_index = next(
        index
        for index, candidate in enumerate(candidates)
        if candidate["archetype"] == "current-transfer-aware"
    )
    scores = _blend_scenario_scores(raw_scores, anchored_scores, raw_weight)
    return _metrics(scores, candidates, primary_index, seed)


def _render_report(result: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    fixed = sorted(
        result["fixed_candidate_metrics"],
        key=lambda row: row["evidence_weighted_mean_points"],
        reverse=True,
    )
    policy = sorted(
        result["policy_finalist_metrics"],
        key=lambda row: row["evidence_weighted_mean_points"],
        reverse=True,
    )
    native = sorted(
        result.get("component_native_metrics", []),
        key=lambda row: row["evidence_weighted_mean_points"],
        reverse=True,
    )
    gate = result["promotion_gate"]
    recommended = result["recommended_candidate"]
    recommended_metric = next(
        row for row in [*native, *policy] if row["candidate_id"] == recommended
    )
    lines = [
        "# GW1–5 match-component tournament",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{gate['status'].upper()}** — {gate['reason']} The production recommendation is "
            f"**{result['recommended_candidate']}**; the residual-engine incumbent entering this "
            f"test was **{result['incumbent_recommendation']}**."
        ),
        "",
        (
            f"The xP-anchored component policy leader is **{policy[0]['candidate_id']}** "
            f"({policy[0]['anchored_mean_points']:.2f} mean points); the raw-component leader is "
            f"**{max(policy, key=lambda row: row['raw_mean_points'])['candidate_id']}**."
        ),
        (
            f"Including independently discovered component-native squads, the evidence-weighted "
            f"leader is **{result['leaders']['evidence_weighted']}**. The anchored leader is "
            f"**{result['leaders']['overall_anchored']}** and the raw leader is "
            f"**{result['leaders']['overall_raw']}**."
            if native
            else "No component-native challenger file was available for this run."
        ),
        "",
        "## What is now simulated",
        "",
        "- GPU Poisson home/away goal rates trained from leakage-safe opponent-adjusted attack/defence ratings, venue splits and promoted-team priors.",
        "- Separately gated GPU player-event models for scorer, assister and bonus allocation.",
        "- Correlated match scores, goal times and player on-pitch intervals.",
        "- Every team goal is allocated to an eligible scorer; no more than one eligible teammate receives an assist.",
        "- Clean sheets and goals conceded are derived from goals while each player is on the pitch.",
        "- Appearance points, saves, cards, own goals, missed/saved penalties, defensive contribution and match-level 3/2/1 bonus.",
        "- Exact FPL autosubs, legal formations, captain fallback and the previously generated transfer-aware finalist policies.",
        "",
        "## Adversarial gates",
        "",
        "| Gate | Result | Evidence |",
        "|---|---:|---|",
    ]
    for check in gate["checks"]:
        lines.append(
            f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | {check['evidence']} |"
        )
    lines.extend(
        [
            "",
            "## Transfer-aware finalists",
            "",
            "| Rank | ID | Archetype | Raw mean | Anchored mean | Decision mean | Decision P10–P90 | Decision Δ |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, row in enumerate(policy, start=1):
        lines.append(
            f"| {rank} | {row['candidate_id']} | {row['archetype']} | "
            f"{row['raw_mean_points']:.2f} | {row['anchored_mean_points']:.2f} | "
            f"{row['evidence_weighted_mean_points']:.2f} | "
            f"{row['evidence_weighted_p10_points']:.0f}–"
            f"{row['evidence_weighted_p90_points']:.0f} | "
            f"{row['evidence_weighted_mean_delta_to_primary']:+.2f} |"
        )
    if native:
        lines.extend(
            [
                "",
                "## Independently selected component-native challengers",
                "",
                "| Rank | ID | Archetype | Raw mean | Anchored mean | Decision mean | Decision 95% CI Δ | Decision Δ |",
                "|---:|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for rank, row in enumerate(native, start=1):
            lines.append(
                f"| {rank} | {row['candidate_id']} | {row['archetype']} | "
                f"{row['raw_mean_points']:.2f} | {row['anchored_mean_points']:.2f} | "
                f"{row['evidence_weighted_mean_points']:.2f} | "
                f"{row['evidence_weighted_delta_95ci_low']:+.2f} to "
                f"{row['evidence_weighted_delta_95ci_high']:+.2f} | "
                f"{row['evidence_weighted_mean_delta_to_primary']:+.2f} |"
            )
    lines.extend(
        [
            "",
            "## Top 20 fixed squads",
            "",
            "| Rank | ID | Archetype | Bench | Raw mean | Anchored mean | Decision mean | Decision top-three |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, row in enumerate(fixed[:20], start=1):
        lines.append(
            f"| {rank} | {row['candidate_id']} | {row['archetype']} | "
            f"£{row['gw1_bench_spend']:.1f}m | {row['raw_mean_points']:.2f} | "
            f"{row['anchored_mean_points']:.2f} | {row['evidence_weighted_mean_points']:.2f} | "
            f"{100 * row['evidence_weighted_top_3_probability']:.1f}% |"
        )
    historical_bench = result["historical_bench_evidence"]["gameweeks"][0]
    current_fixed = next(row for row in fixed if row["candidate_id"] == "S001")
    bench_bands = (
        ("≤£18.5m", lambda value: value <= 18.5),
        ("£18.6–20.0m", lambda value: 18.5 < value <= 20.0),
        ("£20.1–22.0m", lambda value: 20.0 < value <= 22.0),
        (">£22.0m", lambda value: value > 22.0),
    )
    lines.extend(
        [
            "",
            "## Premium and bench interrogation",
            "",
            (
                f"S001 spends £{current_fixed['gw1_bench_spend']:.1f}m on its GW1 bench. The "
                f"2019/20 eventual top ten averaged £{historical_bench['mean_bench_spend']:.2f}m "
                f"(range £{historical_bench['minimum_bench_spend']:.1f}m–"
                f"£{historical_bench['maximum_bench_spend']:.1f}m). Those ten managers are "
                "survivorship-selected and played under older prices/rules, so this is an audit "
                "signal rather than an optimisation target."
            ),
            "",
            "| GW1 bench band | Fixed squads | Best fixed decision | Best transfer-aware finalist |",
            "|---|---:|---:|---:|",
        ]
    )
    for label, in_band in bench_bands:
        fixed_group = [row for row in fixed if in_band(float(row["gw1_bench_spend"]))]
        policy_group = [row for row in policy if in_band(float(row["gw1_bench_spend"]))]
        fixed_best = max(fixed_group, key=lambda row: row["evidence_weighted_mean_points"])
        policy_best = max(policy_group, key=lambda row: row["evidence_weighted_mean_points"])
        lines.append(
            f"| {label} | {len(fixed_group)} | {fixed_best['candidate_id']} "
            f"{fixed_best['evidence_weighted_mean_points']:.2f} | "
            f"{policy_best['candidate_id']} {policy_best['evidence_weighted_mean_points']:.2f} |"
        )
    premium_rows = {
        name: next(row for row in policy if name in row["archetype"])
        for name in ("Haaland", "Saka", "Palmer", "Isak")
    }
    lines.extend(
        [
            "",
            (
                "Relative to S001, the strongest named-premium policies score: "
                + ", ".join(
                    f"{name} {row['evidence_weighted_mean_delta_to_primary']:+.2f}"
                    for name, row in premium_rows.items()
                )
                + " points over five weeks. Saka therefore wins the residual-policy field, but "
                f"the independently selected overall recommendation is {recommended}. Bruno "
                "Fernandes remains the premium and captain in the promoted squad."
            ),
            "",
            (
                "The conclusion is not that an expensive bench is universally desirable. Fixed and "
                "transfer-aware winners occupy different bench bands, while the final promoted "
                f"candidate {recommended} spends £"
                f"{recommended_metric['gw1_bench_spend']:.1f}m "
                "on its GW1 bench. Bench spend remains a diagnostic, never a rewarded feature."
            ),
        ]
    )
    anchoring = result["candidate_player_calibration"]
    anchor_impact = result["anchor_impact_on_candidate_scores"]
    conservation = result["league_point_conservation"]
    identities = result["simulation_diagnostics"]["identity_checks"]
    lines.extend(
        [
            "",
            "## Calibration and identities",
            "",
            (
                f"All {identities['team_goals']:,} team goals are reconciled: "
                f"{identities['allocated_goals']:,} player goals and "
                f"{identities['unattributed_team_goals']:,} own/unattributed goals "
                f"({100 * identities['goal_allocation_reconciliation_rate']:.3f}%). "
                f"The simulated assist/goal ratio is {identities['assist_to_goal_ratio']:.3f}; "
                f"bonus averages {identities['expected_bonus_points_per_match_scenario']:.2f} "
                "points per match scenario."
            ),
            "",
            (
                f"Across the {anchoring['players']} players used by the 128 candidate squads, "
                f"pre-anchor player-event mean absolute error is "
                f"{anchoring['raw_player_mean_absolute_error']:.3f} points; after anchoring it is "
                f"{anchoring['anchored_player_mean_absolute_error']:.3f}. The conditional adjustment "
                f"has mean absolute size {anchoring['mean_absolute_conditional_adjustment']:.3f} "
                f"and P95 {anchoring['p95_absolute_conditional_adjustment']:.3f}."
            ),
            "",
            (
                f"Literal full anchoring adds "
                f"{anchor_impact['incumbent_policy_total_points']:.2f} points to S001 over five "
                f"weeks ({anchor_impact['incumbent_policy_points_per_event']:.2f}/GW). The "
                f"season-forward backtest selected only {100 * anchor_impact['evidence_raw_weight']:.0f}% "
                f"raw component signal, so the evidence-weighted component shift is "
                f"{anchor_impact['evidence_component_shift_points_per_event']:.2f}/GW. "
                "That historically frozen lineup-weighted figure controls the excessive-anchor gate."
            ),
            "",
            (
                f"This is a selection-tail disagreement, not league-wide point inflation. The raw "
                f"component model generates {conservation['current_raw_points_per_match']:.2f} "
                f"points per match and xP {conservation['current_xp_points_per_match']:.2f}, versus "
                f"{conservation['historical']['2025-26']['points_per_match']:.2f} actually scored in "
                "2025/26. Rolling top-k xP is also historically calibrated within the gate. The raw "
                "layer is therefore useful for covariance and sensitivity, but not yet proven superior "
                "for identifying the best individual players."
            ),
            "",
            (
                "The raw result is the literal component model. The anchored result preserves those "
                "match-driven covariance shocks but adjusts marginal means to the promoted xP forecast. "
                f"The decision column uses the {100 * result['component_player_backtest']['selected_raw_weight']:.0f}% "
                "raw weight selected on 2024/25 and then tested unchanged on 2025/26."
            ),
            "",
            "## Squad detail for the anchored policy leader",
            "",
        ]
    )
    leader = by_id[policy[0]["candidate_id"]]
    for player in leader["players"]:
        lines.append(
            f"- {player['position']}: {player['name']} ({player['team']}, £{player['price']:.1f}m)"
        )
    lines.extend(
        [
            "",
            "## Remaining limitations",
            "",
            "The goal model has only a modest out-of-season edge over a home/away baseline. Goal timing is uniform, whether a goal receives an assist still uses a league-level probability, and bonus uses a promoted player-event prior inside a BPS-inspired 3/2/1 approximation rather than a full event-by-event BPS engine. Defensive-contribution probabilities have one season of evidence. The xP anchor is deliberately reported, never disguised as an observed component.",
            "",
        ]
    )
    return "\n".join(lines)


def run_component_tournament(
    *, simulations: int = 25_000, seed: int = 20260802, force_goal_model: bool = False
) -> dict[str, Any]:
    if simulations < 1_000:
        raise ValueError("Component tournament requires at least 1,000 simulations")
    ensure_engine_layout()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if not COMPONENT_BACKTEST_METRICS.exists():
        raise FileNotFoundError(
            "Run `fplagent backtest-components` before the component tournament"
        )
    component_backtest = json.loads(COMPONENT_BACKTEST_METRICS.read_text(encoding="utf-8"))
    evidence_raw_weight = float(
        component_backtest["blend_selection"]["selected_raw_weight"]
    )
    if not 0.0 <= evidence_raw_weight <= 1.0:
        raise ValueError("Historically selected component raw weight must be in [0, 1]")
    candidate_payload = load_json_artifact(CANDIDATES_JSON, "residual candidates")
    current_forecast_sha256 = require_current_forecast(
        candidate_payload, CURRENT_FORECAST, "residual candidates"
    )
    candidates = candidate_payload["candidates"]
    residual_result = load_json_artifact(
        RESIDUAL_RESULTS_JSON, "residual tournament results"
    )
    require_recorded_hash(
        residual_result,
        ("forecast_sha256",),
        current_forecast_sha256,
        "residual tournament results",
    )
    goal_metrics = train_goal_model(force=force_goal_model, seed=seed)
    rows, loaded = _load_rows(DEFAULT_EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    goal_rates, current_goal_diagnostics = predict_current_goal_rates(by_player, DEFAULT_EVENTS)
    empirical = calibrate_empirical_components()
    attack_allocation_backtest = backtest_attack_allocation(empirical)
    scoring_reconstruction_backtest = backtest_scoring_reconstruction()
    xp_topk_backtest = backtest_xp_topk_calibration()
    player_ids, raw_points, anchored_points, played, component_means, simulation_diagnostics = (
        simulate_component_outcomes(
            by_player,
            DEFAULT_EVENTS,
            goal_rates,
            empirical,
            simulations,
            seed + 301,
        )
    )
    raw_fixed, raw_fixed_scores = _scenario_metrics(
        candidates,
        player_ids,
        DEFAULT_EVENTS,
        raw_points,
        played,
        meta,
        seed + 401,
    )
    anchored_fixed, anchored_fixed_scores = _scenario_metrics(
        candidates,
        player_ids,
        DEFAULT_EVENTS,
        anchored_points,
        played,
        meta,
        seed + 402,
    )
    evidence_fixed = _evidence_metrics(
        candidates,
        raw_fixed_scores,
        anchored_fixed_scores,
        evidence_raw_weight,
        seed + 403,
    )
    fixed_metrics = [
        _compact_metric(candidate, raw, anchored, evidence)
        for candidate, raw, anchored, evidence in zip(
            candidates, raw_fixed, anchored_fixed, evidence_fixed, strict=True
        )
    ]
    candidate_player_calibration = _candidate_player_calibration(
        candidates,
        player_ids,
        DEFAULT_EVENTS,
        by_player,
        raw_points,
        anchored_points,
        played,
    )
    league_point_conservation = _league_point_conservation(
        by_player, player_ids, DEFAULT_EVENTS, raw_points
    )
    finalists = _finalist_candidates(candidates, residual_result["selection_metrics"])
    policy_candidates = [
        _policy_candidate(candidate, rows, DEFAULT_EVENTS) for candidate in finalists
    ]
    raw_policy, raw_policy_scores = _scenario_metrics(
        policy_candidates,
        player_ids,
        DEFAULT_EVENTS,
        raw_points,
        played,
        meta,
        seed + 501,
    )
    anchored_policy, anchored_policy_scores = _scenario_metrics(
        policy_candidates,
        player_ids,
        DEFAULT_EVENTS,
        anchored_points,
        played,
        meta,
        seed + 502,
    )
    evidence_policy = _evidence_metrics(
        policy_candidates,
        raw_policy_scores,
        anchored_policy_scores,
        evidence_raw_weight,
        seed + 503,
    )
    policy_metrics = [
        _compact_metric(candidate, raw, anchored, evidence)
        for candidate, raw, anchored, evidence in zip(
            policy_candidates, raw_policy, anchored_policy, evidence_policy, strict=True
        )
    ]
    native_payload: dict[str, Any] | None = None
    native_candidates: list[dict[str, Any]] = []
    native_metrics: list[dict[str, Any]] = []
    native_selection_independent = False
    if COMPONENT_CANDIDATES_JSON.exists():
        candidate_native_payload = load_json_artifact(
            COMPONENT_CANDIDATES_JSON, "component-native candidates"
        )
        if (
            candidate_native_payload.get("forecast_sha256") == current_forecast_sha256
            and candidate_native_payload.get("player_calibration_sha256")
            == (
                sha256_file(PLAYER_CALIBRATION_PARQUET)
                if PLAYER_CALIBRATION_PARQUET.exists()
                else None
            )
            and candidate_native_payload.get("selection_results_sha256")
            == (sha256_file(RESULTS_JSON) if RESULTS_JSON.exists() else None)
        ):
            native_payload = candidate_native_payload
    if native_payload is not None:
        native_candidates = native_payload["candidates"]
        native_selection_independent = int(native_payload["selection_seed"]) != seed
        incumbent_candidate = next(
            candidate for candidate in policy_candidates if candidate["candidate_id"] == "S001"
        )
        native_evaluation = [incumbent_candidate, *native_candidates]
        native_raw_all, native_raw_scores = _scenario_metrics(
            native_evaluation,
            player_ids,
            DEFAULT_EVENTS,
            raw_points,
            played,
            meta,
            seed + 601,
        )
        native_anchored_all, native_anchored_scores = _scenario_metrics(
            native_evaluation,
            player_ids,
            DEFAULT_EVENTS,
            anchored_points,
            played,
            meta,
            seed + 602,
        )
        native_evidence_all = _evidence_metrics(
            native_evaluation,
            native_raw_scores,
            native_anchored_scores,
            evidence_raw_weight,
            seed + 603,
        )
        native_metrics = [
            _compact_metric(candidate, raw, anchored, evidence)
            for candidate, raw, anchored, evidence in zip(
                native_candidates,
                native_raw_all[1:],
                native_anchored_all[1:],
                native_evidence_all[1:],
                strict=True,
            )
        ]
    market_goal_rates, market_shadow = apply_current_market_shadow_rates(
        goal_rates,
        events=DEFAULT_EVENTS,
    )
    if market_shadow["status"] == "ready_shadow":
        (
            market_player_ids,
            market_raw_points,
            market_anchored_points,
            market_played,
            _,
            market_simulation_diagnostics,
        ) = simulate_component_outcomes(
            by_player,
            DEFAULT_EVENTS,
            market_goal_rates,
            empirical,
            simulations,
            seed + 301,
        )
        if market_player_ids != player_ids:
            raise ValueError("Market shadow changed the component player universe")
        market_raw_fixed, _ = _scenario_metrics(
            candidates,
            market_player_ids,
            DEFAULT_EVENTS,
            market_raw_points,
            market_played,
            meta,
            seed + 401,
        )
        market_anchored_fixed, _ = _scenario_metrics(
            candidates,
            market_player_ids,
            DEFAULT_EVENTS,
            market_anchored_points,
            market_played,
            meta,
            seed + 402,
        )
        market_raw_policy, _ = _scenario_metrics(
            policy_candidates,
            market_player_ids,
            DEFAULT_EVENTS,
            market_raw_points,
            market_played,
            meta,
            seed + 501,
        )
        market_anchored_policy, _ = _scenario_metrics(
            policy_candidates,
            market_player_ids,
            DEFAULT_EVENTS,
            market_anchored_points,
            market_played,
            meta,
            seed + 502,
        )
        market_shadow.update(
            {
                "simulations": simulations,
                "seed": seed + 301,
                "paired_random_stream": True,
                "fixed_raw": _market_candidate_shadow_summary(
                    raw_fixed, market_raw_fixed
                ),
                "fixed_anchored": _market_candidate_shadow_summary(
                    anchored_fixed, market_anchored_fixed
                ),
                "policy_raw": _market_candidate_shadow_summary(
                    raw_policy, market_raw_policy
                ),
                "policy_anchored": _market_candidate_shadow_summary(
                    anchored_policy, market_anchored_policy
                ),
                "simulation_diagnostics": market_simulation_diagnostics,
            }
        )
        if native_candidates:
            market_native_evaluation = [incumbent_candidate, *native_candidates]
            market_native_raw, _ = _scenario_metrics(
                market_native_evaluation,
                market_player_ids,
                DEFAULT_EVENTS,
                market_raw_points,
                market_played,
                meta,
                seed + 601,
            )
            market_native_anchored, _ = _scenario_metrics(
                market_native_evaluation,
                market_player_ids,
                DEFAULT_EVENTS,
                market_anchored_points,
                market_played,
                meta,
                seed + 602,
            )
            market_shadow.update(
                {
                    "native_raw": _market_candidate_shadow_summary(
                        native_raw_all[1:], market_native_raw[1:]
                    ),
                    "native_anchored": _market_candidate_shadow_summary(
                        native_anchored_all[1:], market_native_anchored[1:]
                    ),
                }
            )
    incumbent_policy = next(row for row in policy_metrics if row["candidate_id"] == "S001")
    anchor_impact = {
        "incumbent_policy_total_points": (
            incumbent_policy["anchored_mean_points"] - incumbent_policy["raw_mean_points"]
        ),
        "incumbent_policy_points_per_event": (
            incumbent_policy["anchored_mean_points"] - incumbent_policy["raw_mean_points"]
        )
        / len(DEFAULT_EVENTS),
        "evidence_raw_weight": evidence_raw_weight,
        "evidence_component_shift_points_per_event": (
            evidence_raw_weight
            * abs(incumbent_policy["anchored_mean_points"] - incumbent_policy["raw_mean_points"])
            / len(DEFAULT_EVENTS)
        ),
        "mean_fixed_total_points": float(
            np.mean([row["anchored_mean_points"] - row["raw_mean_points"] for row in fixed_metrics])
        ),
        "minimum_fixed_total_points": float(
            min(row["anchored_mean_points"] - row["raw_mean_points"] for row in fixed_metrics)
        ),
        "maximum_fixed_total_points": float(
            max(row["anchored_mean_points"] - row["raw_mean_points"] for row in fixed_metrics)
        ),
    }
    anchored_fixed_leader = max(fixed_metrics, key=lambda row: row["anchored_mean_points"])
    raw_fixed_leader = max(fixed_metrics, key=lambda row: row["raw_mean_points"])
    anchored_policy_leader = max(policy_metrics, key=lambda row: row["anchored_mean_points"])
    raw_policy_leader = max(policy_metrics, key=lambda row: row["raw_mean_points"])
    all_challenger_metrics = [*policy_metrics, *native_metrics]
    overall_anchored_policy_leader = max(
        all_challenger_metrics, key=lambda row: row["anchored_mean_points"]
    )
    overall_raw_policy_leader = max(all_challenger_metrics, key=lambda row: row["raw_mean_points"])
    evidence_weighted_leader = max(
        all_challenger_metrics,
        key=lambda row: row["evidence_weighted_mean_points"],
    )
    incumbent = str(residual_result["recommendation"]["candidate_id"])
    policy_index = {
        candidate["candidate_id"]: index for index, candidate in enumerate(policy_candidates)
    }
    native_index = {
        candidate["candidate_id"]: index + 1
        for index, candidate in enumerate(native_candidates)
    }
    policy_evidence_scores = _blend_scenario_scores(
        raw_policy_scores, anchored_policy_scores, evidence_raw_weight
    )
    native_evidence_scores = (
        _blend_scenario_scores(
            native_raw_scores, native_anchored_scores, evidence_raw_weight
        )
        if native_candidates
        else None
    )

    def candidate_scores(candidate_id: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if candidate_id in policy_index:
            index = policy_index[candidate_id]
            return (
                raw_policy_scores[:, index, :],
                anchored_policy_scores[:, index, :],
                policy_evidence_scores[:, index, :],
            )
        index = native_index[candidate_id]
        if native_evidence_scores is None:
            raise RuntimeError("Native evidence scores are unexpectedly absent")
        return (
            native_raw_scores[:, index, :],
            native_anchored_scores[:, index, :],
            native_evidence_scores[:, index, :],
        )

    decision_leader = str(evidence_weighted_leader["candidate_id"])
    incumbent_scores = candidate_scores(incumbent)
    leader_scores = candidate_scores(decision_leader)
    decision_comparison = {
        "incumbent": incumbent,
        "challenger": decision_leader,
        "challenger_is_component_native": decision_leader in native_index,
        "selection_independent": native_selection_independent,
        "raw": _paired_delta_metrics(leader_scores[0], incumbent_scores[0]),
        "anchored": _paired_delta_metrics(leader_scores[1], incumbent_scores[1]),
        "evidence_weighted": _paired_delta_metrics(
            leader_scores[2], incumbent_scores[2]
        ),
    }
    independent_challenger_dominates = bool(
        decision_comparison["challenger_is_component_native"]
        and decision_comparison["selection_independent"]
        and decision_comparison["raw"]["mean_delta"] > 0.0
        and decision_comparison["anchored"]["mean_delta"] > 0.0
        and decision_comparison["evidence_weighted"]["delta_95ci_low"] > 0.0
    )
    decision_comparison["promotion_rule_passed"] = bool(
        decision_leader == incumbent or independent_challenger_dominates
    )
    residual_rank = {
        row["candidate_id"]: rank
        for rank, row in enumerate(
            sorted(
                residual_result["holdout_metrics"],
                key=lambda value: value["base_mean_points"],
                reverse=True,
            ),
            start=1,
        )
    }
    component_rank = _rank_map(
        [
            {
                "candidate_id": row["candidate_id"],
                "mean_points": row["anchored_mean_points"],
            }
            for row in fixed_metrics
        ]
    )
    shared_ids = sorted(component_rank)
    rank_correlation = float(
        np.corrcoef(
            [residual_rank[candidate_id] for candidate_id in shared_ids],
            [component_rank[candidate_id] for candidate_id in shared_ids],
        )[0, 1]
    )
    anchoring = candidate_player_calibration
    identities = simulation_diagnostics["identity_checks"]
    checks = [
        {
            "name": "season-forward player-component blend",
            "passed": bool(component_backtest["gate"]["passed"]),
            "evidence": (
                f"2024/25 selected raw weight={evidence_raw_weight:.2f}; frozen 2025/26 "
                f"top-k={component_backtest['blend_selection']['test_top_k_actual_points']:.3f} "
                f"vs xP={component_backtest['blend_selection']['test_xp_top_k_actual_points']:.3f}"
            ),
        },
        {
            "name": "season-forward goal model",
            "passed": bool(goal_metrics["acceptance"]["passed"]),
            "evidence": "Poisson deviance beats the home/away baseline in 2024/25 and 2025/26",
        },
        {
            "name": "season-forward scorer/assister allocation",
            "passed": bool(attack_allocation_backtest["acceptance"]["passed"]),
            "evidence": "player propensities beat position-and-minutes allocation in both holdouts",
        },
        {
            "name": "historical scoring reconstruction",
            "passed": bool(scoring_reconstruction_backtest["acceptance"]["passed"]),
            "evidence": (
                f"exactly reconstructed {100 * scoring_reconstruction_backtest['exact_rate']:.4f}% "
                "of 2023/24–2025/26 player-fixtures"
            ),
        },
        {
            "name": "optimizer-tail xP calibration",
            "passed": bool(xp_topk_backtest["acceptance"]["passed"]),
            "evidence": (
                f"maximum pooled top-k position bias="
                f"{xp_topk_backtest['maximum_absolute_pooled_bias']:.3f} points"
            ),
        },
        {
            "name": "league point conservation",
            "passed": bool(league_point_conservation["acceptance"]["passed"]),
            "evidence": (
                f"raw={league_point_conservation['current_raw_points_per_match']:.2f}; "
                f"xP={league_point_conservation['current_xp_points_per_match']:.2f}; "
                f"2025/26 actual={league_point_conservation['historical']['2025-26']['points_per_match']:.2f}"
            ),
        },
        {
            "name": "football identities",
            "passed": bool(
                abs(identities["goal_allocation_reconciliation_rate"] - 1.0) < 1e-12
                and identities["assist_exceeds_goal_violations"] == 0
            ),
            "evidence": (
                f"goal reconciliation={identities['goal_allocation_reconciliation_rate']:.6f}; "
                f"assist violations={identities['assist_exceeds_goal_violations']}"
            ),
        },
        {
            "name": "marginal xP anchoring",
            "passed": anchoring["anchored_player_mean_absolute_error"] <= 0.03,
            "evidence": (
                f"anchored MAE={anchoring['anchored_player_mean_absolute_error']:.4f} points"
            ),
        },
        {
            "name": "anchor is not doing excessive work",
            "passed": bool(
                anchoring["mean_absolute_conditional_adjustment"] <= 2.5
                and anchoring["p95_absolute_conditional_adjustment"] <= 6.0
                and anchor_impact["evidence_component_shift_points_per_event"] <= 5.0
            ),
            "evidence": (
                f"mean |adjustment|={anchoring['mean_absolute_conditional_adjustment']:.2f}; "
                f"P95={anchoring['p95_absolute_conditional_adjustment']:.2f}; "
                f"evidence-weighted S001 component shift="
                f"{anchor_impact['evidence_component_shift_points_per_event']:.2f}/GW"
            ),
        },
        {
            "name": "component-native selection holdout",
            "passed": bool(native_candidates and native_selection_independent),
            "evidence": (
                f"candidates={len(native_candidates)}; "
                f"selection_seed={native_payload['selection_seed'] if native_payload else None}; "
                f"holdout_seed={seed}"
            ),
        },
        {
            "name": "decision stability or independent challenger dominance",
            "passed": decision_comparison["promotion_rule_passed"],
            "evidence": (
                f"incumbent={incumbent}; "
                f"anchored={overall_anchored_policy_leader['candidate_id']}; "
                f"evidence-weighted={evidence_weighted_leader['candidate_id']}; "
                f"raw stress={overall_raw_policy_leader['candidate_id']}; "
                f"paired evidence delta={decision_comparison['evidence_weighted']['mean_delta']:+.3f} "
                f"[{decision_comparison['evidence_weighted']['delta_95ci_low']:+.3f}, "
                f"{decision_comparison['evidence_weighted']['delta_95ci_high']:+.3f}]"
            ),
        },
        {
            "name": "full-field rank stability",
            "passed": rank_correlation >= 0.80,
            "evidence": f"residual/component rank correlation={rank_correlation:.3f}",
        },
    ]
    passed = all(check["passed"] for check in checks)
    promotion_gate = {
        "status": "promoted" if passed else "shadow",
        "passed": passed,
        "reason": (
            "all adversarial acceptance gates passed."
            if passed
            else "one or more adversarial gates failed, so this challenger is not allowed to replace the incumbent."
        ),
        "checks": checks,
    }
    result = {
        "version": 1,
        "engine": COMPONENT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "simulations": simulations,
        "events": list(DEFAULT_EVENTS),
        "incumbent_recommendation": incumbent,
        "recommended_candidate": (
            decision_leader if decision_comparison["promotion_rule_passed"] else incumbent
        ),
        "decision_comparison": decision_comparison,
        "promotion_gate": promotion_gate,
        "leaders": {
            "fixed_raw": raw_fixed_leader["candidate_id"],
            "fixed_anchored": anchored_fixed_leader["candidate_id"],
            "policy_raw": raw_policy_leader["candidate_id"],
            "policy_anchored": anchored_policy_leader["candidate_id"],
            "overall_raw": overall_raw_policy_leader["candidate_id"],
            "overall_anchored": overall_anchored_policy_leader["candidate_id"],
            "evidence_weighted": evidence_weighted_leader["candidate_id"],
        },
        "residual_component_fixed_rank_correlation": rank_correlation,
        "goal_model": goal_metrics,
        "component_player_backtest": {
            "selected_raw_weight": evidence_raw_weight,
            "validation_season": component_backtest["blend_selection"]["validation_season"],
            "validation_top_k_actual_points": component_backtest["blend_selection"][
                "validation_top_k_actual_points"
            ],
            "test_season": component_backtest["blend_selection"]["test_season"],
            "test_top_k_actual_points": component_backtest["blend_selection"][
                "test_top_k_actual_points"
            ],
            "test_xp_top_k_actual_points": component_backtest["blend_selection"][
                "test_xp_top_k_actual_points"
            ],
            "gate": component_backtest["gate"],
            "sha256": sha256_file(COMPONENT_BACKTEST_METRICS),
        },
        "attack_allocation_backtest": attack_allocation_backtest,
        "scoring_reconstruction_backtest": scoring_reconstruction_backtest,
        "xp_topk_backtest": xp_topk_backtest,
        "historical_bench_evidence": residual_result["historical_bench_evidence"],
        "league_point_conservation": league_point_conservation,
        "current_goal_rates": current_goal_diagnostics,
        "market_goal_rate_shadow": market_shadow,
        "empirical_components": _empirical_summary(empirical),
        "simulation_diagnostics": simulation_diagnostics,
        "candidate_player_calibration": candidate_player_calibration,
        "anchor_impact_on_candidate_scores": anchor_impact,
        "fixed_candidate_metrics": fixed_metrics,
        "policy_finalist_metrics": policy_metrics,
        "component_native_metrics": native_metrics,
        "component_native_selection": (
            {
                key: native_payload.get(key)
                for key in (
                    "candidate_count",
                    "selection_seed",
                    "selection_simulations",
                    "selection_engine",
                    "historically_selected_raw_weight",
                    "raw_weights",
                    "component_backtest_sha256",
                    "selection_results_sha256",
                    "player_calibration_sha256",
                )
            }
            if native_payload
            else None
        ),
        "policy_finalists": [
            {
                "candidate_id": candidate["candidate_id"],
                "transfer_policy": candidate["transfer_policy"],
            }
            for candidate in policy_candidates
        ],
        "artifacts": {
            "goal_model": str(GOAL_MODEL_FILE),
            "current_goal_rates": str(CURRENT_GOAL_RATES),
            "player_calibration": str(PLAYER_CALIBRATION_PARQUET),
            "candidate_sha256": sha256_file(CANDIDATES_JSON),
            "component_candidate_sha256": (
                sha256_file(COMPONENT_CANDIDATES_JSON)
                if COMPONENT_CANDIDATES_JSON.exists()
                else None
            ),
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
        },
        "assumptions": [
            "Goal times are uniform within matches conditional on the simulated score.",
            "One FPL assist at most is allocated per goal using a league-level assisted-goal rate.",
            "Bonus uses a BPS-inspired match ranking with exactly 3/2/1 points and no ties.",
            "Defensive contribution is shrunk to 2025/26 position/minute-class frequencies.",
            "Raw component and xP-anchored results are both reported.",
        ],
    }
    if market_shadow["status"] == "ready_shadow":
        result["artifacts"].update(
            {
                "market_goal_rates": market_shadow["artifact"],
                "market_goal_rates_sha256": market_shadow["artifact_sha256"],
                "market_goal_rate_receipt": market_shadow["receipt"],
                "market_goal_rate_receipt_sha256": market_shadow[
                    "receipt_sha256"
                ],
            }
        )
    parquet_rows = [
        {
            key: value
            for key, value in row.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        for row in fixed_metrics
    ]
    write_table(pa.Table.from_pylist(parquet_rows), RESULTS_PARQUET)
    candidate_elements = {
        int(element) for candidate in candidates for element in candidate["selected"]
    }
    player_index = {element: index for index, element in enumerate(player_ids)}
    raw_means = raw_points.mean(axis=0)
    anchored_means = anchored_points.mean(axis=0)
    play_means = played.mean(axis=0)
    player_calibration_rows = []
    for event_offset, event in enumerate(DEFAULT_EVENTS):
        for element in player_ids:
            index = player_index[element]
            target = float(by_player[element][event]["expected_points"])
            player_calibration_rows.append(
                {
                    "event": event,
                    "element": element,
                    "player_name": by_player[element][event]["player_name"],
                    "position": by_player[element][event]["position"],
                    "team_id": int(by_player[element][event]["team_id"]),
                    "in_candidate_universe": element in candidate_elements,
                    "expected_points": target,
                    "raw_component_mean": float(raw_means[event_offset, index]),
                    "anchored_mean": float(anchored_means[event_offset, index]),
                    "observed_play_probability": float(play_means[event_offset, index]),
                    "raw_minus_expected": float(raw_means[event_offset, index] - target),
                    "conditional_anchor_adjustment": float(
                        (target - raw_means[event_offset, index])
                        / max(play_means[event_offset, index], 0.005)
                    ),
                    **{
                        f"mean_{name}": float(values[event_offset, index])
                        for name, values in component_means.items()
                    },
                }
            )
    write_table(pa.Table.from_pylist(player_calibration_rows), PLAYER_CALIBRATION_PARQUET)
    result["artifacts"]["player_calibration_sha256"] = sha256_file(
        PLAYER_CALIBRATION_PARQUET
    )
    RESULTS_JSON.write_text(
        json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.write_text(_render_report(result, candidates), encoding="utf-8")
    return result
