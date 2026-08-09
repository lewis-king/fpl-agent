from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import (
    CURRENT_POINTER,
    CURRENT_STATUS,
    SNAPSHOT_ROOT,
    latest_official_status,
)
from fplagent_data.manager_snapshots import (
    MANAGER_SNAPSHOT_ROOT,
    manager_snapshot_status,
)
from fplagent_data.paths import MANIFESTS

from .decision_synthesis import DECISION_JSON
from .optimizer import CURRENT_FORECAST
from .paths import FORECASTS

CURRENT_COMPONENT_FORECAST = FORECASTS / "2026-27-preseason-components.parquet"
DEADLINE_STATUS_RECEIPT = MANIFESTS / "fpl-deadline-evidence-status.json"


class DeadlineEvidenceError(ValueError):
    pass


def _aware(value: str | datetime, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise DeadlineEvidenceError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _unique_strings(table: Any, column: str) -> list[str]:
    if column not in table.column_names:
        return []
    return sorted({str(value) for value in table[column].to_pylist() if value is not None})


def _forecast_status(
    path: Path,
    *,
    checked_at: datetime,
    official_observed_at: datetime,
    freshness_limit_seconds: int,
) -> dict[str, Any]:
    issues: list[str] = []
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "publishable": False,
            "issues": ["forecast artifact is missing"],
        }
    try:
        table = pq.read_table(path)
    except (OSError, pa.ArrowException) as exc:
        return {
            "path": str(path),
            "exists": True,
            "publishable": False,
            "issues": [f"forecast artifact is unreadable: {exc}"],
        }
    snapshot_values = _unique_strings(table, "snapshot_at")
    model_created_values = _unique_strings(table, "model_created_at")
    forecast_created_values = _unique_strings(table, "forecast_created_at")
    model_versions = _unique_strings(table, "model_version")
    events = sorted({int(value) for value in table["event_number"].to_pylist()})
    elements = {int(value) for value in table["element"].to_pylist()}
    if table.num_rows == 0:
        issues.append("forecast artifact is empty")
    if len(snapshot_values) != 1:
        issues.append("forecast artifact must contain one source snapshot_at")
    if len(model_created_values) != 1:
        issues.append("forecast artifact must contain one model_created_at")
    if len(model_versions) != 1:
        issues.append("forecast artifact must contain one model_version")
    if len(forecast_created_values) != 1:
        issues.append("forecast artifact must contain one forecast_created_at")
    if not events or events != list(range(min(events), max(events) + 1)):
        issues.append("forecast event horizon must be contiguous")
    if events and table.num_rows != len(events) * len(elements):
        issues.append("forecast artifact does not contain a complete player-event grid")

    observed = None
    age_seconds = None
    aligned = False
    fresh = False
    if len(snapshot_values) == 1:
        try:
            observed = _aware(snapshot_values[0], "forecast snapshot_at")
            if observed > checked_at + timedelta(minutes=5):
                issues.append("forecast source snapshot is in the future")
            age = max(timedelta(0), checked_at - observed)
            age_seconds = int(age.total_seconds())
            aligned = observed == official_observed_at
            fresh = age_seconds <= freshness_limit_seconds
            if not aligned:
                issues.append(
                    "forecast source snapshot does not match the current official snapshot"
                )
            if not fresh:
                issues.append("forecast source snapshot is stale")
        except (DeadlineEvidenceError, ValueError) as exc:
            issues.append(str(exc))
    if len(forecast_created_values) == 1:
        try:
            forecast_created = _aware(
                forecast_created_values[0], "forecast forecast_created_at"
            )
            if forecast_created > checked_at + timedelta(minutes=5):
                issues.append("forecast creation time is in the future")
        except (DeadlineEvidenceError, ValueError) as exc:
            issues.append(str(exc))
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "rows": table.num_rows,
        "players": len(elements),
        "events": events,
        "snapshot_at": observed.isoformat() if observed else None,
        "model_created_at": model_created_values[0] if len(model_created_values) == 1 else None,
        "forecast_created_at": (
            forecast_created_values[0] if len(forecast_created_values) == 1 else None
        ),
        "model_version": model_versions[0] if len(model_versions) == 1 else None,
        "age_seconds": age_seconds,
        "fresh": fresh,
        "aligned_to_official": aligned,
        "publishable": not issues,
        "issues": issues,
        "keys": {
            (int(event), int(element))
            for event, element in zip(
                table["event_number"].to_pylist(),
                table["element"].to_pylist(),
                strict=True,
            )
        },
    }


def _component_status(path: Path, direct: Mapping[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "publishable": False,
            "issues": ["component forecast artifact is missing"],
        }
    try:
        table = pq.read_table(path)
    except (OSError, pa.ArrowException) as exc:
        return {
            "path": str(path),
            "exists": True,
            "publishable": False,
            "issues": [f"component forecast artifact is unreadable: {exc}"],
        }
    keys = {
        (int(event), int(element))
        for event, element in zip(
            table["event_number"].to_pylist(),
            table["element"].to_pylist(),
            strict=True,
        )
    }
    issues = []
    direct_keys = direct.get("keys")
    if not isinstance(direct_keys, set) or keys != direct_keys:
        issues.append("component forecast keys do not match the direct forecast grid")
    snapshot_values = _unique_strings(table, "snapshot_at")
    direct_hash_values = _unique_strings(table, "direct_forecast_sha256")
    component_versions = _unique_strings(table, "component_model_version")
    component_created = _unique_strings(table, "component_model_created_at")
    component_forecast_created = _unique_strings(table, "component_forecast_created_at")
    if snapshot_values != [str(direct.get("snapshot_at"))]:
        issues.append("component forecast source snapshot does not match the direct forecast")
    if direct_hash_values != [str(direct.get("sha256"))]:
        issues.append("component forecast does not reference the current direct forecast hash")
    if (
        len(component_versions) != 1
        or len(component_created) != 1
        or len(component_forecast_created) != 1
    ):
        issues.append("component forecast must identify one component model generation")
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "rows": table.num_rows,
        "snapshot_at": snapshot_values[0] if len(snapshot_values) == 1 else None,
        "component_model_version": (
            component_versions[0] if len(component_versions) == 1 else None
        ),
        "component_model_created_at": (
            component_created[0] if len(component_created) == 1 else None
        ),
        "component_forecast_created_at": (
            component_forecast_created[0] if len(component_forecast_created) == 1 else None
        ),
        "direct_forecast_sha256": (direct_hash_values[0] if len(direct_hash_values) == 1 else None),
        "publishable": not issues,
        "issues": issues,
    }


def _hash_values(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        hashes = {
            str(nested)
            for key, nested in value.items()
            if str(key).endswith("sha256") and isinstance(nested, str)
        }
        for nested in value.values():
            hashes.update(_hash_values(nested))
        return hashes
    if isinstance(value, list):
        hashes: set[str] = set()
        for nested in value:
            hashes.update(_hash_values(nested))
        return hashes
    return set()


def _decision_status(
    path: Path,
    *,
    official_observed_at: datetime,
    direct: Mapping[str, Any],
    component: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "publishable": False,
            "issues": ["decision receipt is missing"],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = _aware(str(payload["created_at"]), "decision created_at")
    except (OSError, KeyError, json.JSONDecodeError, DeadlineEvidenceError, ValueError) as exc:
        return {
            "path": str(path),
            "exists": True,
            "publishable": False,
            "issues": [f"decision receipt is invalid: {exc}"],
        }
    if created_at < official_observed_at:
        issues.append("decision predates the current official snapshot")
    forecast_created = direct.get("forecast_created_at")
    if isinstance(forecast_created, str):
        try:
            if created_at < _aware(forecast_created, "forecast forecast_created_at"):
                issues.append("decision predates the current forecast output")
        except (DeadlineEvidenceError, ValueError) as exc:
            issues.append(str(exc))

    source_hashes: set[str] = set()
    raw_sources = payload.get("source_artifacts")
    if not isinstance(raw_sources, Mapping):
        issues.append("decision receipt has no source_artifacts mapping")
    else:
        for key, source_path_value in raw_sources.items():
            if key.endswith("_sha256"):
                continue
            expected = raw_sources.get(f"{key}_sha256")
            source_path = Path(str(source_path_value))
            if not source_path.is_file():
                issues.append(f"decision source artifact is missing: {key}")
                continue
            actual = sha256_file(source_path)
            if expected != actual:
                issues.append(f"decision source artifact checksum changed: {key}")
                continue
            source_hashes.add(actual)
            if source_path.suffix.casefold() == ".json":
                try:
                    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    issues.append(f"decision JSON source artifact is invalid: {key}")
                    continue
                source_hashes.update(_hash_values(source_payload))
    current_forecast_hashes = {
        str(value)
        for value in (direct.get("sha256"), component.get("sha256"))
        if isinstance(value, str)
    }
    if current_forecast_hashes and not (source_hashes & current_forecast_hashes):
        issues.append("decision sources do not reference either current forecast artifact")
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "created_at": created_at.isoformat(),
        "status": payload.get("decision_status"),
        "source_forecast_hash_match": bool(source_hashes & current_forecast_hashes),
        "publishable": not issues,
        "issues": issues,
    }


def audit_deadline_evidence(
    *,
    as_of: str | datetime | None = None,
    manager_entry_id: int | None = None,
    official_snapshot_root: Path = SNAPSHOT_ROOT,
    official_pointer_path: Path = CURRENT_POINTER,
    manager_snapshot_root: Path = MANAGER_SNAPSHOT_ROOT,
    manifest_root: Path = MANIFESTS,
    direct_forecast_path: Path = CURRENT_FORECAST,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
    decision_path: Path = DECISION_JSON,
    output_path: Path | None = DEADLINE_STATUS_RECEIPT,
) -> dict[str, Any]:
    checked = _aware(as_of or datetime.now(tz=UTC), "as_of")
    official = latest_official_status(
        as_of=checked,
        snapshot_root=official_snapshot_root,
        pointer_path=official_pointer_path,
        status_path=CURRENT_STATUS if output_path == DEADLINE_STATUS_RECEIPT else None,
    )
    official_observed = _aware(str(official["observed_at"]), "official observed_at")
    direct = _forecast_status(
        direct_forecast_path,
        checked_at=checked,
        official_observed_at=official_observed,
        freshness_limit_seconds=int(official["freshness_limit_seconds"]),
    )
    component = _component_status(component_forecast_path, direct)
    decision = _decision_status(
        decision_path,
        official_observed_at=official_observed,
        direct=direct,
        component=component,
    )
    manager = None
    if manager_entry_id is not None:
        manager = manager_snapshot_status(
            manager_entry_id,
            as_of=checked,
            next_deadline=official.get("next_deadline"),
            snapshot_root=manager_snapshot_root,
            manifest_root=manifest_root,
        )
    stages = [official, direct, component, decision]
    if manager is not None:
        stages.append(manager)
    publishable = all(bool(stage["publishable"]) for stage in stages)
    issues = [
        f"{name}: {issue}"
        for name, stage in (
            ("official", official),
            ("manager", manager),
            ("direct_forecast", direct),
            ("component_forecast", component),
            ("decision", decision),
        )
        if stage is not None
        for issue in stage["issues"]
    ]
    direct.pop("keys", None)
    result = {
        "receipt_version": 1,
        "checked_at": checked.isoformat(),
        "manager_required": manager_entry_id is not None,
        "official": official,
        "manager": manager,
        "direct_forecast": direct,
        "component_forecast": component,
        "decision": decision,
        "publishable": publishable,
        "issues": issues,
    }
    if output_path is not None:
        _atomic_json(output_path, result)
    return result
