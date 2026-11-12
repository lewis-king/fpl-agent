from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
from scipy.stats import norm

from fplagent_data.http import sha256_file

from .paths import MODEL_DATA, REPORTS

VERSION = "full_distribution_calibration_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
RESULTS = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "full-distribution-calibration.md"
RESULT_ROOT = MODEL_DATA / "prospective_weekly_scoring_v4"
RESIDUAL_CALIBRATION = OUTPUT_DIR / "historical-residual-calibration.json"
BACKTEST_FORECAST = MODEL_DATA / "forecasts" / "rolling-backtest.parquet"
TRAINING_FEATURES = MODEL_DATA / "features" / "player_deadlines.parquet"
SCORE_MINIMUM = -4
SCORE_MAXIMUM = 30
MINIMUM_EVENTS = 6
MINIMUM_PLAYERS = 200


def build_historical_residual_calibration(
    *,
    backtest_path: Path = BACKTEST_FORECAST,
    training_path: Path = TRAINING_FEATURES,
    output_path: Path = RESIDUAL_CALIBRATION,
) -> dict[str, Any]:
    """Fit pre-2026 conditional score residuals without touching future outcomes."""
    minutes = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row["target_minutes"]
        )
        for row in pq.read_table(
            training_path,
            columns=["season", "event_number", "element", "target_minutes"],
        ).to_pylist()
    }
    grouped: dict[str, list[float]] = {position: [] for position in ("GK", "DEF", "MID", "FWD")}
    seasons = set()
    for row in pq.read_table(backtest_path).to_pylist():
        key = (str(row["season"]), int(row["event_number"]), int(row["element"]))
        if minutes.get(key, 0.0) <= 0.0:
            continue
        position = str(row["position"])
        p_play = max(float(row.get("p_play") or 0.0), 0.05)
        conditional_mean = float(row["expected_points"]) / p_play
        grouped[position].append(float(row["target_points"]) - conditional_mean)
        seasons.add(str(row["season"]))
    positions = {}
    for position, values in grouped.items():
        if len(values) < 1_000:
            raise ValueError(f"insufficient played residuals for {position}: {len(values)}")
        array = np.asarray(values, dtype=np.float64)
        centered = array - float(np.mean(array))
        bins = np.clip(np.rint(centered), -15, 25).astype(np.int16)
        unique, counts = np.unique(bins, return_counts=True)
        positions[position] = {
            "rows": len(values),
            "raw_residual_mean": float(np.mean(array)),
            "raw_residual_sd": float(np.std(array)),
            "bins": {
                str(int(value)): float(count / len(bins))
                for value, count in zip(unique, counts, strict=True)
            },
        }
    result = {
        "version": "historical_conditional_residuals_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "maximum_training_season": max(seasons),
        "prospective_target_season": "2026-27",
        "positions": positions,
        "backtest_path": str(backtest_path),
        "backtest_sha256": sha256_file(backtest_path),
        "training_path": str(training_path),
        "training_sha256": sha256_file(training_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _current_residual_calibration(path: Path = RESIDUAL_CALIBRATION) -> dict[str, Any]:
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        if path != RESIDUAL_CALIBRATION or (
            value.get("backtest_sha256") == sha256_file(BACKTEST_FORECAST)
            and value.get("training_sha256") == sha256_file(TRAINING_FEATURES)
        ):
            return value
    if path != RESIDUAL_CALIBRATION:
        raise ValueError(f"custom residual calibration is stale or missing: {path}")
    return build_historical_residual_calibration(output_path=path)


def empirical_points_pmf(
    mean: float,
    *,
    position: str,
    p_dnp: float = 0.0,
    calibration_path: Path = RESIDUAL_CALIBRATION,
    minimum: int = SCORE_MINIMUM,
    maximum: int = SCORE_MAXIMUM,
) -> dict[str, float]:
    """Return a realistic score PMF from played residuals plus explicit DNP mass."""
    if not 0.0 <= p_dnp <= 1.0:
        raise ValueError("p_dnp must be in [0, 1]")
    calibration = _current_residual_calibration(calibration_path)
    position_row = (calibration.get("positions") or {}).get(position)
    if not isinstance(position_row, Mapping):
        raise TypeError(f"residual calibration has no position {position}")
    bins = position_row.get("bins")
    if not isinstance(bins, Mapping) or not bins:
        raise ValueError(f"residual calibration has no bins for {position}")
    played_probability = 1.0 - p_dnp
    conditional_mean = float(mean) / max(played_probability, 0.05)
    output = {str(score): 0.0 for score in range(minimum, maximum + 1)}
    for residual, probability in bins.items():
        value = conditional_mean + int(residual)
        mass = played_probability * float(probability)
        if value <= minimum:
            output[str(minimum)] += mass
            continue
        if value >= maximum:
            output[str(maximum)] += mass
            continue
        lower = math.floor(value)
        upper = lower + 1
        upper_weight = min(max(value - math.floor(value), 0.0), 1.0)
        output[str(lower)] += mass * (1.0 - upper_weight)
        output[str(upper)] += mass * upper_weight
    output["0"] += p_dnp
    total = sum(output.values())
    return {score: probability / total for score, probability in output.items()}


def gaussian_points_pmf(
    mean: float,
    standard_deviation: float,
    *,
    p_dnp: float = 0.0,
    minimum: int = SCORE_MINIMUM,
    maximum: int = SCORE_MAXIMUM,
) -> dict[str, float]:
    """Build a frozen, bounded discrete points distribution.

    DNP mass is placed at zero and the remaining mass follows a discretised normal.
    This is an explicit baseline distribution contract; calibrated component simulation
    PMFs can replace it without changing the scorer.
    """
    if minimum >= maximum:
        raise ValueError("minimum must be below maximum")
    if not 0.0 <= p_dnp <= 1.0:
        raise ValueError("p_dnp must be in [0, 1]")
    sd = max(float(standard_deviation), 0.75)
    scores = np.arange(minimum, maximum + 1)
    lower = scores.astype(float) - 0.5
    upper = scores.astype(float) + 0.5
    probabilities = norm.cdf((upper - mean) / sd) - norm.cdf((lower - mean) / sd)
    probabilities[0] += norm.cdf((minimum - 0.5 - mean) / sd)
    probabilities[-1] += 1.0 - norm.cdf((maximum + 0.5 - mean) / sd)
    probabilities *= 1.0 - p_dnp
    probabilities[int(0 - minimum)] += p_dnp
    probabilities /= probabilities.sum()
    return {
        str(int(score)): float(probability)
        for score, probability in zip(scores, probabilities, strict=True)
    }


def _normalise_pmf(pmf: Mapping[str | int, float]) -> tuple[np.ndarray, np.ndarray]:
    pairs = sorted((int(score), float(probability)) for score, probability in pmf.items())
    if not pairs or any(not math.isfinite(value) or value < 0.0 for _, value in pairs):
        raise ValueError("points PMF is empty or invalid")
    scores = np.asarray([score for score, _ in pairs], dtype=np.int16)
    probabilities = np.asarray([value for _, value in pairs], dtype=np.float64)
    if probabilities.sum() <= 0.0:
        raise ValueError("points PMF has no mass")
    probabilities /= probabilities.sum()
    return scores, probabilities


def discrete_crps(pmf: Mapping[str | int, float], actual: float) -> float:
    scores, probabilities = _normalise_pmf(pmf)
    cdf = np.cumsum(probabilities)
    # Integrate on the complete unit lattice; sparse PMFs must not compress gaps.
    # Observations outside the support contribute their distance to its nearest edge.
    lattice = np.arange(
        min(int(scores[0]), math.floor(actual)), max(int(scores[-1]), math.ceil(actual)) + 1
    )
    indices = np.searchsorted(scores, lattice, side="right") - 1
    full_cdf = np.where(indices < 0, 0.0, cdf[np.maximum(indices, 0)])
    # FPL outcomes are integral. Fractional actuals use the energy-score identity.
    if float(actual).is_integer():
        return float(np.sum(np.square(full_cdf - (lattice >= actual))))
    return float(
        np.sum(probabilities * np.abs(scores - actual))
        - 0.5
        * np.sum(
            probabilities[:, None]
            * probabilities[None, :]
            * np.abs(scores[:, None] - scores[None, :])
        )
    )


def pmf_quantile(pmf: Mapping[str | int, float], quantile: float) -> int:
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be in [0, 1]")
    scores, probabilities = _normalise_pmf(pmf)
    return int(
        scores[min(int(np.searchsorted(np.cumsum(probabilities), quantile)), len(scores) - 1)]
    )


def pmf_tail_probability(pmf: Mapping[str | int, float], threshold: int) -> float:
    scores, probabilities = _normalise_pmf(pmf)
    return float(probabilities[scores >= threshold].sum())


def pmf_cvar(pmf: Mapping[str | int, float], alpha: float = 0.10, *, lower: bool = True) -> float:
    """Expected score inside the worst (or best) alpha probability mass."""
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be in (0, 1]")
    scores, probabilities = _normalise_pmf(pmf)
    if not lower:
        scores = scores[::-1]
        probabilities = probabilities[::-1]
    remaining = alpha
    weighted = 0.0
    for score, probability in zip(scores, probabilities, strict=True):
        used = min(remaining, float(probability))
        weighted += float(score) * used
        remaining -= used
        if remaining <= 1e-12:
            break
    return weighted / alpha


def _score_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored = []
    for row in rows:
        pmf = row.get("points_pmf")
        if not isinstance(pmf, Mapping):
            continue
        actual = int(row["actual_points"])
        reference = gaussian_points_pmf(float(row["expected_points"]), 4.5)
        scored.append(
            {
                **dict(row),
                "crps": discrete_crps(pmf, actual),
                "reference_crps": discrete_crps(reference, actual),
                "p10": pmf_quantile(pmf, 0.10),
                "p25": pmf_quantile(pmf, 0.25),
                "p75": pmf_quantile(pmf, 0.75),
                "p90": pmf_quantile(pmf, 0.90),
                "haul_probability": pmf_tail_probability(pmf, 10),
                "haul": actual >= 10,
                "lower_cvar_10": pmf_cvar(pmf, 0.10, lower=True),
                "upper_cvar_10": pmf_cvar(pmf, 0.10, lower=False),
            }
        )
    if not scored:
        return {"rows": 0}
    cover50 = [row["p25"] <= row["actual_points"] <= row["p75"] for row in scored]
    cover80 = [row["p10"] <= row["actual_points"] <= row["p90"] for row in scored]
    haul_errors = [(float(row["haul_probability"]) - float(row["haul"])) ** 2 for row in scored]
    lower_breaches = [row for row in scored if row["actual_points"] < row["p10"]]
    upper_exceedances = [row for row in scored if row["actual_points"] > row["p90"]]
    return {
        "rows": len(scored),
        "mean_crps": float(np.mean([row["crps"] for row in scored])),
        "reference_mean_crps": float(np.mean([row["reference_crps"] for row in scored])),
        "crps_skill": float(
            1.0
            - np.mean([row["crps"] for row in scored])
            / max(np.mean([row["reference_crps"] for row in scored]), 1e-9)
        ),
        "interval_50_coverage": float(np.mean(cover50)),
        "interval_80_coverage": float(np.mean(cover80)),
        "interval_50_mean_width": float(np.mean([row["p75"] - row["p25"] for row in scored])),
        "interval_80_mean_width": float(np.mean([row["p90"] - row["p10"] for row in scored])),
        "p10_breach_rate": float(np.mean([row["actual_points"] < row["p10"] for row in scored])),
        "p90_exceedance_rate": float(
            np.mean([row["actual_points"] > row["p90"] for row in scored])
        ),
        "haul_brier": float(np.mean(haul_errors)),
        "lower_cvar_10_mean": float(np.mean([row["lower_cvar_10"] for row in scored])),
        "upper_cvar_10_mean": float(np.mean([row["upper_cvar_10"] for row in scored])),
        "actual_below_p10_mean": (
            float(np.mean([row["actual_points"] for row in lower_breaches]))
            if lower_breaches
            else None
        ),
        "actual_above_p90_mean": (
            float(np.mean([row["actual_points"] for row in upper_exceedances]))
            if upper_exceedances
            else None
        ),
    }


def score_distribution_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    overall = _score_rows(rows)
    by_position = {
        position: _score_rows([row for row in rows if str(row.get("position")) == position])
        for position in ("GK", "DEF", "MID", "FWD")
    }
    by_role = {
        role: _score_rows([row for row in rows if str(row.get("decision_role")) == role])
        for role in ("captain", "starter", "bench")
    }
    by_source = {
        source: _score_rows(
            [row for row in rows if str(row.get("distribution_source") or "unrecorded") == source]
        )
        for source in sorted({str(row.get("distribution_source") or "unrecorded") for row in rows})
    }
    return {
        "overall": overall,
        "by_position": by_position,
        "by_decision_role": by_role,
        "by_distribution_source": by_source,
    }


def _load_prospective_rows(result_root: Path) -> tuple[list[dict[str, Any]], list[int]]:
    rows = []
    events = set()
    if not result_root.is_dir():
        return rows, []
    # Multiple receipts may exist per event. Select by frozen decision time, not file mtime;
    # each result already checksum-locks a pre-deadline decision and final outcome.
    for event_dir in sorted(result_root.glob("event-*")):
        candidates = sorted(
            event_dir.glob("*.json"),
            key=lambda path: (
                json.loads(path.read_text(encoding="utf-8"))["frozen_evidence"][
                    "decision_created_at"
                ],
                path.name,
            ),
        )
        if not candidates:
            continue
        result = json.loads(candidates[-1].read_text(encoding="utf-8"))
        event = int(result["event"])
        for row in result.get("selected_squad_player_outcomes") or []:
            if isinstance(row.get("points_pmf"), dict):
                rows.append({"event": event, **row})
        events.add(event)
    return rows, sorted(events)


def build_distribution_scoreboard(
    *,
    result_root: Path = RESULT_ROOT,
    results_path: Path = RESULTS,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    calibration = _current_residual_calibration()
    rows, events = _load_prospective_rows(result_root)
    score = score_distribution_rows(rows)
    overall = score["overall"]
    positions = score["by_position"]
    roles = score["by_decision_role"]

    def tail_rates_are_plausible(view: Mapping[str, Any]) -> bool:
        return (
            int(view.get("rows") or 0) > 0
            and float(view.get("p10_breach_rate") or 0.0) <= 0.20
            and float(view.get("p90_exceedance_rate") or 0.0) <= 0.20
        )

    def intervals_are_plausible(view: Mapping[str, Any]) -> bool:
        return (
            0.35 <= float(view.get("interval_50_coverage") or 0.0) <= 0.65
            and 0.65 <= float(view.get("interval_80_coverage") or 0.0) <= 0.95
        )

    checks = {
        "single_distribution_method": len(score["by_distribution_source"]) == 1,
        "six_untouched_events": len(events) >= MINIMUM_EVENTS,
        "minimum_player_outcomes": int(overall.get("rows") or 0) >= MINIMUM_PLAYERS,
        "frozen_distribution_lineage": bool(rows)
        and all(str(row.get("distribution_calibration_sha256") or "") for row in rows),
        "positive_crps_skill": float(overall.get("crps_skill") or -1.0) > 0.0,
        "central_50_coverage_calibrated": 0.42
        <= float(overall.get("interval_50_coverage") or 0)
        <= 0.58,
        "central_80_coverage_calibrated": 0.72
        <= float(overall.get("interval_80_coverage") or 0)
        <= 0.88,
        "overall_p10_p90_calibrated": tail_rates_are_plausible(overall),
        "captain_tail_calibrated": int(roles["captain"].get("rows") or 0) >= MINIMUM_EVENTS
        and tail_rates_are_plausible(roles["captain"]),
        "bench_tail_calibrated": int(roles["bench"].get("rows") or 0) >= 4 * MINIMUM_EVENTS
        and tail_rates_are_plausible(roles["bench"]),
        "all_positions_scored": all(
            int(value.get("rows") or 0) >= 20 for value in positions.values()
        ),
        "position_crps_skill_positive": all(
            float(value.get("crps_skill") or -1.0) > 0.0 for value in positions.values()
        ),
        "position_intervals_calibrated": all(
            intervals_are_plausible(value) for value in positions.values()
        ),
        "position_tails_calibrated": all(
            tail_rates_are_plausible(value) for value in positions.values()
        ),
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "events": events,
        "completed_events": len(events),
        "scores": score,
        "frozen_distribution_calibration": {
            "path": str(RESIDUAL_CALIBRATION),
            "sha256": sha256_file(RESIDUAL_CALIBRATION),
            "maximum_training_season": calibration["maximum_training_season"],
        },
        "promotion_gate": {
            "passed": all(checks.values()),
            "checks": checks,
            "production_changed": False,
            "authority": "A pass authorizes challenger replay, not automatic production promotion.",
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# Full forecast-distribution calibration",
                "",
                f"**Completed untouched events:** {len(events)}  ",
                f"**Gate:** {'PASS TO REPLAY' if result['promotion_gate']['passed'] else 'HOLD SHADOW'}  ",
                "",
                "CRPS, central interval coverage, p10/p90 breaches and haul tails are scored by position and decision role.",
                "Captain and bench calibration are explicit rather than inferred from mean expected points.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result
