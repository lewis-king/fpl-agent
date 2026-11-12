from dataclasses import replace

import pytest
from test_engine_weekly_policy_research import _worlds
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.allocation_research import (
    policy_identity,
    run_allocation_research,
    subset_metrics,
)
from fplagent_engine.weekly_actions import generate_weekly_actions
from fplagent_engine.weekly_simulation import evaluate_action_paths


def test_constraints_produce_legal_premium_and_bench_budget_alternatives():
    rows = _rows()
    actions = generate_weekly_actions(
        _state(),
        rows,
        _rules(),
        events=(2, 3),
        max_total_transfers=2,
        alternatives_per_transfer_count=1,
        required_player_ids=(18,),
        bench_cost_cap=200,
    )
    assert actions
    for a in actions:
        assert 18 in a.selected_player_ids
        prices = {r["element"]: r["market_price"] for r in rows}
        assert sum(prices[p] for p in a.action.lineup.bench_order) <= 200
    impossible = generate_weekly_actions(
        _state(),
        rows,
        _rules(),
        events=(2, 3),
        required_player_ids=(999,),
    )
    assert not impossible


def test_comparison_has_all_worlds_and_explicit_infeasible_cases():
    rows = _rows()
    actions = generate_weekly_actions(_state(), rows, _rules(), events=(2, 3))
    result = run_allocation_research(
        _state(),
        actions,
        rows,
        _rules(),
        _worlds(rows),
        {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        events=(2, 3),
        selected_id=actions[0].action_id,
    )
    assert result["complete_requested_families"]
    assert not result["decision_authority"]
    assert len(result["risk_weight_sensitivity"]) == 8
    assert next(f for f in result["families"] if f["family"] == "bench_cap_16")["status"] == "infeasible_within_two_transfers"
    assert len(result["capital_release_targets"]) == 2
    assert all(result["families"][i]["family"].startswith("sell_reinvest_") for i in (0, 1))
    assert any(
        f["family"].startswith("premium_fwd") and f["status"] == "feasible"
        for f in result["families"]
    )
    assert all(r["current_bench_cost"] >= 20 for r in result["actions"])


def test_original_risk_regret_is_rebased_after_pool_expansion():
    rows = _rows()
    actions = generate_weekly_actions(_state(), rows, _rules(), events=(2, 3))
    metrics, _ = evaluate_action_paths(actions, events=(2, 3), **_worlds(rows)["residual"])
    baseline = subset_metrics(
        {"a": [replace(m, scenario_regret=m.scenario_regret + 10) for m in metrics]},
        {a.action_id for a in actions},
    )
    assert [m.scenario_regret for m in baseline["a"]] == pytest.approx(
        [m.scenario_regret for m in metrics]
    )


def test_vice_captain_affects_policy_identity_and_budget_is_not_infeasibility():
    actions = generate_weekly_actions(_state(), _rows(), _rules(), events=(2, 3))
    a = actions[0]
    first = a.lineups[0]
    changed = replace(
        a, lineups=(replace(first, lineup=replace(first.lineup, vice_captain=999)), *a.lineups[1:])
    )
    assert policy_identity(a) != policy_identity(changed)
    result = run_allocation_research(
        _state(),
        actions,
        _rows(),
        _rules(),
        _worlds(_rows()),
        {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        events=(2, 3),
        selected_id=a.action_id,
        seconds=0,
    )
    assert not result["complete_requested_families"]
    assert result["status"] == "incomplete_search"
    assert all(f["status"] == "budget_exhausted" for f in result["families"])


def test_joint_sale_reinvest_uses_selling_value_and_keeps_required_sale():
    state = _state(free_transfers=2, bank=0)
    # A price rise is not all spendable: sale proceeds are deliberately below
    # market value. Selling the premium funds a separate-position improvement.
    state = replace(state, squad=tuple(
        replace(h, purchase_price=80, current_price=120, selling_price=100)
        if h.player_id == 13 else h for h in state.squad
    ))
    rows = [dict(r, market_price=120) if r["element"] == 13 else r for r in _rows()]
    trace = []
    actions = generate_weekly_actions(
        state, rows, _rules(), events=(2, 3), alternatives_per_transfer_count=1,
        max_total_transfers=2, max_paid_transfers=0, protect_role_sale_routes=False,
        required_outgoing_player_ids=(13,), search_diagnostics=trace,
    )
    assert actions and all(13 not in a.selected_player_ids for a in actions)
    assert trace[0]["status"] == "infeasible"  # cannot roll and sell simultaneously
    both = next(a for a in actions if len(a.action.transfers) == 2)
    holdings = {h.player_id: h for h in state.squad}
    proceeds = sum(holdings[t.outgoing_player_id].selling_price for t in both.action.transfers)
    spending = sum(t.incoming.current_price for t in both.action.transfers)
    assert both.outcome.gameweek.bank == proceeds - spending >= 0
    assert both.incremental_points_cost == 0
    assert len({t.incoming.position for t in both.action.transfers}) == 2
    assert all(t["required_outgoing_player_ids"] == [13] for t in trace)


def test_sale_constraint_cannot_be_silently_ignored():
    for outgoing, required in [((999,), ()), ((13,), (13,))]:
        with pytest.raises(ValueError):
            generate_weekly_actions(
                _state(), _rows(), _rules(), events=(2, 3),
                required_outgoing_player_ids=outgoing, required_player_ids=required,
            )


def test_zero_free_transfers_still_examines_joint_two_hit_reinvestment():
    rows = _rows()
    state = _state(free_transfers=0)
    actions = generate_weekly_actions(state, rows, _rules(), events=(2, 3))
    result = run_allocation_research(
        state, actions, rows, _rules(), _worlds(rows),
        {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        events=(2, 3), selected_id=actions[0].action_id,
    )
    for family in result["families"][:2]:
        assert {a["transfer_count"] for a in family["attempts"]} == {0, 1, 2}
    assert result["original_pool_complete"] is True
    assert result["transfer_bounds"]["max_paid_transfers"] == 2
