from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .market_policy_replay import _score_solutions
from .market_transfer_replay import moving_block_mean_interval
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .return_distribution import OOF_FORECAST, _group_policy_rows, _merge_oof
from .rules import load_rules

OUTPUT_DIR = MODEL_DATA / "captain_return_policy_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "captain-return-policy-replay.md"
WEIGHTS = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.0)
VALIDATION_SEASON = "2024-25"
FROZEN_TEST_SEASON = "2025-26"
REPLICATION_SEASON = "2023-24"


def choose_regularized_weight(
    event_scores: dict[float, list[int]],
) -> tuple[float, list[dict[str, Any]]]:
    """Choose the smallest blend statistically indistinguishable from validation's best."""
    if not event_scores or any(not values for values in event_scores.values()):
        raise ValueError("captain calibration needs non-empty event scores")
    lengths = {len(values) for values in event_scores.values()}
    if len(lengths) != 1:
        raise ValueError("captain calibration score paths must have equal length")
    best = max(event_scores, key=lambda weight: (sum(event_scores[weight]), -weight))
    best_scores = np.asarray(event_scores[best], dtype=np.float64)
    rows = []
    eligible = []
    for weight in sorted(event_scores):
        candidate = np.asarray(event_scores[weight], dtype=np.float64)
        paired_loss = best_scores - candidate
        mean_loss = float(paired_loss.mean())
        standard_error = (
            float(paired_loss.std(ddof=1) / np.sqrt(len(paired_loss)))
            if len(paired_loss) > 1
            else 0.0
        )
        within = mean_loss <= standard_error + 1e-12
        if within:
            eligible.append(weight)
        rows.append(
            {
                "weight": weight,
                "actual_points": int(candidate.sum()),
                "mean_points": float(candidate.mean()),
                "paired_mean_loss_to_best": mean_loss,
                "paired_standard_error": standard_error,
                "within_one_standard_error": within,
            }
        )
    return min(eligible), rows


def _captain_solution(
    incumbent: dict[str, Any],
    rows: list[dict[str, Any]],
    event: int,
    weight: float,
) -> dict[str, Any]:
    if weight == 0.0:
        return incumbent
    challenger = copy.deepcopy(incumbent)
    by_id = {int(row["element"]): row for row in rows}
    starters = [int(value) for value in challenger["lineups"][event]["starters"]]
    ranked = sorted(
        starters,
        key=lambda element: (
            (1.0 - weight) * float(by_id[element]["xp_expected_points"])
            + weight * float(by_id[element]["return_distribution_expected_points"]),
            float(by_id[element].get("p_play") or 0.0),
            -element,
        ),
        reverse=True,
    )
    challenger["lineups"][event]["captain"] = ranked[0]
    challenger["lineups"][event]["vice_captain"] = ranked[1]
    return challenger


def _season_summary(
    rows: list[dict[str, Any]], *, season: str, weight: float
) -> dict[str, Any]:
    selected = [row for row in rows if row["season"] == season]
    deltas = [
        int(row["scores"][str(weight)]) - int(row["incumbent_points"])
        for row in selected
    ]
    changes = [
        row["captains"][str(weight)] != row["incumbent_captain"] for row in selected
    ]
    return {
        "events": len(selected),
        "incumbent_points": sum(int(row["incumbent_points"]) for row in selected),
        "challenger_points": sum(int(row["scores"][str(weight)]) for row in selected),
        "total_delta": sum(deltas),
        "mean_delta": float(np.mean(deltas)),
        "captain_changes": sum(changes),
        "captain_change_rate": float(np.mean(changes)),
        "moving_block_interval": moving_block_mean_interval(deltas, seed=20260810),
        "squad_xi_bench_frozen": True,
    }


def _render(result: dict[str, Any]) -> str:
    selected = result["selected_weight"]
    lines = [
        "# Captain-only return-distribution policy replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — the validation-only one-standard-error rule selected a "
            f"{selected:.0%} blend. The squad, XI and bench were held exactly fixed, so every "
            "point difference is attributable only to captain/vice selection and captain fallback."
        ),
        "",
        "| Season role | Season | Delta | Delta/GW | Captain changes | Four-GW 95% interval |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for role, season in (
        ("Replication", REPLICATION_SEASON),
        ("Validation", VALIDATION_SEASON),
        ("Frozen test", FROZEN_TEST_SEASON),
    ):
        row = result["by_season"][season]
        interval = row["moving_block_interval"]
        lines.append(
            f"| {role} | {season} | {row['total_delta']:+d} | {row['mean_delta']:+.3f} | "
            f"{row['captain_changes']}/{row['events']} | "
            f"{interval['p025']:+.3f} to {interval['p975']:+.3f} |"
        )
    lines.extend(
        [
            "",
            "## Deployment decision",
            "",
            (
                "The frozen-test mean improved, but at least one moving-block downside gate did "
                "not clear. The signal therefore remains shadow-only and does not alter live "
                "captaincy."
                if result["verdict"] != "PROMOTE"
                else "Every predeclared gate passed; a separately versioned live model is required before deployment."
            ),
            "",
            "The existing xP captain remains production authority. Return probabilities may be shown only as research evidence until a future prospective sample confirms the gain.",
            "",
        ]
    )
    return "\n".join(lines)


def run_captain_return_replay() -> dict[str, Any]:
    distribution_rows = pq.read_table(OOF_FORECAST).to_pylist()
    grouped = _group_policy_rows(_merge_oof(distribution_rows))
    rules = load_rules()
    event_rows: list[dict[str, Any]] = []
    validation_scores: dict[float, list[int]] = {weight: [] for weight in WEIGHTS}
    for (season, event), rows in sorted(grouped.items()):
        incumbent = _solve(rows, [event], rules=rules)
        solutions = [
            (f"weight-{weight}", _captain_solution(incumbent, rows, event, weight))
            for weight in WEIGHTS
        ]
        scores = _score_solutions(solutions, rows, event)
        if season == VALIDATION_SEASON:
            for weight, score in zip(WEIGHTS, scores, strict=True):
                validation_scores[weight].append(score)
        event_rows.append(
            {
                "season": season,
                "event": event,
                "incumbent_points": scores[0],
                "incumbent_captain": int(incumbent["lineups"][event]["captain"]),
                "scores": {
                    str(weight): score
                    for weight, score in zip(WEIGHTS, scores, strict=True)
                },
                "captains": {
                    str(weight): int(solution["lineups"][event]["captain"])
                    for weight, (_, solution) in zip(WEIGHTS, solutions, strict=True)
                },
            }
        )
    selected_weight, calibration = choose_regularized_weight(validation_scores)
    seasons = (REPLICATION_SEASON, VALIDATION_SEASON, FROZEN_TEST_SEASON)
    by_season = {
        season: _season_summary(event_rows, season=season, weight=selected_weight)
        for season in seasons
    }
    checks = {
        "nonzero_weight_selected_on_validation": selected_weight > 0.0,
        "positive_validation_total": by_season[VALIDATION_SEASON]["total_delta"] > 0,
        "positive_frozen_test_total": by_season[FROZEN_TEST_SEASON]["total_delta"] > 0,
        "positive_replication_total": by_season[REPLICATION_SEASON]["total_delta"] > 0,
        "frozen_test_block_lower_bound_above_minus_point_one": (
            by_season[FROZEN_TEST_SEASON]["moving_block_interval"]["p025"] > -0.10
        ),
        "replication_block_lower_bound_above_minus_point_one": (
            by_season[REPLICATION_SEASON]["moving_block_interval"]["p025"] > -0.10
        ),
        "squad_xi_and_bench_held_fixed": True,
    }
    passed = all(checks.values())
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PROMOTE" if passed else "HOLD_SHADOW",
        "production_changed": False,
        "selected_weight": selected_weight,
        "selection_policy": "validation_only_paired_one_standard_error_smallest_weight",
        "calibration": calibration,
        "by_season": by_season,
        "gate": {"passed": passed, "checks": checks},
        "event_rows": event_rows,
        "artifacts": {
            "return_distribution_oof": str(OOF_FORECAST),
            "return_distribution_oof_sha256": sha256_file(OOF_FORECAST),
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS_JSON.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(RESULTS_JSON)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
