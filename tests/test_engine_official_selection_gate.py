from __future__ import annotations

from fplagent_engine.models import _apply_official_selection_gate


def test_official_selection_gate_zeros_sale_only_player_across_horizon() -> None:
    rows = [
        {
            "event_number": event,
            "element": 527,
            "can_select": False,
            "p_dnp": 0.8,
            "p_1_59": 0.1,
            "p_60_89": 0.05,
            "p_90_or_more": 0.05,
            "p_play": 0.2,
            "conditional_points_if_playing": 4.0,
            "expected_points": 0.8,
            "epistemic_uncertainty": 0.2,
            "robust_points": 0.77,
            "live_role_minutes_ratio": 0.35,
        }
        for event in range(3, 8)
    ]

    gated, count = _apply_official_selection_gate(rows)

    assert count == 5
    assert all(row["p_dnp"] == 1.0 for row in gated)
    assert all(row["p_play"] == 0.0 for row in gated)
    assert all(row["expected_points"] == 0.0 for row in gated)
    assert all(row["robust_points"] == 0.0 for row in gated)
    assert all(row["live_role_minutes_ratio"] == 0.0 for row in gated)
    assert all(row["official_selection_gate_applied"] is True for row in gated)


def test_official_selection_gate_does_not_touch_selectable_player() -> None:
    original = {
        "event_number": 3,
        "element": 1,
        "can_select": True,
        "p_play": 0.9,
        "expected_points": 5.0,
        "robust_points": 4.9,
    }

    gated, count = _apply_official_selection_gate([original])

    assert count == 0
    assert gated[0]["p_play"] == 0.9
    assert gated[0]["expected_points"] == 5.0
    assert gated[0]["official_selection_gate_applied"] is False
