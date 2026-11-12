from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest
from test_engine_horizon_decay_replay import _coefficients
from test_engine_weekly_continuation_replay import _inputs
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine import sequential_policy_replay as replay
from fplagent_engine import tournament, weekly_continuation_replay
from fplagent_engine.score_shape import SCORES


def _calibration():
    return tournament.ResidualCalibration(
        global_shocks=np.zeros((1, 4), dtype=np.float32),
        fixture_shocks=np.zeros((1, 2, 4), dtype=np.float32),
        residual_pools={(p, b): np.array([-1, 0, 1], dtype=np.float32)
                        for p in tournament.POSITIONS for b in range(5)},
        bin_edges={p: np.array([2., 3., 4., 5.]) for p in tournament.POSITIONS},
        residual_sd={(p, b): 1.0 for p in tournament.POSITIONS for b in range(5)},
        play_rho=0.1, points_rho=0.0, rows=1000, played_rows=900, fixtures=100,
        global_sd=0.0, fixture_sd=0.0, idiosyncratic_sd=1.0,
    )


def _shape():
    return {"trained_before": "2024-25", "positions": {
        p: {"probabilities": np.full(len(SCORES), 1 / len(SCORES)).tolist()}
        for p in tournament.POSITIONS}}


def test_prefix_fit_never_consumes_evaluation_seasons(monkeypatch):
    inputs = _inputs()
    seen = {}

    def residual(*, rows, fixture_rows):
        seen["rows"] = {r["season"] for r in rows}
        seen["fixtures"] = {r["season"] for r in fixture_rows}
        return _calibration()

    def shapes(rows, *, before_season):
        assert before_season == "2024-25"
        seen["shapes"] = {r["season"] for r in rows}
        return _shape()

    monkeypatch.setattr(replay, "calibrate_residuals", residual)
    monkeypatch.setattr(replay, "fit_shapes", shapes)
    replay.fit_prefix(inputs, "2024-25", [{"season": s} for s in inputs["available_snapshots"]])
    assert seen == {"rows": {"2023-24"}, "fixtures": {"2023-24"}, "shapes": {"2023-24"}}


def test_explicit_fixtures_do_not_load_live_fixture_feed(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Historical simulation attempted live fixture read")

    monkeypatch.setattr(tournament, "_current_fixture_map", forbidden)
    rows = replay.origin_simulation_rows([dict(r, fixture_count=1) for r in _rows()])
    world = replay.deadline_world(rows, [], _calibration(), events=(2, 3), samples=50, seed=11)
    repeated = replay.deadline_world(rows, [], _calibration(), events=(2, 3), samples=50, seed=11)
    np.testing.assert_array_equal(world["points"], repeated["points"])
    np.testing.assert_array_equal(world["played"], repeated["played"])


def test_blanks_conditional_means_and_labels():
    source = [dict(r, fixture_count=1, conditional_points_if_playing=999) for r in _rows()]
    source[0]["fixture_count"] = 0
    before = deepcopy(source)
    rows = replay.origin_simulation_rows(source)
    assert source == before
    assert rows[0]["p_play"] == rows[0]["expected_points"] == 0
    for row in rows[1:]:
        assert row["conditional_points_if_playing"] * row["p_play"] == pytest.approx(row["expected_points"])
    with pytest.raises(ValueError, match="labels"):
        replay.origin_simulation_rows([dict(source[0], target_points=5)])
    with pytest.raises(ValueError, match="Double"):
        replay.origin_simulation_rows([dict(source[0], fixture_count=2)])


def test_four_paths_carry_state_and_only_execute_first_action(monkeypatch):
    monkeypatch.setattr(replay, "_historical_rules", lambda s: _rules())
    monkeypatch.setattr(weekly_continuation_replay, "_historical_rules", lambda s: _rules())
    monkeypatch.setattr(replay, "prefix_coefficients", lambda *a: (_coefficients(), ["2023-24"]))
    monkeypatch.setattr(replay, "fit_prefix", lambda *a: (_calibration(), _shape()))
    result = replay.paired_season(_inputs(), [], "2024-25",
                                  replay.SequentialConfig(end_event=3, horizon=2, samples=1000))
    assert set(result["paths"]) == set(replay.ARMS)
    initial = result["paths"]["baseline"]["events"][0]
    for path in result["paths"].values():
        assert path["events"][0] == initial
        assert path["net_points"] == sum(r["gross_points"] - r["points_cost"] for r in path["events"])
        for before, after in zip(path["events"], path["events"][1:]):
            assert before["free_transfers_after"] == after["free_transfers_before"]
            assert after["points_cost"] == 4 * max(0, len(after["transfers"]) - after["free_transfers_before"])
            assert len(after["selected"]) == len(set(after["selected"])) == 15
            assert after["bank_after"] >= 0
    assert set(result["terminal_curve"].values()) == {0}


def test_capital_search_protects_two_largest_outfield_sale_values():
    state = _state()
    config = replay.SequentialConfig(horizon=2)
    curve = {i: 0 for i in range(6)}
    actions, _ = replay.search(state, _rows(), _rules(), (2, 3), config, curve)
    expanded, audit = replay.expanded_candidates(state, actions, _rows(), _rules(),
                                                 (2, 3), config, curve)
    expected = sorted((h for h in state.squad if h.position != "GK"),
                      key=lambda h: (-h.selling_price, h.player_id))[:2]
    assert [r["required_sale"] for r in audit] == [h.player_id for h in expected]
    assert {a.action_id for a in actions} <= {a.action_id for a in expanded}
    assert sum(a.route_type == "roll" for a in expanded) == 1


def test_validation_cannot_promote_its_own_winner(monkeypatch):
    actions, _ = replay.search(_state(), _rows(), _rules(), (2, 3),
                               replay.SequentialConfig(horizon=2), {i: 0 for i in range(6)})
    roll = next(a for a in actions if a.route_type == "roll")
    move = next(a for a in actions if a.action.transfers)
    calls = []

    def synthesize(*args, **kwargs):
        calls.append(1)
        return {"selected_action_id": roll.action_id if len(calls) == 1 else move.action_id,
                "selection_audit": {"gates_by_action": {a.action_id: {"passed": True} for a in actions}}}

    monkeypatch.setattr(replay, "synthesize_weekly_decision", synthesize)
    rows = replay.origin_simulation_rows([dict(r, fixture_count=1) for r in _rows()])
    world = replay.deadline_world(rows, [], _calibration(), events=(2, 3), samples=50, seed=11)
    winner, audit = replay.select_frozen(actions, world, world, rows, (2, 3), 0.88)
    assert winner.action_id == roll.action_id
    assert audit["selection_choice"] == roll.action_id


@pytest.mark.parametrize("changes", [{"samples": 5}, {"end_event": 38},
                                     {"solver_seconds": float("nan")}, {"seed": -1}])
def test_unsupported_experiments_rejected(changes):
    with pytest.raises(ValueError):
        replace(replay.SequentialConfig(), **changes).validate()


def test_receipt_cannot_overwrite_existing_experiment(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text("original")
    with pytest.raises(FileExistsError):
        replay.run_replay(path)
    assert path.read_text() == "original"
