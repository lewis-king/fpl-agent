import numpy as np

from fplagent_engine.models import _spearman


def test_spearman_uses_average_ranks_for_ties() -> None:
    actual = np.asarray([0.0, 0.0, 1.0, 1.0])
    same_tie_groups_reordered = np.asarray([5.0, 5.0, 9.0, 9.0])

    assert _spearman(actual, same_tie_groups_reordered) == 1.0


def test_spearman_does_not_reward_arbitrary_order_within_ties() -> None:
    actual = np.asarray([0.0, 0.0, 1.0, 1.0])
    arbitrary_row_order = np.asarray([1.0, 0.0, 1.0, 0.0])

    assert _spearman(actual, arbitrary_row_order) == 0.0
