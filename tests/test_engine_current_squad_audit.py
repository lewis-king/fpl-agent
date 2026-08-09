from __future__ import annotations

import numpy as np

from fplagent_engine.current_squad_audit import (
    _choice_leaders,
    _paired_delta,
    enumerate_legal_xis,
)


def _valid_meta() -> tuple[list[int], dict[int, dict]]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    selected = list(range(1, 16))
    return selected, {
        element: {"element": element, "position": position}
        for element, position in zip(selected, positions, strict=True)
    }


def test_enumerate_legal_xis_covers_every_formation_and_player_choice() -> None:
    selected, meta = _valid_meta()
    lineups = enumerate_legal_xis(selected, meta)

    formations = {
        tuple(sum(meta[element]["position"] == position for element in lineup) for position in ("DEF", "MID", "FWD"))
        for lineup in lineups
    }
    assert formations == {
        (3, 4, 3),
        (3, 5, 2),
        (4, 3, 3),
        (4, 4, 2),
        (4, 5, 1),
        (5, 2, 3),
        (5, 3, 2),
        (5, 4, 1),
    }
    assert len(lineups) == 550
    assert len(set(lineups)) == len(lineups)
    assert all(len(lineup) == 11 for lineup in lineups)


def test_choice_leaders_keeps_balanced_and_family_specific_options() -> None:
    family_means = np.asarray(
        [
            [5.0, 3.0],
            [4.4, 4.4],
            [3.0, 5.0],
        ]
    )
    assert _choice_leaders(family_means) == [1, 0, 2]


def test_paired_delta_uses_shared_world_differences() -> None:
    metrics = _paired_delta(np.asarray([2, 5, 4]), np.asarray([1, 3, 4]))
    assert metrics["mean"] == 1.0
    assert metrics["beat_probability"] == 2 / 3
    assert metrics["tie_probability"] == 1 / 3
