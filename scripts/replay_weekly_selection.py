"""Replay only selection on frozen candidates/world metrics, without live data.

Does not rebuild forecasts, substitute today's role news, or publish decisions.
Prints a research receipt to stdout; never writes an active decision pointer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplagent_data.http import sha256_file
from fplagent_engine.manager_state_store import _state_from_payload
from fplagent_engine.rules import load_rules
from fplagent_engine.season_state import ActionBundle, Lineup, MarketPlayer, Transfer, apply_action
from fplagent_engine.weekly_actions import EvaluatedAction, EventLineup
from fplagent_engine.weekly_decision import _rules_sha256, synthesize_weekly_decision
from fplagent_engine.weekly_simulation import ActionPathMetric


def replay(path: Path, *, worst_case_weight: float | None = None) -> dict:
    receipt = json.loads(path.read_text())
    sources = receipt["source_artifacts"]
    rules = load_rules()
    if sources.get("runtime_rules_sha256") != _rules_sha256(rules):
        raise ValueError("Frozen decision rules differ from the current rules")
    contract = Path(sources["manager_state_contract"])
    if sha256_file(contract) != sources["manager_state_contract_sha256"]:
        raise ValueError("Frozen manager contract hash mismatch")
    state = _state_from_payload(json.loads(contract.read_text())["manager_state"])
    actions = []
    for summary in receipt["action_summaries"]:
        lineups = tuple(
            EventLineup(
                event=row["event"],
                lineup=Lineup(
                    tuple(row["starter_player_ids"]),
                    tuple(row["bench_player_ids"]),
                    row["captain_player_id"],
                    row["vice_captain_player_id"],
                ),
                formation=row["formation"],
                projected_points=row["projected_points"],
            )
            for row in summary["event_lineups"]
        )
        transfers = tuple(
            Transfer(
                row["outgoing_player_id"],
                MarketPlayer(
                    row["incoming_player_id"],
                    row["incoming_position"],
                    row["incoming_team_id"],
                    row["incoming_price"],
                ),
            )
            for row in summary["transfers"]
        )
        bundle = ActionBundle(state.event, lineups[0].lineup, transfers)
        outcome = apply_action(state, bundle, rules)
        if outcome.gameweek.incremental_points_cost != summary["incremental_points_cost"]:
            raise ValueError("Frozen transfer hit does not match the reconstructed legal action")
        actions.append(
            EvaluatedAction(
                action_id=summary["action_id"],
                route_type=summary["route_type"],
                score_field=receipt["selected_action"]["score_field"],
                selected_player_ids=tuple(h.player_id for h in outcome.gameweek.squad),
                action=bundle,
                outcome=outcome,
                lineups=lineups,
                gross_horizon_utility=summary["gross_horizon_utility"],
                incremental_points_cost=summary["incremental_points_cost"],
                total_points_cost=summary["total_points_cost"],
                next_free_transfers=summary["next_free_transfers"],
                terminal_free_transfers=summary["terminal_free_transfers"],
                terminal_transfer_value=summary["terminal_transfer_value"],
                decision_utility=summary["decision_utility"],
            )
        )
    metrics = {
        name: [ActionPathMetric(**row) for row in values.values()]
        for name, values in receipt["scenario_metrics_by_action"].items()
    }
    result = synthesize_weekly_decision(
        actions,
        metrics,
        scenario_weights=receipt["method"]["scenario_weights"],
        worst_case_weight=receipt["method"]["worst_case_weight"]
        if worst_case_weight is None
        else worst_case_weight,
    )
    selected = next(
        row
        for row in receipt["action_summaries"]
        if row["action_id"] == result["selected_action_id"]
    )
    return {
        "event": state.event,
        "source": str(path),
        "source_sha256": sha256_file(path),
        "old_action": receipt["selected_action_id"],
        "new_action": result["selected_action_id"],
        "changed": receipt["selected_action_id"] != result["selected_action_id"],
        "worst_case_weight": receipt["method"]["worst_case_weight"]
        if worst_case_weight is None
        else worst_case_weight,
        "selected_transfers": selected["transfers"],
        "gate": result["promotion_gate"],
        "selection_audit": result["selection_audit"],
        "objective_tradeoff": result["objective_tradeoff"],
        "scope": "Frozen-candidate selector replay only; no forecast or role-feed replay, no realized gain claim.",
        "decision_authority": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([replay(path) for path in args.receipts], indent=2))


if __name__ == "__main__":
    main()
