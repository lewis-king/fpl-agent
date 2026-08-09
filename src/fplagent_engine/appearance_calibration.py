from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import numpy as np

from .paths import ARTIFACTS

CALIBRATION_FILE = ARTIFACTS / "appearance_v1" / "calibration.json"


@lru_cache(maxsize=1)
def load_appearance_calibration() -> dict[str, Any] | None:
    if not CALIBRATION_FILE.exists():
        return None
    artifact = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    return artifact if artifact.get("promoted_positions") else None


def calibrate_minute_probabilities(
    probabilities: np.ndarray, position: str
) -> tuple[np.ndarray, bool]:
    """Apply the promoted position calibrator without changing unpromoted positions."""
    artifact = load_appearance_calibration()
    if not artifact or position not in artifact["calibrators"]:
        return probabilities, False
    calibrator = artifact["calibrators"][position]
    output = probabilities.copy()
    raw_play = np.clip(output[..., 1:].sum(axis=-1), 1e-5, 1.0 - 1e-5)
    logit = np.log(raw_play / (1.0 - raw_play))
    play = calibrator.get("play", calibrator)
    adjusted_play = 1.0 / (
        1.0
        + np.exp(
            -(
                float(play["intercept"])
                + float(play["coefficient"]) * logit
            )
        )
    )
    conditional = output[..., 1:] / raw_play[..., None]
    if calibrator.get("method") == "two_stage_temperature":
        temperature = float(calibrator["conditional_temperature"])
        if not 0.1 <= temperature <= 10.0:
            raise ValueError("appearance conditional temperature is outside [0.1, 10]")
        logits = np.log(np.clip(conditional, 1e-8, 1.0)) / temperature
        logits -= logits.max(axis=-1, keepdims=True)
        conditional = np.exp(logits)
        conditional /= conditional.sum(axis=-1, keepdims=True)
    output[..., 1:] = adjusted_play[..., None] * conditional
    output[..., 0] = 1.0 - adjusted_play
    output /= output.sum(axis=-1, keepdims=True)
    return output, True
