"""Research-only score-shape sensitivity in legal, correlated simulation worlds.

Retains appearance paths and score rank ordering within each player/event. It
does NOT prove the new discrete joint distribution's covariance is calibrated.
No function here changes production simulations or grants decision authority.
"""

from __future__ import annotations

import numpy as np

from .score_shape import SCORES, tilted_pmfs


def remap_score_shapes(world: dict, rows: list[dict], calibration: dict, *, events, seed):
    if any(k.startswith(("target_", "realized_")) for r in rows for k in r):
        raise ValueError("Realized outcomes cannot enter a decision simulation")
    if any(str(r["season"]) < calibration["trained_before"] for r in rows if "season" in r):
        raise ValueError("Score-shape training extends beyond the forecast origin")
    points, played = world["points"], world["played"]
    if points.shape != played.shape or points.shape[1:] != (len(events), len(world["player_ids"])):
        raise ValueError("Incoherent world dimensions")
    if not np.isfinite(points).all():
        raise ValueError("Non-finite simulation scores")
    result = points.copy()
    by_key = {(int(r["event_number"]), int(r["element"])): r for r in rows}
    rng = np.random.default_rng(seed)
    transformed, skipped, mean_errors = 0, [], []
    for e, event in enumerate(events):
        for i, player in enumerate(world["player_ids"]):
            row = by_key[(event, player)]
            if row.get("fixture_count") != 1:
                skipped.append({"event": event, "player": player, "reason": "not_single_fixture"})
                continue
            mask = played[:, e, i]
            n = int(mask.sum())
            p_play = float(row["p_play"])
            xp = float(row["expected_points"])
            if not 0 <= p_play <= 1 or (p_play == 0 and (xp != 0 or n)):
                raise ValueError("Inconsistent zero-appearance forecast")
            if not n:
                continue
            conditional = xp / p_play
            prior = np.array(calibration["positions"][row["position"]]["probabilities"])
            try:
                mass = tilted_pmfs(np.array([conditional]), np.ones(1), prior)[0]
            except ValueError:
                skipped.append({"event": event, "player": player, "reason": "unsupported_mean"})
                continue
            old = points[mask, e, i]
            # Randomise ties only. Non-tied ordering (shared fixture/performance
            # shocks) is retained; Pearson correlations need not be unchanged.
            order = np.lexsort((rng.random(n), old))
            quantiles = (np.arange(n) + 0.5) / n
            cdf = mass.cumsum()
            cdf[-1] = 1.0
            draws = SCORES[np.searchsorted(cdf, quantiles)]
            mapped = np.empty(n, dtype=result.dtype)
            mapped[order] = draws
            result[mask, e, i] = mapped
            mean_errors.append(abs(float(mapped.mean()) - conditional))
            transformed += 1
    if not np.array_equal(result[~played], points[~played]):
        raise ValueError("Score-shape remapping changed a nonappearance")
    return {**world, "points": result}, {
        "version": "rank_preserving_score_shape_sensitivity_v1",
        "decision_authority": False,
        "transformed_player_events": transformed,
        "skipped": skipped,
        "max_conditional_mean_quantisation_error": max(mean_errors, default=0),
        "appearance_paths_unchanged": True,
        "limitations": [
            "Marginal historical validation does not validate this joint simulation.",
            "Only residual-world score shape changes; component worlds stay unchanged.",
            "Non-tied score ordering is preserved; discrete ties and Pearson correlations may change.",
            "Same xP does not guarantee same simulated mean: realised appearance frequency and finite draws differ.",
            "Mean-preserving variance alone does not improve expected linear FPL points.",
        ],
    }
