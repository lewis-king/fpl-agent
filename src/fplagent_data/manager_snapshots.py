from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .http import sha256_file
from .live_snapshots import SnapshotValidationError, freshness_limit
from .paths import MANIFESTS, RAW

SEASON = "2026-27"
MANAGER_SNAPSHOT_ROOT = RAW / "fpl" / SEASON / "manager-snapshots"
FORBIDDEN_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "email",
    "password",
    "refresh_token",
    "access_token",
    "id_token",
    "username",
)
TOP_LEVEL_FIELDS = (
    "status",
    "observed_at",
    "entry_id",
    "picks",
    "bank",
    "squad_value",
    "free_transfers",
    "transfer_cost",
    "transfer_cost_per_additional",
    "transfer_limit",
    "transfers_made",
    "transfer_accounting_version",
    "chips",
)
PICK_FIELDS = (
    "element",
    "position",
    "is_captain",
    "is_vice_captain",
    "purchase_price",
    "selling_price",
    "name",
    "team",
)


def _aware(value: str | datetime, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SnapshotValidationError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _timestamp_id(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _reject_secrets(value: Any, path: str = "snapshot") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if any(fragment in normalized for fragment in FORBIDDEN_KEY_FRAGMENTS):
                raise SnapshotValidationError(
                    f"manager snapshot contains forbidden key {path}.{key}"
                )
            _reject_secrets(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secrets(nested, f"{path}[{index}]")


def normalized_manager_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    _reject_secrets(snapshot)
    normalized = {field: snapshot.get(field) for field in TOP_LEVEL_FIELDS}
    picks = snapshot.get("picks")
    if not isinstance(picks, list):
        raise SnapshotValidationError("manager snapshot picks must be a list")
    normalized["picks"] = [
        {field: pick.get(field) for field in PICK_FIELDS}
        for pick in picks
        if isinstance(pick, Mapping)
    ]
    return normalized


def _manager_issues(snapshot: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if snapshot.get("status") != "connected":
        issues.append("manager snapshot must be authenticated")
    try:
        if int(snapshot.get("entry_id", 0)) < 1:
            issues.append("entry_id must be a positive integer")
    except (TypeError, ValueError):
        issues.append("entry_id must be a positive integer")
    try:
        _aware(str(snapshot["observed_at"]), "observed_at")
    except (KeyError, SnapshotValidationError, ValueError):
        issues.append("observed_at must be a timezone-aware timestamp")

    picks = snapshot.get("picks")
    if not isinstance(picks, list) or len(picks) != 15:
        issues.append("manager snapshot must contain exactly 15 picks")
        return issues
    try:
        elements = [int(pick["element"]) for pick in picks]
        positions = [int(pick["position"]) for pick in picks]
    except (KeyError, TypeError, ValueError):
        issues.append("every pick must have integer element and position fields")
        return issues
    if len(set(elements)) != 15 or any(element < 1 for element in elements):
        issues.append("manager snapshot must contain 15 unique positive player IDs")
    if sorted(positions) != list(range(1, 16)):
        issues.append("manager snapshot positions must be exactly 1 through 15")
    captains = [pick for pick in picks if pick.get("is_captain")]
    vice_captains = [pick for pick in picks if pick.get("is_vice_captain")]
    if len(captains) != 1 or len(vice_captains) != 1:
        issues.append("manager snapshot requires exactly one captain and vice-captain")
    elif captains[0]["element"] == vice_captains[0]["element"]:
        issues.append("captain and vice-captain must differ")
    elif int(captains[0]["position"]) > 11 or int(vice_captains[0]["position"]) > 11:
        issues.append("captain and vice-captain must be in the starting XI")
    for field in ("purchase_price", "selling_price"):
        if any(
            pick.get(field) is not None
            and (
                isinstance(pick.get(field), bool)
                or not isinstance(pick.get(field), int)
                or int(pick[field]) < 0
            )
            for pick in picks
        ):
            issues.append(f"every available {field} must be a non-negative integer")
    for field in ("bank", "squad_value"):
        value = snapshot.get(field)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            issues.append(f"{field} must be null or a non-negative integer")
    for field in (
        "free_transfers",
        "transfer_cost",
        "transfer_cost_per_additional",
        "transfer_limit",
        "transfers_made",
        "transfer_accounting_version",
    ):
        value = snapshot.get(field)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            issues.append(f"{field} must be null or a non-negative integer")
    if not isinstance(snapshot.get("chips"), list):
        issues.append("chips must be a list")
    return issues


def _unavailable_fields(snapshot: Mapping[str, Any]) -> list[str]:
    unavailable = [
        field
        for field in ("bank", "squad_value", "free_transfers", "transfer_cost")
        if snapshot.get(field) is None
    ]
    picks = snapshot.get("picks", [])
    for field in ("purchase_price", "selling_price"):
        if any(pick.get(field) is None for pick in picks):
            unavailable.append(f"picks.{field}")
    return unavailable


def manager_pointer_path(entry_id: int, manifest_root: Path = MANIFESTS) -> Path:
    return manifest_root / f"fpl-manager-{entry_id}-snapshot.json"


def archive_manager_snapshot(
    snapshot: Mapping[str, Any],
    *,
    snapshot_root: Path = MANAGER_SNAPSHOT_ROOT,
    manifest_root: Path = MANIFESTS,
) -> dict[str, Any]:
    normalized = normalized_manager_snapshot(snapshot)
    issues = _manager_issues(normalized)
    if issues:
        raise SnapshotValidationError("; ".join(issues))
    observed = _aware(str(normalized["observed_at"]), "observed_at")
    entry_id = int(normalized["entry_id"])
    snapshot_id = _timestamp_id(observed)
    snapshot_dir = snapshot_root / str(entry_id) / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    payload_path = snapshot_dir / "manager-state.json"
    rendered = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if payload_path.exists():
        if payload_path.read_text(encoding="utf-8") != rendered:
            raise SnapshotValidationError(
                f"immutable manager snapshot collision for entry {entry_id} at {snapshot_id}"
            )
    else:
        temporary = payload_path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(payload_path)
    unavailable_fields = _unavailable_fields(normalized)
    manifest = {
        "manifest_version": 1,
        "season": SEASON,
        "snapshot_id": snapshot_id,
        "entry_id": entry_id,
        "observed_at": observed.isoformat(),
        "source": "local-mcp:get_manager_snapshot",
        "player_count": 15,
        "manager_state_sha256": sha256_file(payload_path),
        "secret_fields_persisted": False,
        "complete": not unavailable_fields,
        "unavailable_fields": unavailable_fields,
    }
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise SnapshotValidationError(
                f"immutable manager manifest collision for entry {entry_id} at {snapshot_id}"
            )
    else:
        _atomic_json(manifest_path, manifest)
    pointer = manager_pointer_path(entry_id, manifest_root)
    _atomic_json(
        pointer,
        {
            "pointer_version": 1,
            "season": SEASON,
            "entry_id": entry_id,
            "snapshot_id": snapshot_id,
            "observed_at": observed.isoformat(),
            "manifest_sha256": sha256_file(manifest_path),
        },
    )
    return manifest


def latest_manager_snapshot(
    entry_id: int,
    *,
    snapshot_root: Path = MANAGER_SNAPSHOT_ROOT,
    manifest_root: Path = MANIFESTS,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    pointer_path = manager_pointer_path(entry_id, manifest_root)
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_id = str(pointer["snapshot_id"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError(f"no manager snapshot exists for entry {entry_id}") from exc
    snapshot_dir = snapshot_root / str(entry_id) / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    payload_path = snapshot_dir / "manager-state.json"
    if not manifest_path.is_file() or not payload_path.is_file():
        raise SnapshotValidationError("the pointed manager snapshot is incomplete")
    if pointer.get("manifest_sha256") != sha256_file(manifest_path):
        raise SnapshotValidationError("the pointed manager snapshot manifest changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = json.loads(payload_path.read_text(encoding="utf-8"))
    if manifest.get("manager_state_sha256") != sha256_file(payload_path):
        raise SnapshotValidationError("the pointed manager state changed")
    issues = _manager_issues(snapshot)
    if issues:
        raise SnapshotValidationError("; ".join(issues))
    return snapshot_dir, manifest, snapshot


def manager_snapshot_status(
    entry_id: int,
    *,
    as_of: str | datetime | None = None,
    next_deadline: str | datetime | None = None,
    snapshot_root: Path = MANAGER_SNAPSHOT_ROOT,
    manifest_root: Path = MANIFESTS,
) -> dict[str, Any]:
    _, manifest, _ = latest_manager_snapshot(
        entry_id,
        snapshot_root=snapshot_root,
        manifest_root=manifest_root,
    )
    checked = _aware(as_of or datetime.now(tz=UTC), "as_of")
    observed = _aware(str(manifest["observed_at"]), "observed_at")
    deadline = _aware(next_deadline, "next_deadline") if next_deadline else None
    limit = freshness_limit(checked, deadline)
    age = max(timedelta(0), checked - observed)
    fresh = observed <= checked + timedelta(minutes=5) and age <= limit
    return {
        "entry_id": entry_id,
        "snapshot_id": manifest["snapshot_id"],
        "observed_at": observed.isoformat(),
        "checked_at": checked.isoformat(),
        "age_seconds": int(age.total_seconds()),
        "freshness_limit_seconds": int(limit.total_seconds()),
        "complete": bool(manifest["complete"]),
        "fresh": fresh,
        "publishable": fresh and bool(manifest["complete"]),
        "issues": (
            ([] if fresh else ["authenticated manager state is stale"])
            + [
                f"authenticated manager state is missing {field}"
                for field in manifest.get("unavailable_fields", [])
            ]
        ),
    }
