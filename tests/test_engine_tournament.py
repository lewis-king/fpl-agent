from __future__ import annotations

import numpy as np

from fplagent_engine.rules import SquadRules
from fplagent_engine.tournament import (
    ResidualCalibration,
    _autosub_weights,
    _knockout,
    _lineup_for_squad,
    _policy_recovery_delta_cell,
    _simulate_player_outcomes,
)


def _rules() -> SquadRules:
    return SquadRules(
        budget=1000,
        squad_size=15,
        starting_size=11,
        club_limit=3,
        squad_positions={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        minimum_starters={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        maximum_starters={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_free_transfers=5,
        scoring={},
    )


def _squad() -> tuple[list[int], dict[int, dict], dict[int, dict[int, dict]]]:
    positions = {
        1: "GK",
        2: "GK",
        3: "DEF",
        4: "DEF",
        5: "DEF",
        6: "DEF",
        7: "DEF",
        8: "MID",
        9: "MID",
        10: "MID",
        11: "MID",
        12: "MID",
        13: "FWD",
        14: "FWD",
        15: "FWD",
    }
    selected = list(positions)
    meta = {element: {"position": position} for element, position in positions.items()}
    by_player = {
        element: {
            1: {
                "position": position,
                "expected_points": float(20 - element),
                "p_play": 0.9,
                "market_price": 50.0,
            }
        }
        for element, position in positions.items()
    }
    return selected, meta, by_player


def test_required_premium_starts_even_when_its_base_xp_is_lower() -> None:
    selected, _, by_player = _squad()
    by_player[15][1]["expected_points"] = 0.1

    ordinary = _lineup_for_squad(selected, 1, by_player, _rules())
    forced = _lineup_for_squad(selected, 1, by_player, _rules(), required_starters={15})

    assert 15 not in ordinary["starters"]
    assert 15 in forced["starters"]


def test_autosub_skips_midfielder_when_three_defender_minimum_would_break() -> None:
    selected, meta, _ = _squad()
    candidate = {
        "selected": selected,
        "lineups": {
            "1": {
                "starters": [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
                "bench_order": [12, 6, 7, 2],
                "captain": 13,
                "vice_captain": 14,
            }
        },
    }
    # Everyone except starting defender 3 plays.
    pattern = sum(1 << (element - 1) for element in selected if element != 3)

    weights = _autosub_weights(candidate, 1, pattern, meta)

    assert weights[selected.index(12)] == 0
    assert weights[selected.index(6)] == 1


def test_captain_falls_back_to_playing_vice_captain() -> None:
    selected, meta, _ = _squad()
    candidate = {
        "selected": selected,
        "lineups": {
            "1": {
                "starters": [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
                "bench_order": [12, 6, 7, 2],
                "captain": 13,
                "vice_captain": 14,
            }
        },
    }
    pattern = sum(1 << (element - 1) for element in selected if element != 13)

    weights = _autosub_weights(candidate, 1, pattern, meta)

    assert weights[selected.index(13)] == 0
    assert weights[selected.index(14)] == 2


def test_five_round_knockout_reduces_128_squads_to_four() -> None:
    scores = np.zeros((20, 128, 5), dtype=np.int16)

    survival, champions = _knockout(scores, seed=7)

    assert survival.sum(axis=1).tolist() == [[64, 32, 16, 8, 4]] * 20
    assert champions.shape == (20,)


def test_report_marks_non_finalist_policy_delta_as_unavailable() -> None:
    policy_results = {
        "S001": {"recovery_mean_delta_to_primary": 1.234},
    }

    assert _policy_recovery_delta_cell(policy_results, "S001") == "+1.23"
    assert _policy_recovery_delta_cell(policy_results, "S028") == "—"


def test_simulator_maps_sparse_official_team_ids_to_dense_indices(monkeypatch) -> None:
    monkeypatch.setattr(
        "fplagent_engine.tournament._current_fixture_map",
        lambda events: {1: [(7, 20)]},
    )
    calibration = ResidualCalibration(
        global_shocks=np.zeros((1, 4), dtype=np.float32),
        fixture_shocks=np.zeros((1, 2, 4), dtype=np.float32),
        residual_pools={("GK", 0): np.zeros(1, dtype=np.float32)},
        bin_edges={"GK": np.asarray([], dtype=np.float32)},
        residual_sd={("GK", 0): 0.0},
        play_rho=0.0,
        points_rho=0.0,
        rows=1,
        played_rows=1,
        fixtures=1,
        global_sd=0.0,
        fixture_sd=0.0,
        idiosyncratic_sd=0.0,
    )
    by_player = {
        101: {
            1: {
                "team_id": 7,
                "position": "GK",
                "p_play": 0.999,
                "conditional_points_if_playing": 4.0,
            }
        }
    }

    points, played = _simulate_player_outcomes(
        [101], (1,), by_player, calibration, simulations=8, seed=11
    )

    assert points.shape == (8, 1, 1)
    assert played.shape == (8, 1, 1)
    assert set(np.unique(points)).issubset({0, 4})

    for probability in (0., 1.):
        by_player[101][1]["p_play"] = probability
        points, played = _simulate_player_outcomes([101], (1,), by_player, calibration,
                                                   simulations=10000, seed=11)
        assert np.all(played == bool(probability))
        assert np.all(points == int(4 * probability))
