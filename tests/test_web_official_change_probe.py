from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fplagent_web.official_change_probe import OfficialChangeProbe, _semantic_fingerprint


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


def test_probe_does_not_launch_full_tournament_for_cosmetic_player_identity_changes(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    player = payloads["bootstrap-static.json"]["elements"][0]  # type: ignore[index]
    player.update({"code": 101, "web_name": "Sangare"})
    snapshot = _write_snapshot(tmp_path, payloads)
    remote = _payloads()
    remote_player = remote["bootstrap-static.json"]["elements"][0]  # type: ignore[index]
    remote_player.update({"code": 202, "web_name": "I.Sangare"})

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


@pytest.mark.parametrize("material", [None, "price", "rules", "scoring", "deadline", "status"])
def test_price_check_timestamp_is_not_a_price_change(material):
    payloads = _payloads()
    bootstrap = payloads["bootstrap-static.json"]
    bootstrap["elements"][0]["now_cost"] = 60
    bootstrap["game_config"] = {
        "status": {"price_change_last_updated": "2026-10-16T14:05:15Z"},
        "rules": {"squad_team_limit": 3},
        "scoring": {"assists": 3},
        "settings": {"price_change_deadlines": ["2026-10-16T23:00:00Z"]},
    }
    remote = deepcopy(payloads)
    config = remote["bootstrap-static.json"]["game_config"]
    config["status"]["price_change_last_updated"] = "2026-10-16T14:20:17Z"
    if material == "price":
        remote["bootstrap-static.json"]["elements"][0]["now_cost"] = 59
    elif material == "rules":
        config["rules"]["squad_team_limit"] = 4
    elif material == "scoring":
        config["scoring"]["assists"] = 4
    elif material == "deadline":
        config["settings"]["price_change_deadlines"] = ["2026-10-17T00:00:00Z"]
    elif material == "status":
        config["status"]["unknown_new_flag"] = True
    before = deepcopy(payloads)
    assert (_semantic_fingerprint(payloads) != _semantic_fingerprint(remote)) == (material is not None)
    assert payloads == before  # Fingerprinting must not edit stored evidence.
