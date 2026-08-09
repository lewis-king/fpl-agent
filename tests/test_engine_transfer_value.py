from __future__ import annotations

import json
from pathlib import Path

import pytest

from fplagent_engine.transfer_value import (
    fit_terminal_free_transfer_curve,
    load_terminal_free_transfer_curve,
)


def _observation(season: str, event: int, scale: float) -> dict:
    return {
        "season": season,
        "event": event,
        "cumulative_value_by_bank": {
            str(bank): scale * (bank**0.7) for bank in range(6)
        },
    }


def test_transfer_value_curve_promotes_on_stable_held_out_opportunities() -> None:
    observations = [
        *[_observation("2023-24", event, 0.95 + 0.01 * event) for event in range(1, 11)],
        *[_observation("2024-25", event, 1.00 + 0.01 * event) for event in range(1, 11)],
        *[_observation("2025-26", event, 1.02 + 0.01 * event) for event in range(1, 11)],
    ]

    result = fit_terminal_free_transfer_curve(observations, bootstrap_samples=200)

    assert result["promotion_gate"]["promoted"] is True
    assert result["held_out_metrics"]["candidate_mae"] < result["held_out_metrics"][
        "zero_baseline_mae"
    ]
    curve = [result["selected_curve"][str(bank)] for bank in range(6)]
    assert curve == sorted(curve)
    assert curve[0] == 0.0


def test_transfer_value_curve_rejects_candidate_that_does_not_beat_zero() -> None:
    observations = [
        *[_observation("2023-24", event, 0.0) for event in range(1, 11)],
        *[_observation("2024-25", event, 0.0) for event in range(1, 11)],
        *[_observation("2025-26", event, 1.0) for event in range(1, 11)],
    ]

    result = fit_terminal_free_transfer_curve(observations, bootstrap_samples=200)

    assert result["promotion_gate"]["promoted"] is False
    assert set(result["selected_curve"].values()) == {0.0}


def test_transfer_value_curve_rejects_decreasing_observation() -> None:
    observations = [_observation("2023-24", event, 1.0) for event in range(1, 21)]
    observations.extend(_observation("2025-26", event, 1.0) for event in range(1, 11))
    observations[0]["cumulative_value_by_bank"]["3"] = 0.1

    with pytest.raises(ValueError, match="non-decreasing"):
        fit_terminal_free_transfer_curve(observations, bootstrap_samples=200)


def test_transfer_value_loader_uses_only_a_promoted_curve(tmp_path: Path) -> None:
    artifact = tmp_path / "transfer-value.json"
    payload = {
        "version": "test-v1",
        "created_at": "2026-08-07T12:00:00+00:00",
        "fit": {
            "maximum_free_transfers": 5,
            "selected_curve": {str(bank): float(bank) for bank in range(6)},
            "promotion_gate": {"promoted": True},
        },
    }
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    curve, receipt = load_terminal_free_transfer_curve(path=artifact)

    assert curve[5] == 5.0
    assert receipt["status"] == "promoted"
    payload["fit"]["promotion_gate"]["promoted"] = False
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    curve, receipt = load_terminal_free_transfer_curve(path=artifact)
    assert set(curve.values()) == {0.0}
    assert receipt["status"] == "not_promoted"
