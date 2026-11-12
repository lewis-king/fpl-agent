import numpy as np
import pytest

from fplagent_engine.distribution_policy_audit import remap_score_shapes
from fplagent_engine.score_shape import SCORES


def _data():
    n = 10000
    scores = np.tile(np.arange(n)[:, None, None], (1, 1, 2)).astype(float)
    played = np.ones(scores.shape, dtype=bool)
    played[-100:, 0, 1] = False
    scores[~played] = 0
    world = {"player_ids": [1, 2], "points": scores, "played": played}
    rows = [{"season": "2026-27", "event_number": 8, "element": p,
             "fixture_count": 1, "position": "MID", "p_play": 1 if p == 1 else 0.99,
             "expected_points": 6 if p == 1 else 5.94} for p in (1, 2)]
    base = np.ones(len(SCORES))
    base[SCORES == 2] = 1000
    calibration = {"trained_before": "2026-27", "positions": {"MID": {"probabilities": base}}}
    return world, rows, calibration


def test_shape_research_preserves_paths_and_non_tied_ranks_without_mutation():
    world, rows, calibration = _data()
    before = world["points"].copy()
    new, audit = remap_score_shapes(world, rows, calibration, events=(8,), seed=1)
    assert np.array_equal(world["points"], before)
    assert np.array_equal(new["played"], world["played"])
    assert np.all(new["points"][~new["played"]] == 0)
    assert np.all(np.diff(new["points"][:, 0, 0]) >= 0)
    assert abs(new["points"][:, 0, 0].mean() - 6) < 0.01
    assert not audit["decision_authority"]


def test_doubles_are_not_remapped_with_a_single_match_distribution():
    world, rows, calibration = _data()
    rows[0]["fixture_count"] = 2
    new, audit = remap_score_shapes(world, rows, calibration, events=(8,), seed=1)
    assert np.array_equal(new["points"][:, 0, 0], world["points"][:, 0, 0])
    assert audit["skipped"][0]["reason"] == "not_single_fixture"


def test_future_training_and_outcome_leakage_rejected():
    world, rows, calibration = _data()
    calibration["trained_before"] = "2027-28"
    with pytest.raises(ValueError, match="origin"):
        remap_score_shapes(world, rows, calibration, events=(8,), seed=1)
    calibration["trained_before"] = "2026-27"
    rows[0]["target_points"] = 15
    with pytest.raises(ValueError, match="outcomes"):
        remap_score_shapes(world, rows, calibration, events=(8,), seed=1)
