import json
import math
from pathlib import Path

from fplagent_engine.distribution_calibration import (
    discrete_crps,
    empirical_points_pmf,
    gaussian_points_pmf,
    pmf_cvar,
    pmf_quantile,
    score_distribution_rows,
)


def test_distribution_is_normalized_and_has_ordered_tails() -> None:
    pmf = gaussian_points_pmf(5.0, 2.0, p_dnp=0.1)
    assert math.isclose(sum(pmf.values()), 1.0)
    assert pmf_quantile(pmf, 0.1) <= pmf_quantile(pmf, 0.9)
    assert pmf_cvar(pmf, lower=True) < pmf_cvar(pmf, lower=False)


def test_crps_rewards_probability_on_realized_score() -> None:
    sharp = {"0": 0.1, "2": 0.8, "5": 0.1}
    wrong = {"0": 0.8, "2": 0.1, "5": 0.1}
    assert discrete_crps(sharp, 2.0) < discrete_crps(wrong, 2.0)


def test_scoreboard_splits_position_captain_and_bench() -> None:
    rows = [
        {
            "position": "MID",
            "decision_role": "captain",
            "actual_points": 10,
            "expected_points": 7,
            "points_pmf": gaussian_points_pmf(7, 3),
        },
        {
            "position": "DEF",
            "decision_role": "bench",
            "actual_points": 2,
            "expected_points": 3,
            "points_pmf": gaussian_points_pmf(3, 2),
        },
    ]
    result = score_distribution_rows(rows)
    assert result["overall"]["rows"] == 2
    assert result["by_decision_role"]["captain"]["rows"] == 1
    assert result["by_decision_role"]["bench"]["rows"] == 1


def test_empirical_distribution_combines_played_tail_and_dnp(
    tmp_path: Path,
) -> None:
    calibration = tmp_path / "residuals.json"
    calibration.write_text(
        json.dumps(
            {
                "positions": {
                    "MID": {
                        "bins": {"-2": 0.25, "0": 0.5, "4": 0.25},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    pmf = empirical_points_pmf(
        4.0,
        position="MID",
        p_dnp=0.2,
        calibration_path=calibration,
    )
    assert math.isclose(sum(pmf.values()), 1.0)
    assert pmf["0"] >= 0.2
    assert pmf["9"] > 0.0
