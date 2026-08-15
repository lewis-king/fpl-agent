from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fplagent_web.deadline_scheduler import DeadlineRefreshScheduler
from fplagent_web.models import ManagerProfileView, WorkspaceRefreshView
from fplagent_web.official_change_probe import OfficialChangeProbeResult
from fplagent_web.workspace import WorkspaceBuilder


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


def _scheduler(
    tmp_path: Path,
    *,
    now: list[datetime],
    refresh: FakeRefreshCoordinator,
) -> DeadlineRefreshScheduler:
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    )
    return DeadlineRefreshScheduler(
        workspace_loader=lambda: builder.build(now=now[0]),
        profile_loader=_profile,
        refresh_coordinator=refresh,  # type: ignore[arg-type]
        state_path=tmp_path / "schedule.json",
        clock=lambda: now[0],
        retry_seconds=900,
    )


def test_scheduler_waits_before_first_window_then_triggers_t72_once(
    tmp_path: Path,
) -> None:
    now = [datetime(2026, 8, 18, 16, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)

    waiting = scheduler.tick()
    now[0] = datetime(2026, 8, 18, 18, tzinfo=UTC)
    started = scheduler.tick()
    joined = scheduler.tick()

    assert waiting.status == "waiting"
    assert waiting.next_window == "T-72h"
    assert started.status == "running"
    assert started.active_window == "T-72h"
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
    assert covered.active_window == "T-72h"
    assert covered.refresh_run_id == "refresh-1"


def test_scheduler_catches_up_only_latest_window_and_throttles_retry(
    tmp_path: Path,
) -> None:
    # The deadline is 21 Aug 17:30 UTC, so 12:30 is inside T-6h but before T-60m.
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

    assert first.active_window == "T-6h"
    assert held.status == "waiting"
    assert "retry is held" in held.message
    assert len(refresh.requests) == 2
    assert retried.status == "running"


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

    assert result.status == "waiting"
    assert result.event == 2
    assert result.next_window == "T-72h"
    assert not refresh.requests


def test_live_gameweek_scheduler_targets_the_next_decision_event(
    tmp_path: Path,
) -> None:
    # GW1 is live, but the actionable T-72h window belongs to the GW2 deadline.
    now = [datetime(2026, 8, 25, 18, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    scheduler = _scheduler(tmp_path, now=now, refresh=refresh)

    result = scheduler.tick()

    assert result.status == "running"
    assert result.event == 2
    assert result.active_window == "T-72h"
    assert refresh.requests[0]["mode"] == "weekly"
    assert refresh.requests[0]["event"] == 2


def test_material_official_change_triggers_once_and_is_covered_after_publish(
    tmp_path: Path,
) -> None:
    # Keep the test clock after the repository's current evidence generation.
    now = [datetime(2026, 8, 16, 20, tzinfo=UTC)]
    refresh = FakeRefreshCoordinator()
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    )
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
        workspace_loader=lambda: builder.build(now=now[0]),
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

    assert covered.status == "waiting"
    assert covered.material_change_detected is False
    assert len(refresh.requests) == 1


def test_material_change_does_not_duplicate_a_blocked_app_open_attempt(
    tmp_path: Path,
) -> None:
    # Keep the test clock after the repository's current evidence generation.
    now = [datetime(2026, 8, 16, 20, tzinfo=UTC)]
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
    builder = WorkspaceBuilder(
        active_decision_path=tmp_path / "missing-active.json",
        profile_path=tmp_path / "profile.json",
        deadline_status_path=None,
    )
    scheduler = DeadlineRefreshScheduler(
        workspace_loader=lambda: builder.build(now=now[0]),
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
