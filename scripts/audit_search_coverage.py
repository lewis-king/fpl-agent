"""Identify whether first wider-search divergences require protected premium exits.

Read-only structural audit, not another outcome-selected strategy/ablation.
"""
import argparse
import json
from pathlib import Path

from fplagent_engine.horizon_decay_replay import _historical_rules, _load_inputs
from fplagent_engine.season_state import (
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    default_chip_inventory,
)
from fplagent_engine.sequential_policy_replay import SequentialConfig, origin_simulation_rows
from fplagent_engine.weekly_actions import generate_weekly_actions
from fplagent_engine.weekly_continuation_replay import prefix_coefficients, prepare_deadline


def audit(path):
    receipt = json.loads(path.read_text())
    inputs = _load_inputs()
    config = SequentialConfig(**{**receipt["config"], "seasons": tuple(receipt["config"]["seasons"])})
    results = []
    for fold in receipt["folds"]:
        baseline = fold["paths"]["baseline"]["events"]
        wider = fold["paths"]["broad_incumbent"]["events"]
        changed = next((i for i, (a, b) in enumerate(zip(baseline, wider, strict=True))
                        if a["action_id"] != b["action_id"]), None)
        if changed is None:
            continue
        season = fold["season"]
        event = wider[changed]["event"]
        coefficients, _ = prefix_coefficients(inputs, season)
        rows, _, _ = prepare_deadline(inputs, season, event, config, coefficients)
        rows = origin_simulation_rows(rows)
        current = {r["element"]: r for r in rows if r["event_number"] == event}
        purchases = {}
        for record in wider[:changed]:
            quotes = {r["element"]: round(r["market_price"])
                      for r in inputs["forecast_by_event"][(season, record["event"])]}
            if record["event"] == 1:
                purchases.update({p: quotes[p] for p in record["selected"]})
            for transfer in record["transfers"]:
                del purchases[transfer["out"]]
                purchases[transfer["in"]] = quotes[transfer["in"]]
        previous = wider[changed - 1]
        holdings = []
        for p, paid in sorted(purchases.items()):
            price = round(current[p]["market_price"])
            sale = min(price, paid) + max(0, price - paid) // 2
            holdings.append(PlayerHolding(p, current[p]["position"], current[p]["team_id"], paid, price, sale))
        state = ManagerState(season, event, EventStatus.DEADLINE_OPEN, tuple(holdings),
                              previous["bank_after"], previous["free_transfers_after"], default_chip_inventory(),
                              Lineup(tuple(previous["starters"]), tuple(previous["bench_order"]),
                                     previous["captain"], previous["vice_captain"]))
        trace = []
        plain = generate_weekly_actions(
            state, rows, _historical_rules(season), events=tuple(sorted({r["event_number"] for r in rows})),
            score_field="expected_points", horizon_decay=config.decay, alternatives_per_transfer_count=4,
            max_total_transfers=2, max_paid_transfers=2, protect_role_sale_routes=False,
            terminal_free_transfer_curve={int(k): v for k, v in fold["terminal_curve"].items()},
            solver_time_limit_seconds=config.solver_seconds, search_diagnostics=trace)
        assert not any(t["status"] == "unresolved" for t in trace)
        selected = wider[changed]["action_id"]
        results.append({"season": season, "event": event, "winning_action": selected,
                        "present_without_forced_premium_sales": selected in {a.action_id for a in plain},
                        "unconstrained_candidates": len(plain),
                        "interpretation": "Checks first divergent roster coverage only, not attribution of the whole season points delta."})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    print(json.dumps(audit(parser.parse_args().receipt), indent=2))
