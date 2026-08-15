from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_engine.market_odds import (
    CURRENT_MARKET_RATES,
    CURRENT_MARKET_RECEIPT,
    assess_current_market_materiality,
    build_current_market_goal_rates,
)
from fplagent_llm.paths import ROOT

from .official_change_probe import OfficialChangeProbe, OfficialChangeProbeResult

DEFAULT_DECISION_PROBE_RECEIPT = (
    ROOT / "data" / "web" / "state" / "decision-change-probe.json"
)


@dataclass(frozen=True)
class DecisionChangeProbeResult:
    checked_at: str
    changed: bool
    local_fingerprint: str
    remote_fingerprint: str


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        return pq.read_table(path).to_pylist()
    except (OSError, ValueError, pa.ArrowException):
        return []


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


class DecisionChangeProbe:
    """Probe official semantics and material market movement without running the optimizer."""

    def __init__(
        self,
        *,
        official_probe: Callable[[], OfficialChangeProbeResult] | None = None,
        market_collector: Callable[..., Mapping[str, Any]] = build_current_market_goal_rates,
        market_receipt_path: Path = CURRENT_MARKET_RECEIPT,
        market_rates_path: Path = CURRENT_MARKET_RATES,
        receipt_path: Path = DEFAULT_DECISION_PROBE_RECEIPT,
        event_resolver: Callable[[], int] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.official_probe = official_probe or OfficialChangeProbe().probe
        self.market_collector = market_collector
        self.market_receipt_path = market_receipt_path
        self.market_rates_path = market_rates_path
        self.receipt_path = receipt_path
        self.event_resolver = event_resolver
        self.clock = clock or (lambda: datetime.now(tz=UTC))

    def probe(self) -> DecisionChangeProbeResult:
        official = self.official_probe()
        previous_receipt = _read_json(self.market_receipt_path)
        previous_rows = _read_rows(self.market_rates_path)
        event = self.event_resolver() if self.event_resolver is not None else None
        collected = dict(self.market_collector(event=event, horizon=1))
        current_receipt = _read_json(self.market_receipt_path) or collected
        current_rows = _read_rows(self.market_rates_path)
        decision_event = int(
            event
            if event is not None
            else current_receipt.get("event")
            or (previous_receipt or {}).get("event")
            or 1
        )
        market = assess_current_market_materiality(
            previous_receipt,
            previous_rows,
            current_receipt,
            current_rows,
            event=decision_event,
        )
        checked = self.clock()
        if checked.tzinfo is None:
            raise ValueError("decision change probe clock must include a timezone")
        checked_at = checked.astimezone(UTC).isoformat()
        local_identity = {
            "official": official.local_fingerprint,
            "market": market.get("previous_fingerprint"),
        }
        remote_identity = {
            "official": official.remote_fingerprint,
            "market": market.get("current_fingerprint"),
        }
        payload = {
            "version": 1,
            "checked_at": checked_at,
            "changed": bool(official.changed or market["changed"]),
            "official": {
                "changed": official.changed,
                "local_fingerprint": official.local_fingerprint,
                "remote_fingerprint": official.remote_fingerprint,
            },
            "market": market,
            "policy": {
                "archive_every_market_observation": True,
                "full_rebuild_only_on_material_change": True,
                "scheduled_deadline_windows_still_force_validation": True,
            },
        }
        _atomic_json(self.receipt_path, payload)
        return DecisionChangeProbeResult(
            checked_at=checked_at,
            changed=payload["changed"],
            local_fingerprint=_fingerprint(local_identity),
            remote_fingerprint=_fingerprint(remote_identity),
        )
