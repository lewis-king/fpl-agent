from __future__ import annotations

import pytest

from fplagent_engine.role_residual_challenger import (
    adjusted_expected_points,
    decision_focus_mask,
)


def test_decision_focus_is_scoped_per_event_and_position(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        __import__(
            "fplagent_engine.role_residual_challenger", fromlist=["TOP_K"]
        ).TOP_K,
        "FWD",
        1,
    )
    rows = [
        {
            "season": "2025-26",
            "event_number": event,
            "position": "FWD",
            "element": event * 10 + offset,
            "champion_expected_points": points,
            "market_price": price,
        }
        for event in (1, 2)
        for offset, (points, price) in enumerate(((8.0, 120.0), (6.0, 45.0), (2.0, 40.0)))
    ]

    focus = decision_focus_mask(rows)

    assert focus.tolist() == [True, True, False, True, True, False]


def test_adjusted_expected_points_caps_play_probability_leverage() -> None:
    assert adjusted_expected_points(5.0, 0.5, 1.0) == pytest.approx(6.25)
    assert adjusted_expected_points(5.0, 1.0, 0.1) == pytest.approx(3.0)


def test_adjusted_expected_points_preserves_score_when_probability_is_unchanged() -> None:
    assert adjusted_expected_points(4.7, 0.83, 0.83) == pytest.approx(4.7)
