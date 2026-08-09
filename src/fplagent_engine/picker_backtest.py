from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import highspy
import pyarrow.parquet as pq

from .models import BACKTEST_FORECAST, MODEL_DIR
from .paths import REPORTS, ensure_engine_layout

PICKER_METRICS = MODEL_DIR / "picker-backtest.json"
PICKER_REPORT = REPORTS / "picker-backtest.md"
SQUAD_POSITIONS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
STARTER_LIMITS = {"GK": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}


def _solve_event(rows: list[dict], score_key: str) -> dict[str, Any]:
    candidates = [
        row
        for row in rows
        if row["market_price"] is not None
        and row["position"] in SQUAD_POSITIONS
        and row[score_key] is not None
    ]
    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    highs.setOptionValue("random_seed", 7)
    highs.setOptionValue("mip_rel_gap", 1e-9)
    integer = highspy.HighsVarType.kInteger
    squad = highs.addVariables(
        len(candidates), lb=0, ub=1, type=integer, out_array=True
    )
    start = highs.addVariables(
        len(candidates), lb=0, ub=1, type=integer, out_array=True
    )
    captain = highs.addVariables(
        len(candidates), lb=0, ub=1, type=integer, out_array=True
    )
    highs.addConstr(sum(squad) == 15)
    highs.addConstr(sum(start) == 11)
    highs.addConstr(sum(captain) == 1)
    highs.addConstr(
        sum(float(row["market_price"]) * squad[index] for index, row in enumerate(candidates))
        <= 1000
    )
    for position, count in SQUAD_POSITIONS.items():
        indices = [
            index for index, row in enumerate(candidates) if row["position"] == position
        ]
        highs.addConstr(sum(squad[index] for index in indices) == count)
        minimum, maximum = STARTER_LIMITS[position]
        highs.addConstr(sum(start[index] for index in indices) >= minimum)
        highs.addConstr(sum(start[index] for index in indices) <= maximum)
    for team_id in sorted({int(row["team_id"]) for row in candidates}):
        highs.addConstr(
            sum(
                squad[index]
                for index, row in enumerate(candidates)
                if int(row["team_id"]) == team_id
            )
            <= 3
        )
    for index in range(len(candidates)):
        highs.addConstr(start[index] <= squad[index])
        highs.addConstr(captain[index] <= start[index])
    objective = 0
    for index, row in enumerate(candidates):
        points = float(row[score_key])
        objective += points * start[index]
        objective += points * captain[index]
        objective += 0.08 * points * (squad[index] - start[index])
    highs.maximize(objective)
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"Historical picker solve failed: {highs.getModelStatus()}")
    selected_indices = [
        index for index in range(len(candidates)) if highs.val(squad[index]) > 0.5
    ]
    starter_indices = [
        index for index in range(len(candidates)) if highs.val(start[index]) > 0.5
    ]
    captain_index = next(
        index for index in range(len(candidates)) if highs.val(captain[index]) > 0.5
    )
    actual_points = sum(
        float(candidates[index]["target_points"]) for index in starter_indices
    ) + float(candidates[captain_index]["target_points"])
    return {
        "actual_points": actual_points,
        "predicted_objective": float(highs.getObjectiveValue()),
        "budget": sum(
            float(candidates[index]["market_price"]) for index in selected_indices
        )
        / 10.0,
        "captain": candidates[captain_index]["player_name"],
        "squad": [candidates[index]["player_name"] for index in selected_indices],
        "starters": [candidates[index]["player_name"] for index in starter_indices],
    }


def evaluate_picker() -> dict[str, Any]:
    ensure_engine_layout()
    if not BACKTEST_FORECAST.exists():
        raise FileNotFoundError("Rolling forecasts missing; run fplagent train first")
    rows = pq.read_table(BACKTEST_FORECAST).to_pylist()
    seasons = sorted({row["season"] for row in rows if int(row["event_number"]) == 1})
    evaluations = []
    for season in seasons:
        event_rows = [
            row
            for row in rows
            if row["season"] == season and int(row["event_number"]) == 1
        ]
        model = _solve_event(event_rows, "expected_points")
        baseline = _solve_event(event_rows, "form5_expected_points")
        oracle = _solve_event(event_rows, "target_points")
        evaluations.append(
            {
                "season": season,
                "model": model,
                "form5": baseline,
                "oracle": oracle,
                "model_lift_vs_form5": model["actual_points"]
                - baseline["actual_points"],
            }
        )
    total_lift = sum(item["model_lift_vs_form5"] for item in evaluations)
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "seasons": evaluations,
        "summary": {
            "model_wins": sum(item["model_lift_vs_form5"] > 0 for item in evaluations),
            "ties": sum(item["model_lift_vs_form5"] == 0 for item in evaluations),
            "form5_wins": sum(item["model_lift_vs_form5"] < 0 for item in evaluations),
            "total_actual_point_lift": total_lift,
            "mean_actual_point_lift": total_lift / len(evaluations),
        },
    }
    PICKER_METRICS.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Historical GW1 picker backtest",
        "",
        (
            "Each season is a strict rolling out-of-season forecast. Both model and baseline "
            "select a legal £100m squad, XI and captain before actual GW1 points are scored."
        ),
        "",
        "| Season | Model actual | Form actual | Lift | Oracle ceiling | Model captain |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in evaluations:
        lines.append(
            f"| {item['season']} | {item['model']['actual_points']:.1f} | "
            f"{item['form5']['actual_points']:.1f} | {item['model_lift_vs_form5']:+.1f} | "
            f"{item['oracle']['actual_points']:.1f} | {item['model']['captain']} |"
        )
    lines.extend(
        [
            "",
            (
                f"Total lift: **{total_lift:+.1f} points** across {len(evaluations)} "
                "seasons. The sample is deliberately small and is a diagnostic, not a "
                "performance guarantee."
            ),
            "",
        ]
    )
    PICKER_REPORT.write_text("\n".join(lines), encoding="utf-8")
    return result
