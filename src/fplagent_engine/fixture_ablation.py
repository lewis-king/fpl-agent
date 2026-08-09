from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .features import (
    LEGACY_MODEL_FEATURES,
    MODEL_FEATURES,
    RAW_OR_OFFICIAL_TEAM_FEATURES,
    TRAINING_FEATURES,
)
from .models import (
    TEST_SEASONS,
    _backtest,
    _matrix,
    _numeric,
    _strings,
    require_cuda,
)
from .paths import ARTIFACTS, REPORTS, ensure_engine_layout
from .picker_backtest import _solve_event

ABLATION_DIR = ARTIFACTS / "fixture_ablation_v1"
ABLATION_METRICS = ABLATION_DIR / "metrics.json"
ABLATION_REPORT = REPORTS / "fixture-context-ablation.md"

FIXTURE_IDENTITY_FEATURES = ("fixture_count", "home_fraction")
PLAYER_ONLY_FEATURES = tuple(
    feature
    for feature in LEGACY_MODEL_FEATURES
    if feature
    not in (
        *FIXTURE_IDENTITY_FEATURES,
        *RAW_OR_OFFICIAL_TEAM_FEATURES,
    )
)
ADJUSTED_BASE_FEATURES = (
    "adjusted_team_attack",
    "adjusted_team_defence",
    "adjusted_opponent_attack",
    "adjusted_opponent_defence",
    "team_promoted_prior",
    "opponent_promoted_prior",
    "team_rating_matches",
    "opponent_rating_matches",
    "team_rating_days_since_match",
    "opponent_rating_days_since_match",
)
OPPONENT_ADJUSTED_FEATURES = (
    *PLAYER_ONLY_FEATURES,
    *FIXTURE_IDENTITY_FEATURES,
    *ADJUSTED_BASE_FEATURES,
)

FEATURE_SETS = {
    "player_only": PLAYER_ONLY_FEATURES,
    "legacy_official_raw": LEGACY_MODEL_FEATURES,
    "opponent_adjusted": OPPONENT_ADJUSTED_FEATURES,
    "opponent_adjusted_home_away": MODEL_FEATURES,
}


def _summarize(slices: list[dict[str, Any]]) -> dict[str, float | int]:
    return {
        "slices": len(slices),
        "mae": float(np.mean([row["mae"] for row in slices])),
        "rmse": float(np.mean([row["rmse"] for row in slices])),
        "mean_gameweek_spearman": float(
            np.mean([row["mean_gameweek_spearman"] for row in slices])
        ),
        "top_k_actual_points": float(
            np.mean([row["top_k_actual_points"] for row in slices])
        ),
        "gw1_top_k_actual_points": float(
            np.mean([row["gw1_top_k_actual_points"] for row in slices])
        ),
        "play_brier": float(np.mean([row["play_brier"] for row in slices])),
    }


def _forecast_rows(table: pa.Table, predictions: list[dict]) -> list[dict]:
    metadata = table.select(
        [
            "season",
            "event_number",
            "element",
            "player_name",
            "position",
            "team_id",
            "market_price",
            "target_points",
        ]
    ).to_pylist()
    rows = []
    for prediction in predictions:
        prediction = dict(prediction)
        row = dict(metadata[prediction.pop("row_index")])
        row.update(prediction)
        rows.append(row)
    return rows


def _picker_summary(rows: list[dict]) -> dict:
    seasons = sorted(
        {row["season"] for row in rows if int(row["event_number"]) == 1}
    )
    results = []
    for season in seasons:
        selected = [
            row
            for row in rows
            if row["season"] == season and int(row["event_number"]) == 1
        ]
        solved = _solve_event(selected, "expected_points")
        results.append(
            {
                "season": season,
                "actual_points": solved["actual_points"],
                "captain": solved["captain"],
                "budget": solved["budget"],
                "squad": solved["squad"],
            }
        )
    return {
        "seasons": results,
        "total_actual_points": float(sum(row["actual_points"] for row in results)),
        "mean_actual_points": float(np.mean([row["actual_points"] for row in results])),
    }


def run_fixture_ablation() -> dict[str, Any]:
    """Run the preregistered fixture champion/challenger experiment on CUDA."""
    ensure_engine_layout()
    if not TRAINING_FEATURES.exists():
        raise FileNotFoundError("Training features missing; run fplagent prepare first")
    gpu = require_cuda()
    table = pq.read_table(TRAINING_FEATURES)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _numeric(table, "event_number").astype(np.int16)
    target_points = _numeric(table, "target_points")
    target_minutes = _numeric(table, "target_minutes")
    minute_classes = _numeric(table, "minutes_class").astype(np.int32)
    form5 = _numeric(table, "form5_points")
    availability = _numeric(table, "availability_chance")
    ABLATION_DIR.mkdir(parents=True, exist_ok=True)

    variants = {}
    for name, feature_names in FEATURE_SETS.items():
        matrix = _matrix(table, feature_names)
        slices, predictions = _backtest(
            matrix,
            seasons,
            positions,
            events,
            target_points,
            target_minutes,
            minute_classes,
            form5,
            availability,
        )
        forecasts = _forecast_rows(table, predictions)
        output = ABLATION_DIR / f"{name}.parquet"
        pq.write_table(pa.Table.from_pylist(forecasts), output, compression="zstd")
        variants[name] = {
            "feature_count": len(feature_names),
            "features": feature_names,
            "summary": _summarize(slices),
            "by_slice": slices,
            "gw1_legal_picker": _picker_summary(forecasts),
            "forecast": str(output),
        }
    champion = variants["legacy_official_raw"]
    challenger = variants["opponent_adjusted_home_away"]
    champion_slices = champion["by_slice"]
    challenger_slices = challenger["by_slice"]
    comparisons = []
    for legacy, adjusted in zip(champion_slices, challenger_slices, strict=True):
        if (legacy["season"], legacy["position"]) != (
            adjusted["season"],
            adjusted["position"],
        ):
            raise RuntimeError("Ablation slices are not aligned")
        comparisons.append(
            {
                "season": legacy["season"],
                "position": legacy["position"],
                "mae_lift": legacy["mae"] - adjusted["mae"],
                "rank_lift": adjusted["mean_gameweek_spearman"]
                - legacy["mean_gameweek_spearman"],
                "top_k_lift": adjusted["top_k_actual_points"]
                - legacy["top_k_actual_points"],
                "gw1_top_k_lift": adjusted["gw1_top_k_actual_points"]
                - legacy["gw1_top_k_actual_points"],
            }
        )
    legacy_summary = champion["summary"]
    adjusted_summary = challenger["summary"]
    gate = {
        "preregistered_before_frozen_run": True,
        "frozen_seasons": list(TEST_SEASONS),
        "mae_not_worse_by_more_than_0_01": adjusted_summary["mae"]
        <= legacy_summary["mae"] + 0.01,
        "rank_not_worse_by_more_than_0_002": adjusted_summary[
            "mean_gameweek_spearman"
        ]
        >= legacy_summary["mean_gameweek_spearman"] - 0.002,
        "mean_top_k_improves": adjusted_summary["top_k_actual_points"]
        > legacy_summary["top_k_actual_points"],
        "top_k_slice_wins_at_least_half": sum(
            row["top_k_lift"] >= 0 for row in comparisons
        )
        >= len(comparisons) // 2,
    }
    gate["passed"] = all(
        value for key, value in gate.items() if key not in {"frozen_seasons"}
    )
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "gpu": gpu,
        "official_fpl_strength_used_by_challenger": False,
        "variants": variants,
        "champion_challenger": {
            "champion": "legacy_official_raw",
            "challenger": "opponent_adjusted_home_away",
            "slice_comparisons": comparisons,
            "mean_lifts": {
                "mae": legacy_summary["mae"] - adjusted_summary["mae"],
                "rank": adjusted_summary["mean_gameweek_spearman"]
                - legacy_summary["mean_gameweek_spearman"],
                "top_k": adjusted_summary["top_k_actual_points"]
                - legacy_summary["top_k_actual_points"],
                "gw1_top_k": adjusted_summary["gw1_top_k_actual_points"]
                - legacy_summary["gw1_top_k_actual_points"],
                "legal_gw1_total": challenger["gw1_legal_picker"][
                    "total_actual_points"
                ]
                - champion["gw1_legal_picker"]["total_actual_points"],
            },
            "promotion_gate": gate,
        },
    }
    ABLATION_METRICS.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(result)
    return result


def _write_report(result: dict[str, Any]) -> None:
    variants = result["variants"]
    comparison = result["champion_challenger"]
    lines = [
        "# Fixture-context champion/challenger",
        "",
        (
            "All variants use the same rolling seasons, position models, targets and "
            "CUDA training. Only the feature contract changes. The full challenger "
            "does not consume FPL's official team-strength ratings."
        ),
        "",
        "| Variant | Features | MAE | Rank | Top-k actual | GW1 top-k | Legal GW1 total |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, variant in variants.items():
        summary = variant["summary"]
        lines.append(
            f"| {name} | {variant['feature_count']} | {summary['mae']:.4f} | "
            f"{summary['mean_gameweek_spearman']:.4f} | "
            f"{summary['top_k_actual_points']:.3f} | "
            f"{summary['gw1_top_k_actual_points']:.3f} | "
            f"{variant['gw1_legal_picker']['total_actual_points']:.1f} |"
        )
    gate = comparison["promotion_gate"]
    lines.extend(
        [
            "",
            "## Preregistered promotion gate",
            "",
            f"Result: **{'PASS' if gate['passed'] else 'FAIL'}**",
            "",
            *[
                f"- {'PASS' if value else 'FAIL'} — {key.replace('_', ' ')}"
                for key, value in gate.items()
                if isinstance(value, bool) and key != "preregistered_before_frozen_run"
            ],
            "",
            (
                "The three-season legal GW1 replay is reported as a high-variance "
                "diagnostic and is deliberately not a promotion condition."
            ),
            "",
        ]
    )
    ABLATION_REPORT.write_text("\n".join(lines), encoding="utf-8")
