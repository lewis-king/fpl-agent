#!/usr/bin/env python3
"""Run only the post-synthesis GW1 publication gates for an existing stage directory."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from fplagent_engine import preseason_pipeline as pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    stage = parse_args().stage.resolve()

    print("Deadline validation: bench allocation", flush=True)
    bench = pipeline.run_bench_allocation_audit(
        **pipeline.BENCH_ALLOCATION_CONFIG,
        forecast_path=stage / "direct-forecast.parquet",
        synthesis_path=stage / "results.json",
        participation_consensus_path=stage / "participation-consensus.parquet",
        results_path=stage / "bench-allocation.json",
        report_path=stage / "bench-allocation.md",
    )
    print({"bench_verdict": bench.get("verdict")}, flush=True)
    if not (bench.get("verdict") or {}).get("promotable"):
        raise RuntimeError("bench allocation did not pass")

    print("Deadline validation: structure stress", flush=True)
    structure = pipeline.run_structure_stress(
        **pipeline.STRUCTURE_STRESS_CONFIG,
        decision_path=stage / "decision.json",
        participation_consensus_path=stage / "participation-consensus.parquet",
        results_path=stage / "structure-stress.json",
        report_path=stage / "structure-stress.md",
    )
    print(
        {
            "structure_publishable": structure.get("publishable"),
            "verdict": structure.get("verdict"),
        },
        flush=True,
    )
    if not structure.get("publishable"):
        raise RuntimeError("structure stress did not pass")

    print("Deadline validation: role scenarios", flush=True)
    role = pipeline.run_preseason_role_scenario_audit(
        **pipeline.ROLE_SCENARIO_CONFIG,
        decision_path=stage / "decision.json",
        role_receipt_path=pipeline.ROLE_RECEIPT,
        role_evidence_path=pipeline.ROLE_EVIDENCE,
        results_path=stage / "preseason-role-scenario.json",
        report_path=stage / "preseason-role-scenario.md",
    )
    print(
        {"role_verdict": role.get("verdict"), "publishable": role.get("publishable")},
        flush=True,
    )

    print("Deadline validation: role thresholds", flush=True)
    threshold = pipeline.run_preseason_role_threshold_audit(
        **pipeline.ROLE_THRESHOLD_CONFIG,
        scenario_results_path=stage / "preseason-role-scenario.json",
        decision_path=stage / "decision.json",
        role_receipt_path=pipeline.ROLE_RECEIPT,
        role_evidence_path=pipeline.ROLE_EVIDENCE,
        results_path=stage / "preseason-role-threshold.json",
        report_path=stage / "preseason-role-threshold.md",
    )
    print(
        {
            "threshold_verdict": threshold.get("verdict"),
            "publishable": threshold.get("publishable"),
        },
        flush=True,
    )

    print("Deadline validation: availability watch", flush=True)
    availability = pipeline.audit_availability_watch(
        as_of=datetime.now(UTC).isoformat(),
        players_path=pipeline.OFFICIAL_PLAYERS,
        forecast_path=stage / "direct-forecast.parquet",
        forecast_manifest_path=stage / "direct-forecast-manifest.json",
        decision_path=stage / "decision.json",
        role_receipt_path=pipeline.ROLE_RECEIPT,
        role_evidence_path=pipeline.ROLE_EVIDENCE,
        scenario_results_path=stage / "preseason-role-scenario.json",
        threshold_results_path=stage / "preseason-role-threshold.json",
        participation_receipt_path=stage / "participation-receipt.json",
        participation_consensus_path=stage / "participation-consensus.parquet",
        output_path=stage / "availability-watch.json",
    )
    print(
        {
            "availability_current": availability.get("current"),
            "issues": availability.get("issues"),
        },
        flush=True,
    )
    if not availability.get("current"):
        raise RuntimeError("availability watch did not pass")

    print("Deadline validation: top-player omissions", flush=True)
    top = pipeline.run_top_player_omission_audit(
        forecast_path=stage / "direct-forecast.parquet",
        official_players_path=pipeline.OFFICIAL_PLAYERS,
        participation_consensus_path=stage / "participation-consensus.parquet",
        participation_receipt_path=stage / "participation-receipt.json",
        decision_path=stage / "decision.json",
        results_path=stage / "top-player-omission-audit.json",
        report_path=stage / "top-player-omission-audit.md",
    )
    print(
        {"top_publishable": top.get("publishable"), "checks": top.get("checks")},
        flush=True,
    )
    if not top.get("publishable"):
        raise RuntimeError("top-player omission audit did not pass")

    print("DEADLINE_VALIDATION_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
