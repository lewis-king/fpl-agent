from __future__ import annotations

import json

import pytest

from fplagent_engine.schedule_scenarios import (
    ScheduleValidationError,
    analyse_schedule_rows,
    compare_schedule_receipts,
    load_schedule_receipt,
    schedule_horizon_status,
)


def _fixtures() -> list[dict]:
    return [
        {
            "id": 1,
            "event": 1,
            "kickoff_time": "2026-08-22T14:00:00+00:00",
            "team_h": 1,
            "team_a": 2,
            "provisional_start_time": False,
        },
        {
            "id": 2,
            "event": 1,
            "kickoff_time": "2026-08-23T14:00:00+00:00",
            "team_h": 1,
            "team_a": 3,
            "provisional_start_time": False,
        },
        {
            "id": 3,
            "event": 2,
            "kickoff_time": None,
            "team_h": 2,
            "team_a": 4,
            "provisional_start_time": True,
        },
        {
            "id": 4,
            "event": None,
            "kickoff_time": None,
            "team_h": 3,
            "team_a": 4,
            "provisional_start_time": False,
        },
    ]


def _by_team_event(receipt: dict) -> dict[tuple[int, int], dict]:
    return {
        (int(row["team_id"]), int(row["event"])): row
        for row in receipt["team_events"]
    }


def test_schedule_classifies_known_doubles_blanks_and_unresolved_fixtures() -> None:
    receipt = analyse_schedule_rows(_fixtures(), team_ids=[1, 2, 3, 4], events=[1, 2])
    rows = _by_team_event(receipt)

    assert receipt["summary"]["confirmed_fixtures"] == 2
    assert receipt["summary"]["provisional_fixtures"] == 1
    assert receipt["summary"]["unassigned_fixtures"] == 1
    assert rows[(1, 1)]["kind"] == "double"
    assert rows[(1, 1)]["schedule_certainty"] == "confirmed"
    assert rows[(1, 2)]["kind"] == "blank"
    assert rows[(1, 2)]["schedule_certainty"] == "confirmed"
    assert rows[(2, 2)]["kind"] == "single"
    assert rows[(2, 2)]["assigned_certainty"] == "provisional"
    assert rows[(3, 2)]["kind"] == "blank"
    assert rows[(3, 2)]["fixture_count"] == 0
    assert rows[(3, 2)]["schedule_certainty"] == "at_risk"
    assert rows[(4, 1)]["kind"] == "blank"
    assert rows[(4, 1)]["schedule_certainty"] == "at_risk"

    team_one = schedule_horizon_status(receipt, events=[1, 2], team_ids=[1])
    unresolved_teams = schedule_horizon_status(receipt, events=[1, 2], team_ids=[3, 4])
    assert team_one["fully_confirmed"] is True
    assert [(row["event"], row["kind"]) for row in team_one["double_team_events"]] == [
        (1, "double")
    ]
    assert unresolved_teams["fully_confirmed"] is False


def test_unassigned_fixture_is_not_speculatively_promoted_to_a_double() -> None:
    receipt = analyse_schedule_rows(_fixtures(), team_ids=[1, 2, 3, 4], events=[1, 2])
    rows = _by_team_event(receipt)

    assert rows[(3, 2)]["fixture_count"] == 0
    assert rows[(4, 1)]["fixture_count"] == 0
    assert not [
        row
        for row in receipt["team_events"]
        if row["team_id"] in {3, 4} and row["kind"] == "double"
    ]


def test_schedule_comparison_identifies_rearranged_fixture_and_events() -> None:
    previous = analyse_schedule_rows(_fixtures(), team_ids=[1, 2, 3, 4], events=[1, 2])
    rearranged = _fixtures()
    rearranged[-1] = {
        **rearranged[-1],
        "event": 2,
        "kickoff_time": "2026-08-30T14:00:00+00:00",
    }
    current = analyse_schedule_rows(rearranged, team_ids=[1, 2, 3, 4], events=[1, 2])

    comparison = compare_schedule_receipts(previous, current)

    assert comparison["changed"] is True
    assert comparison["change_count"] == 1
    assert comparison["affected_events"] == [2]
    assert comparison["affected_teams"] == [3, 4]
    assert comparison["changes"][0]["fields"]["event"] == {
        "before": None,
        "after": 2,
    }
    current_rows = _by_team_event(current)
    assert current_rows[(3, 2)]["kind"] == "single"
    assert current_rows[(4, 2)]["kind"] == "double"


def test_schedule_rejects_duplicate_fixture_ids() -> None:
    fixtures = _fixtures()
    fixtures[-1] = {**fixtures[-1], "id": 1}

    with pytest.raises(ScheduleValidationError, match="duplicate fixture IDs"):
        analyse_schedule_rows(fixtures, team_ids=[1, 2, 3, 4], events=[1, 2])


def test_schedule_loader_rejects_tampered_receipt(tmp_path) -> None:
    path = tmp_path / "schedule.json"
    receipt = analyse_schedule_rows(_fixtures(), team_ids=[1, 2, 3, 4], events=[1, 2])
    receipt["team_events"][0]["fixture_count"] = 99
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ScheduleValidationError, match="fingerprint"):
        load_schedule_receipt(path, expected_fixtures_path=None)
