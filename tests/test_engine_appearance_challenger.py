from __future__ import annotations

import json

import numpy as np
import pytest

from fplagent_engine.appearance_challenger import (
    anchor_play_probability,
    apply_calibrator,
    fit_calibrator,
    method_gate,
)
from fplagent_engine.appearance_policy_replay import (
    policy_replay_gate,
    retire_failed_appearance_calibration,
)
from fplagent_engine.cli import parser


def test_anchor_preserves_champion_play_probability_and_model_class_shares() -> None:
    model = np.asarray(
        [
            [0.20, 0.10, 0.20, 0.50],
            [0.40, 0.30, 0.20, 0.10],
        ],
        dtype=float,
    )
    champion_play = np.asarray([0.90, 0.25])

    anchored = anchor_play_probability(model, champion_play)

    np.testing.assert_allclose(anchored[:, 1:].sum(axis=1), champion_play)
    np.testing.assert_allclose(anchored.sum(axis=1), 1.0)
    np.testing.assert_allclose(
        anchored[0, 1:] / anchored[0, 1:].sum(),
        model[0, 1:] / model[0, 1:].sum(),
    )


def test_two_stage_calibrator_returns_valid_four_class_probabilities() -> None:
    probabilities = np.asarray(
        [
            [0.80, 0.10, 0.05, 0.05],
            [0.60, 0.20, 0.10, 0.10],
            [0.30, 0.30, 0.20, 0.20],
            [0.20, 0.10, 0.30, 0.40],
            [0.10, 0.05, 0.15, 0.70],
            [0.05, 0.05, 0.10, 0.80],
            [0.25, 0.25, 0.25, 0.25],
            [0.45, 0.20, 0.20, 0.15],
        ],
        dtype=float,
    )
    actual = np.asarray([0, 0, 1, 2, 3, 3, 1, 0])

    calibrator = fit_calibrator("two_stage_temperature", probabilities, actual)
    adjusted = apply_calibrator(probabilities, calibrator)

    assert calibrator["method"] == "two_stage_temperature"
    assert 0.25 <= calibrator["conditional_temperature"] <= 4.0
    assert np.all(adjusted >= 0.0)
    np.testing.assert_allclose(adjusted.sum(axis=1), 1.0)


def _validation(season: str, *, challenger_brier: float = 0.09) -> dict:
    return {
        "test_season": season,
        "method": "two_stage_temperature",
        "raw": {
            "play_brier": 0.10,
            "play_log_loss": 0.30,
            "multiclass_brier": 0.40,
            "multiclass_log_loss": 0.70,
            "expected_minutes_mae": 16.0,
        },
        "challenger": {
            "play_brier": challenger_brier,
            "play_log_loss": 0.29,
            "multiclass_brier": 0.39,
            "multiclass_log_loss": 0.69,
            "expected_minutes_mae": 15.9,
        },
        "raw_decision": {"points_mae": 2.50, "top_k_actual_points": 4.25},
        "challenger_decision": {"points_mae": 2.505, "top_k_actual_points": 4.245},
    }


def test_gate_requires_every_forward_slice_and_decision_non_regression() -> None:
    passing = [_validation("2024-25"), _validation("2025-26")]
    failing = [_validation("2024-25"), _validation("2025-26", challenger_brier=0.11)]

    assert method_gate(passing, "two_stage_temperature")["passed"] is True
    result = method_gate(failing, "two_stage_temperature")
    assert result["passed"] is False
    assert result["checks"]["play_brier_wins"] is False


def test_four_class_challenger_is_exposed_without_a_promotion_flag() -> None:
    args = parser().parse_args(["audit-appearance-challenger"])

    assert args.command == "audit-appearance-challenger"
    assert not hasattr(args, "promote")


def test_policy_replay_gate_requires_positive_points_and_bounded_season_downside() -> None:
    passing = [
        {"season": "2024-25", "calibrated_minus_raw_points": value}
        for value in (2, 1, 0, 2)
    ] + [
        {"season": "2025-26", "calibrated_minus_raw_points": value}
        for value in (2, 1, 2, 1)
    ]
    failing = [
        {"season": "2024-25", "calibrated_minus_raw_points": -1},
        {"season": "2025-26", "calibrated_minus_raw_points": 0},
    ]

    assert policy_replay_gate(passing)["passed"] is True
    result = policy_replay_gate(failing)
    assert result["passed"] is False
    assert result["checks"]["positive_overall_mean"] is False


def test_failed_policy_replay_retires_and_archives_production_calibrator(
    tmp_path,
) -> None:
    calibration = tmp_path / "calibration.json"
    replay = tmp_path / "replay.json"
    archive = tmp_path / "before.json"
    receipt = tmp_path / "receipt.json"
    calibration.write_text(
        json.dumps(
            {
                "version": 1,
                "promoted_positions": ["FWD"],
                "calibrators": {"FWD": {"coefficient": 1.0, "intercept": 0.2}},
                "gate": {"FWD": {"promoted": True}},
            }
        ),
        encoding="utf-8",
    )
    before = calibration.read_bytes()
    replay.write_text(
        json.dumps(
            {
                "position": "FWD",
                "gate": {
                    "passed": False,
                    "mean_delta": -0.7,
                    "delta_95ci_low": -1.2,
                    "delta_95ci_high": -0.1,
                    "season_mean_delta": {"2024-25": -0.5, "2025-26": -0.9},
                },
            }
        ),
        encoding="utf-8",
    )

    result = retire_failed_appearance_calibration(
        position="FWD",
        replay_path=replay,
        calibration_path=calibration,
        archive_path=archive,
        receipt_path=receipt,
    )
    updated = json.loads(calibration.read_text(encoding="utf-8"))

    assert result["status"] == "retired"
    assert updated["promoted_positions"] == []
    assert updated["calibrators"] == {}
    assert updated["retirement"]["mean_delta"] == -0.7
    assert archive.read_bytes() == before


def test_passing_replay_cannot_retire_a_calibrator(tmp_path) -> None:
    replay = tmp_path / "replay.json"
    replay.write_text(
        json.dumps({"position": "FWD", "gate": {"passed": True}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="failed policy replay"):
        retire_failed_appearance_calibration(
            position="FWD",
            replay_path=replay,
            calibration_path=tmp_path / "missing.json",
        )
