from __future__ import annotations

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .arrow import write_rows
from .catalog import sources
from .http import download
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "solio" / "2025-26"
OUT_DIR = PROCESSED / "solio"


def fetch(force: bool = False) -> None:
    config = sources()["solio"]
    for filename, url in config["files"].items():
        print(f"solio: {filename}")
        download(url, RAW_DIR / filename, force=force)


def _u24(value: np.ndarray) -> np.ndarray:
    return (
        value[:, 0].astype(np.uint32)
        | value[:, 1].astype(np.uint32) << 8
        | value[:, 2].astype(np.uint32) << 16
    )


def _i24(value: np.ndarray) -> np.ndarray:
    result = _u24(value).astype(np.int32)
    return np.where(result & 0x800000, result - 0x1000000, result).astype(np.int32)


def _write_outcomes(manifest: dict, chunk_size: int = 500_000) -> int:
    main_dtype = np.dtype(
        [
            ("points", "<i2"),
            ("overall_rank", "u1", 3),
            ("projected_points", "u1", 3),
            ("projected_rank", "u1", 3),
            ("overperformance_points", "u1", 3),
            ("overperformance_rank", "u1", 3),
        ]
    )
    active_dtype = np.dtype(
        [
            ("active_overall_rank", "u1", 3),
            ("active_projected_rank", "u1", 3),
            ("active_overperformance_rank", "u1", 3),
        ]
    )
    main = np.memmap(RAW_DIR / "eos.bin", dtype=main_dtype, mode="r")
    active = np.memmap(RAW_DIR / "eos_active.bin", dtype=active_dtype, mode="r")
    expected = int(manifest["max_user_id"]) + 1
    if len(main) != expected or len(active) != expected:
        raise ValueError(f"Solio record count mismatch: {len(main)=}, {len(active)=}, {expected=}")

    schema = pa.schema(
        [
            ("season", pa.string()),
            ("manager_id", pa.int64()),
            ("points", pa.int16()),
            ("overall_rank", pa.int32()),
            ("projected_points", pa.float32()),
            ("projected_rank", pa.int32()),
            ("overperformance_points", pa.float32()),
            ("overperformance_rank", pa.int32()),
            ("active", pa.bool_()),
            ("active_overall_rank", pa.int32()),
            ("active_projected_rank", pa.int32()),
            ("active_overperformance_rank", pa.int32()),
        ]
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / "manager_outcomes.parquet"
    writer = pq.ParquetWriter(output, schema, compression="zstd", write_statistics=True)
    written = 0
    try:
        for start in range(0, expected, chunk_size):
            stop = min(start + chunk_size, expected)
            batch = main[start:stop]
            ranks = _u24(batch["overall_rank"])
            mask = ranks != 0
            if not mask.any():
                continue
            active_batch = active[start:stop]
            active_ranks = _u24(active_batch["active_overall_rank"])
            ids = np.arange(start, stop, dtype=np.int64)[mask]
            table = pa.table(
                {
                    "season": pa.array(["2025-26"] * int(mask.sum()), type=pa.string()),
                    "manager_id": ids,
                    "points": batch["points"][mask],
                    "overall_rank": ranks[mask].astype(np.int32),
                    "projected_points": (_i24(batch["projected_points"])[mask] / 100).astype(
                        np.float32
                    ),
                    "projected_rank": _u24(batch["projected_rank"])[mask].astype(np.int32),
                    "overperformance_points": (
                        _i24(batch["overperformance_points"])[mask] / 100
                    ).astype(np.float32),
                    "overperformance_rank": _u24(batch["overperformance_rank"])[mask].astype(
                        np.int32
                    ),
                    "active": (active_ranks[mask] != 0),
                    "active_overall_rank": active_ranks[mask].astype(np.int32),
                    "active_projected_rank": _u24(active_batch["active_projected_rank"])[
                        mask
                    ].astype(np.int32),
                    "active_overperformance_rank": _u24(
                        active_batch["active_overperformance_rank"]
                    )[mask].astype(np.int32),
                },
                schema=schema,
            )
            writer.write_table(table)
            written += table.num_rows
            print(f"solio: decoded {stop:,}/{expected:,} IDs")
    finally:
        writer.close()
    return written


def _write_leaderboards() -> int:
    with (RAW_DIR / "leaderboards.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = []
    seen = set()
    for scope in ("all", "active"):
        for board in payload[scope]:
            for item in board["entries"]:
                key = (scope, board["key"], item["id"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "season": "2025-26",
                        "scope": scope,
                        "board": board["key"],
                        "manager_id": item["id"],
                        "team_name": item.get("team"),
                        "points": item.get("rt"),
                        "overall_rank": item.get("rr"),
                        "projected_points": (item.get("pt") / 100 if item.get("pt") is not None else None),
                        "projected_rank": item.get("pr"),
                        "overperformance_points": (
                            item.get("lt") / 100 if item.get("lt") is not None else None
                        ),
                        "overperformance_rank": item.get("lr"),
                    }
                )
    write_rows(rows, OUT_DIR / "leaderboards.parquet")
    top100 = [
        row for row in rows if row["scope"] == "all" and row["board"] == "real"
    ]
    write_rows(top100, OUT_DIR / "top100.parquet")
    return len(top100)


def preprocess() -> dict:
    with (RAW_DIR / "manifest.json").open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    outcomes = _write_outcomes(manifest)
    top100 = _write_leaderboards()
    if outcomes != int(manifest["total_managers"]):
        raise ValueError(
            f"Expected {manifest['total_managers']:,} present managers, wrote {outcomes:,}"
        )
    return {"manager_outcomes": outcomes, "top100": top100}

