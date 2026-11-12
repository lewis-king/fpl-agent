import json

import pytest
from test_engine_prospective_scoring import _decision, _paths

from fplagent_engine.prospective_scoring import (
    _shadow_policy_choices,
    score_allocation_diagnostic,
    score_role_shift_diagnostic,
    score_weekly_event,
)


def test_new_first_action_and_risk_hypotheses_are_scored_without_future_claims(tmp_path):
    outcome_root, pointer_root, result_root, report_root = _paths(tmp_path)
    decision = _decision()
    decision["diagnostics"] = {
        "stateful_policy_research": {
            "complete_requested_roots": True,
            "same_production_worlds": True,
            "ordinary_continuation": {"selected_first_action_id": "roll"},
        },
        "allocation_research": {
            "complete_requested_families": True,
            "risk_weight_sensitivity": [
                {"pool": "original", "worst_case_weight": 0.0, "selected_action_id": "roll"}
            ],
        },
    }
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(decision))
    result = score_weekly_event(
        2,
        decision_path=path,
        outcome_root=outcome_root,
        outcome_pointer_root=pointer_root,
        result_root=result_root,
        report_root=report_root,
    )
    assert (
        result["challenger_policy_scores"]["shared_world_continuation"]["scope"]
        == "first_action_only"
    )
    assert result["challenger_policy_scores"]["risk_weight_0"]["realized_delta_to_champion"] < 0
    assert result["allocation_scores"]["comparisons"][0]["realized_delta_to_champion"] < 0
    assert result["role_shift_scores"]["status"] == "not_frozen"


def test_role_probabilities_use_frozen_supported_players_only():
    players = [
        {
            "player_id": p,
            "champion_p_play": 0.9,
            "challenger_p_play": 0.5,
            "forecast_status": "scorable_single_fixture" if p != 3 else "unsupported_fixture_count",
            "signal": {"loss_of_regular_role": int(p == 1)},
        }
        for p in (1, 2, 3)
    ]
    decision = {
        "diagnostics": {
            "role_shift_research": {
                "status": "ready_diagnostic",
                "players": players,
                "model_sha256": "frozen",
            }
        }
    }
    result = score_role_shift_diagnostic(decision, {1: {"minutes": 0}, 3: {"minutes": 90}})
    assert result["missing_outcome_player_ids"] == [2]
    assert result["unsupported_player_ids"] == [3]
    assert result["cohorts"]["all_supported"]["champion"]["brier"] == pytest.approx(0.81)
    assert result["cohorts"]["all_supported"]["role_shift"]["brier"] == 0.25
    assert not result["decision_authority"]


def test_incomplete_extra_search_does_not_discard_complete_original_risk_grid():
    decision = {"diagnostics": {"allocation_research": {
        "version": "allocation_research_v2", "original_pool_complete": True,
        "complete_requested_families": False, "risk_weight_sensitivity": [
            {"pool": pool, "worst_case_weight": 0., "selected_action_id": "roll"}
            for pool in ("original", "expanded_research")
        ],
    }}}
    assert "risk_weight_0" in _shadow_policy_choices(decision)
    result = score_allocation_diagnostic(
        decision, {"roll": {"realized_decision_net_points": 50}},
        event=4, meta={}, live_by_player={}, champion_net=45,
    )
    assert result["comparisons"][0]["realized_delta_to_champion"] == 5
    assert result["comparisons"][1]["status"] == "incomplete_expanded_search"
    # Old v1 receipts retain their original interpretation/immutable scores.
    decision["diagnostics"]["allocation_research"].pop("original_pool_complete")
    assert "risk_weight_0" not in _shadow_policy_choices(decision)
