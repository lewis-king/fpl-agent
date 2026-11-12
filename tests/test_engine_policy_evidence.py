from copy import deepcopy

import pytest

from fplagent_engine.policy_evidence import summarize_policy_evidence


def _score(event):
    return {"event": event, "allocation_scores": {"comparisons": [
        {"pool": "original", "status": "scored_shadow", "worst_case_weight": w,
         "action_id": "base" if w == 0.25 else "other", "realized_net_points": value}
        for w, value in ((0, 60), (0.1, 60), (0.25, 55), (0.5, 53))
    ]}, "challenger_policy_scores": {"shared_world_continuation": {
        "status": "scored_shadow", "realized_delta_to_champion": -2, "action_id": "plan",
    }}}


def test_all_risk_weights_use_matched_events_and_no_automatic_promotion():
    good, incomplete = _score(4), _score(5)
    incomplete["allocation_scores"]["comparisons"].pop()
    out = summarize_policy_evidence([good, incomplete])
    assert out["risk"]["matched_events"] == [4]
    assert out["risk"]["total_paired_delta"]["0.0"] == 5
    assert out["continuation"]["shared_world_continuation"]["total_paired_delta"] == -4
    assert not out["decision_authority"]
    assert out["promotion"] == "retain_current_policy"


def test_expanded_search_is_not_mixed_with_objective_ablation():
    original = _score(4)
    expanded = deepcopy(original["allocation_scores"]["comparisons"])
    for r in expanded:
        r.update(pool="expanded_research", realized_net_points=999)
    original["allocation_scores"]["comparisons"].extend(expanded)
    assert summarize_policy_evidence([original])["risk"]["total_paired_delta"]["0.0"] == 5


def test_cannot_count_multiple_deadline_runs_as_independent_games():
    with pytest.raises(ValueError, match="one pre-deadline"):
        summarize_policy_evidence([_score(4), _score(4)])
    assert summarize_policy_evidence([])["risk"]["matched_events"] == []
