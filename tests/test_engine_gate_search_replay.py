from dataclasses import replace

import numpy as np
from test_engine_weekly_configuration import EVENTS, WEIGHTS, _setup

from fplagent_engine import gate_search_replay as replay
from fplagent_engine.sequential_policy_replay import SequentialConfig


def test_mean_gate_does_not_veto_positive_after_cost_gain_for_one_negative_world():
    _, rows, _, actions, _, _ = _setup()
    action = replace(actions[0], action_id="transfer", route_type="free_transfer")
    actions = [actions[0], action]
    totals = {name: np.column_stack([np.zeros(100), np.full(100, 1 if name != "component_raw" else -2)])
              for name in WEIGHTS}
    audit = replay.mean_gate(actions, totals, 1, rows, EVENTS[0])
    assert audit["passed"]
    assert audit["weighted_gain"] > .8
    assert audit["world_gains"]["component_raw"] == -2


def test_incoming_role_risk_cannot_be_relaxed(monkeypatch):
    _, rows, _, actions, _, _ = _setup()
    totals = {name: np.zeros((100, 1)) for name in WEIGHTS}
    monkeypatch.setattr(replay, "selected_incoming_role_risks", lambda *a: ["unavailable"])
    assert not replay.mean_gate(actions, totals, 0, rows, EVENTS[0])["passed"]


def test_broader_candidate_search_is_a_superset_and_protects_premium_sales():
    state, rows, rules, _, _, _ = _setup()
    config = SequentialConfig(end_event=3, samples=1000)
    curve = {i: 1.5 * i for i in range(6)}
    narrow, _ = replay.search(state, rows, rules, EVENTS, config, curve)
    broad, _ = replay.broad_search(state, rows, rules, EVENTS, config, curve)
    assert {a.action_id for a in narrow} <= {a.action_id for a in broad}
    assert len(broad) > len(narrow)
    assert sum(a.route_type == "roll" for a in broad) == 1


def test_frozen_mean_choice_rejects_without_picking_holdout_winner(monkeypatch):
    _, rows, _, actions, _, _ = _setup()
    actions = [actions[0], replace(actions[0], action_id="a", route_type="free_transfer"),
               replace(actions[0], action_id="b", route_type="free_transfer")]
    worlds = iter([{n: np.tile([0., 2., 1.], (100, 1)) for n in WEIGHTS},
                   {n: np.tile([0., -1., 5.], (100, 1)) for n in WEIGHTS}])
    monkeypatch.setattr(replay, "score_configurations", lambda *a, **k: ({}, next(worlds)))
    winner, audit = replay.freeze_mean(actions, None, None, rows, EVENTS)
    assert audit["frozen_selection"] == "a"
    assert not audit["holdout_reselection"]
    assert winner.route_type == "roll"
