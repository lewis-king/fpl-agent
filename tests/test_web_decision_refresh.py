from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fplagent_web.app import create_app
from fplagent_web.decision_refresh import WorkspaceRefreshCoordinator
from fplagent_web.models import WorkspaceRefreshView
from fplagent_web.profile import ManagerProfileStore
from fplagent_web.workspace import WorkspaceBuilder


class DeterministicPipelineError(ValueError):
    code = "stale_preseason_role_evidence"
    retryable = False


def _wait_for_terminal(
    coordinator: WorkspaceRefreshCoordinator,
    *,
    timeout: float = 2.0,
) -> WorkspaceRefreshView:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = coordinator.status()
        if state.status != "running":
            return state
        time.sleep(0.005)
    raise AssertionError("workspace refresh did not finish")


def test_refresh_coordinator_is_single_flight_and_persists_publication(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[dict[str, Any]] = []

    def runner(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        entered.set()
        assert release.wait(timeout=1)
        return {
            "status": "published",
            "published": True,
            "reused": False,
            "input_fingerprint": "generation-1",
            "stages": [{"name": "initial_squad"}, {"name": "synthesis"}],
            "message": "A coherent decision is active.",
        }

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
        gw1_receipt_path=tmp_path / "pipeline.json",
        clock=lambda: datetime(2026, 8, 8, 10, tzinfo=UTC),
    )
    (tmp_path / "pipeline.json").write_text("pipeline receipt", encoding="utf-8")
    first = coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )
    assert entered.wait(timeout=1)
    second = coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )

    assert first.status == "running"
    assert second.run_id == first.run_id
    assert len(calls) == 1
    assert calls[0]["reuse_latest_official"] is False

    release.set()
    final = _wait_for_terminal(coordinator)

    assert final.status == "published"
    assert final.published is True
    assert final.input_fingerprint == "generation-1"
    assert final.receipt_path == str(tmp_path / "pipeline.json")
    assert final.receipt_sha256 is not None
    assert final.completed_stages == ["initial_squad", "synthesis"]
    assert (
        WorkspaceRefreshView.model_validate_json(
            (tmp_path / "refresh.json").read_text(encoding="utf-8")
        )
        == final
    )


def test_failed_refresh_keeps_previous_artifact_and_reports_safe_failure(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.json"
    active.write_text("previous validated receipt", encoding="utf-8")

    def runner(**_: Any) -> dict[str, Any]:
        raise RuntimeError("upstream unavailable")

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
    )
    coordinator.request(
        mode="gw1",
        reason="manual",
        manager_entry_id=None,
        event=1,
    )
    final = _wait_for_terminal(coordinator)

    assert final.status == "failed"
    assert "last valid workspace was retained" in final.message
    assert active.read_text(encoding="utf-8") == "previous validated receipt"


def test_deterministic_refresh_failure_blocks_automatic_retry(tmp_path: Path) -> None:
    def runner(**_: Any) -> dict[str, Any]:
        raise DeterministicPipelineError("role evidence is incoherent")

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
    )
    coordinator.request(
        mode="gw1",
        reason="material_change",
        manager_entry_id=431892,
        event=1,
    )

    final = _wait_for_terminal(coordinator)

    assert final.status == "blocked"
    assert final.failure_code == "stale_preseason_role_evidence"
    assert "automatic retries are paused" in final.message


def test_app_open_reuses_recent_terminal_refresh_but_manual_bypasses(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 8, 10, tzinfo=UTC)]
    calls = 0

    def runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "status": "published",
            "published": True,
            "reused": False,
            "message": "Published current evidence.",
        }

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
        gw1_receipt_path=tmp_path / "pipeline.json",
        clock=lambda: now[0],
    )
    coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )
    _wait_for_terminal(coordinator)
    assert calls == 1

    now[0] += timedelta(hours=2)
    cached = coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )

    assert cached.status == "reused"
    assert cached.reused is True
    assert "6-hour app-open window" in cached.message
    assert calls == 1

    coordinator.request(
        mode="gw1",
        reason="manual",
        manager_entry_id=431892,
        event=1,
    )
    _wait_for_terminal(coordinator)
    assert calls == 2


def test_recent_blocked_refresh_is_not_retried_by_app_open(tmp_path: Path) -> None:
    calls = 0

    def runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise DeterministicPipelineError("role evidence is incoherent")

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
        gw1_receipt_path=tmp_path / "pipeline.json",
        clock=lambda: datetime(2026, 8, 8, 10, tzinfo=UTC),
    )
    coordinator.request(
        mode="gw1",
        reason="material_change",
        manager_entry_id=431892,
        event=1,
    )
    blocked = _wait_for_terminal(coordinator)

    cached = coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )

    assert blocked.status == "blocked"
    assert cached.run_id == blocked.run_id
    assert cached.status == "blocked"
    assert calls == 1


def test_newer_external_publication_invalidates_a_cached_block(tmp_path: Path) -> None:
    calls = 0
    pipeline = tmp_path / "pipeline.json"

    def runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise DeterministicPipelineError("role evidence is incoherent")

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
        gw1_receipt_path=pipeline,
        clock=lambda: datetime(2026, 8, 8, 11, tzinfo=UTC),
    )
    coordinator.request(
        mode="gw1",
        reason="material_change",
        manager_entry_id=431892,
        event=1,
    )
    assert _wait_for_terminal(coordinator).status == "blocked"
    pipeline.write_text(
        '{"status":"published","checked_at":"2026-08-08T11:30:00+00:00"}\n',
        encoding="utf-8",
    )

    restarted = coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )

    assert restarted.status == "running"
    assert _wait_for_terminal(coordinator).status == "blocked"
    assert calls == 2


def test_changed_gw1_implementation_invalidates_a_cached_block(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    calls = 0
    pipeline = tmp_path / "pipeline.json"

    def runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise DeterministicPipelineError("role evidence is incoherent")

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
        gw1_receipt_path=pipeline,
        clock=lambda: datetime(2026, 8, 8, 11, tzinfo=UTC),
    )
    coordinator.request(
        mode="gw1",
        reason="material_change",
        manager_entry_id=431892,
        event=1,
    )
    assert _wait_for_terminal(coordinator).status == "blocked"
    pipeline.write_text(
        """{
  "status": "failed",
  "checked_at": "2026-08-08T11:00:00+00:00",
  "input_identity": {"implementation_sha256": "old-implementation"}
}\n""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fplagent_web.decision_refresh.gw1_pipeline_implementation_sha256",
        lambda: "new-implementation",
    )

    coordinator.request(
        mode="gw1",
        reason="app_open",
        manager_entry_id=431892,
        event=1,
    )

    assert _wait_for_terminal(coordinator).status == "blocked"
    assert calls == 2


def test_running_refresh_surfaces_pipeline_stage_progress(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    receipt = tmp_path / "pipeline.json"
    requested_at = "2026-08-08T10:00:00+00:00"

    def runner(**_: Any) -> dict[str, Any]:
        receipt.write_text(
            """{
  "status": "running",
  "checked_at": "2026-08-08T10:00:00+00:00",
  "current_stage": "robust_search",
  "total_stages": 11,
  "stages": [
    {"name": "initial_squad"},
    {"name": "residual_tournament"},
    {"name": "component_selection"},
    {"name": "component_candidates"},
    {"name": "component_holdout"}
  ]
}\n""",
            encoding="utf-8",
        )
        entered.set()
        assert release.wait(timeout=1)
        return {"status": "blocked", "message": "test finished"}

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        gw1_runner=runner,
        gw1_receipt_path=receipt,
        clock=lambda: datetime.fromisoformat(requested_at),
    )
    coordinator.request(
        mode="gw1",
        reason="manual",
        manager_entry_id=431892,
        event=1,
    )
    assert entered.wait(timeout=1)

    running = coordinator.status()

    assert running.current_stage == "robust_search"
    assert running.completed_stage_count == 5
    assert running.total_stages == 11
    assert running.progress_percent == 45
    assert running.message == "Stage 6 of 11: searching globally robust squads."
    release.set()
    _wait_for_terminal(coordinator)


def test_orphaned_in_process_worker_is_failed_closed(tmp_path: Path) -> None:
    state = WorkspaceRefreshView(
        run_id="refresh-v1-orphan",
        status="running",
        mode="gw1",
        reason="manual",
        requested_at="2026-08-08T10:00:00+00:00",
        started_at="2026-08-08T10:00:00+00:00",
        event=1,
        message="Refresh started.",
    )
    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        clock=lambda: datetime(2026, 8, 8, 12, tzinfo=UTC),
    )
    coordinator._write_state(state)
    coordinator._active_run_id = state.run_id
    coordinator._worker = threading.Thread(target=lambda: None)

    result = coordinator.status()

    assert result.status == "failed"
    assert result.failure_code == "refresh_worker_terminated"
    assert result.completed_at == "2026-08-08T12:00:00+00:00"
    assert "last valid workspace was retained" in result.message
    assert coordinator._active_run_id is None


def test_weekly_refresh_requires_a_manager_identity_without_starting_runner(
    tmp_path: Path,
) -> None:
    calls = 0

    def runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    coordinator = WorkspaceRefreshCoordinator(
        state_path=tmp_path / "refresh.json",
        weekly_runner=runner,
    )
    result = coordinator.request(
        mode="weekly",
        reason="app_open",
        manager_entry_id=None,
        event=2,
    )

    assert result.status == "blocked"
    assert result.published is False
    assert calls == 0


class FakeRefreshCoordinator:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.current = WorkspaceRefreshView(
            status="idle",
            message="No decision refresh has run yet.",
        )

    def request(self, **kwargs: Any) -> WorkspaceRefreshView:
        self.requests.append(kwargs)
        self.current = WorkspaceRefreshView(
            run_id="refresh-v1-test",
            status="running",
            mode=kwargs["mode"],
            reason=kwargs["reason"],
            requested_at="2026-08-08T10:00:00+00:00",
            started_at="2026-08-08T10:00:00+00:00",
            manager_entry_id=kwargs["manager_entry_id"],
            event=kwargs["event"],
            message="Refresh started.",
        )
        return self.current

    def status(self) -> WorkspaceRefreshView:
        return self.current


def test_workspace_get_is_fast_read_only_and_refresh_has_explicit_start_contract(
    tmp_path: Path,
) -> None:
    refresh = FakeRefreshCoordinator()
    profile = ManagerProfileStore(tmp_path / "profile.json")
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    )
    client = TestClient(
        create_app(
            workspace_factory=lambda: builder,
            profile_factory=lambda: profile,
            refresh_factory=lambda: refresh,  # type: ignore[arg-type]
        )
    )

    workspace = client.get("/api/v1/workspace")
    started = client.post("/api/v1/workspace/refresh", json={"reason": "app_open"})
    status = client.get("/api/v1/workspace/refresh")

    assert workspace.status_code == 200
    assert refresh.requests == [
        {
            "mode": "gw1",
            "reason": "app_open",
            "manager_entry_id": None,
            "event": 1,
        }
    ]
    assert started.status_code == 202
    assert started.json()["status"] == "running"
    assert status.json()["run_id"] == "refresh-v1-test"
