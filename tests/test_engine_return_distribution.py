import numpy as np

from fplagent_engine.captain_return_challenger import choose_regularized_weight
from fplagent_engine.market_transfer_replay import blend_score_rows
from fplagent_engine.return_distribution import (
    choose_temperature,
    return_class,
    temperature_scale,
)


def test_return_class_uses_fpl_return_and_haul_thresholds() -> None:
    points = np.asarray([-2.0, 0.0, 4.0, 5.0, 9.0, 10.0, 18.0])
    assert return_class(points).tolist() == [0, 0, 0, 1, 1, 2, 2]


def test_temperature_scale_preserves_valid_probabilities() -> None:
    probabilities = np.asarray([[0.80, 0.15, 0.05], [0.40, 0.35, 0.25]])
    calibrated = temperature_scale(probabilities, 1.35)
    assert np.allclose(calibrated.sum(axis=1), 1.0)
    assert np.all((calibrated > 0.0) & (calibrated < 1.0))
    assert calibrated[0, 0] < probabilities[0, 0]


def test_temperature_selection_is_deterministic() -> None:
    probabilities = np.asarray(
        [
            [0.90, 0.08, 0.02],
            [0.70, 0.20, 0.10],
            [0.40, 0.45, 0.15],
            [0.20, 0.45, 0.35],
        ]
    )
    labels = np.asarray([0, 0, 1, 2])
    assert choose_temperature(probabilities, labels) == choose_temperature(
        probabilities, labels
    )


def test_return_score_can_use_shared_sequential_replay_adapter() -> None:
    row = {
        "xp_expected_points": 4.0,
        "return_distribution_expected_points": 5.0,
    }
    scored = blend_score_rows([row], "return_distribution_expected_points", 0.5)[0]
    assert scored["expected_points"] == 4.5


def test_captain_weight_uses_smallest_one_standard_error_candidate() -> None:
    selected, rows = choose_regularized_weight(
        {
            0.0: [5, 5, 5, 5],
            0.5: [6, 5, 6, 5],
            1.0: [7, 4, 7, 4],
        }
    )

    assert selected == 0.5
    assert next(row for row in rows if row["weight"] == 0.5)[
        "within_one_standard_error"
    ] is True
