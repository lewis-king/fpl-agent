"""Score frozen timing paths with BB/TC dates chosen on selection draws only."""

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_engine.rules import load_rules
from fplagent_engine.sequential_policy_replay import deadline_world, origin_simulation_rows
from fplagent_engine.tournament import _score_candidates, calibrate_residuals
from fplagent_engine.weekly_decision import load_weekly_manager_state
from fplagent_engine.weekly_simulation import _candidate_payload
from fplagent_engine.wildcard_timing import (
    InformationShock,
    compare_frozen,
    extend_origin_forecast,
    plan_from_ledger,
    revealed_rows,
    select_team_chip_calendar,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--samples", type=int, default=10000)
    args = parser.parse_args()
    output = args.run / "team-chips-results.json"
    if output.exists():
        raise FileExistsError(output)
    inputs = json.loads((args.run / "inputs.json").read_text())
    if inputs["status"] != "completed_diagnostic":
        raise ValueError("Wait for complete path comparison")
    events = tuple(inputs["events"])
    rules = load_rules()
    state, _ = load_weekly_manager_state(
        args.run / "manager.json",
        forecast_path=args.run / "forecast.parquet",
        event=events[0],
        rules=rules,
    )
    fixtures = pq.read_table(args.run / "fixtures.parquet").to_pylist()
    rows = extend_origin_forecast(
        pq.read_table(args.run / "forecast.parquet").to_pylist(),
        fixtures,
        end_event=events[-1],
        coefficients=inputs["fixture_coefficients"],
    )
    shocks = tuple(InformationShock(**s) for s in inputs["shocks"])
    paths = json.loads((args.run / "paths.json").read_text())
    calibration = calibrate_residuals()
    sim = origin_simulation_rows(
        [
            r
            for e in events
            for r in revealed_rows(rows, deadline=e, shocks=shocks)
            if r["event_number"] == e
        ]
    )
    selection = deadline_world(
        sim, fixtures, calibration, events=events, samples=args.samples, seed=2026102203
    )
    plans, calendars = [], []
    bare_plans = [
        plan_from_ledger(state, p["ledger"], rows, rules, identity=p["plan_id"], shocks=shocks)
        for p in paths
    ]
    scores = _score_candidates(
        [_candidate_payload(p) for p in bare_plans],
        selection["player_ids"],
        events,
        selection["points"],
        selection["played"],
        selection["player_meta"],
    )
    for index, (p, plan) in enumerate(zip(paths, bare_plans, strict=True)):
        calendar = select_team_chip_calendar(
            plan, selection, events=events, state=state, event_scores=scores[:, index, :]
        )
        ledger = [dict(r, chip=calendar.get(r["event"], r["chip"])) for r in p["ledger"]]
        plans.append(
            plan_from_ledger(state, ledger, rows, rules, identity=p["plan_id"], shocks=shocks)
        )
        calendars.append({"plan_id": p["plan_id"], "calendar": calendar, "ledger": ledger})
    validation = deadline_world(
        sim, fixtures, calibration, events=events, samples=args.samples * 2, seed=2026102204
    )
    result = compare_frozen(
        plans,
        [p["group"] for p in paths],
        selection,
        validation,
        events=events,
        reference_group="published",
    )
    by_id = {p["plan_id"]: p for p in paths}
    calendar_by_id = {c["plan_id"]: c["calendar"] for c in calendars}
    for group in result["groups"]:
        group["wildcard_event"] = by_id[group["plan_id"]]["wildcard_event"]
        group["team_chip_dates"] = calendar_by_id[group["plan_id"]]
    result["conditional_team_chip_timing"] = True
    result["limitations"].append(
        "BB/TC dates are optimised conditional on the saved transfer paths, not a joint search of chip preparation transfers. Free Hit timing remains excluded."
    )
    result["selection_seed"], result["validation_seed"] = 2026102203, 2026102204
    output.write_text(json.dumps(result, indent=2) + "\n")
    (args.run / "team-chips-ledgers.json").write_text(json.dumps(calendars, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
