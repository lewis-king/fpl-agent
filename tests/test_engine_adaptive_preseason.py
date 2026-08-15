from __future__ import annotations

import numpy as np
import pytest

from fplagent_engine.adaptive_preseason import (
    full_pipeline_request_gate,
    rank_adaptive_candidates,
)


def _row(
    candidate_id: str,
    *,
    regret: float,
    base: float,
    lead: float,
    role: float,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "robust_regret": regret,
        "scenario_values": {
            "base_open": base,
            "lead_open": lead,
            "base_fixed": base - 2.0,
            "lead_fixed": lead - 2.0,
            "moderate_role_base_open": role,
        },
    }


def test_ranking_penalises_a_one_world_specialist() -> None:
    candidate_ids = ["production", "specialist", "balanced"]
    values = {
        "base_open": np.asarray([100.0, 98.0, 100.2]),
        "lead_open": np.asarray([100.0, 105.0, 101.0]),
        "base_fixed": np.asarray([100.0, 97.0, 100.2]),
        "lead_fixed": np.asarray([100.0, 105.0, 101.0]),
        "moderate_role_base_open": np.asarray([100.0, 96.0, 100.2]),
    }

    ranking = rank_adaptive_candidates(
        candidate_ids,
        values,
        production_id="production",
    )

    assert ranking[0]["candidate_id"] == "balanced"
    specialist = next(row for row in ranking if row["candidate_id"] == "specialist")
    assert specialist["robust_regret"] > ranking[0]["robust_regret"]


def test_ranking_keeps_incumbent_when_robust_regret_is_tied() -> None:
    values = {
        name: np.asarray([100.0, 100.0])
        for name in (
            "base_open",
            "lead_open",
            "base_fixed",
            "lead_fixed",
            "moderate_role_base_open",
        )
    }

    ranking = rank_adaptive_candidates(
        ["challenger", "production"],
        values,
        production_id="production",
    )

    assert ranking[0]["candidate_id"] == "production"


def test_ranking_rejects_misaligned_scenarios() -> None:
    with pytest.raises(ValueError, match="same scenarios"):
        rank_adaptive_candidates(
            ["production"],
            {"base_open": np.asarray([1.0])},
            production_id="production",
        )


def test_full_pipeline_gate_requires_broad_non_regression() -> None:
    incumbent = _row(
        "production", regret=1.0, base=100.0, lead=100.0, role=100.0
    )
    strong = _row("challenger", regret=0.70, base=99.8, lead=101.0, role=99.8)
    fragile = _row("fragile", regret=0.50, base=99.0, lead=103.0, role=98.0)

    passed = full_pipeline_request_gate(strong, incumbent)
    failed = full_pipeline_request_gate(fragile, incumbent)

    assert passed["passed"] is True
    assert all(passed["checks"].values())
    assert failed["passed"] is False
    assert failed["checks"]["base_open_non_regression"] is False
    assert failed["checks"]["role_downside_non_regression"] is False
