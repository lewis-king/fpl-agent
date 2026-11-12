"""Outcome scoring only: empirical CRPS and tails for frozen simulated scores."""

from __future__ import annotations

import numpy as np


def score_frozen_draws(draws, actual):
    draws, actual = np.asarray(draws, dtype=float), np.asarray(actual, dtype=float)
    if (draws.ndim != 2 or actual.shape != (draws.shape[1],) or len(draws) < 2
            or not np.isfinite(draws).all() or not np.isfinite(actual).all()):
        raise ValueError("Calibration requires finite, aligned frozen paths and outcomes")
    n = len(draws)
    ordered = np.sort(draws, axis=0)
    # Exact empirical energy-score identity, including scores outside the support.
    spread = ((2 * np.arange(1, n + 1) - n - 1)[:, None] * ordered).sum(axis=0) / n**2
    crps = np.abs(draws - actual).mean(axis=0) - spread
    low, high = np.quantile(ordered, [.1, .9], axis=0, method="inverted_cdf")
    predicted_haul = (draws >= 10).mean(axis=0)
    return {"rows": len(actual), "mean_crps": float(crps.mean()),
            "interval80_coverage": float(((actual >= low) & (actual <= high)).mean()),
            "below_p10_rate": float((actual < low).mean()),
            "above_p90_rate": float((actual > high).mean()),
            "haul_brier": float(np.square(predicted_haul - (actual >= 10)).mean()),
            "mean_bias": float((draws.mean(axis=0) - actual).mean()),
            "scope": "Discrete score calibration; nominal intervals can overcover due to point masses."}


def deadline_calibration(worlds, outcomes, baseline_record):
    """Call only after every policy choice has been frozen for this deadline."""
    by_id = {int(r["element"]): r for r in outcomes}
    result = {}
    for name, world in worlds.items():
        ids, meta = world["player_ids"], world["player_meta"]
        actual = np.asarray([by_id[p]["target_points"] for p in ids], dtype=float)
        cohorts = {"all": np.ones(len(ids), dtype=bool),
                   **{p: np.asarray([meta[i]["position"] == p for i in ids])
                      for p in ("GK", "DEF", "MID", "FWD")},
                   "captain": np.asarray([i == baseline_record["captain"] for i in ids]),
                   "bench": np.asarray([i in baseline_record["bench_order"] for i in ids])}
        result[name] = {cohort: score_frozen_draws(world["points"][:, 0, mask], actual[mask])
                        for cohort, mask in cohorts.items() if mask.any()}
    return result
