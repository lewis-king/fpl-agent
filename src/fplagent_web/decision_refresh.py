from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fplagent_data.http import sha256_file
from fplagent_engine.deadline_pipeline import (
    WEEKLY_PIPELINE_RECEIPT,
    run_weekly_deadline_pipeline,
)
from fplagent_engine.preseason_pipeline import (
    GW1_PIPELINE_RECEIPT,
    run_gw1_deadline_pipeline,
)
from fplagent_llm.paths import ROOT

from .models import WorkspaceRefreshView

DEFAULT_REFRESH_STATE = ROOT / "data" / "web" / "state" / "workspace-refresh.json"
RefreshMode = Literal["gw1", "weekly"]
RefreshReason = Literal["app_open", "manual", "scheduled", "material_change"]
PipelineRunner = Callable[..., Mapping[str, Any]]
STAGE_LABELS = {
    "initial_squad": "solving the legal initial squad",
    "residual_tournament": "testing the residual squad field",
    "component_selection": "selecting the component policy",
    "component_candidates": "generating component-native challengers",
    "component_holdout": "running the component holdout",
    "robust_search": "searching globally robust squads",
    "horizon_audit": "auditing the eight-week horizon",
    "synthesis": "synthesising the decision families",
    "preseason_role_scenario": "stress-testing preseason roles",
    "preseason_role_threshold": "measuring role-risk thresholds",
    "availability_watch": "checking final availability evidence",
}


class WorkspaceRefreshCoordinator:
    """Run one deadline pipeline at a time without blocking the web read model.

    The engine owns fetching, content fingerprints, staged artifacts, evidence gates and atomic
    publication. This class only supplies single-flight execution and a small persisted status
    contract for the browser. The worker is daemonised so a local server shutdown never waits for
    a long tournament; engine staging and atomic publication keep the previous receipt safe.
    """

    def __init__(
        self,
        *,
        state_path: Path = DEFAULT_REFRESH_STATE,
        gw1_runner: PipelineRunner = run_gw1_deadline_pipeline,
        weekly_runner: PipelineRunner = run_weekly_deadline_pipeline,
        gw1_receipt_path: Path = GW1_PIPELINE_RECEIPT,
        weekly_receipt_path: Path = WEEKLY_PIPELINE_RECEIPT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.state_path = state_path
        self.gw1_runner = gw1_runner
        self.weekly_runner = weekly_runner
        self.gw1_receipt_path = gw1_receipt_path
        self.weekly_receipt_path = weekly_receipt_path
        self.clock = clock or (lambda: datetime.now(tz=UTC))
        self._lock = threading.RLock()
        self._active_run_id: str | None = None
        self._worker: threading.Thread | None = None

    def request(
        self,
        *,
        mode: RefreshMode,
        reason: RefreshReason,
        manager_entry_id: int | None,
        event: int,
    ) -> WorkspaceRefreshView:
        with self._lock:
            if self._active_run_id is not None:
                return self._read_state()

            requested_at = self._now().isoformat()
            run_seed = f"{mode}:{reason}:{manager_entry_id}:{event}:{requested_at}"
            run_id = "refresh-v1-" + hashlib.sha256(run_seed.encode()).hexdigest()[:16]
            if mode == "weekly" and manager_entry_id is None:
                state = WorkspaceRefreshView(
                    run_id=run_id,
                    status="blocked",
                    mode=mode,
                    reason=reason,
                    requested_at=requested_at,
                    started_at=requested_at,
                    completed_at=requested_at,
                    event=event,
                    message=(
                        "A weekly decision run needs an FPL entry ID and authenticated manager "
                        "state. The last valid workspace remains active."
                    ),
                )
                self._write_state(state)
                return state

            state = WorkspaceRefreshView(
                run_id=run_id,
                status="running",
                mode=mode,
                reason=reason,
                requested_at=requested_at,
                started_at=requested_at,
                manager_entry_id=manager_entry_id,
                event=event,
                message=(
                    "Checking official FPL changes and validating lineup evidence before "
                    "simulation."
                ),
            )
            self._active_run_id = run_id
            self._write_state(state)
            worker = threading.Thread(
                target=self._execute,
                args=(state,),
                daemon=True,
                name=f"fplagent-{run_id}",
            )
            self._worker = worker
            try:
                worker.start()
            except RuntimeError as exc:
                self._active_run_id = None
                failed = state.model_copy(
                    update={
                        "status": "failed",
                        "completed_at": self._now().isoformat(),
                        "message": f"The decision refresh worker could not start: {exc}",
                    }
                )
                self._write_state(failed)
                return failed
            return state

    def status(self) -> WorkspaceRefreshView:
        with self._lock:
            state = self._read_state()
            if state.status == "running" and self._active_run_id is None:
                interrupted = state.model_copy(
                    update={
                        "status": "failed",
                        "completed_at": self._now().isoformat(),
                        "message": (
                            "The previous local process ended before its decision refresh "
                            "completed. The last valid workspace remains active."
                        ),
                    }
                )
                self._write_state(interrupted)
                return interrupted
            if state.status == "running" and self._active_run_id == state.run_id:
                return self._with_pipeline_progress(state)
            return state

    def _execute(self, state: WorkspaceRefreshView) -> None:
        try:
            common = {
                "as_of": state.requested_at,
                # Every app-open request checks the source again. Downstream stages remain
                # content-addressed and are reused when the fetched bytes are unchanged.
                "reuse_latest_official": False,
            }
            if state.mode == "gw1":
                result = dict(self.gw1_runner(**common))
            else:
                result = dict(
                    self.weekly_runner(
                        manager_entry_id=int(state.manager_entry_id or 0),
                        **common,
                    )
                )
            raw_status = str(result.get("status") or "failed")
            reused = bool(result.get("reused"))
            if raw_status == "published":
                final_status = "reused" if reused else "published"
            elif raw_status in {"not_ready", "blocked"}:
                final_status = raw_status
            else:
                final_status = "failed"
            stages = [
                str(stage["name"])
                for stage in result.get("stages", [])
                if isinstance(stage, Mapping) and stage.get("name")
            ]
            receipt_path = (
                self.gw1_receipt_path if state.mode == "gw1" else self.weekly_receipt_path
            )
            receipt_sha256 = sha256_file(receipt_path) if receipt_path.is_file() else None
            completed = state.model_copy(
                update={
                    "status": final_status,
                    "completed_at": self._now().isoformat(),
                    "published": bool(result.get("published")),
                    "reused": reused,
                    "input_fingerprint": (
                        str(result["input_fingerprint"])
                        if result.get("input_fingerprint")
                        else None
                    ),
                    "receipt_path": str(receipt_path) if receipt_sha256 else None,
                    "receipt_sha256": receipt_sha256,
                    "completed_stages": stages,
                    "completed_stage_count": len(stages),
                    "total_stages": len(stages) or None,
                    "progress_percent": 100 if raw_status == "published" else None,
                    "failure_code": (
                        str(result["failure_code"]) if result.get("failure_code") else None
                    ),
                    "message": str(
                        result.get("message")
                        or "The decision refresh ended without a publication message."
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - pipeline failure must preserve the active receipt
            retryable = bool(getattr(exc, "retryable", True))
            failure_code = str(getattr(exc, "code", type(exc).__name__.lower()))
            completed = state.model_copy(
                update={
                    "status": "failed" if retryable else "blocked",
                    "completed_at": self._now().isoformat(),
                    "failure_code": failure_code,
                    "message": (
                        (
                            "The refresh hit a temporary failure; the last valid workspace was "
                            "retained and an automatic retry remains allowed: "
                        )
                        if retryable
                        else (
                            "The refresh was blocked before publication; the last valid "
                            "workspace was retained and automatic retries are paused: "
                        )
                    )
                    + str(exc),
                }
            )
        with self._lock:
            if self._active_run_id == state.run_id:
                self._write_state(completed)
                self._active_run_id = None
                self._worker = None

    def _with_pipeline_progress(self, state: WorkspaceRefreshView) -> WorkspaceRefreshView:
        receipt_path = self.gw1_receipt_path if state.mode == "gw1" else self.weekly_receipt_path
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return state
        if receipt.get("status") != "running" or receipt.get("checked_at") != state.requested_at:
            return state
        completed_stages = [
            str(stage["name"])
            for stage in receipt.get("stages", [])
            if isinstance(stage, Mapping) and stage.get("name")
        ]
        current_stage = str(receipt["current_stage"]) if receipt.get("current_stage") else None
        total = int(receipt.get("total_stages") or 0) or None
        completed_count = len(completed_stages)
        percent = min(99, round(100 * completed_count / total)) if total else None
        if current_stage and total:
            message = (
                f"Stage {completed_count + 1} of {total}: "
                f"{STAGE_LABELS.get(current_stage, current_stage.replace('_', ' '))}."
            )
        elif completed_count:
            message = f"Completed {completed_count} validated pipeline stages."
        else:
            message = state.message
        return state.model_copy(
            update={
                "completed_stages": completed_stages,
                "current_stage": current_stage,
                "completed_stage_count": completed_count,
                "total_stages": total,
                "progress_percent": percent,
                "message": message,
            }
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("workspace refresh clock must include a timezone")
        return value.astimezone(UTC)

    def _read_state(self) -> WorkspaceRefreshView:
        if not self.state_path.is_file():
            return WorkspaceRefreshView(status="idle", message="No decision refresh has run yet.")
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return WorkspaceRefreshView.model_validate(value)
        except (OSError, json.JSONDecodeError, ValueError):
            return WorkspaceRefreshView(
                status="failed",
                message=(
                    "The previous refresh status is unreadable. The last validated decision "
                    "artifacts have not been replaced."
                ),
            )

    def _write_state(self, state: WorkspaceRefreshView) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)
