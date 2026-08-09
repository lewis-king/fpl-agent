from __future__ import annotations

import numpy as np
import pytest

from fplagent_engine.preseason_role_scenario import (
    FLAG_NOT_LISTED,
    FLAG_OTHER,
    FLAG_ROLE_WATCH,
    FLAG_UNCOVERED,
    SCENARIOS,
    _deep_configuration_comparison,
    apply_conditional_dnp_stress,
    derive_role_flags,
    scenario_player_factors,
)


def _row(
    element: int,
    status: str,
    *,
    eligible: int,
    listed: int = 0,
    starts: int = 0,
    recent: float | None = None,
    latest: bool | None = None,
) -> dict:
    return {
        "fpl_element": element,
        "evidence_status": status,
        "eligible_team_matches": eligible,
        "squad_listings": listed,
        "starts": starts,
        "recency_weighted_start_share": recent,
        "last_match_started": latest,
    }


def test_role_flags_separate_absence_watch_uncovered_and_other() -> None:
    rows = [
        _row(1, "not_listed_in_eligible_lineups", eligible=3),
        _row(
            2,
            "observed_in_lineup",
            eligible=3,
            listed=3,
            starts=1,
            recent=0.30,
            latest=False,
        ),
        _row(3, "no_confirmed_team_lineups", eligible=0),
        _row(
            4,
            "observed_in_lineup",
            eligible=3,
            listed=3,
            starts=3,
            recent=1.0,
            latest=True,
        ),
    ]

    assert derive_role_flags(rows, {1, 2, 3, 4}) == {
        1: FLAG_NOT_LISTED,
        2: FLAG_ROLE_WATCH,
        3: FLAG_UNCOVERED,
        4: FLAG_OTHER,
    }


def test_scenario_factors_never_penalize_uncovered_players() -> None:
    flags = {1: FLAG_NOT_LISTED, 2: FLAG_ROLE_WATCH, 3: FLAG_UNCOVERED}

    factors = scenario_player_factors(flags, SCENARIOS["severe_role_stress"])

    assert factors == {1: 0.5, 2: 0.75}
    assert 3 not in factors


def test_conditional_dnp_boundary_zeros_only_flagged_existing_appearances() -> None:
    points = np.asarray([[[7, 4]], [[0, 5]], [[3, 0]]], dtype=np.int16)
    played = np.asarray([[[True, True]], [[False, True]], [[True, False]]])

    stressed_points, stressed_played, diagnostics = apply_conditional_dnp_stress(
        points,
        played,
        [10, 20],
        {10: 0.0},
        seed=99,
    )

    assert stressed_played[:, 0, 0].tolist() == [False, False, False]
    assert stressed_points[:, 0, 0].tolist() == [0, 0, 0]
    assert np.array_equal(stressed_played[:, 0, 1], played[:, 0, 1])
    assert np.array_equal(stressed_points[:, 0, 1], points[:, 0, 1])
    assert diagnostics["10"]["base_appearance_rate"] == pytest.approx(2 / 3)
    assert diagnostics["10"]["stressed_appearance_rate"] == 0.0


def test_conditional_stress_is_deterministic_and_never_creates_appearances() -> None:
    points = np.ones((1_000, 1, 1), dtype=np.int16) * 4
    played = np.ones((1_000, 1, 1), dtype=bool)
    first = apply_conditional_dnp_stress(
        points, played, [10], {10: 0.5}, seed=7
    )
    second = apply_conditional_dnp_stress(
        points, played, [10], {10: 0.5}, seed=7
    )

    assert np.array_equal(first[0], second[0])
    assert np.array_equal(first[1], second[1])
    assert 0.40 < first[1][:, 0, 0].mean() < 0.60
    assert np.all(first[1] <= played)

    severe = apply_conditional_dnp_stress(
        points, played, [10], {10: 0.25}, seed=7
    )
    assert np.all(severe[1] <= first[1])


def test_conditional_stress_rejects_unknown_players_and_invalid_factors() -> None:
    points = np.ones((2, 1, 1), dtype=np.int16)
    played = np.ones((2, 1, 1), dtype=bool)

    with pytest.raises(ValueError, match="unknown players"):
        apply_conditional_dnp_stress(points, played, [10], {11: 0.5}, seed=1)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        apply_conditional_dnp_stress(points, played, [10], {10: 1.1}, seed=1)


def test_deep_configuration_comparison_scores_exact_captain_difference() -> None:
    player_ids = list(range(1, 16))
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    meta = {
        element: {"position": position, "player_name": str(element)}
        for element, position in zip(player_ids, positions, strict=True)
    }
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [6, 7, 12, 2]
    incumbent = {
        "candidate_id": "incumbent",
        "selected": player_ids,
        "lineups": {
            "1": {
                "starters": starters,
                "bench_order": bench,
                "captain": 8,
                "vice_captain": 9,
                "formation": "3-4-3",
            }
        },
    }
    challenger = {
        **incumbent,
        "candidate_id": "challenger",
        "lineups": {
            "1": {
                **incumbent["lineups"]["1"],
                "captain": 9,
                "vice_captain": 8,
            }
        },
    }
    points = np.ones((100, 1, 15), dtype=np.int16)
    points[:, 0, 7] = 5
    points[:, 0, 8] = 10
    played = np.ones_like(points, dtype=bool)

    result = _deep_configuration_comparison(
        challenger,
        incumbent,
        meta,
        player_ids,
        points,
        played,
        points,
        played,
    )

    assert result["cross_family_holdout_support"] is True
    assert result["holdout_delta_challenger_to_incumbent"]["residual"]["mean"] == 5.0
    assert result["holdout_delta_challenger_to_incumbent"]["component"]["mean"] == 5.0
