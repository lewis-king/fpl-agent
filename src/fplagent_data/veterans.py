from __future__ import annotations

import html
import re
import unicodedata
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl

from .arrow import json_text, write_rows
from .catalog import sources
from .http import download
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "veterans"
OUT_DIR = PROCESSED / "veterans"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
SHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
GW_RE = re.compile(r"\bGW\s*(\d{1,2})\b", re.IGNORECASE)


def _rss_url(after: str | None = None) -> str:
    base = sources()["veterans"]["rss"]
    query = {"limit": "25"}
    if after:
        query["after"] = after
    return f"{base}?{urllib.parse.urlencode(query)}"


def _parse_feed(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    rows = []
    for entry in root.findall("atom:entry", ATOM):
        content = entry.findtext("atom:content", default="", namespaces=ATOM)
        post_url_node = entry.find("atom:link", ATOM)
        post_id = entry.findtext("atom:id", default="", namespaces=ATOM)
        rows.append(
            {
                "post_id": post_id,
                "title": entry.findtext("atom:title", default="", namespaces=ATOM),
                "published": entry.findtext("atom:published", default="", namespaces=ATOM),
                "updated": entry.findtext("atom:updated", default="", namespaces=ATOM),
                "url": post_url_node.attrib.get("href") if post_url_node is not None else None,
                "content_html": html.unescape(content or ""),
            }
        )
    return rows


def _season_from_timestamp(value: str) -> str:
    date = datetime.fromisoformat(value)
    start = date.year if date.month >= 7 else date.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _post_metadata(rows: list[dict]) -> list[dict]:
    result = []
    for item in rows:
        gw_match = GW_RE.search(item["title"])
        workbook_ids = sorted(set(SHEET_RE.findall(item["content_html"])))
        title = item["title"].lower()
        post_type = "performance" if title.startswith("how did veterans") else "picks_transfers"
        result.append(
            {
                **item,
                "season": _season_from_timestamp(item["published"]),
                "gameweek": int(gw_match.group(1)) if gw_match else None,
                "post_type": post_type,
                "workbook_ids": workbook_ids,
            }
        )
    return result


def fetch(force: bool = False, max_pages: int = 60) -> None:
    feed_dir = RAW_DIR / "reddit"
    seen: dict[str, dict] = {}
    after = None
    for page in range(max_pages):
        destination = feed_dir / f"page-{page:02d}.xml"
        try:
            download(
                _rss_url(after),
                destination,
                force=force,
                throttle_seconds=15.0 if page else 0.0,
                retries=7,
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            print("veterans: Reddit rate limit reached; preserving completed RSS pages")
            break
        entries = _parse_feed(destination)
        new_count = 0
        for item in entries:
            if item["post_id"] not in seen:
                seen[item["post_id"]] = item
                new_count += 1
        print(f"veterans: RSS page {page + 1}, {new_count} new posts")
        if not entries or new_count == 0:
            break
        next_after = entries[-1]["post_id"]
        if not next_after or next_after == after:
            break
        after = next_after

    posts = _post_metadata(list(seen.values()))
    workbook_ids = {item for post in posts for item in post["workbook_ids"]}
    selection_id = sources()["veterans"]["selection_workbook_id"]
    workbook_ids.add(selection_id)
    for number, workbook_id in enumerate(sorted(workbook_ids), 1):
        url = f"https://docs.google.com/spreadsheets/d/{workbook_id}/export?format=xlsx"
        destination = RAW_DIR / "workbooks" / f"{workbook_id}.xlsx"
        path = download(
            url,
            destination,
            optional=True,
            force=force,
            throttle_seconds=0.5,
        )
        if path is not None and not zipfile.is_zipfile(path):
            raise ValueError(f"Google Sheet export is not an XLSX file: {workbook_id}")
        if number % 10 == 0 or number == len(workbook_ids):
            print(f"veterans: fetched {number}/{len(workbook_ids)} workbooks")


def _normalise_header(value: Any, position: int) -> str:
    if value is None or str(value).strip() == "":
        return f"column_{position}"
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    text = text.lower().replace("%", " percent ").replace("£", " cost ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or f"column_{position}"


def _unique_headers(values: list[Any]) -> list[str]:
    counts: dict[str, int] = {}
    result = []
    for index, value in enumerate(values, 1):
        base = _normalise_header(value, index)
        counts[base] = counts.get(base, 0) + 1
        result.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return result


def _clean_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _category(sheet_name: str, headers: list[str]) -> str:
    text = f"{sheet_name} {' '.join(headers)}".lower().replace("_", " ")
    if "main trade" in text or ("from" in headers and "to" in headers and "freq" in text):
        return "transfer_pairs"
    if "captain" in text:
        return "captaincy"
    if "trade" in text or "transfer" in text:
        if " out" in text or "sold" in text:
            return "transfers_out"
        if " in" in text or "bought" in text:
            return "transfers_in"
    if "dislike" in text:
        return "ownership_dislike"
    if "like" in text:
        return "ownership_like"
    if "wildcard" in text or " wc" in text:
        return "wildcard_squad"
    if "free hit" in text or " fh" in text:
        return "free_hit_squad"
    return "other"


def _first(record: dict, aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _workbook_rows(path: Path, metadata: dict) -> list[dict]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    result = []
    try:
        for worksheet in workbook.worksheets:
            values = list(worksheet.iter_rows(values_only=True))
            header_index = next(
                (
                    index
                    for index, row in enumerate(values)
                    if sum(value not in (None, "") for value in row) >= 2
                ),
                None,
            )
            if header_index is None:
                continue
            headers = _unique_headers(list(values[header_index]))
            category = _category(worksheet.title, headers)
            for row_number, values_row in enumerate(values[header_index + 1 :], header_index + 2):
                if not any(value not in (None, "") for value in values_row):
                    continue
                record = {
                    header: _clean_value(value)
                    for header, value in zip(headers, values_row, strict=False)
                    if value not in (None, "")
                }
                result.append(
                    {
                        **metadata,
                        "sheet_name": worksheet.title,
                        "table_category": category,
                        "row_number": row_number,
                        "player": _first(record, ("player", "web_name", "second_name")),
                        "team": _first(record, ("team", "club")),
                        "position": _first(record, ("pos", "position")),
                        "from_player": _first(record, ("from", "player_out", "sold")),
                        "to_player": _first(record, ("to", "player_in", "bought")),
                        "frequency": _first(
                            record,
                            ("freq", "frequency", "freqin", "freqout", "freqsold"),
                        ),
                        "record_json": json_text(record),
                    }
                )
    finally:
        workbook.close()
    return result


def _candidate_rows(path: Path) -> list[dict]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook.worksheets[0]
    iterator = worksheet.iter_rows(values_only=True)
    headers = _unique_headers(list(next(iterator)))
    rows = []
    try:
        for row in iterator:
            record = dict(zip(headers, row, strict=False))
            if record.get("entry") is None:
                continue
            rows.append(
                {
                    "season": "2025-26",
                    "manager_id": int(record["entry"]),
                    "veteran_score": record.get("vetscore"),
                    "seasons_played": record.get("nseasons"),
                    "manager_name": record.get("player_name"),
                    "team_name": record.get("entry_name"),
                }
            )
    finally:
        workbook.close()
    return rows


def preprocess() -> dict:
    all_posts: dict[str, dict] = {}
    for path in sorted((RAW_DIR / "reddit").glob("page-*.xml")):
        for item in _parse_feed(path):
            all_posts[item["post_id"]] = item
    posts = _post_metadata(list(all_posts.values()))
    post_rows = []
    workbook_metadata: dict[str, dict] = {}
    for post in posts:
        ids = post.pop("workbook_ids")
        post_rows.append({**post, "workbook_ids_json": json_text(ids)})
        for workbook_id in ids:
            workbook_metadata.setdefault(
                workbook_id,
                {
                    "season": post["season"],
                    "gameweek": post["gameweek"],
                    "post_id": post["post_id"],
                    "post_type": post["post_type"],
                    "workbook_id": workbook_id,
                },
            )

    selection_id = sources()["veterans"]["selection_workbook_id"]
    candidate_path = RAW_DIR / "workbooks" / f"{selection_id}.xlsx"
    candidates = _candidate_rows(candidate_path)
    workbook_metadata.pop(selection_id, None)

    rows = []
    for workbook_id, metadata in workbook_metadata.items():
        path = RAW_DIR / "workbooks" / f"{workbook_id}.xlsx"
        if path.exists():
            rows.extend(_workbook_rows(path, metadata))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "posts": write_rows(post_rows, OUT_DIR / "posts.parquet"),
        "candidates": write_rows(candidates, OUT_DIR / "candidates.parquet"),
        "rows": write_rows(rows, OUT_DIR / "rows.parquet"),
    }
