from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fplagent_data.live_snapshots import SnapshotValidationError
from fplagent_data.manager_snapshots import (
    archive_manager_snapshot,
    latest_manager_snapshot,
    manager_snapshot_status,
)


def _snapshot(*, observed_at: str = "2026-08-07T12:00:00+00:00") -> dict:
    return {
        "status": "connected",
        "observed_at": observed_at,
        "entry_id": 431892,
        "bank": 15,
        "squad_value": 985,
        "free_transfers": 1,
        "transfer_cost": 0,
        "transfer_cost_per_additional": 4,
        "transfer_limit": 1,
        "transfers_made": 0,
        "transfer_accounting_version": 2,
        "chips": [{"name": "wildcard", "status_for_entry": "available"}],
        "ignored_extra_field": "must not be persisted",
        "picks": [
            {
                "element": 100 + position,
                "position": position,
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
                "purchase_price": 45 + position,
                "selling_price": 45 + position,
                "name": f"Player {position}",
                "team": "Test FC",
                "ignored_pick_field": "drop me",
            }
            for position in range(1, 16)
        ],
    }


def test_manager_snapshot_is_allowlisted_content_locked_and_fresh(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    manifests = tmp_path / "manifests"
    snapshot = _snapshot()

    manifest = archive_manager_snapshot(
        snapshot,
        snapshot_root=root,
        manifest_root=manifests,
    )
    snapshot_dir, loaded_manifest, loaded = latest_manager_snapshot(
        431892,
        snapshot_root=root,
        manifest_root=manifests,
    )
    status = manager_snapshot_status(
        431892,
        as_of="2026-08-07T12:05:00+00:00",
        next_deadline="2026-08-21T17:30:00+00:00",
        snapshot_root=root,
        manifest_root=manifests,
    )

    assert manifest == loaded_manifest
    assert manifest["complete"] is True
    assert manifest["secret_fields_persisted"] is False
    assert len(loaded["picks"]) == 15
    assert "ignored_extra_field" not in loaded
    assert "ignored_pick_field" not in loaded["picks"][0]
    assert status["publishable"] is True
    assert json.loads((snapshot_dir / "manager-state.json").read_text())["bank"] == 15

    changed = _snapshot()
    changed["bank"] = 20
    with pytest.raises(SnapshotValidationError, match="immutable manager snapshot collision"):
        archive_manager_snapshot(
            changed,
            snapshot_root=root,
            manifest_root=manifests,
        )


def test_manager_snapshot_rejects_secret_material_and_illegal_squad(tmp_path: Path) -> None:
    with_secret = _snapshot()
    with_secret["access_token"] = "do-not-store"
    with pytest.raises(SnapshotValidationError, match="forbidden key"):
        archive_manager_snapshot(
            with_secret,
            snapshot_root=tmp_path / "snapshots",
            manifest_root=tmp_path / "manifests",
        )

    illegal = _snapshot()
    illegal["picks"][14]["position"] = 14
    with pytest.raises(SnapshotValidationError, match="positions"):
        archive_manager_snapshot(
            illegal,
            snapshot_root=tmp_path / "snapshots",
            manifest_root=tmp_path / "manifests",
        )


def test_unavailable_preseason_finance_is_archived_but_not_publishable(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot["bank"] = None
    snapshot["squad_value"] = None
    snapshot["free_transfers"] = None
    snapshot["transfer_cost"] = None
    for pick in snapshot["picks"]:
        pick["purchase_price"] = None
    manifest = archive_manager_snapshot(
        snapshot,
        snapshot_root=tmp_path / "snapshots",
        manifest_root=tmp_path / "manifests",
    )
    status = manager_snapshot_status(
        431892,
        as_of="2026-08-07T12:01:00+00:00",
        snapshot_root=tmp_path / "snapshots",
        manifest_root=tmp_path / "manifests",
    )

    assert manifest["complete"] is False
    assert "bank" in manifest["unavailable_fields"]
    assert "picks.purchase_price" in manifest["unavailable_fields"]
    assert status["fresh"] is True
    assert status["publishable"] is False


def test_manager_freshness_uses_the_same_deadline_schedule(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    archive_manager_snapshot(
        _snapshot(observed_at=observed.isoformat()),
        snapshot_root=tmp_path / "snapshots",
        manifest_root=tmp_path / "manifests",
    )
    status = manager_snapshot_status(
        431892,
        as_of=observed + timedelta(minutes=11),
        next_deadline=observed + timedelta(minutes=59),
        snapshot_root=tmp_path / "snapshots",
        manifest_root=tmp_path / "manifests",
    )

    assert status["freshness_limit_seconds"] == 600
    assert status["publishable"] is False
    assert status["issues"] == ["authenticated manager state is stale"]
