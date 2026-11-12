from __future__ import annotations

import pytest

from fplagent_engine.deadline_stability import evaluate_stability, synthesis_ranking


def test_synthesis_ranking_balances_families_and_worst_case() -> None:
    ranking = synthesis_ranking(
        {"balanced": 1.0, "short": 0.0},
        {"balanced": 1.0, "short": 3.0},
        horizon_weight=0.5,
        worst_weight=0.2,
    )

    assert ranking[0]["candidate_id"] == "balanced"
    assert ranking[0]["synthesis_regret"] == pytest.approx(1.0)
    assert ranking[1]["synthesis_regret"] == pytest.approx(1.8)
    assert ranking[1]["regret_to_leader"] == pytest.approx(0.8)


def _seed(seed: int, winner: str, selected_grid_regret: float = 0.10) -> dict:
    other = "other" if winner == "selected" else "selected"
    return {
        "seed": seed,
        "production": [
            {
                "candidate_id": winner,
                "rank": 1,
                "synthesis_regret": 0.0,
                "regret_to_leader": 0.0,
            },
            {
                "candidate_id": other,
                "rank": 2,
                "synthesis_regret": 0.1,
                "regret_to_leader": 0.1,
            },
        ],
        "weight_grid": [
            {
                "winner": winner,
                "selected_regret_to_leader": selected_grid_regret,
            }
        ],
    }


def test_stability_gate_requires_selected_winner_on_every_production_seed() -> None:
    stable = evaluate_stability(
        decision_candidate_id="selected",
        candidate_count=5,
        seed_results=[_seed(1, "selected"), _seed(2, "selected"), _seed(3, "selected")],
    )
    unstable = evaluate_stability(
        decision_candidate_id="selected",
        candidate_count=5,
        seed_results=[_seed(1, "selected"), _seed(2, "other"), _seed(3, "selected")],
    )

    assert stable["passed"] is True
    assert stable["production_winner_counts"] == {"selected": 3}
    assert unstable["passed"] is False
    assert unstable["checks"]["selected_candidate_wins_every_production_seed"] is False


def test_stability_gate_rejects_material_weight_grid_brittleness() -> None:
    result = evaluate_stability(
        decision_candidate_id="selected",
        candidate_count=5,
        seed_results=[
            _seed(1, "selected"),
            _seed(2, "selected", selected_grid_regret=0.26),
            _seed(3, "selected"),
        ],
    )

    assert result["passed"] is False
    assert result["maximum_selected_grid_regret"] == pytest.approx(0.26)
    assert result["checks"]["selected_candidate_within_every_weight_grid_tolerance"] is False
