from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from fplagent_data.event_outcomes import (
    CURRENT_PLAYER_HISTORY,
    CURRENT_PLAYER_HISTORY_RECEIPT,
    LIVE_STAT_FIELDS,
)
from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS

from .team_strength import CURRENT_TEAM_STRENGTH

LIVE_FEATURE_CONTRACT = MANIFESTS / "fpl-live-feature-contract.json"


class LiveFeatureContractError(ValueError):
    """Current football inputs cannot safely support a forecast rebuild."""


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def audit_live_feature_contract(
    connection: duckdb.DuckDBPyConnection,
    *,
    current_features_path: Path,
    start_event: int,
    end_event: int,
    player_history_path: Path = CURRENT_PLAYER_HISTORY,
    player_history_receipt_path: Path = CURRENT_PLAYER_HISTORY_RECEIPT,
    team_strength_path: Path = CURRENT_TEAM_STRENGTH,
    output_path: Path = LIVE_FEATURE_CONTRACT,
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    """Prove live xG/xA/results are complete and reached the forecast matrix."""
    finalized = [
        int(row[0])
        for row in connection.execute(
            """
            SELECT id FROM fpl_current_events
            WHERE coalesce(finished, false) AND coalesce(data_checked, false)
            ORDER BY id
            """
        ).fetchall()
    ]
    awaiting_data_check = [
        int(row[0])
        for row in connection.execute(
            """
            SELECT id FROM fpl_current_events
            WHERE coalesce(finished, false) AND NOT coalesce(data_checked, false)
            ORDER BY id
            """
        ).fetchall()
    ]
    issues: list[str] = []
    checks: dict[str, Any] = {}
    history_receipt: dict[str, Any] | None = None

    checks["official_event_finality"] = {
        "finalized_events": finalized,
        "awaiting_data_check": awaiting_data_check,
        "passed": not awaiting_data_check,
    }
    if awaiting_data_check:
        issues.append(
            "finished official events are still awaiting FPL's data-checked flag"
        )

    event_columns = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'fpl_current_events'
            """
        ).fetchall()
    }
    live_current_events = (
        [
            int(row[0])
            for row in connection.execute(
                """
                SELECT id FROM fpl_current_events
                WHERE coalesce(is_current, false)
                  AND NOT coalesce(data_checked, false)
                ORDER BY id
                """
            ).fetchall()
        ]
        if "is_current" in event_columns
        else []
    )

    expected_grid = list(range(start_event, end_event + 1))
    actual_grid = sorted(
        {
            int(row[0])
            for row in connection.execute(
                "SELECT DISTINCT event_number FROM read_parquet(?) ORDER BY 1",
                [str(current_features_path)],
            ).fetchall()
        }
    )
    checks["forecast_event_grid"] = {
        "expected": expected_grid,
        "actual": actual_grid,
        "passed": actual_grid == expected_grid,
    }
    if actual_grid != expected_grid:
        issues.append("current forecast feature grid is not the requested forward horizon")

    if not finalized:
        checks["current_player_history"] = {
            "required": False,
            "passed": True,
            "reason": "No 2026/27 event is final and data-checked yet.",
        }
    else:
        if not player_history_path.is_file() or not player_history_receipt_path.is_file():
            issues.append("finalized events exist but normalized current player history is missing")
        else:
            try:
                history_receipt = json.loads(
                    player_history_receipt_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                issues.append("current player history receipt is unreadable")
            if history_receipt is not None:
                receipt_events = [int(value) for value in history_receipt.get("events", [])]
                receipt_hash = history_receipt.get("output_sha256")
                actual_hash = sha256_file(player_history_path)
                if receipt_events != finalized:
                    issues.append(
                        "current player history does not cover exactly the finalized events"
                    )
                if history_receipt.get("status") != "ready":
                    issues.append("current player history receipt is not ready")
                if receipt_hash != actual_hash:
                    issues.append("current player history bytes differ from their receipt")

                schema = set(pq.read_schema(player_history_path).names)
                required_columns = {
                    "event",
                    "player_code",
                    "event_kickoff",
                    *LIVE_STAT_FIELDS.keys(),
                }
                missing_columns = sorted(required_columns - schema)
                if missing_columns:
                    issues.append(
                        f"current player history is missing columns: {missing_columns}"
                    )
                else:
                    escaped_history = str(player_history_path.resolve()).replace("'", "''")
                    coverage = connection.execute(
                        f"""
                        SELECT
                            count(*)::BIGINT AS rows,
                            count(xg)::BIGINT AS xg_rows,
                            count(xa)::BIGINT AS xa_rows,
                            count(minutes)::BIGINT AS minute_rows,
                            count(points)::BIGINT AS point_rows
                        FROM read_parquet('{escaped_history}')
                        """
                    ).fetchone()
                    checks["event_live_coverage"] = {
                        "rows": coverage[0],
                        "xg_rows": coverage[1],
                        "xa_rows": coverage[2],
                        "minute_rows": coverage[3],
                        "point_rows": coverage[4],
                        "passed": len(set(coverage)) == 1 and coverage[0] > 0,
                    }
                    if not checks["event_live_coverage"]["passed"]:
                        issues.append("event-live xG/xA/minutes/points coverage is incomplete")

                    # Reconcile the normalized event stream to FPL's current
                    # cumulative totals. A small xG/xA tolerance allows source
                    # rounding but not a missing event or schema drift.
                    mismatches = connection.execute(
                        f"""
                        WITH actual AS (
                            SELECT
                                player_code,
                                sum(points) AS points,
                                sum(minutes) AS minutes,
                                sum(xg) AS xg,
                                sum(xa) AS xa
                            FROM read_parquet('{escaped_history}')
                            GROUP BY player_code
                        )
                        SELECT count(*)
                        FROM actual a
                        JOIN fpl_current_players p ON a.player_code = p.code
                        WHERE abs(a.points - p.total_points) > 0.001
                           OR abs(a.minutes - p.minutes) > 0.001
                           OR abs(a.xg - try_cast(p.expected_goals AS DOUBLE)) > 0.05
                           OR abs(a.xa - try_cast(p.expected_assists AS DOUBLE)) > 0.05
                        """
                    ).fetchone()[0]
                    prefix_violations = 0
                    if live_current_events:
                        prefix_violations = connection.execute(
                            f"""
                            WITH actual AS (
                                SELECT
                                    player_code,
                                    sum(minutes) AS minutes,
                                    sum(xg) AS xg,
                                    sum(xa) AS xa
                                FROM read_parquet('{escaped_history}')
                                GROUP BY player_code
                            )
                            SELECT count(*)
                            FROM actual a
                            JOIN fpl_current_players p ON a.player_code = p.code
                            WHERE a.minutes - p.minutes > 0.001
                               OR a.xg - try_cast(p.expected_goals AS DOUBLE) > 0.05
                               OR a.xa - try_cast(p.expected_assists AS DOUBLE) > 0.05
                            """
                        ).fetchone()[0]
                    reconciliation_passed = (
                        prefix_violations == 0 if live_current_events else mismatches == 0
                    )
                    checks["official_cumulative_reconciliation"] = {
                        "mode": (
                            "finalized_history_is_prefix_of_live_cumulative"
                            if live_current_events
                            else "exact_finalized_cumulative"
                        ),
                        "current_unfinalized_events": live_current_events,
                        "mismatched_players": int(mismatches),
                        "prefix_violations": int(prefix_violations),
                        "exact_match": mismatches == 0,
                        "xg_xa_tolerance": 0.05,
                        "passed": reconciliation_passed,
                    }
                    if not reconciliation_passed:
                        issues.append(
                            "event-live history does not reconcile to official cumulative totals"
                        )

                    escaped_features = str(current_features_path.resolve()).replace("'", "''")
                    latest_mismatches = connection.execute(
                        f"""
                        WITH latest AS (
                            SELECT * EXCLUDE (recent_rank) FROM (
                                SELECT
                                    player_code,
                                    points,
                                    row_number() OVER (
                                        PARTITION BY player_code
                                        ORDER BY event DESC
                                    ) AS recent_rank
                                FROM read_parquet('{escaped_history}')
                            ) WHERE recent_rank = 1
                        ), feature_player AS (
                            SELECT player_code, any_value(last_points) AS last_points
                            FROM read_parquet('{escaped_features}')
                            GROUP BY player_code
                        )
                        SELECT count(*) FROM latest l
                        JOIN feature_player f USING (player_code)
                        WHERE abs(l.points - f.last_points) > 0.001
                        """
                    ).fetchone()[0]
                    checks["history_reached_forecast_features"] = {
                        "latest_point_mismatches": int(latest_mismatches),
                        "passed": latest_mismatches == 0,
                    }
                    if latest_mismatches:
                        issues.append(
                            "normalized live history did not reach current rolling features"
                        )

    if not team_strength_path.is_file():
        issues.append("current opponent-adjusted team strength is missing")
    else:
        escaped_strength = str(team_strength_path.resolve()).replace("'", "''")
        strength_events = [
            int(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT event FROM read_parquet('{escaped_strength}') ORDER BY 1"
            ).fetchall()
        ]
        checks["team_strength_event_grid"] = {
            "expected": expected_grid,
            "actual": strength_events,
            "passed": set(expected_grid).issubset(strength_events),
        }
        if not set(expected_grid).issubset(strength_events):
            issues.append("current team-strength rows do not cover the forward horizon")

    receipt = {
        "contract_version": 1,
        "season": "2026-27",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "ready" if not issues else "blocked",
        "publishable": not issues,
        "start_event": start_event,
        "end_event": end_event,
        "finalized_events": finalized,
        "awaiting_data_check_events": awaiting_data_check,
        "required_live_features": list(LIVE_STAT_FIELDS),
        "checks": checks,
        "issues": issues,
        "artifacts": {
            "current_features": str(current_features_path),
            "current_features_sha256": sha256_file(current_features_path),
            "current_player_history": (
                str(player_history_path) if player_history_path.is_file() else None
            ),
            "current_player_history_sha256": (
                sha256_file(player_history_path)
                if player_history_path.is_file()
                else None
            ),
            "current_team_strength": str(team_strength_path),
            "current_team_strength_sha256": (
                sha256_file(team_strength_path) if team_strength_path.is_file() else None
            ),
        },
    }
    _atomic_json(output_path, receipt)
    if issues and raise_on_failure:
        raise LiveFeatureContractError("; ".join(issues))
    return receipt
