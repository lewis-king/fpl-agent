"""Recent-season chronological WC-now versus delayed-WC development replay.

At GW8 select a fixed WC date using only origin forecasts, then replay both
policies with genuinely refreshed deadline forecasts and prices through GW19.
No season's outcomes fit its own residual model. These reused development
seasons are not pristine holdouts and do not grant live timing authority.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.paths import PROCESSED
from fplagent_engine.historical_blank_holdings import complete_blank_holdings
from fplagent_engine.horizon_decay_replay import _initial_state, _load_inputs
from fplagent_engine.joint_chip_state_replay import actual_score
from fplagent_engine.rules import load_rules
from fplagent_engine.season_state import ActionBundle, apply_action
from fplagent_engine.sequential_policy_replay import (
    deadline_world,
    fit_prefix,
    origin_simulation_rows,
)
from fplagent_engine.tournament import HISTORICAL_FIXTURES
from fplagent_engine.weekly_continuation_replay import (
    ReplayConfig,
    prefix_coefficients,
    prepare_deadline,
    reprice_state,
)
from fplagent_engine.wildcard_timing import (
    TimingConfig,
    compare_frozen,
    ordinary_actions,
    rollout,
    wildcard_action,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--solver-seconds", type=float, default=10)
    parser.add_argument("--samples", type=int, default=3000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = _load_inputs()
    historical_fixtures = pq.read_table(HISTORICAL_FIXTURES).to_pylist()
    catalog = pq.read_table(
        PROCESSED / "vaastav_deadlines" / "player_snapshots.parquet"
    ).to_pylist()
    cfg = TimingConfig(solver_seconds=args.solver_seconds)
    rules = load_rules()
    results = {
        "version": "wildcard_timing_development_replay_v1",
        "decision_authority": False,
        "status": "running",
        "config": asdict(cfg),
        "folds": [],
        "limitations": [
            "Reused development seasons, not untouched policy holdouts.",
            "Current chip/FT mechanics counterfactually applied to original-season points.",
            "WC timing only; other chips held equally unused. No future news simulation fitted.",
            "Bounded residual-family research policy, not a reproduction of the production selector.",
        ],
    }

    def persist():
        (args.output / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")

    persist()
    for season in ("2024-25", "2025-26"):
        coeff, training = prefix_coefficients(inputs, season)
        residual, _ = fit_prefix(inputs, season, historical_fixtures)
        fold = {"season": season, "training_seasons": training, "status": "running", "paths": {}}
        results["folds"].append(fold)

        def prepare(event, state=None, horizon=5, *, season=season, coeff=coeff):
            rows, outcomes, snapshot = prepare_deadline(
                inputs, season, event, ReplayConfig(horizon=horizon), coeff
            )
            repairs = []
            if state is not None:
                rows, outcomes, repairs = complete_blank_holdings(
                    state,
                    rows,
                    outcomes,
                    inputs,
                    coeff,
                    catalog_rows=catalog,
                    final_fixtures=historical_fixtures,
                )
            rows = [r for r in rows if r["event_number"] <= 19]
            return rows, outcomes, snapshot, repairs

        def search(state, rows, *, wc_date=None, season=season):
            horizon = tuple(sorted({int(r["event_number"]) for r in rows}))
            if wc_date is not None and state.event < wc_date:
                horizon = tuple(e for e in horizon if e < wc_date)
            if wc_date == state.event:
                return wildcard_action(state, rows, rules, events=horizon, config=cfg)
            trace = []
            choices = ordinary_actions(state, rows, rules, events=horizon, config=cfg, trace=trace)
            if not choices or any(t["status"] == "unresolved" for t in trace):
                raise RuntimeError(f"Incomplete historical solve {season}/{state.event}: {trace}")
            return max(choices, key=lambda a: a.decision_utility)

        # One common starting squad and policy before the intervention.
        state = None
        for event in range(1, 8):
            print(
                json.dumps({"season": season, "stage": "common_prefix", "event": event}), flush=True
            )
            rows, outcomes, _, _ = prepare(event, state)
            if state is None:
                state, _ = _initial_state(
                    season=season,
                    rows=rows,
                    events=tuple(sorted({r["event_number"] for r in rows})),
                    decay=0.88,
                    rules=rules,
                )
                action = ActionBundle(event, state.lineup)
            else:
                state = reprice_state(state, [r for r in rows if r["event_number"] == event])
                action = search(state, rows).action
            state = apply_action(state, action, rules).next_manager
        rows, _, snapshot, _ = prepare(8, state, horizon=12)
        state = reprice_state(state, [r for r in rows if r["event_number"] == 8])
        root_events = (8, 9, 10, 11, 12)
        trace = []
        roots = ordinary_actions(state, rows, rules, events=root_events, config=cfg, trace=trace)
        if any(t["status"] == "unresolved" for t in trace):
            raise RuntimeError(f"Incomplete historical roots: {trace}")
        wc = wildcard_action(state, rows, rules, events=root_events, config=cfg)
        plans, groups, metadata, cache = [], [], [], {}
        for root in [wc, *roots]:
            dates = [8] if root is wc else list(range(9, 20))
            for date in dates:
                print(
                    json.dumps(
                        {
                            "season": season,
                            "stage": "origin_timing",
                            "wc_date": date,
                            "root": root.action_id,
                        }
                    ),
                    flush=True,
                )
                plan, ledger = rollout(
                    state,
                    root,
                    rows,
                    rules,
                    end_event=19,
                    wildcard_event=date,
                    config=cfg,
                    cache=cache,
                )
                plans.append(plan)
                groups.append("now" if root is wc else "later")
                metadata.append(
                    {
                        "plan_id": plan.action_id,
                        "wildcard_event": date,
                        "root": root,
                        "ledger": ledger,
                    }
                )
        fixtures = inputs["fixture_by_snapshot"][(season, snapshot["snapshot_event"])]
        sim = origin_simulation_rows(rows)
        events = tuple(range(8, 20))
        selection = deadline_world(
            sim, fixtures, residual, events=events, samples=args.samples, seed=2026102211
        )
        validation = deadline_world(
            sim, fixtures, residual, events=events, samples=args.samples * 2, seed=2026102212
        )
        comparison = compare_frozen(
            plans, groups, selection, validation, events=events, reference_group="later"
        )
        fold["origin_comparison"] = comparison
        by_id = {m["plan_id"]: m for m in metadata}
        choices = {g["group"]: by_id[g["plan_id"]] for g in comparison["groups"]}
        fold["frozen_wc_dates"] = {arm: m["wildcard_event"] for arm, m in choices.items()}
        for arm, policy in choices.items():
            carried, records = state, []
            fold["paths"][arm] = records
            for event in events:
                print(
                    json.dumps(
                        {
                            "season": season,
                            "stage": "actual_deadline_replan",
                            "arm": arm,
                            "event": event,
                        }
                    ),
                    flush=True,
                )
                current_rows, outcomes, dated, repairs = prepare(event, carried)
                carried = reprice_state(
                    carried, [r for r in current_rows if r["event_number"] == event]
                )
                chosen = (
                    policy["root"]
                    if event == 8
                    else search(carried, current_rows, wc_date=policy["wildcard_event"])
                )
                outcome = apply_action(carried, chosen.action, rules)
                records.append(
                    {
                        "event": event,
                        "net_points": actual_score(outcome, outcomes),
                        "chip": chosen.action.chip,
                        "bank_before": carried.bank,
                        "bank_after": outcome.gameweek.bank,
                        "free_transfers_before": carried.free_transfers,
                        "free_transfers_after": outcome.next_manager.free_transfers,
                        "hit": outcome.gameweek.incremental_points_cost,
                        "lineup": asdict(chosen.action.lineup),
                        "transfers": [asdict(t) for t in chosen.action.transfers],
                        "snapshot": dated,
                        "missing_holding_repairs": repairs,
                    }
                )
                carried = outcome.next_manager
                persist()
        totals = {arm: sum(r["net_points"] for r in rs) for arm, rs in fold["paths"].items()}
        fold.update(
            status="complete", net_points=totals, wc_now_minus_later=totals["now"] - totals["later"]
        )
        persist()
    results["status"] = "completed_development_replay"
    persist()
    print(json.dumps({k: v for k, v in results.items() if k != "folds"}, indent=2))
    print(
        json.dumps(
            [
                {k: f[k] for k in ("season", "net_points", "wc_now_minus_later", "frozen_wc_dates")}
                for f in results["folds"]
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
