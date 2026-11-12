from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .arrow import write_rows
from .http import download, sha256_file
from .live_snapshots import SnapshotValidationError, latest_official_snapshot
from .paths import MANIFESTS, PROCESSED, RAW, ensure_layout

SEASON = "2026-27"
OUTCOME_ROOT = RAW / "fpl" / SEASON / "event-outcomes"
POINTER_ROOT = MANIFESTS / "fpl-event-outcomes"
EVENT_LIVE_URL = "https://fantasy.premierleague.com/api/event/{event}/live/"
CURRENT_PLAYER_HISTORY = (
    PROCESSED / "fpl" / SEASON / "current-history" / "player-events.parquet"
)
CURRENT_PLAYER_HISTORY_RECEIPT = MANIFESTS / "fpl-current-player-history.json"

LIVE_STAT_FIELDS = {
    "points": "total_points",
    "minutes": "minutes",
    "goals": "goals_scored",
    "assists": "assists",
    "xg": "expected_goals",
    "xa": "expected_assists",
    "bps": "bps",
    "clean_sheets": "clean_sheets",
    "defensive_contribution": "defensive_contribution",
}


def _aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SnapshotValidationError("event outcome observed_at must include a timezone")
    return parsed.astimezone(UTC)


def _timestamp_id(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _event_row(bootstrap: Mapping[str, Any], event: int) -> Mapping[str, Any]:
    rows = bootstrap.get("events")
    if not isinstance(rows, list):
        raise SnapshotValidationError("bootstrap events must be a list")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("id") == event]
    if len(matches) != 1:
        raise SnapshotValidationError(f"bootstrap must contain exactly one event {event}")
    return matches[0]


def _post_event_bootstrap_additions(
    bootstrap_players: list[Any],
    *,
    missing_ids: set[int],
    live_ids: set[int],
    deadline_at: datetime | None,
) -> list[dict[str, Any]] | None:
    """Describe players added to bootstrap after an event's live roster was frozen.

    FPL's current bootstrap is a season catalogue while ``event/{gw}/live`` is an
    immutable event roster. After a deadline, newly registered players are appended
    to bootstrap with higher element IDs but are not backfilled into earlier event
    payloads. Accept only that narrow, auditable superset shape; an arbitrary missing
    player must continue to fail closed.
    """

    if not missing_ids or not live_ids or deadline_at is None:
        return None
    maximum_live_id = max(live_ids)
    players = {
        int(row["id"]): row
        for row in bootstrap_players
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    additions: list[dict[str, Any]] = []
    for element in sorted(missing_ids):
        row = players.get(element)
        if row is None or element <= maximum_live_id:
            return None
        try:
            joined = date.fromisoformat(str(row["team_join_date"]))
        except (KeyError, TypeError, ValueError):
            return None
        if joined < deadline_at.date():
            return None
        additions.append(
            {
                "element": element,
                "player_name": str(
                    row.get("known_name") or row.get("web_name") or f"#{element}"
                ),
                "team_join_date": joined.isoformat(),
            }
        )
    return additions


def validate_event_outcome(
    bootstrap: Mapping[str, Any], live: Mapping[str, Any], *, event: int
) -> dict[str, Any]:
    if not 1 <= event <= 38:
        raise SnapshotValidationError("event must be in [1, 38]")
    event_row = _event_row(bootstrap, event)
    issues = []
    if event_row.get("finished") is not True:
        issues.append("official event is not finished")
    if event_row.get("data_checked") is not True:
        issues.append("official event data has not been checked")
    deadline = event_row.get("deadline_time")
    try:
        deadline_at = _aware(str(deadline))
    except (SnapshotValidationError, ValueError):
        issues.append("official event has no valid deadline")
        deadline_at = None

    bootstrap_players = bootstrap.get("elements")
    if not isinstance(bootstrap_players, list) or not bootstrap_players:
        issues.append("bootstrap elements must be a non-empty list")
        bootstrap_ids: set[int] = set()
    else:
        try:
            bootstrap_ids = {int(row["id"]) for row in bootstrap_players}
        except (KeyError, TypeError, ValueError):
            issues.append("bootstrap elements contain invalid IDs")
            bootstrap_ids = set()
        if len(bootstrap_ids) != len(bootstrap_players):
            issues.append("bootstrap player IDs must be unique")

    live_players = live.get("elements")
    live_ids: set[int] = set()
    live_rows_valid = True
    if not isinstance(live_players, list) or not live_players:
        issues.append("event live elements must be a non-empty list")
        live_rows_valid = False
    else:
        for row in live_players:
            if not isinstance(row, Mapping) or not isinstance(row.get("stats"), Mapping):
                issues.append("every live element must contain a stats object")
                live_rows_valid = False
                break
            stats = row["stats"]
            missing_stats = [
                source for source in LIVE_STAT_FIELDS.values() if source not in stats
            ]
            if missing_stats:
                issues.append(
                    "event live stats are missing required production fields: "
                    f"{missing_stats}"
                )
                live_rows_valid = False
                break
            try:
                element = int(row["id"])
                minutes = int(stats["minutes"])
                int(stats["total_points"])
                # Parse every field here so an upstream schema/value change cannot be
                # archived as publishable and fail only during a later model rebuild.
                for source in LIVE_STAT_FIELDS.values():
                    float(stats[source])
            except (KeyError, TypeError, ValueError):
                issues.append("live element IDs and required stats must be numeric")
                live_rows_valid = False
                break
            if minutes < 0:
                issues.append("live element minutes cannot be negative")
                live_rows_valid = False
                break
            live_ids.add(element)
        if live_rows_valid and len(live_ids) != len(live_players):
            issues.append("live player IDs must be unique")
            live_rows_valid = False
    post_event_additions: list[dict[str, Any]] = []
    if bootstrap_ids and live_rows_valid and live_ids != bootstrap_ids:
        missing_ids = bootstrap_ids - live_ids
        extra_ids = live_ids - bootstrap_ids
        accepted_additions = _post_event_bootstrap_additions(
            bootstrap_players,
            missing_ids=missing_ids,
            live_ids=live_ids,
            deadline_at=deadline_at,
        )
        if extra_ids or accepted_additions is None:
            issues.append(
                "event live player set differs from bootstrap: "
                f"missing={len(missing_ids)}, extra={len(extra_ids)}"
            )
        else:
            post_event_additions = accepted_additions
    return {
        "event": event,
        "deadline_time": deadline_at.isoformat() if deadline_at else None,
        "finished": event_row.get("finished") is True,
        "data_checked": event_row.get("data_checked") is True,
        "players": len(live_ids),
        "post_event_bootstrap_additions": post_event_additions,
        "complete": not issues,
        "publishable": not issues,
        "issues": issues,
    }


def archive_event_outcome(
    live: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    *,
    event: int,
    observed_at: str | datetime,
    outcome_root: Path = OUTCOME_ROOT,
    pointer_root: Path = POINTER_ROOT,
    bootstrap_path: Path | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    ensure_layout()
    observed = _aware(observed_at)
    validation = validate_event_outcome(bootstrap, live, event=event)
    if not validation["publishable"]:
        raise SnapshotValidationError("; ".join(validation["issues"]))
    snapshot_dir = outcome_root / f"event-{event}" / _timestamp_id(observed)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    live_path = snapshot_dir / "event-live.json"
    rendered = json.dumps(live, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if live_path.exists() and live_path.read_text(encoding="utf-8") != rendered:
        raise SnapshotValidationError(f"immutable event outcome collision: {snapshot_dir}")
    if not live_path.exists():
        temporary = live_path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(live_path)
    manifest = {
        "manifest_version": 1,
        "season": SEASON,
        "event": event,
        "observed_at": observed.isoformat(),
        **validation,
        "event_live_sha256": sha256_file(live_path),
        "bootstrap_path": str(bootstrap_path) if bootstrap_path else None,
        "bootstrap_sha256": (
            sha256_file(bootstrap_path) if bootstrap_path and bootstrap_path.is_file() else None
        ),
        "source_url": source_url or EVENT_LIVE_URL.format(event=event),
    }
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise SnapshotValidationError(f"immutable event manifest collision: {snapshot_dir}")
    else:
        _atomic_json(manifest_path, manifest)
    _atomic_json(
        pointer_root / f"event-{event}.json",
        {
            "pointer_version": 1,
            "season": SEASON,
            "event": event,
            "snapshot_id": snapshot_dir.name,
            "manifest_sha256": sha256_file(manifest_path),
        },
    )
    return manifest


def latest_event_outcome(
    event: int,
    *,
    outcome_root: Path = OUTCOME_ROOT,
    pointer_root: Path = POINTER_ROOT,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    pointer_path = pointer_root / f"event-{event}.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_id = str(pointer["snapshot_id"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError(f"no valid outcome pointer exists for event {event}") from exc
    snapshot_dir = outcome_root / f"event-{event}" / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    live_path = snapshot_dir / "event-live.json"
    if not manifest_path.is_file() or not live_path.is_file():
        raise SnapshotValidationError("the pointed event outcome is incomplete")
    if pointer.get("manifest_sha256") != sha256_file(manifest_path):
        raise SnapshotValidationError("the pointed event outcome manifest changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("event") != event or not manifest.get("publishable"):
        raise SnapshotValidationError("the pointed event outcome is not publishable")
    if manifest.get("event_live_sha256") != sha256_file(live_path):
        raise SnapshotValidationError("the pointed event live data changed")
    live = json.loads(live_path.read_text(encoding="utf-8"))
    return snapshot_dir, manifest, live


def _number(value: Any, *, field: str, event: int, element: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError(
            f"event {event} player {element} has invalid {field}"
        ) from exc


def build_current_player_history(
    *,
    outcome_root: Path = OUTCOME_ROOT,
    pointer_root: Path = POINTER_ROOT,
    output_path: Path = CURRENT_PLAYER_HISTORY,
    receipt_path: Path = CURRENT_PLAYER_HISTORY_RECEIPT,
) -> dict[str, Any]:
    """Normalize every finalized current-season event into one live feature table."""
    pointer_paths = sorted(
        pointer_root.glob("event-*.json"),
        key=lambda path: int(path.stem.split("-")[-1]),
    )
    if not pointer_paths:
        raise SnapshotValidationError("no finalized current-season event outcomes exist")
    rows: list[dict[str, Any]] = []
    sources = []
    for pointer_path in pointer_paths:
        try:
            event = int(pointer_path.stem.split("-")[-1])
        except ValueError as exc:
            raise SnapshotValidationError(
                f"invalid event outcome pointer name: {pointer_path.name}"
            ) from exc
        snapshot_dir, manifest, live = latest_event_outcome(
            event,
            outcome_root=outcome_root,
            pointer_root=pointer_root,
        )
        bootstrap_path_value = manifest.get("bootstrap_path")
        if not bootstrap_path_value:
            raise SnapshotValidationError(
                f"event {event} outcome does not identify its official bootstrap"
            )
        bootstrap_path = Path(str(bootstrap_path_value))
        fixtures_path = bootstrap_path.with_name("fixtures.json")
        if not bootstrap_path.is_file() or not fixtures_path.is_file():
            raise SnapshotValidationError(
                f"event {event} official bootstrap/fixtures lineage is incomplete"
            )
        if manifest.get("bootstrap_sha256") != sha256_file(bootstrap_path):
            raise SnapshotValidationError(f"event {event} official bootstrap changed")
        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
        players = {
            int(player["id"]): player
            for player in bootstrap.get("elements", [])
            if isinstance(player, Mapping)
        }
        team_kickoffs: dict[int, list[datetime]] = {}
        for fixture in fixtures:
            if not isinstance(fixture, Mapping) or fixture.get("event") != event:
                continue
            try:
                kickoff = _aware(str(fixture["kickoff_time"]))
                teams = (int(fixture["team_h"]), int(fixture["team_a"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise SnapshotValidationError(
                    f"event {event} has an invalid official fixture"
                ) from exc
            for team in teams:
                team_kickoffs.setdefault(team, []).append(kickoff)
        if not team_kickoffs:
            raise SnapshotValidationError(f"event {event} has no official fixtures")
        for live_player in live.get("elements", []):
            if not isinstance(live_player, Mapping):
                raise SnapshotValidationError(f"event {event} has an invalid live player row")
            element = int(live_player["id"])
            player = players.get(element)
            stats = live_player.get("stats")
            if player is None or not isinstance(stats, Mapping):
                raise SnapshotValidationError(
                    f"event {event} player {element} lacks official metadata/stats"
                )
            team = int(player["team"])
            kickoffs = team_kickoffs.get(team)
            # A blank is not a zero-minute appearance and must not alter role/form windows.
            if not kickoffs:
                continue
            missing = [source for source in LIVE_STAT_FIELDS.values() if source not in stats]
            if missing:
                raise SnapshotValidationError(
                    f"event {event} player {element} is missing live stats: {missing}"
                )
            position = int(player["element_type"])
            if position not in {1, 2, 3, 4}:
                continue
            row = {
                "season": SEASON,
                "event": event,
                "element": element,
                "player_code": int(player["code"]),
                "player_name": str(
                    player.get("known_name") or player.get("web_name") or f"#{element}"
                ),
                "position": ("GK", "DEF", "MID", "FWD")[position - 1],
                "team_id": team,
                "event_kickoff": min(kickoffs).isoformat(),
                "fixture_count": len(kickoffs),
                "observed_at": str(manifest["observed_at"]),
                "source_event_live_sha256": str(manifest["event_live_sha256"]),
                "source_bootstrap_sha256": str(manifest["bootstrap_sha256"]),
            }
            row.update(
                {
                    target: _number(
                        stats[source],
                        field=source,
                        event=event,
                        element=element,
                    )
                    for target, source in LIVE_STAT_FIELDS.items()
                }
            )
            rows.append(row)
        sources.append(
            {
                "event": event,
                "snapshot": str(snapshot_dir),
                "event_live_sha256": manifest["event_live_sha256"],
                "bootstrap_sha256": manifest["bootstrap_sha256"],
                "fixtures_sha256": sha256_file(fixtures_path),
            }
        )
    rows.sort(key=lambda row: (int(row["event"]), int(row["element"])))
    if not rows:
        raise SnapshotValidationError("current-season player history contains no fixture rows")
    write_rows(rows, output_path)
    events = sorted({int(row["event"]) for row in rows})
    expected_events = list(range(1, max(events) + 1))
    issues = [] if events == expected_events else [
        f"current-season player history events are not contiguous: {events}"
    ]
    receipt = {
        "receipt_version": 1,
        "season": SEASON,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "ready" if not issues else "blocked",
        "events": events,
        "rows": len(rows),
        "players": len({int(row["element"]) for row in rows}),
        "xg_coverage": sum(row["xg"] is not None for row in rows) / len(rows),
        "xa_coverage": sum(row["xa"] is not None for row in rows) / len(rows),
        "defensive_contribution_coverage": sum(
            row["defensive_contribution"] is not None for row in rows
        )
        / len(rows),
        "issues": issues,
        "sources": sources,
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }
    _atomic_json(receipt_path, receipt)
    if issues:
        raise SnapshotValidationError("; ".join(issues))
    return receipt


def collect_event_outcome(
    event: int,
    *,
    observed_at: str | datetime | None = None,
    outcome_root: Path = OUTCOME_ROOT,
    pointer_root: Path = POINTER_ROOT,
    fetcher: Callable[..., Path | None] = download,
) -> dict[str, Any]:
    observed = _aware(observed_at or datetime.now(tz=UTC))
    official_dir, _ = latest_official_snapshot()
    bootstrap_path = official_dir / "bootstrap-static.json"
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    # Fail before network I/O when official finality has not been declared.
    event_row = _event_row(bootstrap, event)
    if event_row.get("finished") is not True or event_row.get("data_checked") is not True:
        raise SnapshotValidationError(f"official event {event} is not final and checked")
    # Download to staging, then let ``archive_event_outcome`` exclusively create
    # the immutable destination. Downloading directly to ``event-live.json`` made
    # the archiver compare the server's whitespace-preserving response with its
    # canonical JSON rendering and report a false content collision.
    with TemporaryDirectory(prefix=f"fpl-event-{event}-") as temporary_dir:
        live_path = fetcher(
            EVENT_LIVE_URL.format(event=event),
            Path(temporary_dir) / "event-live.json",
            force=True,
        )
        if live_path is None:
            raise SnapshotValidationError(
                f"event {event} live data could not be downloaded"
            )
        live = json.loads(Path(live_path).read_text(encoding="utf-8"))
        manifest = archive_event_outcome(
            live,
            bootstrap,
            event=event,
            observed_at=observed,
            outcome_root=outcome_root,
            pointer_root=pointer_root,
            bootstrap_path=bootstrap_path,
        )
    return {
        **manifest,
        "current_player_history": build_current_player_history(
            outcome_root=outcome_root,
            pointer_root=pointer_root,
        ),
    }


def sync_finalized_event_outcomes(
    *,
    observed_at: str | datetime | None = None,
    outcome_root: Path = OUTCOME_ROOT,
    pointer_root: Path = POINTER_ROOT,
    output_path: Path = CURRENT_PLAYER_HISTORY,
    receipt_path: Path = CURRENT_PLAYER_HISTORY_RECEIPT,
    fetcher: Callable[..., Path | None] = download,
) -> dict[str, Any]:
    """Collect any newly finalized events and rebuild current rolling history.

    This is safe to invoke on every app refresh. Already archived immutable
    events are verified and reused; only missing finalized events use the
    network. No live-history file is required before the first final event.
    """
    observed = _aware(observed_at or datetime.now(tz=UTC))
    official_dir, official_manifest = latest_official_snapshot()
    bootstrap = json.loads(
        (official_dir / "bootstrap-static.json").read_text(encoding="utf-8")
    )
    events = bootstrap.get("events")
    if not isinstance(events, list):
        raise SnapshotValidationError("official bootstrap events must be a list")
    finalized = sorted(
        int(row["id"])
        for row in events
        if isinstance(row, Mapping)
        and row.get("finished") is True
        and row.get("data_checked") is True
    )
    collected: list[int] = []
    reused: list[int] = []
    for event in finalized:
        try:
            latest_event_outcome(
                event,
                outcome_root=outcome_root,
                pointer_root=pointer_root,
            )
            reused.append(event)
        except SnapshotValidationError:
            collect_event_outcome(
                event,
                observed_at=observed,
                outcome_root=outcome_root,
                pointer_root=pointer_root,
                fetcher=fetcher,
            )
            collected.append(event)
    if not finalized:
        return {
            "status": "preseason_ready",
            "season": SEASON,
            "official_snapshot": str(official_dir),
            "official_observed_at": official_manifest["observed_at"],
            "finalized_events": [],
            "collected_events": [],
            "reused_events": [],
            "history_required": False,
        }
    history = build_current_player_history(
        outcome_root=outcome_root,
        pointer_root=pointer_root,
        output_path=output_path,
        receipt_path=receipt_path,
    )
    if history["events"] != finalized:
        raise SnapshotValidationError(
            "normalized current-season history does not exactly cover every "
            f"finalized event: expected={finalized}, actual={history['events']}"
        )
    return {
        "status": "ready",
        "season": SEASON,
        "official_snapshot": str(official_dir),
        "official_observed_at": official_manifest["observed_at"],
        "finalized_events": finalized,
        "collected_events": collected,
        "reused_events": reused,
        "history_required": True,
        "history": history,
    }
