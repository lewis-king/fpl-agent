from __future__ import annotations

import pytest

from fplagent_engine.current_squad_audit import _candidate
from fplagent_engine.preseason_role_threshold import (
    build_threshold_grid,
    reconstruct_named_configuration,
    summarize_supported_boundary,
)


def test_threshold_grid_couples_severe_and_moderate_bounds() -> None:
    grid = build_threshold_grid([0.50, 0.55, 0.60, 0.65, 0.70, 0.75])

    assert [row["not_listed_retention"] for row in grid] == [
        0.50,
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
    ]
    assert [row["role_watch_retention"] for row in grid] == [
        0.75,
        0.78,
        0.81,
        0.84,
        0.87,
        0.90,
    ]
    assert grid[0]["severity_fraction"] == 1.0
    assert grid[-1]["severity_fraction"] == 0.0


def test_threshold_grid_rejects_unsorted_duplicate_and_out_of_path_values() -> None:
    with pytest.raises(ValueError, match="unique and ascending"):
        build_threshold_grid([0.60, 0.55])
    with pytest.raises(ValueError, match="unique and ascending"):
        build_threshold_grid([0.55, 0.55])
    with pytest.raises(ValueError, match="defined from 0.50 to 0.75"):
        build_threshold_grid([0.80])


def test_named_configuration_reconstructs_exact_candidate_identity() -> None:
    selected = list(range(1, 16))
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    meta = {
        element: {"position": position, "player_name": f"Player {element}"}
        for element, position in zip(selected, positions, strict=True)
    }
    starters = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
    bench = (6, 7, 12, 2)
    expected = _candidate(selected, starters, bench, 8, 9, meta)
    lineup = expected["lineups"]["1"]
    named = {
        "candidate_id": expected["candidate_id"],
        "formation": lineup["formation"],
        "starters": [meta[element]["player_name"] for element in starters],
        "bench_order": [meta[element]["player_name"] for element in bench],
        "captain": meta[8]["player_name"],
        "vice_captain": meta[9]["player_name"],
    }

    actual = reconstruct_named_configuration(selected, named, meta)

    assert actual == expected


def test_supported_boundary_returns_mildest_supported_and_next_point() -> None:
    points = [
        {
            "not_listed_retention": retention,
            "role_watch_retention": role,
            "challenger_squad_id": "challenger",
            "cross_family_holdout_support": support,
        }
        for retention, role, support in [
            (0.50, 0.75, True),
            (0.55, 0.78, True),
            (0.60, 0.81, False),
            (0.65, 0.84, False),
        ]
    ]

    boundary = summarize_supported_boundary(points)

    assert boundary["classification"] == "supported_boundary_bracketed"
    assert boundary["support_is_monotone"] is True
    assert boundary["highest_supported_retention"] == 0.55
    assert boundary["next_tested_unsupported_retention"] == 0.60
    assert boundary["grid_resolution"] == pytest.approx(0.05)


def test_supported_boundary_marks_non_monotone_curve() -> None:
    points = [
        {
            "not_listed_retention": retention,
            "role_watch_retention": 0.75,
            "challenger_squad_id": "challenger",
            "cross_family_holdout_support": support,
        }
        for retention, support in [(0.50, True), (0.55, False), (0.60, True)]
    ]

    boundary = summarize_supported_boundary(points)

    assert boundary["classification"] == "non_monotone_support_requires_finer_replay"
    assert boundary["support_is_monotone"] is False
