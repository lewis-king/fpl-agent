from itertools import product
from pathlib import Path

import numpy as np
import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.season_state import apply_action
from fplagent_engine.weekly_actions import generate_weekly_actions
from fplagent_engine.weekly_deep_search import (
    MAX_HOLDOUT_REGRET,
    SELECTION_SEEDS,
    VALIDATION_SEEDS,
    configured_action,
    joint_configuration,
    validation_gate,
)


@pytest.mark.parametrize("risk", [0.0, 0.1, 0.25, 0.5, 1.0])
def test_joint_configuration_solves_full_cartesian_horizon_not_greedy(risk):
    # Match live execution order: HiGHS' global scheduler is initialised by
    # roster search before this joint configuration problem. Changing its
    # thread count mid-process leaves a new solve in kNotset.
    generate_weekly_actions(_state(), _rows(), _rules(), events=(2, 3))
    rng = np.random.default_rng(72)
    frontiers = [{"means": rng.random((4, 3)) * 10} for _ in range(3)]
    weights = [0.5, 0.45, 0.05]
    constant = -4
    reference = sum(0.88**e * f["means"].max(axis=0) for e, f in enumerate(frontiers)) + constant

    def objective(choices):
        gains = (
            sum(
                0.88**e * f["means"][choice]
                for e, (f, choice) in enumerate(zip(frontiers, choices, strict=True))
            )
            + constant
        )
        regrets = reference - gains
        return (1 - risk) * np.dot(weights, regrets) + risk * regrets.max()

    chosen = joint_configuration(frontiers, weights=weights, reference=reference, constant=constant,
                                 worst_case_weight=risk)
    assert objective(chosen) == pytest.approx(
        min(objective(c) for c in product(range(4), repeat=3))
    )


def test_configuration_preserves_exact_legal_transfer_state():
    state, rules, rows = _state(), _rules(), _rows()
    root = generate_weekly_actions(state, rows, rules, events=(2, 3))[0]
    fs = [
        {
            "configurations": [
                (l.lineup.starters, l.lineup.bench_order, l.lineup.captain, l.lineup.vice_captain)
            ]
        }
        for l in root.lineups
    ]
    result = configured_action(root, [0, 0], fs, state, rows, rules, (2, 3))
    assert result.outcome == apply_action(state, result.action, rules)
    assert result.outcome == root.outcome
    assert result.incremental_points_cost == root.incremental_points_cost
    assert result.gross_horizon_utility == pytest.approx(root.gross_horizon_utility)
    assert result.decision_utility == pytest.approx(root.decision_utility)


def test_validation_seeds_are_disjoint_and_not_tuned():
    seeds = [*SELECTION_SEEDS, *(s for pair in VALIDATION_SEEDS for s in pair)]
    assert len(seeds) == len(set(seeds)) == 6
    assert MAX_HOLDOUT_REGRET == 0.05


def test_research_goal_rates_match_production_without_overwriting_artifact(monkeypatch):
    import pyarrow as pa

    from fplagent_engine import component_simulator as module

    monkeypatch.setattr(module, "GOAL_MODEL_FILE", Path(__file__))
    monkeypatch.setattr(
        module.joblib,
        "load",
        lambda _: {"model": object(), "medians": np.zeros(1), "score_correlation": 0.05},
    )
    monkeypatch.setattr(module, "_goal_feature_vector", lambda row, home: [float(home)])
    monkeypatch.setattr(module, "xgboost_infer", lambda *args: np.array([1.5, 0.9]))
    monkeypatch.setattr(
        module.pq,
        "read_table",
        lambda _: pa.Table.from_pylist([{"id": 1, "event": 4, "team_h": 1, "team_a": 2}]),
    )
    writes = []
    monkeypatch.setattr(module.pq, "write_table", lambda *a, **kw: writes.append(a))
    rows = {1: {4: {"team_id": 1}}, 2: {4: {"team_id": 2}}}
    read_only = module.predict_current_goal_rates(rows, (4,), persist=False)
    assert writes == []
    production = module.predict_current_goal_rates(rows, (4,))
    assert len(writes) == 1
    assert production == read_only


@pytest.mark.parametrize(
    "world_loss,selected_gap,expected", [(0, 0, True), (-0.1, 0, False), (0, 0.1, False)]
)
def test_holdout_can_reject_but_never_reselect(monkeypatch, world_loss, selected_gap, expected):
    import fplagent_engine.weekly_decision as module

    actions = generate_weekly_actions(_state(), _rows(), _rules(), events=(2, 3))[:2]
    incumbent, frozen = [a.action_id for a in actions]
    monkeypatch.setattr(
        module,
        "synthesize_weekly_decision",
        lambda *a, **kw: {
            "selected_action_id": "a-different-holdout-winner",
            "admissible_ranking": [
                {"action_id": "a-different-holdout-winner", "robust_regret": 0},
                {"action_id": frozen, "robust_regret": selected_gap},
            ],
        },
    )
    totals = {
        name: np.column_stack((np.zeros(100), np.full(100, gain)))
        for name, gain in (("a", 2), ("b", 2), ("c", world_loss))
    }
    result = validation_gate(
        {"event_rows": {}},
        actions,
        {},
        totals,
        weights={"a": 0.5, "b": 0.45, "c": 0.05},
        incumbent_id=incumbent,
        selected_id=frozen,
    )
    assert result["passed"] == expected
    assert result["frozen_selection"] == frozen
