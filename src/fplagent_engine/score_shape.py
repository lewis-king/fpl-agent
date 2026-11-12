"""Time-forward test of a mean-preserving, football-shaped marginal score model.

Research output only: no model means, joint simulations or live decisions are changed.
Actual score atoms (especially blanks) stay at their real values rather than moving
upwards when a strong player's forecast rises. Exponential tilting matches the
incumbent mean; explicit non-appearance mass is retained at zero.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .distribution_calibration import BACKTEST_FORECAST, TRAINING_FEATURES
from .paths import MODEL_DATA

SCORES = np.arange(-10, 41, dtype=float)
POSITIONS = ("GK", "DEF", "MID", "FWD")
RESULT = MODEL_DATA / "score_shape_v1" / "replay.json"
ARTIFACT = MODEL_DATA / "score_shape_v1" / "marginal-diagnostics.json"
GATE_KEYS = {
    "both_folds_positive_block_lower_bound",
    "no_position_crps_regression_over_one_percent",
    "top_candidate_crps_improves_both_folds",
    "means_preserved",
}


def fit_shapes(rows: list[dict], *, before_season: str) -> dict:
    eligible = [
        r
        for r in rows
        if r["season"] < before_season
        and r["target_minutes"] > 0
        and r["fixture_count"] == 1
        and r["p_play"] >= 0.05
    ]
    shapes = {}
    for position in POSITIONS:
        subset = [r for r in eligible if r["position"] == position]
        if len(subset) < 100:
            raise ValueError(f"Insufficient prior-season evidence for {position}")
        actual = np.asarray([r["target_points"] for r in subset])
        if np.any(actual < SCORES[0]) or np.any(actual > SCORES[-1]):
            raise ValueError("Historical score outside declared support; extend it explicitly")
        # Small count smoothing avoids impossible unseen outcomes, not an xP boost.
        counts = np.bincount((actual - SCORES[0]).astype(int), minlength=len(SCORES)) + 0.5
        residual = actual - np.asarray(
            [r["expected_points"] / max(r["p_play"], 0.05) for r in subset]
        )
        residual -= residual.mean()
        values, frequencies = np.unique(np.clip(np.rint(residual), -15, 25), return_counts=True)
        shapes[position] = {
            "rows": len(subset),
            "probabilities": (counts / counts.sum()).tolist(),
            "residuals": {str(int(v)): float(n / len(subset)) for v, n in zip(values, frequencies)},
        }
    return {
        "trained_before": before_season,
        "training_seasons": sorted({r["season"] for r in eligible}),
        "positions": shapes,
    }


def tilted_pmfs(means: np.ndarray, p_play: np.ndarray, base: np.ndarray) -> np.ndarray:
    means, p_play, base = [np.asarray(v, dtype=float) for v in (means, p_play, base)]
    if means.ndim != 1 or means.shape != p_play.shape or base.shape != SCORES.shape:
        raise ValueError("Invalid score-shape dimensions")
    if not all(np.isfinite(v).all() for v in (means, p_play, base)) or np.any(base <= 0):
        raise ValueError("Non-finite inputs or non-positive score prior")
    if np.any((p_play < 0) | (p_play > 1)) or np.any((p_play == 0) & (means != 0)):
        raise ValueError("Inconsistent appearance probability and mean")
    conditional = np.divide(means, p_play, out=np.zeros_like(means), where=p_play > 0)
    if np.any((conditional <= SCORES[0]) | (conditional >= SCORES[-1])):
        raise ValueError("Conditional mean outside score support")
    lo, hi = np.full(len(means), -20.0), np.full(len(means), 20.0)
    for _ in range(64):
        theta = (lo + hi) / 2
        logits = np.log(base)[None, :] + theta[:, None] * SCORES
        mass = np.exp(logits - logits.max(axis=1, keepdims=True))
        mass /= mass.sum(axis=1, keepdims=True)
        below = mass @ SCORES < conditional
        lo = np.where(below, theta, lo)
        hi = np.where(below, hi, theta)
    mass *= p_play[:, None]
    mass[:, int(-SCORES[0])] += 1 - p_play
    return mass


def shifted_pmfs(
    means: np.ndarray, p_play: np.ndarray, residuals: dict, *, scale: float = 1.0
) -> np.ndarray:
    output = np.zeros((len(means), len(SCORES)))
    conditional = means / np.maximum(p_play, 0.05)
    for residual, probability in residuals.items():
        value = np.clip(conditional + float(residual) * scale, -4, 30)
        left = np.floor(value).astype(int) - int(SCORES[0])
        right = np.minimum(left + 1, len(SCORES) - 1)
        fraction = value - np.floor(value)
        output[np.arange(len(means)), left] += p_play * probability * (1 - fraction)
        output[np.arange(len(means)), right] += p_play * probability * fraction
    output[:, int(-SCORES[0])] += 1 - p_play
    return output


def metrics(mass: np.ndarray, actual: np.ndarray) -> dict:
    cdf = mass.cumsum(axis=1)
    crps = ((cdf[:, :-1] - (SCORES[None, :-1] >= actual[:, None])) ** 2).sum(axis=1)
    crps += np.maximum(SCORES[0] - actual, 0) + np.maximum(actual - SCORES[-1], 0)
    low = SCORES[(cdf >= 0.1).argmax(axis=1)]
    high = SCORES[(cdf >= 0.9).argmax(axis=1)]
    return {
        "rows": len(actual),
        "crps": float(crps.mean()),
        "crps_by_row": crps,
        "coverage80": float(((actual >= low) & (actual <= high)).mean()),
        "blank_brier": float(((mass[:, SCORES <= 2].sum(axis=1) - (actual <= 2)) ** 2).mean()),
        "haul_brier": float(((mass[:, SCORES >= 10].sum(axis=1) - (actual >= 10)) ** 2).mean()),
    }


def _historical_rows() -> list[dict]:
    training = pq.read_table(
        TRAINING_FEATURES,
        columns=["season", "event_number", "element", "target_minutes", "fixture_count"],
    ).to_pylist()
    key = lambda r: (r["season"], r["event_number"], r["element"])
    meta = {key(r): r for r in training}
    rows = [
        {**r, **{k: meta[key(r)][k] for k in ("target_minutes", "fixture_count")}}
        for r in pq.read_table(BACKTEST_FORECAST).to_pylist()
        if key(r) in meta
    ]
    return rows


def replay_score_shapes(*, output_path: Path = RESULT) -> dict:
    rows = _historical_rows()
    folds = []
    for season in ("2024-25", "2025-26"):
        calibration = fit_shapes(rows, before_season=season)
        test = [
            r
            for r in rows
            if r["season"] == season and r["fixture_count"] == 1 and r["p_play"] >= 0.05
        ]
        means = np.asarray([r["expected_points"] for r in test])
        plays = np.asarray([r["p_play"] for r in test])
        actual = np.asarray([r["target_points"] for r in test])
        positions = np.asarray([r["position"] for r in test])
        events = np.asarray([r["event_number"] for r in test])
        distributions = {name: np.zeros((len(test), len(SCORES))) for name in ("shifted", "tilted")}
        for position in POSITIONS:
            mask = positions == position
            shape = calibration["positions"][position]
            distributions["shifted"][mask] = shifted_pmfs(
                means[mask], plays[mask], shape["residuals"]
            )
            distributions["tilted"][mask] = tilted_pmfs(
                means[mask], plays[mask], shape["probabilities"]
            )
        top = np.zeros(len(test), dtype=bool)
        for event in np.unique(events):
            indices = np.flatnonzero(events == event)
            top[indices[np.argsort(means[indices], kind="stable")[-3:]]] = True
        cohorts = {}
        for name, mask in {
            "all": np.ones(len(test), dtype=bool),
            "top3_xp_per_event": top,
            **{p: positions == p for p in POSITIONS},
        }.items():
            cohorts[name] = {}
            for model, mass in distributions.items():
                result = metrics(mass[mask], actual[mask])
                result.pop("crps_by_row")
                cohorts[name][model] = result
        old, new = [metrics(distributions[m], actual)["crps_by_row"] for m in ("shifted", "tilted")]
        # Preserve within-GW dependence and neighbouring weeks in a moving-block interval.
        weekly = np.asarray([(old - new)[events == e].mean() for e in sorted(set(events))])
        rng = np.random.default_rng(20261021)
        starts = rng.integers(0, len(weekly), (2000, (len(weekly) + 3) // 4))
        indices = (starts[..., None] + np.arange(4)) % len(weekly)
        sampled = weekly[indices.reshape(2000, -1)[:, : len(weekly)]].mean(axis=1)
        folds.append(
            {
                "test_season": season,
                "training_seasons": calibration["training_seasons"],
                "cohorts": cohorts,
                "weekly_crps_gain": float(weekly.mean()),
                "block95_crps_gain": np.quantile(sampled, [0.025, 0.975]).tolist(),
                "max_mean_drift": float(np.max(np.abs(distributions["tilted"] @ SCORES - means))),
            }
        )
    checks = {
        "both_folds_positive_block_lower_bound": all(f["block95_crps_gain"][0] > 0 for f in folds),
        "no_position_crps_regression_over_one_percent": all(
            f["cohorts"][p]["tilted"]["crps"] <= f["cohorts"][p]["shifted"]["crps"] * 1.01
            for f in folds
            for p in POSITIONS
        ),
        "top_candidate_crps_improves_both_folds": all(
            f["cohorts"]["top3_xp_per_event"]["tilted"]["crps"]
            < f["cohorts"]["top3_xp_per_event"]["shifted"]["crps"]
            for f in folds
        ),
        "means_preserved": all(f["max_mean_drift"] < 1e-6 for f in folds),
    }
    result = {
        "version": "score_shape_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "folds": folds,
        "checks": checks,
        "diagnostic_promotion_eligible": all(checks.values()),
        "decision_authority": False,
        "backtest_sha256": sha256_file(BACKTEST_FORECAST),
        "features_sha256": sha256_file(TRAINING_FEATURES),
        "limitations": [
            "Single-fixture events only; missing/DGW evidence is not invented.",
            "Top-three full-pool forecasts are not actual legal squad captains.",
            "This tests marginal score shape, not legal policy points lift or joint dependence.",
            "Historical rule changes limit transferability; current-season outcomes were not used to fit.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def activate_marginal_diagnostics(
    *, replay_path: Path = RESULT, output_path: Path = ARTIFACT
) -> dict:
    """Promote only the uncertainty diagnostic, not means, risk weights or policies."""
    replay = json.loads(replay_path.read_text())
    if (
        replay.get("version") != "score_shape_v1"
        or set(replay.get("checks") or {}) != GATE_KEYS
        or not all(replay["checks"].values())
    ):
        raise ValueError("Score-shape replay did not pass the declared gates")
    if replay["backtest_sha256"] != sha256_file(BACKTEST_FORECAST) or replay[
        "features_sha256"
    ] != sha256_file(TRAINING_FEATURES):
        raise ValueError("Score-shape replay inputs changed")
    calibration = fit_shapes(_historical_rows(), before_season="2026-27")
    artifact = {
        "version": "mean_preserving_score_atoms_v1",
        "authority": "marginal_diagnostics_only",
        "created_at": datetime.now(UTC).isoformat(),
        "calibration": calibration,
        "backtest_sha256": replay["backtest_sha256"],
        "features_sha256": replay["features_sha256"],
        "replay_path": str(replay_path),
        "replay_sha256": sha256_file(replay_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, sort_keys=True, indent=2) + "\n")
    return artifact


@lru_cache(maxsize=2)
def _load_artifact(signature: tuple) -> dict | None:
    del signature  # File size/mtime signature makes replacement invalidate the cache.
    artifact = json.loads(ARTIFACT.read_text())
    if (
        artifact.get("version") != "mean_preserving_score_atoms_v1"
        or artifact.get("authority") != "marginal_diagnostics_only"
        or artifact["calibration"]["trained_before"] != "2026-27"
        or artifact["backtest_sha256"] != sha256_file(BACKTEST_FORECAST)
        or artifact["features_sha256"] != sha256_file(TRAINING_FEATURES)
        or artifact["replay_sha256"] != sha256_file(Path(artifact["replay_path"]))
    ):
        return None
    return artifact


def frozen_score_distribution(row: dict) -> dict:
    from .distribution_calibration import RESIDUAL_CALIBRATION, empirical_points_pmf

    p_play = float(row.get("p_play", 1.0))
    fallback = "not_promoted_or_not_single_fixture"
    if ARTIFACT.is_file() and row.get("fixture_count") == 1:
        files = (ARTIFACT, BACKTEST_FORECAST, TRAINING_FEATURES, RESULT)
        try:
            artifact = _load_artifact(
                tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
            )
        except (OSError, ValueError, KeyError):
            artifact = None  # An optional diagnostic must not block a legal decision.
        if artifact and 0 <= p_play <= 1:
            try:
                mass = tilted_pmfs(
                    np.array([row["expected_points"]]),
                    np.array([p_play]),
                    np.array(
                        artifact["calibration"]["positions"][row["position"]]["probabilities"]
                    ),
                )[0]
                return {
                    "points_pmf": {str(int(s)): float(v) for s, v in zip(SCORES, mass)},
                    "distribution_source": "historical score atoms, mean-preserving tilt, explicit DNP; marginal diagnostic only",
                    "distribution_calibration_sha256": sha256_file(ARTIFACT),
                    "distribution_policy_authority": False,
                    "distribution_version": artifact["version"],
                }
            except ValueError:
                fallback = "conditional_mean_outside_validated_support"
        else:
            fallback = "artifact_stale_or_invalid"
    return {
        "points_pmf": empirical_points_pmf(
            float(row["expected_points"]),
            position=row["position"],
            p_dnp=float(row["p_dnp"]) if row.get("p_dnp") is not None else 1 - p_play,
        ),
        "distribution_source": "pre-2026 position residual distribution plus explicit DNP mass",
        "distribution_calibration_sha256": sha256_file(RESIDUAL_CALIBRATION),
        "distribution_policy_authority": False,
        "distribution_fallback": fallback,
    }
