"""Bounded, read-only audit of premium capital, risk, continuation and score shape.

Uses a hash-matched saved forecast generation, NOT fresh gameweek advice. Frozen
choices are checked on independent draws; nothing can publish or enable a model.
"""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_engine.allocation_research import run_allocation_research
from fplagent_engine.chip_opportunity_audit import audit_chip_opportunities
from fplagent_engine.chip_strategy import CALIBRATION as CHIP_CALIBRATION
from fplagent_engine.chip_strategy import load_chip_strategy_calibration
from fplagent_engine.deadline_pipeline import weekly_pipeline_implementation_sha256
from fplagent_engine.distribution_policy_audit import remap_score_shapes
from fplagent_engine.policy_evidence import summarize_policy_evidence
from fplagent_engine.prospective_scoring import score_weekly_event
from fplagent_engine.rules import load_rules
from fplagent_engine.score_shape import ARTIFACT, _load_artifact
from fplagent_engine.transfer_value import load_terminal_free_transfer_curve
from fplagent_engine.weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from fplagent_engine.weekly_decision import load_weekly_manager_state, synthesize_weekly_decision
from fplagent_engine.weekly_deep_search import sample_worlds, score, validation_gate
from fplagent_engine.weekly_policy_research import build_policy_plans, score_policy_plans


def run(receipt_path, output, *, samples=10000):
    if output.exists():
        raise FileExistsError("Research receipts cannot be overwritten")
    if samples < 1000:
        raise ValueError("At least 1000 paths per family are required")
    original = json.loads(receipt_path.read_text())
    sources = original["source_artifacts"]
    for name in ("forecast", "component_forecast", "manager_state_contract"):
        if sha256_file(Path(sources[name])) != sources[name + "_sha256"]:
            raise ValueError(f"Saved {name} no longer matches this generation")
    source_paths = {str(receipt_path), str(ARTIFACT), str(CHIP_CALIBRATION), str(Path(__file__).resolve())}
    source_paths.update(v for k, v in sources.items() if not k.endswith("sha256")
                        and isinstance(v, str) and len(v) < 250 and Path(v).is_file())
    hashes = {p: sha256_file(Path(p)) for p in sorted(source_paths)}
    implementation = weekly_pipeline_implementation_sha256()
    rows = pq.read_table(sources["forecast"]).to_pylist()
    events = tuple(r["event"] for r in original["action_summaries"][0]["event_lineups"])
    rows = [r for r in rows if int(r["event_number"]) in events]
    rules = load_rules()
    state, _ = load_weekly_manager_state(
        Path(sources["manager_state_contract"]), forecast_path=Path(sources["forecast"]),
        event=events[0], rules=rules, forecast_rows=rows,
    )
    curve, _ = load_terminal_free_transfer_curve(maximum=rules.max_free_transfers, rules=rules)
    artifact = _load_artifact(("audit", sha256_file(ARTIFACT)))
    if artifact is None:
        raise ValueError("Validated marginal artifact is missing or stale")
    result = {"version": "points_priorities_audit_20261021_v1", "status": "running",
              "decision_authority": False, "source_receipt": str(receipt_path),
              "event": events[0], "events": events, "input_hashes": hashes,
              "implementation_sha256": implementation,
              "samples_per_family_per_draw": samples,
              "seeds": [[202610211, 202610212], [202610213, 202610214]],
              "scope": "Saved generation with regenerated scalar configurations; not a fresh decision or sequential historical policy replay."}
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def save(stage):
        result["stage"] = stage
        result["elapsed_seconds"] = time.monotonic() - started
        temp = output.with_suffix(".tmp")
        temp.write_text(json.dumps(result, indent=2, default=str) + "\n")
        temp.replace(output)
        print(stage, flush=True)

    try:
        save("frozen historical policy evidence")
        result["historical_policy_evidence"] = summarize_policy_evidence([
            score_weekly_event(e) for e in range(1, events[0] + 1)
        ])
        save("ordinary legal candidates")
        actions = generate_weekly_actions(state, rows, rules, events=events,
                                         terminal_free_transfer_curve=curve)
        worlds, weights, _diagnostics = sample_worlds(
            rows, events, seeds=result["seeds"][0], samples=samples,
            component_forecast_path=Path(sources["component_forecast"]),
        )
        worlds = {k: {f: v for f, v in w.items() if f != "events"} for k, w in worlds.items()}
        current = {int(r["element"]): r for r in rows if r["event_number"] == events[0]}
        metrics, _totals = score(actions, worlds, events)

        def choose(members, values):
            return synthesize_weekly_decision(members, values, scenario_weights=weights,
                                             event_rows=current)

        baseline = choose(actions, metrics)["selected_action_id"]
        result["baseline_action_id"] = baseline
        save("premium sale and joint reinvestment")
        proposals = []
        result["allocation"] = run_allocation_research(
            state, actions, rows, rules, worlds, weights, events=events,
            selected_id=baseline, terminal_curve=curve, seconds=90, proposals_out=proposals,
        )
        expanded = actions + [replace(a, route_type=a.route_type.removeprefix("screened_"))
                              if a.route_type != "screened_roll" else a for a in proposals]
        expanded_metrics, _ = score(expanded, worlds, events)
        capital_choice = choose(expanded, expanded_metrics)["selected_action_id"]
        result["capital_selection"] = capital_choice
        save("guarded future transfers and legal chip branches")
        chips = generate_squad_chip_shadow_actions(
            state, rows, rules, events=events, alternatives_per_chip=1,
            terminal_free_transfer_curve=curve,
        )
        chips += generate_team_chip_shadow_actions(state, actions, rows, rules, events=events)
        plans, plan_receipt = build_policy_plans(
            actions, chips, rows, rules, events=events, selected_id=baseline,
            terminal_curve=curve, time_budget=180, solver_seconds=5,
        )
        result["continuation"] = score_policy_plans(
            actions, plans, plan_receipt, worlds, weights, events=events, selected_id=baseline,
            event_rows=current,
        )
        result["exact_chip_opportunities"] = audit_chip_opportunities(
            state, next(a for a in actions if a.action_id == baseline), rows, worlds, weights,
            events, load_chip_strategy_calibration(),
        )
        save("legal score-shape selection sensitivity")
        changed, shape = remap_score_shapes(worlds["residual"], rows, artifact["calibration"],
                                           events=events, seed=202610215)
        shape_worlds = {**worlds, "residual": changed}
        shape_metrics, _ = score(actions, shape_worlds, events)
        shape_choice = choose(actions, shape_metrics)["selected_action_id"]
        result["distribution"] = {"sensitivity": shape, "selected_action_id": shape_choice}
        # Freeze both hypotheses before seeing new validation samples.
        save("frozen choices; independent simulation validation")
        validation, _, _ = sample_worlds(
            rows, events, seeds=result["seeds"][1], samples=samples,
            component_forecast_path=Path(sources["component_forecast"]),
        )
        validation_metrics, validation_totals = score(expanded, validation, events)
        result["capital_validation"] = validation_gate(
            {"event_rows": current}, expanded, validation_metrics, validation_totals,
            weights=weights, incumbent_id=baseline, selected_id=capital_choice,
        )
        validation_changed, _ = remap_score_shapes(
            validation["residual"], rows, artifact["calibration"], events=events, seed=202610216,
        )
        for name, candidate_worlds in (
            ("existing_worlds", validation),
            ("changed_shape_worlds", {**validation, "residual": validation_changed}),
        ):
            ms, ts = score(actions, candidate_worlds, events)
            result["distribution"][name] = validation_gate(
                {"event_rows": current}, actions, ms, ts, weights=weights,
                incumbent_id=baseline, selected_id=shape_choice,
            )
        result["input_hashes_stable"] = all(sha256_file(Path(p)) == h for p, h in hashes.items())
        result["implementation_stable"] = implementation == weekly_pipeline_implementation_sha256()
        result["status"] = "completed" if result["input_hashes_stable"] and result["implementation_stable"] else "invalidated"
        result["promotion"] = "retain_current_production_policy"
        result["reason"] = "Simulation sensitivity on one saved generation is not historical net-points lift; no self-promotion."
        save("complete")
    except (Exception, KeyboardInterrupt) as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save("failed")
        raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=Path("data/decisions/2026-27-weekly-current.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10000)
    args = parser.parse_args()
    run(args.receipt, args.output, samples=args.samples)
