from datetime import UTC, datetime

import duckdb
import pytest

from fplagent_data.availability import official_availability
from fplagent_data.participation_consensus import _event_context, _official_status
from fplagent_engine.component_models import component_role_ratio
from fplagent_engine.deadline_evidence import availability_violations
from fplagent_engine.features import _current_query
from fplagent_engine.forecast_diagnosis import error_summary, historical_next_chance
from fplagent_engine.models import _apply_official_selection_gate
from fplagent_engine.participation_policy import apply_current_participation_policy


@pytest.mark.parametrize("previous,next_chance", [(100, 0), (0, 100), (75, 25), (0, None)])
def test_no_cross_round_fallback(previous, next_chance):
    player = {
        "status": "a",
        "chance_of_playing_this_round": previous,
        "chance_of_playing_next_round": next_chance,
    }
    expected = next_chance if next_chance is not None else 100
    assert official_availability(player) == expected
    assert _official_status(player)[1] == expected
    assert official_availability(player, next_round=False) == previous


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 101])
def test_invalid_official_probability_fails(bad):
    with pytest.raises(ValueError):
        official_availability({"chance_of_playing_next_round": bad})


def test_next_event_wins_over_running_current_event():
    events = [
        {"id": 7, "is_current": True, "deadline_time": "2026-10-17T10:00:00Z"},
        {"id": 8, "is_next": True, "deadline_time": "2026-10-23T17:30:00Z"},
    ]
    assert _event_context(events, [], None)[0] == 8


@pytest.mark.parametrize("start", [1, 3, 8, 19, 20, 38])
def test_sql_availability_is_relative_to_actionable_event(start):
    # Execute the actual expression from production, not a string-only assertion.
    query = _current_query(1, start_event=start)
    expression = query[
        query.index("CASE\n                -- FPL can keep") : query.index(
            "END AS availability_chance"
        )
        + 3
    ]
    c = duckdb.connect()
    try:
        for event, expected in [(start, 0), (start + 1, 0), (start + 3, 85)]:
            got = c.execute(
                f"SELECT {expression} FROM (SELECT true can_select, 'i' status, 100 chance_of_playing_this_round, 0 chance_of_playing_next_round) p CROSS JOIN (SELECT {event} event_number) h"
            ).fetchone()[0]
            assert got == expected
    finally:
        c.close()


def test_zero_is_enforced_even_with_missing_lineup_sources(tmp_path):
    original = {
        "event_number": 8,
        "element": 1,
        "position": "MID",
        "can_select": True,
        "official_availability_event": 8,
        "official_availability_chance": 0,
        "p_dnp": 0.1,
        "p_1_59": 0.1,
        "p_60_89": 0.4,
        "p_90_or_more": 0.4,
        "p_play": 0.9,
        "expected_points": 5,
        "robust_points": 4.9,
    }
    role_rows, _ = apply_current_participation_policy(
        [original],
        receipt_path=tmp_path / "missing.json",
        consensus_path=tmp_path / "missing.parquet",
        as_of=datetime(2026, 10, 21, tzinfo=UTC),
    )
    fixed, count = _apply_official_selection_gate(role_rows)
    assert count == 1 and fixed[0]["p_play"] == fixed[0]["expected_points"] == 0
    assert fixed[0]["live_role_minutes_ratio"] == 0
    future, count = _apply_official_selection_gate([{**original, "event_number": 9}])
    assert count == 0 and future[0]["expected_points"] == 5
    assert original["expected_points"] == 5


def test_raw_official_publication_check_catches_incorrect_forecast_flags():
    bootstrap = {
        "events": [{"id": 8, "is_next": True}],
        "elements": [
            {
                "id": 1,
                "status": "i",
                "chance_of_playing_this_round": 100,
                "chance_of_playing_next_round": 0,
            }
        ],
    }
    row = {"event_number": 8, "element": 1, "p_play": 0.75, "expected_points": 2.7}
    assert len(availability_violations(bootstrap, [row])) == 2
    assert not availability_violations(bootstrap, [{**row, "p_play": 0, "expected_points": 0}])
    assert not availability_violations(bootstrap, [{**row, "event_number": 9}])


@pytest.mark.parametrize("value,expected", [(None, 1), (0, 0), (0.35, 0.35)])
def test_zero_component_role_ratio_is_not_missing(value, expected):
    assert component_role_ratio({"p_play": 0.9, "live_role_minutes_ratio": value}) == expected
    assert component_role_ratio({"p_play": 0, "live_role_minutes_ratio": value}) == 0


def test_error_decomposition_and_missing_minutes():
    rows = [
        {
            "actual_points": 0,
            "expected_points": 4,
            "p_play": 0.8,
            "actual_minutes": 0,
            "expected_minutes": None,
        },
        {
            "actual_points": 7,
            "expected_points": 4,
            "p_play": 0.8,
            "actual_minutes": 90,
            "expected_minutes": 70,
        },
    ]
    result = error_summary(rows)
    assert result["appearance_error_sum"] + result[
        "conditional_performance_error_sum"
    ] == pytest.approx(-1)
    assert result["minutes"] == {"rows": 1, "mae": 20, "bias_actual_minus_expected": 20}


def test_historical_chance_requires_dated_explicit_observation():
    row = {
        "observed_at": "2025-09-01T10:00:00Z",
        "deadline_at": "2025-09-02T10:00:00Z",
        "chance_of_playing_next_round": "0",
        "chance_of_playing_this_round": "100",
    }
    assert historical_next_chance(row) == 0
    assert historical_next_chance({**row, "chance_of_playing_next_round": None}) is None
    assert historical_next_chance({**row, "chance_of_playing_next_round": "None"}) is None
    assert historical_next_chance({**row, "deadline_at": row["observed_at"]}) is None
    assert historical_next_chance({**row, "deadline_at": "2025-10-02T10:00:00Z"}) is None
