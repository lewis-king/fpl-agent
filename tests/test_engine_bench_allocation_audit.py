from __future__ import annotations

from fplagent_engine.bench_allocation_audit import (
    bench_profile,
    targeted_retention_assessment,
)


def _row(element: int, name: str, position: str, price: int) -> dict:
    return {
        "element": element,
        "player_name": name,
        "position": position,
        "market_price": price,
        "can_select": True,
        "removed": False,
    }


def test_bench_profile_separates_role_assignment_from_four_cheapest_spend() -> None:
    meta = {
        1: _row(1, "Starting keeper", "GK", 55),
        2: _row(2, "Reserve keeper", "GK", 45),
        3: _row(3, "Def one", "DEF", 60),
        4: _row(4, "Def two", "DEF", 55),
        5: _row(5, "Def three", "DEF", 50),
        6: _row(6, "Def four", "DEF", 50),
        7: _row(7, "Def five", "DEF", 40),
        8: _row(8, "Mid one", "MID", 120),
        9: _row(9, "Mid two", "MID", 80),
        10: _row(10, "Rotating mid", "MID", 70),
        11: _row(11, "Floor mid", "MID", 50),
        12: _row(12, "Mid five", "MID", 50),
        13: _row(13, "Forward one", "FWD", 80),
        14: _row(14, "Forward two", "FWD", 80),
        15: _row(15, "Forward three", "FWD", 60),
        16: _row(16, "Floor keeper", "GK", 40),
        17: _row(17, "Floor forward", "FWD", 45),
    }
    selected = list(range(1, 16))
    lineups = {
        "1": {
            "starters": [1, 3, 4, 5, 6, 8, 9, 11, 13, 14, 15],
            "bench_order": [10, 7, 12, 2],
            "formation": "4-3-3",
        },
        "2": {
            "starters": [1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15],
            "bench_order": [11, 7, 12, 2],
            "formation": "4-3-3",
        },
    }
    result = bench_profile({"selected": selected, "lineups": lineups}, meta, events=(1, 2))

    assert result["nominal_gw1_bench_spend"] == 20.5
    assert result["four_cheapest_squad_spend"] == 18.5
    assert result["gw1_role_assignment_premium"] == 2.0
    assert result["gw1_bench_players_used_later"] == 1
    assert result["gw1_bench_future_start_events"] == 1
    rotating = next(
        player for player in result["gw1_bench_players"] if player["name"] == "Rotating mid"
    )
    assert rotating["future_starts"] == [2]
    assert rotating["premium_above_position_floor"] == 2.0


def _ranking_row(candidate_id: str, regret: float, worst: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "synthesis_regret": regret,
        "family_worst_regret": worst,
    }


def test_targeted_holdout_retains_practical_tie_only_with_lower_worst_regret() -> None:
    result = targeted_retention_assessment(
        _ranking_row("active", 0.80, 0.95),
        _ranking_row("fresh", 0.74, 1.20),
        active_won_original_selector=True,
        equivalence_regret=0.25,
    )

    assert result["survives"] is True
    assert result["practically_equivalent"] is True


def test_targeted_holdout_rejects_material_gap_or_worse_tail() -> None:
    material = targeted_retention_assessment(
        _ranking_row("active", 1.10, 0.90),
        _ranking_row("fresh", 0.74, 1.20),
        active_won_original_selector=True,
        equivalence_regret=0.25,
    )
    worse_tail = targeted_retention_assessment(
        _ranking_row("active", 0.80, 1.30),
        _ranking_row("fresh", 0.74, 1.20),
        active_won_original_selector=True,
        equivalence_regret=0.25,
    )

    assert material["survives"] is False
    assert worse_tail["survives"] is False


def test_targeted_holdout_cannot_rescue_non_selector_winner() -> None:
    result = targeted_retention_assessment(
        _ranking_row("active", 0.80, 0.95),
        _ranking_row("fresh", 0.74, 1.20),
        active_won_original_selector=False,
        equivalence_regret=0.25,
    )

    assert result["survives"] is False
