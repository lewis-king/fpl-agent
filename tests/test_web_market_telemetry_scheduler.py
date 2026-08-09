from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fplagent_web.market_telemetry_scheduler import MarketTelemetryScheduler


def test_market_scheduler_collects_once_per_fifteen_minute_window(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 8, 10, tzinfo=UTC)]
    calls: list[str] = []

    def collector(*, observed_at: str) -> dict[str, Any]:
        calls.append(observed_at)
        receipt_path = tmp_path / f"receipt-{len(calls)}.json"
        receipt_path.write_text("{}\n", encoding="utf-8")
        return {
            "observed_at": observed_at,
            "observation_id": f"observation-{len(calls)}",
            "rows": 640,
            "receipt_path": str(receipt_path),
        }

    scheduler = MarketTelemetryScheduler(
        collector=collector,
        feature_builder=lambda **_: {"status": "not_ready"},
        state_path=tmp_path / "state.json",
        clock=lambda: now[0],
    )

    first = scheduler.tick()
    now[0] += timedelta(minutes=10)
    held = scheduler.tick()
    now[0] += timedelta(minutes=5)
    second = scheduler.tick()

    assert first.status == "collected"
    assert first.rows == 640
    assert held.observation_id == "observation-1"
    assert held.next_collection_at == "2026-08-08T10:15:00+00:00"
    assert second.observation_id == "observation-2"
    assert len(calls) == 2


def test_market_scheduler_fails_safely_and_retries_on_next_window(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 8, 10, tzinfo=UTC)]
    calls = 0

    def failed_collector(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    scheduler = MarketTelemetryScheduler(
        collector=failed_collector,
        state_path=tmp_path / "state.json",
        clock=lambda: now[0],
    )

    failed = scheduler.tick()
    now[0] += timedelta(minutes=14)
    held = scheduler.tick()
    now[0] += timedelta(minutes=1)
    retried = scheduler.tick()

    assert failed.status == "error"
    assert "failed safely" in failed.message
    assert held.status == "error"
    assert retried.status == "error"
    assert calls == 2
