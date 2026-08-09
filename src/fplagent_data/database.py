from __future__ import annotations

import re

import duckdb
import pyarrow.parquet as pq

from .paths import DATA, PROCESSED, ensure_layout

DATABASE = DATA / "fpl_history.duckdb"


def _view_name(relative: str) -> str:
    stem = relative.removesuffix(".parquet")
    if stem.startswith("fpl/2026-27/preseason/"):
        stem = "fpl_current/" + stem.rsplit("/", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


def build_catalog() -> dict:
    """Create lightweight DuckDB views over every normalized Parquet table."""
    ensure_layout()
    files = sorted(PROCESSED.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError("No processed Parquet tables found; run preprocess first")

    records = []
    connection = duckdb.connect(str(DATABASE))
    try:
        has_catalog = connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = 'dataset_catalog' "
            "AND table_type = 'BASE TABLE'"
        ).fetchone()[0]
        if has_catalog:
            for (name,) in connection.execute(
                "SELECT view_name FROM dataset_catalog"
            ).fetchall():
                connection.execute(f'DROP VIEW IF EXISTS "{name}"')

        for path in files:
            relative = path.relative_to(PROCESSED).as_posix()
            name = _view_name(relative)
            escaped = str(path.resolve()).replace("'", "''")
            connection.execute(
                f'CREATE VIEW "{name}" AS SELECT * FROM read_parquet(\'{escaped}\')'
            )
            metadata = pq.ParquetFile(path).metadata
            records.append(
                (
                    name,
                    relative,
                    relative.split("/", 1)[0],
                    metadata.num_rows,
                    metadata.num_columns,
                )
            )

        connection.execute(
            "CREATE OR REPLACE TABLE dataset_catalog ("
            "view_name VARCHAR PRIMARY KEY, relative_path VARCHAR, source VARCHAR, "
            "row_count BIGINT, column_count INTEGER)"
        )
        connection.executemany(
            "INSERT INTO dataset_catalog VALUES (?, ?, ?, ?, ?)", records
        )
    finally:
        connection.close()

    return {
        "database": str(DATABASE.relative_to(DATA.parent)),
        "views": len(records),
        "rows": sum(record[3] for record in records),
    }
