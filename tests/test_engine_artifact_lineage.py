from __future__ import annotations

import json

import pytest

from fplagent_data.http import sha256_file
from fplagent_engine.artifact_lineage import (
    ArtifactLineageError,
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)


def test_current_forecast_lineage_accepts_exact_bytes(tmp_path) -> None:
    forecast = tmp_path / "forecast.parquet"
    forecast.write_bytes(b"current forecast bytes")
    payload = {"artifacts": {"forecast_sha256": sha256_file(forecast)}}

    assert require_current_forecast(
        payload,
        forecast,
        "audit",
        fields=("artifacts", "forecast_sha256"),
    ) == sha256_file(forecast)


def test_current_forecast_lineage_rejects_stale_generation(tmp_path) -> None:
    forecast = tmp_path / "forecast.parquet"
    forecast.write_bytes(b"new generation")

    with pytest.raises(ArtifactLineageError, match="active evidence run"):
        require_current_forecast(
            {"forecast_sha256": "old-generation"}, forecast, "candidates"
        )


def test_recorded_file_rejects_mutated_upstream_artifact(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("before", encoding="utf-8")
    payload = {"source_sha256": sha256_file(source)}
    source.write_text("after", encoding="utf-8")

    with pytest.raises(ArtifactLineageError, match="Rerun its upstream stage"):
        require_recorded_file(payload, ("source_sha256",), source, "source")


def test_load_json_artifact_rejects_non_object(tmp_path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ArtifactLineageError, match="JSON object"):
        load_json_artifact(path, "artifact")
