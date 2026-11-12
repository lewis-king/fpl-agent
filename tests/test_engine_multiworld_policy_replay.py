from dataclasses import replace

import pytest
from test_engine_sequential_policy_replay import _calibration, _coefficients, _inputs, _shape
from test_engine_weekly_configuration import EVENTS, WEIGHTS, _setup
from test_engine_weekly_simulation import _rules

from fplagent_engine import multiworld_policy_replay as replay
from fplagent_engine import sequential_policy_replay, weekly_continuation_replay


def test_risk_setting_controls_both_configuration_and_route_selection():
    state, rows, rules, actions, _, worlds = _setup()
    winner, audit, _ = replay.configured_choice(actions, state, rows, rules, worlds, worlds,
                                                EVENTS, 0.1, {})
    assert winner.action_id == actions[0].action_id
    assert audit["route_risk"] == audit["configuration_risk"] == .1
    assert audit["configuration_accepted"]
    assert audit["configured_gate"]["holdout_reselection"] is False


def test_holdout_cannot_select_its_own_winner(monkeypatch):
    _, rows, _, actions, _, worlds = _setup()
    calls = []

    def choose(*args):
        calls.append(1)
        return {"selected_action_id": actions[0].action_id if len(calls) == 1 else "unseen-winner",
                "selection_audit": {"gates_by_action": {actions[0].action_id: {"passed": True}}}}

    monkeypatch.setattr(replay, "choose", choose)
    winner, audit = replay.freeze_and_validate(actions, worlds, worlds, rows, EVENTS, .25)
    assert winner.action_id == actions[0].action_id
    assert not audit["holdout_reselection"]


def test_seven_arms_have_separate_legal_state_and_account_for_hits(monkeypatch):
    monkeypatch.setattr(replay, "_historical_rules", lambda s: _rules())
    monkeypatch.setattr(weekly_continuation_replay, "_historical_rules", lambda s: _rules())
    monkeypatch.setattr(replay, "prefix_coefficients", lambda *a: (_coefficients(), ["2023-24"]))

    class Prefix:
        def __init__(self):
            self.terminal_curve = {i: i * 1.5 for i in range(6)}
            self.shapes = _shape()
            self.provenance = {"test": True}

        @staticmethod
        def fit(*args):
            return Prefix()

        @staticmethod
        def prepare(inputs, rows, fixtures, origin):
            return rows, {}, {}, {"origin_event": origin}

        @staticmethod
        def sample(rows, fixtures, components, goals, *, events, samples, seed):
            world = sequential_policy_replay.deadline_world(rows, [], _calibration(),
                                                             events=events, samples=samples, seed=seed)
            return {name: dict(world) for name in WEIGHTS}, {}

    monkeypatch.setattr(replay, "PrefixWorlds", Prefix)
    result = replay.season_replay(_inputs(), [], "2024-25",
                                  replay.SequentialConfig(end_event=3, horizon=2, samples=1000),
                                  lambda r: None)
    assert set(result["paths"]) == set(replay.ARMS)
    initial = result["paths"]["baseline"]["events"][0]
    for path in result["paths"].values():
        assert path["events"][0] == initial
        assert path["net_points"] == sum(r["gross_points"] - r["points_cost"] for r in path["events"])
        for before, after in zip(path["events"], path["events"][1:]):
            assert before["free_transfers_after"] == after["free_transfers_before"]
            assert after["points_cost"] == 4 * max(0, len(after["transfers"]) - after["free_transfers_before"])
            assert after["bank_after"] >= 0
            assert len(set(after["selected"])) == 15


def test_unsupported_decay_and_existing_receipt_fail_closed(tmp_path):
    output = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="decay"):
        replay.run_replay(output, replace(replay.SequentialConfig(), decay=.5))
    output.write_text("original")
    with pytest.raises(FileExistsError):
        replay.run_replay(output)
    assert output.read_text() == "original"
