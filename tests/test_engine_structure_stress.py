from __future__ import annotations

import pytest

from fplagent_engine.structure_stress import (
    bench_proxy_coverage,
    reconcile_structure_reversal,
    robust_structure_rows,
)


def test_structure_regret_prefers_candidate_balanced_across_scoring_views() -> None:
    values = {
        "fragile": {
            "central_rules": 60.0,
            "bonus_removed": 55.0,
            "defensive_contribution_removed": 55.0,
            "bonus_and_defensive_removed": 50.0,
            "bonus_and_defensive_doubled": 65.0,
        },
        "balanced": {
            "central_rules": 59.5,
            "bonus_removed": 59.0,
            "defensive_contribution_removed": 59.0,
            "bonus_and_defensive_removed": 58.5,
            "bonus_and_defensive_doubled": 60.0,
        },
    }

    rows = robust_structure_rows(values)

    assert rows[0]["candidate_id"] == "balanced"
    assert rows[0]["worst_regret"] < rows[1]["worst_regret"]


def test_proxy_coverage_counts_settings_not_unique_squads() -> None:
    runs = [
        {"bench_autosub_weight": weight, "candidate_id": "same" if weight < 0.1 else "other"}
        for weight in (0.0, 0.04, 0.08, 0.12, 0.20)
    ]

    assert bench_proxy_coverage(runs) is True


def test_supported_gw1_reversal_is_reconciled_when_multiweek_selector_ranked_it_lower() -> None:
    decision = {
        "ranking": [
            {"candidate_id": "season", "rank": 1, "synthesis_regret": 1.2},
            {"candidate_id": "gw1", "rank": 2, "synthesis_regret": 1.5},
        ]
    }

    result = reconcile_structure_reversal(
        decision,
        published_candidate_id="season",
        challenger_candidate_id="gw1",
        supported_reversal=True,
    )

    assert result["passed"] is True
    assert result["challenger_synthesis_regret_delta"] == pytest.approx(0.3)


def test_new_gw1_proxy_challenger_without_multiweek_score_blocks_publication() -> None:
    decision = {
        "ranking": [
            {"candidate_id": "season", "rank": 1, "synthesis_regret": 1.2},
        ]
    }

    result = reconcile_structure_reversal(
        decision,
        published_candidate_id="season",
        challenger_candidate_id="new-proxy",
        supported_reversal=True,
    )

    assert result["passed"] is False
    assert result["status"] == "challenger_missing_multiweek_evaluation"
