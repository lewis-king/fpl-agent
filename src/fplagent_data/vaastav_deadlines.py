from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa

from .arrow import write_rows
from .catalog import sources
from .http import download, download_json
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "vaastav_deadlines"
OUT_DIR = PROCESSED / "vaastav_deadlines"


def _commit_rows(payload: list[dict], season: str) -> list[dict]:
    rows = []
    for item in payload:
        commit = item.get("commit", {})
        committer = commit.get("committer", {})
        author = commit.get("author", {})
        observed_at = committer.get("date") or author.get("date")
        if not observed_at:
            continue
        rows.append(
            {
                "season": season,
                "snapshot_sha": item["sha"],
                "observed_at": observed_at,
                "authored_at": author.get("date"),
                "message": commit.get("message", ""),
                "html_url": item.get("html_url"),
            }
        )
    return rows


def fetch(force: bool = False) -> None:
    config = sources()["vaastav_deadlines"]
    for season in config["seasons"]:
        commits_url = (
            f"{config['api_base']}/commits?"
            f"path=data%2F{season}%2Fplayers_raw.csv&per_page=100"
        )
        commits_path = RAW_DIR / season / "commits.json"
        payload = download_json(commits_url, commits_path, force=force)
        if payload is None:
            continue
        rows = _commit_rows(payload, season)
        metadata_path = RAW_DIR / season / "snapshot_index.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for index, row in enumerate(rows, start=1):
            sha = row["snapshot_sha"]
            print(f"vaastav_deadlines: {season} {index}/{len(rows)} {sha[:8]}")
            for filename in config["snapshot_files"]:
                url = f"{config['raw_base']}/{sha}/data/{season}/{filename}"
                download(
                    url,
                    RAW_DIR / season / "snapshots" / sha / filename,
                    optional=True,
                    force=force,
                    throttle_seconds=0.02,
                )


def _quoted(paths: list[Path]) -> str:
    escaped = [str(path).replace("'", "''") for path in paths]
    return "[" + ",".join(f"'{path}'" for path in escaped) + "]"


def _metadata() -> pa.Table:
    rows = []
    for path in sorted(RAW_DIR.glob("*/snapshot_index.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    if not rows:
        raise FileNotFoundError("No deadline snapshot index found; run fetch first")
    return pa.Table.from_pylist(rows)


def _snapshot_query(paths: list[Path], relation: str) -> str:
    if not paths:
        raise FileNotFoundError(f"No {relation} snapshot files found; run fetch first")
    return f"""
        SELECT
            regexp_extract(filename, '/vaastav_deadlines/([^/]+)/', 1) AS season,
            regexp_extract(filename, '/snapshots/([^/]+)/', 1) AS snapshot_sha,
            * EXCLUDE (filename)
        FROM read_csv_auto(
            {_quoted(paths)},
            union_by_name = true,
            filename = true,
            header = true,
            sample_size = -1,
            null_padding = true
        )
    """


def _copy(connection: duckdb.DuckDBPyConnection, query: str, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(output).replace("'", "''")
    count = connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
    connection.execute(
        f"COPY ({query}) TO '{escaped}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    return count


def preprocess() -> dict:
    connection = duckdb.connect()
    connection.register("snapshot_metadata", _metadata())
    try:
        player_paths = sorted(RAW_DIR.glob("*/snapshots/*/players_raw.csv"))
        fixture_paths = sorted(RAW_DIR.glob("*/snapshots/*/fixtures.csv"))
        team_paths = sorted(RAW_DIR.glob("*/snapshots/*/teams.csv"))
        connection.execute(
            f"CREATE TEMP VIEW raw_players AS {_snapshot_query(player_paths, 'player')}"
        )
        connection.execute(
            f"CREATE TEMP VIEW raw_fixtures AS {_snapshot_query(fixture_paths, 'fixture')}"
        )
        connection.execute(
            f"CREATE TEMP VIEW raw_teams AS {_snapshot_query(team_paths, 'team')}"
        )
        connection.execute(
            """
            CREATE TEMP VIEW snapshot_deadlines AS
            WITH fixture_deadlines AS (
                SELECT
                    f.season,
                    f.snapshot_sha,
                    f.event,
                    min(try_cast(f.kickoff_time AS TIMESTAMPTZ)) - INTERVAL 90 MINUTE
                        AS deadline_at
                FROM raw_fixtures f
                WHERE f.event IS NOT NULL AND f.kickoff_time IS NOT NULL
                GROUP BY ALL
            ), candidates AS (
                SELECT
                    m.*,
                    d.event AS decision_event,
                    d.deadline_at,
                    row_number() OVER (
                        PARTITION BY m.season, m.snapshot_sha
                        ORDER BY d.deadline_at
                    ) AS upcoming_rank
                FROM snapshot_metadata m
                JOIN fixture_deadlines d
                  ON m.season = d.season AND m.snapshot_sha = d.snapshot_sha
                 AND try_cast(m.observed_at AS TIMESTAMPTZ) < d.deadline_at
            )
            SELECT * EXCLUDE (upcoming_rank)
            FROM candidates WHERE upcoming_rank = 1
            """
        )
        connection.execute(
            """
            CREATE TEMP VIEW selected_deadlines AS
            SELECT * EXCLUDE (snapshot_rank)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY season, decision_event
                    ORDER BY try_cast(observed_at AS TIMESTAMPTZ) DESC
                ) AS snapshot_rank
                FROM snapshot_deadlines
            ) WHERE snapshot_rank = 1
            """
        )
        player_query = """
            SELECT
                p.*,
                d.decision_event,
                d.deadline_at,
                d.observed_at,
                d.authored_at,
                d.message AS commit_message,
                true AS is_deadline_proxy,
                'github_commit' AS observation_source
            FROM raw_players p
            JOIN selected_deadlines d USING (season, snapshot_sha)
        """
        fixture_query = """
            SELECT
                f.*,
                d.decision_event,
                d.deadline_at,
                d.observed_at,
                d.authored_at,
                d.message AS commit_message,
                true AS is_deadline_proxy,
                'github_commit' AS observation_source
            FROM raw_fixtures f
            JOIN selected_deadlines d USING (season, snapshot_sha)
        """
        team_query = """
            SELECT
                t.*,
                d.decision_event,
                d.deadline_at,
                d.observed_at,
                d.authored_at,
                d.message AS commit_message,
                true AS is_deadline_proxy,
                'github_commit' AS observation_source
            FROM raw_teams t
            JOIN selected_deadlines d USING (season, snapshot_sha)
        """
        selected_rows = connection.execute(
            "SELECT count(*) FROM selected_deadlines"
        ).fetchone()[0]
        coverage_rows = connection.execute(
            """
            SELECT season, count(*) AS deadlines, min(decision_event), max(decision_event)
            FROM selected_deadlines GROUP BY season ORDER BY season
            """
        ).fetchall()
        coverage = [
            {
                "season": season,
                "deadlines": count,
                "first_event": first,
                "last_event": last,
            }
            for season, count, first, last in coverage_rows
        ]
        write_rows(coverage, OUT_DIR / "coverage.parquet")
        return {
            "selected_deadlines": selected_rows,
            "coverage": coverage,
            "player_snapshots": _copy(
                connection, player_query, OUT_DIR / "player_snapshots.parquet"
            ),
            "fixture_snapshots": _copy(
                connection, fixture_query, OUT_DIR / "fixture_snapshots.parquet"
            ),
            "team_snapshots": _copy(
                connection, team_query, OUT_DIR / "team_snapshots.parquet"
            ),
        }
    finally:
        connection.close()
