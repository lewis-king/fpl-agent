from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_web.decision_change_probe import DecisionChangeProbe
from fplagent_web.official_change_probe import OfficialChangeProbeResult


def _write_market(path: Path, *, home_rate: float) -> None:
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event": 1,
                    "fixture_id": 10,
                    "market_home_goal_rate": home_rate,
                    "market_away_goal_rate": 1.0,
                    "home_clean_sheet_probability": 0.367879,
                    "away_clean_sheet_probability": 0.223130,
                }
            ]
        ),
        path,
    )


def test_decision_change_probe_combines_official_and_material_market_evidence(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "market.json"
    rates_path = tmp_path / "market.parquet"
    receipt_path.write_text(
        json.dumps(
            {
                "event": 1,
                "ready_events": [1],
                "provider": "betfair_exchange_public_delayed",
                "semantic_fingerprint": "market-old",
            }
        ),
        encoding="utf-8",
    )
    _write_market(rates_path, home_rate=1.5)

    def collect(**_: object) -> dict[str, object]:
        receipt = {
            "event": 1,
            "ready_events": [1],
            "provider": "betfair_exchange_public_delayed",
            "semantic_fingerprint": "market-new",
        }
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        _write_market(rates_path, home_rate=1.65)
        return receipt

    probe = DecisionChangeProbe(
        official_probe=lambda: OfficialChangeProbeResult(
            checked_at="2026-08-10T10:00:00+00:00",
            changed=False,
            local_fingerprint="official-same",
            remote_fingerprint="official-same",
        ),
        market_collector=collect,
        market_receipt_path=receipt_path,
        market_rates_path=rates_path,
        receipt_path=tmp_path / "probe.json",
        event_resolver=lambda: 1,
        clock=lambda: datetime(2026, 8, 10, 10, tzinfo=UTC),
    )

    result = probe.probe()
    receipt = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))

    assert result.changed is True
    assert receipt["official"]["changed"] is False
    assert receipt["market"]["changed"] is True
    assert "team_goal_expectation_moved" in receipt["market"]["reasons"]
