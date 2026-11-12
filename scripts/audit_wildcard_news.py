"""Evaluate ORIGIN-FROZEN choices under later news, without choosing a root on that news."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_engine.rules import load_rules
from fplagent_engine.sequential_policy_replay import deadline_world, origin_simulation_rows
from fplagent_engine.tournament import calibrate_residuals
from fplagent_engine.weekly_decision import load_weekly_manager_state
from fplagent_engine.weekly_simulation import evaluate_action_paths
from fplagent_engine.wildcard_timing import (
    InformationShock,
    extend_origin_forecast,
    plan_from_ledger,
    revealed_rows,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", type=Path)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args()
    output = args.scenario / "origin-frozen-news-check.json"
    if output.exists():
        raise FileExistsError(output)

    def read(folder, name):
        return json.loads((folder / name).read_text())

    origin, origin_inputs = read(args.origin, "results.json"), read(args.origin, "inputs.json")
    inputs, paths = read(args.scenario, "inputs.json"), read(args.scenario, "paths.json")
    if origin_inputs["shocks"] or inputs["source_hashes"] != origin_inputs["source_hashes"]:
        raise ValueError("Need unchanged-origin selection and identical source evidence")
    events = tuple(inputs["events"])
    if any(s["event"] <= events[0] for s in inputs["shocks"]):
        raise ValueError("This audit is for unobserved future news only")
    chosen_groups = [origin["reference_group"], origin["selected_group"]]
    origin_paths = {p["plan_id"]: p for p in read(args.origin, "paths.json")}
    selected_paths = []
    for group in chosen_groups:
        choice = next(g for g in origin["groups"] if g["group"] == group)
        original = origin_paths[choice["plan_id"]]
        path = next(
            p
            for p in paths
            if p["group"] == group and p["wildcard_event"] == original["wildcard_event"]
        )
        first_news = min(s["event"] for s in inputs["shocks"])
        if [r for r in path["ledger"] if r["event"] < first_news] != [
            r for r in original["ledger"] if r["event"] < first_news
        ]:
            raise ValueError("Policy changed before news arrived")
        selected_paths.append(path)
    rules = load_rules()
    state, _ = load_weekly_manager_state(
        args.scenario / "manager.json",
        forecast_path=args.scenario / "forecast.parquet",
        event=events[0],
        rules=rules,
    )
    fixtures = pq.read_table(args.scenario / "fixtures.parquet").to_pylist()
    rows = extend_origin_forecast(
        pq.read_table(args.scenario / "forecast.parquet").to_pylist(),
        fixtures,
        end_event=events[-1],
        coefficients=inputs["fixture_coefficients"],
    )
    shocks = tuple(InformationShock(**s) for s in inputs["shocks"])
    plans = [
        plan_from_ledger(state, p["ledger"], rows, rules, identity=p["plan_id"], shocks=shocks)
        for p in selected_paths
    ]
    plans[0] = replace(plans[0], route_type="roll")
    sim = origin_simulation_rows(
        [
            r
            for e in events
            for r in revealed_rows(rows, deadline=e, shocks=shocks)
            if r["event_number"] == e
        ]
    )
    world = deadline_world(
        sim, fixtures, calibrate_residuals(), events=events, samples=20000, seed=2026102231
    )
    metrics, _ = evaluate_action_paths(plans, events=events, horizon_decay=1, **world)
    # Metrics are sorted by score; the totals matrix retains input order.
    delta = next(metric for metric in metrics if metric.action_id == plans[1].action_id)
    result = {
        "decision_authority": False,
        "origin_choices_frozen_before_news": True,
        "unchanged_actions_before_news_verified": True,
        "selected_origin_group": chosen_groups[1],
        "reference_origin_group": chosen_groups[0],
        "wc_dates": [p["wildcard_event"] for p in selected_paths],
        "paired_gain_under_news": delta.mean_delta_to_roll,
        "mc95": [delta.delta_to_roll_95ci_low, delta.delta_to_roll_95ci_high],
        "probability_beat_reference": delta.beat_roll_probability,
        "seed": 2026102231,
        "samples": 20000,
        "warning": "Do not use the scenario results.json selected_group to recommend an origin action: selecting it after assuming this specific future news is an oracle sensitivity comparison.",
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
