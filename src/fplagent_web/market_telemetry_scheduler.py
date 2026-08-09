from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file
from fplagent_data.market_telemetry import (
    build_market_evidence,
    collect_market_observation,
)
from fplagent_llm.paths import ROOT

from .models import MarketTelemetryView

DEFAULT_STATE = ROOT / "data" / "web" / "state" / "market-telemetry.json"
DEFAULT_INTERVAL = timedelta(minutes=15)


class MarketTelemetryScheduler:
    """Collect append-only transfer/price evidence without running the decision engine."""

    def __init__(
        self,
        *,
        collector: Callable[..., Mapping[str, Any]] = collect_market_observation,
        feature_builder: Callable[..., Mapping[str, Any]] = build_market_evidence,
        state_path: Path = DEFAULT_STATE,
        interval: timedelta = DEFAULT_INTERVAL,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if interval <= timedelta(0):
            raise ValueError("market telemetry interval must be positive")
        self.collector = collector
        self.feature_builder = feature_builder
        self.state_path = state_path
        self.interval = interval
        self.clock = clock or (lambda: datetime.now(tz=UTC))
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="fplagent-market-telemetry",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=0.25)
        self._thread = None

    def status(self) -> MarketTelemetryView:
        with self._lock:
            return self._read_state() or MarketTelemetryView(
                status="idle", message="No market observation has been collected yet."
            )

    def tick(self) -> MarketTelemetryView:
        with self._lock:
            now = self._now()
            prior = self._read_state()
            last_attempt = (
                datetime.fromisoformat(prior.last_attempt_at).astimezone(UTC)
                if prior and prior.last_attempt_at
                else None
            )
            next_at = last_attempt + self.interval if last_attempt else now
            if last_attempt is not None and now < next_at:
                return prior.model_copy(
                    update={
                        "checked_at": now.isoformat(),
                        "next_collection_at": next_at.isoformat(),
                    }
                )
            collecting = MarketTelemetryView(
                status="collecting",
                checked_at=now.isoformat(),
                last_attempt_at=now.isoformat(),
                next_collection_at=(now + self.interval).isoformat(),
                message="Collecting the append-only FPL price and transfer observation.",
            )
            self._write_state(collecting)
            try:
                receipt = dict(self.collector(observed_at=now.isoformat()))
                receipt_path = Path(str(receipt["receipt_path"]))
                features = dict(self.feature_builder(as_of=now.isoformat()))
                feature_path = (
                    Path(str(features["output_path"]))
                    if features.get("status") == "ready"
                    else None
                )
                result = collecting.model_copy(
                    update={
                        "status": "collected",
                        "observed_at": str(receipt["observed_at"]),
                        "observation_id": str(receipt["observation_id"]),
                        "rows": int(receipt["rows"]),
                        "receipt_path": str(receipt_path),
                        "receipt_sha256": sha256_file(receipt_path),
                        "feature_status": str(features["status"]),
                        "feature_path": str(feature_path) if feature_path else None,
                        "feature_sha256": (
                            sha256_file(feature_path) if feature_path else None
                        ),
                        "outcome_status": str(
                            (features.get("price_outcomes") or {}).get(
                                "status", "not_ready"
                            )
                        ),
                        "outcome_nights": int(
                            (features.get("price_outcomes") or {}).get(
                                "outcome_nights", 0
                            )
                        ),
                        "message": (
                            f"Captured {int(receipt['rows'])} player market observations; "
                            f"velocity features are {features['status']}; nightly calibration "
                            f"has {int((features.get('price_outcomes') or {}).get('outcome_nights', 0))} nights."
                        ),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - telemetry failure cannot stop the app
                result = collecting.model_copy(
                    update={
                        "status": "error",
                        "message": f"Market telemetry failed safely: {exc}",
                    }
                )
            self._write_state(result)
            return result

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.poll_seconds)

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("market telemetry clock must include a timezone")
        return value.astimezone(UTC)

    def _read_state(self) -> MarketTelemetryView | None:
        if not self.state_path.is_file():
            return None
        try:
            return MarketTelemetryView.model_validate_json(
                self.state_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _write_state(self, state: MarketTelemetryView) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)
