from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fplagent_web.deadline_scheduler import DeadlineRefreshScheduler
from fplagent_web.models import ManagerProfileView, WorkspaceRefreshView
from fplagent_web.official_change_probe import OfficialChangeProbeResult


class FakeRefreshCoordinator:
    def __init__(self) -> None:
        self.current = WorkspaceRefreshView(
            status="idle",
            message="No decision refresh has run yet.",
        )
        self.requests: list[dict[str, Any]] = []

    def status(self) -> WorkspaceRefreshView:
        return self.current

    def request(self, **kwargs: Any) -> WorkspaceRefreshView:
        self.requests.append(kwargs)
        self.current = WorkspaceRefreshView(
            run_id=f"refresh-{len(self.requests)}",
            status="running",
            mode=kwargs["mode"],
            reason=kwargs["reason"],
            requested_at="2026-08-18T18:00:00+00:00",
            started_at="2026-08-18T18:00:00+00:00",
            manager_entry_id=kwargs["manager_entry_id"],
            event=kwargs["event"],
            message="Refresh started.",
        )
        return self.current


def _profile() -> ManagerProfileView:
    return ManagerProfileView(
        display_name="Lewis",
        fpl_entry_id=431892,
        sync_state="mcp_connected",
        last_synced_at="2026-08-18T17:59:00+00:00",
        message="Connected.",
    )


def _workspace(now: datetime) -> SimpleNamespace:
    gw1_deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    if now < gw1_deadline:
        event = 1
        deadline = gw1_deadline
    else:
        event = 2
        deadline = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)
    return SimpleNamespace(
        phase=SimpleNamespace(
            decision_event=event,
            event=event,
            decision_deadline=deadline.isoformat(),
            deadline=deadline.isoformat(),
        )
    )


def _scheduler(
    tmp_path: Path,
    *,
    now: list[datetime],
    refresh: FakeRefreshCoordinator,
) -> DeadlineRefreshScheduler:
    return DeadlineRefreshScheduler(
        workspace_loader=lambda: _workspace(now[0]),  # type: ignore[arg-type]
        profile_loader=_profile,
        refresh_coordinator=refresh,  # type: ignore[arg-type]
        state_path=tmp_path / "schedule.json",
        clock=lambda: now[0],
        retry_seconds=900,
    )


def test_scheduler_starts_initial_six_hour_cadence_once(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 18, 16, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)

    started = scheduler.tick()
    now[0] = datetime(2026, 8, 18, 18, tzinfo=UTC)
    joined = scheduler.tick()

    assert started.status == "running"
    assert started.active_window == "6-hour cadence"
    assert started.cadence_minutes == 360
    assert refresh.requests[0]["reason"] == "scheduled"
    assert refresh.requests[0]["mode"] == "gw1"
    assert joined.status == "running"
    assert len(refresh.requests) == 1


def test_successful_refresh_after_window_marks_it_covered(tmp_path: Path) -> None:
    now = [datetime(2026, 8, 18, 18, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)
    scheduler.tick()
    refresh.current = WorkspaceRefreshView(
        run_id="refresh-1",
        status="published",
        mode="gw1",
        reason="scheduled",
        requested_at=now[0].isoformat(),
        started_at=now[0].isoformat(),
        completed_at=(now[0] + timedelta(minutes=1)).isoformat(),
        manager_entry_id=431892,
        event=1,
        published=True,
        message="Published.",
    )
    now[0] += timedelta(minutes=2)

    covered = scheduler.tick()

    assert covered.status == "covered"
    assert covered.active_window == "6-hour cadence"
    assert covered.next_window_at == "2026-08-19T00:01:00+00:00"
    assert covered.refresh_run_id == "refresh-1"


def test_scheduler_catches_up_only_latest_window_and_throttles_retry(
    tmp_path: Path,
) -> None:
    # Five hours remain, so the agreed final-day cadence is two hours.
    now = [datetime(2026, 8, 21, 12, 30, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)

    first = scheduler.tick()
    refresh.current = WorkspaceRefreshView(
        run_id="refresh-1",
        status="failed",
        mode="gw1",
        reason="scheduled",
        requested_at=now[0].isoformat(),
        started_at=now[0].isoformat(),
        completed_at=now[0].isoformat(),
        manager_entry_id=431892,
        event=1,
        message="Failed.",
    )
    now[0] += timedelta(minutes=5)
    held = scheduler.tick()
    now[0] += timedelta(minutes=11)
    retried = scheduler.tick()

    assert first.active_window == "2-hour cadence"
    assert held.status == "waiting"
    assert "retry is held" in held.message
    assert held.next_window_at == "2026-08-21T12:45:00+00:00"
    assert len(refresh.requests) == 2
    assert retried.status == "running"


def test_missing_manager_state_waits_then_resumes_immediately_after_sync(tmp_path: Path) -> None:
    now = [datetime(2026, 8, 27, 12, 0, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    refresh.current = WorkspaceRefreshView(
        status="not_ready", event=2, manager_entry_id=431892,
        started_at="2026-08-27T11:59:00+00:00", completed_at=now[0].isoformat(),
        message="Reconnect FPL for a current manager snapshot.",
    )
    profile = [_profile()]
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)
    scheduler.profile_loader = lambda: profile[0]
    assert scheduler.tick().status == "waiting"
    now[0] += timedelta(hours=1)
    waiting = scheduler.tick()
    assert not refresh.requests
    assert waiting.next_window_at is None
    assert "no refresh is running" in waiting.message
    profile[0] = profile[0].model_copy(update={"last_synced_at": now[0].isoformat()})
    assert scheduler.tick().status == "running"
    assert len(refresh.requests) == 1
    assert refresh.requests[0]["mode"] == "weekly"
    assert refresh.requests[0]["event"] == 2
    scheduler.tick()
    assert len(refresh.requests) == 1


def test_scheduler_does_not_retry_deterministic_block_after_timeout(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 21, 12, 30, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)
    scheduler.tick()
    refresh.current = WorkspaceRefreshView(
        run_id="refresh-1",
        status="blocked",
        mode="gw1",
        reason="scheduled",
        requested_at=now[0].isoformat(),
        started_at=now[0].isoformat(),
        completed_at=now[0].isoformat(),
        manager_entry_id=431892,
        event=1,
        failure_code="preseason_role_evidence_incoherent",
        message="Automatic retries are paused.",
    )
    now[0] += timedelta(hours=2)

    held = scheduler.tick()

    assert held.status == "waiting"
    assert "automatic retries are paused" in held.message.lower()
    assert len(refresh.requests) == 1


def test_scheduler_moves_to_next_event_after_current_deadline(tmp_path: Path) -> None:
    now = [datetime(2026, 8, 21, 17, 31, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)

    result = scheduler.tick()

    assert result.status == "running"
    assert result.event == 2
    assert result.next_window == "6-hour cadence"
    assert refresh.requests[0]["event"] == 2


def test_live_gameweek_scheduler_targets_the_next_decision_event(
    tmp_path: Path,
) -> None:
    # GW1 is live, but the actionable cadence belongs to the GW2 deadline.
    now = [datetime(2026, 8, 25, 18, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)

    result = scheduler.tick()

    assert result.status == "running"
    assert result.event == 2
    assert result.active_window == "6-hour cadence"
    assert refresh.requests[0]["mode"] == "weekly"
    assert refresh.requests[0]["event"] == 2


def test_material_official_change_triggers_once_and_is_covered_after_publish(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 18, 20, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    probe_calls = 0

    def changed_probe() -> OfficialChangeProbeResult:
        nonlocal probe_calls
        probe_calls += 1
        return OfficialChangeProbeResult(
            checked_at=now[0].isoformat(),
            changed=True,
            local_fingerprint="old-generation",
            remote_fingerprint="new-generation",
        )

    scheduler = DeadlineRefreshScheduler(
        workspace_loader=lambda: _workspace(now[0]),  # type: ignore[arg-type]
        profile_loader=_profile,
        refresh_coordinator=refresh,  # type: ignore[arg-type]
        material_probe=changed_probe,
        state_path=tmp_path / "schedule.json",
        clock=lambda: now[0],
    )

    started = scheduler.tick()
    joined = scheduler.tick()

    assert started.status == "running"
    assert started.active_window == "material-change"
    assert started.material_change_detected is True
    assert refresh.requests == [
        {
            "mode": "gw1",
            "reason": "material_change",
            "manager_entry_id": 431892,
            "event": 1,
            "deadline_at": datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
        }
    ]
    assert joined.status == "running"
    assert probe_calls == 1

    refresh.current = WorkspaceRefreshView(
        run_id="refresh-1",
        status="published",
        mode="gw1",
        reason="material_change",
        requested_at=now[0].isoformat(),
        started_at=now[0].isoformat(),
        completed_at=(now[0] + timedelta(seconds=30)).isoformat(),
        manager_entry_id=431892,
        event=1,
        published=True,
        message="Published.",
    )
    now[0] += timedelta(minutes=1)

    covered = scheduler.tick()

    assert covered.status == "covered"
    assert covered.material_change_detected is False
    assert covered.next_window_at == "2026-08-19T02:00:30+00:00"
    assert len(refresh.requests) == 1


def test_material_change_does_not_duplicate_a_blocked_app_open_attempt(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 18, 20, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    refresh.current = WorkspaceRefreshView(
        run_id="app-open-blocked",
        status="blocked",
        mode="gw1",
        reason="app_open",
        requested_at=now[0].isoformat(),
        started_at=now[0].isoformat(),
        completed_at=now[0].isoformat(),
        manager_entry_id=431892,
        event=1,
        failure_code="preseason_role_evidence_incoherent",
        message="Role evidence could not be made coherent.",
    )
    scheduler = DeadlineRefreshScheduler(
        workspace_loader=lambda: _workspace(now[0]),  # type: ignore[arg-type]
        profile_loader=_profile,
        refresh_coordinator=refresh,  # type: ignore[arg-type]
        material_probe=lambda: OfficialChangeProbeResult(
            checked_at=now[0].isoformat(),
            changed=True,
            local_fingerprint="old-generation",
            remote_fingerprint="new-generation",
        ),
        state_path=tmp_path / "schedule.json",
        clock=lambda: now[0],
    )

    result = scheduler.tick()

    assert result.status == "waiting"
    assert "automatic retries are paused" in result.message.lower()
    assert refresh.requests == []


def test_material_probe_does_not_mutate_evidence_during_active_refresh(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 28, 11, 50, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    refresh.current = WorkspaceRefreshView(
        run_id="manual-weekly",
        status="running",
        mode="weekly",
        reason="manual",
        requested_at=now[0].isoformat(),
        started_at=now[0].isoformat(),
        manager_entry_id=431892,
        event=2,
        message="Building the GW2 decision.",
    )
    probe_calls = 0

    def material_probe() -> OfficialChangeProbeResult:
        nonlocal probe_calls
        probe_calls += 1
        return OfficialChangeProbeResult(
            checked_at=now[0].isoformat(),
            changed=False,
            local_fingerprint="same",
            remote_fingerprint="same",
        )

    scheduler = DeadlineRefreshScheduler(
        workspace_loader=lambda: _workspace(now[0]),  # type: ignore[arg-type]
        profile_loader=_profile,
        refresh_coordinator=refresh,  # type: ignore[arg-type]
        material_probe=material_probe,
        state_path=tmp_path / "schedule.json",
        clock=lambda: now[0],
    )

    result = scheduler.tick()

    assert result.status == "running"
    assert result.refresh_run_id == "manual-weekly"
    assert probe_calls == 0
