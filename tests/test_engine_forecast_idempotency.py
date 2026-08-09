from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_data.http import sha256_file
from fplagent_engine import component_models, models


def _write_manifest(
    path: Path,
    *,
    inputs: dict[str, str | None],
    forecast_path: Path,
    result: dict,
) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "inputs": inputs,
                "forecast_sha256": sha256_file(forecast_path),
                "result": result,
            }
        ),
        encoding="utf-8",
    )


def test_direct_forecast_reuses_exact_input_generation_without_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = tmp_path / "features.parquet"
    model = tmp_path / "model.joblib"
    calibration = tmp_path / "calibration.json"
    output = tmp_path / "forecast.parquet"
    manifest = tmp_path / "forecast-manifest.json"
    for path, payload in (
        (features, b"features"),
        (model, b"model"),
        (calibration, b"calibration"),
        (output, b"forecast"),
    ):
        path.write_bytes(payload)
    inputs = {
        "features_sha256": sha256_file(features),
        "model_sha256": sha256_file(model),
        "appearance_calibration_sha256": sha256_file(calibration),
    }
    _write_manifest(
        manifest,
        inputs=inputs,
        forecast_path=output,
        result={"forecast": str(output), "rows": 572},
    )
    monkeypatch.setattr(models, "CURRENT_FEATURES", features)
    monkeypatch.setattr(models, "MODEL_FILE", model)
    monkeypatch.setattr(models, "CALIBRATION_FILE", calibration)
    monkeypatch.setattr(models, "CURRENT_FORECAST", output)
    monkeypatch.setattr(models, "CURRENT_FORECAST_MANIFEST", manifest)
    monkeypatch.setattr(
        models,
        "require_cuda",
        lambda: (_ for _ in ()).throw(AssertionError("CUDA inference should not run")),
    )

    result = models.forecast()

    assert result["reused"] is True
    assert result["rows"] == 572
    assert output.read_bytes() == b"forecast"


def test_direct_forecast_refuses_reuse_after_output_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = tmp_path / "features.parquet"
    model = tmp_path / "model.joblib"
    output = tmp_path / "forecast.parquet"
    manifest = tmp_path / "forecast-manifest.json"
    features.write_bytes(b"features")
    model.write_bytes(b"model")
    output.write_bytes(b"forecast")
    inputs = {
        "features_sha256": sha256_file(features),
        "model_sha256": sha256_file(model),
        "appearance_calibration_sha256": None,
    }
    _write_manifest(
        manifest,
        inputs=inputs,
        forecast_path=output,
        result={"forecast": str(output)},
    )
    output.write_bytes(b"tampered")
    monkeypatch.setattr(models, "CURRENT_FEATURES", features)
    monkeypatch.setattr(models, "MODEL_FILE", model)
    monkeypatch.setattr(models, "CALIBRATION_FILE", tmp_path / "absent.json")
    monkeypatch.setattr(models, "CURRENT_FORECAST", output)
    monkeypatch.setattr(models, "CURRENT_FORECAST_MANIFEST", manifest)
    monkeypatch.setattr(
        models,
        "require_cuda",
        lambda: (_ for _ in ()).throw(RuntimeError("fresh inference required")),
    )

    with pytest.raises(RuntimeError, match="fresh inference required"):
        models.forecast()


def test_component_forecast_reuses_exact_input_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = tmp_path / "features.parquet"
    direct = tmp_path / "direct.parquet"
    model = tmp_path / "component.joblib"
    bps_priors = tmp_path / "bps.parquet"
    bps_metrics = tmp_path / "bps.json"
    output = tmp_path / "components.parquet"
    manifest = tmp_path / "components-manifest.json"
    for path, payload in (
        (features, b"features"),
        (direct, b"direct"),
        (model, b"component-model"),
        (bps_priors, b"bps-priors"),
        (bps_metrics, b"bps-metrics"),
        (output, b"components"),
    ):
        path.write_bytes(payload)
    inputs = {
        "features_sha256": sha256_file(features),
        "direct_forecast_sha256": sha256_file(direct),
        "component_model_sha256": sha256_file(model),
        "bps_priors_sha256": sha256_file(bps_priors),
        "bps_metrics_sha256": sha256_file(bps_metrics),
    }
    _write_manifest(
        manifest,
        inputs=inputs,
        forecast_path=output,
        result={"path": str(output), "rows": 572},
    )
    monkeypatch.setattr(component_models, "CURRENT_FEATURES", features)
    monkeypatch.setattr(component_models, "CURRENT_FORECAST", direct)
    monkeypatch.setattr(component_models, "MODEL_FILE", model)
    monkeypatch.setattr(component_models, "BPS_PRIORS", bps_priors)
    monkeypatch.setattr(component_models, "BPS_METRICS", bps_metrics)
    monkeypatch.setattr(component_models, "CURRENT_COMPONENT_FORECAST", output)
    monkeypatch.setattr(component_models, "CURRENT_COMPONENT_FORECAST_MANIFEST", manifest)
    monkeypatch.setattr(
        component_models.joblib,
        "load",
        lambda _: (_ for _ in ()).throw(AssertionError("model should not load")),
    )

    result = component_models.forecast_components()

    assert result["reused"] is True
    assert result["rows"] == 572
    assert output.read_bytes() == b"components"


def test_component_forecast_rejects_equal_length_grid_in_different_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = tmp_path / "features.parquet"
    direct = tmp_path / "direct.parquet"
    model = tmp_path / "component.joblib"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"event_number": 1, "element": 10},
                {"event_number": 1, "element": 20},
            ]
        ),
        features,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"event_number": 1, "element": 20},
                {"event_number": 1, "element": 10},
            ]
        ),
        direct,
    )
    model.write_bytes(b"component-model")
    monkeypatch.setattr(component_models, "CURRENT_FEATURES", features)
    monkeypatch.setattr(component_models, "CURRENT_FORECAST", direct)
    monkeypatch.setattr(component_models, "MODEL_FILE", model)
    monkeypatch.setattr(
        component_models, "CURRENT_COMPONENT_FORECAST", tmp_path / "components.parquet"
    )
    monkeypatch.setattr(
        component_models,
        "CURRENT_COMPONENT_FORECAST_MANIFEST",
        tmp_path / "components-manifest.json",
    )
    monkeypatch.setattr(component_models.joblib, "load", lambda _: {})

    with pytest.raises(ValueError, match="row order does not match"):
        component_models.forecast_components()
