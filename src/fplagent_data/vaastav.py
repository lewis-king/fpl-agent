from __future__ import annotations

from pathlib import Path

import duckdb

from .catalog import sources
from .http import download
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "vaastav"
OUT_DIR = PROCESSED / "vaastav"


def fetch(force: bool = False) -> None:
    config = sources()["vaastav"]
    base = config["raw_base"]
    for season in config["seasons"]:
        for relative in config["season_files"]:
            url = f"{base}/{season}/{relative}"
            destination = RAW_DIR / season / relative
            print(f"vaastav: {season}/{relative}")
            download(url, destination, optional=True, force=force, throttle_seconds=0.05)

    manager_base = f"{base}/2019-20/managers"
    for filename in ("top_managers.csv", "top_managers_gwInfo.csv", "top_managers_gwPicks.csv"):
        download(
            f"{manager_base}/{filename}",
            RAW_DIR / "2019-20" / "managers" / filename,
            force=force,
        )


def _quoted_paths(paths: list[Path]) -> str:
    escaped = [str(path).replace("'", "''") for path in paths]
    return "[" + ",".join(f"'{path}'" for path in escaped) + "]"


def _read_csv_query(paths: list[Path], encoding: str | None = None) -> str:
    inputs = _quoted_paths(paths)
    encoding_sql = f", encoding = '{encoding}'" if encoding else ""
    return f"""
        SELECT
            regexp_extract(filename, '/vaastav/([^/]+)/', 1) AS season,
            * EXCLUDE (filename)
        FROM read_csv_auto(
            {inputs},
            union_by_name = true,
            filename = true,
            header = true,
            sample_size = -1,
            null_padding = true
            {encoding_sql}
        )
    """


def _copy_union(
    connection: duckdb.DuckDBPyConnection,
    paths: list[Path],
    output: Path,
    *,
    latin1_paths: list[Path] | None = None,
) -> int:
    if not paths:
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output_sql = str(output).replace("'", "''")
    latin1 = set(latin1_paths or [])
    utf8_paths = [path for path in paths if path not in latin1]
    parts = []
    if utf8_paths:
        parts.append(_read_csv_query(utf8_paths))
    if latin1:
        parts.append(_read_csv_query(sorted(latin1), encoding="latin-1"))
    union = " UNION ALL BY NAME ".join(f"({part})" for part in parts)
    # Some upstream merged files contain a handful of byte-for-byte duplicate
    # player-fixture rows. Preserve double/triple gameweeks, but remove only
    # complete duplicate records.
    query = f"SELECT DISTINCT * FROM ({union})"
    count = connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
    connection.execute(
        f"COPY ({query}) TO '{output_sql}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    return count


def preprocess() -> dict:
    connection = duckdb.connect()
    try:
        gameweek_paths = sorted(RAW_DIR.glob("*/gws/merged_gw.csv"))
        latin1_seasons = {"2016-17", "2017-18", "2018-19"}
        result = {
            "player_gameweeks": _copy_union(
                connection,
                gameweek_paths,
                OUT_DIR / "player_gameweeks.parquet",
                latin1_paths=[
                    path for path in gameweek_paths if path.parts[-3] in latin1_seasons
                ],
            ),
            "players": _copy_union(
                connection,
                sorted(RAW_DIR.glob("*/players_raw.csv")),
                OUT_DIR / "players.parquet",
            ),
            "fixtures": _copy_union(
                connection,
                sorted(RAW_DIR.glob("*/fixtures.csv")),
                OUT_DIR / "fixtures.parquet",
            ),
            "teams": _copy_union(
                connection,
                sorted(RAW_DIR.glob("*/teams.csv")),
                OUT_DIR / "teams.parquet",
            ),
        }
        manager_dir = RAW_DIR / "2019-20" / "managers"
        for source_name, output_name in (
            ("top_managers.csv", "top_manager_summary.parquet"),
            ("top_managers_gwInfo.csv", "top_manager_gameweeks.parquet"),
            ("top_managers_gwPicks.csv", "top_manager_picks.parquet"),
        ):
            result[output_name.removesuffix(".parquet")] = _copy_union(
                connection, [manager_dir / source_name], OUT_DIR / output_name
            )
        return result
    finally:
        connection.close()
