from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from fplagent_engine.appearance_role_challenger import (
    align_role_matrix,
    role_adjusted_play_probability,
)


def test_role_adjustment_preserves_champion_when_feature_model_is_unchanged() -> None:
    champion = np.asarray([0.2, 0.5, 0.9])
    baseline = np.asarray([0.3, 0.6, 0.8])

    adjusted = role_adjusted_play_probability(champion, baseline, baseline)

    assert adjusted == pytest.approx(champion)


def test_role_adjustment_transfers_odds_direction_without_exceeding_probability_bounds() -> None:
    adjusted = role_adjusted_play_probability(
        np.asarray([0.7, 0.7]),
        np.asarray([0.5, 0.5]),
        np.asarray([0.8, 0.2]),
    )

    assert adjusted[0] > 0.7
    assert adjusted[1] < 0.7
    assert np.all((adjusted > 0.0) & (adjusted < 1.0))


def test_role_matrix_is_realigned_to_physical_base_row_order() -> None:
    base = pa.Table.from_pylist([{"row_id": 2}, {"row_id": 1}])
    role = pa.Table.from_pylist(
        [
            {
                "row_id": 1,
                "role_appearance_rate10": 0.1,
                "role_appearance_rate38": 0.1,
                "role_start_rate3": 0.1,
                "role_start_rate10": 0.1,
                "role_start_rate38": 0.1,
                "role_full_match_rate5": 0.1,
                "role_full_match_rate10": 0.1,
                "role_minutes_sd5": 1.0,
                "role_minutes_sd10": 1.0,
                "role_minutes_min5": 0.0,
                "role_minutes_max5": 90.0,
                "role_season_boundary": 0.0,
                "role_regular_before_boundary": 0.0,
                "role_isolated_rest_before_boundary": 0.0,
            },
            {
                "row_id": 2,
                "role_appearance_rate10": 0.9,
                "role_appearance_rate38": 0.9,
                "role_start_rate3": 0.9,
                "role_start_rate10": 0.9,
                "role_start_rate38": 0.9,
                "role_full_match_rate5": 0.9,
                "role_full_match_rate10": 0.9,
                "role_minutes_sd5": 2.0,
                "role_minutes_sd10": 2.0,
                "role_minutes_min5": 10.0,
                "role_minutes_max5": 80.0,
                "role_season_boundary": 1.0,
                "role_regular_before_boundary": 0.9,
                "role_isolated_rest_before_boundary": 1.0,
            },
        ]
    )

    matrix = align_role_matrix(base, role)

    assert matrix[0, 0] == pytest.approx(0.9)
    assert matrix[1, 0] == pytest.approx(0.1)
