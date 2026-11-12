from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from fplagent_data.http import sha256_file
from fplagent_llm.runtime_tools import DEFAULT_DECISION
from fplagent_web.app import create_app
from fplagent_web.workspace import WorkspaceBuilder


@pytest.fixture(autouse=True)
def stable_workspace_view_clock(tmp_path, monkeypatch):
    """View tests must not change as live receipts/calendar advance each day.

    This is a presentation fixture, not point-in-time forecast validation. Keep
    the squad shape but freeze its display timestamp and the GW1 live flag.
    Explicit test inputs still take precedence; production files are untouched.
    """
    snapshot = tmp_path / "view-fixture.json"
    payload = json.loads(DEFAULT_DECISION.read_text())
    payload["created_at"] = "2026-08-21T10:00:00+00:00"
    snapshot.write_text(json.dumps(payload))
    monkeypatch.setattr(__import__(__name__), "DEFAULT_DECISION", snapshot)
    original_init = WorkspaceBuilder.__init__
    original_calendar = WorkspaceBuilder._event_calendar

    def init(builder, **kwargs):
        kwargs.setdefault("decision_path", snapshot)
        original_init(builder, **kwargs)

    def calendar(builder):
        return [dict(row, data_checked=False, finished=False) for row in original_calendar(builder)]

    monkeypatch.setattr(WorkspaceBuilder, "__init__", init)
    monkeypatch.setattr(WorkspaceBuilder, "_event_calendar", calendar)


def _weekly_receipt(path: Path) -> None:
    current_starters = [384, 229, 418, 498, 61, 426, 427, 480, 106, 55, 346]
    current_bench = [368, 60, 345, 109]
    transferred_bench = [368, 60, 345, 1]
    action_summaries = [
        {
            "action_id": "roll",
            "route_type": "roll",
            "transfer_count": 0,
            "transfers": [],
            "formation": "3-4-3",
            "captain_player_id": 55,
            "captain_name": "Watkins",
            "vice_captain_player_id": 426,
            "vice_captain_name": "Bruno Fernandes",
            "starter_player_ids": current_starters,
            "bench_player_ids": current_bench,
            "event_lineups": [
                {
                    "event": 2,
                    "formation": "3-4-3",
                    "projected_points": 57.1,
                    "starter_player_ids": current_starters,
                    "bench_player_ids": current_bench,
                    "captain_player_id": 55,
                    "vice_captain_player_id": 426,
                }
            ],
            "incremental_points_cost": 0,
            "next_free_transfers": 2,
            "terminal_free_transfers": 4,
            "terminal_transfer_value": 4.1,
        },
        {
            "action_id": "move",
            "route_type": "one_free_transfer",
            "transfer_count": 1,
            "transfers": [
                {
                    "outgoing_player_id": 109,
                    "outgoing_name": "Verbruggen",
                    "incoming_player_id": 1,
                    "incoming_name": "Raya",
                    "incoming_price": 60,
                }
            ],
            "formation": "3-4-3",
            "captain_player_id": 426,
            "captain_name": "Bruno Fernandes",
            "vice_captain_player_id": 55,
            "vice_captain_name": "Watkins",
            "starter_player_ids": current_starters,
            "bench_player_ids": transferred_bench,
            "event_lineups": [
                {
                    "event": 2,
                    "formation": "3-4-3",
                    "projected_points": 60.2,
                    "starter_player_ids": current_starters,
                    "bench_player_ids": transferred_bench,
                    "captain_player_id": 426,
                    "vice_captain_player_id": 55,
                }
            ],
            "incremental_points_cost": 0,
            "next_free_transfers": 1,
            "terminal_free_transfers": 3,
            "terminal_transfer_value": 3.4,
        },
    ]
    metric = {
        "mean_delta_to_roll": 1.2,
        "delta_to_roll_95ci_low": 0.4,
        "delta_to_roll_95ci_high": 2.0,
        "beat_roll_probability": 0.63,
    }
    roll_metric = {
        "mean_delta_to_roll": 0.0,
        "delta_to_roll_95ci_low": 0.0,
        "delta_to_roll_95ci_high": 0.0,
        "beat_roll_probability": 0.0,
    }
    path.write_text(
        json.dumps(
            {
                "decision_event": 2,
                "created_at": "2026-08-24T10:00:00+00:00",
                "selected_action_id": "move",
                "action_summaries": action_summaries,
                "strongest_rejected": {"action_id": "roll"},
                "method": {
                    "scenario_weights": {
                        "residual": 0.5,
                        "component_anchored": 0.45,
                        "component_raw": 0.05,
                    }
                },
                "scenario_metrics_by_action": {
                    name: {"roll": roll_metric, "move": metric}
                    for name in ("residual", "component_anchored", "component_raw")
                },
                "promotion_gate": {
                    "status": "promoted",
                    "central_scenario": "residual",
                },
                "selected_robust_metrics": {"robust_regret": 0.17},
                "chip_shadow": {
                    "status": "retain_chip",
                    "operational_recommendation": "no_chip",
                    "shadow_preference": {"chip": "bench_boost"},
                    "candidates": [
                        {"checks": [{"name": "retention policy promoted", "passed": False}]}
                    ],
                },
                "squad_chip_shadow": {
                    "status": "retain_chip_uncalibrated_option_value",
                    "operational_recommendation": "no_chip",
                    "shadow_preference": {"chip": "wildcard"},
                    "candidates": [
                        {
                            "checks": [
                                {
                                    "name": "retained chip option value calibrated",
                                    "passed": False,
                                }
                            ]
                        }
                    ],
                },
                "diagnostics": {
                    "early_transfer_shadow": {
                        "status": "ready_shadow",
                        "operational_recommendation": "wait",
                        "route_blocked_by_threshold_stress": True,
                        "next_price_change_at": "2026-08-23T23:00:00+00:00",
                    },
                    "retained_role_counterfactuals": {
                        "status": "evaluated",
                        "watches": [
                            {
                                "element": 527,
                                "player_name": "Richarlison",
                                "expected_minutes": 23.9,
                                "p_play": 0.53,
                                "expected_points": 1.66,
                                "participation_consensus": "single_source_bench",
                                "selected_action_sells_player": False,
                                "best_forced_sale_rank": 3,
                                "best_forced_sale_transfers": [
                                    {
                                        "outgoing_name": "Richarlison",
                                        "incoming_name": "Igor Jesus",
                                    }
                                ],
                                "forced_sale_delta_to_selected": -0.8,
                                "forced_sale_beats_selected": False,
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_weekly_decision_exposes_the_retained_role_sale_challenge(tmp_path: Path) -> None:
    weekly_path = tmp_path / "weekly.json"
    _weekly_receipt(weekly_path)
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        weekly_decision_path=weekly_path,
    )

    weekly = builder._weekly_decision(event=2)

    assert len(weekly.retained_role_watches) == 1
    watch = weekly.retained_role_watches[0]
    assert watch.player_name == "Richarlison"
    assert watch.best_forced_sale_rank == 3
    assert watch.best_forced_sale_transfers[0].incoming_name == "Igor Jesus"
    assert watch.forced_sale_delta_to_selected == -0.8


def test_weekly_decision_exposes_configuration_validation_and_exact_chip_plan(tmp_path):
    path = tmp_path / "weekly.json"
    _weekly_receipt(path)
    payload = json.loads(path.read_text())
    parent = next(s for s in payload["action_summaries"] if s["action_id"] == "roll")
    payload["execution_plan"] = {
        **parent, "configuration_action_id": "roll-triple_captain", "chip": "triple_captain",
    }
    payload["chip_strategy"] = {
        "operational_recommendation": "triple_captain",
        "recommended_action_id": "roll-triple_captain",
        "candidates": [{"action_id": "roll-triple_captain", "parent_action_id": "roll",
                        "chip": "triple_captain"}],
    }
    payload.setdefault("diagnostics", {})["configuration_optimisation"] = {
        "status": "validated", "message": "Frozen lineup passed independent validation.",
    }
    path.write_text(json.dumps(payload))
    view = WorkspaceBuilder(weekly_decision_path=path)._weekly_decision(event=2)
    assert view.status == "ready"
    assert view.selected.action_id == "roll"
    assert view.selected.configuration_action_id == "roll-triple_captain"
    assert view.selected.captain_player_id == parent["captain_player_id"]
    assert view.chip_advice.parent_action_id == "roll"
    assert "independent validation" in view.explanation
    payload["execution_plan"]["configuration_action_id"] = "different-chip"
    path.write_text(json.dumps(payload))
    assert WorkspaceBuilder(weekly_decision_path=path)._weekly_decision(event=2).status == "blocked"


def test_workspace_builder_exposes_grounded_gw1_read_model(tmp_path: Path) -> None:
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    assert workspace.phase.phase == "preseason"
    assert workspace.phase.primary_action == "generate_squad"
    assert workspace.squad.formation == published["decision"]["squad"]["formation"]
    assert len(workspace.squad.starters) == 11
    assert len(workspace.squad.bench) == 4
    assert workspace.squad.confirmed is False
    assert workspace.freshness.refresh_required is True
    assert workspace.freshness.observed_at.endswith("+00:00")
    assert workspace.freshness.model_generated_at.endswith("+00:00")
    assert workspace.freshness.squad_synced_at is None
    assert workspace.freshness.age_seconds >= 0
    assert workspace.freshness.status in {"fresh", "attention", "stale"}
    starter_names = {player["name"] for player in published["decision"]["squad"]["starters"]}
    assert workspace.decision.captain.captain_name in starter_names
    assert workspace.decision.captain.vice_captain_name in starter_names
    assert workspace.decision.captain.receipt_id.startswith("captain-v1-")
    assert workspace.squad.starters[0].fixture is not None
    assert len(workspace.decision.horizon) == 5
    assert workspace.decision.weekly.status == "not_available"


def test_fixture_view_preserves_every_match_in_a_double_gameweek(tmp_path: Path) -> None:
    database = tmp_path / "fixtures.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute("CREATE TABLE fpl_current_teams (id INTEGER, short_name VARCHAR)")
        connection.execute(
            "INSERT INTO fpl_current_teams VALUES (1, 'ARS'), (2, 'CHE'), (3, 'LIV')"
        )
        connection.execute(
            """
            CREATE TABLE fpl_current_fixtures (
                event INTEGER, team_h INTEGER, team_a INTEGER,
                team_h_difficulty INTEGER, team_a_difficulty INTEGER,
                kickoff_time VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO fpl_current_fixtures VALUES
                (25, 1, 2, 2, 4, '2027-02-06T15:00:00+00:00'),
                (25, 3, 1, 3, 3, '2027-02-10T19:45:00+00:00')
            """
        )
    finally:
        connection.close()

    fixtures = WorkspaceBuilder(database_path=database)._fixtures(25)

    assert [row.label for row in fixtures[1]] == ["CHE (H)", "LIV (A)"]
    assert fixtures[1][0].kickoff_time < fixtures[1][1].kickoff_time


def test_workspace_exposes_selected_and_rejected_weekly_actions(
    tmp_path: Path, monkeypatch
) -> None:
    weekly_path = tmp_path / "weekly.json"
    _weekly_receipt(weekly_path)
    original_context = WorkspaceBuilder._participation_context
    requested_players = []

    def context(builder, path, forecasts, **kwargs):
        requested_players.append(set(forecasts))
        summary, rows = original_context(builder, path, forecasts, **kwargs)
        if 1 in forecasts:
            rows[1] = {
                "element": 1,
                "attention": [],
                "official": {"chance": 100, "news": ""},
                "predicted_lineups": {
                    "consensus": "single_source_start",
                    "predicted_start_sources": ["rotowire"],
                },
            }
        return summary, rows

    monkeypatch.setattr(WorkspaceBuilder, "_participation_context", context)

    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        weekly_decision_path=weekly_path,
    ).build(now=datetime(2026, 8, 22, 12, tzinfo=UTC))

    weekly = workspace.decision.weekly
    assert weekly.status == "ready"
    assert weekly.event == 2
    assert weekly.selected is not None
    assert weekly.selected.label == "Make one free transfer"
    assert weekly.selected.transfers[0].incoming_name == "Raya"
    assert weekly.selected.projected_points == 60.2
    assert workspace.phase.phase == "live_gameweek"
    assert workspace.phase.decision_event == 2
    assert workspace.decision.recommended_squad.source == "weekly_decision"
    assert workspace.decision.recommended_squad.event == 2
    assert workspace.decision.recommended_squad.expected_points == 60.2
    assert any(player.player_id == 1 for player in workspace.decision.recommended_squad.bench)
    incoming = next(
        player for player in workspace.decision.recommended_squad.bench if player.player_id == 1
    )
    assert incoming.participation.predicted_start_sources == ["rotowire"]
    assert 1 not in requested_players[0]
    assert any(1 in request for request in requested_players[1:])
    assert workspace.decision.captain.captain_name == "Bruno Fernandes"
    assert workspace.decision.captain.evidence_status == "weekly_decision_receipt"
    assert weekly.chip_advice is not None
    assert weekly.chip_advice.headline == "Save the chips"
    assert weekly.chip_advice.watched_chips == ["bench_boost", "wildcard"]
    assert weekly.execution_timing is not None
    assert weekly.execution_timing.recommendation == "wait"
    assert weekly.execution_timing.affordability_at_risk is True
    assert weekly.strongest_rejected is not None
    assert weekly.strongest_rejected.route_type == "roll"
    assert weekly.expected_gain_vs_roll == 1.2
    assert weekly.confidence_low == 0.4
    assert weekly.beat_roll_probability == 0.63
    assert weekly.receipt_sha256 is not None
    assert workspace.decision.evidence[-1].label == "Weekly action receipt"
    assert workspace.decision.evidence[-1].sha256 == weekly.receipt_sha256


def test_workspace_blocks_an_invalid_weekly_receipt(tmp_path: Path) -> None:
    weekly_path = tmp_path / "weekly.json"
    weekly_path.write_text("{}", encoding="utf-8")

    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        weekly_decision_path=weekly_path,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    assert workspace.decision.weekly.status == "blocked"
    assert workspace.decision.weekly.selected is None
    assert "cannot be trusted" in workspace.decision.weekly.explanation


def test_workspace_hides_weekly_action_when_deadline_evidence_is_blocked(
    tmp_path: Path,
) -> None:
    weekly_path = tmp_path / "weekly.json"
    _weekly_receipt(weekly_path)
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=tmp_path / "deadline-status.json",
        weekly_decision_path=weekly_path,
    )
    forecast_path, component_path = builder._analysis_forecast_paths(2)
    (tmp_path / "deadline-status.json").write_text(
        json.dumps(
            {
                "publishable": False,
                "issues": ["manager snapshot predates the previous Gameweek deadline"],
                "direct_forecast": {"sha256": sha256_file(forecast_path)},
                "component_forecast": {"sha256": sha256_file(component_path)},
                "decision": {"sha256": sha256_file(weekly_path)},
            }
        ),
        encoding="utf-8",
    )

    workspace = builder.build(now=datetime(2026, 8, 22, 12, tzinfo=UTC))

    assert workspace.decision.weekly.status == "blocked"
    assert workspace.decision.weekly.selected is None
    assert "previous Gameweek deadline" in workspace.decision.weekly.explanation
    assert workspace.decision.recommended_squad.source != "weekly_decision"


def test_workspace_api_is_available(tmp_path: Path) -> None:
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    )
    client = TestClient(create_app(workspace_factory=lambda: builder))

    health = client.get("/api/health")
    workspace = client.get("/api/v1/workspace")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "fplagent-web"}
    assert workspace.status_code == 200
    assert workspace.json()["schema_version"] == "fplagent-workspace-v1"


def test_web_lifespan_starts_and_stops_both_daemon_schedulers() -> None:
    class FakeScheduler:
        def __init__(self) -> None:
            self.started = 0
            self.stopped = 0

        def start(self) -> None:
            self.started += 1

        def stop(self) -> None:
            self.stopped += 1

    deadline = FakeScheduler()
    market = FakeScheduler()
    app = create_app(
        scheduler_factory=lambda: deadline,  # type: ignore[arg-type]
        market_scheduler_factory=lambda: market,  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert deadline.started == 1
        assert market.started == 1

    assert deadline.stopped == 1
    assert market.stopped == 1


def test_live_gameweek_manual_refresh_targets_next_decision_event() -> None:
    class FakeScheduler:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class FakeWorkspaceBuilder:
        def build(self):
            class Phase:
                phase = "live_gameweek"
                event = 1
                decision_event = 2

            class Workspace:
                phase = Phase()

            return Workspace()

    class FakeProfileStore:
        def get(self):
            class Profile:
                fpl_entry_id = 123

            return Profile()

    class FakeRefreshCoordinator:
        call: dict[str, object] | None = None

        def request(self, **kwargs):
            self.call = kwargs
            return {
                "status": "running",
                "mode": kwargs["mode"],
                "reason": kwargs["reason"],
                "manager_entry_id": kwargs["manager_entry_id"],
                "event": kwargs["event"],
                "message": "started",
            }

    refresh = FakeRefreshCoordinator()
    scheduler = FakeScheduler()
    app = create_app(
        workspace_factory=FakeWorkspaceBuilder,  # type: ignore[arg-type]
        profile_factory=FakeProfileStore,  # type: ignore[arg-type]
        refresh_factory=lambda: refresh,  # type: ignore[arg-type]
        scheduler_factory=lambda: scheduler,  # type: ignore[arg-type]
        market_scheduler_factory=lambda: scheduler,  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/workspace/refresh", json={"reason": "manual"})

    assert response.status_code == 202
    assert refresh.call == {
        "mode": "weekly",
        "reason": "manual",
        "manager_entry_id": 123,
        "event": 2,
        "deadline_at": None,
    }


def test_forecast_freshness_is_independent_from_final_deadline_confirmation() -> None:
    assert WorkspaceBuilder._freshness_status(60) == "fresh"
    assert WorkspaceBuilder._freshness_status(21_601) == "attention"
    assert WorkspaceBuilder._freshness_status(86_401) == "stale"


def test_deadline_handoff_surfaces_chip_and_minutes_switches() -> None:
    view = WorkspaceBuilder._deadline_handoff_view(
        {
            "verdict": "DEADLINE_READY",
            "publishable": True,
            "chip": {
                "label": "NO_CHIP",
                "strongest_immediate_signal": {
                    "chip": "bench_boost",
                    "cross_family_floor": 12.90396,
                },
            },
            "contingencies": {"routes": 6, "precomputed_fallbacks": 4},
            "participation_break_even": {
                "players": [
                    {
                        "element": 55,
                        "name": "Watkins",
                        "boundary": {
                            "classification": "challenger_boundary_bracketed",
                            "highest_supported_challenger_minutes": 30.0,
                            "next_tested_incumbent_minutes": 45.0,
                            "highest_supported_challenger_squad_id": "R-fallback",
                        },
                    },
                    {
                        "element": 323,
                        "name": "McAteer",
                        "boundary": {
                            "classification": "incumbent_stable_on_tested_minutes",
                            "highest_supported_challenger_minutes": None,
                            "next_tested_incumbent_minutes": 0.0,
                        },
                    },
                ]
            },
        }
    )

    assert view is not None
    assert view.status == "ready"
    assert view.chip_label == "NO_CHIP"
    assert "+12.90" in view.chip_detail
    assert view.precomputed_fallbacks == 4
    assert view.boundaries[0].trigger_expected_minutes == 30.0
    assert view.boundaries[0].fallback_candidate_id == "R-fallback"
    assert view.boundaries[1].stable_on_tested_range is True


def test_workspace_marks_a_superseded_deadline_pack_stale(tmp_path: Path) -> None:
    decision = tmp_path / "decision.json"
    pipeline = tmp_path / "pipeline.json"
    pack = tmp_path / "pack.json"
    decision.write_text('{"decision":{"candidate_id":"new"}}\n', encoding="utf-8")
    pipeline.write_text('{"status":"published"}\n', encoding="utf-8")
    pack.write_text(
        json.dumps(
            {
                "verdict": "DEADLINE_READY",
                "publishable": True,
                "lineage": {
                    "decision_sha256": "old",
                    "pipeline_sha256": sha256_file(pipeline),
                },
            }
        ),
        encoding="utf-8",
    )
    builder = WorkspaceBuilder(
        decision_path=decision,
        deadline_pack_path=pack,
        deadline_pipeline_path=pipeline,
    )

    stored = builder._deadline_pack()
    view = builder._deadline_handoff_view(stored)

    assert stored["verdict"] == "STALE"
    assert stored["publishable"] is False
    assert view is not None
    assert view.status == "blocked"


def test_phase_resolver_advances_from_live_event_to_next_decision_deadline() -> None:
    events = [
        {
            "event": 1,
            "name": "Gameweek 1",
            "deadline": "2026-08-21T17:30:00+00:00",
            "finished": False,
            "data_checked": False,
        },
        {
            "event": 2,
            "name": "Gameweek 2",
            "deadline": "2026-08-28T17:30:00+00:00",
            "finished": False,
            "data_checked": False,
        },
    ]

    live = WorkspaceBuilder._phase(datetime(2026, 8, 22, 12, tzinfo=UTC), events)
    events[0]["finished"] = True
    events[0]["data_checked"] = True
    next_desk = WorkspaceBuilder._phase(datetime(2026, 8, 24, 12, tzinfo=UTC), events)

    assert live.phase == "live_gameweek"
    assert live.event == 1
    assert live.decision_event == 2
    assert live.decision_deadline == "2026-08-28T17:30:00+00:00"
    assert next_desk.phase == "pre_deadline"
    assert next_desk.event == 2
    assert next_desk.primary_action == "manage_team"


def test_failed_deadline_evidence_gate_forces_visible_refresh_state(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "deadline-status.json"
    status_path.write_text(
        json.dumps(
            {
                "publishable": False,
                "issues": [
                    "direct_forecast: forecast source snapshot does not match",
                    "decision: decision predates the current official snapshot",
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=status_path,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    assert workspace.freshness.status == "stale"
    assert workspace.freshness.refresh_required is True
    assert workspace.freshness.message.startswith("Decision refresh required:")
    assert "forecast source snapshot" in workspace.freshness.message


def test_deadline_receipt_cannot_validate_a_mixed_published_generation(
    tmp_path: Path,
) -> None:
    forecast = tmp_path / "forecast.parquet"
    component = tmp_path / "component.parquet"
    decision = tmp_path / "decision.json"
    status = tmp_path / "deadline.json"
    forecast.write_bytes(b"new-forecast")
    component.write_bytes(b"old-component")
    decision.write_text("{}", encoding="utf-8")
    status.write_text(
        json.dumps(
            {
                "publishable": True,
                "issues": [],
                "direct_forecast": {"sha256": sha256_file(forecast)},
                "component_forecast": {"sha256": "not-the-component"},
                "decision": {"sha256": sha256_file(decision)},
            }
        ),
        encoding="utf-8",
    )
    builder = WorkspaceBuilder(
        decision_path=decision,
        forecast_path=forecast,
        component_path=component,
        deadline_status_path=status,
        active_decision_path=None,
    )

    result = builder._deadline_evidence_status()

    assert result is not None
    assert result["publishable"] is False
    assert any("component forecast" in issue for issue in result["issues"])


def test_workspace_joins_aligned_participation_evidence_and_minute_bands(
    tmp_path: Path,
) -> None:
    decision = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    selected = decision["decision"]["candidate"]["selected"]
    flagged = int(selected[0])
    consensus_path = tmp_path / "participation-consensus.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event": 1,
                    "element": int(element),
                    "official_chance": 100,
                    "official_news": "",
                    "attention": [],
                    "consensus": "single_source_start",
                    "predicted_start_sources": ["rotowire"],
                    "predicted_not_start_sources": [],
                    "complete_source_count": 1,
                }
                for element in selected
            ]
        ),
        consensus_path,
    )
    watch_path = tmp_path / "availability.json"
    watch_path.write_text(
        json.dumps(
            {
                "current": True,
                "checked_at": "2026-08-21T10:00:00+00:00",
                "lineage": {
                    "decision_sha256": sha256_file(DEFAULT_DECISION),
                    "forecast_sha256": sha256_file(WorkspaceBuilder().forecast_path),
                },
                "summary": {
                    "selected_players": 15,
                    "official_attention": 0,
                    "role_verification": 1,
                    "uncovered_club_feed": 0,
                    "no_attention": 14,
                },
                "scenario_stability": {
                    "baseline_stable": True,
                    "moderate_stable": True,
                },
                "predicted_lineup_consensus": {
                    "current": True,
                    "status": "shadow_consensus_partial",
                    "eligible_source_count": 1,
                    "captured_source_count": 2,
                },
                "coverage": {"teams": 20, "teams_with_confirmed_lineups": 19},
                "decision_impacts": [],
                "players": [
                    {
                        "element": flagged,
                        "attention": ["three_plus_lineup_absence"],
                        "official": {"chance": 100, "news": ""},
                        "preseason": {
                            "eligible_team_matches": 4,
                            "squad_listings": 0,
                            "starts": 0,
                            "appearances": 0,
                            "last_match_listed": False,
                            "last_match_started": None,
                        },
                        "supported_edge_sensitivity": None,
                        "predicted_lineups": {
                            "consensus": "single_source_start",
                            "predicted_start_sources": ["rotowire"],
                            "predicted_not_start_sources": [],
                            "complete_source_count": 1,
                            "production_weight": 0.0,
                            "production_adjustment_authorized": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        availability_watch_path=watch_path,
        participation_consensus_path=consensus_path,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    player = next(
        row for row in workspace.squad.starters + workspace.squad.bench if row.player_id == flagged
    )
    assert workspace.participation.status == "attention"
    assert workspace.participation.teams_with_confirmed_lineups == 19
    assert workspace.participation.predicted_start_support == 15
    assert workspace.participation.predicted_lineup_eligible_sources == 1
    assert workspace.participation.predicted_lineup_captured_sources == 2
    assert player.participation.evidence_status == "verify_role"
    assert player.participation.predicted_start_sources == ["rotowire"]
    assert player.participation.states.dnp == round(1 - player.play_probability, 4)
    assert "4 tracked preseason lineups" in player.participation.detail

    active_path = tmp_path / "connected.json"
    decision["workspace_candidate"] = {
        **(decision.get("workspace_candidate") or {}),
        "source": "connected",
        "source_label": "Authenticated FPL squad",
    }
    active_path.write_text(json.dumps(decision), encoding="utf-8")
    connected = WorkspaceBuilder(
        active_decision_path=active_path,
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        availability_watch_path=watch_path,
        participation_consensus_path=consensus_path,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))
    connected_player = next(
        row for row in connected.squad.starters + connected.squad.bench if row.player_id == flagged
    )
    assert connected_player.participation.evidence_status == "verify_role"
    assert connected.participation.baseline_stable is None
    assert connected.participation.alternatives == []
    assert "Squad-specific stress alternatives are hidden" in connected.participation.detail


def test_workspace_exposes_only_a_hash_aligned_successful_app_open_receipt(
    tmp_path: Path,
) -> None:
    pipeline = tmp_path / "pipeline.json"
    pipeline.write_text('{"status":"published"}\n', encoding="utf-8")
    refresh = tmp_path / "refresh.json"
    refresh.write_text(
        json.dumps(
            {
                "schema_version": "workspace-refresh-v1",
                "run_id": "refresh-v1-test",
                "status": "reused",
                "mode": "gw1",
                "reason": "app_open",
                "requested_at": "2026-08-08T09:00:00+00:00",
                "started_at": "2026-08-08T09:00:00+00:00",
                "completed_at": "2026-08-08T09:00:04+00:00",
                "manager_entry_id": None,
                "event": 1,
                "published": True,
                "reused": True,
                "input_fingerprint": "generation-1",
                "receipt_path": str(pipeline),
                "receipt_sha256": sha256_file(pipeline),
                "completed_stages": [],
                "message": "The current decision is still exact.",
            }
        ),
        encoding="utf-8",
    )
    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        refresh_state_path=refresh,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    evidence = workspace.decision.evidence[-1]
    assert evidence.label == "App-open decision pipeline"
    assert evidence.path == str(pipeline)
    assert evidence.sha256 == sha256_file(pipeline)

    pipeline.write_text('{"status":"tampered"}\n', encoding="utf-8")
    rebuilt = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        refresh_state_path=refresh,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))
    assert all(item.label != "App-open decision pipeline" for item in rebuilt.decision.evidence)


def test_joint_chip_strategy_is_exposed_with_expiry_and_calendar() -> None:
    advice = WorkspaceBuilder._chip_advice_view(
        {
            "operational_recommendation": "no_chip",
            "headline": "Retain all chips this Gameweek",
            "reason": "GW4 has the stronger collision-aware Bench Boost window.",
            "half_expiry_event": 19,
            "events_until_expiry": 16,
            "candidates": [
                {
                    "chip": "bench_boost",
                    "checks": [
                        {
                            "name": "positive joint retained-value edge",
                            "passed": False,
                        }
                    ],
                }
            ],
            "visible_calendar": [
                {
                    "event": 4,
                    "chip": "bench_boost",
                    "projected_uplift": 12.4,
                }
            ],
        },
        {},
        {},
    )

    assert advice is not None
    assert advice.headline == "Retain all chips this Gameweek"
    assert advice.half_expiry_event == 19
    assert advice.next_opportunities[0].event == 4
    assert advice.next_opportunities[0].projected_uplift == 12.4
    assert advice.blockers == ["positive joint retained-value edge"]
    assert advice.candidate_statuses[0].status == "needs_review"


def test_chip_status_distinguishes_retention_research_and_missing_branch():
    advice = WorkspaceBuilder._chip_advice_view(
        {
            "operational_recommendation": "no_chip",
            "available_chips": ["bench_boost", "triple_captain", "wildcard", "free_hit"],
            "calibration": {"authority_by_chip": {"bench_boost": True, "wildcard": False}},
            "candidates": [
                {"chip": "bench_boost", "joint_net_value": -2, "checks": []},
                {
                    "chip": "wildcard",
                    "joint_net_value": 5,
                    "checks": [{"name": "historical outcome authority", "passed": False}],
                },
            ],
        },
        {},
        {},
    )
    statuses = {row.chip: row for row in advice.candidate_statuses}
    assert statuses["bench_boost"].status == "retain"
    assert statuses["wildcard"].status == "research_only"
    assert statuses["wildcard"].joint_net_value == 5
    assert statuses["free_hit"].status == "not_evaluated"
    assert advice.needs_review
    assert "unresolved" in advice.headline
    assert "does NOT establish" in advice.detail


def test_weekly_confidence_keeps_its_own_mean_and_scenario(tmp_path):
    path = tmp_path / "weekly.json"
    _weekly_receipt(path)
    payload = json.loads(path.read_text())
    payload["method"]["scenario_weights"] = {"residual": 0.6, "stress": 0.4}
    payload["scenario_metrics_by_action"]["stress"] = {
        key: {**value, "mean_delta_to_roll": -0.2}
        for key, value in payload["scenario_metrics_by_action"]["residual"].items()
    }
    payload["promotion_gate"]["status"] = "promoted_after_rejections"
    path.write_text(json.dumps(payload))
    weekly = WorkspaceBuilder(weekly_decision_path=path)._weekly_decision(event=2)
    assert abs(weekly.expected_gain_vs_roll - 0.64) < 1e-9
    assert weekly.confidence_mean == 1.2
    assert weekly.confidence_scenario == "residual"
    assert "Higher-ranked moves failed" in weekly.explanation


def test_fallback_lineup_evidence_does_not_invent_a_second_source(tmp_path):
    consensus = tmp_path / "one-source.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "element": 1,
                    "consensus": "single_source_start",
                    "predicted_start_sources": ["rotowire"],
                    "predicted_not_start_sources": [],
                    "complete_source_count": 1,
                }
            ]
        ),
        consensus,
    )
    builder = WorkspaceBuilder(availability_watch_path=None)
    summary, _ = builder._participation_context(
        builder.decision_path, {1: {}}, consensus_path=consensus
    )
    assert summary.predicted_lineup_eligible_sources == 1
    assert summary.predicted_lineup_captured_sources == 1
