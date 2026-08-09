from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .component_backtest import METRICS_JSON, OOF_FORECAST, TEST_SEASONS
from .features import TRAINING_FEATURES
from .market_odds import MARKET_RECEIPT, current_season_source_available
from .models import BACKTEST_FORECAST
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .rules import load_rules
from .tournament import _score_candidates

OUTPUT_DIR = MODEL_DATA / "market_goal_policy_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "market-goal-policy-replay.md"


def _candidate_payload(solution: dict[str, Any], event: int, candidate_id: str) -> dict[str, Any]:
    lineup = solution["lineups"][event]
    return {
        "candidate_id": candidate_id,
        "selected": list(solution["selected"]),
        "lineups": {
            str(event): {
                "starters": list(lineup["starters"]),
                "bench_order": list(lineup["bench_order"]),
                "captain": int(lineup["captain"]),
                "vice_captain": int(lineup["vice_captain"]),
            }
        },
    }


def _score_solutions(
    solutions: list[tuple[str, dict[str, Any]]],
    rows: list[dict[str, Any]],
    event: int,
) -> list[int]:
    player_ids = sorted(int(row["element"]) for row in rows)
    actual = {int(row["element"]): row for row in rows}
    points = np.asarray(
        [[[actual[player]["target_points"] for player in player_ids]]], dtype=np.int16
    )
    played = np.asarray(
        [[[actual[player]["target_minutes"] > 0 for player in player_ids]]], dtype=bool
    )
    candidates = [
        _candidate_payload(solution, event, candidate_id)
        for candidate_id, solution in solutions
    ]
    scores = _score_candidates(
        candidates,
        player_ids,
        (event,),
        points,
        played,
        {int(row["element"]): row for row in rows},
    )[0, :, 0]
    return [int(value) for value in scores]


def paired_policy_gate(event_results: list[dict[str, Any]], test_season: str) -> dict[str, Any]:
    test_rows = [row for row in event_results if row["season"] == test_season]
    if not test_rows:
        raise ValueError(f"No policy replay rows for frozen test season {test_season}")
    deltas = np.asarray([row["challenger_minus_incumbent"] for row in test_rows], dtype=float)
    standard_error = float(deltas.std(ddof=1) / np.sqrt(len(deltas))) if len(deltas) > 1 else 0.0
    mean = float(deltas.mean())
    low = mean - 1.96 * standard_error
    high = mean + 1.96 * standard_error
    checks = {
        "positive_test_mean": mean > 0.0,
        "test_lower_bound_above_minus_point_one": low > -0.10,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "test_season": test_season,
        "events": len(test_rows),
        "mean_delta": mean,
        "delta_95ci_low": low,
        "delta_95ci_high": high,
        "challenger_win_rate": float(np.mean(deltas > 0.0)),
        "tie_rate": float(np.mean(deltas == 0.0)),
    }


def _render(result: dict[str, Any]) -> str:
    gate = result["policy_gate"]
    lines = [
        "# Pre-closing market goal-rate legal policy replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — validation selected a {result['market_raw_weight']:.0%} "
            "market-component blend. On the untouched 2025/26 legal-squad replay it changed "
            f"realised points by {gate['mean_delta']:+.3f} per gameweek "
            f"(95% interval {gate['delta_95ci_low']:+.3f} to "
            f"{gate['delta_95ci_high']:+.3f})."
        ),
        "",
        "Every event independently selects a legal £100m 15-player squad, XI, bench order, captain and vice-captain. Both policies are scored on identical realised points and minutes with formation-valid autosubs and captain fallback.",
        "Because each gameweek is rebuilt from scratch, the season totals measure ranking and selection quality; they are not an achievable transfer-policy return. A sequential transfer replay is a separate promotion requirement for in-season use.",
        "",
        "## Season results",
        "",
        "| Season | Events | Incumbent | Internal 90% control | Market challenger | Delta/GW | Market vs control |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for season, row in result["by_season"].items():
        lines.append(
            f"| {season} | {row['events']} | {row['incumbent_points']:.0f} | "
            f"{row['internal_component_control_points']:.0f} | "
            f"{row['challenger_points']:.0f} | {row['mean_delta']:+.3f} | "
            f"{row['mean_delta_vs_internal_component_control']:+.3f} |"
        )
    lines.extend(
        [
            "",
            "## Decision changes",
            "",
            f"- Exact squad unchanged: **{result['exact_squad_rate']:.1%}**",
            f"- Captain unchanged: **{result['same_captain_rate']:.1%}**",
            f"- Mean squad overlap: **{result['mean_squad_overlap']:.2f}/15**",
            "",
            "## Promotion status",
            "",
            (
                "The historical signal remains shadow-only. A live 2026/27 pre-closing source is "
                "not yet published, and no source is allowed to enter production without verified "
                "pre-deadline timestamps and complete fixture coverage."
                if not result["current_source"]["available"]
                else "The current source exists but still requires full fixture coverage and timestamp validation before promotion."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_market_goal_policy_replay() -> dict[str, Any]:
    metrics = json.loads(METRICS_JSON.read_text(encoding="utf-8"))
    topk_market_weight = float(metrics["market_challenger"]["selected_raw_weight"])
    component_rows = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(OOF_FORECAST).to_pylist()
    }
    target_minutes = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row["target_minutes"]
        )
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in TEST_SEASONS
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(row["season"])
        if season not in TEST_SEASONS:
            continue
        key = (season, int(row["event_number"]), int(row["element"]))
        component = component_rows.get(key)
        if component is None or key not in target_minutes:
            continue
        if row.get("market_price") is None or float(row["market_price"]) <= 0.0:
            continue
        grouped[(season, int(row["event_number"]))].append(
            {
                **row,
                "target_points": float(component["target_points"]),
                "target_minutes": target_minutes[key],
                "market_component_expected_points": float(
                    component["market_component_expected_points"]
                ),
                "internal_component_expected_points": float(
                    component["component_expected_points"]
                ),
                "xp_expected_points": float(component["xp_expected_points"]),
            }
        )

    rules = load_rules()
    validation_weights = [float(value) for value in np.linspace(0.0, 1.0, 11)]
    validation_totals = {weight: 0 for weight in validation_weights}
    validation_events = 0
    for (season, event), rows in sorted(grouped.items()):
        if season != "2024-25":
            continue
        solutions = []
        for weight in validation_weights:
            weighted_rows = [
                {
                    **row,
                    "expected_points": (
                        weight * row["market_component_expected_points"]
                        + (1.0 - weight) * row["xp_expected_points"]
                    ),
                }
                for row in rows
            ]
            solutions.append((f"weight-{weight:.1f}", _solve(weighted_rows, [event], rules=rules)))
        scores = _score_solutions(solutions, rows, event)
        for weight, score in zip(validation_weights, scores, strict=True):
            validation_totals[weight] += score
        validation_events += 1
    market_weight = max(validation_weights, key=lambda weight: (validation_totals[weight], -weight))
    weight_calibration = [
        {
            "raw_weight": weight,
            "validation_actual_points": validation_totals[weight],
            "validation_mean_points": validation_totals[weight] / validation_events,
        }
        for weight in validation_weights
    ]
    event_results = []
    for (season, event), rows in sorted(grouped.items()):
        incumbent_solution = _solve(rows, [event], rules=rules)
        challenger_rows = [
            {
                **row,
                "expected_points": (
                    market_weight * row["market_component_expected_points"]
                    + (1.0 - market_weight) * row["xp_expected_points"]
                ),
            }
            for row in rows
        ]
        challenger_solution = _solve(challenger_rows, [event], rules=rules)
        control_rows = [
            {
                **row,
                "expected_points": (
                    market_weight * row["internal_component_expected_points"]
                    + (1.0 - market_weight) * row["xp_expected_points"]
                ),
            }
            for row in rows
        ]
        control_solution = _solve(control_rows, [event], rules=rules)
        scores = _score_solutions(
            [
                ("incumbent", incumbent_solution),
                ("market-challenger", challenger_solution),
                ("internal-component-control", control_solution),
            ],
            rows,
            event,
        )
        incumbent_selected = set(incumbent_solution["selected"])
        challenger_selected = set(challenger_solution["selected"])
        event_results.append(
            {
                "season": season,
                "event": event,
                "incumbent_points": int(scores[0]),
                "challenger_points": int(scores[1]),
                "challenger_minus_incumbent": int(scores[1] - scores[0]),
                "internal_component_control_points": int(scores[2]),
                "challenger_minus_internal_component_control": int(scores[1] - scores[2]),
                "squad_overlap": len(incumbent_selected & challenger_selected),
                "same_squad": incumbent_selected == challenger_selected,
                "incumbent_captain": int(incumbent_solution["lineups"][event]["captain"]),
                "challenger_captain": int(challenger_solution["lineups"][event]["captain"]),
            }
        )

    policy_gate = paired_policy_gate(event_results, "2025-26")
    by_season = {}
    for season in TEST_SEASONS:
        rows = [row for row in event_results if row["season"] == season]
        deltas = np.asarray([row["challenger_minus_incumbent"] for row in rows], dtype=float)
        by_season[season] = {
            "events": len(rows),
            "incumbent_points": sum(row["incumbent_points"] for row in rows),
            "challenger_points": sum(row["challenger_points"] for row in rows),
            "internal_component_control_points": sum(
                row["internal_component_control_points"] for row in rows
            ),
            "mean_delta": float(deltas.mean()),
            "mean_delta_vs_internal_component_control": float(
                np.mean(
                    [row["challenger_minus_internal_component_control"] for row in rows]
                )
            ),
            "challenger_win_rate": float(np.mean(deltas > 0.0)),
            "tie_rate": float(np.mean(deltas == 0.0)),
        }
    current_source = current_season_source_available()
    promotable = policy_gate["passed"] and bool(current_source["available"])
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PROMOTE" if promotable else "HOLD",
        "status": "shadow" if not promotable else "production-candidate",
        "market_raw_weight": market_weight,
        "topk_selected_market_raw_weight": topk_market_weight,
        "weight_calibration": {
            "method": "maximise realised legal-squad points on 2024-25 only",
            "validation_season": "2024-25",
            "selected_raw_weight": market_weight,
            "weights": weight_calibration,
        },
        "policy_gate": policy_gate,
        "current_source": current_source,
        "by_season": by_season,
        "exact_squad_rate": float(np.mean([row["same_squad"] for row in event_results])),
        "same_captain_rate": float(
            np.mean(
                [
                    row["incumbent_captain"] == row["challenger_captain"]
                    for row in event_results
                ]
            )
        ),
        "mean_squad_overlap": float(
            np.mean([row["squad_overlap"] for row in event_results])
        ),
        "events": event_results,
        "artifacts": {
            "component_metrics": str(METRICS_JSON),
            "component_metrics_sha256": sha256_file(METRICS_JSON),
            "component_oof": str(OOF_FORECAST),
            "component_oof_sha256": sha256_file(OOF_FORECAST),
            "market_receipt": str(MARKET_RECEIPT),
            "market_receipt_sha256": sha256_file(MARKET_RECEIPT),
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
