#!/usr/bin/env python3
"""Rebuild the GW1 squad from supplied role-correct evidence without recollecting inputs."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from fplagent_engine import preseason_pipeline as pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--participation-consensus", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stage = args.stage.resolve()
    consensus = args.participation_consensus.resolve()
    runtime = stage / "runtime-reports"
    runtime.mkdir(parents=True, exist_ok=True)

    print("Role-corrected core: initial squad", flush=True)
    pipeline.select_initial_squad(20, report_path=runtime / "initial-squad.md")

    print("Role-corrected core: residual tournament", flush=True)
    pipeline.run_tournament(
        **pipeline.TOURNAMENT_CONFIG,
        report_path=runtime / "residual-tournament.md",
    )

    print("Role-corrected core: component selection", flush=True)
    pipeline.run_component_tournament(
        **pipeline.COMPONENT_SELECTION_CONFIG,
        report_path=runtime / "component-selection.md",
    )

    print("Role-corrected core: component candidates", flush=True)
    pipeline.generate_component_candidates()

    print("Role-corrected core: component holdout", flush=True)
    pipeline.run_component_tournament(
        **pipeline.COMPONENT_HOLDOUT_CONFIG,
        report_path=runtime / "component-holdout.md",
    )

    print("Role-corrected core: robust search", flush=True)
    pipeline.run_robust_search(
        **pipeline.ROBUST_CONFIG,
        participation_consensus_path=consensus,
        report_path=runtime / "robust-search.md",
    )

    print("Role-corrected core: horizon audit", flush=True)
    pipeline.run_horizon_audit(
        **pipeline.HORIZON_CONFIG,
        report_path=runtime / "horizon-audit.md",
    )

    print("Role-corrected core: synthesis", flush=True)
    pipeline.run_decision_synthesis(
        **pipeline.SYNTHESIS_CONFIG,
        results_path=stage / "results.json",
        decision_path=stage / "decision.json",
        report_path=stage / "report.md",
        participation_consensus_path=consensus,
        created_at=datetime.now(UTC).isoformat(),
    )

    print("Role-corrected core: XI, bench and armband simulations", flush=True)
    configuration = pipeline.run_current_squad_audit(
        **pipeline.CONFIGURATION_CONFIG,
        promote=True,
        decision_path=stage / "decision.json",
        decision_results_path=stage / "results.json",
        decision_report_path=stage / "report.md",
        results_path=stage / "simulation-configuration.json",
        report_path=stage / "simulation-configuration.md",
    )
    print(
        {
            "publishable": configuration.get("publishable"),
            "verdict": configuration.get("verdict"),
            "resolved": (configuration.get("configuration_stability") or {}).get(
                "resolved_candidate_id"
            ),
        },
        flush=True,
    )
    if not configuration.get("publishable"):
        raise RuntimeError("role-corrected configuration did not pass")
    print("ROLE_CORRECTED_CORE_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
