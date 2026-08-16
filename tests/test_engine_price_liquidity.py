import numpy as np

from fplagent_engine.price_liquidity import (
    affordability_scenario,
    multiclass_brier,
    score_net_points_timing,
    simulate_price_paths,
)


def test_multiclass_brier_rewards_correct_price_direction() -> None:
    good = np.asarray([[0.05, 0.10, 0.85]])
    bad = np.asarray([[0.80, 0.15, 0.05]])
    assert multiclass_brier(good, ["rise"]) < multiclass_brier(bad, ["rise"])


def test_affordability_scenario_models_forced_loss() -> None:
    scenario = affordability_scenario(
        [
            {
                "outgoing_player_id": 1,
                "incoming_player_id": 2,
                "purchase_price": 50,
                "outgoing_current_price": 50,
            }
        ],
        bank=0,
        price_probabilities={
            1: {"p_fall": 0.5, "p_none": 0.5, "p_rise": 0.0},
            2: {"p_fall": 0.0, "p_none": 0.5, "p_rise": 0.5},
        },
    )
    assert scenario["forced_affordability_loss_probability"] > 0.0


def test_price_policy_is_promoted_on_net_points_not_team_value() -> None:
    result = score_net_points_timing(
        [
            {
                "event": 2,
                "predicted_timing": "wait",
                "realized_wait_net_points": 8,
                "realized_move_now_net_points": 5,
                "team_value_delta": -2,
            }
        ]
    )
    assert result["total_net_points_delta"] == 3


def test_multi_night_paths_are_seeded_and_expose_affordability_tail() -> None:
    transfer = {
        "outgoing_player_id": 1,
        "incoming_player_id": 2,
        "purchase_price": 50,
        "outgoing_current_price": 50,
    }
    probabilities = {
        1: {"p_fall": 0.7, "p_none": 0.3, "p_rise": 0.0},
        2: {"p_fall": 0.0, "p_none": 0.3, "p_rise": 0.7},
    }
    first = simulate_price_paths(
        [transfer], bank=0, price_probabilities=probabilities, nights=3, simulations=2_000
    )
    second = simulate_price_paths(
        [transfer], bank=0, price_probabilities=probabilities, nights=3, simulations=2_000
    )
    assert first == second
    assert first["forced_affordability_loss_probability"] > 0.5
    assert first["p10_bank_after_wait"] < 0
