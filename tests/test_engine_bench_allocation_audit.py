from __future__ import annotations

from fplagent_engine.bench_allocation_audit import (
    _targeted_candidates,
    bench_allocation_publication_checks,
    bench_profile,
    selected_synthesis_publication_rank,
    targeted_retention_assessment,
)


def test_targeted_candidates_include_promoted_horizon_neighbour() -> None:
    shortlist = [
        {"candidate_id": "current", "gw1_bench_spend": 21.0},
        {"candidate_id": "robust", "gw1_bench_spend": 21.0},
        {"candidate_id": "historical", "gw1_bench_spend": 19.5},
        {"candidate_id": "high", "gw1_bench_spend": 22.5},
    ]
    selection_rows = [
        {"candidate_id": candidate["candidate_id"], "evidence_mean": 1.0, "cvar10": 1.0}
        for candidate in shortlist
    ]
    synthesis = {
        "decision": {"candidate_id": "current"},
        "ranking": [
            {"candidate_id": "current", "gw1_bench_spend": 21.0},
            {"candidate_id": "high", "gw1_bench_spend": 22.5},
        ],
    }
    horizon_candidate = {"candidate_id": "horizon", "gw1_bench_spend": 20.5}

    candidates, coverage = _targeted_candidates(
        shortlist,
        selection_rows,
        synthesis,
        {"leader": {"candidate_id": "robust"}},
        {
            "leader": {"candidate_id": "horizon"},
            "leader_candidate": horizon_candidate,
        },
        top_historical_band=8,
        publication_eligible_ids={"current", "historical", "high", "horizon"},
    )

    candidate_ids = {candidate["candidate_id"] for candidate in candidates}
    assert "horizon" in candidate_ids
    assert "robust" not in candidate_ids
    assert coverage["horizon_leader_added_outside_robust_shortlist"] is True
    assert coverage["role_ineligible_candidates_excluded"] == 1


def test_selected_rank_uses_publication_field_not_unsafe_raw_field() -> None:
    synthesis = {
        "ranking": [
            {"candidate_id": "unsafe", "rank": 1},
            {"candidate_id": "selected", "rank": 9, "publication_rank": 1},
        ]
    }

    assert selected_synthesis_publication_rank(synthesis, "selected") == 1


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


def _family_ranking_row(
    candidate_id: str,
    regret: float,
    *,
    robust: float,
    horizon: float,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "synthesis_regret": regret,
        "family_worst_regret": max(robust, horizon),
        "robust_family_regret": robust,
        "horizon_family_regret": horizon,
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


def test_targeted_holdout_retains_small_non_dominated_family_tradeoff() -> None:
    result = targeted_retention_assessment(
        _family_ranking_row("active", 1.27, robust=1.62, horizon=0.76),
        _family_ranking_row("fresh", 1.11, robust=1.26, horizon=0.89),
        active_won_original_selector=True,
        equivalence_regret=0.25,
    )

    assert result["survives"] is True
    assert result["practically_equivalent"] is True
    assert result["pareto_dominated"] is False
    assert result["status"] == "practically_equivalent_non_dominated_family_tradeoff"


def test_targeted_holdout_rejects_pareto_dominated_active_squad() -> None:
    result = targeted_retention_assessment(
        _family_ranking_row("active", 1.20, robust=1.40, horizon=1.00),
        _family_ranking_row("fresh", 1.10, robust=1.25, horizon=0.90),
        active_won_original_selector=True,
        equivalence_regret=0.25,
    )

    assert result["survives"] is False
    assert result["pareto_dominated"] is True


def test_targeted_holdout_cannot_rescue_non_selector_winner() -> None:
    result = targeted_retention_assessment(
        _ranking_row("active", 0.80, 0.95),
        _ranking_row("fresh", 0.74, 1.20),
        active_won_original_selector=False,
        equivalence_regret=0.25,
    )

    assert result["survives"] is False


def test_bench_gate_accepts_complete_band_when_fewer_than_requested_exist() -> None:
    checks = bench_allocation_publication_checks(
        profile={
            "four_cheapest_squad_spend": 19.5,
            "gw1_bench_players_used_later": 4,
            "gw1_bench_future_start_events": 12,
        },
        retention={"survives": True},
        active_interval={"lower": 0.3, "upper": 0.7},
        coverage={
            "shortlist_at_or_below_20": 18,
            "top_historical_band_by_mean": 18,
            "targeted_unique_candidates": 22,
        },
        requested_historical_band=24,
    )

    assert all(checks.values())
