from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file


class ArtifactLineageError(RuntimeError):
    """Raised when a downstream artifact does not belong to the active evidence run."""


def load_json_artifact(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactLineageError(f"Invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactLineageError(f"Invalid {label}: expected a JSON object at {path}")
    return value


def nested_value(payload: Mapping[str, Any], fields: Sequence[str]) -> Any:
    value: Any = payload
    for field in fields:
        if not isinstance(value, Mapping) or field not in value:
            return None
        value = value[field]
    return value


def require_recorded_hash(
    payload: Mapping[str, Any],
    fields: Sequence[str],
    expected_sha256: str,
    label: str,
) -> None:
    recorded = nested_value(payload, fields)
    dotted = ".".join(fields)
    if recorded != expected_sha256:
        raise ArtifactLineageError(
            f"{label} does not belong to the active evidence run: {dotted} is "
            f"{recorded!r}, expected {expected_sha256}. Rerun its upstream stage."
        )


def require_current_forecast(
    payload: Mapping[str, Any],
    current_forecast_path: Path,
    label: str,
    *,
    fields: Sequence[str] = ("forecast_sha256",),
) -> str:
    current_sha256 = sha256_file(current_forecast_path)
    require_recorded_hash(payload, fields, current_sha256, label)
    return current_sha256


def require_recorded_file(
    payload: Mapping[str, Any],
    fields: Sequence[str],
    source_path: Path,
    label: str,
) -> str:
    actual_sha256 = sha256_file(source_path)
    require_recorded_hash(payload, fields, actual_sha256, label)
    return actual_sha256
