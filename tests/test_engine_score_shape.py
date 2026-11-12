import numpy as np
import pytest

from fplagent_engine.distribution_calibration import discrete_crps
from fplagent_engine.score_shape import SCORES, fit_shapes, metrics, tilted_pmfs


def test_tilt_preserves_mean_dnp_and_real_blank_atoms():
    base = np.full(len(SCORES), 0.0001)
    base[np.flatnonzero(SCORES == 2)] = 0.7
    base[np.flatnonzero(SCORES == 8)] = 0.2
    base[np.flatnonzero(SCORES == 16)] = 0.1
    means = np.array([0.0, 2.0, 6.0, 8.0])
    plays = np.array([0.0, 0.5, 0.95, 1.0])
    mass = tilted_pmfs(means, plays, base)
    np.testing.assert_allclose(mass.sum(axis=1), 1)
    np.testing.assert_allclose(mass @ SCORES, means, atol=1e-8)
    assert mass[0, SCORES == 0] == 1
    assert mass[2, SCORES == 2] > 0.1  # High xP does not move the two-point atom upwards.
    assert mass[2, SCORES == 0] >= 0.05


@pytest.mark.parametrize(
    "mean,play", [(5.0, 0.0), (0.0, -1.0), (0.0, 1.1), (float("nan"), 1.0), (50.0, 1.0)]
)
def test_invalid_probabilities_or_means_fail_closed(mean, play):
    with pytest.raises(ValueError):
        tilted_pmfs(np.array([mean]), np.array([play]), np.ones(len(SCORES)))


def test_sparse_crps_keeps_distance_and_scores_outside_support():
    assert discrete_crps({"0": 0.5, "10": 0.5}, 5) == pytest.approx(2.5)
    assert discrete_crps({"2": 1}, 5) == pytest.approx(3)
    assert discrete_crps({"2": 1}, -1.5) == pytest.approx(3.5)
    mass = np.zeros((1, len(SCORES)))
    mass[0, SCORES == 2] = 1
    assert metrics(mass, np.array([42]))["crps"] == 40


def test_shape_training_never_consumes_test_or_later_seasons():
    rows = [
        {
            "season": season,
            "position": p,
            "target_minutes": 90,
            "fixture_count": 1,
            "p_play": 0.9,
            "expected_points": 3,
            "target_points": points,
        }
        for season, points in [("2023-24", 2), ("2024-25", 20)]
        for p in ("GK", "DEF", "MID", "FWD")
        for _ in range(110)
    ]
    fitted = fit_shapes(rows, before_season="2024-25")
    assert fitted["training_seasons"] == ["2023-24"]
    assert all(p["rows"] == 110 for p in fitted["positions"].values())
    assert fitted["positions"]["MID"]["probabilities"][int(2 - SCORES[0])] > 0.8


def test_diagnostic_activation_requires_all_declared_gates(tmp_path):
    import json

    from fplagent_engine.score_shape import activate_marginal_diagnostics

    path = tmp_path / "replay.json"
    path.write_text(json.dumps({"version": "score_shape_v1", "checks": {"means_preserved": True}}))
    with pytest.raises(ValueError, match="gates"):
        activate_marginal_diagnostics(replay_path=path, output_path=tmp_path / "artifact.json")


def test_missing_optional_shape_artifact_falls_back_with_explicit_label(monkeypatch, tmp_path):
    from fplagent_engine import distribution_calibration, score_shape

    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}")
    monkeypatch.setattr(score_shape, "ARTIFACT", artifact)
    monkeypatch.setattr(score_shape, "RESULT", tmp_path / "missing-replay.json")
    monkeypatch.setattr(
        distribution_calibration, "empirical_points_pmf", lambda *a, **k: {"0": 1.0}
    )
    monkeypatch.setattr(score_shape, "sha256_file", lambda _: "legacy-hash")
    value = score_shape.frozen_score_distribution(
        {"expected_points": 0, "p_play": 0.0, "p_dnp": None, "position": "MID", "fixture_count": 1}
    )
    assert value["distribution_policy_authority"] is False
    assert value["distribution_fallback"] == "artifact_stale_or_invalid"
    assert value["points_pmf"] == {"0": 1.0}


def test_method_change_is_scored_as_separate_cohorts():
    from fplagent_engine.distribution_calibration import score_distribution_rows

    rows = [
        {
            "position": "MID",
            "decision_role": "captain",
            "actual_points": 2,
            "expected_points": 2,
            "points_pmf": {"2": 1.0},
            "distribution_source": source,
        }
        for source in ("old", "new")
    ]
    result = score_distribution_rows(rows)
    assert set(result["by_distribution_source"]) == {"old", "new"}
    assert result["by_distribution_source"]["new"]["rows"] == 1
