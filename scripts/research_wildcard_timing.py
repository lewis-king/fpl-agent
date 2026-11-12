"""Freeze a live decision and compare WC timing without publishing or account writes."""

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_engine.horizon_decay_replay import _fixture_response_coefficients, _load_inputs
from fplagent_engine.rules import load_rules
from fplagent_engine.season_state import (
    ActionBundle,
    ChipType,
    Lineup,
    MarketPlayer,
    Transfer,
    apply_action,
)
from fplagent_engine.sequential_policy_replay import deadline_world, origin_simulation_rows
from fplagent_engine.tournament import calibrate_residuals
from fplagent_engine.weekly_actions import EventLineup
from fplagent_engine.weekly_decision import load_weekly_manager_state
from fplagent_engine.wildcard_timing import (
    InformationShock,
    TimingConfig,
    compare_frozen,
    extend_origin_forecast,
    ordinary_actions,
    revealed_rows,
    rollout,
    wildcard_action,
)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New isolated directory")
    parser.add_argument("--end-event", type=int, default=19)
    parser.add_argument("--solver-seconds", type=float, default=8)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument(
        "--wc-aware-roots",
        action="store_true",
        help="Regenerate ordinary first moves for their planned WC date; keep published route fixed",
    )
    parser.add_argument("--united-multiplier", type=float, default=1)
    parser.add_argument("--shock-event", type=int, help="Reveal reduced United xP at this deadline")
    parser.add_argument("--snapshot", type=Path, help="Reuse another run's frozen inputs")
    args = parser.parse_args()
    if args.samples < 100 or args.united_multiplier < 0:
        parser.error("Require >=100 simulations and nonnegative multiplier")
    args.output.mkdir(parents=True, exist_ok=False)
    cfg = TimingConfig(solver_seconds=args.solver_seconds)
    if args.snapshot:
        decision = json.loads((args.snapshot / "decision.json").read_text())
        frozen = {
            name: (args.snapshot / name).read_bytes()
            for name in ("forecast.parquet", "fixtures.parquet", "manager.json")
        }
        source_hashes = json.loads((args.snapshot / "inputs.json").read_text())["source_hashes"]
        if source_hashes != {name: hashlib.sha256(value).hexdigest() for name, value in frozen.items()}:
            raise ValueError("Frozen research inputs changed; refusing to reuse the snapshot")
    else:
        decision = json.loads(Path("data/decisions/2026-27-weekly-current.json").read_text())
        sources = decision["source_artifacts"]
        pairs = {
            "forecast.parquet": "forecast",
            "fixtures.parquet": "schedule_fixtures",
            "manager.json": "manager_state_contract",
        }
        frozen = {name: Path(sources[key]).read_bytes() for name, key in pairs.items()}
        source_hashes = {name: hashlib.sha256(value).hexdigest() for name, value in frozen.items()}
        for name, key in pairs.items():
            if source_hashes[name] != sources[key + "_sha256"]:
                raise ValueError(
                    f"Published source changed during capture: {key}; retry after refresh"
                )
    for name, value in frozen.items():
        (args.output / name).write_bytes(value)
    save(args.output / "decision.json", decision)
    rows = pq.read_table(args.output / "forecast.parquet").to_pylist()
    fixtures = pq.read_table(args.output / "fixtures.parquet").to_pylist()
    rules = load_rules()
    event = int(decision["decision_event"])
    # Validate the original contract against its frozen forecast content. The
    # loader checks the hash, not a demand that research overwrite live paths.
    state, _ = load_weekly_manager_state(
        args.output / "manager.json",
        forecast_path=args.output / "forecast.parquet",
        event=event,
        rules=rules,
    )
    inputs = _load_inputs()
    coefficients = _fixture_response_coefficients(inputs["forecasts"], inputs["features"])
    historical_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in inputs["paths"].items()
    }
    origin_last = max(int(r["event_number"]) for r in rows)
    rows = extend_origin_forecast(
        rows, fixtures, end_event=args.end_event, coefficients=coefficients
    )
    events = tuple(range(event, args.end_event + 1))
    if len(events) < 2:
        raise ValueError("Need at least two deadlines for a timing comparison")
    # Team identity is resolved from current data, never a cross-season numeric ID.
    united = tuple(sorted({int(r["element"]) for r in rows if r.get("team_short_name") == "MUN"}))
    shocks = (
        ()
        if args.united_multiplier == 1
        else (InformationShock(args.shock_event or event, united, args.united_multiplier),)
    )
    root_rows = revealed_rows(rows, deadline=event, shocks=shocks)
    horizon = tuple(range(event, min(event + cfg.planning_horizon, args.end_event + 1)))
    trace = []
    roots = ordinary_actions(state, root_rows, rules, events=horizon, config=cfg, trace=trace)
    if any(t["status"] == "unresolved" for t in trace):
        raise RuntimeError(f"Root search incomplete: {trace}")
    named = {
        ("roll" if not r.action.transfers else f"ordinary_{len(r.action.transfers)}"): r
        for r in roots
    }
    # Include the exact published action/configuration, not just a freshly solved neighbour.
    value = decision["selected_action"]

    def lineup(v):
        return Lineup(
            tuple(v["starters"]), tuple(v["bench_order"]), int(v["captain"]), int(v["vice_captain"])
        )

    a = value["action"]
    bundle = ActionBundle(
        event,
        lineup(a["lineup"]),
        tuple(
            Transfer(t["outgoing_player_id"], MarketPlayer(**t["incoming"])) for t in a["transfers"]
        ),
        ChipType(a["chip"]) if a["chip"] else None,
    )
    published = replace(
        roots[0],
        action_id=value["action_id"],
        action=bundle,
        outcome=apply_action(state, bundle, rules),
        selected_player_ids=tuple(
            sorted(h.player_id for h in apply_action(state, bundle, rules).gameweek.squad)
        ),
        lineups=tuple(
            EventLineup(int(l["event"]), lineup(l["lineup"]), l["formation"], l["projected_points"])
            for l in value["lineups"]
        ),
        incremental_points_cost=value["incremental_points_cost"],
        total_points_cost=value["total_points_cost"],
    )
    named["published"] = published
    current = {int(r["element"]): r for r in root_rows if int(r["event_number"]) == event}
    bruno = next(p for p, r in current.items() if "Bruno Fernandes" in r["player_name"])
    mbeumo = next(p for p, r in current.items() if r["player_name"] == "Mbeumo")
    constraints = [
        ("both", (bruno, mbeumo), ()),
        ("bruno_only", (bruno,), (mbeumo,)),
        ("mbeumo_only", (mbeumo,), (bruno,)),
        ("neither", (), (bruno, mbeumo)),
    ]
    for label, required, sold in constraints:
        named["wc_" + label] = wildcard_action(
            state, root_rows, rules, events=horizon, config=cfg, required=required, sold=sold
        )
        if sold:
            extra_trace = []
            alternatives = ordinary_actions(
                state,
                root_rows,
                rules,
                events=horizon,
                config=cfg,
                trace=extra_trace,
                required_player_ids=required,
                required_outgoing_player_ids=sold,
            )
            if any(t["status"] == "unresolved" for t in extra_trace):
                raise RuntimeError(f"United alternative search unresolved: {label}")
            if alternatives:
                named["sell_" + label] = max(alternatives, key=lambda a: a.decision_utility)
    receipt = {
        "version": "wildcard_timing_v2" if args.wc_aware_roots else "wildcard_timing_v1",
        "wc_aware_ordinary_roots": args.wc_aware_roots,
        "created_at": datetime.now(UTC).isoformat(),
        "decision_authority": False,
        "source_hashes": source_hashes,
        "historical_hashes": historical_hashes,
        "rules": asdict(rules),
        "config": asdict(cfg),
        "events": events,
        "direct_forecast_end": origin_last,
        "fixture_extrapolation_events": list(range(origin_last + 1, args.end_event + 1)),
        "fixture_coefficients": coefficients,
        "shocks": [asdict(s) for s in shocks],
        "other_chips": "held unused equally; joint timing remains an untested interaction",
        "historical_evidence": "Earlier-season residual and fixture calibration only; not a historical timing-policy validation",
        "status": "running",
    }
    save(args.output / "inputs.json", receipt)
    cache, plans, groups, paths = {}, [], [], []
    for group, root in named.items():
        dates = [event] if root.action.chip == ChipType.WILDCARD else [None, *events[1:]]
        for date in dates:
            print(json.dumps({"stage": "rollout", "root": group, "wc_event": date}), flush=True)
            timed_root = root
            if (
                args.wc_aware_roots
                and date is not None
                and date > event
                and group not in {"published", "roll"}
            ):
                timed_events = tuple(e for e in horizon if e < date)
                kwargs = {}
                if group.startswith("sell_"):
                    _, required, sold = next(c for c in constraints if "sell_" + c[0] == group)
                    kwargs = {"required_player_ids": required, "required_outgoing_player_ids": sold}
                timed_trace = []
                timed_choices = ordinary_actions(
                    state,
                    root_rows,
                    rules,
                    events=timed_events,
                    config=cfg,
                    trace=timed_trace,
                    **kwargs,
                )
                if any(t["status"] == "unresolved" for t in timed_trace):
                    raise RuntimeError(f"Unresolved WC-aware root: {group}/{date}")
                same_count = [
                    a
                    for a in timed_choices
                    if len(a.action.transfers) == len(root.action.transfers)
                ]
                if not same_count:
                    raise RuntimeError(f"Missing WC-aware root: {group}/{date}")
                timed_root = max(same_count, key=lambda a: a.decision_utility)
            plan, ledger = rollout(
                state,
                timed_root,
                rows,
                rules,
                end_event=args.end_event,
                wildcard_event=date,
                config=cfg,
                shocks=shocks,
                cache=cache,
            )
            # Same physical policy can occur under several labelled constraints.
            plan = replace(plan, action_id=plan.action_id + "-" + group)
            plans.append(plan)
            groups.append(group)
            paths.append(
                {
                    "plan_id": plan.action_id,
                    "group": group,
                    "wildcard_event": date,
                    "ledger": ledger,
                }
            )
            save(args.output / "paths.json", paths)
    print(
        json.dumps({"stage": "paired_independent_simulation", "policies": len(plans)}), flush=True
    )
    calibration = calibrate_residuals()
    # Sample each event with its scenario's actual prefix, without feeding draws
    # back to the action planner. News shocks are sensitivity cases, not fitted odds.
    simulation_rows = []
    for e in events:
        simulation_rows.extend(
            r for r in revealed_rows(rows, deadline=e, shocks=shocks) if int(r["event_number"]) == e
        )
    sim = origin_simulation_rows(simulation_rows)
    selection = deadline_world(
        sim,
        fixtures,
        calibration,
        events=events,
        samples=args.samples,
        seed=2026102221 if args.wc_aware_roots else 2026102201,
    )
    validation = deadline_world(
        sim,
        fixtures,
        calibration,
        events=events,
        samples=args.samples * 2,
        seed=2026102222 if args.wc_aware_roots else 2026102202,
    )
    result = compare_frozen(
        plans, groups, selection, validation, events=events, reference_group="published"
    )
    path_by_id = {p["plan_id"]: p for p in paths}
    for row in result["groups"]:
        path = path_by_id[row["plan_id"]]
        row["wildcard_event"] = path["wildcard_event"]
        row["root_transfers"] = path["ledger"][0]["transfers"]
        row["root_squad_names"] = [current[p]["player_name"] for p in path["ledger"][0]["squad"]]
    result.update(
        {
            "status": "completed_diagnostic",
            "inputs": str(args.output / "inputs.json"),
            "selection_seed": 2026102221 if args.wc_aware_roots else 2026102201,
            "validation_seed": 2026102222 if args.wc_aware_roots else 2026102202,
            "samples_selection": args.samples,
            "samples_validation": args.samples * 2,
            "future_news_root_selection_is_oracle_sensitivity": bool(
                args.shock_event and args.shock_event > event
            ),
        }
    )
    save(args.output / "results.json", result)
    save(args.output / "inputs.json", {**receipt, "status": "completed_diagnostic"})
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
