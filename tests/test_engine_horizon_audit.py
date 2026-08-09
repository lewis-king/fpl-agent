from __future__ import annotations

import numpy as np
import pytest

from fplagent_engine.cli import parser
from fplagent_engine.horizon_audit import (
    _select_horizon_neighbour_records,
    horizon_weights,
    weighted_totals,
)


def test_horizon_weights_decay_from_first_selected_event() -> None:
    assert horizon_weights((3, 4, 5), 0.8).tolist() == pytest.approx([1.0, 0.8, 0.64])


def test_weighted_totals_select_events_and_preserve_candidates() -> None:
    scores = np.asarray(
        [
            [[1, 2, 3, 4], [10, 20, 30, 40]],
            [[2, 3, 4, 5], [20, 30, 40, 50]],
        ],
        dtype=np.float64,
    )

    totals = weighted_totals(scores, (1, 2, 3, 4), (2, 3, 4), 0.5)

    assert totals.shape == (2, 2)
    assert totals[0].tolist() == pytest.approx([2 + 1.5 + 1.0, 20 + 15 + 10])
    assert totals[1].tolist() == pytest.approx([3 + 2 + 1.25, 30 + 20 + 12.5])


def test_horizon_weights_reject_invalid_decay() -> None:
    with pytest.raises(ValueError, match="valid horizon"):
        horizon_weights((1, 2), 0.0)


def test_weighted_totals_accept_single_candidate_matrix() -> None:
    scores = np.asarray([[1, 2, 3, 4], [2, 3, 4, 5]], dtype=np.float64)

    totals = weighted_totals(scores, (1, 2, 3, 4), (2, 3, 4), 0.5)

    assert totals.tolist() == pytest.approx([4.5, 6.25])


def test_horizon_neighbour_selection_preserves_each_source_seed() -> None:
    records = [
        {
            "candidate_id": f"candidate-{index}",
            "origin_ids": [f"horizon-neighbour:seed-{index % 3}"],
        }
        for index in range(12)
    ]
    metrics = [
        {
            "early": float(20 - index),
            "central": float(index),
            "late": float(12 - abs(6 - index)),
        }
        for index in range(12)
    ]

    selected = _select_horizon_neighbour_records(records, metrics, limit=8)

    assert len(selected) == 8
    selected_origins = {
        origin for row in selected for origin in row["origin_ids"]
    }
    assert selected_origins == {
        "horizon-neighbour:seed-0",
        "horizon-neighbour:seed-1",
        "horizon-neighbour:seed-2",
    }
    assert "candidate-0" in {row["candidate_id"] for row in selected}
    assert "candidate-11" in {row["candidate_id"] for row in selected}


def test_horizon_audit_cli_enables_protected_neighbour_portfolio() -> None:
    args = parser().parse_args(["horizon-audit"])

    assert args.horizon_neighbours == 32
    assert args.horizon_neighbour_seeds == 8
