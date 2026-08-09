from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine import component_simulator
from fplagent_engine.component_candidates import _modified_rows
from fplagent_engine.component_simulator import (
    EmpiricalComponents,
    _award_bonus,
    _blend_scenario_scores,
    _calibrate_to_xp,
    _categorical_player,
    _market_candidate_shadow_summary,
    _paired_delta_metrics,
    _sample_fixture_appearance_plan,
    _simulate_scores,
    simulate_component_outcomes,
)


def test_market_candidate_shadow_summary_detects_leader_and_rank_change() -> None:
    incumbent = [
        {"candidate_id": "A", "mean_points": 100.0},
        {"candidate_id": "B", "mean_points": 99.0},
    ]
    market = [
        {"candidate_id": "A", "mean_points": 99.5},
        {"candidate_id": "B", "mean_points": 101.0},
    ]

    summary = _market_candidate_shadow_summary(incumbent, market)

    assert summary["incumbent_leader"] == "A"
    assert summary["market_leader"] == "B"
    assert summary["leader_changed"] is True
    assert summary["market_leader_incumbent_rank"] == 2


def test_correlated_poisson_scores_preserve_requested_means() -> None:
    rng = np.random.default_rng(7)

    home, away = _simulate_scores(1.8, 1.1, -0.05, 100_000, rng)

    assert abs(float(home.mean()) - 1.8) < 0.03
    assert abs(float(away.mean()) - 1.1) < 0.03
    assert abs(float(np.corrcoef(home, away)[0, 1]) + 0.05) < 0.03


def test_categorical_allocation_never_selects_ineligible_player() -> None:
    rng = np.random.default_rng(11)
    eligible = np.asarray([[True, False, True], [False, True, False]])

    choices, available = _categorical_player(eligible, np.asarray([1.0, 100.0, 0.0]), rng)

    assert available.tolist() == [True, True]
    assert choices.tolist() == [0, 1]


def test_xp_anchor_preserves_dnp_and_calibrates_integer_mean() -> None:
    rng = np.random.default_rng(13)
    simulations = 50_000
    played = np.ones((simulations, 1, 1), dtype=bool)
    played[:10_000] = False
    raw = np.where(played, 2, 0).astype(np.int8)
    target = np.asarray([[2.4]])

    anchored, diagnostics = _calibrate_to_xp(raw, played, target, rng)

    assert np.all(anchored[~played] == 0)
    assert abs(float(anchored.mean()) - 2.4) < 0.02
    assert diagnostics["anchored_player_mean_absolute_error"] < 0.02


def test_xp_anchor_does_not_clip_valid_double_gameweek_tail() -> None:
    rng = np.random.default_rng(14)
    played = np.ones((20_000, 1, 1), dtype=bool)
    raw = np.full((20_000, 1, 1), 50, dtype=np.int8)

    anchored, diagnostics = _calibrate_to_xp(raw, played, np.asarray([[55.0]]), rng)

    assert np.all(anchored == 55)
    assert diagnostics["anchored_player_mean_absolute_error"] == 0.0


def test_multi_fixture_plan_preserves_event_play_and_historical_rotation_rate() -> None:
    rng = np.random.default_rng(15)
    simulations = 100_000
    event_available = np.zeros((simulations, 1), dtype=bool)
    event_available[:70_000, 0] = True

    plan = _sample_fixture_appearance_plan(
        event_available,
        np.asarray([2]),
        {2: np.asarray([0.0, 0.30, 0.70])},
        rng,
    )

    assert np.array_equal(plan.any(axis=2)[:, 0], event_available[:, 0])
    appearance_count = plan[event_available[:, 0], 0, :].sum(axis=1)
    assert abs(float(np.mean(appearance_count == 2)) - 0.70) < 0.01
    assert abs(float(np.mean(appearance_count == 1)) - 0.30) < 0.01


def test_bonus_awards_exactly_six_points_per_match() -> None:
    rng = np.random.default_rng(17)
    simulations = 100
    players = 22
    shape = (simulations, players)
    indices = np.arange(players)
    positions = np.asarray(["GK"] * 2 + ["DEF"] * 8 + ["MID"] * 8 + ["FWD"] * 4)

    bonus = _award_bonus(
        indices,
        np.full(shape, 90, dtype=np.int8),
        np.zeros(shape, dtype=np.int8),
        np.zeros(shape, dtype=np.int8),
        np.zeros(shape, dtype=bool),
        np.zeros(shape, dtype=np.int8),
        np.zeros(shape, dtype=np.int8),
        np.zeros(shape, dtype=np.int8),
        np.zeros(shape, dtype=np.int8),
        positions,
        np.full(players, 0.1),
        rng,
    )

    assert np.all(bonus.sum(axis=1) == 6)
    assert set(np.unique(bonus)) == {0, 1, 2, 3}


def test_historical_weight_blends_raw_component_and_incumbent_xp() -> None:
    rows = [
        {
            "element": 7,
            "event_number": 1,
            "expected_points": 6.0,
            "p_play": 0.8,
        }
    ]

    blended = _modified_rows(rows, {(7, 1): 10.0}, raw_weight=0.05)

    assert rows[0]["expected_points"] == 6.0
    assert blended[0]["incumbent_expected_points"] == 6.0
    assert blended[0]["raw_component_points"] == 10.0
    assert blended[0]["expected_points"] == pytest.approx(6.2)
    assert blended[0]["conditional_points_if_playing"] == pytest.approx(7.75)


def test_evidence_weighted_paths_use_frozen_raw_weight() -> None:
    raw = np.asarray([[[100.0], [120.0]], [[80.0], [90.0]]])
    anchored = np.asarray([[[110.0], [108.0]], [[100.0], [100.0]]])

    blended = _blend_scenario_scores(raw, anchored, raw_weight=0.05)

    assert blended.dtype == np.float32
    np.testing.assert_allclose(blended[:, :, 0], [[109.5, 108.6], [99.0, 99.5]])


def test_paired_delta_metrics_use_shared_paths() -> None:
    incumbent = np.asarray([[[5.0], [5.0]], [[10.0], [10.0]]])
    challenger = incumbent + np.asarray([[[1.0], [0.0]], [[0.0], [1.0]]])

    metrics = _paired_delta_metrics(challenger, incumbent)

    assert metrics["mean_delta"] == 1.0
    assert metrics["delta_95ci_low"] == 1.0
    assert metrics["delta_95ci_high"] == 1.0
    assert metrics["beat_probability"] == 1.0


def test_component_simulator_scores_doubles_per_fixture_and_blanks_as_zero(
    tmp_path, monkeypatch
) -> None:
    fixtures = tmp_path / "fixtures.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"id": 10, "event": 1, "team_h": 1, "team_a": 2},
                {"id": 11, "event": 1, "team_h": 1, "team_a": 3},
            ]
        ),
        fixtures,
    )
    monkeypatch.setattr(component_simulator, "CURRENT_FIXTURES", fixtures)
    monkeypatch.setattr(
        component_simulator,
        "calibrate_residuals",
        lambda: SimpleNamespace(play_rho=0.0),
    )
    monkeypatch.setattr(
        component_simulator.joblib,
        "load",
        lambda _path: {"score_correlation": 0.0},
    )

    def full_match_minutes(rows, _empirical, _rng, player_latent, _play_rho):
        shape = player_latent.shape
        return (
            np.full(shape, 90, dtype=np.int8),
            np.zeros(shape, dtype=np.int8),
            np.full(shape, 90, dtype=np.int8),
            np.full(shape, 3, dtype=np.int8),
        )

    monkeypatch.setattr(component_simulator, "_sample_minutes", full_match_minutes)
    simulated_scores = iter(
        [
            (np.zeros(20, dtype=np.int8), np.zeros(20, dtype=np.int8)),
            (np.zeros(20, dtype=np.int8), np.ones(20, dtype=np.int8)),
        ]
    )
    monkeypatch.setattr(
        component_simulator,
        "_simulate_scores",
        lambda _home, _away, _correlation, _simulations, _rng: next(simulated_scores),
    )
    monkeypatch.setattr(
        component_simulator,
        "_categorical_player",
        lambda eligible, _propensities, _rng: (
            np.zeros(len(eligible), dtype=np.int64),
            np.zeros(len(eligible), dtype=bool),
        ),
    )
    monkeypatch.setattr(
        component_simulator,
        "_award_bonus",
        lambda player_indices, minutes, *_args: np.zeros(
            (len(minutes), len(player_indices)), dtype=np.int8
        ),
    )

    def row(team: int, event: int, expected_points: float) -> dict:
        return {
            "team_id": team,
            "position": "GK",
            "expected_points": expected_points,
            "p_dnp": 0.0,
            "p_1_59": 0.0,
            "p_60_89": 0.0,
            "p_90_or_more": 1.0,
        }

    by_player = {
        1: {1: row(1, 1, 8.0), 2: row(1, 2, 0.0)},
        2: {1: row(2, 1, 6.0), 2: row(2, 2, 0.0)},
        3: {1: row(3, 1, 6.0), 2: row(3, 2, 0.0)},
    }
    zero_by_position = {"GK": 0.0, "DEF": 0.0, "MID": 0.0, "FWD": 0.0}
    empirical = EmpiricalComponents(
        minute_pools={},
        goal_rate90=zero_by_position,
        assist_rate90=zero_by_position,
        yellow_rate90=zero_by_position,
        red_rate90=zero_by_position,
        own_goal_rate90=zero_by_position,
        penalty_miss_rate90=zero_by_position,
        penalty_save_rate90=0.0,
        save_rate90=0.0,
        dc_probability={},
        multi_fixture_appearance_probability={
            2: np.asarray([0.0, 0.0, 1.0], dtype=np.float64)
        },
        assist_per_goal=0.0,
        rows=0,
        recent_rows=0,
    )

    player_ids, raw, _anchored, played, means, diagnostics = simulate_component_outcomes(
        by_player,
        (1, 2),
        {(1, 1, 2): (0.0, 0.0), (1, 1, 3): (0.0, 0.0)},
        empirical,
        simulations=20,
        seed=23,
        component_forecast_path=tmp_path / "absent.parquet",
    )

    assert player_ids == [1, 2, 3]
    # Team 1 plays twice: two appearance awards, one clean sheet and one separate
    # one-goal concession. The latter must not combine with the other fixture into
    # a spurious "two goals conceded" deduction.
    assert np.all(raw[:, 0, 0] == 8)
    assert np.all(raw[:, 0, 1:] == 6)
    assert np.all(raw[:, 1, :] == 0)
    assert np.all(played[:, 0, :])
    assert not np.any(played[:, 1, :])
    assert means["appearance_points"][:, 0].tolist() == [4.0, 0.0]
    assert means["clean_sheet_points"][:, 0].tolist() == [4.0, 0.0]
    assert means["goals_conceded_points"][:, 0].tolist() == [0.0, 0.0]
    identity = diagnostics["identity_checks"]
    assert identity["double_fixture_player_events"] == 1
    assert identity["single_fixture_player_events"] == 2
    assert identity["blank_player_events"] == 3
    assert identity["maximum_fixtures_per_team_event"] == 2
