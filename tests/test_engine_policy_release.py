import pytest

from fplagent_engine.policy_release import DECISIONS, attach_policy_release


def test_every_experiment_has_a_concluded_deployment_decision():
    assert len({d["key"] for d in DECISIONS}) == len(DECISIONS)
    assert {d["decision"] for d in DECISIONS} == {"promote", "reject"}
    assert all(d["basis"] and d["reason"] for d in DECISIONS)


def test_rejected_measurements_are_retained_without_changing_the_recommendation():
    result = {"selected_action_id": "ordinary", "diagnostics": {
        "role_shift_research": {"status": "ready_diagnostic", "decision_authority": False,
                                "players": [1, 2]},
        "stateful_policy_research": {"status": "incomplete_diagnostic", "decision_authority": False},
    }, "chip_strategy": {"operational_recommendation": "bench_boost"}}
    attach_policy_release(result)
    assert result["selected_action_id"] == "ordinary"
    assert result["diagnostics"]["role_shift_research"]["players"] == [1, 2]
    for diagnostic in result["diagnostics"].values():
        assert diagnostic["deployment_review"]["decision"] == "reject"
        assert diagnostic["decision_authority"] is False
    original = DECISIONS[0]["decision"]
    result["policy_release"]["decisions"][0]["decision"] = "corrupted"
    assert DECISIONS[0]["decision"] == original


@pytest.mark.parametrize("key", ["transfer_continuation", "stateful_policy_research",
                                 "role_shift_research", "allocation_research",
                                 "exact_chip_opportunities", "score_shape_policy",
                                 "scout_private_benchmark", "gate_search_policy"])
@pytest.mark.parametrize("authority", [True, None, "false"])
def test_rejected_experiments_cannot_self_promote(key, authority):
    result = {"diagnostics": {key: {"decision_authority": authority}}}
    with pytest.raises(ValueError, match="cannot acquire decision authority"):
        attach_policy_release(result)


@pytest.mark.parametrize("chip", ["wildcard", "free_hit"])
def test_unapproved_joint_chip_policy_cannot_spend_inventory(chip):
    with pytest.raises(ValueError, match="timing or expiry authority"):
        attach_policy_release({"chip_strategy": {"operational_recommendation": chip}})


def test_wildcard_needs_a_play_now_timing_verdict():
    later = {"operational_recommendation": "wildcard",
             "squad_timing": {"verdict": {"play_now": False, "best_wildcard_event": 12}}}
    with pytest.raises(ValueError, match="timing or expiry authority"):
        attach_policy_release({"chip_strategy": later})
    now = {"operational_recommendation": "wildcard",
           "squad_timing": {"verdict": {"play_now": True, "best_wildcard_event": 10}}}
    attach_policy_release({"chip_strategy": now})


@pytest.mark.parametrize("chip", ["wildcard", "free_hit"])
def test_expiry_guarantee_authorises_any_squad_chip(chip):
    result = {"chip_strategy": {"operational_recommendation": chip, "expiry_forced": True}}
    attach_policy_release(result)
    assert result["chip_strategy"]["operational_recommendation"] == chip


def test_free_hit_is_authorised_by_its_calendar_gates():
    strategy = {"operational_recommendation": "free_hit",
                "policy": {"free_hit_timing": "joint calendar and uncertainty gates"}}
    attach_policy_release({"chip_strategy": strategy})


def test_calendar_correctness_is_distinct_from_new_timing_authority():
    decisions = {d["key"]: d for d in DECISIONS}
    assert decisions["chip_calendar_constraints"]["decision"] == "promote"
    for key in ("exact_chip_opportunities", "joint_wildcard_free_hit"):
        assert decisions[key]["decision"] == "reject"
    result = {"selected_action_id": "unchanged", "diagnostics": {
        "exact_chip_opportunities": {"decision_authority": False,
                                     "opportunities": [{"projected_uplift": 12.0}]}},
        "chip_strategy": {"operational_recommendation": None}}
    attach_policy_release(result)
    assert result["selected_action_id"] == "unchanged"
    assert result["chip_strategy"]["operational_recommendation"] is None
    assert result["diagnostics"]["exact_chip_opportunities"]["opportunities"]
