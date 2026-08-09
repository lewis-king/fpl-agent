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


def test_final_event_scores_selected_roll_and_every_considered_action(tmp_path: Path) -> None:
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(_decision()) + "\n", encoding="utf-8")

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
    assert by_id["move"]["realized_decision_net_points"] > by_id["roll"][
        "realized_decision_net_points"
    ]
    assert result["selected_comparison"]["realized_rank"] == 1
    assert result["selected_comparison"]["realized_opportunity_cost"] == 0.0
    assert Path(result["receipt_path"]).is_file()
    assert Path(result["report_path"]).is_file()
    assert len(result["selected_squad_player_outcomes"]) == 15
    assert result["version"] == "prospective_weekly_scoring_v2"
    assert result["decision_attribution"]["action_selection_regret"] == 0.0
    assert result["decision_attribution"]["forecast_diagnostics"][
        "appearance_brier"
    ] >= 0.0
    assert result["decision_attribution"]["configuration"][
        "configuration_regret"
    ] >= 0.0

    repeated = score_weekly_event(
        2,
        decision_path=decision_path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )
    assert repeated == result


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
