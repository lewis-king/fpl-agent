"""Full-half Wildcard timing for live weekly decisions.

Every chip in a half must be used before that half expires (GW19, GW38).
This module runs the adaptive Wildcard planner from ``wildcard_timing`` on the
currently published weekly decision: every ordinary first move (and the exact
published route) is rolled forward with weekly replanning and a Wildcard placed
in each remaining week, alongside a Wildcard played now. All branches share
the same simulated outcomes, chosen on one draw set and checked on another.

The resulting receipt is bound to the decision event, forecast and exact
manager-state contract. ``chip_strategy`` grants Wildcard authority for the
current week only when this receipt says now is the best remaining week and the
holdout margin over the best later-Wildcard branch is clear. Otherwise the
receipt still supplies the dated plan ("Wildcard in GW12") shown to the user.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .season_state import (
    ActionBundle,
    ChipType,
    Lineup,
    MarketPlayer,
    Transfer,
    apply_action,
)
from .weekly_actions import EventLineup

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DECISION_PATH = ROOT / "data/decisions/2026-27-weekly-current.json"
DEFAULT_RECEIPT_PATH = ROOT / "data/decisions/chip-timing-current.json"
VERSION = "full_half_chip_calendar_v3"
SELECTION_SEED = 2026110601
VALIDATION_SEED = 2026110602


MAX_RECEIPT_AGE_HOURS = 12.0


def squad_fingerprint(state) -> str:
    """Identity of the decision-relevant manager state, stable across re-syncs."""
    payload = {
        "event": int(state.event),
        "squad": sorted((int(h.player_id), int(h.selling_price)) for h in state.squad),
        "bank": int(state.bank),
        "free_transfers": int(state.free_transfers),
        "chips": sorted(
            (s.chip.value, int(s.half), s.status.value) for s in state.chips
        ),
    }
    return _sha(json.dumps(payload, sort_keys=True).encode())


def half_end(event: int) -> int:
    return 19 if event <= 19 else 38


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _published_action(decision, state, roots, rules):
    value = decision["selected_action"]

    def lineup(v):
        return Lineup(
            tuple(v["starters"]), tuple(v["bench_order"]), int(v["captain"]), int(v["vice_captain"])
        )

    a = value["action"]
    bundle = ActionBundle(
        int(decision["decision_event"]),
        lineup(a["lineup"]),
        tuple(
            Transfer(t["outgoing_player_id"], MarketPlayer(**t["incoming"])) for t in a["transfers"]
        ),
        ChipType(a["chip"]) if a["chip"] else None,
    )
    outcome = apply_action(state, bundle, rules)
    return replace(
        roots[0],
        action_id=value["action_id"],
        action=bundle,
        outcome=outcome,
        selected_player_ids=tuple(sorted(h.player_id for h in outcome.gameweek.squad)),
        lineups=tuple(
            EventLineup(int(l["event"]), lineup(l["lineup"]), l["formation"], l["projected_points"])
            for l in value["lineups"]
        ),
        incremental_points_cost=value["incremental_points_cost"],
        total_points_cost=value["total_points_cost"],
    )


# The planner sees no news between deadlines, so it gives waiting zero value.
# Waiting a week means rebuilding with one more week of injury and role news;
# a gap that spans an international break adds a second week of news. These
# margins are an explicit, unvalidated prior: the play-now edge must exceed
# them before a Wildcard fires early. They do not apply in the final week.
WAIT_MARGIN_POINTS = 2.0
LONG_GAP_EXTRA_POINTS = 2.0
LONG_GAP_DAYS = 10.0


def wait_margin(next_deadline_gap_days: float | None) -> float:
    if next_deadline_gap_days is not None and next_deadline_gap_days >= LONG_GAP_DAYS:
        return WAIT_MARGIN_POINTS + LONG_GAP_EXTRA_POINTS
    return WAIT_MARGIN_POINTS


def next_deadline_gap_days(fixtures: list[Mapping[str, Any]], event: int) -> float | None:
    def first_kickoff(e):
        times = [
            datetime.fromisoformat(str(f["kickoff_time"]))
            for f in fixtures
            if f.get("event") is not None and int(f["event"]) == e and f.get("kickoff_time")
        ]
        return min(times) if times else None

    now, nxt = first_kickoff(event), first_kickoff(event + 1)
    if now is None or nxt is None:
        return None
    return (nxt - now).total_seconds() / 86_400


def timing_verdict(
    groups: list[Mapping[str, Any]],
    *,
    event: int,
    next_gap_days: float | None = None,
) -> dict[str, Any]:
    """Decide whether the Wildcard belongs in the current week.

    ``groups`` are frozen-selection rows from ``compare_frozen``: one per root,
    each carrying the Wildcard week its own selection draws preferred. A branch
    that never Wildcards is impossible before expiry, so the planner only
    offers dated Wildcards; ``None`` rows are ignored when present.
    """
    required_margin = wait_margin(next_gap_days)
    dated = [g for g in groups if g.get("wildcard_event") is not None]
    if not dated:
        raise ValueError("Timing receipt has no dated Wildcard branches")
    now = [g for g in dated if int(g["wildcard_event"]) == event]
    later = [g for g in dated if int(g["wildcard_event"]) > event]
    best = max(dated, key=lambda g: float(g["validation_mean"]))
    best_now = max(now, key=lambda g: float(g["validation_mean"])) if now else None
    best_later = max(later, key=lambda g: float(g["validation_mean"])) if later else None
    if best_now is None:
        margin = None
    elif best_later is None:
        margin = math.inf
    else:
        margin = float(best_now["validation_mean"]) - float(best_later["validation_mean"])
    # Both rows are paired against the same reference on the same holdout
    # draws, so non-overlap of their reference-relative intervals is a
    # conservative test that the gap is not simulation noise.
    separated = bool(
        best_now is not None
        and (
            best_later is None
            or float(best_now["mc95"][0]) > float(best_later["mc95"][1])
        )
    )
    play_now = bool(
        best_now is not None and margin is not None and margin > required_margin and separated
    )
    return {
        "best_wildcard_event": event if play_now else int(
            (best_later or best)["wildcard_event"]
        ),
        "play_now": play_now,
        "now_minus_best_later": margin,
        "required_waiting_margin": required_margin,
        "next_deadline_gap_days": next_gap_days,
        "holdout_separated": separated,
        "best_now_group": best_now["group"] if best_now else None,
        "best_later_group": best_later["group"] if best_later else None,
        "best_later_event": int(best_later["wildcard_event"]) if best_later else None,
        "rule": (
            "Wildcard now only when the best play-now branch beats the best later-Wildcard "
            f"branch on holdout draws by more than {required_margin:.1f} points (the value "
            "of waiting for news) with non-overlapping paired 95% intervals."
        ),
    }


def run_live_wildcard_timing(
    *,
    decision_path: Path = DEFAULT_DECISION_PATH,
    output_path: Path = DEFAULT_RECEIPT_PATH,
    samples: int = 10_000,
    solver_seconds: float = 8.0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    from .horizon_decay_replay import _fixture_response_coefficients, _load_inputs
    from .rules import load_rules
    from .sequential_policy_replay import deadline_world, origin_simulation_rows
    from .tournament import calibrate_residuals
    from .weekly_decision import load_weekly_manager_state
    from .wildcard_timing import (
        TimingConfig,
        compare_frozen,
        extend_origin_forecast,
        ordinary_actions,
        revealed_rows,
        rollout,
        wildcard_action,
    )

    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    event = int(decision["decision_event"])
    end = half_end(event)
    sources = decision["source_artifacts"]
    forecast_path = Path(sources["forecast"])
    fixtures_path = Path(sources["schedule_fixtures"])
    manager_path = Path(sources["manager_state_contract"])
    hashes = {
        "forecast": _sha(forecast_path.read_bytes()),
        "schedule_fixtures": _sha(fixtures_path.read_bytes()),
        "manager_state_contract": _sha(manager_path.read_bytes()),
    }
    for key, digest in hashes.items():
        if digest != sources[key + "_sha256"]:
            raise ValueError(f"Published source changed since the decision: {key}")
    rules = load_rules()
    state, _ = load_weekly_manager_state(
        manager_path, forecast_path=forecast_path, event=event, rules=rules
    )
    base = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "decision_event": event,
        "half_expiry_event": end,
        "source_hashes": hashes,
        "squad_fingerprint": squad_fingerprint(state),
        "decision_selected_action_id": decision["selected_action_id"],
    }
    if end - event < 1:
        receipt = {
            **base,
            "status": "final_week",
            "verdict": {"best_wildcard_event": event, "play_now": True,
                        "rule": "Final week of the half: an unused Wildcard must be played now."},
        }
        _save(output_path, receipt)
        return receipt
    rows = pq.read_table(forecast_path).to_pylist()
    fixtures = pq.read_table(fixtures_path).to_pylist()
    half = 1 if event <= 19 else 2
    held = {s.chip for s in state.chips if s.half == half and s.status.value == "available"}
    if not held:
        receipt = {**base, "status": "no_chips_held", "verdict": None}
        _save(output_path, receipt)
        return receipt
    wildcard_held = ChipType.WILDCARD in held
    cfg = TimingConfig(solver_seconds=solver_seconds)
    inputs = _load_inputs()
    coefficients = _fixture_response_coefficients(inputs["forecasts"], inputs["features"])
    origin_last = max(int(r["event_number"]) for r in rows)
    rows = extend_origin_forecast(rows, fixtures, end_event=end, coefficients=coefficients)
    events = tuple(range(event, end + 1))
    root_rows = revealed_rows(rows, deadline=event)
    horizon = tuple(range(event, min(event + cfg.planning_horizon, end + 1)))
    trace: list[dict[str, Any]] = []
    roots = ordinary_actions(state, root_rows, rules, events=horizon, config=cfg, trace=trace)
    if any(t["status"] == "unresolved" for t in trace):
        raise RuntimeError(f"Root search incomplete: {trace}")
    published = _published_action(decision, state, roots, rules)
    if wildcard_held:
        named = {
            ("roll" if not r.action.transfers else f"ordinary_{len(r.action.transfers)}"): r
            for r in roots
        }
        named["published"] = published
        named["wildcard_now"] = wildcard_action(
            state, root_rows, rules, events=horizon, config=cfg
        )
        # A Wildcard squad is held for many weeks, so also build one on a longer,
        # flatter view. Duplicates are dropped; simulation picks between them.
        long_cfg = TimingConfig(
            solver_seconds=solver_seconds,
            planning_horizon=min(WILDCARD_LONG_HORIZON, len(events)),
            planning_decay=WILDCARD_LONG_DECAY,
        )
        long_horizon = events[: long_cfg.planning_horizon]
        long_build = wildcard_action(
            state, [r for r in root_rows if int(r["event_number"]) in long_horizon],
            rules, events=long_horizon, config=long_cfg,
        )
        if long_build.selected_player_ids != named["wildcard_now"].selected_player_ids:
            named["wildcard_now_long_view"] = long_build
    else:
        named = {"published": published}
    cache: dict[Any, Any] = {}
    plans, groups, paths = [], [], []
    for group, root in named.items():
        if not wildcard_held:
            dates = [None]
        elif root.action.chip == ChipType.WILDCARD:
            dates = [event]
        else:
            dates = list(events[1:])
        for date in dates:
            if progress:
                progress(
                    f"Chip timing: {group} with Wildcard in GW{date}" if date
                    else f"Chip timing: {group}"
                )
            plan, ledger = rollout(
                state, root, rows, rules, end_event=end, wildcard_event=date,
                config=cfg, cache=cache,
            )
            plan = replace(plan, action_id=plan.action_id + "-" + group)
            plans.append(plan)
            groups.append(group)
            paths.append({"plan_id": plan.action_id, "group": group, "root": root,
                          "plan": plan, "wildcard_event": date, "ledger": ledger})
    if progress:
        progress(f"Chip timing: simulating {len(plans)} season paths")
    calibration = calibrate_residuals()
    simulation_rows = []
    for e in events:
        simulation_rows.extend(
            r for r in revealed_rows(rows, deadline=e) if int(r["event_number"]) == e
        )
    sim = origin_simulation_rows(simulation_rows)
    selection = deadline_world(sim, fixtures, calibration, events=events,
                               samples=samples, seed=SELECTION_SEED)
    validation = deadline_world(sim, fixtures, calibration, events=events,
                                samples=samples * 2, seed=VALIDATION_SEED)
    path_by_id = {p["plan_id"]: p for p in paths}
    next_gap = next_deadline_gap_days(fixtures, event)
    verdict = None
    group_rows: list[dict[str, Any]] = []
    limitations: list[str] = []
    if wildcard_held:
        result = compare_frozen(plans, groups, selection, validation,
                                events=events, reference_group="published")
        current = {int(r["element"]): r for r in root_rows if int(r["event_number"]) == event}
        for row in result["groups"]:
            path = path_by_id[row["plan_id"]]
            row["wildcard_event"] = path["wildcard_event"]
            row["root_transfers"] = path["ledger"][0]["transfers"]
            row["root_squad_names"] = [
                current[p]["player_name"] for p in path["ledger"][0]["squad"]
            ]
        group_rows = result["groups"]
        limitations = list(result["limitations"])
        verdict = timing_verdict(group_rows, event=event, next_gap_days=next_gap)
        chosen_group = verdict["best_now_group"] if verdict["play_now"] else (
            verdict["best_later_group"] or verdict["best_now_group"]
        )
        base_path = path_by_id[
            next(r["plan_id"] for r in group_rows if r["group"] == chosen_group)
        ]
        best_now = path_by_id[
            next(r["plan_id"] for r in group_rows if r["group"] == verdict["best_now_group"])
        ]["root"]
        wildcard_squad = {
            "group": verdict["best_now_group"],
            "player_ids": sorted(best_now.selected_player_ids),
            "player_names": [
                current[p]["player_name"] for p in sorted(best_now.selected_player_ids)
            ],
        } if best_now.action.chip == ChipType.WILDCARD else None
    else:
        base_path = paths[0]
        wildcard_squad = None
    calendar = _chip_calendar_stage(
        state=state, held=held, base_path=base_path, rows=rows, rules=rules, end=end,
        cfg=cfg, cache=cache, selection=selection, validation=validation, events=events,
        next_gap_days=next_gap, progress=progress,
    )
    receipt = {
        **base,
        "status": "completed",
        "direct_forecast_end": origin_last,
        "fixture_extrapolation_events": list(range(origin_last + 1, end + 1)),
        "samples_selection": samples,
        "samples_validation": samples * 2,
        "groups": group_rows,
        "verdict": verdict,
        "wildcard_squad": wildcard_squad,
        "chip_calendar": calendar,
        "limitations": limitations,
    }
    _save(output_path, receipt)
    return receipt


# One-week chips lose less by waiting than a Wildcard does, but a later week
# still arrives with a week more injury and role news. Explicit prior, as above.
WILDCARD_LONG_HORIZON = 8
WILDCARD_LONG_DECAY = 0.95
TEAM_CHIP_WAIT_MARGIN_POINTS = 1.0
PREPARED_BENCH_BOOST_CANDIDATES = 3
_CALENDAR_CHIPS = (ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN, ChipType.FREE_HIT)


def team_chip_wait_margin(next_deadline_gap_days: float | None) -> float:
    return TEAM_CHIP_WAIT_MARGIN_POINTS * (wait_margin(next_deadline_gap_days) / WAIT_MARGIN_POINTS)


def optimise_chip_calendar(
    gains: Mapping[str, Mapping[int, float]],
    *,
    fixed: Mapping[str, int] | None = None,
    barred: Mapping[str, int] | None = None,
) -> tuple[float, dict[str, int]] | None:
    """Best one-chip-per-week assignment of every chip in ``gains``.

    ``fixed`` pins a chip to a week and ``barred`` forbids one week for a chip.
    Returns None when the chips cannot all be placed.
    """
    fixed, barred = dict(fixed or {}), dict(barred or {})
    chips = sorted(gains)
    options = []
    for chip in chips:
        weeks = [w for w in sorted(gains[chip]) if barred.get(chip) != w]
        if chip in fixed:
            weeks = [w for w in weeks if w == fixed[chip]]
        options.append(weeks)
    best: tuple[float, dict[str, int]] | None = None
    for combo in itertools.product(*options):
        if len(set(combo)) != len(combo):
            continue
        total = sum(float(gains[c][w]) for c, w in zip(chips, combo, strict=True))
        if best is None or total > best[0]:
            best = (total, dict(zip(chips, combo, strict=True)))
    return best


def calendar_verdict(
    gains: Mapping[str, Mapping[int, float]],
    *,
    event: int,
    next_gap_days: float | None = None,
) -> dict[str, Any]:
    """Dated plan for every one-week chip, and whether one belongs in this week.

    A chip is played now only when the best calendar with it now beats the best
    calendar that keeps it for later by more than the waiting margin. When no
    later week exists the chip must be played now.
    """
    gains = {chip: dict(weeks) for chip, weeks in gains.items() if weeks}
    best = optimise_chip_calendar(gains)
    if best is None:
        return {"allocations": [], "total_expected_gain": 0.0, "now": {},
                "play_now_chip": None, "feasible": not gains}
    margin = team_chip_wait_margin(next_gap_days)
    now: dict[str, dict[str, Any]] = {}
    for chip in sorted(gains):
        if event not in gains[chip]:
            continue
        with_now = optimise_chip_calendar(gains, fixed={chip: event})
        without = optimise_chip_calendar(gains, barred={chip: event})
        if with_now is None:
            continue
        edge = math.inf if without is None else with_now[0] - without[0]
        now[chip] = {
            "gain_now": float(gains[chip][event]),
            "edge_over_waiting": edge,
            "required_waiting_margin": margin,
            "best_later_event": None if without is None else without[1][chip],
            "play_now": bool(edge > margin),
        }
    playable = [c for c, row in now.items() if row["play_now"]]
    play = max(playable, key=lambda c: now[c]["edge_over_waiting"]) if playable else None
    plan = best[1]
    if play is not None:
        plan = optimise_chip_calendar(gains, fixed={play: event})[1]
    else:
        # Nothing clears the margin, so the plan shown keeps every chip for later
        # where a later week exists.
        later = optimise_chip_calendar(
            {c: {w: g for w, g in weeks.items() if w != event} or weeks
             for c, weeks in gains.items()}
        )
        plan = later[1] if later is not None else plan
    return {
        "allocations": [
            {"chip": chip, "event": week, "expected_gain": float(gains[chip][week])}
            for chip, week in sorted(plan.items(), key=lambda item: item[1])
        ],
        "total_expected_gain": float(sum(gains[c][w] for c, w in plan.items())),
        "now": now,
        "play_now_chip": play,
        "feasible": True,
        "rule": (
            "A one-week chip is played now only when the best calendar with it now beats "
            f"the best calendar that holds it by more than {margin:.1f} points."
        ),
    }


def _free_hit_gains(state, ledger, rows, rules, cfg) -> dict[int, float]:
    """Forecast gain of a one-week unrestricted squad over the path's own XI."""
    from .weekly_actions import _solve_exact_transfer_count
    from .wildcard_timing import reprice, revealed_rows

    gains: dict[int, float] = {}
    current = state
    for record in ledger:
        event = int(record["event"])
        visible = revealed_rows(rows, deadline=event)
        current = reprice(current, visible)
        week = [r for r in visible if int(r["event_number"]) == event]
        points = {int(r["element"]): float(r["expected_points"]) for r in week}
        raw = record["lineup"]
        if not record.get("chip"):
            _, lineups, _ = _solve_exact_transfer_count(
                current, week, (event,), rules, transfer_count=None,
                score_field="expected_points", horizon_decay=1.0, bench_autosub_weight=0.08,
                solver_time_limit_seconds=cfg.solver_seconds,
            )
            best = lineups[0].lineup
            gains[event] = (
                sum(points[p] for p in best.starters) + points[best.captain]
                - sum(points[p] for p in raw["starters"]) - points[raw["captain"]]
            )
        action = ActionBundle(
            event,
            Lineup(tuple(raw["starters"]), tuple(raw["bench_order"]),
                   raw["captain"], raw["vice_captain"]),
            tuple(Transfer(t["outgoing_player_id"], MarketPlayer(**t["incoming"]))
                  for t in record["transfers"]),
            ChipType(record["chip"]) if record.get("chip") else None,
        )
        current = apply_action(current, action, rules).next_manager
        if current is None:
            break
    return gains


def _chip_calendar_stage(
    *, state, held, base_path, rows, rules, end, cfg, cache, selection, validation,
    events, next_gap_days, progress,
) -> dict[str, Any] | None:
    """Date the Bench Boost, Triple Captain and Free Hit on the chosen season path."""
    from .wildcard_timing import compare_frozen, rollout, team_chip_gains

    chips = [c for c in _CALENDAR_CHIPS if c in held]
    if not chips:
        return None
    event = state.event
    bb, tc, fh = ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN, ChipType.FREE_HIT
    base_plan, ledger = base_path["plan"], base_path["ledger"]
    conditional = team_chip_gains(base_plan, selection, events=events)
    gains: dict[str, dict[int, float]] = {c.value: {} for c in chips}
    for week, row in conditional.items():
        for chip in (bb, tc):
            if chip in held:
                gains[chip.value][week] = row[chip]
    if fh in held:
        if progress:
            progress("Chip timing: pricing a Free Hit in each week")
        free_weeks = set(conditional)
        gains[fh.value] = {
            week: value
            for week, value in _free_hit_gains(state, ledger, rows, rules, cfg).items()
            if week in free_weeks
        }
    prepared: list[dict[str, Any]] = []
    if bb in held:
        later = sorted(
            (w for w in gains[bb.value] if w > event),
            key=lambda w: -gains[bb.value][w],
        )
        candidates = later[:PREPARED_BENCH_BOOST_CANDIDATES]
        after_wildcard = (base_path["wildcard_event"] or event) + 1
        if after_wildcard in later and after_wildcard not in candidates:
            candidates.append(after_wildcard)
        plans, names, meta = [base_plan], ["base"], {}
        for week in candidates:
            captain_weeks = [
                w for w in gains.get(tc.value, {}) if w > event and w != week
            ]
            captain_week = (
                max(captain_weeks, key=lambda w: gains[tc.value][w]) if captain_weeks else None
            )
            calendar = tuple(
                item for item in ((week, bb), (captain_week, tc)) if item[0] is not None
            )
            if progress:
                progress(f"Chip timing: squad built for a Bench Boost in GW{week}")
            plan, _ = rollout(
                state, base_path["root"], rows, rules, end_event=end,
                wildcard_event=base_path["wildcard_event"], config=cfg, cache=cache,
                chip_calendar=calendar,
            )
            name = f"bench_boost_{week}"
            plans.append(replace(plan, action_id=plan.action_id + "-" + name))
            names.append(name)
            meta[name] = (week, captain_week)
        if len(plans) > 1:
            compared = compare_frozen(plans, names, selection, validation,
                                      events=events, reference_group="base")
            for row in compared["groups"]:
                if row["group"] == "base":
                    continue
                week, captain_week = meta[row["group"]]
                captain_gain = gains[tc.value][captain_week] if captain_week else 0.0
                value = float(row["paired_gain"]) - captain_gain
                prepared.append({
                    "bench_boost_event": week,
                    "triple_captain_event": captain_week,
                    "joint_gain": float(row["paired_gain"]),
                    "mc95": row["mc95"],
                    "bench_boost_gain_prepared": value,
                    "bench_boost_gain_unprepared": gains[bb.value][week],
                })
                gains[bb.value][week] = max(gains[bb.value][week], value)
    verdict = calendar_verdict(gains, event=event, next_gap_days=next_gap_days)
    return {
        "base_group": base_path["group"],
        "wildcard_event": base_path["wildcard_event"],
        "gains_by_event": [
            {"event": week, **{chip: gains[chip].get(week) for chip in sorted(gains)}}
            for week in events
        ],
        "prepared_bench_boost": prepared,
        **verdict,
        "limitations": [
            "Weeks beyond the direct forecast use fixture-adjusted current form and roles.",
            "Free Hit gains are forecast means, not simulated outcomes.",
            "Bench Boost preparation is tested for the strongest candidate weeks only.",
            (
                "Short-rest weeks carry no extra discount: since 2021-22 regular starters reached "
                "60 minutes in 83% of matches on three days' rest against 85% on a full week."
            ),
        ],
    }


def _save(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_live_timing(
    *,
    event: int,
    fingerprint: str,
    path: Path = DEFAULT_RECEIPT_PATH,
    now: datetime | None = None,
    max_age_hours: float = MAX_RECEIPT_AGE_HOURS,
) -> dict[str, Any] | None:
    """Return a receipt only if it is recent and built for this event and squad."""
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(receipt["created_at"]))
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None
    age_hours = ((now or datetime.now(UTC)) - created).total_seconds() / 3600
    if (
        receipt.get("version") != VERSION
        or int(receipt.get("decision_event", -1)) != event
        or receipt.get("squad_fingerprint") != fingerprint
        or receipt.get("status") not in {"completed", "final_week"}
        or not 0 <= age_hours <= max_age_hours
    ):
        return None
    return receipt


def timing_refresh_needed(
    decision_path: Path = DEFAULT_DECISION_PATH,
    *,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
) -> bool:
    """True when a chip is still held this half and no fresh receipt fits the squad."""
    from .rules import load_rules
    from .weekly_decision import load_weekly_manager_state

    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    event = int(decision["decision_event"])
    sources = decision["source_artifacts"]
    state, _ = load_weekly_manager_state(
        Path(sources["manager_state_contract"]),
        forecast_path=Path(sources["forecast"]),
        event=event,
        rules=load_rules(),
    )
    half = 1 if event <= 19 else 2
    if not any(s.half == half and s.status.value == "available" for s in state.chips):
        return False
    return load_live_timing(
        event=event, fingerprint=squad_fingerprint(state), path=receipt_path
    ) is None
