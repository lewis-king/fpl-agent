from __future__ import annotations

import json
from pathlib import Path

import pytest

from fplagent_data.event_outcomes import archive_event_outcome
from fplagent_engine.cli import parser
from fplagent_engine.prospective_scoring import (
    ProspectiveScoringError,
    latest_archived_weekly_decision,
    score_weekly_event,
)

POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _bootstrap() -> dict:
    return {
        "elements": [{"id": element} for element in range(1, 16)],
        "events": [
            {
                "id": 2,
                "deadline_time": "2026-08-28T17:30:00+00:00",
                "finished": True,
                "data_checked": True,
            }
        ],
    }


def _live() -> dict:
    points = {element: 2 for element in range(1, 16)}
    points[3] = 1
    points[12] = 10
    return {
        "elements": [
            {
                "id": element,
                "stats": {
                    "minutes": 90,
                    "total_points": points[element],
                    "goals_scored": 0,
                    "assists": 0,
                    "expected_goals": "0.00",
                    "expected_assists": "0.00",
                    "bps": 10,
                    "clean_sheets": 0,
                    "defensive_contribution": 0,
                },
            }
            for element in range(1, 16)
        ]
    }


def _summary(
    action_id: str,
    route_type: str,
    starters: list[int],
    bench: list[int],
    *,
    projected: float,
    incremental_cost: int = 0,
) -> dict:
    return {
        "action_id": action_id,
        "route_type": route_type,
        "incremental_points_cost": incremental_cost,
        "total_points_cost": incremental_cost,
        "starter_player_ids": starters,
        "bench_player_ids": bench,
        "captain_player_id": 13,
        "vice_captain_player_id": 8,
        "event_lineups": [
            {
                "event": 2,
                "formation": "3-4-3",
                "projected_points": projected,
                "starter_player_ids": starters,
                "bench_player_ids": bench,
                "captain_player_id": 13,
                "vice_captain_player_id": 8,
            }
        ],
    }


def _decision(*, created_at: str = "2026-08-28T16:00:00+00:00") -> dict:
    roll_starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    roll_bench = [6, 7, 12, 2]
    move_starters = [1, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14]
    move_bench = [3, 7, 15, 2]
    return {
        "version": "weekly_decision_synthesis_v3",
        "created_at": created_at,
        "decision_event": 2,
        "selected_action_id": "move",
        "action_summaries": [
            _summary("roll", "roll", roll_starters, roll_bench, projected=45.0),
            _summary(
                "move",
                "one_free_transfer",
                move_starters,
                move_bench,
                projected=50.0,
            ),
        ],
        "event_player_forecasts": {
            str(element): {
                "element": element,
                "player_name": f"P{element}",
                "position": position,
                "team_id": (element - 1) // 3 + 1,
                "expected_points": 3.0,
                "robust_points": 2.8,
                "p_play": 0.95,
                "expected_minutes": 80.0,
            }
            for element, position in zip(range(1, 16), POSITIONS, strict=True)
        },
    }


def test_full_pool_scoring_includes_omitted_players_and_keeps_missing_outcomes_missing():
    from fplagent_engine.prospective_scoring import score_forecast_universe
    meta = {1: {"position": "MID", "expected_points": 5.0, "p_play": 0.9,
                "expected_minutes": 80.0},
            2: {"position": "FWD", "expected_points": 2.0, "p_play": 0.5},
            3: {"position": "DEF", "expected_points": 1.0, "p_play": 0.1}}
    result = score_forecast_universe(meta, {1: {"total_points": 2, "minutes": 90},
                                          2: {"total_points": 10, "minutes": 90}},
                                     selected_players={1}, declared_scope="entire_current_event_forecast_pool")
    assert result["status"] == "partial_outcomes"
    assert result["missing_outcome_player_ids"] == [3]
    assert result["scored_players"] == 2
    assert result["cohorts"]["all_frozen"]["points_mae"] == 5.5
    assert result["cohorts"]["not_selected"]["points_mae"] == 8.0
    assert result["cohorts"]["predicted_regulars"]["players"] == 1
    assert result["cohorts"]["DEF"]["points_mae"] is None
    assert result["cohorts"]["all_frozen"]["minutes_mae"] == 10.0


def test_legacy_forecast_subset_is_not_reported_as_full_pool():
    from fplagent_engine.prospective_scoring import score_forecast_universe
    result = score_forecast_universe({}, {}, selected_players=set())
    assert result["scope"] == "legacy_frozen_subset"
    assert result["cohorts"]["all_frozen"]["points_mae"] is None


@pytest.mark.parametrize("complete", [True, False])
def test_recourse_scores_only_the_frozen_first_action_and_requires_complete_search(tmp_path, complete):
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["diagnostics"] = {"transfer_continuation": {
        "status": "ready_diagnostic" if complete else "incomplete_diagnostic",
        "complete_root_comparison": complete, "shadow_preference": "roll",
    }}
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(decision))
    result = score_weekly_event(
        2, decision_path=path, outcome_root=outcome_root, outcome_pointer_root=pointer_root,
        result_root=result_root, report_root=report_root,
    )
    scores = result["challenger_policy_scores"]
    if not complete:
        assert "next_deadline_recourse" not in scores
        return
    score = scores["next_deadline_recourse"]
    assert score["scope"] == "first_action_only"
    assert score["status"] == "scored_shadow"
    assert not score["decision_authority"]
    by_id = {a["action_id"]: a for a in result["actions"]}
    assert score["realized_delta_to_champion"] == (
        by_id["roll"]["realized_decision_net_points"] - by_id["move"]["realized_decision_net_points"]
    )


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    outcome_root = tmp_path / "outcomes"
    pointer_root = tmp_path / "outcome-pointers"
    result_root = tmp_path / "results"
    report_root = tmp_path / "reports"
    archive_event_outcome(
        _live(),
        _bootstrap(),
        event=2,
        observed_at="2026-08-29T20:00:00+00:00",
        outcome_root=outcome_root,
        pointer_root=pointer_root,
    )
    return outcome_root, pointer_root, result_root, report_root


@pytest.mark.parametrize("decision_version", ["weekly_decision_synthesis_v3", "weekly_decision_synthesis_v4"])
def test_final_event_scores_selected_roll_and_every_considered_action(tmp_path: Path, decision_version) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision_path = tmp_path / "decision.json"
    decision = dict(_decision(), version=decision_version)
    decision_path.write_text(json.dumps(decision) + "\n", encoding="utf-8")

    result = score_weekly_event(
        2,
        decision_path=decision_path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )

    by_id = {row["action_id"]: row for row in result["actions"]}
    assert result["selected_action_id"] == "move"
    assert (
        by_id["move"]["realized_decision_net_points"]
        > by_id["roll"]["realized_decision_net_points"]
    )
    assert result["selected_comparison"]["realized_rank"] == 1
    assert result["selected_comparison"]["realized_opportunity_cost"] == 0.0
    assert Path(result["receipt_path"]).is_file()
    assert Path(result["report_path"]).is_file()
    assert len(result["selected_squad_player_outcomes"]) == 15
    assert result["version"] == "prospective_weekly_scoring_v4"
    assert result["decision_attribution"]["action_selection_regret"] == 0.0
    assert result["decision_attribution"]["forecast_diagnostics"]["appearance_brier"] >= 0.0
    assert result["decision_attribution"]["configuration"]["configuration_regret"] >= 0.0

    repeated = score_weekly_event(
        2,
        decision_path=decision_path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )
    assert repeated == result

    # Identical outcomes recaptured with repaired/new source lineage must preserve
    # the original immutable receipt, not collide over an observation timestamp.
    archive_event_outcome(_live(), _bootstrap(), event=2,
                          observed_at="2026-08-31T12:00:00+00:00",
                          outcome_root=outcome_root, pointer_root=pointer_root)
    recaptured = score_weekly_event(2, decision_path=decision_path, outcome_root=outcome_root,
                                  outcome_pointer_root=pointer_root, result_root=result_root,
                                  report_root=report_root)
    assert recaptured == result


def test_decision_created_after_deadline_is_rejected(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision_path = tmp_path / "late.json"
    decision_path.write_text(
        json.dumps(_decision(created_at="2026-08-28T18:00:00+00:00")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProspectiveScoringError, match="after the official deadline"):
        score_weekly_event(
            2,
            decision_path=decision_path,
            outcome_root=outcome_root,
            outcome_pointer_root=pointer_root,
            result_root=result_root,
            report_root=report_root,
        )


def test_latest_archive_selects_last_valid_predeadline_receipt(tmp_path: Path) -> None:
    event_dir = tmp_path / "archive" / "event-2"
    event_dir.mkdir(parents=True)
    early = event_dir / "early.json"
    late = event_dir / "late.json"
    early.write_text(json.dumps(_decision(created_at="2026-08-28T10:00:00+00:00")))
    late.write_text(json.dumps(_decision(created_at="2026-08-28T16:00:00+00:00")))

    assert latest_archived_weekly_decision(2, archive_root=tmp_path / "archive") == late


def test_latest_archive_prefers_newer_contract_schema_on_same_decision(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "archive" / "event-2"
    event_dir.mkdir(parents=True)
    old = event_dir / "z-old.json"
    new = event_dir / "a-new.json"
    old_decision = _decision()
    old_decision["version"] = "prospective_decision_contract_v1"
    new_decision = _decision()
    new_decision["version"] = "prospective_decision_contract_v2"
    old.write_text(json.dumps(old_decision), encoding="utf-8")
    new.write_text(json.dumps(new_decision), encoding="utf-8")

    assert latest_archived_weekly_decision(2, archive_root=tmp_path / "archive") == new


def test_score_weekly_event_command_is_exposed() -> None:
    args = parser().parse_args(
        ["score-weekly-event", "--event", "2", "--decision", "/tmp/decision.json"]
    )
    assert args.event == 2
    assert args.decision == Path("/tmp/decision.json")


def test_preseason_contract_uses_strongest_rejected_squad_as_reference(
    tmp_path: Path,
) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["version"] = "prospective_decision_contract_v1"
    decision["reference_action_id"] = "roll"
    decision["reference_label"] = "strongest pre-deadline rejected squad"
    decision["action_summaries"][0]["route_type"] = "preseason_squad"
    decision["action_summaries"][1]["route_type"] = "preseason_squad"
    decision_path = tmp_path / "preseason.json"
    decision_path.write_text(json.dumps(decision) + "\n", encoding="utf-8")

    result = score_weekly_event(
        2,
        decision_path=decision_path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )

    assert result["roll_action_id"] is None
    assert result["reference_action_id"] == "roll"
    assert result["selected_comparison"]["realized_delta_to_reference"] > 0.0


def test_frozen_shadow_policy_choice_is_scored_against_champion(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["diagnostics"] = {
        "form_reversion_shadow": {
            "status": "ready_shadow",
            "leader_action_id": "roll",
        }
    }
    decision_path = tmp_path / "shadow.json"
    decision_path.write_text(json.dumps(decision) + "\n", encoding="utf-8")

    result = score_weekly_event(
        2,
        decision_path=decision_path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )

    score = result["challenger_policy_scores"]["form_reversion"]
    assert score["status"] == "scored_shadow"
    assert score["decision_authority"] is False
    assert score["realized_delta_to_champion"] < 0.0


def test_frozen_chip_hold_scores_team_chip_counterfactuals(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["chip_strategy"] = {
        "status": "retain_chips",
        "operational_recommendation": "no_chip",
        "candidates": [
            {
                "chip": "bench_boost",
                "action_id": "bb-move",
                "parent_action_id": "move",
                "projected_uplift": 11.0,
                "joint_net_value": -1.0,
                "operational_gate_passed": False,
            },
            {
                "chip": "triple_captain",
                "action_id": "tc-move",
                "parent_action_id": "move",
                "projected_uplift": 6.0,
                "joint_net_value": -2.0,
                "operational_gate_passed": False,
            },
        ],
    }
    decision_path = tmp_path / "chip-hold.json"
    decision_path.write_text(json.dumps(decision) + "\n", encoding="utf-8")

    result = score_weekly_event(
        2,
        decision_path=decision_path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )

    by_chip = {
        row["chip"]: row for row in result["chip_strategy_score"]["candidates"]
    }
    assert result["chip_strategy_score"]["frozen_recommendation"] == "no_chip"
    assert by_chip["bench_boost"]["actual_immediate_uplift"] == 7.0
    assert by_chip["triple_captain"]["actual_immediate_uplift"] == 2.0


@pytest.mark.parametrize("chip", ["bench_boost", "triple_captain"])
def test_chip_scores_its_frozen_parent_not_the_ordinary_winner(tmp_path: Path, chip: str) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    # The chip branch has a different bench and captain and incurs a four-point hit.
    parent = decision["action_summaries"][0]
    parent["total_points_cost"] = 4
    parent["incremental_points_cost"] = 4
    parent["event_lineups"][0]["captain_player_id"] = 3
    decision["chip_shadow"] = {"candidates": [
        {"action_id": "chip-roll", "parent_action_id": "roll", "chip": chip}
    ]}
    decision["chip_strategy"] = {
        "operational_recommendation": "no_chip",
        "candidates": [{"action_id": "chip-roll", "chip": chip}],
    }
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    result = score_weekly_event(
        2, decision_path=decision_path, outcome_root=outcome_root,
        outcome_pointer_root=pointer_root, result_root=result_root, report_root=report_root,
    )
    row = result["chip_strategy_score"]["candidates"][0]
    scores = {r["action_id"]: r for r in result["actions"]}
    chip_only = 16.0 if chip == "bench_boost" else 1.0
    assert row["parent_action_id"] == "roll"
    assert row["actual_chip_only_uplift"] == chip_only
    assert row["actual_immediate_uplift"] == (
        scores["roll"]["realized_manager_net_points"] + chip_only
        - scores["move"]["realized_manager_net_points"]
    )
    assert row["total_points_cost"] == 4


def test_chip_without_parent_is_unscorable_not_assumed_selected(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["chip_strategy"] = {"candidates": [{"chip": "bench_boost", "action_id": "lost"}]}
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    result = score_weekly_event(
        2, decision_path=decision_path, outcome_root=outcome_root,
        outcome_pointer_root=pointer_root, result_root=result_root, report_root=report_root,
    )
    row = result["chip_strategy_score"]["candidates"][0]
    assert row["status"] == "not_scorable_missing_lineage"
    assert row["actual_immediate_uplift"] is None


def test_chip_scores_its_exact_captain_not_the_ordinary_parent(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    parent = decision["action_summaries"][1]
    execution = json.loads(json.dumps(parent))
    execution.update(chip="triple_captain", configuration_action_id="tc")
    execution["event_lineups"][0]["captain_player_id"] = 12  # ten points, not P13's two
    decision["execution_plan"] = execution
    decision["chip_strategy"] = {"operational_recommendation": "triple_captain",
        "recommended_action_id": "tc", "candidates": [
            {"chip": "triple_captain", "action_id": "tc", "parent_action_id": "move"}
        ]}
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(decision))
    result = score_weekly_event(2, decision_path=path, outcome_root=outcome_root,
        outcome_pointer_root=pointer_root, result_root=result_root, report_root=report_root)
    chip = result["chip_strategy_score"]["candidates"][0]
    assert chip["actual_chip_only_uplift"] == 10
    assert chip["actual_immediate_uplift"] == 18
    assert chip["configuration_basis"] == "exact_frozen_chip"


def test_new_chip_without_its_configuration_is_not_assumed_parent(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["diagnostics"] = {"configuration_optimisation": {"status": "validated", "candidates": []}}
    decision["chip_strategy"] = {"candidates": [{"chip": "triple_captain", "action_id": "tc", "parent_action_id": "move"}]}
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(decision))
    result = score_weekly_event(2, decision_path=path, outcome_root=outcome_root,
        outcome_pointer_root=pointer_root, result_root=result_root, report_root=report_root)
    assert result["chip_strategy_score"]["candidates"][0]["actual_immediate_uplift"] is None


def test_bench_boost_does_not_double_count_automatic_substitute_points(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    live = _live()
    # Starter 6 misses out and first outfield reserve 3 replaces him.
    live["elements"][5]["stats"]["minutes"] = 0
    live["elements"][5]["stats"]["total_points"] = 0
    archive_event_outcome(
        live, _bootstrap(), event=2, observed_at="2026-08-30T20:00:00+00:00",
        outcome_root=outcome_root, pointer_root=pointer_root,
    )
    decision = _decision()
    decision["chip_strategy"] = {"candidates": [
        {"chip": "bench_boost", "action_id": "bb", "parent_action_id": "move"}
    ]}
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    result = score_weekly_event(
        2, decision_path=decision_path, outcome_root=outcome_root,
        outcome_pointer_root=pointer_root, result_root=result_root, report_root=report_root,
    )
    assert result["chip_strategy_score"]["candidates"][0]["actual_chip_only_uplift"] == 6.0


@pytest.mark.parametrize("chip", ["wildcard", "free_hit"])
def test_squad_chip_comparison_includes_waived_event_hits(tmp_path: Path, chip: str) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    selected = decision["action_summaries"][1]
    selected["total_points_cost"] = 4
    lineup = selected["event_lineups"][0]
    decision["squad_chip_shadow"] = {"candidates": [{
        "action_id": "rebuild",
        "selected_player_ids": lineup["starter_player_ids"] + lineup["bench_player_ids"],
        **lineup,
    }]}
    decision["chip_strategy"] = {"candidates": [{"action_id": "rebuild", "chip": chip}]}
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    result = score_weekly_event(
        2, decision_path=decision_path, outcome_root=outcome_root,
        outcome_pointer_root=pointer_root, result_root=result_root, report_root=report_root,
    )
    row = result["chip_strategy_score"]["candidates"][0]
    assert row["actual_immediate_uplift"] == 4.0
    assert row["total_points_cost"] == 0
    assert row["actual_chip_only_uplift"] is None
