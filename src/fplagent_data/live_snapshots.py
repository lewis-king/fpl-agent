from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .catalog import sources
from .http import download, sha256_file
from .paths import MANIFESTS, RAW, ROOT, ensure_layout

SEASON = "2026-27"
REQUIRED_FILES = ("bootstrap-static.json", "fixtures.json")
SNAPSHOT_ROOT = RAW / "fpl" / SEASON / "snapshots" / "live"
CURRENT_POINTER = MANIFESTS / "fpl-current-snapshot.json"
CURRENT_STATUS = MANIFESTS / "fpl-current-status.json"
CURRENT_REFRESH_RECEIPT = MANIFESTS / "fpl-current-refresh.json"


class SnapshotValidationError(ValueError):
    pass


def _aware(value: str | datetime, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SnapshotValidationError(f"{field} must include a timezone")
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


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError(f"invalid JSON file: {path.name}") from exc


def _structural_issues(bootstrap: Any, fixtures: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(bootstrap, Mapping):
        return ["bootstrap-static.json must contain an object"]
    required_lists = ("elements", "teams", "events", "chips", "element_types")
    for field in required_lists:
        value = bootstrap.get(field)
        if not isinstance(value, list) or not value:
            issues.append(f"bootstrap {field} must be a non-empty list")
    game_config = bootstrap.get("game_config")
    if not isinstance(game_config, Mapping):
        issues.append("bootstrap game_config must be an object")
    else:
        for field in ("rules", "scoring", "settings"):
            if not isinstance(game_config.get(field), Mapping):
                issues.append(f"bootstrap game_config.{field} must be an object")
    if not isinstance(fixtures, list) or not fixtures:
        issues.append("fixtures.json must contain a non-empty list")

    teams = bootstrap.get("teams")
    players = bootstrap.get("elements")
    events = bootstrap.get("events")
    if isinstance(teams, list) and teams:
        team_ids = [row.get("id") for row in teams if isinstance(row, Mapping)]
        if len(team_ids) != len(teams) or len(set(team_ids)) != len(team_ids):
            issues.append("team IDs must be present and unique")
        team_id_set = set(team_ids)
        if isinstance(players, list):
            player_ids = [row.get("id") for row in players if isinstance(row, Mapping)]
            if len(player_ids) != len(players) or len(set(player_ids)) != len(player_ids):
                issues.append("player IDs must be present and unique")
            if any(
                row.get("team") not in team_id_set for row in players if isinstance(row, Mapping)
            ):
                issues.append("every player must reference a known team")
        if isinstance(fixtures, list) and any(
            row.get("team_h") not in team_id_set
            or row.get("team_a") not in team_id_set
            or row.get("team_h") == row.get("team_a")
            for row in fixtures
            if isinstance(row, Mapping)
        ):
            issues.append("every fixture must reference two distinct known teams")
    if isinstance(events, list) and events:
        event_ids = [row.get("id") for row in events if isinstance(row, Mapping)]
        if len(event_ids) != len(events) or len(set(event_ids)) != len(event_ids):
            issues.append("event IDs must be present and unique")
        for row in events:
            if not isinstance(row, Mapping):
                issues.append("every event must be an object")
                break
            try:
                _aware(str(row["deadline_time"]), "event deadline_time")
            except (KeyError, SnapshotValidationError, ValueError):
                issues.append("every event must have a valid timezone-aware deadline_time")
                break
    return issues


def _next_deadline(bootstrap: Mapping[str, Any], as_of: datetime) -> datetime | None:
    deadlines = []
    for row in bootstrap.get("events", []):
        if not isinstance(row, Mapping) or not row.get("deadline_time"):
            continue
        try:
            deadline = _aware(str(row["deadline_time"]), "event deadline_time")
        except (SnapshotValidationError, ValueError):
            continue
        if deadline >= as_of:
            deadlines.append(deadline)
    return min(deadlines, default=None)


def freshness_limit(as_of: datetime, next_deadline: datetime | None) -> timedelta:
    if next_deadline is None:
        return timedelta(hours=6)
    time_to_deadline = next_deadline - as_of
    if time_to_deadline <= timedelta(hours=1):
        return timedelta(minutes=10)
    if time_to_deadline <= timedelta(hours=6):
        return timedelta(hours=1)
    if time_to_deadline <= timedelta(hours=24):
        return timedelta(hours=6)
    if time_to_deadline <= timedelta(hours=72):
        return timedelta(hours=24)
    return timedelta(hours=72)


def snapshot_status(
    snapshot_dir: Path,
    *,
    observed_at: str | datetime,
    as_of: str | datetime | None = None,
    expected_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    checked_at = _aware(as_of or datetime.now(tz=UTC), "as_of")
    observed = _aware(observed_at, "observed_at")
    issues: list[str] = []
    if observed > checked_at + timedelta(minutes=5):
        issues.append("snapshot observation time is in the future")

    files: dict[str, dict[str, Any]] = {}
    payloads: dict[str, Any] = {}
    for filename in REQUIRED_FILES:
        path = snapshot_dir / filename
        if not path.is_file() or path.stat().st_size == 0:
            issues.append(f"missing required file: {filename}")
            continue
        checksum = sha256_file(path)
        files[filename] = {"bytes": path.stat().st_size, "sha256": checksum}
        if expected_hashes and expected_hashes.get(filename) != checksum:
            issues.append(f"checksum mismatch: {filename}")
        try:
            payloads[filename] = _load_json(path)
        except SnapshotValidationError as exc:
            issues.append(str(exc))

    bootstrap = payloads.get("bootstrap-static.json")
    fixtures = payloads.get("fixtures.json")
    if bootstrap is not None or fixtures is not None:
        issues.extend(_structural_issues(bootstrap, fixtures))

    complete = not issues
    next_deadline = (
        _next_deadline(bootstrap, checked_at) if isinstance(bootstrap, Mapping) else None
    )
    maximum_age = freshness_limit(checked_at, next_deadline)
    age = max(timedelta(0), checked_at - observed)
    fresh = age <= maximum_age and observed <= checked_at + timedelta(minutes=5)
    if complete and not fresh:
        issues.append(
            f"snapshot is stale: age {int(age.total_seconds())}s exceeds "
            f"{int(maximum_age.total_seconds())}s"
        )
    return {
        "snapshot_id": snapshot_dir.name,
        "season": SEASON,
        "observed_at": observed.isoformat(),
        "checked_at": checked_at.isoformat(),
        "age_seconds": int(age.total_seconds()),
        "next_deadline": next_deadline.isoformat() if next_deadline else None,
        "freshness_limit_seconds": int(maximum_age.total_seconds()),
        "complete": complete,
        "fresh": fresh,
        "publishable": complete and fresh,
        "issues": issues,
        "files": files,
    }


def _write_pointer(
    snapshot_dir: Path,
    manifest: Mapping[str, Any],
    *,
    pointer_path: Path,
) -> None:
    _atomic_json(
        pointer_path,
        {
            "pointer_version": 1,
            "season": SEASON,
            "snapshot_id": snapshot_dir.name,
            "observed_at": manifest["observed_at"],
            "manifest_sha256": sha256_file(snapshot_dir / "manifest.json"),
        },
    )


def archive_official_payloads(
    payloads: Mapping[str, bytes | str | Mapping[str, Any] | list[Any]],
    *,
    observed_at: str | datetime,
    snapshot_root: Path = SNAPSHOT_ROOT,
    pointer_path: Path = CURRENT_POINTER,
    source_urls: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Write an immutable, validated official snapshot and advance the valid pointer."""

    ensure_layout()
    observed = _aware(observed_at, "observed_at")
    snapshot_dir = snapshot_root / _timestamp_id(observed)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_FILES:
        if filename not in payloads:
            raise SnapshotValidationError(f"payload is missing {filename}")
        value = payloads[filename]
        if isinstance(value, bytes):
            encoded = value
        elif isinstance(value, str):
            encoded = value.encode()
        else:
            encoded = (
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
        destination = snapshot_dir / filename
        if destination.exists():
            if destination.read_bytes() != encoded:
                raise SnapshotValidationError(
                    f"immutable snapshot collision for {snapshot_dir.name}/{filename}"
                )
        else:
            _atomic_bytes(destination, encoded)

    status = snapshot_status(
        snapshot_dir,
        observed_at=observed,
        as_of=observed,
    )
    manifest = {
        "manifest_version": 1,
        **status,
        "sources": {filename: (source_urls or {}).get(filename) for filename in REQUIRED_FILES},
    }
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise SnapshotValidationError(
                f"immutable manifest collision for snapshot {snapshot_dir.name}"
            )
    else:
        _atomic_json(manifest_path, manifest)
    if not status["publishable"]:
        raise SnapshotValidationError("; ".join(status["issues"]))
    _write_pointer(snapshot_dir, manifest, pointer_path=pointer_path)
    return manifest


def collect_official_snapshot(
    *,
    observed_at: str | datetime | None = None,
    snapshot_root: Path = SNAPSHOT_ROOT,
    pointer_path: Path = CURRENT_POINTER,
    fetcher: Callable[..., Path | None] = download,
) -> dict[str, Any]:
    observed = _aware(observed_at or datetime.now(tz=UTC), "observed_at")
    urls = sources()["fpl_current"]["files"]
    snapshot_dir = snapshot_root / _timestamp_id(observed)
    if (snapshot_dir / "manifest.json").exists():
        manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
        _write_pointer(snapshot_dir, manifest, pointer_path=pointer_path)
        return manifest
    for filename in REQUIRED_FILES:
        path = fetcher(urls[filename], snapshot_dir / filename, force=False)
        if path is None:
            raise SnapshotValidationError(f"download failed for {filename}")
    payloads = {filename: (snapshot_dir / filename).read_bytes() for filename in REQUIRED_FILES}
    return archive_official_payloads(
        payloads,
        observed_at=observed,
        snapshot_root=snapshot_root,
        pointer_path=pointer_path,
        source_urls=urls,
    )


def latest_official_snapshot(
    *,
    snapshot_root: Path = SNAPSHOT_ROOT,
    pointer_path: Path = CURRENT_POINTER,
) -> tuple[Path, dict[str, Any]]:
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_id = str(pointer["snapshot_id"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError("no valid official snapshot pointer exists") from exc
    snapshot_dir = snapshot_root / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SnapshotValidationError("the pointed official snapshot manifest is missing")
    if pointer.get("manifest_sha256") != sha256_file(manifest_path):
        raise SnapshotValidationError("the pointed official snapshot manifest changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return snapshot_dir, manifest


def latest_official_status(
    *,
    as_of: str | datetime | None = None,
    snapshot_root: Path = SNAPSHOT_ROOT,
    pointer_path: Path = CURRENT_POINTER,
    status_path: Path | None = CURRENT_STATUS,
) -> dict[str, Any]:
    snapshot_dir, manifest = latest_official_snapshot(
        snapshot_root=snapshot_root,
        pointer_path=pointer_path,
    )
    expected_hashes = {
        filename: str(details["sha256"]) for filename, details in manifest["files"].items()
    }
    status = snapshot_status(
        snapshot_dir,
        observed_at=str(manifest["observed_at"]),
        as_of=as_of,
        expected_hashes=expected_hashes,
    )
    if status_path is not None:
        _atomic_json(status_path, status)
    return status


def default_relative_snapshot_path(snapshot_dir: Path) -> str:
    try:
        return snapshot_dir.relative_to(ROOT).as_posix()
    except ValueError:
        return str(snapshot_dir)


def record_refresh_receipt(
    receipt: Mapping[str, Any],
    *,
    path: Path = CURRENT_REFRESH_RECEIPT,
) -> None:
    status = receipt.get("status")
    if not isinstance(status, Mapping) or not status.get("publishable"):
        raise SnapshotValidationError("a refresh receipt requires a publishable snapshot status")
    _atomic_json(path, receipt)
