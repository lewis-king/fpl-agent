from __future__ import annotations

import json
from decimal import Decimal

import numpy as np
import pytest

from fplagent_engine.participation_break_even import (
    apply_player_minutes_counterfactual,
    compact_counterfactual_forecast,
    counterfactual_player_forecast,
    minute_tilt_probabilities,
    select_attention_players,
    summarize_player_boundary,
)


def _row() -> dict:
    return {
        "element": 10,
        "expected_points": 4.5,
        "robust_points": 4.3,
        "epistemic_uncertainty": 0.2,
        "p_dnp": 0.10,
        "p_1_59": 0.10,
        "p_60_89": 0.50,
        "p_90_or_more": 0.30,
        "p_play": 0.90,
    }


@pytest.mark.parametrize("target", [0.0, 30.0, 45.0, 60.0, 75.0, 90.0])
def test_minute_tilt_hits_requested_mean(target: float) -> None:
    result = minute_tilt_probabilities((0.1, 0.1, 0.5, 0.3), target)

    assert sum(result) == pytest.approx(1.0)
    assert np.dot(result, [0.0, 28.0, 75.0, 90.0]) == pytest.approx(target)


def test_counterfactual_zero_minutes_means_dnp_and_zero_points() -> None:
    result = counterfactual_player_forecast(_row(), 0.0)

    assert result["p_dnp"] == 1.0
    assert result["p_play"] == 0.0
    assert result["expected_points"] == 0.0


def test_compact_forecast_drops_non_json_source_types() -> None:
    source = {**counterfactual_player_forecast(_row(), 60.0), "source_price": Decimal("8.0")}

    compact = compact_counterfactual_forecast(source)

    json.dumps(compact)
    assert "source_price" not in compact


def test_world_counterfactual_is_deterministic_and_monotone_in_appearances() -> None:
    points = np.full((2_000, 1, 1), 5, dtype=np.int16)
    played = np.ones_like(points, dtype=bool)
    row = {**_row(), "p_dnp": 0.0, "p_play": 1.0}

    low = apply_player_minutes_counterfactual(points, played, [10], row, 30.0, seed=7)
    high = apply_player_minutes_counterfactual(points, played, [10], row, 75.0, seed=7)
    repeated = apply_player_minutes_counterfactual(points, played, [10], row, 30.0, seed=7)

    assert np.array_equal(low[0], repeated[0])
    assert np.array_equal(low[1], repeated[1])
    assert low[1].sum() <= high[1].sum()
    assert np.all(low[0][~low[1]] == 0)


def test_attention_selection_uses_evidence_not_names() -> None:
    by_player = {
        1: {1: {**_row(), "element": 1, "live_participation_consensus": "source_disagreement"}},
        2: {
            1: {
                **_row(),
                "element": 2,
                "p_dnp": 0.02,
                "p_1_59": 0.01,
                "p_60_89": 0.10,
                "p_90_or_more": 0.87,
                "p_play": 0.98,
                "live_participation_consensus": "predicted_start_consensus",
                "live_role_minutes_ratio": 1.0,
            }
        },
        3: {
            1: {
                **_row(),
                "element": 3,
                "live_participation_consensus": "predicted_start_consensus",
                "live_role_minutes_ratio": 1.4,
            }
        },
    }

    assert select_attention_players([1, 2, 3], by_player, {1: "other", 2: "other", 3: "other"}) == [
        1,
        3,
    ]


def _boundary_point(minutes: float, *, supported: bool, anchor: bool = False) -> dict:
    return {
        "target_expected_minutes": minutes,
        "is_production_anchor": anchor,
        "deep_squad_replay": (
            {
                "cross_family_holdout_support": True,
                "challenger_squad_id": "challenger",
                "incumbent_squad_id": "incumbent",
            }
            if supported
            else None
        ),
    }


def test_boundary_is_actionable_only_when_deterioration_causes_reversal() -> None:
    boundary = summarize_player_boundary(
        [
            _boundary_point(0.0, supported=True),
            _boundary_point(45.0, supported=True),
            _boundary_point(60.0, supported=False),
            _boundary_point(70.0, supported=False, anchor=True),
            _boundary_point(90.0, supported=False),
        ]
    )

    assert boundary["classification"] == "challenger_boundary_bracketed"
    assert boundary["actionable"] is True
    assert boundary["highest_supported_challenger_minutes"] == 45.0
    assert boundary["next_tested_incumbent_minutes"] == 60.0


def test_challenger_at_live_anchor_is_not_mislabelled_as_minute_trigger() -> None:
    boundary = summarize_player_boundary(
        [
            _boundary_point(0.0, supported=True),
            _boundary_point(60.0, supported=True),
            _boundary_point(70.0, supported=True, anchor=True),
            _boundary_point(90.0, supported=True),
        ]
    )

    assert boundary["classification"] == "general_gw1_challenger_at_production_anchor"
    assert boundary["actionable"] is False
    assert boundary["highest_supported_challenger_minutes"] is None
