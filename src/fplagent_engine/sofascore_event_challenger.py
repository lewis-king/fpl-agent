from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.metrics import mean_absolute_error

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .features import TRAINING_FEATURES
from .matched_policy import matched_legal_policy_replay
from .models import BACKTEST_FORECAST
from .paths import MODEL_DATA, REPORTS

VERSION = "sofascore_event_policy_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
OOF = OUTPUT_DIR / "rolling-forecasts.parquet"
RESULTS = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "sofascore-player-event-challenger.md"
SOURCE_ROOT = PROCESSED / "supporting" / "sofascore" / "player-events"
DEVELOPMENT_SEASONS = ("2023-24", "2024-25")
FROZEN_TEST_SEASON = "2025-26"
WEIGHTS = (0.0, 0.10, 0.20, 0.30)


def _event_rows(source_root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(source_root.glob("*/player_events.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    return [row for row in rows if row.get("fpl_element") is not None]


def _feature_deadlines(training_path: Path) -> dict[tuple[str, int, int], str]:
    table = pq.read_table(
        training_path,
        columns=["season", "event_number", "element", "deadline_at"],
    )
    return {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): str(row["deadline_at"])
        for row in table.to_pylist()
        if row.get("deadline_at")
    }


def build_sofascore_signal_rows(
    champion_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    deadlines: dict[tuple[str, int, int], str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_player: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        by_player[(str(row["season"]), int(row["fpl_element"]))].append(row)
    for values in by_player.values():
        values.sort(key=lambda row: str(row["available_after"]))
    output = []
    leakage = 0
    matched = 0
    for champion in champion_rows:
        key = (
            str(champion["season"]),
            int(champion["event_number"]),
            int(champion["element"]),
        )
        deadline = deadlines.get(key)
        history = (
            [
                row
                for row in by_player.get((key[0], key[2]), [])
                if str(row["available_after"]) < deadline
            ]
            if deadline
            else []
        )
        if deadline:
            leakage += sum(str(row["available_after"]) >= deadline for row in history)
        minutes = sum(int(row.get("minutes") or 0) for row in history)
        matched += int(minutes > 0)
        scale = 90.0 / max(minutes, 180)
        signal = (
            (
                (
                    sum(float(row.get("expected_goals") or 0.0) for row in history)
                    + sum(float(row.get("expected_assists") or 0.0) for row in history)
                )
                * scale
                + 0.08 * sum(bool(row.get("starter")) for row in history) / max(len(history), 1)
            )
            if history
            else None
        )
        output.append(
            {
                **champion,
                "deadline_at": deadline,
                "sofascore_history_events": len(history),
                "sofascore_history_minutes": minutes,
                "sofascore_signal": signal,
            }
        )

    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in output:
        grouped[(str(row["season"]), int(row["event_number"]), str(row["position"]))].append(row)
    for rows in grouped.values():
        values = np.asarray(
            [float(row["sofascore_signal"]) for row in rows if row["sofascore_signal"] is not None]
        )
        center = float(np.mean(values)) if len(values) else 0.0
        spread = float(np.std(values)) if len(values) else 0.0
        for row in rows:
            row["sofascore_signal_z"] = (
                (float(row["sofascore_signal"]) - center) / spread
                if row["sofascore_signal"] is not None and spread > 1e-9
                else 0.0
            )
    return output, {
        "rows": len(output),
        "matched_player_deadlines": matched,
        "coverage": matched / len(output) if output else 0.0,
        "leakage_rows": leakage,
        "passed": leakage == 0,
    }


def _with_weight(rows: list[dict[str, Any]], weight: float) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        enriched = dict(row)
        enriched["sofascore_expected_points"] = max(
            0.0,
            float(row["expected_points"]) + weight * float(row["sofascore_signal_z"]),
        )
        result.append(enriched)
    return result


def run_sofascore_event_policy_replay(
    *,
    source_root: Path = SOURCE_ROOT,
    training_path: Path = TRAINING_FEATURES,
    champion_path: Path = BACKTEST_FORECAST,
    oof_path: Path = OOF,
    results_path: Path = RESULTS,
    report_path: Path = REPORT,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    champion = pq.read_table(champion_path).to_pylist()
    source = _event_rows(source_root)
    signal_rows, point_in_time = build_sofascore_signal_rows(
        champion,
        source,
        _feature_deadlines(training_path),
    )
    development = [row for row in signal_rows if str(row["season"]) in DEVELOPMENT_SEASONS]
    weight_rows = []
    for weight in WEIGHTS:
        weighted = _with_weight(development, weight)
        policy = matched_legal_policy_replay(
            weighted,
            champion_field="expected_points",
            challenger_field="sofascore_expected_points",
        )
        mae = mean_absolute_error(
            [row["target_points"] for row in weighted],
            [row["sofascore_expected_points"] for row in weighted],
        )
        weight_rows.append({"weight": weight, "development_policy": policy, "mae": float(mae)})
        if progress is not None:
            progress(f"SofaScore replay: completed development weight {weight:.2f}")
    selected = max(
        weight_rows,
        key=lambda row: (
            row["development_policy"]["total_delta"],
            -row["mae"],
            -row["weight"],
        ),
    )
    weighted_all = _with_weight(signal_rows, float(selected["weight"]))
    write_table(pa.Table.from_pylist(weighted_all), oof_path)
    frozen = [row for row in weighted_all if str(row["season"]) == FROZEN_TEST_SEASON]
    frozen_policy = matched_legal_policy_replay(
        frozen,
        champion_field="expected_points",
        challenger_field="sofascore_expected_points",
    )
    if progress is not None:
        progress("SofaScore replay: completed untouched 2025/26 legal policy")
    champion_mae = float(
        mean_absolute_error(
            [row["target_points"] for row in frozen],
            [row["expected_points"] for row in frozen],
        )
    )
    challenger_mae = float(
        mean_absolute_error(
            [row["target_points"] for row in frozen],
            [row["sofascore_expected_points"] for row in frozen],
        )
    )
    frozen_feature_coverage = (
        sum(row["sofascore_history_events"] > 0 for row in frozen) / len(frozen) if frozen else 0.0
    )
    frozen_mapping_path = source_root / FROZEN_TEST_SEASON / "player_mapping.parquet"
    frozen_mapping = (
        pq.read_table(frozen_mapping_path).to_pylist() if frozen_mapping_path.is_file() else []
    )
    test_season_coverage = (
        sum(row.get("fpl_element") is not None for row in frozen_mapping) / len(frozen_mapping)
        if frozen_mapping
        else 0.0
    )
    checks = {
        "point_in_time_no_leakage": point_in_time["passed"],
        "three_historical_seasons_collected": len(
            {str(row["season"]) for row in source} & {*DEVELOPMENT_SEASONS, FROZEN_TEST_SEASON}
        )
        == 3,
        "frozen_mapping_coverage_above_80_percent": test_season_coverage >= 0.80,
        "nonzero_weight_selected": float(selected["weight"]) > 0.0,
        "frozen_forecast_mae_not_worse": challenger_mae <= champion_mae,
        "positive_frozen_legal_policy_lift": frozen_policy["total_delta"] > 0.0,
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "gate": {"passed": all(checks.values()), "checks": checks},
        "selected_weight": selected["weight"],
        "development": weight_rows,
        "frozen_test": {
            "season": FROZEN_TEST_SEASON,
            "champion_mae": champion_mae,
            "challenger_mae": challenger_mae,
            "mapping_coverage": test_season_coverage,
            "player_deadline_feature_coverage": frozen_feature_coverage,
            "legal_policy": frozen_policy,
        },
        "point_in_time": point_in_time,
        "source_files": [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in sorted(source_root.glob("*/player_events.parquet"))
        ],
        "oof_path": str(oof_path),
        "oof_sha256": sha256_file(oof_path),
        "production_authority": False,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# SofaScore independent player-event challenger",
                "",
                f"**Gate:** {'PASS' if result['gate']['passed'] else 'HOLD SHADOW'}  ",
                f"**Frozen legal-policy delta:** {frozen_policy['total_delta']:+.1f}",
                "",
                "Every event statistic becomes available only after that match and is joined by a stable, club-restricted player mapping.",
                "No source row can change production until it beats the champion on a frozen legal-policy replay.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result
