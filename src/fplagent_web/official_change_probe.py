from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.catalog import sources
from fplagent_data.http import USER_AGENT
from fplagent_data.live_snapshots import REQUIRED_FILES, latest_official_snapshot


@dataclass(frozen=True)
class OfficialChangeProbeResult:
    checked_at: str
    changed: bool
    local_fingerprint: str
    remote_fingerprint: str


ELEMENT_FIELDS = (
    "id",
    "team",
    "element_type",
    "now_cost",
    "status",
    "news",
    "news_added",
    "chance_of_playing_this_round",
    "chance_of_playing_next_round",
    "can_select",
    "removed",
    "penalties_order",
    "corners_and_indirect_freekicks_order",
)
EVENT_FIELDS = (
    "id",
    "name",
    "deadline_time",
    "finished",
    "data_checked",
    "is_previous",
    "is_current",
    "is_next",
)
FIXTURE_FIELDS = (
    "id",
    "event",
    "kickoff_time",
    "provisional_start_time",
    "started",
    "finished",
    "finished_provisional",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
)


def _project_rows(rows: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise TypeError("official change probe expected a list")
    return [
        {field: row.get(field) for field in fields}
        for row in rows
        if isinstance(row, Mapping)
    ]


def _decision_relevant_payloads(payloads: Mapping[str, Any]) -> dict[str, Any]:
    bootstrap = payloads.get("bootstrap-static.json")
    fixtures = payloads.get("fixtures.json")
    if not isinstance(bootstrap, Mapping) or not isinstance(fixtures, list):
        raise TypeError("official change probe received invalid FPL payload shapes")
    config = bootstrap.get("game_config")
    if isinstance(config, Mapping):
        config = dict(config)
        status = config.get("status")
        if isinstance(status, Mapping):
            # FPL advances this bookkeeping timestamp even when no price has
            # changed. Actual prices remain fingerprinted via elements.now_cost.
            # Preserve every other status/config key, including unknown ones.
            config["status"] = {
                key: value for key, value in status.items()
                if key != "price_change_last_updated"
            }
    return {
        "bootstrap-static.json": {
            "elements": _project_rows(bootstrap.get("elements"), ELEMENT_FIELDS),
            "events": _project_rows(bootstrap.get("events"), EVENT_FIELDS),
            "teams": bootstrap.get("teams"),
            "chips": bootstrap.get("chips"),
            "element_types": bootstrap.get("element_types"),
            "game_config": config,
        },
        "fixtures.json": _project_rows(fixtures, FIXTURE_FIELDS),
    }


def _semantic_fingerprint(payloads: Mapping[str, Any]) -> str:
    payloads = _decision_relevant_payloads(payloads)
    digest = hashlib.sha256()
    for filename in REQUIRED_FILES:
        if filename not in payloads:
            raise ValueError(f"official change probe is missing {filename}")
        rendered = json.dumps(
            payloads[filename],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(rendered)
        digest.update(b"\0")
    return digest.hexdigest()


def _download_bytes(url: str, *, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class OfficialChangeProbe:
    """Compare public FPL payload semantics without advancing the active snapshot."""

    def __init__(
        self,
        *,
        fetcher: Callable[[str], bytes] | None = None,
        snapshot_loader: Callable[[], tuple[Path, Mapping[str, Any]]] = (
            latest_official_snapshot
        ),
        timeout_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.fetcher = fetcher or (
            lambda url: _download_bytes(url, timeout=self.timeout_seconds)
        )
        self.snapshot_loader = snapshot_loader
        self.clock = clock or (lambda: datetime.now(tz=UTC))

    def probe(self) -> OfficialChangeProbeResult:
        snapshot_dir, _ = self.snapshot_loader()
        urls = sources()["fpl_current"]["files"]
        local_payloads = {
            filename: json.loads((snapshot_dir / filename).read_text(encoding="utf-8"))
            for filename in REQUIRED_FILES
        }
        remote_payloads: dict[str, Any] = {}
        for filename in REQUIRED_FILES:
            payload = json.loads(self.fetcher(str(urls[filename])))
            if filename == "bootstrap-static.json" and not isinstance(payload, Mapping):
                raise ValueError("remote bootstrap payload is not an object")
            if filename == "fixtures.json" and not isinstance(payload, list):
                raise ValueError("remote fixtures payload is not a list")
            remote_payloads[filename] = payload
        checked = self.clock()
        if checked.tzinfo is None:
            raise ValueError("official change probe clock must include a timezone")
        local_fingerprint = _semantic_fingerprint(local_payloads)
        remote_fingerprint = _semantic_fingerprint(remote_payloads)
        return OfficialChangeProbeResult(
            checked_at=checked.astimezone(UTC).isoformat(),
            changed=local_fingerprint != remote_fingerprint,
            local_fingerprint=local_fingerprint,
            remote_fingerprint=remote_fingerprint,
        )
