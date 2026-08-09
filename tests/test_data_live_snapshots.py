from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fplagent_data.cli import parser
from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import (
    SnapshotValidationError,
    archive_official_payloads,
    freshness_limit,
    latest_official_snapshot,
    latest_official_status,
    record_refresh_receipt,
)


def _payloads(deadline: str = "2026-08-21T18:30:00+00:00") -> dict:
    return {
        "bootstrap-static.json": {
            "elements": [
                {"id": 101, "team": 1, "web_name": "Home"},
                {"id": 102, "team": 2, "web_name": "Away"},
            ],
            "teams": [
                {"id": 1, "name": "Home FC"},
                {"id": 2, "name": "Away FC"},
            ],
            "events": [{"id": 1, "deadline_time": deadline}],
            "chips": [{"id": 1, "name": "wildcard"}],
            "element_types": [{"id": 1, "singular_name_short": "GKP"}],
            "game_config": {"rules": {}, "scoring": {}, "settings": {}},
        },
        "fixtures.json": [{"id": 1, "event": 1, "team_h": 1, "team_a": 2}],
    }


def test_official_snapshots_are_immutable_idempotent_and_content_locked(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshots"
    pointer = tmp_path / "latest.json"
    observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

    first = archive_official_payloads(
        _payloads(),
        observed_at=observed,
        snapshot_root=root,
        pointer_path=pointer,
    )
    snapshot_dir, loaded = latest_official_snapshot(
        snapshot_root=root,
        pointer_path=pointer,
    )
    original_bootstrap = (snapshot_dir / "bootstrap-static.json").read_bytes()
    repeated = archive_official_payloads(
        _payloads(),
        observed_at=observed,
        snapshot_root=root,
        pointer_path=pointer,
    )

    assert first == repeated == loaded
    assert first["publishable"] is True
    assert (snapshot_dir / "bootstrap-static.json").read_bytes() == original_bootstrap
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert pointer_payload["manifest_sha256"] == sha256_file(snapshot_dir / "manifest.json")

    changed = _payloads()
    changed["bootstrap-static.json"]["elements"][0]["web_name"] = "Changed"
    with pytest.raises(SnapshotValidationError, match="immutable snapshot collision"):
        archive_official_payloads(
            changed,
            observed_at=observed,
            snapshot_root=root,
            pointer_path=pointer,
        )


def test_snapshot_pointer_advances_without_mutating_previous_capture(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    pointer = tmp_path / "latest.json"
    first_observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    archive_official_payloads(
        _payloads(),
        observed_at=first_observed,
        snapshot_root=root,
        pointer_path=pointer,
    )
    first_dir, _ = latest_official_snapshot(snapshot_root=root, pointer_path=pointer)
    first_hash = sha256_file(first_dir / "bootstrap-static.json")

    second_observed = first_observed + timedelta(hours=1)
    archive_official_payloads(
        _payloads(),
        observed_at=second_observed,
        snapshot_root=root,
        pointer_path=pointer,
    )
    second_dir, _ = latest_official_snapshot(snapshot_root=root, pointer_path=pointer)

    assert second_dir != first_dir
    assert first_dir.is_dir()
    assert sha256_file(first_dir / "bootstrap-static.json") == first_hash


def test_invalid_or_corrupted_snapshot_cannot_be_published(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    pointer = tmp_path / "latest.json"
    invalid = _payloads()
    invalid["fixtures.json"][0]["team_a"] = 999
    with pytest.raises(SnapshotValidationError, match="known teams"):
        archive_official_payloads(
            invalid,
            observed_at="2026-08-07T12:00:00+00:00",
            snapshot_root=root,
            pointer_path=pointer,
        )
    assert not pointer.exists()

    archive_official_payloads(
        _payloads(),
        observed_at="2026-08-07T13:00:00+00:00",
        snapshot_root=root,
        pointer_path=pointer,
    )
    snapshot_dir, _ = latest_official_snapshot(snapshot_root=root, pointer_path=pointer)
    (snapshot_dir / "fixtures.json").write_text("[]\n", encoding="utf-8")
    status = latest_official_status(
        as_of="2026-08-07T13:01:00+00:00",
        snapshot_root=root,
        pointer_path=pointer,
        status_path=None,
    )

    assert status["complete"] is False
    assert status["publishable"] is False
    assert any("checksum mismatch" in issue for issue in status["issues"])


def test_freshness_tightens_as_the_deadline_approaches(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    pointer = tmp_path / "latest.json"
    observed = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    archive_official_payloads(
        _payloads(deadline="2026-08-21T18:30:00+00:00"),
        observed_at=observed,
        snapshot_root=root,
        pointer_path=pointer,
    )

    assert freshness_limit(observed, observed + timedelta(minutes=59)) == timedelta(minutes=10)
    status = latest_official_status(
        as_of=observed + timedelta(minutes=11),
        snapshot_root=root,
        pointer_path=pointer,
        status_path=None,
    )
    assert status["freshness_limit_seconds"] == 600
    assert status["fresh"] is False
    assert status["publishable"] is False
    assert "stale" in status["issues"][-1]


def test_refresh_receipt_refuses_non_publishable_status(tmp_path: Path) -> None:
    receipt = {"status": {"publishable": False}, "snapshot_id": "bad"}
    with pytest.raises(SnapshotValidationError, match="publishable"):
        record_refresh_receipt(receipt, path=tmp_path / "receipt.json")


def test_current_snapshot_commands_are_exposed_by_the_data_cli() -> None:
    refresh = parser().parse_args(["refresh-current", "--reuse-latest"])
    status = parser().parse_args(["snapshot-status", "--as-of", "2026-08-07T12:00:00+00:00"])

    assert refresh.command == "refresh-current"
    assert refresh.reuse_latest is True
    assert status.command == "snapshot-status"
    assert status.as_of == "2026-08-07T12:00:00+00:00"
