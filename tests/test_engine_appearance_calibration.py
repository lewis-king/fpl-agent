from __future__ import annotations

import json

import numpy as np
import pytest

from fplagent_engine import appearance_calibration


def test_play_calibration_preserves_playing_class_shares(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "calibration.json"
    artifact.write_text(
        json.dumps(
            {
                "promoted_positions": ["GK"],
                "calibrators": {"GK": {"coefficient": 1.0, "intercept": 0.5}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(appearance_calibration, "CALIBRATION_FILE", artifact)
    appearance_calibration.load_appearance_calibration.cache_clear()
    probabilities = np.asarray([[[0.2, 0.1, 0.3, 0.4]]], dtype=float)

    adjusted, applied = appearance_calibration.calibrate_minute_probabilities(
        probabilities, "GK"
    )

    assert applied
    assert adjusted[..., 1:].sum() > probabilities[..., 1:].sum()
    np.testing.assert_allclose(
        adjusted[0, 0, 1:] / adjusted[0, 0, 1:].sum(),
        probabilities[0, 0, 1:] / probabilities[0, 0, 1:].sum(),
    )
    np.testing.assert_allclose(adjusted.sum(axis=-1), 1.0)
    appearance_calibration.load_appearance_calibration.cache_clear()


def test_two_stage_calibration_adjusts_conditional_minute_classes(
    tmp_path, monkeypatch
) -> None:
    artifact = tmp_path / "calibration.json"
    artifact.write_text(
        json.dumps(
            {
                "promoted_positions": ["MID"],
                "calibrators": {
                    "MID": {
                        "method": "two_stage_temperature",
                        "play": {"coefficient": 1.0, "intercept": 0.0},
                        "conditional_temperature": 0.5,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(appearance_calibration, "CALIBRATION_FILE", artifact)
    appearance_calibration.load_appearance_calibration.cache_clear()
    raw = np.asarray([[0.10, 0.20, 0.30, 0.40]], dtype=float)

    adjusted, applied = appearance_calibration.calibrate_minute_probabilities(raw, "MID")

    assert applied is True
    assert adjusted.sum() == pytest.approx(1.0)
    assert adjusted[0, 0] == pytest.approx(raw[0, 0])
    assert adjusted[0, 3] / adjusted[0, 1] > raw[0, 3] / raw[0, 1]
    appearance_calibration.load_appearance_calibration.cache_clear()
