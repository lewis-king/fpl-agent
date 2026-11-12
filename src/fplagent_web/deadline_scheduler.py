from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fplagent_llm.paths import ROOT

from .decision_refresh import WorkspaceRefreshCoordinator, decision_refresh_interval
from .models import DeadlineScheduleView, ManagerProfileView, WorkspaceView
from .official_change_probe import OfficialChangeProbeResult

DEFAULT_SCHEDULE_STATE = ROOT / "data" / "web" / "state" / "deadline-refresh-schedule.json"
def material_probe_interval(time_to_deadline: timedelta) -> timedelta:
    """Use a respectful public-API cadence that tightens as information value rises."""
    if time_to_deadline <= timedelta(minutes=10):
        return timedelta(seconds=30)
    if time_to_deadline <= timedelta(hours=1):
        return timedelta(minutes=1)
    if time_to_deadline <= timedelta(hours=6):
        return timedelta(minutes=5)
    if time_to_deadline <= timedelta(hours=24):
        return timedelta(minutes=10)
    if time_to_deadline <= timedelta(hours=72):
        return timedelta(minutes=30)
    return timedelta(hours=6)


class DeadlineRefreshScheduler:
    """Keep the decision validated on a cadence that tightens near deadline."""

    def __init__(
        self,
        *,
        workspace_loader: Callable[[], WorkspaceView],
        profile_loader: Callable[[], ManagerProfileView],
        refresh_coordinator: WorkspaceRefreshCoordinator,
        material_probe: Callable[[], OfficialChangeProbeResult] | None = None,
        state_path: Path = DEFAULT_SCHEDULE_STATE,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 30.0,
        retry_seconds: float = 900.0,
    ) -> None:
        self.workspace_loader = workspace_loader
        self.profile_loader = profile_loader
        self.refresh_coordinator = refresh_coordinator
        self.material_probe = material_probe
        self.state_path = state_path
        self.clock = clock or (lambda: datetime.now(tz=UTC))
        self.poll_seconds = poll_seconds
        self.retry_seconds = retry_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="fplagent-deadline-scheduler",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=0.25)
        self._thread = None

    def status(self) -> DeadlineScheduleView:
        with self._lock:
            return self._read_state() or self.tick()

    def tick(self) -> DeadlineScheduleView:
        with self._lock:
            try:
                return self._tick()
            except Exception as exc:  # noqa: BLE001 - scheduler must never stop the API
                now = self._now().isoformat()
                result = DeadlineScheduleView(
                    status="error",
                    checked_at=now,
                    message=f"The deadline scheduler could not evaluate its next run: {exc}",
                )
                self._write_state(result)
                return result

    def _tick(self) -> DeadlineScheduleView:
        now = self._now()
        workspace = self.workspace_loader()
        scheduled_event = workspace.phase.decision_event or workspace.phase.event
        deadline = datetime.fromisoformat(
            workspace.phase.decision_deadline or workspace.phase.deadline
        )
        if deadline.tzinfo is None:
            raise ValueError("workspace deadline must include a timezone")
        deadline = deadline.astimezone(UTC)
        prior = self._read_state()
        same_event_prior = prior if prior and prior.event == scheduled_event else None
        cadence = decision_refresh_interval(now=now, deadline_at=deadline)
        cadence_minutes = int(cadence.total_seconds() // 60)
        cadence_label = (
            f"{cadence_minutes // 60}-hour cadence"
            if cadence_minutes % 60 == 0
            else f"{cadence_minutes}-minute cadence"
        )
        common = {
            "checked_at": now.isoformat(),
            "event": scheduled_event,
            "deadline": deadline.isoformat(),
            "next_window": cadence_label,
            "next_window_at": None,
            "cadence_minutes": cadence_minutes,
            "cadence_label": cadence_label,
            "last_validated_at": (
                same_event_prior.last_validated_at if same_event_prior else None
            ),
            "last_attempt_window": (
                same_event_prior.last_attempt_window if same_event_prior else None
            ),
            "last_attempt_at": same_event_prior.last_attempt_at if same_event_prior else None,
            "material_checked_at": (
                same_event_prior.material_checked_at if same_event_prior else None
            ),
            "material_local_fingerprint": (
                same_event_prior.material_local_fingerprint if same_event_prior else None
            ),
            "material_remote_fingerprint": (
                same_event_prior.material_remote_fingerprint if same_event_prior else None
            ),
            "material_change_detected": (
                same_event_prior.material_change_detected if same_event_prior else False
            ),
        }
        if now >= deadline:
            result = DeadlineScheduleView(
                status="deadline_passed",
                **common,
                message="The current deadline has passed; no preseason refresh window is due.",
            )
            self._write_state(result)
            return result

        # A missing private snapshot is not a transient market/solver failure.
        # Wait for a genuinely newer sync; immediately resume when it arrives,
        # even if the login dialog closed before its frontend callback completed.
        refresh = self.refresh_coordinator.status()
        if refresh.status == "not_ready" and refresh.event == scheduled_event:
            profile = self.profile_loader()
            synced = (
                datetime.fromisoformat(profile.last_synced_at).astimezone(UTC)
                if profile.last_synced_at else None
            )
            attempted = (
                datetime.fromisoformat(refresh.started_at).astimezone(UTC)
                if refresh.started_at else None
            )
            if (
                synced is not None and attempted is not None and attempted < synced <= now
                and profile.fpl_entry_id == refresh.manager_entry_id
            ):
                started = self.refresh_coordinator.request(
                    mode="gw1" if scheduled_event == 1 else "weekly",
                    reason="scheduled", manager_entry_id=profile.fpl_entry_id,
                    event=scheduled_event, deadline_at=deadline,
                )
                result = DeadlineScheduleView(
                    status="running" if started.status == "running" else "waiting",
                    **{**common, "last_attempt_at": now.isoformat(),
                       "last_attempt_window": "manager_sync", "refresh_run_id": started.run_id},
                    message="New FPL squad sync received; resuming the decision refresh.",
                )
            else:
                result = DeadlineScheduleView(
                    status="waiting", **common, refresh_run_id=refresh.run_id,
                    message=f"Waiting for a new FPL squad sync; no refresh is running. {refresh.message}",
                )
            self._write_state(result)
            return result

        if self.material_probe is not None:
            last_checked = (
                datetime.fromisoformat(same_event_prior.material_checked_at).astimezone(UTC)
                if same_event_prior and same_event_prior.material_checked_at
                else None
            )
            probe_due = last_checked is None or now - last_checked >= material_probe_interval(
                deadline - now
            )
            # The material probe refreshes the active bookmaker generation. Never
            # mutate that generation while a decision is being built from it: the
            # final checksum gate would correctly reject the otherwise coherent
            # decision. The single-flight refresh will itself collect current
            # market evidence, so deferring this lightweight probe loses nothing.
            refresh_before_probe = self.refresh_coordinator.status()
            if probe_due and refresh_before_probe.status != "running":
                try:
                    probe = self.material_probe()
                    probe_checked = datetime.fromisoformat(probe.checked_at)
                    if probe_checked.tzinfo is None:
                        raise ValueError("material probe checked_at must include a timezone")
                    common.update(
                        material_checked_at=probe_checked.astimezone(UTC).isoformat(),
                        material_local_fingerprint=probe.local_fingerprint,
                        material_remote_fingerprint=probe.remote_fingerprint,
                        material_change_detected=probe.changed,
                    )
                except Exception as exc:  # noqa: BLE001 - retry at the declared cadence
                    common["material_checked_at"] = now.isoformat()
                    result = DeadlineScheduleView(
                        status="error",
                        **common,
                        message=f"The official FPL change probe failed safely: {exc}",
                    )
                    self._write_state(result)
                    return result

        if common["material_change_detected"]:
            refresh = self.refresh_coordinator.status()
            material_checked = datetime.fromisoformat(
                str(common["material_checked_at"])
            ).astimezone(UTC)
            material_key = (
                "material-change:" + str(common["material_remote_fingerprint"] or "unknown")[:12]
            )
            active = {
                **common,
                "active_window": "material-change",
                "active_window_at": material_checked.isoformat(),
                "refresh_run_id": refresh.run_id,
            }
            covered = (
                refresh.status in {"published", "reused"}
                and refresh.completed_at is not None
                and datetime.fromisoformat(refresh.completed_at).astimezone(UTC) >= material_checked
            )
            if covered:
                common["material_change_detected"] = False
            elif refresh.status == "running":
                result = DeadlineScheduleView(
                    status="running",
                    **active,
                    message=(
                        "A material official-data change is waiting for refresh "
                        f"{refresh.run_id} to finish."
                    ),
                )
                self._write_state(result)
                return result
            elif (
                refresh.status == "blocked"
                and (
                    refresh.failure_code == "refresh_process_interrupted"
                    or (
                        refresh.completed_at is not None
                        and datetime.fromisoformat(refresh.completed_at).astimezone(UTC)
                        >= material_checked
                    )
                )
            ):
                result = DeadlineScheduleView(
                    status="waiting",
                    **active,
                    message=(
                        "Automatic retries are paused for this unchanged official-data "
                        f"generation: {refresh.message}"
                    ),
                )
                self._write_state(result)
                return result
            elif self._retry_held(same_event_prior, material_key, now):
                retry_at = datetime.fromisoformat(str(prior.last_attempt_at)).astimezone(
                    UTC
                ) + timedelta(seconds=self.retry_seconds)
                result = DeadlineScheduleView(
                    status="waiting",
                    **{**active, "next_window_at": retry_at.isoformat()},
                    message=(f"The material-change retry is held until {retry_at.isoformat()}."),
                )
                self._write_state(result)
                return result
            else:
                profile = self.profile_loader()
                mode = "gw1" if scheduled_event == 1 else "weekly"
                started = self.refresh_coordinator.request(
                    mode=mode,
                    reason="material_change",
                    manager_entry_id=profile.fpl_entry_id,
                    event=scheduled_event,
                    deadline_at=deadline,
                )
                result = DeadlineScheduleView(
                    status="running" if started.status == "running" else "waiting",
                    **{
                        **active,
                        "last_attempt_window": material_key,
                        "last_attempt_at": now.isoformat(),
                        "refresh_run_id": started.run_id,
                    },
                    message=(
                        "Started a decision refresh after a material official-data change."
                        if started.status == "running"
                        else started.message
                    ),
                )
                self._write_state(result)
                return result

        refresh = self.refresh_coordinator.status()
        refresh_completed = (
            refresh.status in {"published", "reused"}
            and refresh.completed_at is not None
            and refresh.event == scheduled_event
        )
        if refresh_completed:
            completed_at = datetime.fromisoformat(str(refresh.completed_at)).astimezone(UTC)
            prior_validated = (
                datetime.fromisoformat(same_event_prior.last_validated_at).astimezone(UTC)
                if same_event_prior and same_event_prior.last_validated_at
                else None
            )
            validated_at = max(
                value for value in (completed_at, prior_validated) if value is not None
            )
        elif same_event_prior and same_event_prior.last_validated_at:
            validated_at = datetime.fromisoformat(
                same_event_prior.last_validated_at
            ).astimezone(UTC)
        else:
            validated_at = None
        due_at = validated_at + cadence if validated_at is not None else now
        due_at = min(due_at, deadline)
        common["last_validated_at"] = validated_at.isoformat() if validated_at else None
        common["next_window_at"] = due_at.isoformat()
        cadence_key = f"cadence:{scheduled_event}:{cadence_minutes}"
        active = {
            **common,
            "active_window": cadence_label,
            "active_window_at": due_at.isoformat(),
            "refresh_run_id": refresh.run_id,
        }
        if refresh.status == "running":
            result = DeadlineScheduleView(
                status="running",
                **active,
                message=f"The {cadence_label} refresh {refresh.run_id} is running.",
            )
            self._write_state(result)
            return result
        if validated_at is not None and now < due_at:
            result = DeadlineScheduleView(
                status="covered",
                **active,
                message=(
                    f"The decision is covered by validated refresh {refresh.run_id}; the next "
                    f"automatic check is {due_at.isoformat()}."
                ),
            )
            self._write_state(result)
            return result

        if (
            refresh.status == "blocked"
            and (
                refresh.failure_code == "refresh_process_interrupted"
                or (
                    refresh.completed_at is not None
                    and (
                        validated_at is None
                        or datetime.fromisoformat(refresh.completed_at).astimezone(UTC)
                        >= validated_at
                    )
                )
            )
        ):
            result = DeadlineScheduleView(
                status="waiting",
                **active,
                message=(
                    f"{cadence_label} automatic retries are paused until the evidence changes or a "
                    f"manual refresh is requested: {refresh.message}"
                ),
            )
            self._write_state(result)
            return result

        if self._retry_held(same_event_prior, cadence_key, now):
            retry_at = datetime.fromisoformat(same_event_prior.last_attempt_at).astimezone(UTC) + timedelta(
                seconds=self.retry_seconds
            )
            result = DeadlineScheduleView(
                status="waiting",
                **{**active, "next_window_at": retry_at.isoformat()},
                message=f"The {cadence_label} retry is held until {retry_at.isoformat()}.",
            )
            self._write_state(result)
            return result

        profile = self.profile_loader()
        mode = "gw1" if scheduled_event == 1 else "weekly"
        started = self.refresh_coordinator.request(
            mode=mode,
            reason="scheduled",
            manager_entry_id=profile.fpl_entry_id,
            event=scheduled_event,
            deadline_at=deadline,
        )
        result = DeadlineScheduleView(
            status="running" if started.status == "running" else "waiting",
            **{
                **active,
                "last_attempt_window": cadence_key,
                "last_attempt_at": now.isoformat(),
                "refresh_run_id": started.run_id,
            },
            message=(
                f"Started the {cadence_label} decision refresh."
                if started.status == "running"
                else started.message
            ),
        )
        self._write_state(result)
        return result

    def _retry_held(
        self,
        prior: DeadlineScheduleView | None,
        key: str,
        now: datetime,
    ) -> bool:
        return bool(
            prior
            and prior.last_attempt_window == key
            and prior.last_attempt_at is not None
            and (
                now - datetime.fromisoformat(prior.last_attempt_at).astimezone(UTC)
            ).total_seconds()
            < self.retry_seconds
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.poll_seconds)

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("deadline scheduler clock must include a timezone")
        return value.astimezone(UTC)

    def _read_state(self) -> DeadlineScheduleView | None:
        if not self.state_path.is_file():
            return None
        try:
            return DeadlineScheduleView.model_validate_json(
                self.state_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _write_state(self, state: DeadlineScheduleView) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)
