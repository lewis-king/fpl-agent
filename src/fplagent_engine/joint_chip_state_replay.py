"""Real-data full-season integration test of all eight chips and ordinary moves.

The calendar is PRECOMMITTED to exercise transitions, not learned to score well.
This validates state/scoring mechanics under today's chip rules applied to older
football outcomes. It cannot validate optimal timing or current-rule point lift.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .historical_blank_holdings import complete_blank_holdings
from .horizon_decay_replay import _initial_state, _load_inputs
from .rules import load_rules
from .season_state import ActionBundle, ChipType, apply_action
from .tournament import _score_candidates
from .weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from .weekly_continuation_replay import (
    ReplayConfig,
    prefix_coefficients,
    prepare_deadline,
    reprice_state,
)

CALENDAR = {
    5: ChipType.WILDCARD,
    6: ChipType.BENCH_BOOST,
    10: ChipType.TRIPLE_CAPTAIN,
    18: ChipType.FREE_HIT,
    24: ChipType.WILDCARD,
    25: ChipType.BENCH_BOOST,
    30: ChipType.TRIPLE_CAPTAIN,
    37: ChipType.FREE_HIT,
}


def verify_transition(state, outcome, chip):
    if chip in {ChipType.WILDCARD, ChipType.FREE_HIT}:
        if outcome.gameweek.incremental_points_cost != 0:
            raise ValueError("Squad chip charged a transfer hit")
        if outcome.next_manager.free_transfers != state.free_transfers:
            raise ValueError("Squad chip changed banked transfers")
    if chip == ChipType.FREE_HIT:
        if outcome.next_manager.squad != state.squad or outcome.next_manager.bank != state.bank:
            raise ValueError("Free Hit did not restore the exact permanent holdings and bank")
    elif chip == ChipType.WILDCARD and outcome.next_manager.squad != outcome.gameweek.squad:
        raise ValueError("Wildcard did not persist its new holdings")


def actual_score(outcome, outcomes):
    selected = sorted(h.player_id for h in outcome.gameweek.squad)
    by_id = {int(r["element"]): r for r in outcomes}
    if not set(selected) <= set(by_id):
        raise ValueError("Unknown historical player outcomes; do not zero-fill")
    lineup = outcome.gameweek.lineup
    chip = outcome.gameweek.chip
    captain = lineup.captain if by_id[lineup.captain]["target_minutes"] > 0 else lineup.vice_captain
    captain_bonus = (
        int(by_id[captain]["target_points"]) if by_id[captain]["target_minutes"] > 0 else 0
    )
    if chip == ChipType.BENCH_BOOST:
        gross = sum(int(by_id[p]["target_points"]) for p in selected) + captain_bonus
    else:
        candidate = {
            "candidate_id": "actual",
            "selected": selected,
            "lineups": {
                str(outcome.gameweek.event): {
                    "starters": list(lineup.starters),
                    "bench_order": list(lineup.bench_order),
                    "captain": lineup.captain,
                    "vice_captain": lineup.vice_captain,
                }
            },
        }
        points = np.asarray([[[by_id[p]["target_points"] for p in selected]]], dtype=np.int16)
        played = np.asarray([[[by_id[p]["target_minutes"] > 0 for p in selected]]], dtype=bool)
        gross = float(
            _score_candidates(
                [candidate], selected, (outcome.gameweek.event,), points, played, by_id
            )[0, 0, 0]
        )
        if chip == ChipType.TRIPLE_CAPTAIN:
            gross += captain_bonus
    return float(gross) - outcome.gameweek.incremental_points_cost


def run(output: Path, *, seasons=("2024-25", "2025-26"), progress=print):
    from .deadline_pipeline import weekly_pipeline_implementation_sha256

    if output.exists():
        raise FileExistsError("Preserve previous research receipts")
    started = time.monotonic()
    implementation = weekly_pipeline_implementation_sha256()
    inputs = _load_inputs()
    catalog_path = PROCESSED / "vaastav_deadlines" / "player_snapshots.parquet"
    final_fixture_path = PROCESSED / "vaastav" / "fixtures.parquet"
    inputs["paths"].update(
        blank_holding_catalog=catalog_path, blank_outcome_certificate=final_fixture_path
    )
    catalog_rows = pq.read_table(
        catalog_path,
        columns=[
            "season",
            "id",
            "decision_event",
            "deadline_at",
            "observed_at",
            "team",
            "now_cost",
            "can_select",
            "removed",
            "snapshot_sha",
        ],
    ).to_pylist()
    final_fixtures = pq.read_table(
        final_fixture_path, columns=["season", "id", "event", "finished", "team_h", "team_a"]
    ).to_pylist()
    rules = load_rules()
    zero_terminal = {i: 0.0 for i in range(rules.max_free_transfers + 1)}
    result = {
        "version": "joint_chip_state_replay_v1",
        "status": "running",
        "decision_authority": False,
        "created_at": datetime.now(UTC).isoformat(),
        "implementation_sha256": implementation,
        "calendar": {e: c.value for e, c in CALENDAR.items()},
        "sources": {
            k: {"path": str(p), "sha256": sha256_file(p)} for k, p in inputs["paths"].items()
        },
        "rules": asdict(rules),
        "seasons": [],
        "scope": "Precommitted transition/scoring test, not a chip-timing policy or historical current-rule points claim.",
        "limitations": [
            "Today's eight-chip/FT rules applied counterfactually to historical outcomes.",
            "Historical points use their season's scoring; no invented defensive contributions.",
            "Fixed five-event screening objective and zero terminal-FT ablation, not the production three-world selector.",
            "Fixtures/forecasts/prices use each origin only; actual outcomes are separate.",
            "No promotion authority: optimal retained chip value still requires causal policy comparison.",
            "Missing blank-player forecasts use labelled prior-rate reconstruction; catalog ages are recorded. Last observed prices are not certified current prices when a deadline catalog is absent.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def persist():
        output.write_text(json.dumps(result, indent=2, default=str) + "\n")

    persist()
    for season in seasons:
        records = []
        path = {"season": season, "status": "running", "events": records}
        result["seasons"].append(path)
        coefficients, training = prefix_coefficients(inputs, season)
        path["fixture_response_training_seasons"] = training
        state = None
        try:
            for event in range(1, 39):
                rows, outcomes, snapshot = prepare_deadline(
                    inputs, season, event, ReplayConfig(), coefficients
                )
                repairs = []
                if state is not None:
                    rows, outcomes, repairs = complete_blank_holdings(
                        state,
                        rows,
                        outcomes,
                        inputs,
                        coefficients,
                        catalog_rows=catalog_rows,
                        final_fixtures=final_fixtures,
                    )
                events = tuple(sorted({r["event_number"] for r in rows}))
                current = [r for r in rows if r["event_number"] == event]
                trace = []
                chip = CALENDAR.get(event)
                if state is None:
                    state, _ = _initial_state(
                        season=season, rows=rows, events=events, decay=0.88, rules=rules
                    )
                    chosen = ActionBundle(event, state.lineup)
                else:
                    state = reprice_state(state, current)
                    ordinary = generate_weekly_actions(
                        state,
                        rows,
                        rules,
                        events=events,
                        max_total_transfers=2,
                        max_paid_transfers=1,
                        alternatives_per_transfer_count=1,
                        protect_role_sale_routes=False,
                        terminal_free_transfer_curve=zero_terminal,
                        solver_time_limit_seconds=3,
                        search_diagnostics=trace,
                    )
                    candidates = ordinary
                    if chip in {ChipType.WILDCARD, ChipType.FREE_HIT}:
                        candidates = generate_squad_chip_shadow_actions(
                            state,
                            rows,
                            rules,
                            events=events,
                            alternatives_per_chip=1,
                            terminal_free_transfer_curve=zero_terminal,
                            solver_time_limit_seconds=5,
                            search_diagnostics=trace,
                        )
                    elif chip:
                        candidates = generate_team_chip_shadow_actions(
                            state, ordinary, rows, rules, events=events
                        )
                    candidates = [a for a in candidates if a.action.chip == chip]
                    if not candidates or any(t["status"] == "unresolved" for t in trace):
                        raise ValueError(f"Incomplete solve at GW{event}: {trace}")
                    selected = max(
                        candidates,
                        key=lambda a: a.gross_horizon_utility - a.incremental_points_cost,
                    )
                    chosen = selected.action
                outcome = apply_action(state, chosen, rules)
                verify_transition(state, outcome, chip)
                records.append(
                    {
                        "event": event,
                        "chip": chip.value if chip else None,
                        "bank_before": state.bank,
                        "bank_after": outcome.gameweek.bank,
                        "ft_before": state.free_transfers,
                        "ft_after": outcome.next_manager.free_transfers
                        if outcome.next_manager
                        else None,
                        "selected": [h.player_id for h in outcome.gameweek.squad],
                        "next_permanent_selected": [h.player_id for h in outcome.next_manager.squad]
                        if outcome.next_manager
                        else None,
                        "transfers": [asdict(t) for t in chosen.transfers],
                        "lineup": asdict(chosen.lineup),
                        "chip_inventory": [asdict(c) for c in outcome.next_manager.chips]
                        if outcome.next_manager
                        else [],
                        "hit_cost": outcome.gameweek.incremental_points_cost,
                        "net_points": actual_score(outcome, outcomes),
                        "forecast_snapshot": snapshot,
                        "missing_holding_reconstructions": repairs,
                        "search_trace": trace,
                    }
                )
                state = outcome.next_manager
                if event % 5 == 0 or chip:
                    progress(
                        f"Joint chip state audit: {season} GW{event}/38; {chip.value if chip else 'ordinary transfers'}",
                        flush=True,
                    )
                    persist()
            if sum(r["chip"] is not None for r in records) != 8:
                raise ValueError("Did not exercise every chip slot")
            path["status"] = "passed_state_and_scoring_audit"
        except (ValueError, RuntimeError, TypeError, KeyError) as exc:
            path.update(status="blocked_audit", error=str(exc))
            progress(f"Joint chip state audit: {season} blocked: {exc}", flush=True)
        persist()
    result["status"] = (
        "passed_state_and_scoring_audit"
        if all(s["status"] == "passed_state_and_scoring_audit" for s in result["seasons"])
        else "blocked_audit"
    )
    result["elapsed_seconds"] = time.monotonic() - started
    result["implementation_unchanged"] = implementation == weekly_pipeline_implementation_sha256()
    if not result["implementation_unchanged"]:
        result["status"] = "implementation_changed_during_audit"
    persist()
    return result
