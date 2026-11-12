from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_engine_chip_strategy import _live_calibration, _selected_action
from test_engine_weekly_simulation import _rows, _state

from fplagent_engine.chip_strategy import _chip_deadline_plan, synthesize_joint_chip_strategy
from fplagent_engine.chip_timing import (
    VERSION,
    load_live_timing,
    next_deadline_gap_days,
    squad_fingerprint,
    timing_verdict,
    wait_margin,
)
from fplagent_engine.season_state import ChipStatus


def _group(name, week, mean, lo, hi):
    return {"group": name, "wildcard_event": week, "validation_mean": mean, "mc95": [lo, hi]}


def test_wildcard_now_requires_edge_beyond_the_value_of_waiting():
    groups = [_group("wc_now", 10, 617.8, 2.9, 3.35), _group("roll", 11, 614.7, 0.0, 0.0)]
    # The GW10 2026/27 case: +3.1 now, but GW11 follows an international break.
    held = timing_verdict(groups, event=10, next_gap_days=15)
    assert held["play_now"] is False
    assert held["best_wildcard_event"] == 11
    assert held["required_waiting_margin"] == 4.0
    # The same edge in an ordinary week clears the 2-point margin.
    assert timing_verdict(groups, event=10, next_gap_days=7)["play_now"] is True


def test_wildcard_now_needs_holdout_separation():
    groups = [_group("wc_now", 10, 620.0, -1.0, 9.0), _group("roll", 11, 614.0, 0.0, 0.5)]
    verdict = timing_verdict(groups, event=10, next_gap_days=7)
    assert verdict["holdout_separated"] is False
    assert verdict["play_now"] is False


def test_later_week_wins_when_now_is_worse():
    groups = [_group("wc_now", 10, 600.0, -5, -4), _group("o1", 13, 610.0, 1, 2),
              _group("roll", 12, 608.0, 0, 0)]
    verdict = timing_verdict(groups, event=10, next_gap_days=7)
    assert verdict["play_now"] is False
    assert verdict["best_wildcard_event"] == 13


def test_wait_margin_and_gap():
    assert wait_margin(None) == 2.0
    assert wait_margin(6.0) == 2.0
    assert wait_margin(15.0) == 4.0
    fixtures = [{"event": 10, "kickoff_time": "2026-11-07T12:30:00Z"},
                {"event": 10, "kickoff_time": "2026-11-08T14:00:00Z"},
                {"event": 11, "kickoff_time": "2026-11-21T12:30:00Z"}]
    assert next_deadline_gap_days(fixtures, 10) == pytest.approx(14.0)
    assert next_deadline_gap_days(fixtures, 11) is None


def test_live_timing_is_bound_to_event_squad_and_age(tmp_path):
    path = tmp_path / "timing.json"
    made = datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    path.write_text(json.dumps({"version": VERSION, "decision_event": 10, "status": "completed",
                                "created_at": made.isoformat(), "squad_fingerprint": "abc",
                                "verdict": {"play_now": False}}))
    soon = made + timedelta(hours=2)
    assert load_live_timing(event=10, fingerprint="abc", path=path, now=soon)
    assert load_live_timing(event=11, fingerprint="abc", path=path, now=soon) is None
    assert load_live_timing(event=10, fingerprint="other", path=path, now=soon) is None
    assert load_live_timing(event=10, fingerprint="abc", path=path,
                            now=made + timedelta(hours=13)) is None
    assert load_live_timing(event=10, fingerprint="abc", path=tmp_path / "missing.json") is None


def test_squad_fingerprint_ignores_resync_noise_but_not_squad_changes():
    state = _state()
    assert squad_fingerprint(state) == squad_fingerprint(replace(state))
    assert squad_fingerprint(state) != squad_fingerprint(replace(state, bank=state.bank + 1))
    assert squad_fingerprint(state) != squad_fingerprint(
        replace(state, free_transfers=state.free_transfers + 1))


def _wildcard_shadow(delta=60.0, ci_low=58.0):
    return {"candidates": [{
        "action_id": "wildcard-route", "chip": "wildcard",
        "weighted_raw_delta_to_best_ordinary": delta,
        "scenario_metrics": {"residual": {
            "mean_raw_delta_to_best_ordinary": delta, "raw_delta_95ci_low": ci_low}}}]}


_SCHEDULE = {"event_summaries": [{"event": 2, "blank_teams": [], "double_teams": [],
                                  "at_risk_teams": []}]}


@pytest.mark.parametrize("play_now,expected", [(True, "wildcard"), (False, "no_chip")])
def test_live_wildcard_follows_the_timing_verdict(play_now, expected):
    result = synthesize_joint_chip_strategy(
        state=_state(), selected_action=_selected_action(), forecast_rows=_rows(),
        team_shadow={}, squad_shadow=_wildcard_shadow(), schedule_receipt=_SCHEDULE,
        calibration=_live_calibration(),
        squad_timing={"version": VERSION,
                      "verdict": {"play_now": play_now, "best_wildcard_event": 2 if play_now else 7}},
    )
    assert result["operational_recommendation"] == expected
    wc = next(r for r in result["deadline_plan"] if r["chip"] == "wildcard")
    assert wc["planned_event"] == (2 if play_now else 7)


def test_expiry_forces_the_best_chip_when_chips_fill_every_remaining_week():
    selected = _selected_action()
    selected = replace(selected, lineups=(replace(selected.lineups[0], event=16),))
    rows = [dict(r, event_number=16) for r in _rows() if r["event_number"] == 2]
    state = replace(_state(), event=16, chips=tuple(
        replace(slot, status=ChipStatus.AVAILABLE) if slot.half == 1 else slot
        for slot in _state().chips))
    # Weak, uncertain Wildcard: fails the uncertainty gate and has no timing
    # verdict. With 4 chips for GW16-19 it must still be played, not lost.
    result = synthesize_joint_chip_strategy(
        state=state, selected_action=selected, forecast_rows=rows,
        team_shadow={}, squad_shadow=_wildcard_shadow(delta=3.0, ci_low=-2.0),
        schedule_receipt={}, calibration=_live_calibration(),
    )
    assert result["expiry_binding"] is True
    assert result["expiry_forced"] is True
    assert result["operational_recommendation"] == "wildcard"
    assert "so no chip is lost" in result["reason"]


def test_no_forcing_while_spare_weeks_remain():
    result = synthesize_joint_chip_strategy(
        state=_state(), selected_action=_selected_action(), forecast_rows=_rows(),
        team_shadow={}, squad_shadow=_wildcard_shadow(delta=3.0, ci_low=-2.0),
        schedule_receipt=_SCHEDULE, calibration=_live_calibration(),
    )
    assert result["expiry_binding"] is False
    assert result["operational_recommendation"] == "no_chip"


@pytest.mark.parametrize("event", [10, 14, 16, 19])
def test_deadline_plan_is_always_feasible(event):
    chips = ["bench_boost", "free_hit", "triple_captain", "wildcard"][: max(1, min(4, 20 - event))]
    plan = _chip_deadline_plan(
        available=chips, event=event, half_end=19, promoted_chip=None,
        retention_calendar={"allocations": [{"chip": "bench_boost", "event": min(event + 1, 19)},
                                            {"chip": "triple_captain", "event": min(event + 1, 19)}]},
        timing_verdict={"best_wildcard_event": min(event + 1, 19)},
    )
    weeks = [r["planned_event"] for r in plan]
    assert len(set(weeks)) == len(weeks) == len(chips)
    assert all(event <= w <= 19 for w in weeks)
    assert all(r["planned_event"] <= r["latest_safe_event"] or r["planned_event"] == event
               for r in plan)


def test_chip_calendar_places_each_chip_in_its_best_distinct_week():
    from fplagent_engine.chip_timing import optimise_chip_calendar

    gains = {"bench_boost": {11: 9.0, 13: 14.0, 14: 12.0},
             "triple_captain": {11: 7.0, 13: 9.0, 14: 6.0},
             "free_hit": {11: 4.0, 13: 5.0, 14: 8.0}}
    total, plan = optimise_chip_calendar(gains)
    # Bench Boost and Triple Captain both peak in GW13; only one can have it.
    assert plan == {"bench_boost": 13, "triple_captain": 11, "free_hit": 14}
    assert total == 29.0
    assert optimise_chip_calendar(gains, fixed={"bench_boost": 11})[1]["bench_boost"] == 11
    assert optimise_chip_calendar({"bench_boost": {11: 1.0}, "free_hit": {11: 1.0}}) is None


def test_one_week_chip_is_played_now_only_beyond_the_waiting_margin():
    from fplagent_engine.chip_timing import calendar_verdict

    close = {"triple_captain": {11: 8.5, 12: 8.0}}
    held = calendar_verdict(close, event=11, next_gap_days=6)
    assert held["play_now_chip"] is None
    assert held["allocations"] == [
        {"chip": "triple_captain", "event": 12, "expected_gain": 8.0}]
    clear = calendar_verdict({"triple_captain": {11: 10.0, 12: 8.0}}, event=11, next_gap_days=6)
    assert clear["play_now_chip"] == "triple_captain"
    assert clear["allocations"][0]["event"] == 11
    # A long gap before the next deadline doubles the margin.
    assert calendar_verdict({"triple_captain": {11: 9.5, 12: 8.0}}, event=11,
                            next_gap_days=14)["play_now_chip"] is None


def test_last_week_chip_has_no_later_option():
    from fplagent_engine.chip_timing import calendar_verdict

    verdict = calendar_verdict({"free_hit": {19: 0.5}}, event=19)
    assert verdict["play_now_chip"] == "free_hit"
    assert verdict["now"]["free_hit"]["best_later_event"] is None


def test_planned_chip_weeks_change_the_solver_weights():
    from fplagent_engine.season_state import ChipType
    from fplagent_engine.wildcard_timing import chip_week_weights

    weights = chip_week_weights({13: ChipType.BENCH_BOOST, 15: ChipType.TRIPLE_CAPTAIN},
                                (12, 13, 14))
    assert weights == {"bench_weight_by_event": {13: 1.0}, "captain_weight_by_event": {}}


def _bench_boost_shadow(selected, uplift=9.0, ci_low=-1.0):
    return {"candidates": [{
        "action_id": "bb-now", "parent_action_id": selected.action_id,
        "comparison_ordinary_action_id": selected.action_id, "chip": "bench_boost",
        "weighted_delta_to_comparison_ordinary": uplift,
        "worst_delta_to_comparison_ordinary": uplift - 1.0,
        "delta_to_comparison_95ci_low": ci_low,
        "scenario_metrics": {"residual": {"mean_current_chip_uplift": uplift}},
    }]}


@pytest.mark.parametrize("play_now,expected", [("bench_boost", "bench_boost"), (None, "no_chip")])
def test_bench_boost_follows_the_full_half_calendar(play_now, expected):
    from fplagent_engine.chip_timing import calendar_verdict

    selected = _selected_action()
    event = _state().event
    gains = {"bench_boost": {event: 12.0 if play_now else 9.0, event + 3: 10.0},
             "triple_captain": {event: 6.0, event + 2: 8.0}}
    calendar = calendar_verdict(gains, event=event, next_gap_days=7)
    assert calendar["play_now_chip"] == play_now
    # The paired interval includes zero, which blocked every chip before the
    # calendar existed. The calendar now decides the week.
    result = synthesize_joint_chip_strategy(
        state=_state(), selected_action=selected, forecast_rows=_rows(),
        team_shadow=_bench_boost_shadow(selected), squad_shadow={},
        schedule_receipt=_SCHEDULE, calibration=_live_calibration(),
        squad_timing={"version": VERSION, "verdict": None, "chip_calendar": calendar},
    )
    assert result["operational_recommendation"] == expected
    plan = {r["chip"]: r for r in result["deadline_plan"]}
    assert plan["bench_boost"]["planned_event"] == (event if play_now else event + 3)
    assert plan["triple_captain"]["planned_event"] == event + 2
    assert plan["triple_captain"]["expected_gain"] == 8.0


def test_without_a_calendar_the_retention_gates_still_apply():
    selected = _selected_action()
    result = synthesize_joint_chip_strategy(
        state=_state(), selected_action=selected, forecast_rows=_rows(),
        team_shadow=_bench_boost_shadow(selected), squad_shadow={},
        schedule_receipt=_SCHEDULE, calibration=_live_calibration(),
    )
    names = [c["name"] for c in result["candidates"][0]["checks"]]
    assert "paired uncertainty excludes retention" in names
    assert result["operational_recommendation"] == "no_chip"

