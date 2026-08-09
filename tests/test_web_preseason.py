from __future__ import annotations

import json
from pathlib import Path

from fplagent_llm.runtime_tools import DEFAULT_DECISION
from fplagent_web.models import ClubMinimumRequest, GenerateSquadRequest
from fplagent_web.preseason import PreseasonSquadService
from fplagent_web.workspace import WorkspaceBuilder


def _service(tmp_path: Path) -> PreseasonSquadService:
    return PreseasonSquadService(active_decision_path=tmp_path / "active.json")


def test_constrained_build_honours_lock_and_club_minimum(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.generate(
        GenerateSquadRequest(
            horizon=3,
            locked_player_ids=[106],
            club_minimums=[ClubMinimumRequest(team_short_name="LIV", count=3)],
        )
    )
    payload = service.current_payload()
    players = payload["decision"]["squad"]["starters"] + payload["decision"]["squad"]["bench"]

    assert result.candidate_id.startswith("S-")
    assert len(players) == 15
    assert 106 in {int(player["element"]) for player in players}
    assert sum(player["team"] == "LIV" for player in players) == 3
    assert len(payload["decision"]["candidate"]["lineups"]) == 3
    assert payload["workspace_candidate"]["constraints"]["horizon"] == 3


def test_confirmed_upload_becomes_the_active_workspace(tmp_path: Path) -> None:
    service = _service(tmp_path)
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    squad = published["decision"]["squad"]
    lineup = published["decision"]["candidate"]["lineups"]["1"]
    players = [
        {
            "source_text": player["name"],
            "squad_role": role,
            "order": order,
            "player_id": player["element"],
        }
        for role, rows in (("starter", squad["starters"]), ("bench", squad["bench"]))
        for order, player in enumerate(rows, start=1)
    ]

    service.adopt_upload(
        {
            "team_valid": True,
            "proposal": {
                "source_image_id": "test-image",
                "formation": squad["formation"],
                "players": players,
                "captain_player_id": lineup["captain"],
                "vice_captain_player_id": lineup["vice_captain"],
            },
        }
    )
    workspace = WorkspaceBuilder(
        active_decision_path=service.active_decision_path,
        profile_path=tmp_path / "profile.json",
    ).build()

    assert workspace.squad.source == "uploaded"
    assert workspace.squad.confirmed is True
    assert workspace.squad.requires_confirmation is False
    assert workspace.squad.source_label == "Confirmed screenshot draft"
    assert workspace.decision.status == "confirmed"
    assert workspace.critique.strengths
    assert workspace.critique.suggested_questions


def test_workspace_distinguishes_current_armband_from_model_recommendation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    squad = published["decision"]["squad"]
    players = [
        {
            "source_text": player["name"],
            "squad_role": role,
            "order": order,
            "player_id": player["element"],
        }
        for role, rows in (("starter", squad["starters"]), ("bench", squad["bench"]))
        for order, player in enumerate(rows, start=1)
    ]
    service.adopt_upload(
        {
            "team_valid": True,
            "proposal": {
                "source_image_id": "armband-review",
                "formation": squad["formation"],
                "players": players,
                "captain_player_id": 55,
                "vice_captain_player_id": 384,
            },
        }
    )

    workspace = WorkspaceBuilder(
        active_decision_path=service.active_decision_path,
        profile_path=tmp_path / "profile.json",
    ).build()

    assert workspace.decision.captain.current_captain_name == "Watkins"
    assert workspace.decision.captain.current_vice_captain_name == "Donnarumma"
    assert workspace.decision.captain.captain_name == "Bruno Fernandes"
    assert workspace.decision.captain.vice_captain_name == "Tarkowski"
    assert workspace.decision.captain.recommendation_aligned is False
    assert "Move the armband from Watkins" in workspace.decision.recommendation


def test_critique_names_full_squad_differences_from_published_benchmark(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.generate(
        GenerateSquadRequest(horizon=1, excluded_player_ids=[124])
    )

    critique = service.critique()
    structural = next(
        item for item in critique.concerns if item.code == "published_squad_delta"
    )

    assert "the active benchmark instead contains" in structural.detail
    assert 124 in structural.player_ids
    assert critique.suggested_questions[0].startswith("Why does the benchmark use")


def test_chat_optimiser_returns_exact_applied_constraints_and_roster(tmp_path: Path) -> None:
    service = _service(tmp_path)

    output = service.handle_optimize_squad(
        {
            "manager_id": 1,
            "start_event": 1,
            "horizon": 1,
            "constraints": {
                "risk_profile": "balanced",
                "locked_player_ids": [106],
                "club_minimums": [{"team_short_name": "LIV", "count": 3}],
            },
            "as_of": "2026-08-06T12:00:00+00:00",
        }
    )

    assert output["workspace_changed"] is True
    assert output["applied_constraints"]["risk_profile"] == "balanced"
    assert output["planning_horizon_gameweeks"] == 1
    assert "expected_points" not in output
    assert output["gw1_expected_points"] > 0
    assert len(output["starters"]) == 11
    assert len(output["bench"]) == 4
    roster = output["starters"] + output["bench"]
    assert 106 in {player["player_id"] for player in roster}
    assert sum(player["team_short_name"] == "LIV" for player in roster) == 3
