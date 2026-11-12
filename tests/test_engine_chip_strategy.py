from __future__ import annotations

import json
from dataclasses import replace
from itertools import product
from pathlib import Path

import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine import chip_strategy
from fplagent_engine.chip_strategy import (
    _historical_rows_semantic_sha256,
    _lookup_retained,
    _optimise_calendar,
    _remaining_bin,
    _score_timing_policy,
    _weighted_quantile,
    load_chip_strategy_calibration,
    synthesize_joint_chip_strategy,
)
from fplagent_engine.season_state import ChipStatus
from fplagent_engine.weekly_actions import generate_weekly_actions


def _retained_table(value: float = 10.0) -> dict:
    bins = {
        name: {"p25": value, "p50": value, "p75": value, "p90": value}
        for name in ("early_13_18", "middle_7_12", "late_4_6", "expiry_0_3")
    }
    return {"bench_boost": bins, "triple_captain": bins}


def _live_calibration(*, bench_authority: bool = True) -> dict:
    retained = _retained_table(7.0)
    for chip in ("bench_boost", "triple_captain"):
        retained[chip]["by_events_remaining"] = {
            str(remaining): {"p50": 0.0 if remaining == 0 else 7.0}
            for remaining in range(19)
        }
    return {
        "retained_value": retained,
        "squad_chip_priors": {
            "wildcard": {"p50": 6.0},
            "free_hit": {"p50": 6.0},
        },
        "authority_by_chip": {
            "bench_boost": bench_authority,
            "triple_captain": True,
            "wildcard": False,
            "free_hit": False,
        },
        "status": "promoted_team_chips",
    }


def _selected_action():
    actions = generate_weekly_actions(
        _state(),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    return actions[0]


def _complete_historical_paths():
    return [{"season": season, "opportunities": [
        {"event": event,
         "forecast_uplifts": {"bench_boost": 10.0, "triple_captain": 10.0},
         "actual_uplifts": {"bench_boost": 10.0, "triple_captain": 10.0}}
        for event in range(1, 39)]} for season in chip_strategy.SEASONS]


def test_chip_validation_trains_only_on_earlier_seasons():
    paths = _complete_historical_paths()
    gate = chip_strategy._historical_gate(paths)
    assert gate["passed"]
    assert gate["training_only_seasons"] == ["2023-24"]
    assert [f["test_season"] for f in gate["folds"]] == ["2024-25", "2025-26"]
    for fold in gate["folds"]:
        assert all(s < fold["test_season"] for s in fold["train_seasons"])
    # Future outcomes may change the latest evaluation but cannot alter the
    # earlier fold's learned table, decisions or scores.
    for row in paths[-1]["opportunities"]:
        row["forecast_uplifts"] = {"bench_boost": 1000, "triple_captain": 1000}
        row["actual_uplifts"] = {"bench_boost": 0, "triple_captain": 0}
    assert chip_strategy._historical_gate(paths)["folds"][0] == gate["folds"][0]


def test_chip_validation_rejects_duplicate_or_missing_seasons():
    paths = _complete_historical_paths()
    for bad in (paths[:-1], [paths[0], paths[0], paths[-1]]):
        with pytest.raises(ValueError, match="exactly one path"):
            chip_strategy._historical_gate(bad)


def test_old_cross_season_receipt_cannot_grant_chip_authority(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"version": 2, "historical_gate": {"passed": True},
                                "authority_by_chip": {"bench_boost": True}}))
    loaded = load_chip_strategy_calibration(path)
    assert loaded["status"] == "shadow"
    assert not any(loaded["authority_by_chip"].values())


def test_forward_receipt_preserves_valid_team_chip_authority(tmp_path):
    path = tmp_path / "forward.json"
    path.write_text(json.dumps({"version": 2,
        "historical_gate": chip_strategy._historical_gate(_complete_historical_paths()),
        "authority_by_chip": {"bench_boost": True, "wildcard": False}}))
    loaded = load_chip_strategy_calibration(path)
    assert loaded["authority_by_chip"]["bench_boost"]
    assert not loaded["authority_by_chip"]["wildcard"]


def test_weighted_quantile_and_expiry_bins_favour_recent_mass() -> None:
    assert _weighted_quantile([1.0, 9.0], [0.2, 0.8], 0.5) == 9.0
    assert _remaining_bin(18) == "early_13_18"
    assert _remaining_bin(3) == "expiry_0_3"
    assert _lookup_retained(_retained_table(7.0), "triple_captain", 19) == 7.0
    exact = _retained_table(7.0)
    exact["triple_captain"]["by_events_remaining"] = {"0": {"p50": 0.0}}
    assert _lookup_retained(exact, "triple_captain", 19) == 0.0


def test_calendar_enforces_one_chip_per_event_and_one_use_per_chip() -> None:
    result = _optimise_calendar(
        [
            {"event": 4, "chip": "bench_boost", "projected_uplift": 9.0},
            {"event": 4, "chip": "triple_captain", "projected_uplift": 8.0},
            {"event": 5, "chip": "bench_boost", "projected_uplift": 7.0},
            {"event": 5, "chip": "triple_captain", "projected_uplift": 7.0},
        ],
        ["bench_boost", "triple_captain"],
        {"bench_boost": 0.0, "triple_captain": 0.0},
    )

    assert result["total_option_value"] == 16.0
    assert {(row["event"], row["chip"]) for row in result["allocations"]} == {
        (4, "bench_boost"),
        (5, "triple_captain"),
    }


def test_calendar_prices_unseen_terminal_opportunities_instead_of_dropping_them() -> None:
    result = _optimise_calendar(
        [{"event": 4, "chip": "triple_captain", "projected_uplift": 5.0}],
        ["bench_boost", "triple_captain", "wildcard"],
        {"bench_boost": 8.0, "triple_captain": 7.0, "wildcard": 6.0},
    )

    assert result["visible_value"] == 0.0
    assert result["terminal_value"] == 21.0
    assert result["allocations"] == []


def test_unseen_terminal_value_cannot_spend_more_chips_than_remaining_weeks():
    result = _optimise_calendar([], ["bench_boost", "triple_captain", "wildcard"],
                                {"bench_boost": 8., "triple_captain": 7., "wildcard": 6.},
                                terminal_slots=1)
    assert result["total_option_value"] == result["terminal_value"] == 8
    spent = _optimise_calendar([], ["bench_boost", "triple_captain", "wildcard"],
                               {"bench_boost": 8., "triple_captain": 7., "wildcard": 6.},
                               excluded_chip="bench_boost", terminal_slots=1)
    assert spent["terminal_value"] == 7


@pytest.mark.parametrize("slots", [0, 1, 2, 3])
def test_capacity_aware_calendar_matches_exhaustive_enumeration(slots):
    available = ["bench_boost", "triple_captain", "wildcard"]
    terminal = {"bench_boost": 8., "triple_captain": 7., "wildcard": 6.}
    opportunities = [{"event": e, "chip": c, "projected_uplift": (e + i*3) % 11}
                     for e in (15, 16, 17) for i, c in enumerate(available)]
    best = 0.
    for choices in product([None, *available], repeat=3):
        used = [c for c in choices if c is not None]
        if len(set(used)) != len(used):
            continue
        visible = sum(r["projected_uplift"] for r in opportunities
                      if choices[r["event"]-15] == r["chip"])
        saved = sum(sorted((v for c, v in terminal.items() if c not in used), reverse=True)[:slots])
        best = max(best, visible + saved)
    assert _optimise_calendar(opportunities, available, terminal,
                              terminal_slots=slots)["total_option_value"] == best


@pytest.mark.parametrize("slots", [-1, .5, True])
def test_invalid_terminal_calendar_capacity_fails_closed(slots):
    with pytest.raises(ValueError):
        _optimise_calendar([], [], {}, terminal_slots=slots)


def test_joint_calendar_one_unseen_week_cannot_retain_value_of_four_uses():
    selected = _selected_action()
    selected = replace(selected, lineups=(replace(selected.lineups[0], event=18),))
    rows = [dict(r, event_number=18) for r in _rows() if r["event_number"] == 2]
    result = synthesize_joint_chip_strategy(
        state=replace(_state(), event=18), selected_action=selected, forecast_rows=rows,
        team_shadow={}, squad_shadow={}, schedule_receipt={}, calibration=_live_calibration())
    assert result["retention_calendar"]["terminal_value"] == 7.


@pytest.mark.parametrize("event,expiry", [(18, 19), (19, 19), (37, 38), (38, 38)])
def test_joint_calendar_cannot_save_this_halfs_chips_for_after_expiry(event, expiry):
    selected = _selected_action()
    selected = replace(selected, lineups=tuple(
        replace(selected.lineups[0], event=e) for e in range(event, expiry + 3)))
    # Enormous opportunities AFTER expiry must have no effect on this inventory.
    rows = [dict(r, event_number=e, expected_points=10000. if e > expiry else r["expected_points"])
            for e in range(event, expiry + 3) for r in _rows() if r["event_number"] == 2]
    calibration = _live_calibration()
    # Older portable calibrations have bins only. The rules, not a lucky learned
    # zero in the terminal table, must make an expired chip worthless.
    calibration["retained_value"] = _retained_table(999.)
    team_shadow = {"candidates": [{
        "action_id": "bb-now", "parent_action_id": selected.action_id,
        "comparison_ordinary_action_id": selected.action_id, "chip": "bench_boost",
        "weighted_delta_to_comparison_ordinary": 50.,
        "worst_delta_to_comparison_ordinary": 49.,
        "delta_to_comparison_95ci_low": 48.,
        "scenario_metrics": {"residual": {"mean_current_chip_uplift": 50.}},
    }]}
    state = replace(_state(), event=event, chips=tuple(
        replace(slot, status=ChipStatus.AVAILABLE) if slot.half == (1 if event <= 19 else 2) else slot
        for slot in _state().chips))
    result = synthesize_joint_chip_strategy(
        state=state, selected_action=selected, forecast_rows=rows,
        team_shadow=team_shadow, squad_shadow={}, schedule_receipt={}, calibration=calibration)
    assert all(r["event"] <= expiry for r in result["visible_calendar"])
    assert all(r["event"] <= expiry for r in result["retention_calendar"]["allocations"])
    assert result["retention_calendar"]["terminal_value"] == 0
    for candidate in result["candidates"]:
        assert all(r["event"] <= expiry for r in candidate["calendar_after_play"]["allocations"])
        assert candidate["calendar_after_play"]["terminal_value"] == 0
    if event == expiry:
        assert result["operational_recommendation"] == "bench_boost"


def test_joint_policy_can_promote_a_team_chip_but_not_an_uncalibrated_squad_chip() -> None:
    selected = _selected_action()
    team_shadow = {
        "candidates": [
            {
                "action_id": f"{selected.action_id}-bench_boost",
                "parent_action_id": selected.action_id,
                "comparison_ordinary_action_id": selected.action_id,
                "chip": "bench_boost",
                "weighted_delta_to_comparison_ordinary": 50.0,
                "worst_delta_to_comparison_ordinary": 49.0,
                "delta_to_comparison_95ci_low": 48.0,
                "scenario_metrics": {"residual": {"mean_current_chip_uplift": 50.0}},
            }
        ]
    }
    wildcard_shadow = {
        "candidates": [
            {
                "action_id": "wildcard-route",
                "chip": "wildcard",
                "weighted_raw_delta_to_best_ordinary": 60.0,
                "scenario_metrics": {
                    "residual": {
                        "mean_raw_delta_to_best_ordinary": 60.0,
                        "raw_delta_95ci_low": 58.0,
                    }
                },
            }
        ]
    }
    schedule = {
        "event_summaries": [
            {
                "event": 2,
                "blank_teams": [],
                "double_teams": [],
                "at_risk_teams": [],
            }
        ]
    }

    result = synthesize_joint_chip_strategy(
        state=_state(),
        selected_action=selected,
        forecast_rows=_rows(),
        team_shadow=team_shadow,
        squad_shadow=wildcard_shadow,
        schedule_receipt=schedule,
        calibration=_live_calibration(),
    )

    assert result["operational_recommendation"] == "bench_boost"
    assert result["recommended_action_id"] == f"{selected.action_id}-bench_boost"
    wildcard = next(row for row in result["candidates"] if row["chip"] == "wildcard")
    assert wildcard["joint_net_value"] > 0.0
    assert wildcard["operational_gate_passed"] is False
    assert next(
        check for check in wildcard["checks"]
        if check["name"] == "full-half timing: now is the best Wildcard week"
    )["passed"] is False


def test_free_hit_can_be_considered_in_a_normal_single_gameweek():
    result = synthesize_joint_chip_strategy(
        state=_state(), selected_action=_selected_action(), forecast_rows=_rows(),
        team_shadow={}, squad_shadow={"candidates": [{
            "action_id": "fh-normal-week", "chip": "free_hit",
            "weighted_raw_delta_to_best_ordinary": 20.0,
            "scenario_metrics": {"residual": {
                "mean_raw_delta_to_best_ordinary": 20.0, "raw_delta_95ci_low": 18.0}}}]},
        schedule_receipt={"event_summaries": [{"event": 2, "blank_teams": [],
                                               "double_teams": [], "at_risk_teams": []}]},
        calibration=_live_calibration(),
    )
    fh = next(c for c in result["candidates"] if c["chip"] == "free_hit")
    assert next(c for c in fh["checks"] if c["name"] == "current schedule fit")["passed"]
    # Free Hit is one week: the joint calendar and uncertainty gates price holding it.
    assert fh["operational_gate_passed"]
    assert result["operational_recommendation"] == "free_hit"


def test_timing_policy_cannot_let_team_chips_expire_or_collide() -> None:
    opportunities = []
    for event in range(1, 39):
        opportunities.append(
            {
                "event": event,
                "forecast_uplifts": {
                    "bench_boost": 1.0,
                    "triple_captain": 1.0,
                },
                "actual_uplifts": {
                    "bench_boost": 2.0,
                    "triple_captain": 3.0,
                },
            }
        )
    result = _score_timing_policy(
        {"season": "test", "opportunities": opportunities},
        _retained_table(10.0),
    )

    assert [(row["event"], row["chip"]) for row in result["chip_events"]] == [
        (18, "triple_captain"),
        (19, "bench_boost"),
        (37, "triple_captain"),
        (38, "bench_boost"),
    ]


def test_committed_calibration_is_portable_without_large_source_tables(
    tmp_path: Path,
) -> None:
    path = tmp_path / "retained-value.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "artifacts": {
                    "backtest_forecast": "data/model/missing.parquet",
                    "backtest_forecast_sha256": "frozen-source-hash",
                },
            }
        ),
        encoding="utf-8",
    )

    result = load_chip_strategy_calibration(path)

    assert result["source_verification"]["verified"] == []
    assert result["source_verification"]["unavailable"] == ["backtest_forecast"]


def test_calibration_verifies_historical_semantics_not_mutable_file_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backtest = tmp_path / "backtest.parquet"
    features = tmp_path / "features.parquet"
    backtest.write_bytes(b"first physical generation")
    features.write_bytes(b"historical plus live generation one")
    grouped = {
        ("2025-26", 1): [
            {
                "element": 7,
                "player_name": "Player",
                "position": "MID",
                "team_id": 2,
                "market_price": 75,
                "target_points": 8.0,
                "target_minutes": 90.0,
                "expected_points": 5.4,
                "p_play": 0.98,
                "can_select": True,
                "removed": False,
            }
        ]
    }
    receipt = tmp_path / "retained-value.json"
    receipt.write_text(
        json.dumps(
            {
                "version": 2,
                "artifacts": {
                    "backtest_forecast": str(backtest),
                    "training_features": str(features),
                    "historical_rows_semantic_sha256": _historical_rows_semantic_sha256(
                        grouped
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(chip_strategy, "_load_historical_rows", lambda: grouped)

    assert set(load_chip_strategy_calibration(receipt)["source_verification"]["verified"]) == {
        "backtest_forecast",
        "training_features",
    }
    features.write_bytes(b"same history, different live rows and parquet bytes")
    assert load_chip_strategy_calibration(receipt)["source_verification"]["unavailable"] == []

    changed = {key: [dict(rows[0], target_points=9.0)] for key, rows in grouped.items()}
    monkeypatch.setattr(chip_strategy, "_load_historical_rows", lambda: changed)
    with pytest.raises(ValueError, match="historical_rows"):
        load_chip_strategy_calibration(receipt)
