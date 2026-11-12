"""Isolated, bounded Wildcard timing experiment, never deployment authority.

Replans ordinary transfers at EVERY deadline. Information is revealed only at
its declared deadline; realised match outcomes never enter the planner. This is
a policy comparison conditional on forecasts, not a proof of forecast quality.
Other chips can be supplied as a precommitted calendar; their dates are not
optimised here. Keeping them unused is an explicit ablation, not a full season
chip recommendation.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace

import numpy as np

from .horizon_decay_replay import _fixture_multiplier
from .season_state import (
    ActionBundle,
    ChipStatus,
    ChipType,
    Lineup,
    MarketPlayer,
    Transfer,
    apply_action,
)
from .weekly_actions import (
    EvaluatedAction,
    EventLineup,
    _forecast_grid,
    _solve_exact_transfer_count,
    _transfers_for_selected,
    generate_weekly_actions,
)
from .weekly_simulation import evaluate_action_paths


@dataclass(frozen=True)
class InformationShock:
    event: int
    players: tuple[int, ...]
    points_multiplier: float = 1.0
    price_delta: int = 0


@dataclass(frozen=True)
class TimingConfig:
    planning_horizon: int = 5
    planning_decay: float = 0.88
    maximum_transfers: int = 2
    maximum_paid_transfers: int = 1
    solver_seconds: float = 5.0
    # Weight of a benched player's forecast in squad building (auto-sub value).
    bench_weight: float = 0.08

    def __post_init__(self):
        if (
            self.planning_horizon < 1
            or not 0 <= self.bench_weight <= 1
            or self.maximum_transfers < 0
            or self.maximum_paid_transfers < 0
            or not 0 < self.planning_decay <= 1
            or not math.isfinite(self.solver_seconds)
            or self.solver_seconds <= 0
        ):
            raise ValueError("Invalid timing search bounds")


def validate_rows(rows):
    keys = [(int(r["element"]), int(r["event_number"])) for r in rows]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Forecast keys must be nonempty and unique")
    if any(k.startswith(("target_", "realized_")) for r in rows for k in r):
        raise ValueError("Outcomes are forbidden in policy planning")
    for r in rows:
        price, mean, probability = (
            float(r["market_price"]),
            float(r["expected_points"]),
            float(r["p_play"]),
        )
        if (
            not all(math.isfinite(v) for v in (price, mean, probability))
            or price <= 0
            or price != int(price)
            or not 0 <= probability <= 1
            or (probability == 0 and mean != 0)
        ):
            raise ValueError("Invalid price, points or appearance forecast")


def extend_origin_forecast(rows, fixtures, *, end_event, coefficients):
    """Extend beyond the trained forecast horizon using frozen neutral ability.

    Historical coefficients describe the incumbent's fixture response, not
    realised future points. No later-season player rows or future odds are used.
    Current role assumptions are carried, NOT predicted injury recovery dates.
    """
    validate_rows(rows)
    last = max(int(r["event_number"]) for r in rows)
    if end_event < last:
        return [dict(r) for r in rows if int(r["event_number"]) <= end_event]
    by_player = {}
    for row in rows:
        by_player.setdefault(int(row["element"]), []).append(row)
    schedule = {}
    for f in fixtures:
        if f.get("event") is None:
            continue
        for side in ("h", "a"):
            schedule.setdefault((int(f["event"]), int(f[f"team_{side}"])), []).append(
                (float(side == "h"), float(f[f"team_{side}_difficulty"]))
            )
    result = [dict(r) for r in rows]
    for player_rows in by_player.values():
        template = max(player_rows, key=lambda r: int(r["event_number"]))
        rates = []
        for row in player_rows:
            factor = _fixture_multiplier(
                row["position"],
                float(row["fixture_count"]),
                float(row["home_fraction"]),
                row["fixture_difficulty"],
                coefficients,
            )
            if factor > 0:
                rates.append(float(row["expected_points"]) / factor)
        if not rates:
            raise ValueError("No observed fixture-normalised ability for player")
        for event in range(last + 1, end_event + 1):
            games = schedule.get((event, int(template["team_id"])), [])
            home = sum(g[0] for g in games) / len(games) if games else 0
            difficulty = sum(g[1] for g in games) / len(games) if games else 3
            factor = _fixture_multiplier(
                template["position"], len(games), home, difficulty, coefficients
            )
            mean = float(np.mean(rates)) * factor
            probability = float(template["p_play"]) if games else 0.0
            if not probability:
                mean = 0.0
            result.append(
                {
                    **template,
                    "event_number": event,
                    "fixture_count": len(games),
                    "home_fraction": home,
                    "fixture_difficulty": difficulty,
                    "expected_points": mean,
                    "robust_points": mean,
                    "p_play": probability,
                    "conditional_points_if_playing": mean / probability if probability else 0,
                    "timing_forecast_basis": "origin_fixture_extrapolation",
                }
            )
    return result


def revealed_rows(rows, *, deadline, shocks=()):
    validate_rows(rows)
    for shock in shocks:
        if (
            shock.event < min(int(r["event_number"]) for r in rows)
            or not math.isfinite(shock.points_multiplier)
            or shock.points_multiplier < 0
            or shock.price_delta != int(shock.price_delta)
        ):
            raise ValueError("Invalid information shock")
    result = []
    for raw in rows:
        if int(raw["event_number"]) < deadline:
            continue
        row = dict(raw)
        for shock in shocks:
            if shock.event <= deadline and int(row["element"]) in shock.players:
                for field in ("expected_points", "robust_points", "conditional_points_if_playing"):
                    if field in row:
                        row[field] = float(row[field]) * shock.points_multiplier
                row["market_price"] = int(row["market_price"]) + shock.price_delta
        result.append(row)
    validate_rows(result)
    return result


def reprice(state, rows):
    catalog = {int(r["element"]): r for r in rows if int(r["event_number"]) == state.event}
    holdings = []
    for h in state.squad:
        row = catalog[h.player_id]
        if (row["position"], int(row["team_id"])) != (h.position, h.team_id):
            raise ValueError("Identity changes require explicit legal-state handling")
        # Preserve authenticated selling prices unless the current price changes.
        holdings.append(
            h
            if h.current_price == int(row["market_price"])
            else h.with_current_price(int(row["market_price"]))
        )
    return replace(state, squad=tuple(holdings))


def chip_week_weights(calendar, events):
    """Solver weights for planned team chips inside a planning horizon."""
    bench = {e: 1.0 for e in events if calendar.get(e) == ChipType.BENCH_BOOST}
    captain = {e: 2.0 for e in events if calendar.get(e) == ChipType.TRIPLE_CAPTAIN}
    return {"bench_weight_by_event": bench, "captain_weight_by_event": captain}


def wildcard_action(state, rows, rules, *, events, config, required=(), sold=(), **weights):
    selected, lineups, gross = _solve_exact_transfer_count(
        state,
        rows,
        events,
        rules,
        transfer_count=None,
        score_field="expected_points",
        horizon_decay=config.planning_decay,
        bench_autosub_weight=config.bench_weight,
        required_player_ids=required,
        required_outgoing_player_ids=sold,
        solver_time_limit_seconds=config.solver_seconds,
        **weights,
    )
    _, meta = _forecast_grid(rows, events)
    action = ActionBundle(
        state.event,
        lineups[0].lineup,
        _transfers_for_selected(state, selected, meta),
        ChipType.WILDCARD,
    )
    outcome = apply_action(state, action, rules)
    identity = hashlib.sha256(str((state.event, selected)).encode()).hexdigest()[:12]
    return EvaluatedAction(
        action_id=f"TW-{identity}",
        route_type="wildcard",
        score_field="expected_points",
        selected_player_ids=selected,
        action=action,
        outcome=outcome,
        lineups=lineups,
        gross_horizon_utility=gross,
        incremental_points_cost=outcome.gameweek.incremental_points_cost,
        total_points_cost=outcome.gameweek.points_cost,
        next_free_transfers=outcome.next_manager.free_transfers if outcome.next_manager else None,
        terminal_free_transfers=None,
        terminal_transfer_value=0,
        decision_utility=gross,
    )


def ordinary_actions(state, rows, rules, *, events, config, trace=None, **constraints):
    return generate_weekly_actions(
        state,
        rows,
        rules,
        events=events,
        score_field="expected_points",
        horizon_decay=config.planning_decay,
        bench_autosub_weight=config.bench_weight,
        alternatives_per_transfer_count=1,
        max_total_transfers=config.maximum_transfers,
        max_paid_transfers=config.maximum_paid_transfers,
        terminal_free_transfer_value=0,
        protect_role_sale_routes=False,
        solver_time_limit_seconds=config.solver_seconds,
        search_diagnostics=trace,
        **constraints,
    )


def rollout(
    state,
    root,
    rows,
    rules,
    *,
    end_event,
    wildcard_event=None,
    config=None,
    shocks=(),
    chip_calendar=(),
    cache=None,
    progress: Callable | None = None,
):
    """A legal receding-horizon path with a fixed first action and WC date.

    Future outcomes are not arguments. A caller may supply an observable news
    path, but the planner can only see its prefix. Scoring is a separate step.
    """
    config = config or TimingConfig()
    validate_rows(rows)
    half_end = 19 if state.event <= 19 else 38
    events = tuple(range(state.event, end_event + 1))
    if not events or end_event > half_end:
        raise ValueError("Timing comparison must stay within the current chip half")
    if wildcard_event is not None and wildcard_event not in events:
        raise ValueError("Wildcard date outside evaluated horizon")
    if (root.action.chip == ChipType.WILDCARD) != (wildcard_event == state.event):
        raise ValueError("Root Wildcard and declared timing disagree")
    if apply_action(state, root.action, rules) != root.outcome:
        raise ValueError("Root was not built from the exact starting manager state")
    calendar = dict(chip_calendar)
    if len(calendar) != len(chip_calendar) or any(
        e not in events or c == ChipType.WILDCARD for e, c in chip_calendar
    ):
        raise ValueError("Invalid other-chip calendar")
    if wildcard_event in calendar or state.event in calendar:
        raise ValueError("Calendar collides with fixed root or Wildcard")
    if any(c == ChipType.FREE_HIT for c in calendar.values()):
        raise ValueError("Joint Free Hit timing is not supported by this experiment")
    cache = {} if cache is None else cache
    actions, ledger = [], []
    current = state
    for event in events:
        visible = revealed_rows(rows, deadline=event, shocks=shocks)
        current = reprice(current, visible)
        if event == state.event:
            chosen = root
            if apply_action(current, root.action, rules) != root.outcome:
                raise ValueError("A root-date shock requires rebuilding the root")
        else:
            last = min(end_event, event + config.planning_horizon - 1)
            if wildcard_event is not None and event < wildcard_event:
                last = min(last, wildcard_event - 1)
            horizon = tuple(range(event, last + 1))
            view = [r for r in visible if int(r["event_number"]) in horizon]
            from .weekly_continuation import _fingerprint

            key = (
                current,
                horizon,
                _fingerprint(view, "expected_points"),
                wildcard_event == event,
                tuple((e, calendar[e]) for e in horizon if e in calendar),
                config,
            )
            chosen = cache.get(key)
            if chosen is None:
                weights = chip_week_weights(calendar, horizon)
                if wildcard_event == event:
                    chosen = wildcard_action(
                        current, view, rules, events=horizon, config=config, **weights
                    )
                else:
                    trace = []
                    alternatives = ordinary_actions(
                        current, view, rules, events=horizon, config=config, trace=trace,
                        **weights,
                    )
                    if any(t["status"] == "unresolved" for t in trace) or not alternatives:
                        raise RuntimeError(f"Incomplete transfer search at GW{event}: {trace}")
                    chosen = max(alternatives, key=lambda a: (a.decision_utility, a.action_id))
                    if event in calendar:
                        # Timing is precommitted; state and score enforce one use.
                        action = replace(chosen.action, chip=calendar[event])
                        outcome = apply_action(current, action, rules)
                        chosen = replace(
                            chosen,
                            action=action,
                            outcome=outcome,
                            next_free_transfers=outcome.next_manager.free_transfers
                            if outcome.next_manager
                            else None,
                        )
                cache[key] = chosen
        if apply_action(current, chosen.action, rules) != chosen.outcome:
            raise ValueError("Continuation state mismatch")
        ledger.append(
            {
                "event": event,
                "bank_before": current.bank,
                "free_transfers_before": current.free_transfers,
                "chip": chosen.action.chip.value if chosen.action.chip else None,
                "transfers": [asdict(t) for t in chosen.action.transfers],
                "squad": list(chosen.selected_player_ids),
                "lineup": asdict(chosen.action.lineup),
                "bank_after": chosen.outcome.gameweek.bank,
                "hit": chosen.incremental_points_cost,
                "free_transfers_after": chosen.next_free_transfers,
            }
        )
        actions.append(chosen)
        current = chosen.outcome.next_manager
        if progress:
            progress({"event": event, "wildcard_event": wildcard_event, "root": root.action_id})
    identity = hashlib.sha256(str(ledger).encode()).hexdigest()[:16]
    plan = replace(
        root,
        action_id="WT-" + identity,
        route_type="timing_path",
        parent_action_id=root.action_id,
        lineups=tuple(a.lineups[0] for a in actions),
        event_squads=tuple((a.action.event, a.selected_player_ids) for a in actions),
        future_points_costs=tuple((a.action.event, a.incremental_points_cost) for a in actions[1:]),
        planned_chips=tuple((a.action.event, a.action.chip) for a in actions[1:] if a.action.chip),
        terminal_transfer_value=0,
        terminal_free_transfers=actions[-1].next_free_transfers,
    )
    return plan, ledger


def compare_frozen(plans, groups, selection_world, validation_world, *, events, reference_group):
    """Select a timing within each root group, then evaluate frozen choices.

    Independent draws quantify simulation error, not model correctness. Actual
    outcome uncertainty is reported separately. Never pick again on holdout.
    """
    if not plans or len(plans) != len(groups) or reference_group not in groups:
        raise ValueError("Plans/groups/reference mismatch")
    if len({p.action_id for p in plans}) != len(plans):
        raise ValueError("Duplicate policies must be deduplicated before comparison")
    if np.shares_memory(selection_world["points"], validation_world["points"]):
        raise ValueError("Selection and validation must be independent samples")
    scored = [
        replace(p, route_type="roll" if i == 0 else "timing_path") for i, p in enumerate(plans)
    ]
    _, selection = evaluate_action_paths(
        scored, events=events, horizon_decay=1.0, **selection_world
    )
    chosen = {
        g: max(
            (i for i, group in enumerate(groups) if g == group),
            key=lambda i: (float(selection[:, i].mean()), plans[i].action_id),
        )
        for g in dict.fromkeys(groups)
    }
    winner = max(chosen, key=lambda g: float(selection[:, chosen[g]].mean()))
    # Freeze selection before opening the second set of samples.
    _, validation = evaluate_action_paths(
        scored, events=events, horizon_decay=1.0, **validation_world
    )
    reference = validation[:, chosen[reference_group]]
    result = []
    for group, index in chosen.items():
        delta = validation[:, index] - reference
        se = float(delta.std(ddof=1) / math.sqrt(len(delta)))
        result.append(
            {
                "group": group,
                "plan_id": plans[index].action_id,
                "selected_mean": float(selection[:, index].mean()),
                "validation_mean": float(validation[:, index].mean()),
                "paired_gain": float(delta.mean()),
                "mc95": [float(delta.mean() - 1.96 * se), float(delta.mean() + 1.96 * se)],
                "outcome_delta_p10_p90": [float(x) for x in np.quantile(delta, [0.1, 0.9])],
                "probability_beat_reference": float(np.mean(delta > 0)),
                "selected_before_holdout": group == winner,
            }
        )
    return {
        "decision_authority": False,
        "selected_group": winner,
        "reference_group": reference_group,
        "groups": result,
        "score_basis": "undiscounted net points; exact autosubs/captain fallback/hits; no terminal FT/chip credit",
        "limitations": [
            "Bounded receding-horizon transfer policy, not a global optimum.",
            "Fixed WC timing policies; future news probabilities are not calibrated.",
            "Other-chip timing not jointly optimised; this cannot authorise a no-chip recommendation.",
            "Residual simulation family only; independent draws are not independent forecast models.",
            "Monte Carlo confidence intervals do not include forecast/model error.",
        ],
    }


def plan_from_ledger(state, ledger, rows, rules, *, identity, shocks=()):
    """Independently re-apply every saved transfer and chip before scoring."""
    first_outcome = None
    lineups, squads, chips, costs = [], [], [], []
    first_action = None
    for record in ledger:
        event = int(record["event"])
        if event != state.event:
            raise ValueError("Noncontiguous policy ledger")
        state = reprice(state, revealed_rows(rows, deadline=event, shocks=shocks))
        raw = record["lineup"]
        lineup = Lineup(
            tuple(raw["starters"]), tuple(raw["bench_order"]), raw["captain"], raw["vice_captain"]
        )
        chip = ChipType(record["chip"]) if record.get("chip") else None
        transfers = tuple(
            Transfer(t["outgoing_player_id"], MarketPlayer(**t["incoming"]))
            for t in record["transfers"]
        )
        action = ActionBundle(event, lineup, transfers, chip)
        outcome = apply_action(state, action, rules)
        if (
            record["bank_before"] != state.bank
            or record["free_transfers_before"] != state.free_transfers
            or record["bank_after"] != outcome.gameweek.bank
            or record["hit"] != outcome.gameweek.incremental_points_cost
            or set(record["squad"]) != {h.player_id for h in outcome.gameweek.squad}
            or record["free_transfers_after"]
            != (outcome.next_manager.free_transfers if outcome.next_manager else None)
        ):
            raise ValueError("Saved policy cash/transfer/squad ledger disagrees with state engine")
        lineups.append(EventLineup(event, lineup, "", 0))
        squads.append((event, tuple(record["squad"])))
        if first_action is None:
            first_action, first_outcome = action, outcome
        else:
            costs.append((event, outcome.gameweek.incremental_points_cost))
            if chip:
                chips.append((event, chip))
        state = outcome.next_manager
    if first_action is None:
        raise ValueError("Empty policy ledger")
    return EvaluatedAction(
        identity,
        "timing_path",
        "expected_points",
        squads[0][1],
        first_action,
        first_outcome,
        tuple(lineups),
        0,
        first_outcome.gameweek.incremental_points_cost,
        first_outcome.gameweek.points_cost,
        first_outcome.next_manager.free_transfers if first_outcome.next_manager else None,
        state.free_transfers if state else None,
        0,
        0,
        event_squads=tuple(squads),
        future_points_costs=tuple(costs),
        planned_chips=tuple(chips),
    )


def team_chip_gains(plan, world, *, events, event_scores=None):
    """Mean Bench Boost and Triple Captain gain for every chip-free week of a path."""
    from .tournament import _score_candidates
    from .weekly_simulation import _candidate_payload

    occupied = {e for e, _ in plan.planned_chips}
    if plan.action.chip:
        occupied.add(plan.action.event)
    ids = {p: i for i, p in enumerate(world["player_ids"])}
    scores = event_scores
    if scores is None:
        scores = _score_candidates(
            [_candidate_payload(plan)],
            world["player_ids"],
            events,
            world["points"],
            world["played"],
            world["player_meta"],
        )[:, 0, :]
    squads, lineups = dict(plan.event_squads), {l.event: l.lineup for l in plan.lineups}
    gains = {}
    for offset, event in enumerate(events):
        if event in occupied:
            continue
        lineup = lineups[event]
        c, v = ids[lineup.captain], ids[lineup.vice_captain]
        points, played = world["points"][:, offset], world["played"][:, offset]
        cap = np.where(played[:, c], points[:, c], np.where(played[:, v], points[:, v], 0))
        squad = [ids[p] for p in squads[event]]
        gains[event] = {
            ChipType.TRIPLE_CAPTAIN: float(cap.mean()),
            ChipType.BENCH_BOOST: float(
                (
                    np.sum(points[:, squad] * played[:, squad], axis=1) + cap - scores[:, offset]
                ).mean()
            ),
        }
    return gains


def select_team_chip_calendar(plan, world, *, events, state, event_scores=None):
    """Choose BB/TC dates on selection draws, conditional on this transfer path.

    Ordinary FT progression is unchanged by BB/TC. The resulting calendar must
    still be replayed through plan_from_ledger before it is accepted. This is
    NOT a joint optimisation of the transfers made to prepare those chips.
    """
    half = 1 if state.event <= 19 else 2
    available = {c.chip for c in state.chips if c.half == half and c.status == ChipStatus.AVAILABLE}
    gains = team_chip_gains(plan, world, events=events, event_scores=event_scores)
    free = list(gains)
    bb_dates = [None, *free] if ChipType.BENCH_BOOST in available else [None]
    tc_dates = [None, *free] if ChipType.TRIPLE_CAPTAIN in available else [None]
    pairs = [(bb, tc) for bb in bb_dates for tc in tc_dates if bb is None or bb != tc]
    bb, tc = max(
        pairs,
        key=lambda p: sum(
            gains[e][chip]
            for e, chip in zip(p, (ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN))
            if e is not None
        ),
    )
    return {
        e: chip.value
        for e, chip in ((bb, ChipType.BENCH_BOOST), (tc, ChipType.TRIPLE_CAPTAIN))
        if e is not None
    }
