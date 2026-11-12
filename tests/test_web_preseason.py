from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_llm.runtime_tools import DEFAULT_DECISION, DEFAULT_FORECASTS
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


def test_explicit_low_role_lock_is_retained_but_never_silently_endorsed(
    tmp_path: Path,
) -> None:
    forecast_path = tmp_path / "low-role-forecast.parquet"
    rows = pq.read_table(DEFAULT_FORECASTS).to_pylist()
    for row in rows:
        if int(row["element"]) == 55 and int(row["event_number"]) == 1:
            row.update(
                p_dnp=0.5,
                p_1_59=0.4,
                p_60_89=0.1,
                p_90_or_more=0.0,
                p_play=0.5,
            )
    pq.write_table(pa.Table.from_pylist(rows), forecast_path)
    service = PreseasonSquadService(
        active_decision_path=tmp_path / "active.json",
        forecast_path=forecast_path,
    )

    result = service.generate(GenerateSquadRequest(horizon=1, locked_player_ids=[55]))
    payload = service.current_payload()
    risks = payload["workspace_candidate"]["role_integrity_risks"]
    critique = service.critique(payload)

    assert 55 in {
        int(player["element"])
        for player in payload["decision"]["squad"]["starters"]
        + payload["decision"]["squad"]["bench"]
    }
    assert any(int(risk["element"]) == 55 for risk in risks)
    assert "role review" in result.message
    assert any(item.code == "role_integrity_risk" for item in critique.concerns)


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


def test_mcp_candidate_identity_changes_with_squad_not_observation_time(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    squad = published["decision"]["squad"]
    lineup = published["decision"]["candidate"]["lineups"]["1"]
    players = list(squad["starters"]) + list(squad["bench"])
    picks = [
        {
            "element": int(player["element"]),
            "name": str(player["name"]),
            "position": position,
            "is_captain": int(player["element"]) == int(lineup["captain"]),
            "is_vice_captain": int(player["element"]) == int(lineup["vice_captain"]),
        }
        for position, player in enumerate(players, start=1)
    ]
    snapshot = {
        "status": "connected",
        "entry_id": 431892,
        "observed_at": "2026-08-08T10:00:00+00:00",
        "picks": picks,
    }

    first = service.adopt_mcp_snapshot(snapshot)
    second = service.adopt_mcp_snapshot({**snapshot, "observed_at": "2026-08-08T12:00:00+00:00"})
    changed_picks = [dict(row) for row in picks]
    changed_picks[0]["is_captain"] = True
    for row in changed_picks[1:]:
        row["is_captain"] = False
    changed = service.adopt_mcp_snapshot({**snapshot, "picks": changed_picks})

    assert first == second
    assert changed != first


def test_workspace_distinguishes_current_armband_from_model_recommendation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    squad = published["decision"]["squad"]
    recommended_captain = next(player for player in squad["starters"] if player["captain"])
    current_captain = next(
        player
        for player in squad["starters"]
        if player["element"] != recommended_captain["element"]
    )
    current_vice_captain = next(
        player
        for player in squad["starters"]
        if player["element"] not in {recommended_captain["element"], current_captain["element"]}
    )
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
                "captain_player_id": current_captain["element"],
                "vice_captain_player_id": current_vice_captain["element"],
            },
        }
    )

    workspace = WorkspaceBuilder(
        active_decision_path=service.active_decision_path,
        profile_path=tmp_path / "profile.json",
    ).build()

    assert workspace.decision.captain.current_captain_name == current_captain["name"]
    assert workspace.decision.captain.current_vice_captain_name == current_vice_captain["name"]
    # The optimiser may promote a current substitute, including to captain/VC.
    # Check its recommended XI, not the uploaded lineup it is allowed to change.
    starter_names = {player.name for player in workspace.decision.recommended_squad.starters}
    assert workspace.decision.captain.captain_name in starter_names
    assert workspace.decision.captain.vice_captain_name in starter_names
    assert workspace.decision.captain.captain_name != current_captain["name"]
    assert workspace.decision.captain.recommendation_aligned is False
    assert f"Move the armband from {current_captain['name']}" in workspace.decision.recommendation


def test_critique_names_full_squad_differences_from_published_benchmark(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    excluded = int(published["decision"]["squad"]["bench"][0]["element"])
    service.generate(GenerateSquadRequest(horizon=1, excluded_player_ids=[excluded]))

    critique = service.critique()
    structural = next(item for item in critique.concerns if item.code == "published_squad_delta")

    assert "the active benchmark instead contains" in structural.detail
    assert excluded in structural.player_ids
    assert critique.suggested_questions[0].startswith("Why does the benchmark use")


def test_workspace_exposes_published_model_squad_separately_from_active_squad(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # This is a preseason presentation test, not today's live-season calendar.
    original_calendar = WorkspaceBuilder._event_calendar
    monkeypatch.setattr(
        WorkspaceBuilder,
        "_deadline_evidence_status",
        lambda *a, **kw: {"publishable": True, "issues": []},
    )
    monkeypatch.setattr(
        WorkspaceBuilder,
        "_deadline_pack",
        lambda *a, **kw: {
            "gates": {
                "historical_selector": {"passed": True},
                "global_search": {"passed": True},
            }
        },
    )
    monkeypatch.setattr(
        WorkspaceBuilder,
        "_event_calendar",
        lambda builder: [
            dict(row, finished=False, data_checked=False) for row in original_calendar(builder)
        ],
    )
    service = _service(tmp_path)
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    excluded = int(published["decision"]["squad"]["bench"][0]["element"])
    service.generate(GenerateSquadRequest(horizon=1, excluded_player_ids=[excluded]))

    # Both receipts belong to this synthetic preseason view, not the date on
    # which the integration fixture happens to be generated.
    active = service.current_payload()
    active["created_at"] = "2026-08-21T10:00:00+00:00"
    service.active_decision_path.write_text(json.dumps(active))
    published["created_at"] = active["created_at"]
    benchmark = tmp_path / "published-view-fixture.json"
    benchmark.write_text(json.dumps(published))
    workspace = WorkspaceBuilder(
        decision_path=benchmark,
        active_decision_path=service.active_decision_path,
        profile_path=tmp_path / "profile.json",
    ).build(now=datetime(2026, 8, 21, 11, tzinfo=UTC))
    model = workspace.decision.model_squad

    assert model is not None
    assert model.candidate_id == published["decision"]["candidate"]["candidate_id"]
    assert excluded not in {
        player.player_id for player in [*workspace.squad.starters, *workspace.squad.bench]
    }
    assert excluded in {player.player_id for player in [*model.starters, *model.bench]}
    assert len(model.starters) == 11
    assert len(model.bench) == 4
    assert workspace.decision.comparison.status == "adopt_recommendation"
    assert workspace.decision.comparison.authoritative_squad == "model"
    assert workspace.decision.comparison.recommendation_candidate_id == model.candidate_id
    assert workspace.decision.comparison.change_count >= 1
    assert workspace.decision.comparison.incoming
    assert workspace.decision.comparison.outgoing
    assert workspace.decision.comparison.churn_protected is True


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
