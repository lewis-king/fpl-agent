from __future__ import annotations

from fplagent_engine.season_state import ChipType, Lineup
from fplagent_engine.team_chip_replay import (
    _actual_uplifts,
    score_team_chip_forecast_oracle,
    score_team_chip_policy,
)


def test_actual_team_chip_uplifts_include_vice_fallback_and_all_fifteen() -> None:
    selected = tuple(range(1, 16))
    lineup = Lineup(
        starters=tuple(range(1, 12)),
        bench_order=(12, 13, 14, 15),
        captain=1,
        vice_captain=2,
    )
    rows = []
    for element in selected:
        rows.append(
            {
                "element": element,
                "target_minutes": 0.0 if element == 1 else 90.0,
                "target_points": 0.0 if element == 1 else 5.0 if element == 2 else 1.0,
            }
        )

    uplifts = _actual_uplifts(selected, lineup, rows, ordinary_gross=16)

    assert uplifts[ChipType.TRIPLE_CAPTAIN.value] == 5
    assert uplifts[ChipType.BENCH_BOOST.value] == 7


def test_team_chip_policy_uses_each_chip_once_per_half() -> None:
    opportunities = []
    for event in range(1, 39):
        half_event = event if event <= 19 else event - 19
        bb = 12.0 if half_event in (5, 6) else 0.0
        tc = 7.0 if half_event in (10, 11) else 0.0
        opportunities.append(
            {
                "event": event,
                "base_net_points": 50,
                "schedule_confirmed": True,
                "forecast_uplifts": {
                    ChipType.BENCH_BOOST.value: bb,
                    ChipType.TRIPLE_CAPTAIN.value: tc,
                },
                "actual_uplifts": {
                    ChipType.BENCH_BOOST.value: 8,
                    ChipType.TRIPLE_CAPTAIN.value: 10,
                },
            }
        )

    result = score_team_chip_policy(
        {"season": "test", "opportunities": opportunities},
        bench_boost_threshold=8.0,
        triple_captain_threshold=5.0,
    )

    assert len(result["chip_events"]) == 4
    assert [(row["event"], row["chip"]) for row in result["chip_events"]] == [
        (5, ChipType.BENCH_BOOST.value),
        (10, ChipType.TRIPLE_CAPTAIN.value),
        (24, ChipType.BENCH_BOOST.value),
        (29, ChipType.TRIPLE_CAPTAIN.value),
    ]
    assert result["chip_uplift"] == 36


def test_team_chip_policy_blocks_unknown_schedule() -> None:
    result = score_team_chip_policy(
        {
            "season": "test",
            "opportunities": [
                {
                    "event": 1,
                    "base_net_points": 50,
                    "schedule_confirmed": False,
                    "forecast_uplifts": {
                        ChipType.BENCH_BOOST.value: 100.0,
                        ChipType.TRIPLE_CAPTAIN.value: 100.0,
                    },
                    "actual_uplifts": {
                        ChipType.BENCH_BOOST.value: 20,
                        ChipType.TRIPLE_CAPTAIN.value: 20,
                    },
                }
            ],
        },
        bench_boost_threshold=8.0,
        triple_captain_threshold=5.0,
    )

    assert result["chip_events"] == []
    assert result["chip_uplift"] == 0


def test_forecast_oracle_retains_each_chip_for_best_distinct_event_per_half() -> None:
    opportunities = []
    for event in range(1, 39):
        bb = 0.0
        tc = 0.0
        if event in (5, 24):
            bb = 20.0
            tc = 19.0
        if event in (6, 25):
            bb = 18.0
            tc = 17.0
        opportunities.append(
            {
                "event": event,
                "base_net_points": 50,
                "schedule_confirmed": True,
                "forecast_uplifts": {
                    ChipType.BENCH_BOOST.value: bb,
                    ChipType.TRIPLE_CAPTAIN.value: tc,
                },
                "actual_uplifts": {
                    ChipType.BENCH_BOOST.value: event,
                    ChipType.TRIPLE_CAPTAIN.value: event + 100,
                },
            }
        )

    result = score_team_chip_forecast_oracle(
        {"season": "test", "opportunities": opportunities}
    )

    assert [(row["event"], row["chip"]) for row in result["chip_events"]] == [
        (5, ChipType.TRIPLE_CAPTAIN.value),
        (6, ChipType.BENCH_BOOST.value),
        (24, ChipType.TRIPLE_CAPTAIN.value),
        (25, ChipType.BENCH_BOOST.value),
    ]
