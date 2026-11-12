import numpy as np
import pytest

from fplagent_engine.distribution_calibration import discrete_crps
from fplagent_engine.simulation_calibration import score_frozen_draws


@pytest.mark.parametrize("actual", [-8, 0, 3, 10, 25])
def test_empirical_crps_matches_exact_discrete_energy_score(actual):
    draws = np.asarray([-2, 0, 0, 0, 2, 3, 7, 10], dtype=float)
    pmf = {str(int(v)): float((draws == v).mean()) for v in set(draws)}
    assert score_frozen_draws(draws[:, None], [actual])["mean_crps"] == pytest.approx(discrete_crps(pmf, actual))


def test_deterministic_miss_exposes_tail_breach_and_bias():
    result = score_frozen_draws(np.full((10, 1), 3.), [12])
    assert result["mean_crps"] == 9
    assert result["mean_bias"] == -9
    assert result["above_p90_rate"] == result["haul_brier"] == 1
    assert result["interval80_coverage"] == 0


def test_unknown_outcomes_are_not_zero_filled():
    with pytest.raises(ValueError, match="finite"):
        score_frozen_draws(np.ones((20, 1)), [float("nan")])
