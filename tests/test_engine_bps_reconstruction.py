from __future__ import annotations

import numpy as np

from fplagent_engine.bps_reconstruction import allocate_bonus, cbi_bps_delta


def test_bonus_allocation_handles_first_place_tie() -> None:
    bonus = allocate_bonus(
        np.asarray([30, 30, 27, 20]),
        np.asarray([90, 90, 90, 90]),
    )

    assert bonus.tolist() == [3, 3, 1, 0]


def test_bonus_allocation_handles_second_and_third_place_ties() -> None:
    second = allocate_bonus(
        np.asarray([31, 29, 29, 20]),
        np.asarray([90, 90, 90, 90]),
    )
    third = allocate_bonus(
        np.asarray([31, 29, 27, 27]),
        np.asarray([90, 90, 90, 90]),
    )

    assert second.tolist() == [3, 2, 2, 0]
    assert third.tolist() == [3, 2, 1, 1]


def test_bonus_allocation_excludes_zero_minute_players() -> None:
    bonus = allocate_bonus(
        np.asarray([100, 30, 20, 10]),
        np.asarray([0, 90, 90, 90]),
    )

    assert bonus.tolist() == [0, 3, 2, 1]


def test_cbi_delta_changes_from_every_two_to_every_three() -> None:
    cbi = np.arange(0, 13)

    assert cbi_bps_delta(cbi).tolist() == [0, 0, -1, 0, -1, -1, -1, -1, -2, -1, -2, -2, -2]
