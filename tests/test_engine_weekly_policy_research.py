from dataclasses import replace

import numpy as np
import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.season_state import ChipType
from fplagent_engine.weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from fplagent_engine.weekly_policy_research import (
    build_policy_plans,
    compose_plan,
    guard_future_transfers,
    score_policy_plans,
)
from fplagent_engine.weekly_simulation import evaluate_action_paths


def _setup():
    rows = _rows()
    state = _state()
    actions = generate_weekly_actions(
        state,
        rows,
        _rules(),
        events=(2, 3),
        max_total_transfers=1,
        alternatives_per_transfer_count=1,
    )
    chips = generate_squad_chip_shadow_actions(
        state, rows, _rules(), events=(2, 3), alternatives_per_chip=1
    )
    chips += generate_team_chip_shadow_actions(state, actions, rows, _rules(), events=(2, 3))
    return rows, actions, chips


def _worlds(rows, count=20):
    players = sorted({r["element"] for r in rows})
    world = {
        "player_ids": players,
        "player_meta": {r["element"]: r for r in rows},
        "points": np.full((count, 2, len(players)), 2, dtype=np.int16),
        "played": np.ones((count, 2, len(players)), dtype=bool),
    }
    return {name: world for name in ("residual", "component_anchored", "component_raw")}


def test_joint_frontier_preserves_wc_and_restores_fh_and_does_not_grant_authority():
    rows, actions, chips = _setup()
    plans, receipt = build_policy_plans(
        actions, chips, rows, _rules(), events=(2, 3), selected_id=actions[0].action_id
    )
    assert receipt["complete_requested_roots"]
    assert not receipt["decision_authority"]
    roots = {a.action_id: a for a in (*actions, *chips)}
    by_id = {p.action_id: p for p in plans}
    assert any(
        b["current_chip"] == "wildcard" and b["next_chip"] == "bench_boost"
        for b in receipt["branches"]
    )
    for b in receipt["branches"]:
        root = roots[b["root_action_id"]]
        plan = by_id[b["plan_id"]]
        assert b["next_free_transfers_before"] == root.outcome.next_manager.free_transfers
        assert b["next_bank_before"] == root.outcome.next_manager.bank
        if b["current_chip"] == "free_hit":
            assert {h.player_id for h in root.outcome.next_manager.squad} == {
                h.player_id for h in _state().squad
            }
            assert b["next_chip"] != "free_hit"
        if b["current_chip"]:
            assert b["next_chip"] != b["current_chip"]
        assert dict(plan.event_squads)[2] == root.selected_player_ids
    result = score_policy_plans(
        actions,
        plans,
        receipt,
        _worlds(rows),
        {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        events=(2, 3),
        selected_id=actions[0].action_id,
        event_rows={r["element"]: r for r in rows if r["event_number"] == 2},
    )
    assert result["same_production_worlds"]
    assert result["joint_chips"]["operational_recommendation"] is None
    assert not result["ordinary_continuation"]["decision_authority"]
    assert result["future_transfer_gates"]
    for root in {r["root_action_id"] for r in result["future_transfer_gates"]}:
        assert sum(r["is_hold"] for r in result["future_transfer_gates"] if r["root_action_id"] == root) == 1


def test_future_hit_requires_its_own_after_cost_gate_and_retains_root():
    rows, actions, _ = _setup()
    root = next(a for a in actions if a.route_type == "roll")
    hold = replace(root, action_id="hold", parent_action_id="root", route_type="planned_roll")
    hit = replace(hold, action_id="hit", future_points_costs=((3, 4),))
    branches = {"hold": {"no_future_transfer": True, "next_incremental_points_cost": 0},
                "hit": {"no_future_transfer": False, "next_incremental_points_cost": 4}}
    metrics = {}
    for name, world in _worlds(rows).items():
        metrics[name], _ = evaluate_action_paths([root, hold, hit], events=(2, 3), **world)
    # After-cost gain is positive in the weighted average but negative in one
    # world: a future paid move must not slip through current-action-only checks.
    totals = {"residual": np.tile([50., 52.], (20, 1)),
              "component_anchored": np.tile([50., 51.], (20, 1)),
              "component_raw": np.tile([50., 49.], (20, 1))}
    chosen, audit = guard_future_transfers(
        [hold, hit], branches, metrics, totals, {"hold": 0, "hit": 1},
        {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
    )
    assert [p.action_id for p in chosen] == ["hold"]
    failed = next(r for r in audit if r["plan_id"] == "hit")
    assert failed["weighted_delta"] > 0
    assert not failed["checks"]["paid_positive_every_world"]


def test_future_bench_boost_and_hits_are_scored_once_on_correct_event():
    rows, actions, chips = _setup()
    wc = next(a for a in chips if a.action.chip == ChipType.WILDCARD)
    future = [r for r in rows if r["event_number"] == 3]
    children = generate_weekly_actions(
        wc.outcome.next_manager, future, _rules(), events=(3,), max_total_transfers=0
    )
    child = children[0]
    bb = next(
        a
        for a in generate_team_chip_shadow_actions(
            wc.outcome.next_manager, children, future, _rules(), events=(3,)
        )
        if a.action.chip == ChipType.BENCH_BOOST
    )
    normal = compose_plan(wc, child, rows, rules=_rules())
    boosted = compose_plan(wc, bb, rows, rules=_rules())
    roll = next(a for a in actions if a.route_type == "roll")
    _, totals = evaluate_action_paths(
        [roll, normal, boosted], events=(2, 3), **_worlds(rows)["residual"]
    )
    assert np.allclose(totals[:, 2] - totals[:, 1], 0.88 * 8)
    charged = replace(normal, action_id="hit-test", future_points_costs=((3, 4),))
    _, totals = evaluate_action_paths(
        [roll, normal, charged], events=(2, 3), **_worlds(rows)["residual"]
    )
    assert np.allclose(totals[:, 1] - totals[:, 2], 0.88 * 4)


def test_future_tc_uses_future_vice_when_captain_does_not_appear():
    rows, actions, _ = _setup()
    root = next(a for a in actions if a.route_type == "roll")
    future = [r for r in rows if r["event_number"] == 3]
    children = generate_weekly_actions(
        root.outcome.next_manager, future, _rules(), events=(3,), max_total_transfers=0
    )
    tc = next(
        a
        for a in generate_team_chip_shadow_actions(
            root.outcome.next_manager, children, future, _rules(), events=(3,)
        )
        if a.action.chip == ChipType.TRIPLE_CAPTAIN
    )
    plan = compose_plan(root, tc, rows, rules=_rules())
    world = _worlds(rows)["residual"]
    cap, vc = tc.action.lineup.captain, tc.action.lineup.vice_captain
    world["played"][:, 1, world["player_ids"].index(cap)] = False
    world["points"][:, 1, world["player_ids"].index(vc)] = 7
    unboosted = replace(plan, action_id="no-tc", planned_chips=())
    _, totals = evaluate_action_paths([root, unboosted, plan], events=(2, 3), **world)
    assert np.allclose(totals[:, 2] - totals[:, 1], 0.88 * 7)


@pytest.mark.parametrize(
    "changes",
    [
        {"future_points_costs": ((2, 4),)},
        {"future_points_costs": ((3, -4),)},
        {"planned_chips": ((3, ChipType.BENCH_BOOST), (3, ChipType.TRIPLE_CAPTAIN))},
    ],
)
def test_invalid_future_scoring_contract_rejected(changes):
    rows, actions, _ = _setup()
    root = next(a for a in actions if a.route_type == "roll")
    bad = replace(root, action_id="invalid", route_type="planned", **changes)
    with pytest.raises(ValueError):
        evaluate_action_paths([root, bad], events=(2, 3), **_worlds(rows)["residual"])


def test_future_child_cannot_belong_to_another_manager_state():
    rows, actions, _ = _setup()
    root = actions[0]
    future = [r for r in rows if r["event_number"] == 3]
    state = replace(root.outcome.next_manager, bank=root.outcome.next_manager.bank + 50)
    child = generate_weekly_actions(state, future, _rules(), events=(3,), max_total_transfers=0)[0]
    with pytest.raises(ValueError, match="exact manager state"):
        compose_plan(root, child, rows, rules=_rules())


def test_half_boundary_inventory_and_consecutive_fh():
    rows = [dict(r, event_number=r["event_number"] + 17) for r in _rows()]
    state = replace(_state(), event=19)
    roots = generate_squad_chip_shadow_actions(
        state, rows, _rules(), events=(19, 20), alternatives_per_chip=1
    )
    fh = next(a for a in roots if a.action.chip == ChipType.FREE_HIT)
    future = [r for r in rows if r["event_number"] == 20]
    next_chips = generate_squad_chip_shadow_actions(
        fh.outcome.next_manager, future, _rules(), events=(20,), alternatives_per_chip=1
    )
    assert next_chips and all(c.action.chip != ChipType.FREE_HIT for c in next_chips)
    assert all(s.half == 2 for s in fh.outcome.next_manager.chips if s.status.value == "available")
