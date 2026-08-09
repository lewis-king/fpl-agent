from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def write_rows(rows: Iterable[dict], path: Path, schema: pa.Schema | None = None) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(materialized, schema=schema)
    write_table(table, path)
    return table.num_rows


def write_table(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", write_statistics=True)
    temporary.replace(path)


def parquet_rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows
