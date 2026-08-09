from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from fplagent_data.http import sha256_file
from fplagent_web.app import create_app
from fplagent_web.workspace import WorkspaceBuilder


def _weekly_receipt(path: Path) -> None:
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
                    "incoming_player_id": 384,
                    "incoming_name": "Donnarumma",
                    "incoming_price": 55,
                }
            ],
            "formation": "3-4-3",
            "captain_player_id": 426,
            "captain_name": "Bruno Fernandes",
            "vice_captain_player_id": 55,
            "vice_captain_name": "Watkins",
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
            }
        ),
        encoding="utf-8",
    )


def test_workspace_builder_exposes_grounded_gw1_read_model(tmp_path: Path) -> None:
    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    assert workspace.phase.phase == "preseason"
    assert workspace.phase.primary_action == "generate_squad"
    assert workspace.squad.formation == "5-3-2"
    assert len(workspace.squad.starters) == 11
    assert len(workspace.squad.bench) == 4
    assert workspace.squad.confirmed is False
    assert workspace.freshness.refresh_required is True
    assert workspace.freshness.observed_at.endswith("+00:00")
    assert workspace.freshness.model_generated_at.endswith("+00:00")
    assert workspace.freshness.squad_synced_at is None
    assert workspace.freshness.age_seconds >= 0
    assert workspace.freshness.status in {"fresh", "attention", "stale"}
    assert workspace.decision.captain.captain_name == "Bruno Fernandes"
    assert workspace.decision.captain.vice_captain_name == "Tarkowski"
    assert workspace.decision.captain.receipt_id.startswith("captain-v1-")
    assert workspace.squad.starters[0].fixture is not None
    assert len(workspace.decision.horizon) == 5
    assert workspace.decision.weekly.status == "not_available"


def test_workspace_exposes_selected_and_rejected_weekly_actions(tmp_path: Path) -> None:
    weekly_path = tmp_path / "weekly.json"
    _weekly_receipt(weekly_path)

    workspace = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
        weekly_decision_path=weekly_path,
    ).build(now=datetime(2026, 8, 21, 12, tzinfo=UTC))

    weekly = workspace.decision.weekly
    assert weekly.status == "ready"
    assert weekly.event == 2
    assert weekly.selected is not None
    assert weekly.selected.label == "Make one free transfer"
    assert weekly.selected.transfers[0].incoming_name == "Donnarumma"
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
        response = client.post(
            "/api/v1/workspace/refresh", json={"reason": "manual"}
        )

    assert response.status_code == 202
    assert refresh.call == {
        "mode": "weekly",
        "reason": "manual",
        "manager_entry_id": 123,
        "event": 2,
    }


def test_forecast_freshness_is_independent_from_final_deadline_confirmation() -> None:
    assert WorkspaceBuilder._freshness_status(60) == "fresh"
    assert WorkspaceBuilder._freshness_status(21_601) == "attention"
    assert WorkspaceBuilder._freshness_status(86_401) == "stale"


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

    live = WorkspaceBuilder._phase(
        datetime(2026, 8, 22, 12, tzinfo=UTC), events
    )
    events[0]["finished"] = True
    events[0]["data_checked"] = True
    next_desk = WorkspaceBuilder._phase(
        datetime(2026, 8, 24, 12, tzinfo=UTC), events
    )

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
