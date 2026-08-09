from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine.chip_schedule_history import (
    build_historical_chip_schedule_opportunities,
)


def _fixtures(*, observed_at: str = "2024-08-18T12:00:00+00:00") -> list[dict]:
    common = {
        "season": "2024-25",
        "snapshot_sha": "snapshot-a",
        "decision_event": 2.0,
        "deadline_at": datetime(2024, 8, 20, 18, 30, tzinfo=UTC),
        "observed_at": observed_at,
        "provisional_start_time": False,
    }
    return [
        {**common, "id": 1, "event": 2.0, "team_h": 1, "team_a": 2, "kickoff_time": "x"},
        {**common, "id": 2, "event": 2.0, "team_h": 3, "team_a": 4, "kickoff_time": "x"},
        {**common, "id": 3, "event": 3.0, "team_h": 1, "team_a": 2, "kickoff_time": "x"},
        {**common, "id": 4, "event": 3.0, "team_h": 1, "team_a": 3, "kickoff_time": "x"},
        {**common, "id": 5, "event": None, "team_h": 2, "team_a": 4, "kickoff_time": None},
    ]


def test_builds_point_in_time_blank_double_opportunity_ledger(tmp_path) -> None:
    fixture_path = tmp_path / "fixtures.parquet"
    output_path = tmp_path / "opportunities.parquet"
    receipt_path = tmp_path / "receipt.json"
    pq.write_table(pa.Table.from_pylist(_fixtures()), fixture_path)

    receipt = build_historical_chip_schedule_opportunities(
        fixture_path=fixture_path,
        output_path=output_path,
        receipt_path=receipt_path,
    )
    rows = pq.read_table(output_path).to_pylist()
    event_three = next(row for row in rows if row["future_event"] == 3)

    assert receipt["status"] == "ready"
    assert receipt["decision_snapshots"] == 1
    assert receipt["rows"] == 37
    assert event_three["opportunity_kind"] == "blank_and_double"
    assert event_three["blank_team_ids"] == [4]
    assert event_three["double_team_ids"] == [1]
    assert event_three["unassigned_team_ids"] == [2, 4]
    assert event_three["schedule_confirmed"] is False
    assert event_three["within_current_rule_half"] is True
    assert receipt["authority"] is False


def test_rejects_fixture_snapshot_observed_after_decision_deadline(tmp_path) -> None:
    fixture_path = tmp_path / "fixtures.parquet"
    pq.write_table(
        pa.Table.from_pylist(_fixtures(observed_at="2024-08-21T12:00:00+00:00")),
        fixture_path,
    )

    with pytest.raises(ValueError, match="not observed before"):
        build_historical_chip_schedule_opportunities(
            fixture_path=fixture_path,
            output_path=tmp_path / "opportunities.parquet",
            receipt_path=tmp_path / "receipt.json",
        )
