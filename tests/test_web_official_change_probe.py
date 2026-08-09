from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fplagent_web.official_change_probe import OfficialChangeProbe


def _payloads() -> dict[str, object]:
    return {
        "bootstrap-static.json": {
            "elements": [
                {
                    "id": 1,
                    "status": "a",
                    "news": "",
                    "transfers_in_event": 100,
                }
            ],
            "events": [{"id": 1}],
        },
        "fixtures.json": [{"id": 10, "event": 1}],
    }


def _write_snapshot(tmp_path: Path, payloads: dict[str, object]) -> Path:
    for filename, payload in payloads.items():
        (tmp_path / filename).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    return tmp_path


def test_probe_ignores_json_formatting_when_official_semantics_are_unchanged(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    snapshot = _write_snapshot(tmp_path, payloads)

    probe = OfficialChangeProbe(
        fetcher=lambda url: json.dumps(
            payloads[
                "bootstrap-static.json"
                if "bootstrap-static" in url
                else "fixtures.json"
            ],
            separators=(",", ":"),
        ).encode(),
        snapshot_loader=lambda: (snapshot, {}),
        clock=lambda: datetime(2026, 8, 8, 10, tzinfo=UTC),
    ).probe()

    assert probe.changed is False
    assert probe.local_fingerprint == probe.remote_fingerprint


def test_probe_detects_material_player_status_change(tmp_path: Path) -> None:
    payloads = _payloads()
    snapshot = _write_snapshot(tmp_path, payloads)
    remote = _payloads()
    remote["bootstrap-static.json"]["elements"][0]["status"] = "d"  # type: ignore[index]

    probe = OfficialChangeProbe(
        fetcher=lambda url: json.dumps(
            remote[
                "bootstrap-static.json"
                if "bootstrap-static" in url
                else "fixtures.json"
            ]
        ).encode(),
        snapshot_loader=lambda: (snapshot, {}),
        clock=lambda: datetime(2026, 8, 8, 10, tzinfo=UTC),
    ).probe()

    assert probe.changed is True
    assert probe.local_fingerprint != probe.remote_fingerprint


def test_probe_does_not_launch_full_tournament_for_transfer_counter_noise(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    snapshot = _write_snapshot(tmp_path, payloads)
    remote = _payloads()
    remote["bootstrap-static.json"]["elements"][0]["transfers_in_event"] = 101  # type: ignore[index]

    probe = OfficialChangeProbe(
        fetcher=lambda url: json.dumps(
            remote[
                "bootstrap-static.json"
                if "bootstrap-static" in url
                else "fixtures.json"
            ]
        ).encode(),
        snapshot_loader=lambda: (snapshot, {}),
        clock=lambda: datetime(2026, 8, 8, 10, tzinfo=UTC),
    ).probe()

    assert probe.changed is False
