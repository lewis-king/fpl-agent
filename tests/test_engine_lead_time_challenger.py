from __future__ import annotations

import fplagent_engine.lead_time_challenger as challenger
from fplagent_engine.lead_time_challenger import (
    apply_prediction_overrides,
    decision_focus_mask,
)


def test_lead_focus_is_grouped_by_origin_target_and_position(monkeypatch) -> None:
    monkeypatch.setitem(challenger.TOP_K, "GK", 1)
    rows = [
        {
            "season": "2025-26",
            "origin_event": origin,
            "target_event": origin + 1,
            "position": "GK",
            "element": origin * 10 + offset,
            "baseline_expected_points": score,
            "market_price": price,
        }
        for origin in (1, 2)
        for offset, (score, price) in enumerate(
            ((5.0, 55.0), (4.0, 40.0), (1.0, 45.0))
        )
    ]

    assert decision_focus_mask(rows).tolist() == [True, True, False, True, True, False]


def test_prediction_override_only_changes_future_eligible_rows() -> None:
    rows = [
        {
            "event_number": event,
            "element": element,
            "position": position,
            "expected_points": 4.0,
            "robust_points": 4.0,
        }
        for event, element, position in (
            (1, 10, "MID"),
            (2, 10, "MID"),
            (2, 20, "DEF"),
        )
    ]
    predictions = {
        ("2025-26", 1, 2, 10): 6.0,
        ("2025-26", 1, 2, 20): 7.0,
    }

    output = apply_prediction_overrides(
        rows,
        season="2025-26",
        origin_event=1,
        prediction_by_key=predictions,
        eligible_positions=("MID",),
    )

    assert [row["expected_points"] for row in output] == [4.0, 6.0, 4.0]
    assert [row["robust_points"] for row in output] == [4.0, 6.0, 4.0]


def test_prediction_override_does_not_mutate_input_rows() -> None:
    row = {
        "event_number": 2,
        "element": 10,
        "position": "FWD",
        "expected_points": 4.0,
        "robust_points": 4.0,
    }

    output = apply_prediction_overrides(
        [row],
        season="2025-26",
        origin_event=1,
        prediction_by_key={("2025-26", 1, 2, 10): 5.5},
        eligible_positions=("FWD",),
    )

    assert output[0] is not row
    assert row["expected_points"] == 4.0
