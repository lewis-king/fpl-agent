from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_engine.cli import parser
from fplagent_engine.sota_readiness import build_sota_readiness_audit


def _json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def _inputs(tmp_path: Path) -> dict:
    metrics = _json(
        tmp_path / "metrics.json",
        {
            "backtest_gate": {
                "passed": True,
                "mae_wins_vs_form5": 11,
                "top_k_wins_vs_form5": 11,
                "slices": 12,
                "mean_top_k_lift": 0.5,
            }
        },
    )
    picker = _json(
        tmp_path / "picker.json",
        {
            "seasons": [{}, {}, {}],
            "summary": {
                "model_wins": 2,
                "ties": 1,
                "form5_wins": 0,
                "total_actual_point_lift": 18,
            },
        },
    )
    quality = _json(
        tmp_path / "quality.json",
        {"checks": [{} for _ in range(22)], "failed_checks": []},
    )
    robust = _json(
        tmp_path / "robust.json",
        {
            "created_at": "2026-08-15T08:00:00+00:00",
            "leader": {"candidate_id": "R-robust"},
            "funnel": {
                "combined_universe": 550_000,
                "one_swap_universe": 290_000,
                "local_two_swap_universe": 530_000,
                "holdout_simulations": 25_000,
            },
            "global_challenge": {
                "finalists": 8,
                "milp_generated": 256,
                "evolution_generated": 20_000,
            },
        },
    )
    horizon = _json(
        tmp_path / "horizon.json",
        {
            "created_at": "2026-08-15T08:10:00+00:00",
            "leader": {"candidate_id": "R-horizon"},
            "funnel": {"deep_finalists": 48, "holdout_simulations": 25_000},
        },
    )
    structure = _json(
        tmp_path / "structure.json",
        {"publishable": True, "checks": {"rules": True, "autosubs": True}},
    )
    prospective = _json(tmp_path / "prospective.json", {"completed_events": 0})
    participation = _json(
        tmp_path / "participation.json",
        {"promotion_gate": {"passed": False, "qualifying_events": 0}},
    )
    market = _json(
        tmp_path / "market.json",
        {
            "verdict": "PROMOTE_PRESEASON_ONLY",
            "production_policy": {
                "preseason_decision_authority": True,
                "preseason_weight": 0.2,
            },
        },
    )
    pack = _json(
        tmp_path / "pack.json",
        {
            "publishable": True,
            "verdict": "DEADLINE_READY",
            "decision": {"candidate_id": "R-selected"},
            "gates": {"a": {"passed": True}, "b": {"passed": True}},
            "market": {
                "fixture_count": 10,
                "defender_feature": {"status": "applied"},
            },
        },
    )
    registry = tmp_path / "registry.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"feature": "xP", "production_allowed": False},
                {"feature": "form5_xg", "production_allowed": True},
            ]
        ),
        registry,
    )
    robust_report = tmp_path / "robust.md"
    robust_report.write_text("R-robust 2026-08-15T08:00:00+00:00", encoding="utf-8")
    horizon_report = tmp_path / "horizon.md"
    horizon_report.write_text("R-horizon 2026-08-15T08:10:00+00:00", encoding="utf-8")
    return {
        "forecast_metrics_path": metrics,
        "picker_backtest_path": picker,
        "data_quality_path": quality,
        "robust_results_path": robust,
        "horizon_results_path": horizon,
        "structure_results_path": structure,
        "prospective_results_path": prospective,
        "participation_results_path": participation,
        "market_results_path": market,
        "deadline_pack_path": pack,
        "feature_registry_path": registry,
        "robust_report_path": robust_report,
        "horizon_report_path": horizon_report,
        "external_benchmark_path": tmp_path / "no-external-benchmark.json",
        "external_player_data_path": tmp_path / "no-external-player-data.json",
        "results_path": tmp_path / "results.json",
        "report_path": tmp_path / "report.md",
    }


def test_readiness_separates_deadline_quality_from_unproven_sota(tmp_path: Path) -> None:
    result = build_sota_readiness_audit(**_inputs(tmp_path))

    assert result["production_ready"] is True
    assert result["sota_proven"] is False
    assert result["verdict"] == "DEADLINE_GRADE_RESEARCH_SYSTEM_NOT_SOTA_PROVEN"
    by_key = {row["key"]: row for row in result["checks"]}
    assert by_key["official_forecast_independence"]["state"] == "pass"
    assert by_key["independent_player_data"]["state"] == "not_ready"
    assert by_key["external_forecast_benchmark"]["state"] == "not_ready"


def test_stale_human_report_blocks_production_readiness(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    Path(inputs["robust_report_path"]).write_text("old candidate", encoding="utf-8")

    result = build_sota_readiness_audit(**inputs)

    assert result["production_ready"] is False
    assert result["verdict"] == "PRODUCTION_EVIDENCE_REPAIR_REQUIRED"
    report_check = next(row for row in result["checks"] if row["key"] == "human_report_lineage")
    assert report_check["state"] == "not_ready"


def test_sota_readiness_is_exposed_as_one_engine_command() -> None:
    args = parser().parse_args(["audit-sota-readiness"])
    assert args.command == "audit-sota-readiness"
