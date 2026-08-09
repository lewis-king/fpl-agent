from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .arrow import json_text, write_rows
from .live_snapshots import (
    SnapshotValidationError,
    collect_official_snapshot,
    latest_official_snapshot,
)
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "fpl" / "2026-27" / "snapshots" / "preseason"
OUT_DIR = PROCESSED / "fpl" / "2026-27" / "preseason"


def fetch(force: bool = False) -> dict:
    if not force:
        try:
            _, manifest = latest_official_snapshot()
            return manifest
        except SnapshotValidationError:
            pass
    print("fpl_current: collecting immutable official snapshot")
    return collect_official_snapshot()


def _source_snapshot() -> tuple[Path, str]:
    try:
        snapshot_dir, manifest = latest_official_snapshot()
        return snapshot_dir, str(manifest["observed_at"])
    except SnapshotValidationError:
        if not all(
            (RAW_DIR / filename).is_file()
            for filename in ("bootstrap-static.json", "fixtures.json")
        ):
            raise
        fetched_at = datetime.fromtimestamp(
            (RAW_DIR / "bootstrap-static.json").stat().st_mtime, tz=UTC
        ).isoformat()
        return RAW_DIR, fetched_at


def preprocess() -> dict:
    source_dir, fetched_at = _source_snapshot()
    with (source_dir / "bootstrap-static.json").open(encoding="utf-8") as handle:
        bootstrap = json.load(handle)
    with (source_dir / "fixtures.json").open(encoding="utf-8") as handle:
        fixtures = json.load(handle)

    def enrich(rows: list[dict]) -> list[dict]:
        enriched = []
        for row in rows:
            # FPL occasionally introduces empty or shape-changing nested objects
            # (for example event.rules). Canonical JSON keeps the source lossless
            # while giving every snapshot a stable Parquet schema.
            stable = {
                key: json_text(value) if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            }
            enriched.append({"season": "2026-27", "snapshot_at": fetched_at, **stable})
        return enriched

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rules = bootstrap["game_config"]["rules"]
    scoring = bootstrap["game_config"]["scoring"]
    settings = bootstrap["game_config"]["settings"]
    rules_row = {
        "season": "2026-27",
        "snapshot_at": fetched_at,
        "total_players": bootstrap["total_players"],
        "squad_size": rules["squad_squadsize"],
        "starting_size": rules["squad_squadplay"],
        "club_player_limit": rules["squad_team_limit"],
        "budget_tenths": rules["squad_total_spend"],
        "max_extra_free_transfers": rules["max_extra_free_transfers"],
        "max_bankable_free_transfers": rules["max_extra_free_transfers"] + 1,
        "transfer_limit_per_event": rules["transfers_cap"],
        "transfer_sell_on_fee": rules["transfers_sell_on_fee"],
        "defensive_contribution_points_json": json_text(scoring["defensive_contribution"]),
        "rules_json": json_text(rules),
        "scoring_json": json_text(scoring),
        "settings_json": json_text(settings),
    }
    return {
        "snapshot_at": fetched_at,
        "snapshot_source": str(source_dir),
        "players": write_rows(enrich(bootstrap["elements"]), OUT_DIR / "players.parquet"),
        "teams": write_rows(enrich(bootstrap["teams"]), OUT_DIR / "teams.parquet"),
        "events": write_rows(enrich(bootstrap["events"]), OUT_DIR / "events.parquet"),
        "fixtures": write_rows(enrich(fixtures), OUT_DIR / "fixtures.parquet"),
        "chips": write_rows(enrich(bootstrap["chips"]), OUT_DIR / "chips.parquet"),
        "positions": write_rows(enrich(bootstrap["element_types"]), OUT_DIR / "positions.parquet"),
        "element_stats": write_rows(
            enrich(bootstrap["element_stats"]), OUT_DIR / "element_stats.parquet"
        ),
        "phases": write_rows(enrich(bootstrap["phases"]), OUT_DIR / "phases.parquet"),
        "rules": write_rows([rules_row], OUT_DIR / "rules.parquet"),
    }
