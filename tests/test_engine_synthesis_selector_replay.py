from __future__ import annotations

from fplagent_engine.synthesis_selector_replay import (
    calibrate_selector,
    family_regrets,
    select_candidate,
)


def _path(*points: int) -> dict:
    return {
        "events": [
            {"event": event, "net_points": points[event - 1]}
            for event in range(1, len(points) + 1)
        ]
    }


def test_family_regrets_keep_short_and_long_outcomes_separate() -> None:
    paths = {
        ("s", "short"): _path(10, 10, 10, 10, 10, 0, 0, 0),
        ("s", "long"): _path(9, 9, 9, 9, 9, 10, 10, 10),
    }
    result = family_regrets(paths, seasons=("s",), config_ids=("short", "long"))

    assert result["s"]["short"]["short_regret"] == 0
    assert result["s"]["short"]["long_regret"] == 25
    assert result["s"]["long"]["short_regret"] == 5
    assert result["s"]["long"]["long_regret"] == 0


def test_selector_weight_changes_the_winner() -> None:
    paths = {
        ("s", "short"): _path(10, 10, 10, 10, 10, 0, 0, 0),
        ("s", "long"): _path(9, 9, 9, 9, 9, 10, 10, 10),
    }
    regrets = family_regrets(paths, seasons=("s",), config_ids=("short", "long"))

    short, _ = select_candidate(
        regrets,
        seasons=("s",),
        config_ids=("short", "long"),
        horizon_weight=0.0,
        worst_weight=0.0,
    )
    long, _ = select_candidate(
        regrets,
        seasons=("s",),
        config_ids=("short", "long"),
        horizon_weight=1.0,
        worst_weight=0.0,
    )

    assert short == "short"
    assert long == "long"


def test_calibration_retains_incumbent_without_strict_out_of_sample_win() -> None:
    paths = {}
    for season in ("a", "b", "test"):
        paths[(season, "balanced")] = _path(8, 8, 8, 8, 8, 8, 8, 8)
        paths[(season, "other")] = _path(7, 7, 7, 7, 7, 7, 7, 7)

    result = calibrate_selector(
        paths,
        selection_seasons=("a", "b"),
        test_season="test",
        horizon_weights=(0.25, 0.50, 0.75),
        worst_weights=(0.0, 0.20, 0.40),
    )

    assert result["verdict"] == "RETAIN_INCUMBENT"
    assert result["production_configuration"] == {
        "horizon_family_weight": 0.5,
        "family_worst_weight": 0.2,
    }
