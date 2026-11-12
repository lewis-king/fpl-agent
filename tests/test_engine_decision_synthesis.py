from __future__ import annotations

import pytest

from fplagent_engine.decision_synthesis import (
    annotate_future_transfer_policy,
    champion_intervals,
    synthesis_rows,
)


def _row(candidate_id: str, regret: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "display_name": candidate_id,
        "origin_ids": [candidate_id],
        "gw1_formation": "4-3-3",
        "gw1_bench_spend": 20.0,
        "robust_regret": regret,
    }


def test_synthesis_rewards_balance_across_audit_families() -> None:
    rows = synthesis_rows(
        [_row("balanced", 0.7), _row("horizon-only", 1.9)],
        [_row("balanced", 0.8), _row("horizon-only", 0.1)],
        horizon_family_weight=0.5,
        family_worst_weight=0.2,
    )
    assert rows[0]["candidate_id"] == "balanced"
    assert rows[0]["synthesis_regret"] == pytest.approx(0.76)


def test_champion_intervals_find_exact_family_weight_switch() -> None:
    rows = synthesis_rows(
        [_row("a", 0.0), _row("b", 1.0)],
        [_row("a", 1.0), _row("b", 0.0)],
        horizon_family_weight=0.5,
        family_worst_weight=0.0,
    )
    intervals = champion_intervals(rows)
    assert intervals == [
        {"lower": 0.0, "upper": 0.5, "candidate_id": "a", "midpoint_regret": 0.25},
        {"lower": 0.5, "upper": 1.0, "candidate_id": "b", "midpoint_regret": 0.25},
    ]


def test_champion_intervals_include_declared_worst_family_penalty() -> None:
    rows = synthesis_rows(
        [_row("balanced", 0.7), _row("horizon-only", 1.9)],
        [_row("balanced", 0.8), _row("horizon-only", 0.1)],
        horizon_family_weight=0.5,
        family_worst_weight=0.2,
    )
    intervals = champion_intervals(rows, family_worst_weight=0.2)
    assert intervals[0]["candidate_id"] == "balanced"
    assert intervals[0]["upper"] == pytest.approx(0.7763157895)


def test_synthesis_rejects_invalid_weights() -> None:
    with pytest.raises(ValueError, match="horizon_family_weight"):
        synthesis_rows(
            [_row("a", 0.1)],
            [_row("a", 0.1)],
            horizon_family_weight=1.1,
            family_worst_weight=0.2,
        )


def test_future_transfer_policy_is_scenario_only_and_exposes_current_role_conflict() -> None:
    policy = {
        "6": {
            "available": 2,
            "used": 1,
            "in": [{"element": 55, "name": "Watkins"}],
            "out": [{"element": 99, "name": "Other"}],
        }
    }
    rows = [
        {
            "event_number": event,
            "element": 55,
            "position": "FWD",
            "market_price": 80.0,
            "player_name": "Watkins",
            "p_play": 0.78 if event == 1 else 0.95,
            "expected_minutes": 35.3 if event == 1 else 75.0,
            "live_participation_consensus": (
                "predicted_bench_consensus" if event == 1 else "not_covered"
            ),
        }
        for event in (1, 6)
    ]

    result = annotate_future_transfer_policy(
        policy,
        rows,
        {55: {"position": "FWD", "market_price": 80.0, "player_name": "Watkins"}},
    )

    assert result["6"]["execution_status"] == "conditional_recompute_required"
    assert result["6"]["authority"] == "scenario_only_not_an_action_recommendation"
    assert result["6"]["requires_live_role_revalidation"] is True
    assert result["6"]["current_role_conflicts"][0]["element"] == 55
    assert result["6"]["planned_event_role_conflicts"] == []
