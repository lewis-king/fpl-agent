"""Wildcard squad challenge: the engine's pick against field-shaped squads.

Every squad is a Wildcard played in the current decision week, then managed
by the same weekly replanning to the end of the chip half. All squads are
scored on the same simulated outcomes. The field is the latest elite sample:
its weekly score is ownership-weighted points plus captaincy-weighted points.

Usage: PYTHONPATH=src .venv/bin/python scripts/season_review/wildcard_challenge.py
Research only. Writes data/analysis/wildcard-challenge-gwNN.json.
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.elite_sample import load_elite_sample
from fplagent_engine.chip_timing import DEFAULT_DECISION_PATH, half_end
from fplagent_engine.horizon_decay_replay import _fixture_response_coefficients, _load_inputs
from fplagent_engine.rules import load_rules
from fplagent_engine.sequential_policy_replay import deadline_world, origin_simulation_rows
from fplagent_engine.tournament import calibrate_residuals
from fplagent_engine.weekly_decision import load_weekly_manager_state
from fplagent_engine.weekly_simulation import evaluate_action_paths
from fplagent_engine.wildcard_timing import (
    TimingConfig,
    extend_origin_forecast,
    revealed_rows,
    rollout,
    wildcard_action,
)


def field_scores(world, sample):
    ids = {int(p): i for i, p in enumerate(world["player_ids"])}
    weight = np.zeros(len(ids))
    for key in ("started", "captaincy"):
        for element, share in sample[key].items():
            if int(element) in ids:
                weight[ids[int(element)]] += float(share)
    scored = world["points"] * world["played"]
    return (scored * weight).sum(axis=2).sum(axis=1)


def rival_scores(world, managers):
    """Per-draw points of each real rival squad, held unchanged (XI and captain)."""
    ids = {int(p): i for i, p in enumerate(world["player_ids"])}
    weights = np.zeros((len(ids), len(managers)))
    for column, manager in enumerate(managers):
        for slot, (element, multiplier) in enumerate(manager["picks"]):
            if slot >= 11:
                multiplier = 0  # Bench Boost weeks: bench does not score again.
            if element in ids:
                weights[ids[element], column] = min(multiplier, 2)
    per_player = (world["points"] * world["played"]).sum(axis=1)
    return per_player @ weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--solver-seconds", type=float, default=8.0)
    parser.add_argument("--template-share", type=float, default=0.75)
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
    names = {int(r["element"]): r["player_name"] for r in root_rows
             if int(r["event_number"]) == event}
    price = {int(r["element"]): float(r["market_price"]) for r in root_rows
             if int(r["event_number"]) == event}
    sample = load_elite_sample()
    ownership = {int(k): float(v) for k, v in sample["ownership"].items()}
    top = sorted(ownership, key=lambda p: -ownership[p])
    most_owned = top[0]
    template = tuple(p for p in top if ownership[p] >= args.template_share and p in names)

    cfg = TimingConfig(solver_seconds=args.solver_seconds)
    long_cfg = TimingConfig(solver_seconds=args.solver_seconds,
                            planning_horizon=min(8, len(events)), planning_decay=0.95)

    def build(config, **constraints):
        horizon = tuple(range(event, min(event + config.planning_horizon, end + 1)))
        view = [r for r in root_rows if int(r["event_number"]) in horizon]
        return wildcard_action(state, view, rules, events=horizon, config=config, **constraints)

    variants = {
        "engine_pick": build(cfg),
        "engine_long_horizon": build(long_cfg),
        f"with_{names[most_owned]}": build(cfg, required=(most_owned,)),
        f"long_horizon_with_{names[most_owned]}": build(long_cfg, required=(most_owned,)),
        f"without_{names[most_owned]}": build(cfg, sold=tuple(
            p for p in (most_owned,) if p in {h.player_id for h in state.squad})),
        "elite_template_core": build(cfg, required=template),
    }
    cache, plans, labels = {}, [], []
    seen = {}
    for label, root in variants.items():
        squad = tuple(sorted(root.selected_player_ids))
        if label.startswith("without_") and most_owned in squad:
            continue  # Not held now, so "sold" cannot exclude him; skip the duplicate.
        if squad in seen:
            print(f"{label}: same squad as {seen[squad]}")
            continue
        seen[squad] = label
        print(f"Rolling {label} to GW{end}", flush=True)
        plan, _ = rollout(state, root, rows, rules, end_event=end, wildcard_event=event,
                          config=cfg, cache=cache)
        plans.append(replace(plan, action_id=plan.action_id + "-" + label,
                             route_type="roll" if not plans else "timing_path"))
        labels.append(label)

    calibration = calibrate_residuals()
    simulation_rows = [r for e in events for r in revealed_rows(rows, deadline=e)
                       if int(r["event_number"]) == e]
    world = deadline_world(origin_simulation_rows(simulation_rows), fixtures, calibration,
                           events=events, samples=args.samples * 2, seed=2026111201)
    _, scores = evaluate_action_paths(plans, events=events, horizon_decay=1.0, **world)
    field = field_scores(world, sample)
    rivals_path = Path(f"data/analysis/rivals/gw{sample['event']:02d}.json")
    if rivals_path.exists():
        managers = [m for m in json.loads(rivals_path.read_text())["managers"]
                    if m["active_chip"] != "freehit"]
        np.savez_compressed(
            f"data/analysis/wildcard-challenge-gw{event:02d}-draws.npz",
            labels=np.array(labels), scores=scores.astype(np.float32),
            rivals=rival_scores(world, managers).astype(np.float32),
            rival_total=np.array([m["total"] for m in managers]),
            rival_band=np.array([m["band"] for m in managers]),
            field=field.astype(np.float32),
        )
    reference = scores[:, 0]
    out = []
    for i, label in enumerate(labels):
        squad = sorted(variants[label].selected_player_ids, key=lambda p: -price[p])
        delta = scores[:, i] - reference
        gap = scores[:, i] - field
        se = float(delta.std(ddof=1) / np.sqrt(len(delta))) if i else 0.0
        out.append({
            "squad": label,
            "players": [names[p] for p in squad],
            "expected_points_to_half_end": float(scores[:, i].mean()),
            "versus_engine_pick": float(delta.mean()),
            "versus_engine_pick_mc95": [float(delta.mean() - 1.96 * se),
                                        float(delta.mean() + 1.96 * se)],
            "expected_gain_on_field": float(gap.mean()),
            "gap_spread_p10_p90": [float(x) for x in np.quantile(gap, [0.1, 0.9])],
            "chance_to_gain_30_on_field": float(np.mean(gap >= 30)),
            "chance_to_lose_30_to_field": float(np.mean(gap <= -30)),
            "players_shared_with_typical_elite_squad": float(
                sum(ownership.get(p, 0.0) for p in squad)),
        })
    result = {"event": event, "half_end": end, "samples": args.samples * 2,
              "elite_sample_event": sample["event"], "squads": out,
              "limitations": [
                  "The field keeps its sampled squads and captains for every week.",
                  ("Field chips and transfers are not simulated, so field-gap means are "
                   "comparable between squads but not forecasts of rank."),
                  "Weeks beyond the direct forecast use fixture-adjusted current form.",
              ]}
    path = Path(f"data/analysis/wildcard-challenge-gw{event:02d}.json")
    path.write_text(json.dumps(result, indent=2) + "\n")
    for row in out:
        print(f"\n{row['squad']}: {row['expected_points_to_half_end']:.1f} pts "
              f"({row['versus_engine_pick']:+.1f} vs engine, "
              f"{row['versus_engine_pick_mc95'][0]:+.1f} to {row['versus_engine_pick_mc95'][1]:+.1f})"
              f" | shared {row['players_shared_with_typical_elite_squad']:.1f}"
              f" | gap p10/p90 {row['gap_spread_p10_p90'][0]:+.0f}/{row['gap_spread_p10_p90'][1]:+.0f}"
              f" | P(+30) {row['chance_to_gain_30_on_field']:.0%}"
              f" P(-30) {row['chance_to_lose_30_to_field']:.0%}")
        print("  " + ", ".join(row["players"]))


if __name__ == "__main__":
    main()
