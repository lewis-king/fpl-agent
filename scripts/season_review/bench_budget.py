"""Bench budget test: how much should squad building value benched players?

Each arm is a Wildcard this week built and then managed to the end of the chip
half with a different bench weight (the share of a benched player's forecast
counted when choosing the squad). Bench Boost and Triple Captain follow the
live chip calendar. All arms are scored on the same simulated outcomes, with
automatic substitutions.

Usage: PYTHONPATH=src .venv/bin/python scripts/season_review/bench_budget.py
Research only. Writes data/analysis/bench-budget-gwNN.json.
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from fplagent_engine.chip_timing import DEFAULT_DECISION_PATH, DEFAULT_RECEIPT_PATH, half_end
from fplagent_engine.horizon_decay_replay import _fixture_response_coefficients, _load_inputs
from fplagent_engine.rules import load_rules
from fplagent_engine.season_state import ChipType
from fplagent_engine.sequential_policy_replay import deadline_world, origin_simulation_rows
from fplagent_engine.tournament import calibrate_residuals
from fplagent_engine.weekly_decision import load_weekly_manager_state
from fplagent_engine.weekly_simulation import evaluate_action_paths
from fplagent_engine.wildcard_timing import (
    TimingConfig,
    chip_week_weights,
    extend_origin_forecast,
    revealed_rows,
    rollout,
    wildcard_action,
)

WEIGHTS = (0.0, 0.04, 0.08, 0.16, 0.3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20_000)
    parser.add_argument("--solver-seconds", type=float, default=8.0)
    args = parser.parse_args()

    decision = json.loads(DEFAULT_DECISION_PATH.read_text())
    event = int(decision["decision_event"])
    end = half_end(event)
    sources = decision["source_artifacts"]
    rules = load_rules()
    state, _ = load_weekly_manager_state(
        Path(sources["manager_state_contract"]), forecast_path=Path(sources["forecast"]),
        event=event, rules=rules,
    )
    rows = pq.read_table(sources["forecast"]).to_pylist()
    fixtures = pq.read_table(sources["schedule_fixtures"]).to_pylist()
    inputs = _load_inputs()
    rows = extend_origin_forecast(
        rows, fixtures, end_event=end,
        coefficients=_fixture_response_coefficients(inputs["forecasts"], inputs["features"]),
    )
    events = tuple(range(event, end + 1))
    root_rows = revealed_rows(rows, deadline=event)
    now = {int(r["element"]): r for r in root_rows if int(r["event_number"]) == event}
    receipt = json.loads(DEFAULT_RECEIPT_PATH.read_text())
    calendar = tuple(
        (int(a["event"]), ChipType(a["chip"]))
        for a in receipt["chip_calendar"]["allocations"]
        if a["chip"] in ("bench_boost", "triple_captain") and int(a["event"]) > event
    )
    print("Chip calendar:", [(e, c.value) for e, c in calendar], flush=True)

    plans, rows_out = [], []
    for weight in WEIGHTS:
        cfg = TimingConfig(solver_seconds=args.solver_seconds, bench_weight=weight)
        build = replace(cfg, planning_horizon=min(8, len(events)), planning_decay=0.95)
        horizon = events[: build.planning_horizon]
        root = wildcard_action(
            state, [r for r in root_rows if int(r["event_number"]) in horizon], rules,
            events=horizon, config=build, **chip_week_weights(dict(calendar), horizon),
        )
        print(f"Rolling bench weight {weight}", flush=True)
        plan, ledger = rollout(state, root, rows, rules, end_event=end, wildcard_event=event,
                               config=cfg, chip_calendar=calendar, cache={})
        plans.append(replace(plan, action_id=f"{plan.action_id}-bench{weight}",
                             route_type="roll" if not plans else "timing_path"))
        lineup = root.action.lineup
        bench = list(lineup.bench_order) + [
            p for p in root.selected_player_ids
            if p not in lineup.starters and p not in lineup.bench_order
        ]
        rows_out.append({
            "bench_weight": weight,
            "bench_value": sum(float(now[p]["market_price"]) for p in bench) / 10,
            "bench": [now[p]["player_name"] for p in bench],
            "squad": [now[p]["player_name"] for p in sorted(
                root.selected_player_ids, key=lambda p: -float(now[p]["market_price"]))],
            "transfers_after_wildcard": sum(len(step["transfers"]) for step in ledger[1:]),
        })

    simulation_rows = [r for e in events for r in revealed_rows(rows, deadline=e)
                       if int(r["event_number"]) == e]
    world = deadline_world(origin_simulation_rows(simulation_rows), fixtures,
                           calibrate_residuals(), events=events, samples=args.samples,
                           seed=2026111203)
    _, scores = evaluate_action_paths(plans, events=events, horizon_decay=1.0, **world)
    reference = scores[:, WEIGHTS.index(0.08)]
    for i, row in enumerate(rows_out):
        delta = scores[:, i] - reference
        se = float(delta.std(ddof=1) / np.sqrt(len(delta)))
        row["expected_points_to_half_end"] = float(scores[:, i].mean())
        row["versus_current_weight"] = float(delta.mean())
        row["versus_current_weight_mc95"] = [float(delta.mean() - 1.96 * se),
                                             float(delta.mean() + 1.96 * se)]
        print(f"\nweight {row['bench_weight']}: {row['expected_points_to_half_end']:.1f} "
              f"({row['versus_current_weight']:+.1f}, ±{1.96 * se:.1f}) bench £{row['bench_value']:.1f}m "
              f"{row['bench']} | later transfers {row['transfers_after_wildcard']}")
        print("  " + ", ".join(row["squad"]))
    Path(f"data/analysis/bench-budget-gw{event:02d}.json").write_text(json.dumps({
        "event": event, "half_end": end, "samples": args.samples,
        "chip_calendar": [(e, c.value) for e, c in calendar], "arms": rows_out,
        "limitations": [
            ("Model-world test on one deadline: the simulation draws from the same forecasts "
             "the squads were built on."),
            "Weeks beyond the direct forecast use fixture-adjusted current form.",
        ]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
