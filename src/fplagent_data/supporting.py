from __future__ import annotations

import json

import duckdb
import openpyxl

from .arrow import json_text, write_rows
from .catalog import sources
from .http import download
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "supporting"
OUT_DIR = PROCESSED / "supporting"


def fetch(force: bool = False) -> None:
    for filename, url in sources()["supporting"]["files"].items():
        print(f"supporting: {filename}")
        download(url, RAW_DIR / filename, force=force, throttle_seconds=0.05)


def _paul_rows() -> list[dict]:
    workbook = openpyxl.load_workbook(RAW_DIR / "paul_top50.xlsx", read_only=True, data_only=True)
    worksheet = workbook.worksheets[0]
    iterator = worksheet.iter_rows(values_only=True)
    headers = [str(value).strip() for value in next(iterator)]
    rows = []
    try:
        for values in iterator:
            if not any(value is not None for value in values):
                continue
            record = dict(zip(headers, values, strict=False))
            rows.append(
                {
                    "season": "2019-20",
                    "overall_rank": record.get("Overall_Rank"),
                    "manager_name": record.get("Manager"),
                    "total_points": record.get("Total_Points"),
                    "record_json": json_text(record),
                }
            )
    finally:
        workbook.close()
    return rows


def _soong_rows() -> tuple[list[dict], list[dict]]:
    with (RAW_DIR / "soong_manager_history.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)
    gameweeks = []
    chips = []
    for manager_key, manager in payload["data"]["managers"].items():
        manager_id = int(manager.get("entry_id", manager_key))
        for item in manager.get("gws") or []:
            gameweeks.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "event": item.get("event") or item.get("gw"),
                    "points": item.get("points", item.get("pts")),
                    "total_points": item.get("total"),
                    "overall_rank": item.get("overall_rank"),
                    "percentile_rank": item.get("percentile_rank"),
                    "rank_delta": item.get("rank_delta"),
                    "transfer_cost": item.get("hits"),
                    "bench_points": item.get("bench_pts"),
                    "squad_value": item.get("value"),
                    "bank": item.get("bank"),
                    "active_chip": item.get("chip"),
                    "record_json": json_text(item),
                }
            )
        for item in manager.get("chips_used") or []:
            chips.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "event": item.get("event", item.get("gw")),
                    "chip": item.get("name"),
                    "record_json": json_text(item),
                }
            )
    return gameweeks, chips


def _soong_final_squad_rows() -> list[dict]:
    with (RAW_DIR / "soong_manager_history.json").open(encoding="utf-8") as handle:
        history = json.load(handle)
    with (RAW_DIR / "soong_my_squad_final.json").open(encoding="utf-8") as handle:
        own = json.load(handle)
    with (RAW_DIR / "soong_rival_squads_final.json").open(encoding="utf-8") as handle:
        rivals = json.load(handle)

    managers = {int(value.get("entry_id", key)) for key, value in history["data"]["managers"].items()}
    rival_payload = rivals["data"]["rivals"]
    rival_ids = {int(manager_id) for manager_id in rival_payload}
    own_ids = managers - rival_ids
    if len(own_ids) != 1:
        raise ValueError("Could not identify the self manager from Soong's public cohort")

    event = own["meta"]["current_gw"]
    cohorts = [(own_ids.pop(), "self", own["data"])] + [
        (int(manager_id), "rival", squad)
        for manager_id, squad in rival_payload.items()
    ]
    rows = []
    for manager_id, role, squad in cohorts:
        for pick in squad["picks"]:
            rows.append(
                {
                    "season": "2025-26",
                    "event": event,
                    "manager_id": manager_id,
                    "manager_role": role,
                    "active_chip": squad.get("active_chip"),
                    "bank": squad.get("bank"),
                    "squad_value": squad.get("squad_value"),
                    **pick,
                    "record_json": json_text(pick),
                }
            )
    return rows


def preprocess() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {"paul_top50": write_rows(_paul_rows(), OUT_DIR / "paul_top50.parquet")}

    connection = duckdb.connect()
    try:
        source = str(RAW_DIR / "titan_managers.csv").replace("'", "''")
        output = str(OUT_DIR / "titan_managers.parquet").replace("'", "''")
        count = connection.execute(
            f"SELECT count(*) FROM read_csv_auto('{source}', header=true, sample_size=-1)"
        ).fetchone()[0]
        connection.execute(
            f"COPY (SELECT '2022-23' AS season, * FROM read_csv_auto('{source}', "
            f"header=true, sample_size=-1)) TO '{output}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        result["titan_managers"] = count
    finally:
        connection.close()

    gameweeks, chips = _soong_rows()
    result["soong_manager_gameweeks"] = write_rows(
        gameweeks, OUT_DIR / "soong_manager_gameweeks.parquet"
    )
    result["soong_chips"] = write_rows(chips, OUT_DIR / "soong_chips.parquet")
    result["soong_final_squad_picks"] = write_rows(
        _soong_final_squad_rows(), OUT_DIR / "soong_final_squad_picks.parquet"
    )
    return result
