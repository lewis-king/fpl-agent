from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import duckdb

from .features import (
    CURRENT_FEATURES,
    FEATURE_AVAILABILITY,
    MODEL_FEATURES,
    TRAINING_FEATURES,
)
from .paths import NORMALIZED, REPORTS, ensure_engine_layout
from .team_strength import CURRENT_TEAM_STRENGTH, HISTORICAL_TEAM_STRENGTH

QUALITY_JSON = NORMALIZED / "data_quality.json"
QUALITY_REPORT = REPORTS / "data-quality.md"


def _sql_path(path: object) -> str:
    return str(path).replace("'", "''")


def audit_features(expected_horizon: int = 8) -> dict[str, Any]:
    """Run hard, reproducible gates over the model-ready feature contract."""
    ensure_engine_layout()
    historical = _sql_path(TRAINING_FEATURES.resolve())
    current = _sql_path(CURRENT_FEATURES.resolve())
    registry = _sql_path(FEATURE_AVAILABILITY.resolve())
    historical_strength = _sql_path(HISTORICAL_TEAM_STRENGTH.resolve())
    current_strength = _sql_path(CURRENT_TEAM_STRENGTH.resolve())
    deadlines = _sql_path(
        (
            TRAINING_FEATURES.parents[2]
            / "processed"
            / "vaastav_deadlines"
            / "player_snapshots.parquet"
        ).resolve()
    )
    connection = duckdb.connect()

    def scalar(query: str) -> Any:
        return connection.execute(query).fetchone()[0]

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, value: Any, expectation: str) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "value": value,
                "expectation": expectation,
            }
        )

    try:
        historical_rows = scalar(
            f"SELECT count(*) FROM read_parquet('{historical}')"
        )
        check("historical_row_volume", historical_rows >= 200_000, historical_rows, ">=200000")

        duplicate_history = scalar(
            f"""
            SELECT count(*) FROM (
                SELECT season, event_number, element
                FROM read_parquet('{historical}')
                GROUP BY ALL HAVING count(*) > 1
            )
            """
        )
        check("historical_unique_keys", duplicate_history == 0, duplicate_history, "0")

        null_codes = scalar(
            f"SELECT count(*) FROM read_parquet('{historical}') WHERE player_code IS NULL"
        )
        check("historical_player_identity", null_codes == 0, null_codes, "0 null codes")

        lag_mismatches = scalar(
            f"""
            WITH expected AS (
                SELECT *, lag(target_points) OVER (
                    PARTITION BY player_code ORDER BY season, event_number
                ) AS expected_last_points
                FROM read_parquet('{historical}')
            )
            SELECT count(*) FROM expected
            WHERE history_events > 0
              AND last_points IS DISTINCT FROM expected_last_points
            """
        )
        check("last_points_strictly_lagged", lag_mismatches == 0, lag_mismatches, "0 mismatches")

        form_mismatches = scalar(
            f"""
            WITH expected AS (
                SELECT *, avg(target_points) OVER (
                    PARTITION BY player_code ORDER BY season, event_number
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) AS expected_form5
                FROM read_parquet('{historical}')
            )
            SELECT count(*) FROM expected
            WHERE form5_points IS DISTINCT FROM expected_form5
            """
        )
        check("form5_excludes_target_event", form_mismatches == 0, form_mismatches, "0 mismatches")

        late_snapshots = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{deadlines}')
            WHERE try_cast(observed_at AS TIMESTAMPTZ) >= deadline_at
            """
        )
        check("snapshots_precede_deadlines", late_snapshots == 0, late_snapshots, "0 late snapshots")

        false_historical_xg = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{historical}')
            WHERE season < '2022-23' AND form5_xg IS NOT NULL
            """
        )
        check(
            "unavailable_xg_remains_missing",
            false_historical_xg == 0,
            false_historical_xg,
            "0 synthetic pre-2022/23 values",
        )

        duplicate_current = scalar(
            f"""
            SELECT count(*) FROM (
                SELECT event_number, element FROM read_parquet('{current}')
                GROUP BY ALL HAVING count(*) > 1
            )
            """
        )
        check("current_unique_keys", duplicate_current == 0, duplicate_current, "0")

        current_players, current_rows, horizon = connection.execute(
            f"""
            SELECT count(DISTINCT element), count(*), max(event_number)
            FROM read_parquet('{current}')
            """
        ).fetchone()
        complete_grid = current_rows == current_players * expected_horizon
        check(
            "current_player_horizon_grid",
            complete_grid and horizon == expected_horizon,
            {"players": current_players, "rows": current_rows, "horizon": horizon},
            f"players x {expected_horizon}",
        )

        required_missing = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{current}')
            WHERE element IS NULL OR player_code IS NULL OR team_id IS NULL
               OR market_price IS NULL OR fixture_difficulty IS NULL
               OR player_name IS NULL OR trim(player_name) = ''
            """
        )
        check("current_required_fields", required_missing == 0, required_missing, "0 missing")

        duplicate_ratings = scalar(
            f"""
            SELECT count(*) FROM (
                SELECT season, fixture_id, team_id
                FROM read_parquet('{historical_strength}')
                GROUP BY ALL HAVING count(*) > 1
            )
            """
        )
        check(
            "adjusted_rating_unique_keys",
            duplicate_ratings == 0,
            duplicate_ratings,
            "0",
        )

        late_ratings = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{historical_strength}')
            WHERE try_cast(rating_at AS TIMESTAMPTZ)
               >= try_cast(kickoff_time AS TIMESTAMPTZ)
            """
        )
        check(
            "adjusted_ratings_precede_kickoff",
            late_ratings == 0,
            late_ratings,
            "0 late ratings",
        )

        inconsistent_event_snapshots = scalar(
            f"""
            SELECT count(*) FROM (
                SELECT season, event
                FROM read_parquet('{historical_strength}')
                GROUP BY ALL HAVING count(DISTINCT rating_at) > 1
            )
            """
        )
        check(
            "one_information_set_per_event",
            inconsistent_event_snapshots == 0,
            inconsistent_event_snapshots,
            "0 events with mixed information cutoffs",
        )

        missing_current_ratings = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{current}')
            WHERE adjusted_team_attack IS NULL
               OR adjusted_team_defence IS NULL
               OR adjusted_opponent_attack IS NULL
               OR adjusted_opponent_defence IS NULL
               OR team_expected_goals IS NULL
               OR team_expected_goals_against IS NULL
               OR team_clean_sheet_probability IS NULL
            """
        )
        check(
            "current_adjusted_rating_coverage",
            missing_current_ratings == 0,
            missing_current_ratings,
            "0 missing player-horizon ratings",
        )

        invalid_probabilities = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{current_strength}')
            WHERE team_clean_sheet_probability < 0
               OR team_clean_sheet_probability > 1
               OR team_expected_goals <= 0
               OR team_expected_goals_against <= 0
            """
        )
        check(
            "adjusted_rating_probability_bounds",
            invalid_probabilities == 0,
            invalid_probabilities,
            "0 invalid expectations",
        )

        entrant_prior_misses = scalar(
            f"""
            WITH previous AS (
                SELECT DISTINCT team_code
                FROM read_parquet('{historical_strength}')
                WHERE season = '2025-26'
            ), entrants AS (
                SELECT DISTINCT team_id
                FROM read_parquet('{current_strength}')
                WHERE team_code NOT IN (SELECT team_code FROM previous)
            )
            SELECT count(*) FROM read_parquet('{current_strength}') r
            JOIN entrants e ON r.team_id = e.team_id
            WHERE r.team_promoted_prior <> 1
            """
        )
        check(
            "promoted_and_returning_club_priors",
            entrant_prior_misses == 0,
            entrant_prior_misses,
            "0 entrant fixture-sides without a promoted prior",
        )

        official_in_model = "fixture_difficulty" in MODEL_FEATURES
        check(
            "official_difficulty_excluded_from_challenger",
            not official_in_model,
            official_in_model,
            "false",
        )

        min_ownership, max_ownership = connection.execute(
            f"""
            SELECT min(ownership_percentile), max(ownership_percentile)
            FROM read_parquet('{historical}')
            """
        ).fetchone()
        ownership_valid = min_ownership >= 0.0 and max_ownership <= 1.0
        check(
            "ownership_scale",
            ownership_valid,
            {"min": min_ownership, "max": max_ownership},
            "within [0,1] for every season",
        )

        forbidden_allowed = scalar(
            f"""
            SELECT count(*) FROM read_parquet('{registry}')
            WHERE production_allowed
              AND feature IN ('target_points', 'target_minutes', 'minutes_class', 'xP')
            """
        )
        check("feature_allowlist_has_no_targets", forbidden_allowed == 0, forbidden_allowed, "0")

        position_counts = dict(
            connection.execute(
                f"""
                SELECT position, count(DISTINCT element)
                FROM read_parquet('{current}') GROUP BY position
                """
            ).fetchall()
        )
        required_positions = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
        positions_valid = all(
            position_counts.get(position, 0) >= required
            for position, required in required_positions.items()
        )
        check("selectable_position_pool", positions_valid, position_counts, "at least 2/5/5/3")

        promoted_or_stale = [
            {"team": team, "days_since_match": gap}
            for team, gap in connection.execute(
                f"""
                SELECT team_name, min(team_days_since_match)
                FROM read_parquet('{current}')
                GROUP BY team_name
                HAVING min(team_days_since_match) > 250
                    OR min(team_days_since_match) IS NULL
                ORDER BY team_name
                """
            ).fetchall()
        ]
        snapshot_coverage = connection.execute(
            f"""
            SELECT season, count(DISTINCT decision_event)
            FROM read_parquet('{deadlines}') GROUP BY season ORDER BY season
            """
        ).fetchall()
    finally:
        connection.close()

    failures = [item for item in checks if not item["passed"]]
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failed_checks": [item["name"] for item in failures],
        "observations": {
            "legacy_raw_form_gaps": promoted_or_stale,
            "deadline_proxy_events": [
                {"season": season, "events": events}
                for season, events in snapshot_coverage
            ],
        },
    }
    QUALITY_JSON.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    report_lines = [
        "# Model data quality gate",
        "",
        f"Status: **{result['status'].upper()}** · generated {result['created_at']}",
        "",
        "| Check | Result | Value | Expectation |",
        "| --- | --- | --- | --- |",
    ]
    report_lines.extend(
        f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | "
        f"`{json.dumps(item['value'], default=str)}` | {item['expectation']} |"
        for item in checks
    )
    report_lines.extend(
        [
            "",
            "## Legacy raw-form gaps (diagnostic only)",
            "",
            *[
                f"- {item['team']}: prior gap `{item['days_since_match']}` days; "
                "the production challenger replaces this gap with the validated "
                "opponent-adjusted promoted/returning-club prior."
                for item in promoted_or_stale
            ],
            "",
        ]
    )
    QUALITY_REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    if failures:
        names = ", ".join(item["name"] for item in failures)
        raise ValueError(f"Model data quality gate failed: {names}")
    return result
