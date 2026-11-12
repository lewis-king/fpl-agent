"""Chronological, paired early-season test of next-deadline transfer recourse.

This is an isolated planner experiment, not a replay of the full production
three-world selector. Its forecasts, outcomes and state are kept separate. No
result from this module grants decision authority or writes the active workspace.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .horizon_decay_replay import (
    _fixture_response_coefficients,
    _historical_rules,
    _initial_state,
    _load_inputs,
    build_deadline_horizon_rows,
)
from .market_transfer_replay import _score_gameweek, moving_block_mean_interval
from .season_state import ActionBundle, ManagerState, apply_action, validate_manager_state
from .weekly_actions import EvaluatedAction, generate_weekly_actions
from .weekly_continuation import _fingerprint, evaluate_weekly_continuation


@dataclass(frozen=True)
class ReplayConfig:
    seasons: tuple[str, ...] = ("2024-25", "2025-26")
    end_event: int = 10
    horizon: int = 5
    decay: float = 0.88
    maximum_transfers: int = 2
    maximum_paid_transfers: int = 1
    solver_seconds: float = 2.0
    continuation_seconds: float = 24.0

    def validate(self) -> None:
        if not self.seasons or any(s not in ("2024-25", "2025-26") for s in self.seasons):
            raise ValueError("Replay supports the two recent five-FT-cap seasons")
        if len(set(self.seasons)) != len(self.seasons):
            raise ValueError("Duplicate replay seasons")
        # Deliberately isolate the opening ordinary-transfer period. Do not
        # silently cross historical midseason FT grants/chip-rule changes.
        if not 2 <= self.end_event <= 10 or not 2 <= self.horizon <= 5:
            raise ValueError("This early-season experiment supports GW2–10 and horizons 2–5")
        if not 0 < self.decay <= 1 or not 1 <= self.maximum_transfers <= 2:
            raise ValueError("Invalid replay decay/transfer bounds")
        if self.maximum_paid_transfers not in (0, 1):
            raise ValueError("At most one paid transfer is supported")
        if any(
            not math.isfinite(v) or v <= 0 for v in (self.solver_seconds, self.continuation_seconds)
        ):
            raise ValueError("Replay solver budgets must be finite and positive")


def prefix_coefficients(inputs: dict[str, Any], season: str) -> tuple[dict, list[str]]:
    earlier = sorted({str(r["season"]) for r in inputs["forecasts"] if str(r["season"]) < season})
    if not earlier:
        raise ValueError(f"No earlier training season for {season}")
    return _fixture_response_coefficients(
        [r for r in inputs["forecasts"] if str(r["season"]) in earlier],
        [r for r in inputs["features"] if str(r["season"]) in earlier],
    ), earlier


def prepare_deadline(
    inputs: dict[str, Any],
    season: str,
    event: int,
    config: ReplayConfig,
    coefficients: dict,
) -> tuple[list[dict], list[dict], dict]:
    """Return label-free decision rows and a distinct, strictly checked scoring table."""
    base = inputs["forecast_by_event"].get((season, event))
    if not base:
        raise ValueError(f"Missing forecasts for {season} GW{event}")
    outcomes = []
    seen = set()
    for row in base:
        player = int(row["element"])
        if player in seen:
            raise ValueError("Duplicate deadline player")
        seen.add(player)
        feature = inputs["feature_by_key"].get((season, event, player), {})
        points, minutes = row.get("target_points"), feature.get("target_minutes")
        if any(v is None or not math.isfinite(float(v)) for v in (points, minutes)):
            raise ValueError(f"Missing actual outcome for {season} GW{event} player {player}")
        if float(points) != int(points) or float(minutes) < 0:
            raise ValueError("Invalid historical points/minutes")
        outcomes.append(
            {
                "element": player,
                "position": row["position"],
                "target_points": int(points),
                "target_minutes": float(minutes),
            }
        )
    rows, snapshot = build_deadline_horizon_rows(
        season=season,
        origin_event=event,
        horizon=config.horizon,
        # A scoring window is NOT the season end: keep the future forecasts
        # beyond GW10 even though their outcomes are not part of this test.
        end_event=38,
        forecast_by_event=inputs["forecast_by_event"],
        feature_by_key=inputs["feature_by_key"],
        fixture_by_snapshot=inputs["fixture_by_snapshot"],
        available_snapshots=inputs["available_snapshots"],
        coefficients=coefficients,
    )
    decision_rows = [
        {k: v for k, v in r.items() if not k.startswith(("target_", "realized_"))} for r in rows
    ]
    if any(
        r["forecast_origin_event"] != event or r["fixture_snapshot_event"] > event
        for r in decision_rows
    ):
        raise ValueError("Forecast lineage crosses the decision deadline")
    return decision_rows, outcomes, snapshot


def reprice_state(state: ManagerState, current: list[dict]) -> ManagerState:
    rules = _historical_rules(state.season)
    validate_manager_state(state, rules)
    catalog = {int(r["element"]): r for r in current}
    holdings = []
    for holding in state.squad:
        row = catalog.get(holding.player_id)
        if row is None:
            raise ValueError(
                f"Missing holding {holding.player_id}; cannot assume zero points/price"
            )
        if str(row["position"]) != holding.position:
            raise ValueError(f"Historical holding {holding.player_id} changes position")
        price = float(row["market_price"])
        if not math.isfinite(price) or price <= 0 or price != round(price):
            raise ValueError("Invalid as-of-deadline price")
        # A real-world club transfer is not a fantasy transfer: retain purchase
        # price, bank and FTs while using the club known at THIS deadline.
        holdings.append(
            replace(holding.with_current_price(int(price)), team_id=int(row["team_id"]))
        )
    overflow = any(
        sum(p.team_id == h.team_id for p in holdings) > rules.club_limit for h in holdings
    )
    changed_club = any(a.team_id != b.team_id for a, b in zip(state.squad, holdings, strict=True))
    updated = replace(
        state,
        squad=tuple(holdings),
        club_overflow_allowed=overflow and (changed_club or state.club_overflow_allowed),
    )
    validate_manager_state(updated, rules)
    return updated


def _record(state, action, solution, outcomes, snapshot, rows, search, diagnostic):
    if action is None:
        lineup = state.lineup
        outcome = apply_action(
            state, ActionBundle(state.event, lineup), _historical_rules(state.season)
        )
        selected = [h.player_id for h in state.squad]
        transfers = []
    else:
        lineup, outcome = action.action.lineup, action.outcome
        selected = list(action.selected_player_ids)
        names = {int(r["element"]): str(r["player_name"]) for r in rows}
        transfers = [
            {
                "out": t.outgoing_player_id,
                "in": t.incoming.player_id,
                "out_name": names[t.outgoing_player_id],
                "in_name": names[t.incoming.player_id],
            }
            for t in action.action.transfers
        ]
    if not set(selected) <= {r["element"] for r in outcomes}:
        raise ValueError("Missing selected-player actual outcome")
    gross = _score_gameweek(action, state, solution, outcomes)
    cost = outcome.gameweek.incremental_points_cost
    return {
        "event": state.event,
        "gross_points": gross,
        "points_cost": cost,
        "net_points": gross - cost,
        "transfers": transfers,
        "selected": selected,
        "starters": list(lineup.starters),
        "bench_order": list(lineup.bench_order),
        "captain": lineup.captain,
        "vice_captain": lineup.vice_captain,
        "free_transfers_before": state.free_transfers,
        "free_transfers_after": outcome.next_manager.free_transfers,
        "bank_after": outcome.gameweek.bank,
        "sale_value_after": sum(p.selling_price for p in outcome.gameweek.squad),
        "action_id": action.action_id if action else "initial_squad",
        "forecast_sha256": _fingerprint(rows, "expected_points"),
        "snapshot": snapshot,
        "search_diagnostics": search,
        "continuation": diagnostic,
    }, outcome.next_manager


def paired_season(
    inputs: dict[str, Any],
    season: str,
    config: ReplayConfig,
    progress=None,
) -> dict:
    config.validate()
    coefficients, training_seasons = prefix_coefficients(inputs, season)
    rules = _historical_rules(season)
    # Avoid importing today's FT curve, which has seen the evaluation seasons.
    # Both arms use the same zero-terminal ablation. Recourse still values the
    # real bank of free transfers through next week's legal action/hit costs.
    terminal_curve = {i: 0.0 for i in range(rules.max_free_transfers + 1)}
    records: dict[str, list[dict]] = {"fixed_roster": [], "next_deadline_recourse": []}
    states: dict[str, ManagerState] = {}
    for event in range(1, config.end_event + 1):
        rows, outcomes, snapshot = prepare_deadline(inputs, season, event, config, coefficients)
        events = tuple(sorted({int(r["event_number"]) for r in rows}))
        current = [r for r in rows if r["event_number"] == event]
        if event == 1:
            initial, solution = _initial_state(
                season=season,
                rows=rows,
                events=events,
                decay=config.decay,
                rules=rules,
            )
            # Same initial roster AND lineup, solved once, zero bankable GW1 FT.
            record, next_state = _record(
                initial, None, solution, outcomes, snapshot, rows, [], None
            )
            for policy, path in records.items():
                path.append(record)
                states[policy] = next_state
        else:
            shared_searches: dict[ManagerState, tuple[list[EvaluatedAction], list[dict]]] = {}
            for policy, path in records.items():
                state = reprice_state(states[policy], current)
                if state not in shared_searches:
                    search: list[dict] = []
                    actions = generate_weekly_actions(
                        state,
                        rows,
                        rules,
                        events=events,
                        score_field="expected_points",
                        horizon_decay=config.decay,
                        alternatives_per_transfer_count=1,
                        max_total_transfers=config.maximum_transfers,
                        max_paid_transfers=config.maximum_paid_transfers,
                        terminal_free_transfer_curve=terminal_curve,
                        solver_time_limit_seconds=config.solver_seconds,
                        protect_role_sale_routes=False,
                        search_diagnostics=search,
                    )
                    if not actions or any(s["status"] == "unresolved" for s in search):
                        raise RuntimeError(
                            f"Incomplete first-action search at {season} GW{event}: {search}"
                        )
                    if not any(a.route_type == "roll" for a in actions):
                        raise RuntimeError("Missing solved roll comparator")
                    shared_searches[state] = actions, search
                actions, search = shared_searches[state]
                action = actions[0]
                diagnostic = None
                if policy == "next_deadline_recourse":
                    diagnostic = evaluate_weekly_continuation(
                        actions,
                        rows,
                        rules,
                        events=events,
                        selected_action_id=action.action_id,
                        horizon_decay=config.decay,
                        terminal_free_transfer_curve=terminal_curve,
                        maximum_roots=len(actions) + 1,
                        maximum_future_transfers=config.maximum_transfers,
                        maximum_future_paid_transfers=config.maximum_paid_transfers,
                        time_budget_seconds=config.continuation_seconds,
                        solver_time_limit_seconds=config.solver_seconds,
                    )
                    if not diagnostic["complete_root_comparison"]:
                        raise RuntimeError(
                            f"Incomplete recourse at {season} GW{event}: {diagnostic['failures']}"
                        )
                    action = next(
                        a for a in actions if a.action_id == diagnostic["shadow_preference"]
                    )
                record, next_state = _record(
                    state,
                    action,
                    None,
                    outcomes,
                    snapshot,
                    rows,
                    search,
                    diagnostic,
                )
                path.append(record)
                states[policy] = next_state
        if progress:
            progress(
                {
                    "season": season,
                    "event": event,
                    "net_points": {
                        p: sum(r["net_points"] for r in path) for p, path in records.items()
                    },
                    "last_actions": {p: path[-1]["transfers"] for p, path in records.items()},
                }
            )
    paths = {
        p: {
            "events": path,
            "net_points": sum(r["net_points"] for r in path),
            "points_cost": sum(r["points_cost"] for r in path),
            "transfers": sum(len(r["transfers"]) for r in path),
        }
        for p, path in records.items()
    }
    differences = [
        b["net_points"] - a["net_points"]
        for a, b in zip(
            records["fixed_roster"][1:], records["next_deadline_recourse"][1:], strict=True
        )
    ]
    return {
        "season": season,
        "training_seasons": training_seasons,
        "fixture_coefficients": coefficients,
        "terminal_curve": terminal_curve,
        "paths": paths,
        "net_points_delta": sum(differences),
        "event_deltas_excluding_shared_gw1": differences,
        "mean_delta_block_interval": moving_block_mean_interval(
            differences,
            block_length=min(4, len(differences)),
            samples=5000,
            seed=49019,
        ),
    }


def run_replay(output: Path, config: ReplayConfig | None = None, progress=None) -> dict:
    config = config or ReplayConfig()
    config.validate()
    if output.exists():
        raise FileExistsError("Choose a new experiment path; previous results must remain intact")
    started = time.monotonic()
    experiment_code = {
        name: sha256_file(Path(__file__).with_name(name))
        for name in (
            "weekly_continuation_replay.py",
            "weekly_continuation.py",
            "weekly_actions.py",
            "horizon_decay_replay.py",
            "market_transfer_replay.py",
            "season_state.py",
        )
    }
    inputs = _load_inputs()
    config_payload = asdict(config)
    receipt = {
        "version": "weekly_continuation_replay_v1",
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "decision_authority": False,
        "config": config_payload,
        "config_sha256": hashlib.sha256(
            json.dumps(config_payload, sort_keys=True).encode()
        ).hexdigest(),
        "sources": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in inputs["paths"].items()
        },
        "experiment_code_sha256": experiment_code,
        "limitations": [
            "Early-season ordinary transfers only; not a joint chip/whole-season test.",
            "Reuses historical folds already inspected in other research; not an untouched test.",
            "Future xP is reconstructed from origin forecasts and dated fixtures, not archived live multiweek forecasts.",
            "Flat future prices and role information; actual prices become available only at their deadline.",
            "Identical first-action bounds and optimal-solve requirement; recourse adds extra search compute.",
            "Zero terminal FT value in both arms; no import of a curve fitted on the test seasons.",
            "Deterministic screening objective/bench proxy; not the production three-world simulation selector.",
            "A positive small-sample result cannot authorize promotion; prospective, production-matched tests remain required.",
        ],
        "screen_preregistered": "Positive net-point delta in both full 10-event folds; diagnostic only.",
        "folds": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def checkpoint():
        output.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    def update(item):
        receipt["progress"] = item
        checkpoint()
        if progress:
            progress(item)

    checkpoint()  # Freeze assumptions before any path's outcomes are scored.
    try:
        for season in config.seasons:
            receipt["folds"].append(paired_season(inputs, season, config, update))
            checkpoint()
        if any(
            sha256_file(Path(__file__).with_name(name)) != digest
            for name, digest in experiment_code.items()
        ):
            raise RuntimeError(
                "Experiment implementation changed during execution; rerun frozen code"
            )
        if any(
            sha256_file(inputs["paths"][name]) != source["sha256"]
            for name, source in receipt["sources"].items()
        ):
            raise RuntimeError("Historical inputs changed during execution; rerun frozen inputs")
        receipt["status"] = "complete"
        receipt["historical_screen_passed"] = (
            config.end_event == 10
            and set(config.seasons) == {"2024-25", "2025-26"}
            and all(f["net_points_delta"] > 0 for f in receipt["folds"])
        )
    except (ValueError, RuntimeError) as exc:
        receipt.update(status="blocked_experiment", error=str(exc), historical_screen_passed=False)
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - started
        checkpoint()
    return receipt
