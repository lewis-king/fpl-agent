from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .paths import MANIFESTS, PROCESSED, ensure_layout

EXPECTED = {
    "solio/manager_outcomes.parquet": (13_105_875, None),
    "solio/top100.parquet": (100, 100),
    "fpl_genius/managers.parquet": (100, 100),
    "fpl_genius/captaincy.parquet": (3_800, 3_800),
    "veterans/candidates.parquet": (50_000, None),
    "veterans/posts.parquet": (764, None),
    "veterans/rows.parquet": (650_000, None),
    "vaastav/player_gameweeks.parquet": (253_000, None),
    "vaastav/top_manager_summary.parquet": (10, 10),
    "vaastav/top_manager_gameweeks.parquet": (380, 380),
    "vaastav/top_manager_picks.parquet": (5_700, 5_700),
    "fpl/2026-27/preseason/players.parquet": (500, None),
    "fpl/2026-27/preseason/teams.parquet": (20, 20),
    "fpl/2026-27/preseason/events.parquet": (38, 38),
    "fpl/2026-27/preseason/fixtures.parquet": (380, 380),
    "fpl/2026-27/preseason/chips.parquet": (8, 8),
    "fpl/2026-27/preseason/positions.parquet": (4, 4),
    "fpl/2026-27/preseason/element_stats.parquet": (20, None),
    "fpl/2026-27/preseason/phases.parquet": (11, 11),
    "fpl/2026-27/preseason/rules.parquet": (1, 1),
    "supporting/paul_top50.parquet": (50, 50),
    "supporting/soong_manager_gameweeks.parquet": (266, 266),
    "supporting/soong_chips.parquet": (56, 56),
    "supporting/soong_final_squad_picks.parquet": (105, 105),
}


def _count(connection: duckdb.DuckDBPyConnection, path: Path) -> int:
    escaped = str(path).replace("'", "''")
    return connection.execute(f"SELECT count(*) FROM read_parquet('{escaped}')").fetchone()[0]


def validate() -> dict:
    ensure_layout()
    report = {
        "validated_at": datetime.now(UTC).isoformat(),
        "status": "ok",
        "tables": {},
        "checks": [],
    }
    errors = []
    connection = duckdb.connect()
    try:
        for relative, (minimum, maximum) in EXPECTED.items():
            path = PROCESSED / relative
            if not path.exists():
                errors.append(f"missing {relative}")
                continue
            rows = _count(connection, path)
            report["tables"][relative] = rows
            if rows < minimum or (maximum is not None and rows > maximum):
                errors.append(f"unexpected row count {relative}: {rows}")

        solio = str(PROCESSED / "solio" / "top100.parquet").replace("'", "''")
        genius = str(PROCESSED / "fpl_genius" / "managers.parquet").replace("'", "''")
        if Path(PROCESSED / "solio" / "top100.parquet").exists() and Path(
            PROCESSED / "fpl_genius" / "managers.parquet"
        ).exists():
            missing = connection.execute(
                f"SELECT count(*) FROM read_parquet('{solio}') s "
                f"ANTI JOIN read_parquet('{genius}') g USING (manager_id)"
            ).fetchone()[0]
            report["checks"].append({"top100_missing_from_fpl_genius": missing})
            if missing:
                errors.append(f"{missing} Solio top-100 managers absent from FPL Genius")

        vaastav = str(PROCESSED / "vaastav" / "player_gameweeks.parquet").replace(
            "'", "''"
        )
        if (PROCESSED / "vaastav" / "player_gameweeks.parquet").exists():
            season_rows = connection.execute(
                f"SELECT season, count(*) AS rows, count(DISTINCT GW) AS gameweeks "
                f"FROM read_parquet('{vaastav}') GROUP BY season ORDER BY season"
            ).fetchall()
            coverage = [
                {"season": season, "rows": rows, "gameweeks": gameweeks}
                for season, rows, gameweeks in season_rows
            ]
            report["checks"].append({"vaastav_season_coverage": coverage})
            expected_seasons = [f"{year}-{str(year + 1)[-2:]}" for year in range(2016, 2026)]
            if [row[0] for row in season_rows] != expected_seasons:
                errors.append("Vaastav does not contain the expected ten seasons")
            if any(row[2] < 37 for row in season_rows):
                errors.append("A Vaastav season contains fewer than 37 gameweek labels")
            duplicate_keys, null_elements, null_points = connection.execute(
                f"SELECT count(*) - count(DISTINCT (season, GW, element, fixture)), "
                f"count(*) FILTER (WHERE element IS NULL), "
                f"count(*) FILTER (WHERE total_points IS NULL) "
                f"FROM read_parquet('{vaastav}')"
            ).fetchone()
            report["checks"].append(
                {
                    "vaastav_duplicate_player_fixture_keys": duplicate_keys,
                    "vaastav_null_element_ids": null_elements,
                    "vaastav_null_total_points": null_points,
                }
            )
            if duplicate_keys or null_elements or null_points:
                errors.append("Vaastav player-gameweek key/null integrity check failed")

        genius_captaincy = PROCESSED / "fpl_genius" / "captaincy.parquet"
        if genius_captaincy.exists():
            escaped = str(genius_captaincy).replace("'", "''")
            managers, gameweeks = connection.execute(
                f"SELECT count(DISTINCT manager_id), count(DISTINCT event) "
                f"FROM read_parquet('{escaped}')"
            ).fetchone()
            report["checks"].append(
                {"fpl_genius_managers": managers, "fpl_genius_gameweeks": gameweeks}
            )
            if managers != 100 or gameweeks != 38:
                errors.append("FPL Genius top-100 decision coverage is incomplete")

        veterans_posts = PROCESSED / "veterans" / "posts.parquet"
        veterans_rows = PROCESSED / "veterans" / "rows.parquet"
        if veterans_posts.exists() and veterans_rows.exists():
            posts_path = str(veterans_posts).replace("'", "''")
            rows_path = str(veterans_rows).replace("'", "''")
            oldest, newest = connection.execute(
                f"SELECT min(published), max(published) FROM read_parquet('{posts_path}')"
            ).fetchone()
            workbooks = connection.execute(
                f"SELECT count(DISTINCT workbook_id) FROM read_parquet('{rows_path}')"
            ).fetchone()[0]
            report["checks"].append(
                {
                    "veterans_oldest_post": oldest,
                    "veterans_newest_post": newest,
                    "veterans_available_workbooks": workbooks,
                }
            )
            if not oldest or oldest[:4] > "2016":
                errors.append("Veteran post crawl did not reach the beginning of the archive")

        soong_gameweeks = PROCESSED / "supporting" / "soong_manager_gameweeks.parquet"
        soong_chips = PROCESSED / "supporting" / "soong_chips.parquet"
        if soong_gameweeks.exists() and soong_chips.exists():
            gameweeks_path = str(soong_gameweeks).replace("'", "''")
            chips_path = str(soong_chips).replace("'", "''")
            null_gameweeks = connection.execute(
                f"SELECT count(*) FILTER (WHERE event IS NULL OR points IS NULL) "
                f"FROM read_parquet('{gameweeks_path}')"
            ).fetchone()[0]
            null_chip_events = connection.execute(
                f"SELECT count(*) FILTER (WHERE event IS NULL) "
                f"FROM read_parquet('{chips_path}')"
            ).fetchone()[0]
            report["checks"].append(
                {
                    "soong_null_gameweek_facts": null_gameweeks,
                    "soong_null_chip_events": null_chip_events,
                }
            )
            if null_gameweeks or null_chip_events:
                errors.append("Soong manager history contains null normalized facts")
    finally:
        connection.close()

    raw_manifest = MANIFESTS / "raw_files.jsonl"
    if raw_manifest.exists():
        latest_by_path = {}
        for line in raw_manifest.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            latest_by_path[item["path"]] = item
        report["raw_artifacts"] = {
            "unique_paths": len(latest_by_path),
            "statuses": dict(
                sorted(Counter(item["status"] for item in latest_by_path.values()).items())
            ),
        }

    if errors:
        report["status"] = "failed"
        report["errors"] = errors
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    with (MANIFESTS / "build_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    if errors:
        raise ValueError("; ".join(errors))
    return report
