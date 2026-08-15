from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .horizon_decay_replay import (
    RESULTS_JSON as HORIZON_REPLAY_RESULTS,
)
from .horizon_decay_replay import SELECTION_SEASONS, TEST_SEASON
from .paths import MODEL_DATA, REPORTS

VERSION = "synthesis_selector_replay_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "synthesis-selector-policy-replay.md"

DEFAULT_HORIZON_WEIGHT = 0.50
DEFAULT_WORST_WEIGHT = 0.20
HORIZON_WEIGHTS = (0.25, 0.50, 0.75)
WORST_WEIGHTS = (0.0, 0.20, 0.40)
SHORT_END_EVENT = 5
LONG_END_EVENT = 8


def _event_total(path: dict[str, Any], end_event: int) -> int:
    return int(
        sum(
            int(row["net_points"])
            for row in path["events"]
            if int(row["event"]) <= end_event
        )
    )


def family_regrets(
    paths: dict[tuple[str, str], dict[str, Any]],
    *,
    seasons: tuple[str, ...],
    config_ids: tuple[str, ...],
) -> dict[str, dict[str, dict[str, float]]]:
    """Create short- and long-horizon realised regret families by season."""
    output: dict[str, dict[str, dict[str, float]]] = {}
    for season in seasons:
        short = {
            config_id: _event_total(paths[(season, config_id)], SHORT_END_EVENT)
            for config_id in config_ids
        }
        long = {
            config_id: _event_total(paths[(season, config_id)], LONG_END_EVENT)
            for config_id in config_ids
        }
        best_short = max(short.values())
        best_long = max(long.values())
        output[season] = {
            config_id: {
                "short_points": float(short[config_id]),
                "long_points": float(long[config_id]),
                "short_regret": float(best_short - short[config_id]),
                "long_regret": float(best_long - long[config_id]),
            }
            for config_id in config_ids
        }
    return output


def select_candidate(
    regrets: dict[str, dict[str, dict[str, float]]],
    *,
    seasons: tuple[str, ...],
    config_ids: tuple[str, ...],
    horizon_weight: float,
    worst_weight: float,
) -> tuple[str, list[dict[str, Any]]]:
    if not 0.0 <= horizon_weight <= 1.0 or not 0.0 <= worst_weight <= 1.0:
        raise ValueError("Selector weights must be in [0, 1]")
    rows = []
    for config_id in config_ids:
        short = float(np.mean([regrets[season][config_id]["short_regret"] for season in seasons]))
        long = float(np.mean([regrets[season][config_id]["long_regret"] for season in seasons]))
        weighted = (1.0 - horizon_weight) * short + horizon_weight * long
        family_worst = max(short, long)
        score = (1.0 - worst_weight) * weighted + worst_weight * family_worst
        total = sum(
            regrets[season][config_id]["long_points"] for season in seasons
        )
        rows.append(
            {
                "config_id": config_id,
                "short_family_regret": short,
                "long_family_regret": long,
                "family_worst_regret": family_worst,
                "synthesis_regret": score,
                "long_points": total,
            }
        )
    rows.sort(key=lambda row: (row["synthesis_regret"], -row["long_points"], row["config_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return str(rows[0]["config_id"]), rows


def calibrate_selector(
    paths: dict[tuple[str, str], dict[str, Any]],
    *,
    selection_seasons: tuple[str, ...] = SELECTION_SEASONS,
    test_season: str = TEST_SEASON,
    horizon_weights: tuple[float, ...] = HORIZON_WEIGHTS,
    worst_weights: tuple[float, ...] = WORST_WEIGHTS,
) -> dict[str, Any]:
    if len(selection_seasons) < 2:
        raise ValueError("Selector calibration needs at least two selection seasons")
    config_ids = tuple(sorted({config_id for _, config_id in paths}))
    required = {(season, config_id) for season in (*selection_seasons, test_season) for config_id in config_ids}
    missing = required - set(paths)
    if missing:
        raise ValueError(f"Historical selector paths are incomplete: {sorted(missing)[:5]}")
    regrets = family_regrets(
        paths,
        seasons=(*selection_seasons, test_season),
        config_ids=config_ids,
    )
    grid = []
    for horizon_weight in horizon_weights:
        for worst_weight in worst_weights:
            folds = []
            for heldout in selection_seasons:
                training = tuple(season for season in selection_seasons if season != heldout)
                winner, _ = select_candidate(
                    regrets,
                    seasons=training,
                    config_ids=config_ids,
                    horizon_weight=horizon_weight,
                    worst_weight=worst_weight,
                )
                folds.append(
                    {
                        "heldout_season": heldout,
                        "winner": winner,
                        "long_regret": regrets[heldout][winner]["long_regret"],
                    }
                )
            fold_regrets = [float(row["long_regret"]) for row in folds]
            score = 0.80 * float(np.mean(fold_regrets)) + 0.20 * max(fold_regrets)
            grid.append(
                {
                    "horizon_family_weight": horizon_weight,
                    "family_worst_weight": worst_weight,
                    "leave_one_season_out": folds,
                    "mean_long_regret": float(np.mean(fold_regrets)),
                    "worst_long_regret": max(fold_regrets),
                    "selection_score": score,
                }
            )
    grid.sort(
        key=lambda row: (
            row["selection_score"],
            abs(row["horizon_family_weight"] - DEFAULT_HORIZON_WEIGHT)
            + abs(row["family_worst_weight"] - DEFAULT_WORST_WEIGHT),
            row["horizon_family_weight"],
            row["family_worst_weight"],
        )
    )
    selected = grid[0]
    incumbent = next(
        row
        for row in grid
        if row["horizon_family_weight"] == DEFAULT_HORIZON_WEIGHT
        and row["family_worst_weight"] == DEFAULT_WORST_WEIGHT
    )
    selected_winner, selected_ranking = select_candidate(
        regrets,
        seasons=selection_seasons,
        config_ids=config_ids,
        horizon_weight=float(selected["horizon_family_weight"]),
        worst_weight=float(selected["family_worst_weight"]),
    )
    incumbent_winner, incumbent_ranking = select_candidate(
        regrets,
        seasons=selection_seasons,
        config_ids=config_ids,
        horizon_weight=DEFAULT_HORIZON_WEIGHT,
        worst_weight=DEFAULT_WORST_WEIGHT,
    )
    test_delta = (
        regrets[test_season][selected_winner]["long_points"]
        - regrets[test_season][incumbent_winner]["long_points"]
    )
    selected_fold = {
        str(row["heldout_season"]): float(row["long_regret"])
        for row in selected["leave_one_season_out"]
    }
    incumbent_fold = {
        str(row["heldout_season"]): float(row["long_regret"])
        for row in incumbent["leave_one_season_out"]
    }
    changed = (
        float(selected["horizon_family_weight"]) != DEFAULT_HORIZON_WEIGHT
        or float(selected["family_worst_weight"]) != DEFAULT_WORST_WEIGHT
    )
    checks = {
        "candidate_differs_from_incumbent": changed,
        "strict_selection_score_improvement": float(selected["selection_score"])
        < float(incumbent["selection_score"]),
        "non_negative_each_selection_fold": all(
            selected_fold[season] <= incumbent_fold[season] for season in selection_seasons
        ),
        "positive_untouched_test_delta": test_delta > 0,
    }
    promote = changed and all(checks.values())
    production = selected if promote else incumbent
    return {
        "verdict": "PROMOTE" if promote else "RETAIN_INCUMBENT",
        "production_changed": promote,
        "selection_configuration": {
            "horizon_family_weight": selected["horizon_family_weight"],
            "family_worst_weight": selected["family_worst_weight"],
        },
        "incumbent_configuration": {
            "horizon_family_weight": DEFAULT_HORIZON_WEIGHT,
            "family_worst_weight": DEFAULT_WORST_WEIGHT,
        },
        "production_configuration": {
            "horizon_family_weight": production["horizon_family_weight"],
            "family_worst_weight": production["family_worst_weight"],
        },
        "selected_historical_policy": selected_winner,
        "incumbent_historical_policy": incumbent_winner,
        "untouched_test_delta": test_delta,
        "promotion_gate": {"passed": promote, "checks": checks},
        "selection_grid": grid,
        "selected_ranking": selected_ranking,
        "incumbent_ranking": incumbent_ranking,
        "family_definition": {
            "short": "realised legal policy points through GW5",
            "long": "realised legal policy points through GW8",
            "evaluation": "GW8 realised legal policy points",
        },
    }


def _render(result: dict[str, Any]) -> str:
    production = result["production_configuration"]
    selected = result["selection_configuration"]
    gate = result["promotion_gate"]
    lines = [
        "# Final synthesis selector: historical replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}**. Production remains horizon-family weight "
            f"**{production['horizon_family_weight']:.2f}** and worst-family surcharge "
            f"**{production['family_worst_weight']:.2f}**."
        ),
        "",
        (
            "This replays the same selector shape used by the live synthesis. Candidate policies "
            "are compared in a short realised family (GW1–5) and a long realised family "
            "(GW1–8). Weights are selected by leave-one-season-out regret on 2023/24 and "
            "2024/25, then frozen against untouched 2025/26. It calibrates the selector, not the "
            "identity of any 2026/27 player."
        ),
        "",
        (
            f"Grid choice: horizon {selected['horizon_family_weight']:.2f}, worst "
            f"{selected['family_worst_weight']:.2f}; untouched delta versus incumbent-selected "
            f"historical policy: {result['untouched_test_delta']:+.0f} points."
        ),
        "",
        "## Promotion gate",
        "",
    ]
    for name, passed in gate["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend(
        [
            "",
            (
                "A different weight pair receives production authority only if it improves the "
                "selection score, is no worse in either selection fold, and wins on the "
                "untouched season. Otherwise 0.50 / 0.20 is retained."
            ),
            "",
            "## Grid",
            "",
            "| Horizon weight | Worst surcharge | Mean LOO regret | Worst LOO regret | Score |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["selection_grid"]:
        lines.append(
            f"| {row['horizon_family_weight']:.2f} | {row['family_worst_weight']:.2f} | "
            f"{row['mean_long_regret']:.2f} | {row['worst_long_regret']:.2f} | "
            f"{row['selection_score']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            (
                "Only three recent opening windows are available and two are used for "
                "selection. That is enough to reject unsupported tuning, not enough to estimate "
                "a universal constant. Historical player identities are never copied into the "
                "current squad."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_synthesis_selector_replay(
    *,
    horizon_results_path: Path = HORIZON_REPLAY_RESULTS,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not horizon_results_path.is_file():
        raise FileNotFoundError("Run calibrate-horizon-decay before calibrating synthesis")
    horizon = json.loads(horizon_results_path.read_text(encoding="utf-8"))
    paths = {
        tuple(key.split(":", 1)): value for key, value in horizon["paths"].items()
    }
    result = {
        "version": VERSION,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "selection_seasons": list(SELECTION_SEASONS),
        "untouched_test_season": TEST_SEASON,
        **calibrate_selector(paths),
        "artifacts": {
            "horizon_decay_replay": str(horizon_results_path),
            "horizon_decay_replay_sha256": sha256_file(horizon_results_path),
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render(result), encoding="utf-8")
    return result
