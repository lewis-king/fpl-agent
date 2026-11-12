from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def semantic_parquet_sha256(
    path: Path,
    *,
    ignored_columns: set[str] | frozenset[str] = frozenset(),
    sort_columns: tuple[str, ...] = (),
) -> str:
    """Hash decision-bearing Arrow values while ignoring volatile provenance fields."""

    table = pq.read_table(path)
    selected = [name for name in table.column_names if name not in ignored_columns]
    if not selected:
        raise ValueError(f"No semantic columns remain in {path}")
    table = table.select(selected).combine_chunks().replace_schema_metadata(None)
    usable_sort_columns = [name for name in sort_columns if name in table.column_names]
    if usable_sort_columns:
        indices = pc.sort_indices(
            table,
            sort_keys=[(name, "ascending") for name in usable_sort_columns],
        )
        table = table.take(indices)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()

