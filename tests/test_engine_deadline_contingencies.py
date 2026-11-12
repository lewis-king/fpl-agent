from __future__ import annotations

from fplagent_engine.deadline_contingencies import _supported_fallback, _synthesis_tradeoff


def test_supported_fallback_uses_highest_minutes_with_deep_support() -> None:
    player = {
        "boundary": {
            "classification": "challenger_boundary_bracketed",
            "actionable": True,
            "highest_supported_challenger_minutes": 30.0,
        },
        "points": [
            {
                "target_expected_minutes": minutes,
                "deep_squad_replay": (
                    {"cross_family_holdout_support": support} if replay else None
                ),
            }
            for minutes, replay, support in [
                (0.0, True, True),
                (30.0, True, True),
                (45.0, True, False),
                (60.0, False, False),
            ]
        ]
    }

    assert _supported_fallback(player)["target_expected_minutes"] == 30.0


def test_supported_fallback_requires_deep_cross_family_support() -> None:
    player = {
        "boundary": {
            "classification": "challenger_boundary_bracketed",
            "actionable": True,
            "highest_supported_challenger_minutes": 30.0,
        },
        "points": [
            {
                "target_expected_minutes": 0.0,
                "deep_squad_replay": {"cross_family_holdout_support": False},
            },
            {"target_expected_minutes": 30.0, "deep_squad_replay": None},
        ]
    }

    assert _supported_fallback(player) is None


def test_supported_fallback_rejects_general_gw1_alternative_at_live_anchor() -> None:
    player = {
        "boundary": {
            "classification": "general_gw1_challenger_at_production_anchor",
            "actionable": False,
            "highest_supported_challenger_minutes": None,
        },
        "points": [
            {
                "target_expected_minutes": 90.0,
                "deep_squad_replay": {"cross_family_holdout_support": True},
            }
        ],
    }

    assert _supported_fallback(player) is None


def test_synthesis_tradeoff_requires_gw1_gain_to_repay_multiweek_regret() -> None:
    decision = {
        "decision": {"candidate_id": "central"},
        "ranking": [
            {"candidate_id": "central", "synthesis_regret": 1.0},
            {"candidate_id": "challenger", "synthesis_regret": 4.0},
        ],
    }
    replay = {
        "holdout_delta_challenger_to_incumbent": {
            "residual": {"mean": 1.2},
            "component": {"mean": 0.8},
        }
    }

    result = _synthesis_tradeoff(decision, challenger_id="challenger", replay=replay)

    assert result["minimum_gw1_holdout_gain"] == 0.8
    assert result["multiweek_synthesis_regret_delta"] == 3.0
    assert result["actionable"] is False
