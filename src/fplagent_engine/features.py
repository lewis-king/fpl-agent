from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.arrow import write_rows
from fplagent_data.database import DATABASE
from fplagent_data.event_outcomes import CURRENT_PLAYER_HISTORY

from .live_feature_contract import audit_live_feature_contract
from .paths import FEATURES, NORMALIZED, ensure_engine_layout
from .team_strength import (
    CURRENT_TEAM_STRENGTH,
    HISTORICAL_TEAM_STRENGTH,
    build_team_strength,
)

TRAINING_FEATURES = FEATURES / "player_deadlines.parquet"
CURRENT_FEATURES = FEATURES / "current_player_horizons.parquet"
TEAM_FORM = NORMALIZED / "team_form.parquet"
FEATURE_AVAILABILITY = NORMALIZED / "feature_availability.parquet"

POSITIONS = ("GK", "DEF", "MID", "FWD")

# These columns may exist in lossless official snapshots, but they must never
# influence an FPLAgent forecast. Keep this denylist close to the production
# feature allowlist so training and inference can enforce the same contract.
FORBIDDEN_OFFICIAL_FORECAST_FEATURES = frozenset({"xP", "ep_this", "ep_next"})

ATTACKING_HISTORY_FEATURES = (
    "form10_goals",
    "form10_assists",
    "form10_xg",
    "form10_xa",
    "form38_goals",
    "form38_assists",
    "form38_xg",
    "form38_xa",
    "form38_minutes",
)

LEGACY_MODEL_FEATURES = (
    "fixture_count",
    "home_fraction",
    "fixture_difficulty",
    "event_number",
    "history_events",
    "player_days_since_last_event",
    "last_points",
    "form3_points",
    "form5_points",
    "form10_points",
    "form38_points",
    "last_minutes",
    "form3_minutes",
    "form5_minutes",
    "form10_minutes",
    "appearance_rate5",
    "start_rate5",
    "form5_goals",
    "form5_assists",
    "form5_xg",
    "form5_xa",
    "form5_bps",
    "form5_clean_sheets",
    "form5_defensive_contribution",
    "market_price",
    "ownership_percentile",
    "availability_chance",
    "penalty_order",
    "corner_order",
    "team_attack5",
    "team_defence5",
    "team_attack10",
    "team_defence10",
    "opponent_attack5",
    "opponent_defence5",
    "team_history_matches",
    "opponent_history_matches",
    "team_days_since_match",
    "opponent_days_since_match",
    "cold_start",
    "deadline_proxy_available",
)

RAW_OR_OFFICIAL_TEAM_FEATURES = (
    "fixture_difficulty",
    "team_attack5",
    "team_defence5",
    "team_attack10",
    "team_defence10",
    "opponent_attack5",
    "opponent_defence5",
    "team_history_matches",
    "opponent_history_matches",
    "team_days_since_match",
    "opponent_days_since_match",
)

ADJUSTED_RATING_FEATURES = (
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
    "team_rating_matches",
    "opponent_rating_matches",
    "team_rating_days_since_match",
    "opponent_rating_days_since_match",
)

# The production challenger deliberately excludes official FPL difficulty and
# unadjusted rolling goal rates. Those columns remain available solely so the
# champion/challenger experiment can compare against the previous model fairly.
MODEL_FEATURES = (
    *(
        feature
        for feature in LEGACY_MODEL_FEATURES
        if feature not in RAW_OR_OFFICIAL_TEAM_FEATURES
    ),
    *ADJUSTED_RATING_FEATURES,
)


def assert_independent_forecast_features(feature_names: tuple[str, ...]) -> None:
    forbidden = sorted(FORBIDDEN_OFFICIAL_FORECAST_FEATURES.intersection(feature_names))
    if forbidden:
        joined = ", ".join(forbidden)
        raise RuntimeError(
            "Official FPL expected-points fields are forbidden in FPLAgent models: "
            f"{joined}"
        )


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _copy(connection: duckdb.DuckDBPyConnection, query: str, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    escaped = _sql_path(output)
    connection.execute(
        f"COPY ({query}) TO '{escaped}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    return pq.ParquetFile(output).metadata.num_rows


def _feature_registry() -> int:
    lagged = {
        "history_events",
        "player_days_since_last_event",
        "last_points",
        "form3_points",
        "form5_points",
        "form10_points",
        "form38_points",
        "last_minutes",
        "form3_minutes",
        "form5_minutes",
        "form10_minutes",
        "appearance_rate5",
        "start_rate5",
        "form5_goals",
        "form5_assists",
        "form5_xg",
        "form5_xa",
        "form10_goals",
        "form10_assists",
        "form10_xg",
        "form10_xa",
        "form38_goals",
        "form38_assists",
        "form38_xg",
        "form38_xa",
        "form38_minutes",
        "form5_bps",
        "form5_clean_sheets",
        "form5_defensive_contribution",
        "team_attack5",
        "team_defence5",
        "team_attack10",
        "team_defence10",
        "opponent_attack5",
        "opponent_defence5",
        "team_history_matches",
        "opponent_history_matches",
        "team_days_since_match",
        "opponent_days_since_match",
        *ADJUSTED_RATING_FEATURES,
    }
    deadline = {
        "fixture_count",
        "home_fraction",
        "fixture_difficulty",
        "event_number",
        "market_price",
        "ownership_percentile",
        "availability_chance",
        "penalty_order",
        "corner_order",
        "deadline_proxy_available",
    }
    rows = []
    registry_features = tuple(
        dict.fromkeys(
            (*LEGACY_MODEL_FEATURES, *MODEL_FEATURES, *ATTACKING_HISTORY_FEATURES)
        )
    )
    for name in registry_features:
        if name in lagged:
            source = "prior_finalized_match_outcomes"
            availability_rule = "strictly before target deadline"
        elif name in deadline:
            source = "deadline_snapshot"
            availability_rule = "observed_at strictly before deadline"
        else:
            source = "derived"
            availability_rule = "derived only from allowlisted inputs"
        rows.append(
            {
                "feature": name,
                "source": source,
                "availability_rule": availability_rule,
                "production_allowed": name != "fixture_difficulty",
                "same_gameweek_outcome_allowed": False,
                "version": 1,
            }
        )
    rows.extend(
        [
            {
                "feature": "xP",
                "source": "official_fpl_expected_points_alias",
                "availability_rule": "forbidden as an input or fallback",
                "production_allowed": False,
                "same_gameweek_outcome_allowed": False,
                "version": 1,
            },
            {
                "feature": "ep_this",
                "source": "official_fpl_expected_points",
                "availability_rule": "forbidden as an input or fallback",
                "production_allowed": False,
                "same_gameweek_outcome_allowed": False,
                "version": 1,
            },
            {
                "feature": "ep_next",
                "source": "official_fpl_expected_points",
                "availability_rule": "forbidden as an input or fallback",
                "production_allowed": False,
                "same_gameweek_outcome_allowed": False,
                "version": 1,
            },
            {
                "feature": "target_points",
                "source": "finalized_outcome",
                "availability_rule": "label only",
                "production_allowed": False,
                "same_gameweek_outcome_allowed": True,
                "version": 1,
            },
            {
                "feature": "target_minutes",
                "source": "finalized_outcome",
                "availability_rule": "label only",
                "production_allowed": False,
                "same_gameweek_outcome_allowed": True,
                "version": 1,
            },
        ]
    )
    return write_rows(rows, FEATURE_AVAILABILITY)


def _create_team_form(connection: duckdb.DuckDBPyConnection) -> int:
    query = """
        WITH sides AS (
            SELECT
                f.season,
                f.id AS fixture_id,
                f.event,
                try_cast(f.kickoff_time AS TIMESTAMPTZ) AS kickoff_time,
                f.team_h AS team_id,
                f.team_a AS opponent_id,
                ht.code AS team_code,
                away_team.code AS opponent_code,
                1.0 AS home,
                f.team_h_score::DOUBLE AS goals_for,
                f.team_a_score::DOUBLE AS goals_against
            FROM vaastav_fixtures f
            JOIN vaastav_teams ht ON f.season = ht.season AND f.team_h = ht.id
            JOIN vaastav_teams away_team
                ON f.season = away_team.season AND f.team_a = away_team.id
            WHERE f.team_h_score IS NOT NULL AND f.team_a_score IS NOT NULL
            UNION ALL
            SELECT
                f.season,
                f.id AS fixture_id,
                f.event,
                try_cast(f.kickoff_time AS TIMESTAMPTZ) AS kickoff_time,
                f.team_a AS team_id,
                f.team_h AS opponent_id,
                away_team.code AS team_code,
                ht.code AS opponent_code,
                0.0 AS home,
                f.team_a_score::DOUBLE AS goals_for,
                f.team_h_score::DOUBLE AS goals_against
            FROM vaastav_fixtures f
            JOIN vaastav_teams ht ON f.season = ht.season AND f.team_h = ht.id
            JOIN vaastav_teams away_team
                ON f.season = away_team.season AND f.team_a = away_team.id
            WHERE f.team_h_score IS NOT NULL AND f.team_a_score IS NOT NULL
        )
        SELECT
            *,
            row_number() OVER team_window - 1 AS team_history_matches,
            date_diff(
                'day', lag(kickoff_time) OVER team_window, kickoff_time
            )::DOUBLE AS team_days_since_match,
            avg(goals_for) OVER team_5 AS team_attack5,
            avg(goals_against) OVER team_5 AS team_defence5,
            avg(goals_for) OVER team_10 AS team_attack10,
            avg(goals_against) OVER team_10 AS team_defence10
        FROM sides
        WINDOW
            team_window AS (
                PARTITION BY team_code ORDER BY kickoff_time, fixture_id
            ),
            team_5 AS (
                PARTITION BY team_code ORDER BY kickoff_time, fixture_id
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ),
            team_10 AS (
                PARTITION BY team_code ORDER BY kickoff_time, fixture_id
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            )
    """
    return _copy(connection, query, TEAM_FORM)


def _training_query() -> str:
    team_form = _sql_path(TEAM_FORM)
    adjusted_strength = _sql_path(HISTORICAL_TEAM_STRENGTH)
    return f"""
        WITH deadline_fixtures AS (
            SELECT
                season,
                try_cast(decision_event AS INTEGER) AS event,
                id AS fixture_id,
                try_cast(team_h_difficulty AS DOUBLE) AS team_h_difficulty,
                try_cast(team_a_difficulty AS DOUBLE) AS team_a_difficulty
            FROM vaastav_deadlines_fixture_snapshots
        ), player_fixture AS (
            SELECT
                g.season,
                g.element,
                g.GW AS event,
                min(g.kickoff_time) AS event_kickoff,
                any_value(p.code) AS player_code,
                any_value(g.name) AS player_name,
                CASE any_value(p.element_type)
                    WHEN 1 THEN 'GK' WHEN 2 THEN 'DEF'
                    WHEN 3 THEN 'MID' WHEN 4 THEN 'FWD'
                END AS position,
                coalesce(any_value(tn.id), any_value(p.team)) AS team_id,
                any_value(tn.code) AS team_code,
                count(DISTINCT g.fixture) AS fixture_count,
                avg(CASE WHEN g.was_home THEN 1.0 ELSE 0.0 END) AS home_fraction,
                avg(
                    CASE WHEN g.was_home
                        THEN df.team_h_difficulty ELSE df.team_a_difficulty
                    END
                ) AS fixture_difficulty,
                sum(g.total_points)::DOUBLE AS target_points,
                sum(g.minutes)::DOUBLE AS target_minutes,
                sum(coalesce(g.goals_scored, 0))::DOUBLE AS goals,
                sum(coalesce(g.assists, 0))::DOUBLE AS assists,
                sum(g.expected_goals)::DOUBLE AS xg,
                sum(g.expected_assists)::DOUBLE AS xa,
                sum(coalesce(g.bps, 0))::DOUBLE AS bps,
                sum(coalesce(g.clean_sheets, 0))::DOUBLE AS clean_sheets,
                sum(g.defensive_contribution)::DOUBLE AS defensive_contribution,
                max(g.value)::DOUBLE AS event_value,
                max(g.selected)::DOUBLE AS event_selected,
                avg(tf.team_attack5) AS team_attack5,
                avg(tf.team_defence5) AS team_defence5,
                avg(tf.team_attack10) AS team_attack10,
                avg(tf.team_defence10) AS team_defence10,
                avg(ofm.team_attack5) AS opponent_attack5,
                avg(ofm.team_defence5) AS opponent_defence5,
                max(tf.team_history_matches) AS team_history_matches,
                max(ofm.team_history_matches) AS opponent_history_matches,
                avg(tf.team_days_since_match) AS team_days_since_match,
                avg(ofm.team_days_since_match) AS opponent_days_since_match
                ,avg(dr.adjusted_team_attack) AS adjusted_team_attack
                ,avg(dr.adjusted_team_defence) AS adjusted_team_defence
                ,avg(dr.adjusted_team_venue_attack) AS adjusted_team_venue_attack
                ,avg(dr.adjusted_team_venue_defence) AS adjusted_team_venue_defence
                ,avg(dr.adjusted_opponent_attack) AS adjusted_opponent_attack
                ,avg(dr.adjusted_opponent_defence) AS adjusted_opponent_defence
                ,avg(dr.adjusted_opponent_venue_attack)
                    AS adjusted_opponent_venue_attack
                ,avg(dr.adjusted_opponent_venue_defence)
                    AS adjusted_opponent_venue_defence
                ,avg(dr.team_expected_goals) AS team_expected_goals
                ,avg(dr.team_expected_goals_against) AS team_expected_goals_against
                ,avg(dr.team_clean_sheet_probability)
                    AS team_clean_sheet_probability
                ,avg(dr.team_promoted_prior) AS team_promoted_prior
                ,avg(dr.opponent_promoted_prior) AS opponent_promoted_prior
                ,avg(dr.team_rating_matches) AS team_rating_matches
                ,avg(dr.opponent_rating_matches) AS opponent_rating_matches
                ,avg(dr.team_rating_days_since_match)
                    AS team_rating_days_since_match
                ,avg(dr.opponent_rating_days_since_match)
                    AS opponent_rating_days_since_match
            FROM vaastav_player_gameweeks g
            JOIN vaastav_players p
              ON g.season = p.season AND g.element = p.id
            LEFT JOIN vaastav_teams tn
              ON g.season = tn.season AND g.team = tn.name
            LEFT JOIN read_parquet('{team_form}') tf
              ON g.season = tf.season AND g.fixture = tf.fixture_id
             AND coalesce(tn.id, p.team) = tf.team_id
            LEFT JOIN read_parquet('{team_form}') ofm
              ON g.season = ofm.season AND g.fixture = ofm.fixture_id
             AND g.opponent_team = ofm.team_id
            LEFT JOIN read_parquet('{adjusted_strength}') dr
              ON g.season = dr.season AND g.fixture = dr.fixture_id
             AND coalesce(tn.id, p.team) = dr.team_id
            LEFT JOIN deadline_fixtures df
              ON g.season = df.season AND g.GW = df.event AND g.fixture = df.fixture_id
            WHERE p.element_type BETWEEN 1 AND 4
            GROUP BY g.season, g.element, g.GW
        ), player_history AS (
            SELECT
                *,
                row_number() OVER player_window - 1 AS history_events,
                date_diff(
                    'day', lag(event_kickoff) OVER player_window, event_kickoff
                )::DOUBLE AS player_days_since_last_event,
                lag(target_points) OVER player_window AS last_points,
                avg(target_points) OVER player_3 AS form3_points,
                avg(target_points) OVER player_5 AS form5_points,
                avg(target_points) OVER player_10 AS form10_points,
                avg(target_points) OVER player_38 AS form38_points,
                lag(target_minutes) OVER player_window AS last_minutes,
                avg(target_minutes) OVER player_3 AS form3_minutes,
                avg(target_minutes) OVER player_5 AS form5_minutes,
                avg(target_minutes) OVER player_10 AS form10_minutes,
                avg(CASE WHEN target_minutes > 0 THEN 1.0 ELSE 0.0 END)
                    OVER player_5 AS appearance_rate5,
                avg(CASE WHEN target_minutes >= 60 THEN 1.0 ELSE 0.0 END)
                    OVER player_5 AS start_rate5,
                avg(goals) OVER player_5 AS form5_goals,
                avg(assists) OVER player_5 AS form5_assists,
                avg(xg) OVER player_5 AS form5_xg,
                avg(xa) OVER player_5 AS form5_xa,
                avg(goals) OVER player_10 AS form10_goals,
                avg(assists) OVER player_10 AS form10_assists,
                avg(xg) OVER player_10 AS form10_xg,
                avg(xa) OVER player_10 AS form10_xa,
                avg(goals) OVER player_38 AS form38_goals,
                avg(assists) OVER player_38 AS form38_assists,
                avg(xg) OVER player_38 AS form38_xg,
                avg(xa) OVER player_38 AS form38_xa,
                avg(target_minutes) OVER player_38 AS form38_minutes,
                avg(bps) OVER player_5 AS form5_bps,
                avg(clean_sheets) OVER player_5 AS form5_clean_sheets,
                avg(defensive_contribution) OVER player_5
                    AS form5_defensive_contribution,
                lag(event_value) OVER player_window AS lag_value,
                lag(event_selected) OVER player_window AS lag_selected
            FROM player_fixture
            WINDOW
                player_window AS (
                    PARTITION BY player_code ORDER BY season, event
                ),
                player_3 AS (
                    PARTITION BY player_code ORDER BY season, event
                    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                ),
                player_5 AS (
                    PARTITION BY player_code ORDER BY season, event
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ),
                player_10 AS (
                    PARTITION BY player_code ORDER BY season, event
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ),
                player_38 AS (
                    PARTITION BY player_code ORDER BY season, event
                    ROWS BETWEEN 38 PRECEDING AND 1 PRECEDING
                )
        ), snapshots AS (
            SELECT
                season,
                try_cast(decision_event AS INTEGER) AS event,
                id AS element,
                try_cast(now_cost AS DOUBLE) AS now_cost,
                try_cast(selected_by_percent AS DOUBLE) AS selected_percent,
                status,
                try_cast(chance_of_playing_next_round AS DOUBLE) AS chance_next,
                try_cast(chance_of_playing_this_round AS DOUBLE) AS chance_this,
                try_cast(penalties_order AS DOUBLE) AS penalties_order,
                try_cast(corners_and_indirect_freekicks_order AS DOUBLE) AS corners_order,
                observed_at,
                deadline_at
            FROM vaastav_deadlines_player_snapshots
        )
        SELECT
            row_number() OVER (ORDER BY h.season, h.event, h.element) AS row_id,
            h.season,
            h.event AS event_number,
            h.element,
            h.player_code,
            h.player_name,
            h.position,
            h.team_id,
            h.team_code,
            h.fixture_count,
            h.home_fraction,
            h.fixture_difficulty,
            h.target_points,
            h.target_minutes,
            CASE
                WHEN h.target_minutes = 0 THEN 0
                WHEN h.target_minutes < 60 THEN 1
                WHEN h.target_minutes < 90 THEN 2
                ELSE 3
            END AS minutes_class,
            h.history_events,
            h.player_days_since_last_event,
            h.last_points,
            h.form3_points,
            h.form5_points,
            h.form10_points,
            h.form38_points,
            h.last_minutes,
            h.form3_minutes,
            h.form5_minutes,
            h.form10_minutes,
            h.appearance_rate5,
            h.start_rate5,
            h.form5_goals,
            h.form5_assists,
            h.form5_xg,
            h.form5_xa,
            h.form10_goals,
            h.form10_assists,
            h.form10_xg,
            h.form10_xa,
            h.form38_goals,
            h.form38_assists,
            h.form38_xg,
            h.form38_xa,
            h.form38_minutes,
            h.form5_bps,
            h.form5_clean_sheets,
            h.form5_defensive_contribution,
            coalesce(s.now_cost, h.lag_value) AS market_price,
            percent_rank() OVER (
                PARTITION BY h.season, h.event
                ORDER BY coalesce(s.selected_percent, h.lag_selected, 0)
            ) AS ownership_percentile,
            CASE
                WHEN s.chance_this IS NOT NULL THEN s.chance_this
                WHEN s.status = 'a' OR s.status IS NULL THEN 100.0
                WHEN s.status IN ('i', 's', 'u', 'n') THEN 0.0
                ELSE 75.0
            END AS availability_chance,
            s.penalties_order AS penalty_order,
            s.corners_order AS corner_order,
            h.team_attack5,
            h.team_defence5,
            h.team_attack10,
            h.team_defence10,
            h.opponent_attack5,
            h.opponent_defence5,
            h.team_history_matches,
            h.opponent_history_matches,
            h.team_days_since_match,
            h.opponent_days_since_match,
            h.adjusted_team_attack,
            h.adjusted_team_defence,
            h.adjusted_team_venue_attack,
            h.adjusted_team_venue_defence,
            h.adjusted_opponent_attack,
            h.adjusted_opponent_defence,
            h.adjusted_opponent_venue_attack,
            h.adjusted_opponent_venue_defence,
            h.team_expected_goals,
            h.team_expected_goals_against,
            h.team_clean_sheet_probability,
            h.team_promoted_prior,
            h.opponent_promoted_prior,
            h.team_rating_matches,
            h.opponent_rating_matches,
            h.team_rating_days_since_match,
            h.opponent_rating_days_since_match,
            CASE WHEN h.history_events = 0 THEN 1.0 ELSE 0.0 END AS cold_start,
            CASE WHEN s.element IS NOT NULL THEN 1.0 ELSE 0.0 END
                AS deadline_proxy_available,
            s.observed_at AS snapshot_observed_at,
            s.deadline_at
        FROM player_history h
        LEFT JOIN snapshots s
          ON h.season = s.season AND h.event = s.event AND h.element = s.element
        WHERE h.position IN ('GK', 'DEF', 'MID', 'FWD')
    """


def _current_history_sql() -> str:
    """Return a schema-stable current-season history source.

    Before GW1 there is intentionally no event history. After every finalized
    event, ``collect-event-outcome`` creates the normalized parquet and this
    branch makes xG/xA/minutes/points advance with the live season.
    """
    if CURRENT_PLAYER_HISTORY.is_file():
        current_history = _sql_path(CURRENT_PLAYER_HISTORY)
        return f"""
            SELECT
                season,
                element,
                event,
                cast(event_kickoff AS TIMESTAMPTZ) AS event_kickoff,
                player_code,
                points,
                minutes,
                goals,
                assists,
                xg,
                xa,
                bps,
                clean_sheets,
                defensive_contribution
            FROM read_parquet('{current_history}')
        """
    return """
        SELECT
            cast(NULL AS VARCHAR) AS season,
            cast(NULL AS BIGINT) AS element,
            cast(NULL AS BIGINT) AS event,
            cast(NULL AS TIMESTAMPTZ) AS event_kickoff,
            cast(NULL AS BIGINT) AS player_code,
            cast(NULL AS DOUBLE) AS points,
            cast(NULL AS DOUBLE) AS minutes,
            cast(NULL AS DOUBLE) AS goals,
            cast(NULL AS DOUBLE) AS assists,
            cast(NULL AS DOUBLE) AS xg,
            cast(NULL AS DOUBLE) AS xa,
            cast(NULL AS DOUBLE) AS bps,
            cast(NULL AS DOUBLE) AS clean_sheets,
            cast(NULL AS DOUBLE) AS defensive_contribution
        WHERE false
    """


def _current_query(horizon: int, *, start_event: int = 1) -> str:
    if not 1 <= start_event <= 38:
        raise ValueError("start_event must be between 1 and 38")
    end_event = min(38, start_event + horizon - 1)
    team_form = _sql_path(TEAM_FORM)
    adjusted_strength = _sql_path(CURRENT_TEAM_STRENGTH)
    current_history = _current_history_sql()
    return f"""
        WITH historical_player_events AS (
            SELECT
                g.season,
                g.element,
                g.GW AS event,
                min(g.kickoff_time) AS event_kickoff,
                any_value(p.code) AS player_code,
                sum(g.total_points)::DOUBLE AS points,
                sum(g.minutes)::DOUBLE AS minutes,
                sum(coalesce(g.goals_scored, 0))::DOUBLE AS goals,
                sum(coalesce(g.assists, 0))::DOUBLE AS assists,
                sum(g.expected_goals)::DOUBLE AS xg,
                sum(g.expected_assists)::DOUBLE AS xa,
                sum(coalesce(g.bps, 0))::DOUBLE AS bps,
                sum(coalesce(g.clean_sheets, 0))::DOUBLE AS clean_sheets,
                sum(g.defensive_contribution)::DOUBLE AS defensive_contribution
            FROM vaastav_player_gameweeks g
            JOIN vaastav_players p
              ON g.season = p.season AND g.element = p.id
            GROUP BY g.season, g.element, g.GW
        ), current_player_events AS (
            {current_history}
        ), all_player_events AS (
            SELECT * FROM historical_player_events
            UNION ALL
            SELECT * FROM current_player_events
        ), ranked_history AS (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY player_code
                    ORDER BY event_kickoff DESC, season DESC, event DESC
                ) AS recency
            FROM all_player_events
        ), player_prior AS (
            SELECT
                player_code,
                count(*) AS history_events,
                max(points) FILTER (WHERE recency = 1) AS last_points,
                max(minutes) FILTER (WHERE recency = 1) AS last_minutes,
                max(event_kickoff) FILTER (WHERE recency = 1) AS last_event_kickoff,
                avg(points) FILTER (WHERE recency <= 3) AS form3_points,
                avg(points) FILTER (WHERE recency <= 5) AS form5_points,
                avg(points) FILTER (WHERE recency <= 10) AS form10_points,
                avg(points) FILTER (WHERE recency <= 38) AS form38_points,
                avg(minutes) FILTER (WHERE recency <= 3) AS form3_minutes,
                avg(minutes) FILTER (WHERE recency <= 5) AS form5_minutes,
                avg(minutes) FILTER (WHERE recency <= 10) AS form10_minutes,
                avg(CASE WHEN minutes > 0 THEN 1.0 ELSE 0.0 END)
                    FILTER (WHERE recency <= 5) AS appearance_rate5,
                avg(CASE WHEN minutes >= 60 THEN 1.0 ELSE 0.0 END)
                    FILTER (WHERE recency <= 5) AS start_rate5,
                avg(goals) FILTER (WHERE recency <= 5) AS form5_goals,
                avg(assists) FILTER (WHERE recency <= 5) AS form5_assists,
                avg(xg) FILTER (WHERE recency <= 5) AS form5_xg,
                avg(xa) FILTER (WHERE recency <= 5) AS form5_xa,
                avg(goals) FILTER (WHERE recency <= 10) AS form10_goals,
                avg(assists) FILTER (WHERE recency <= 10) AS form10_assists,
                avg(xg) FILTER (WHERE recency <= 10) AS form10_xg,
                avg(xa) FILTER (WHERE recency <= 10) AS form10_xa,
                avg(goals) FILTER (WHERE recency <= 38) AS form38_goals,
                avg(assists) FILTER (WHERE recency <= 38) AS form38_assists,
                avg(xg) FILTER (WHERE recency <= 38) AS form38_xg,
                avg(xa) FILTER (WHERE recency <= 38) AS form38_xa,
                avg(minutes) FILTER (WHERE recency <= 38) AS form38_minutes,
                avg(bps) FILTER (WHERE recency <= 5) AS form5_bps,
                avg(clean_sheets) FILTER (WHERE recency <= 5) AS form5_clean_sheets,
                avg(defensive_contribution) FILTER (WHERE recency <= 5)
                    AS form5_defensive_contribution
            FROM ranked_history GROUP BY player_code
        ), latest_team_form AS (
            SELECT * EXCLUDE (recent_rank) FROM (
                SELECT
                    team_code,
                    kickoff_time AS last_kickoff_time,
                    team_history_matches + 1 AS team_history_matches,
                    avg(goals_for) OVER final_5 AS team_attack5,
                    avg(goals_against) OVER final_5 AS team_defence5,
                    avg(goals_for) OVER final_10 AS team_attack10,
                    avg(goals_against) OVER final_10 AS team_defence10,
                    row_number() OVER (
                        PARTITION BY team_code ORDER BY kickoff_time DESC, fixture_id DESC
                    ) AS recent_rank
                FROM read_parquet('{team_form}')
                WINDOW
                    final_5 AS (
                        PARTITION BY team_code ORDER BY kickoff_time, fixture_id
                        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ),
                    final_10 AS (
                        PARTITION BY team_code ORDER BY kickoff_time, fixture_id
                        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                    )
            ) WHERE recent_rank = 1
        ), current_fixture_sides AS (
            SELECT
                f.event,
                f.id AS fixture_id,
                try_cast(f.kickoff_time AS TIMESTAMPTZ) AS kickoff_time,
                f.team_h AS team_id,
                f.team_a AS opponent_id,
                1.0 AS home,
                f.team_h_difficulty::DOUBLE AS difficulty
            FROM fpl_current_fixtures f
            WHERE f.event BETWEEN {start_event} AND {end_event}
            UNION ALL
            SELECT
                f.event,
                f.id AS fixture_id,
                try_cast(f.kickoff_time AS TIMESTAMPTZ) AS kickoff_time,
                f.team_a AS team_id,
                f.team_h AS opponent_id,
                0.0 AS home,
                f.team_a_difficulty::DOUBLE AS difficulty
            FROM fpl_current_fixtures f
            WHERE f.event BETWEEN {start_event} AND {end_event}
        ), current_team_events AS (
            SELECT
                fs.event,
                fs.team_id,
                min(fs.kickoff_time) AS event_kickoff,
                count(*) AS fixture_count,
                avg(fs.home) AS home_fraction,
                avg(fs.difficulty) AS fixture_difficulty,
                avg(tf.team_attack5) AS team_attack5,
                avg(tf.team_defence5) AS team_defence5,
                avg(tf.team_attack10) AS team_attack10,
                avg(tf.team_defence10) AS team_defence10,
                avg(ofm.team_attack5) AS opponent_attack5,
                avg(ofm.team_defence5) AS opponent_defence5,
                max(tf.team_history_matches) AS team_history_matches,
                max(ofm.team_history_matches) AS opponent_history_matches,
                avg(date_diff('day', tf.last_kickoff_time, fs.kickoff_time))::DOUBLE
                    AS team_days_since_match,
                avg(date_diff('day', ofm.last_kickoff_time, fs.kickoff_time))::DOUBLE
                    AS opponent_days_since_match,
                avg(dr.adjusted_team_attack) AS adjusted_team_attack,
                avg(dr.adjusted_team_defence) AS adjusted_team_defence,
                avg(dr.adjusted_team_venue_attack) AS adjusted_team_venue_attack,
                avg(dr.adjusted_team_venue_defence) AS adjusted_team_venue_defence,
                avg(dr.adjusted_opponent_attack) AS adjusted_opponent_attack,
                avg(dr.adjusted_opponent_defence) AS adjusted_opponent_defence,
                avg(dr.adjusted_opponent_venue_attack)
                    AS adjusted_opponent_venue_attack,
                avg(dr.adjusted_opponent_venue_defence)
                    AS adjusted_opponent_venue_defence,
                avg(dr.team_expected_goals) AS team_expected_goals,
                avg(dr.team_expected_goals_against) AS team_expected_goals_against,
                avg(dr.team_clean_sheet_probability)
                    AS team_clean_sheet_probability,
                avg(dr.team_promoted_prior) AS team_promoted_prior,
                avg(dr.opponent_promoted_prior) AS opponent_promoted_prior,
                avg(dr.team_rating_matches) AS team_rating_matches,
                avg(dr.opponent_rating_matches) AS opponent_rating_matches,
                avg(dr.team_rating_days_since_match)
                    AS team_rating_days_since_match,
                avg(dr.opponent_rating_days_since_match)
                    AS opponent_rating_days_since_match
            FROM current_fixture_sides fs
            JOIN fpl_current_teams ct ON fs.team_id = ct.id
            JOIN fpl_current_teams ot ON fs.opponent_id = ot.id
            LEFT JOIN latest_team_form tf ON ct.code = tf.team_code
            LEFT JOIN latest_team_form ofm ON ot.code = ofm.team_code
            LEFT JOIN read_parquet('{adjusted_strength}') dr
              ON fs.fixture_id = dr.fixture_id AND fs.team_id = dr.team_id
            GROUP BY fs.event, fs.team_id
        ), horizons AS (
            SELECT unnest(generate_series({start_event}, {end_event})) AS event_number
        )
        SELECT
            row_number() OVER (ORDER BY h.event_number, p.id) AS row_id,
            '2026-27' AS season,
            h.event_number,
            p.id AS element,
            p.code AS player_code,
            coalesce(nullif(trim(p.known_name), ''), p.web_name) AS player_name,
            CASE p.element_type
                WHEN 1 THEN 'GK' WHEN 2 THEN 'DEF'
                WHEN 3 THEN 'MID' WHEN 4 THEN 'FWD'
            END AS position,
            p.team AS team_id,
            t.code AS team_code,
            t.name AS team_name,
            t.short_name AS team_short_name,
            coalesce(te.fixture_count, 0)::DOUBLE AS fixture_count,
            coalesce(te.home_fraction, 0)::DOUBLE AS home_fraction,
            te.fixture_difficulty,
            coalesce(pp.history_events, 0)::DOUBLE AS history_events,
            date_diff(
                'day', pp.last_event_kickoff, te.event_kickoff
            )::DOUBLE AS player_days_since_last_event,
            pp.last_points,
            pp.form3_points,
            pp.form5_points,
            pp.form10_points,
            pp.form38_points,
            pp.last_minutes,
            pp.form3_minutes,
            pp.form5_minutes,
            pp.form10_minutes,
            pp.appearance_rate5,
            pp.start_rate5,
            pp.form5_goals,
            pp.form5_assists,
            pp.form5_xg,
            pp.form5_xa,
            pp.form10_goals,
            pp.form10_assists,
            pp.form10_xg,
            pp.form10_xa,
            pp.form38_goals,
            pp.form38_assists,
            pp.form38_xg,
            pp.form38_xa,
            pp.form38_minutes,
            pp.form5_bps,
            pp.form5_clean_sheets,
            pp.form5_defensive_contribution,
            p.now_cost::DOUBLE AS market_price,
            percent_rank() OVER (
                PARTITION BY h.event_number
                ORDER BY coalesce(try_cast(p.selected_by_percent AS DOUBLE), 0)
            ) AS ownership_percentile,
            CASE
                WHEN h.event_number = 1 AND p.chance_of_playing_this_round IS NOT NULL
                    THEN p.chance_of_playing_this_round::DOUBLE
                WHEN h.event_number <= 2 AND p.chance_of_playing_next_round IS NOT NULL
                    THEN p.chance_of_playing_next_round::DOUBLE
                WHEN p.status = 'a' OR p.status IS NULL THEN 100.0
                WHEN h.event_number > 3 THEN 85.0
                WHEN p.status IN ('i', 's', 'u', 'n') THEN 0.0
                ELSE 75.0
            END AS availability_chance,
            p.penalties_order::DOUBLE AS penalty_order,
            p.corners_and_indirect_freekicks_order::DOUBLE AS corner_order,
            te.team_attack5,
            te.team_defence5,
            te.team_attack10,
            te.team_defence10,
            te.opponent_attack5,
            te.opponent_defence5,
            te.team_history_matches,
            te.opponent_history_matches,
            te.team_days_since_match,
            te.opponent_days_since_match,
            te.adjusted_team_attack,
            te.adjusted_team_defence,
            te.adjusted_team_venue_attack,
            te.adjusted_team_venue_defence,
            te.adjusted_opponent_attack,
            te.adjusted_opponent_defence,
            te.adjusted_opponent_venue_attack,
            te.adjusted_opponent_venue_defence,
            te.team_expected_goals,
            te.team_expected_goals_against,
            te.team_clean_sheet_probability,
            te.team_promoted_prior,
            te.opponent_promoted_prior,
            te.team_rating_matches,
            te.opponent_rating_matches,
            te.team_rating_days_since_match,
            te.opponent_rating_days_since_match,
            CASE WHEN pp.player_code IS NULL THEN 1.0 ELSE 0.0 END AS cold_start,
            1.0 AS deadline_proxy_available,
            p.status,
            p.news,
            p.snapshot_at,
            p.can_select,
            p.removed
        FROM fpl_current_players p
        JOIN fpl_current_teams t ON p.team = t.id
        CROSS JOIN horizons h
        LEFT JOIN player_prior pp ON p.code = pp.player_code
        LEFT JOIN current_team_events te
          ON h.event_number = te.event AND p.team = te.team_id
        WHERE p.element_type BETWEEN 1 AND 4
          AND coalesce(p.can_select, true)
          AND NOT coalesce(p.removed, false)
        ORDER BY h.event_number, p.id
    """


def build(horizon: int = 8) -> dict:
    if not 1 <= horizon <= 38:
        raise ValueError("horizon must be between 1 and 38")
    ensure_engine_layout()
    connection = duckdb.connect(str(DATABASE), read_only=True)
    try:
        start_event = int(
            connection.execute(
                """
                SELECT coalesce(
                    min(id) FILTER (WHERE NOT coalesce(finished, false)),
                    max(id)
                )
                FROM fpl_current_events
                """
            ).fetchone()[0]
        )
    finally:
        connection.close()
    end_event = min(38, start_event + horizon - 1)
    # Team ratings need every completed result before the furthest requested
    # event even though forecasts only emit the forward event window.
    strength = build_team_strength(end_event)
    connection = duckdb.connect(str(DATABASE), read_only=True)
    try:
        team_rows = _create_team_form(connection)
        training_rows = _copy(connection, _training_query(), TRAINING_FEATURES)
        current_rows = _copy(
            connection,
            _current_query(horizon, start_event=start_event),
            CURRENT_FEATURES,
        )
        live_contract = audit_live_feature_contract(
            connection,
            current_features_path=CURRENT_FEATURES,
            start_event=start_event,
            end_event=end_event,
        )
    finally:
        connection.close()
    registry_rows = _feature_registry()
    return {
        "team_form_rows": team_rows,
        "training_rows": training_rows,
        "current_rows": current_rows,
        "feature_registry_rows": registry_rows,
        "team_strength": {
            "algorithm": strength["algorithm"],
            "frozen_test": strength["frozen_test"],
            "parameters": strength["parameters"],
        },
        "live_feature_contract": {
            "status": live_contract["status"],
            "publishable": live_contract["publishable"],
            "finalized_events": live_contract["finalized_events"],
        },
        "horizon": horizon,
        "start_event": start_event,
        "end_event": end_event,
    }


def table(path: Path) -> pa.Table:
    return pq.read_table(path)
