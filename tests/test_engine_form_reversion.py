from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_engine.features import TRAINING_FEATURES
from fplagent_engine.form_reversion import (
    _process_percentiles,
    build_form_reversion_shadow_scores,
    run_form_reversion_challenger,
)
from fplagent_engine.models import BACKTEST_FORECAST


def _historical_rows() -> list[dict]:
    rows = []
    seasons = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2019, 2026))
    positions = ("GK", "DEF", "MID", "FWD")
    for season in seasons:
        for position_offset, position in enumerate(positions):
            for player_offset in range(10):
                streak = -2.0 + (4.0 * player_offset / 9.0)
                element = 100 * position_offset + player_offset + 1
                for event in range(1, 39):
                    rows.append(
                        {
                            "season": season,
                            "event_number": event,
                            "element": element,
                            "position": position,
                            "target_points": 4.0 + 0.1 * streak,
                            "target_minutes": 90.0,
                            "history_events": 20,
                            "appearance_rate5": 1.0,
                            "form10_minutes": 90.0,
                            "form5_minutes": 90.0,
                            "fixture_count": 1,
                            "form3_points": 4.0 + streak,
                            "form10_points": 4.0,
                            "team_expected_goals": 1.2 + 0.02 * player_offset,
                            "availability_chance": 100.0,
                            "form5_xg": 0.02 * player_offset,
                            "form5_xa": 0.01 * player_offset,
                        }
                    )
    return rows


def test_form_reversion_audit_uses_lagged_forward_cohorts_and_checksums(
    tmp_path: Path,
) -> None:
    features = tmp_path / "features.parquet"
    results = tmp_path / "results.json"
    report = tmp_path / "report.md"
    pq.write_table(pa.Table.from_pylist(_historical_rows()), features)

    result = run_form_reversion_challenger(
        features_path=features,
        results_path=results,
        report_path=report,
        created_at="2026-08-08T12:00:00+00:00",
    )

    assert result["verdict"] == "AUDIT_ONLY"
    assert result["production_changed"] is False
    assert result["historical_audit"]["classification"] == "strong_mean_reversion_observed"
    regression = result["historical_audit"]["persistence_regression"]
    assert 0.05 < regression["recent_points_persistence"] < 0.15
    assert regression["cluster_bootstrap_95ci"]["p975"] < 0.25
    cohorts = result["historical_audit"]["aggregate_streak_quintiles"]
    assert cohorts[0]["forward_five_points"] > cohorts[0]["recent_three_points"]
    assert cohorts[-1]["forward_five_points"] < cohorts[-1]["recent_three_points"]
    assert result["artifacts"]["training_features_sha256"] == sha256_file(features)
    assert json.loads(results.read_text(encoding="utf-8"))["historical_audit"] == result[
        "historical_audit"
    ]
    assert not report.exists()


def test_process_percentiles_are_position_local_and_deterministic() -> None:
    rows = [
        {
            "element": 1,
            "position": "MID",
            "form5_minutes": 90,
            "form5_xg": 0.1,
            "form5_xa": 0.0,
        },
        {
            "element": 2,
            "position": "MID",
            "form5_minutes": 90,
            "form5_xg": 0.5,
            "form5_xa": 0.0,
        },
        {
            "element": 3,
            "position": "FWD",
            "form5_minutes": 90,
            "form5_xg": 0.3,
            "form5_xa": 0.0,
        },
        {
            "element": 4,
            "position": "DEF",
            "form5_minutes": 90,
            "form5_xg": 2.0,
            "form5_xa": 0.0,
        },
    ]

    percentiles = _process_percentiles(rows)

    assert percentiles == {1: 0.0, 2: 1.0, 3: 0.0}


def test_shadow_scores_regress_points_only_when_process_does_not_confirm_them(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "reversion.json"
    artifact.write_text(
        json.dumps(
            {
                "verdict": "HOLD_SHADOW",
                "artifacts": {
                    "training_features_sha256": sha256_file(TRAINING_FEATURES),
                    "incumbent_oof_sha256": sha256_file(BACKTEST_FORECAST),
                },
                "sequential_replay": {
                    "selected_score_field": "process_reversion_expected_points",
                    "selected_correction_weight": 0.1,
                },
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "event_number": 2,
            "element": 1,
            "position": "MID",
            "expected_points": 5.0,
            "form3_points": 7.0,
            "form10_points": 4.0,
            "form5_minutes": 90,
            "form5_xg": 0.1,
            "form5_xa": 0.0,
        },
        {
            "event_number": 2,
            "element": 2,
            "position": "MID",
            "expected_points": 5.0,
            "form3_points": 7.0,
            "form10_points": 4.0,
            "form5_minutes": 90,
            "form5_xg": 0.8,
            "form5_xa": 0.0,
        },
        {
            "event_number": 2,
            "element": 3,
            "position": "FWD",
            "expected_points": 4.0,
            "form3_points": 2.0,
            "form10_points": 4.0,
            "form5_minutes": 90,
            "form5_xg": 0.7,
            "form5_xa": 0.0,
        },
        {
            "event_number": 2,
            "element": 4,
            "position": "FWD",
            "expected_points": 3.0,
            "form3_points": 3.0,
            "form10_points": 4.0,
            "form5_minutes": 90,
            "form5_xg": 0.1,
            "form5_xa": 0.0,
        },
    ]

    scores, diagnostics = build_form_reversion_shadow_scores(
        rows,
        results_path=artifact,
    )

    assert scores[(2, 1)] == 4.7
    assert scores[(2, 2)] == 5.0
    assert scores[(2, 3)] == 4.2
    assert diagnostics["status"] == "ready_shadow"
    assert diagnostics["decision_authority"] is False
