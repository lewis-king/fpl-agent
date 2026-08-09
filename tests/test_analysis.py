import numpy as np

from fplagent_data.analysis import BASE_FEATURES, UNDERLYING_FEATURES, _rank


def test_production_feature_sets_exclude_same_gameweek_fields() -> None:
    forbidden = {
        "points",
        "minutes",
        "current_xp_unsafe",
        "selected",
        "transfers_in",
        "transfers_out",
    }
    assert forbidden.isdisjoint(BASE_FEATURES)
    assert forbidden.isdisjoint(UNDERLYING_FEATURES)


def test_rank_uses_average_ranks_for_ties() -> None:
    np.testing.assert_array_equal(_rank(np.array([5.0, 2.0, 5.0, 9.0])), [1.5, 0.0, 1.5, 3.0])
