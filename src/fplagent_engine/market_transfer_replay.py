from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .component_backtest import OOF_FORECAST
from .features import TRAINING_FEATURES
from .market_odds import MARKET_RECEIPT, current_season_source_available
from .market_policy_replay import RESULTS_JSON as SELECTION_REPLAY
from .models import BACKTEST_FORECAST
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .rules import SquadRules, load_rules
from .season_state import (
    ActionBundle,
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    apply_action,
    calculated_selling_price,
    default_chip_inventory,
)
from .tournament import _score_candidates
from .transfer_value import ARTIFACT as TRANSFER_VALUE_ARTIFACT
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_actions import EvaluatedAction, generate_weekly_actions

OUTPUT_DIR = MODEL_DATA / "market_transfer_policy_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "market-goal-sequential-transfer-replay.md"
SEASONS = ("2024-25", "2025-26")
POLICIES = ("incumbent_xp", "internal_component_control", "market_challenger")


def moving_block_mean_interval(
    values: list[float] | np.ndarray,
    *,
    block_length: int = 4,
    samples: int = 5_000,
    seed: int = 20260807,
) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    if len(array) < block_length or block_length < 1:
        raise ValueError("Block interval needs at least one complete positive-length block")
    if samples < 500:
        raise ValueError("Block interval requires at least 500 samples")
    rng = np.random.default_rng(seed)
    block_count = math.ceil(len(array) / block_length)
    means = np.empty(samples, dtype=np.float64)
    offsets = np.arange(block_length)
    for sample in range(samples):
        starts = rng.integers(0, len(array), size=block_count)
        indices = (starts[:, None] + offsets[None, :]).reshape(-1)[: len(array)] % len(array)
        means[sample] = array[indices].mean()
    return {
        "events": len(array),
        "block_length": block_length,
        "samples": samples,
        "mean": float(array.mean()),
        "p025": float(np.quantile(means, 0.025)),
        "p975": float(np.quantile(means, 0.975)),
    }


def _load_event_rows(
    seasons: tuple[str, ...] = SEASONS,
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], dict[str, Any]]:
    component = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(OOF_FORECAST).to_pylist()
    }
    minutes = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row["target_minutes"]
        )
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in seasons
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    component_coverage = {season: {"covered": 0, "fallback": 0} for season in seasons}
    excluded = 0
    for raw in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(raw["season"])
        if season not in seasons:
            continue
        key = (season, int(raw["event_number"]), int(raw["element"]))
        if raw.get("market_price") is None or key not in minutes:
            excluded += 1
            continue
        xp = float(raw["expected_points"])
        component_row = component.get(key)
        if component_row is None:
            internal_component = xp
            market_component = xp
            component_coverage[season]["fallback"] += 1
        else:
            internal_component = float(component_row["component_expected_points"])
            market_component = float(component_row["market_component_expected_points"])
            component_coverage[season]["covered"] += 1
        enriched = {
            **raw,
            "market_price": round(float(raw["market_price"])),
            "target_points": float(raw["target_points"]),
            "target_minutes": minutes[key],
            "xp_expected_points": xp,
            "internal_component_expected_points": internal_component,
            "market_component_expected_points": market_component,
            "p_play": float(raw.get("p_play", 1.0)),
            "can_select": True,
            "removed": False,
        }
        grouped.setdefault((season, int(raw["event_number"])), []).append(enriched)
    for season in seasons:
        events = sorted(event for candidate, event in grouped if candidate == season)
        if events != list(range(1, 39)):
            raise ValueError(f"Sequential replay requires events 1-38 for {season}: {events}")
    return grouped, {
        "component_coverage": component_coverage,
        "excluded_incomplete_rows": excluded,
        "fallback_policy": "complete direct-xP pool; component-missing rows retain direct xP",
    }


def _policy_rows(
    rows: list[dict[str, Any]], policy: str, market_weight: float
) -> list[dict[str, Any]]:
    if policy not in POLICIES:
        raise ValueError(f"Unknown sequential replay policy {policy}")
    output = []
    for row in rows:
        xp = float(row["xp_expected_points"])
        if policy == "incumbent_xp":
            score = xp
        elif policy == "internal_component_control":
            score = (
                market_weight * float(row["internal_component_expected_points"])
                + (1.0 - market_weight) * xp
            )
        else:
            score = (
                market_weight * float(row["market_component_expected_points"])
                + (1.0 - market_weight) * xp
            )
        output.append({**row, "expected_points": score, "robust_points": score})
    return output


def blend_score_rows(
    rows: list[dict[str, Any]], score_field: str, challenger_weight: float
) -> list[dict[str, Any]]:
    """Blend any historical challenger score with the direct-xP champion.

    The sequential replay machinery owns the difficult season-state mechanics.  Keeping
    challenger scoring behind this small adapter lets future forecast experiments reuse the
    exact same transfer, price, autosub and captain evaluation rather than implementing subtly
    different backtests.
    """
    if not 0.0 <= challenger_weight <= 1.0:
        raise ValueError("challenger_weight must be in [0, 1]")
    output = []
    for row in rows:
        if score_field not in row:
            raise KeyError(f"Sequential replay row is missing {score_field!r}")
        xp = float(row["xp_expected_points"])
        score = challenger_weight * float(row[score_field]) + (1.0 - challenger_weight) * xp
        output.append({**row, "expected_points": score, "robust_points": score})
    return output


def _initial_state(
    *, season: str, rows: list[dict[str, Any]], rules: SquadRules
) -> tuple[ManagerState, dict[str, Any]]:
    solution = _solve(rows, [1], rules=rules)
    selected = tuple(int(element) for element in solution["selected"])
    by_id = {int(row["element"]): row for row in rows}
    holdings = tuple(
        PlayerHolding(
            player_id=element,
            position=str(by_id[element]["position"]),
            team_id=int(by_id[element]["team_id"]),
            purchase_price=round(float(by_id[element]["market_price"])),
            current_price=round(float(by_id[element]["market_price"])),
            selling_price=round(float(by_id[element]["market_price"])),
        )
        for element in selected
    )
    lineup_row = solution["lineups"][1]
    lineup = Lineup(
        starters=tuple(int(element) for element in lineup_row["starters"]),
        bench_order=tuple(int(element) for element in lineup_row["bench_order"]),
        captain=int(lineup_row["captain"]),
        vice_captain=int(lineup_row["vice_captain"]),
    )
    spend = sum(holding.purchase_price for holding in holdings)
    state = ManagerState(
        season=season,
        event=1,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=holdings,
        bank=rules.budget - spend,
        free_transfers=1,
        chips=default_chip_inventory(),
        lineup=lineup,
    )
    return state, solution


def refresh_holding_prices(
    state: ManagerState, rows: list[dict[str, Any]]
) -> ManagerState:
    current = {int(row["element"]): row for row in rows}
    holdings = []
    for holding in state.squad:
        row = current.get(holding.player_id)
        if row is None:
            holdings.append(holding)
            continue
        current_price = round(float(row["market_price"]))
        holdings.append(
            replace(
                holding,
                current_price=current_price,
                selling_price=calculated_selling_price(
                    holding.purchase_price, current_price
                ),
            )
        )
    return replace(state, squad=tuple(holdings))


def _with_missing_holdings(
    state: ManagerState, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    output = list(rows)
    present = {int(row["element"]) for row in rows}
    for holding in state.squad:
        if holding.player_id in present:
            continue
        output.append(
            {
                "season": state.season,
                "event_number": state.event,
                "element": holding.player_id,
                "player_name": f"Unavailable #{holding.player_id}",
                "position": holding.position,
                "team_id": holding.team_id,
                "market_price": holding.current_price,
                "target_points": 0.0,
                "target_minutes": 0.0,
                "expected_points": 0.0,
                "robust_points": 0.0,
                "p_play": 0.0,
                "can_select": False,
                "removed": True,
            }
        )
    return output


def _score_gameweek(
    action: EvaluatedAction | None,
    state: ManagerState,
    initial_solution: dict[str, Any] | None,
    rows: list[dict[str, Any]],
) -> int:
    event = state.event
    if action is None:
        if initial_solution is None:
            raise ValueError("GW1 scoring requires its initial solution")
        selected = list(initial_solution["selected"])
        lineup = initial_solution["lineups"][event]
    else:
        selected = [holding.player_id for holding in action.outcome.gameweek.squad]
        played_lineup = action.action.lineup
        lineup = {
            "starters": list(played_lineup.starters),
            "bench_order": list(played_lineup.bench_order),
            "captain": played_lineup.captain,
            "vice_captain": played_lineup.vice_captain,
        }
    by_id = {int(row["element"]): row for row in rows}
    player_ids = sorted(by_id)
    points = np.asarray(
        [[[by_id[player]["target_points"] for player in player_ids]]], dtype=np.int16
    )
    played = np.asarray(
        [[[by_id[player]["target_minutes"] > 0 for player in player_ids]]], dtype=bool
    )
    candidate = {
        "candidate_id": "sequential-policy",
        "selected": selected,
        "lineups": {str(event): lineup},
    }
    score = _score_candidates(
        [candidate],
        player_ids,
        (event,),
        points,
        played,
        by_id,
    )[0, 0, 0]
    return int(score)


def _event_record(
    *,
    event: int,
    gross_points: int,
    action: EvaluatedAction | None,
    state: ManagerState,
    solution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if action is None:
        if solution is None:
            raise ValueError("Initial event record requires a solution")
        transfers: list[dict[str, int]] = []
        selected = [int(element) for element in solution["selected"]]
        lineup = solution["lineups"][event]
        bank_after = state.bank
        free_before = state.free_transfers
        free_after = min(5, state.free_transfers + 1)
        points_cost = 0
        route = "initial_squad"
        utility = float(solution["objective"])
    else:
        transfers = [
            {
                "out": transfer.outgoing_player_id,
                "in": transfer.incoming.player_id,
            }
            for transfer in action.action.transfers
        ]
        selected = list(action.selected_player_ids)
        played_lineup = action.action.lineup
        lineup = {
            "starters": list(played_lineup.starters),
            "bench_order": list(played_lineup.bench_order),
            "captain": played_lineup.captain,
            "vice_captain": played_lineup.vice_captain,
        }
        bank_after = action.outcome.gameweek.bank
        free_before = action.outcome.gameweek.free_transfers_before
        free_after = action.next_free_transfers
        points_cost = action.incremental_points_cost
        route = action.route_type
        utility = action.decision_utility
    return {
        "event": event,
        "route": route,
        "gross_points": gross_points,
        "points_cost": points_cost,
        "net_points": gross_points - points_cost,
        "transfers": transfers,
        "transfer_count": len(transfers),
        "free_transfers_before": free_before,
        "free_transfers_after": free_after,
        "bank_after": bank_after,
        "selected": selected,
        "starters": list(lineup["starters"]),
        "bench_order": list(lineup["bench_order"]),
        "captain": int(lineup["captain"]),
        "vice_captain": int(lineup["vice_captain"]),
        "decision_utility": utility,
    }


def run_policy_season(
    *,
    season: str,
    policy: str,
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
    market_weight: float,
    rules: SquadRules,
    terminal_curve: dict[int, float],
    score_field: str | None = None,
) -> dict[str, Any]:
    def scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if score_field is not None:
            return blend_score_rows(rows, score_field, market_weight)
        return _policy_rows(rows, policy, market_weight)

    first_rows = scored(grouped[(season, 1)])
    state, initial_solution = _initial_state(season=season, rows=first_rows, rules=rules)
    event_records = []
    gross = _score_gameweek(None, state, initial_solution, first_rows)
    event_records.append(
        _event_record(
            event=1,
            gross_points=gross,
            action=None,
            state=state,
            solution=initial_solution,
        )
    )
    initial_outcome = apply_action(state, ActionBundle(1, state.lineup), rules)
    if initial_outcome.next_manager is None:
        raise RuntimeError("GW1 unexpectedly ended the season")
    state = initial_outcome.next_manager

    for event in range(2, 39):
        rows = scored(grouped[(season, event)])
        state = refresh_holding_prices(state, rows)
        rows = _with_missing_holdings(state, rows)
        actions = generate_weekly_actions(
            state,
            rows,
            rules,
            events=(event,),
            score_field="expected_points",
            alternatives_per_transfer_count=1,
            max_total_transfers=5,
            max_paid_transfers=2,
            terminal_free_transfer_curve=terminal_curve,
        )
        if not actions:
            raise RuntimeError(f"No legal actions for {season} GW{event} under {policy}")
        action = actions[0]
        gross = _score_gameweek(action, state, None, rows)
        event_records.append(
            _event_record(
                event=event,
                gross_points=gross,
                action=action,
                state=state,
            )
        )
        if event < 38:
            if action.outcome.next_manager is None:
                raise RuntimeError(f"Missing next manager state after GW{event}")
            state = action.outcome.next_manager

    return {
        "season": season,
        "policy": policy,
        "gross_points": sum(row["gross_points"] for row in event_records),
        "points_cost": sum(row["points_cost"] for row in event_records),
        "net_points": sum(row["net_points"] for row in event_records),
        "transfers": sum(row["transfer_count"] for row in event_records),
        "hits": sum(row["points_cost"] for row in event_records) // 4,
        "rolls": sum(row["route"] == "roll" for row in event_records),
        "events": event_records,
    }


def _gate(paths: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    validation_market = paths[("2024-25", "market_challenger")]
    validation_incumbent = paths[("2024-25", "incumbent_xp")]
    test_market = paths[("2025-26", "market_challenger")]
    test_incumbent = paths[("2025-26", "incumbent_xp")]
    test_control = paths[("2025-26", "internal_component_control")]
    validation_delta = validation_market["net_points"] - validation_incumbent["net_points"]
    test_deltas = [
        market["net_points"] - incumbent["net_points"]
        for market, incumbent in zip(
            test_market["events"], test_incumbent["events"], strict=True
        )
    ]
    control_deltas = [
        market["net_points"] - control["net_points"]
        for market, control in zip(test_market["events"], test_control["events"], strict=True)
    ]
    interval = moving_block_mean_interval(test_deltas)
    control_interval = moving_block_mean_interval(control_deltas, seed=20260808)
    checks = {
        "positive_validation_total": validation_delta > 0,
        "positive_frozen_test_total": sum(test_deltas) > 0,
        "frozen_test_block_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
        "positive_frozen_test_total_vs_internal_control": sum(control_deltas) > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "validation_total_delta": validation_delta,
        "validation_mean_delta": validation_delta / 38.0,
        "frozen_test_total_delta": sum(test_deltas),
        "frozen_test_mean_delta": sum(test_deltas) / 38.0,
        "frozen_test_moving_block_interval": interval,
        "frozen_test_total_delta_vs_internal_control": sum(control_deltas),
        "frozen_test_mean_delta_vs_internal_control": sum(control_deltas) / 38.0,
        "frozen_test_control_moving_block_interval": control_interval,
    }


def _render(result: dict[str, Any]) -> str:
    gate = result["gate"]
    lines = [
        "# Market goal signal: sequential transfer-policy replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — the validation path changed by "
            f"{gate['validation_total_delta']:+.0f} net points "
            f"({gate['validation_mean_delta']:+.3f}/GW). On the untouched 2025/26 path, the "
            f"market challenger changed achievable ordinary-transfer points by "
            f"{gate['frozen_test_total_delta']:+.0f} "
            f"({gate['frozen_test_mean_delta']:+.3f}/GW), with a four-GW moving-block 95% "
            f"interval of {gate['frozen_test_moving_block_interval']['p025']:+.3f} to "
            f"{gate['frozen_test_moving_block_interval']['p975']:+.3f}/GW."
        ),
        "",
        "Each policy starts from its own legal GW1 squad, then carries one continuous squad, bank, purchase prices, selling values and free-transfer balance. Every deadline compares roll, free-transfer and up-to-two-hit routes after cost, while reoptimising XI, bench, captain and vice from all 15 players.",
        "",
        "## Validation weight selection",
        "",
        "| Market weight | Gross | Hits cost | Net | Transfers | Rolls |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["weight_calibration"]["candidates"]:
        lines.append(
            f"| {row['raw_weight']:.2f} | {row['gross_points']} | {row['points_cost']} | "
            f"{row['net_points']} | {row['transfers']} | {row['rolls']} |"
        )
    lines.extend(
        [
        "",
        "## Season paths",
        "",
        "| Season | Policy | Gross | Hits cost | Net | Transfers | Rolls |",
        "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for season in SEASONS:
        for policy in POLICIES:
            row = result["paths"][f"{season}:{policy}"]
            lines.append(
                f"| {season} | {policy} | {row['gross_points']} | {row['points_cost']} | "
                f"{row['net_points']} | {row['transfers']} | {row['rolls']} |"
            )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- The blend weight is selected only on continuous 2024/25 net points from the declared coarse grid, with zero included as the incumbent; 2025/26 remains untouched for this test.",
            "- Blank/double or otherwise component-missing player rows remain in the candidate pool with direct xP, rather than being excluded.",
            "- If a held player changes Premier League clubs, the historical state keeps its acquisition-club identity for strict legacy-state validation; every deadline optimiser still uses the current club and enforces the current three-player limit.",
            "- This tests ordinary roll/free/hit decisions. Wildcard, Free Hit, Bench Boost and Triple Captain are deliberately excluded and need their own historical policies.",
            "- The four-GW moving-block interval acknowledges serial dependence, but only one path per season exists. Prospective 2026/27 receipts remain the decisive evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def run_market_transfer_replay() -> dict[str, Any]:
    selection = json.loads(SELECTION_REPLAY.read_text(encoding="utf-8"))
    prior_selection_weight = float(selection["weight_calibration"]["selected_raw_weight"])
    grouped, coverage = _load_event_rows()
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers,
        rules=rules,
    )
    candidate_weights = (0.0, 0.25, 0.50, 0.75, 1.0)
    validation_candidates = {
        weight: run_policy_season(
            season="2024-25",
            policy="market_challenger",
            grouped=grouped,
            market_weight=weight,
            rules=rules,
            terminal_curve=terminal_curve,
        )
        for weight in candidate_weights
    }
    market_weight = max(
        candidate_weights,
        key=lambda weight: (validation_candidates[weight]["net_points"], -weight),
    )
    paths = {
        ("2024-25", "incumbent_xp"): {
            **validation_candidates[0.0],
            "policy": "incumbent_xp",
        },
        ("2024-25", "market_challenger"): validation_candidates[market_weight],
        ("2024-25", "internal_component_control"): run_policy_season(
            season="2024-25",
            policy="internal_component_control",
            grouped=grouped,
            market_weight=market_weight,
            rules=rules,
            terminal_curve=terminal_curve,
        ),
    }
    for policy in POLICIES:
        paths[("2025-26", policy)] = run_policy_season(
            season="2025-26",
            policy=policy,
            grouped=grouped,
            market_weight=market_weight,
            rules=rules,
            terminal_curve=terminal_curve,
        )
    gate = _gate(paths)
    gate["checks"]["nonzero_weight_selected_on_validation"] = market_weight > 0.0
    gate["passed"] = all(gate["checks"].values())
    current_source = current_season_source_available()
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS_SHADOW" if gate["passed"] else "REJECT",
        "status": "shadow",
        "market_raw_weight": market_weight,
        "prior_independent_selection_weight": prior_selection_weight,
        "weight_calibration": {
            "season": "2024-25",
            "objective": "continuous ordinary-transfer net points",
            "selected_raw_weight": market_weight,
            "candidates": [
                {
                    "raw_weight": weight,
                    "gross_points": validation_candidates[weight]["gross_points"],
                    "points_cost": validation_candidates[weight]["points_cost"],
                    "net_points": validation_candidates[weight]["net_points"],
                    "transfers": validation_candidates[weight]["transfers"],
                    "rolls": validation_candidates[weight]["rolls"],
                }
                for weight in candidate_weights
            ],
        },
        "gate": gate,
        "coverage": coverage,
        "current_source": current_source,
        "transfer_value": terminal_receipt,
        "paths": {f"{season}:{policy}": path for (season, policy), path in paths.items()},
        "artifacts": {
            "direct_forecast": str(BACKTEST_FORECAST),
            "direct_forecast_sha256": sha256_file(BACKTEST_FORECAST),
            "component_oof": str(OOF_FORECAST),
            "component_oof_sha256": sha256_file(OOF_FORECAST),
            "selection_replay": str(SELECTION_REPLAY),
            "selection_replay_sha256": sha256_file(SELECTION_REPLAY),
            "market_receipt": str(MARKET_RECEIPT),
            "market_receipt_sha256": sha256_file(MARKET_RECEIPT),
            "transfer_value": str(TRANSFER_VALUE_ARTIFACT),
            "transfer_value_sha256": sha256_file(TRANSFER_VALUE_ARTIFACT),
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS_JSON.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS_JSON)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
