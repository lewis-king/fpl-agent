from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data import fpl_current
from fplagent_data.database import build_catalog
from fplagent_data.event_outcomes import sync_finalized_event_outcomes
from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import latest_official_status
from fplagent_data.participation_consensus import CONSENSUS as PARTICIPATION_CONSENSUS
from fplagent_data.participation_consensus import RECEIPT as PARTICIPATION_RECEIPT
from fplagent_data.participation_consensus import collect_participation_consensus
from fplagent_data.paths import MANIFESTS

from .audit import audit_features
from .component_models import CURRENT_COMPONENT_FORECAST, forecast_components
from .deadline_evidence import DEADLINE_STATUS_RECEIPT, audit_deadline_evidence
from .features import build as build_features
from .manager_state_store import current_actionable_event, derive_latest_manager_state
from .market_odds import build_current_market_goal_rates, disable_current_market_shadow
from .models import CURRENT_FORECAST, forecast
from .paths import DECISIONS
from .rules import SquadRules, load_rules
from .schedule_scenarios import CURRENT_SCHEDULE_RECEIPT, build_schedule_receipt
from .weekly_decision import run_weekly_decision

PIPELINE_VERSION = 2
CURRENT_WEEKLY_DECISION = DECISIONS / "2026-27-weekly-current.json"
WEEKLY_STAGING_ROOT = DECISIONS / "staging" / "weekly"
WEEKLY_DECISION_ARCHIVE_ROOT = DECISIONS / "weekly"
WEEKLY_PIPELINE_RECEIPT = MANIFESTS / "fpl-weekly-deadline-pipeline.json"


class DeadlinePipelineError(ValueError):
    """The weekly deadline pipeline cannot safely proceed or publish."""


def _aware(value: str | datetime | None) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value)
        if value
        else datetime.now(UTC)
    )
    if parsed.tzinfo is None:
        raise DeadlinePipelineError("pipeline as_of must include a timezone")
    return parsed.astimezone(UTC)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_publish(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise DeadlinePipelineError(f"staged decision is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.replace(destination)


def _restore_published(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(path.suffix + ".rollback.tmp")
    temporary.write_bytes(previous)
    temporary.replace(path)


def _archive_immutable(source: Path, destination: Path) -> None:
    payload = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise DeadlinePipelineError(f"immutable weekly decision collision: {destination}")
        return
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)


def refresh_current_generation(
    *,
    reuse_latest_official: bool,
    horizon: int,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    """Collect, validate and forecast one coherent official generation."""
    fpl_current.fetch(force=not reuse_latest_official)
    official = latest_official_status(as_of=as_of)
    if not official["publishable"]:
        raise DeadlinePipelineError(
            f"official snapshot cannot be used: {official.get('issues', [])}"
        )
    processed = fpl_current.preprocess()
    live_outcomes = sync_finalized_event_outcomes(observed_at=as_of)
    try:
        market_goal_rates = build_current_market_goal_rates(horizon=horizon)
    except (OSError, RuntimeError, ValueError, KeyError, pa.ArrowException) as error:
        market_goal_rates = disable_current_market_shadow(f"{type(error).__name__}: {error}")
    schedule_result = build_schedule_receipt()
    schedule = {
        "current_path": schedule_result["current_path"],
        "archive_path": schedule_result["archive_path"],
        "schedule_fingerprint": schedule_result["schedule_fingerprint"],
        "receipt_fingerprint": schedule_result["receipt_fingerprint"],
        "snapshot_at": schedule_result["snapshot_at"],
        "summary": schedule_result["summary"],
        "comparison": schedule_result["comparison"],
    }
    catalog = build_catalog()
    features = build_features(horizon)
    quality = audit_features(horizon)
    direct = forecast()
    component = forecast_components()
    return {
        "official": official,
        "processed": processed,
        "live_outcomes": live_outcomes,
        "market_goal_rates": market_goal_rates,
        "schedule": schedule,
        "catalog": catalog,
        "features": features,
        "quality": quality,
        "direct_forecast": direct,
        "component_forecast": component,
    }


def _forecast_events(path: Path, *, event: int, horizon: int) -> tuple[int, ...]:
    if not 1 <= horizon <= 8:
        raise DeadlinePipelineError("weekly decision horizon must be between 1 and 8")
    try:
        table = pq.read_table(path, columns=["event_number"])
    except (OSError, pa.ArrowException) as exc:
        raise DeadlinePipelineError(f"forecast event grid is unreadable: {path}") from exc
    available = sorted({int(value) for value in table["event_number"].to_pylist()})
    selected = tuple(value for value in available if value >= event)[:horizon]
    if not selected or selected[0] != event:
        raise DeadlinePipelineError(f"forecast does not cover decision event {event}")
    expected = tuple(range(event, event + len(selected)))
    if selected != expected:
        raise DeadlinePipelineError("weekly forecast horizon is not contiguous")
    return selected


def _fingerprint(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _generation_time(
    direct_forecast_path: Path,
    component_forecast_path: Path,
    *,
    minimum: datetime,
) -> datetime:
    latest = minimum
    for path, column in (
        (direct_forecast_path, "forecast_created_at"),
        (component_forecast_path, "component_forecast_created_at"),
    ):
        try:
            table = pq.read_table(path, columns=[column])
        except (OSError, pa.ArrowException, KeyError):
            continue
        values = {str(value) for value in table[column].to_pylist() if value not in (None, "")}
        if len(values) != 1:
            continue
        try:
            candidate = _aware(next(iter(values)))
        except (DeadlinePipelineError, ValueError):
            continue
        latest = max(latest, candidate)
    return latest


def _rules_hash(rules: SquadRules) -> str:
    return _fingerprint(asdict(rules))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def run_weekly_deadline_pipeline(
    *,
    manager_entry_id: int,
    horizon: int = 5,
    as_of: str | datetime | None = None,
    reuse_latest_official: bool = False,
    alternatives_per_transfer_count: int = 4,
    max_total_transfers: int = 5,
    max_paid_transfers: int = 2,
    residual_simulations: int = 10_000,
    component_simulations: int = 25_000,
    direct_forecast_path: Path = CURRENT_FORECAST,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
    schedule_receipt_path: Path = CURRENT_SCHEDULE_RECEIPT,
    published_decision_path: Path = CURRENT_WEEKLY_DECISION,
    staging_root: Path = WEEKLY_STAGING_ROOT,
    decision_archive_root: Path = WEEKLY_DECISION_ARCHIVE_ROOT,
    pipeline_receipt_path: Path = WEEKLY_PIPELINE_RECEIPT,
    deadline_status_path: Path = DEADLINE_STATUS_RECEIPT,
    participation_receipt_path: Path = PARTICIPATION_RECEIPT,
    participation_consensus_path: Path = PARTICIPATION_CONSENSUS,
    refresh_runner: Callable[..., Mapping[str, Any]] = refresh_current_generation,
    event_resolver: Callable[[], int] = current_actionable_event,
    state_deriver: Callable[..., Mapping[str, Any]] | None = None,
    decision_runner: Callable[..., Mapping[str, Any]] = run_weekly_decision,
    evidence_auditor: Callable[..., Mapping[str, Any]] = audit_deadline_evidence,
    participation_refresher: Callable[..., Mapping[str, Any]] = (collect_participation_consensus),
    rules_loader: Callable[[], SquadRules] = load_rules,
) -> dict[str, Any]:
    checked = _aware(as_of)
    checked_text = checked.isoformat()
    if manager_entry_id < 1:
        raise DeadlinePipelineError("manager_entry_id must be positive")
    refresh = dict(
        refresh_runner(
            reuse_latest_official=reuse_latest_official,
            horizon=horizon,
            as_of=checked_text,
        )
    )
    event = event_resolver()
    try:
        participation_refresh = dict(
            participation_refresher(
                event=event,
                observed_at=checked_text,
                forecast_path=direct_forecast_path,
                receipt_path=participation_receipt_path,
                consensus_path=participation_consensus_path,
            )
        )
    except (OSError, ValueError) as exc:
        participation_refresh = {
            "status": "unavailable",
            "production_weight": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    rules = rules_loader()
    derive = state_deriver or (
        lambda entry_id, decision_event: derive_latest_manager_state(
            entry_id,
            decision_event,
            forecast_path=direct_forecast_path,
            rules=rules,
        )
    )
    derived = dict(derive(manager_entry_id, event))
    if derived.get("status") != "ready":
        receipt = {
            "pipeline_version": PIPELINE_VERSION,
            "status": str(derived.get("status") or "blocked"),
            "checked_at": checked_text,
            "manager_entry_id": manager_entry_id,
            "event": event,
            "manager_state": derived,
            "participation_evidence": participation_refresh,
            "published": False,
            "message": str(derived.get("message") or "Exact manager state is unavailable."),
        }
        _atomic_json(pipeline_receipt_path, receipt)
        return receipt

    contract_path = Path(str(derived["contract_path"]))
    events = _forecast_events(direct_forecast_path, event=event, horizon=horizon)
    decision_created_at = _generation_time(
        direct_forecast_path,
        component_forecast_path,
        minimum=checked,
    ).isoformat()
    input_identity = {
        "pipeline_version": PIPELINE_VERSION,
        "checked_at": checked_text,
        "manager_entry_id": manager_entry_id,
        "event": event,
        "events": events,
        "manager_state_contract_sha256": sha256_file(contract_path),
        "direct_forecast_sha256": sha256_file(direct_forecast_path),
        "component_forecast_sha256": sha256_file(component_forecast_path),
        "schedule_receipt_sha256": sha256_file(schedule_receipt_path),
        "market_goal_rate_status": (refresh.get("market_goal_rates") or {}).get("status"),
        "market_goal_rate_raw_sha256": (refresh.get("market_goal_rates") or {}).get("raw_sha256"),
        "market_goal_rate_rates_sha256": (refresh.get("market_goal_rates") or {}).get(
            "rates_sha256"
        ),
        "market_goal_rate_ready_events": (refresh.get("market_goal_rates") or {}).get(
            "ready_events", []
        ),
        "runtime_rules_sha256": _rules_hash(rules),
        "alternatives_per_transfer_count": alternatives_per_transfer_count,
        "max_total_transfers": max_total_transfers,
        "max_paid_transfers": max_paid_transfers,
        "residual_simulations": residual_simulations,
        "component_simulations": component_simulations,
        "decision_created_at": decision_created_at,
    }
    input_fingerprint = _fingerprint(input_identity)
    previous = _read_json(pipeline_receipt_path)
    if (
        previous
        and previous.get("status") == "published"
        and previous.get("input_fingerprint") == input_fingerprint
        and published_decision_path.is_file()
        and previous.get("published_decision_sha256") == sha256_file(published_decision_path)
    ):
        current_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=manager_entry_id,
                direct_forecast_path=direct_forecast_path,
                component_forecast_path=component_forecast_path,
                decision_path=published_decision_path,
                output_path=None,
            )
        )
        if current_gate.get("publishable"):
            return {**previous, "reused": True}

    staged_path = staging_root / f"event-{event}-{input_fingerprint[:16]}.json"
    decision_runner(
        rules,
        event=event,
        events=events,
        forecast_path=direct_forecast_path,
        manager_snapshot_path=contract_path,
        output_path=staged_path,
        alternatives_per_transfer_count=alternatives_per_transfer_count,
        max_total_transfers=max_total_transfers,
        max_paid_transfers=max_paid_transfers,
        residual_simulations=residual_simulations,
        component_simulations=component_simulations,
        component_forecast_path=component_forecast_path,
        schedule_receipt_path=schedule_receipt_path,
        created_at=decision_created_at,
    )
    staged_gate = dict(
        evidence_auditor(
            as_of=checked_text,
            manager_entry_id=manager_entry_id,
            direct_forecast_path=direct_forecast_path,
            component_forecast_path=component_forecast_path,
            decision_path=staged_path,
            output_path=None,
        )
    )
    if not staged_gate.get("publishable"):
        receipt = {
            "pipeline_version": PIPELINE_VERSION,
            "status": "blocked",
            "checked_at": checked_text,
            "manager_entry_id": manager_entry_id,
            "event": event,
            "events": list(events),
            "input_fingerprint": input_fingerprint,
            "staged_decision": str(staged_path),
            "staged_decision_sha256": sha256_file(staged_path),
            "evidence": staged_gate,
            "published": False,
            "message": "The candidate decision failed the deadline evidence gate.",
        }
        _atomic_json(pipeline_receipt_path, receipt)
        return receipt

    previous_published = (
        published_decision_path.read_bytes() if published_decision_path.is_file() else None
    )
    previous_deadline_status = (
        deadline_status_path.read_bytes() if deadline_status_path.is_file() else None
    )
    _atomic_publish(staged_path, published_decision_path)
    archived_path = decision_archive_root / f"event-{event}" / f"{input_fingerprint}.json"
    try:
        final_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=manager_entry_id,
                direct_forecast_path=direct_forecast_path,
                component_forecast_path=component_forecast_path,
                decision_path=published_decision_path,
                output_path=deadline_status_path,
            )
        )
        if not final_gate.get("publishable") or not deadline_status_path.is_file():
            raise DeadlinePipelineError("published bytes failed the final evidence recheck")
        _archive_immutable(published_decision_path, archived_path)
    except Exception:
        _restore_published(published_decision_path, previous_published)
        _restore_published(deadline_status_path, previous_deadline_status)
        raise
    receipt = {
        "pipeline_version": PIPELINE_VERSION,
        "status": "published",
        "checked_at": checked_text,
        "manager_entry_id": manager_entry_id,
        "event": event,
        "events": list(events),
        "input_fingerprint": input_fingerprint,
        "input_identity": input_identity,
        "refresh": refresh,
        "participation_evidence": participation_refresh,
        "manager_state": derived,
        "staged_decision": str(staged_path),
        "published_decision": str(published_decision_path),
        "published_decision_sha256": sha256_file(published_decision_path),
        "archived_decision": str(archived_path),
        "archived_decision_sha256": sha256_file(archived_path),
        "deadline_evidence": str(deadline_status_path),
        "deadline_evidence_sha256": sha256_file(deadline_status_path),
        "published": True,
        "reused": False,
        "message": "The weekly decision passed every evidence gate and is now active.",
    }
    _atomic_json(pipeline_receipt_path, receipt)
    return receipt
