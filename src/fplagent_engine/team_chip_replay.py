from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fplagent_data.http import sha256_file

from .chip_schedule_history import OPPORTUNITIES as SCHEDULE_OPPORTUNITIES
from .market_transfer_replay import (
    _event_record,
    _initial_state,
    _score_gameweek,
    _with_missing_holdings,
    moving_block_mean_interval,
    refresh_holding_prices,
)
from .models import BACKTEST_FORECAST
from .paths import MODEL_DATA, REPORTS
from .rules import SquadRules, load_rules
from .season_state import ActionBundle, ChipType, Lineup, apply_action
from .squad_chip_replay import _load_rows, _load_schedule
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_actions import EvaluatedAction, generate_weekly_actions

OUTPUT_ROOT = MODEL_DATA / "team_chip_replay_v1"
RESULTS = OUTPUT_ROOT / "results.json"
REPORT = REPORTS / "team-chip-retention-replay.md"
SELECTION_SEASON = "2023-24"
TEST_SEASON = "2024-25"


def _forecast_uplifts(
    selected: tuple[int, ...],
    lineup: Lineup,
    by_id: dict[int, dict[str, Any]],
) -> dict[str, float]:
    triple = float(by_id[lineup.captain]["expected_points"])
    bench = 0.92 * sum(
        float(by_id[element]["expected_points"]) for element in lineup.bench_order
    )
    if set(selected) != {*lineup.starters, *lineup.bench_order}:
        raise ValueError("team-chip opportunity lineup does not partition its squad")
    return {ChipType.TRIPLE_CAPTAIN.value: triple, ChipType.BENCH_BOOST.value: bench}


def _actual_uplifts(
    selected: tuple[int, ...],
    lineup: Lineup,
    rows: list[dict[str, Any]],
    ordinary_gross: int,
) -> dict[str, int]:
    by_id = {int(row["element"]): row for row in rows}
    captain = by_id[lineup.captain]
    vice = by_id[lineup.vice_captain]
    captain_copy = (
        int(captain["target_points"])
        if float(captain["target_minutes"]) > 0
        else int(vice["target_points"])
        if float(vice["target_minutes"]) > 0
        else 0
    )
    all_squad = sum(
        int(by_id[element]["target_points"])
        for element in selected
        if float(by_id[element]["target_minutes"]) > 0
    )
    bench_boost_total = all_squad + captain_copy
    return {
        ChipType.TRIPLE_CAPTAIN.value: captain_copy,
        ChipType.BENCH_BOOST.value: bench_boost_total - ordinary_gross,
    }


def _opportunity(
    *,
    event: int,
    selected: tuple[int, ...],
    lineup: Lineup,
    rows: list[dict[str, Any]],
    gross: int,
    points_cost: int,
    schedule: dict[str, Any] | None,
) -> dict[str, Any]:
    by_id = {int(row["element"]): row for row in rows}
    return {
        "event": event,
        "base_gross_points": gross,
        "base_points_cost": points_cost,
        "base_net_points": gross - points_cost,
        "schedule_known": schedule is not None,
        "schedule_confirmed": bool(schedule and schedule["schedule_confirmed"]),
        "blank_teams": int(schedule["blank_team_count"]) if schedule else None,
        "double_teams": int(schedule["double_team_count"]) if schedule else None,
        "forecast_uplifts": _forecast_uplifts(selected, lineup, by_id),
        "actual_uplifts": _actual_uplifts(selected, lineup, rows, gross),
    }


def build_team_chip_opportunity_path(
    *,
    season: str,
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
    schedule_rows: dict[tuple[str, int], dict[str, Any]],
    rules: SquadRules,
    terminal_curve: dict[int, float],
) -> dict[str, Any]:
    first_rows = grouped[(season, 1)]
    state, initial_solution = _initial_state(season=season, rows=first_rows, rules=rules)
    selected = tuple(int(element) for element in initial_solution["selected"])
    first_lineup_row = initial_solution["lineups"][1]
    first_lineup = Lineup(
        starters=tuple(int(element) for element in first_lineup_row["starters"]),
        bench_order=tuple(int(element) for element in first_lineup_row["bench_order"]),
        captain=int(first_lineup_row["captain"]),
        vice_captain=int(first_lineup_row["vice_captain"]),
    )
    gross = _score_gameweek(None, state, initial_solution, first_rows)
    opportunities = [
        _opportunity(
            event=1,
            selected=selected,
            lineup=first_lineup,
            rows=first_rows,
            gross=gross,
            points_cost=0,
            schedule=schedule_rows.get((season, 1)),
        )
    ]
    events = [
        _event_record(
            event=1,
            gross_points=gross,
            action=None,
            state=state,
            solution=initial_solution,
        )
    ]
    initial_outcome = apply_action(state, ActionBundle(1, state.lineup), rules)
    if initial_outcome.next_manager is None:
        raise RuntimeError("GW1 unexpectedly ended team-chip replay")
    state = initial_outcome.next_manager
    for event in range(2, 39):
        rows = grouped[(season, event)]
        state = refresh_holding_prices(state, rows)
        rows = _with_missing_holdings(state, rows)
        ordinary = generate_weekly_actions(
            state,
            rows,
            rules,
            events=(event,),
            score_field="expected_points",
            alternatives_per_transfer_count=1,
            max_total_transfers=3,
            max_paid_transfers=1,
            terminal_free_transfer_curve=terminal_curve,
        )
        action: EvaluatedAction = ordinary[0]
        gross = _score_gameweek(action, state, None, rows)
        opportunities.append(
            _opportunity(
                event=event,
                selected=action.selected_player_ids,
                lineup=action.action.lineup,
                rows=rows,
                gross=gross,
                points_cost=action.incremental_points_cost,
                schedule=schedule_rows.get((season, event)),
            )
        )
        events.append(
            _event_record(
                event=event,
                gross_points=gross,
                action=action,
                state=state,
            )
        )
        if event < 38:
            if action.outcome.next_manager is None:
                raise RuntimeError(f"Missing manager state after {season} GW{event}")
            state = action.outcome.next_manager
    return {"season": season, "events": events, "opportunities": opportunities}


def score_team_chip_policy(
    path: dict[str, Any],
    *,
    bench_boost_threshold: float,
    triple_captain_threshold: float,
) -> dict[str, Any]:
    thresholds = {
        ChipType.BENCH_BOOST.value: bench_boost_threshold,
        ChipType.TRIPLE_CAPTAIN.value: triple_captain_threshold,
    }
    used: set[tuple[int, str]] = set()
    chip_events = []
    event_rows = []
    for opportunity in path["opportunities"]:
        event = int(opportunity["event"])
        half = 1 if event <= 19 else 2
        candidates = []
        if opportunity["schedule_confirmed"]:
            for chip, threshold in thresholds.items():
                if (half, chip) in used:
                    continue
                forecast = float(opportunity["forecast_uplifts"][chip])
                if forecast >= threshold:
                    candidates.append((forecast - threshold, forecast, chip))
        selected_chip = max(candidates)[2] if candidates else None
        uplift = (
            int(opportunity["actual_uplifts"][selected_chip]) if selected_chip else 0
        )
        if selected_chip:
            used.add((half, selected_chip))
            chip_events.append(
                {
                    "event": event,
                    "half": half,
                    "chip": selected_chip,
                    "forecast_uplift": opportunity["forecast_uplifts"][selected_chip],
                    "actual_uplift": uplift,
                }
            )
        event_rows.append(
            {
                "event": event,
                "base_net_points": int(opportunity["base_net_points"]),
                "chip": selected_chip,
                "chip_uplift": uplift,
                "net_points": int(opportunity["base_net_points"]) + uplift,
            }
        )
    return {
        "season": path["season"],
        "bench_boost_threshold": bench_boost_threshold,
        "triple_captain_threshold": triple_captain_threshold,
        "base_net_points": sum(row["base_net_points"] for row in event_rows),
        "net_points": sum(row["net_points"] for row in event_rows),
        "chip_uplift": sum(row["chip_uplift"] for row in event_rows),
        "chip_events": chip_events,
        "events": event_rows,
    }


def score_team_chip_forecast_oracle(path: dict[str, Any]) -> dict[str, Any]:
    """Upper-bound retention comparator using the best later forecast in each half."""
    selected: dict[int, str] = {}
    for half, start, stop in ((1, 1, 19), (2, 20, 38)):
        opportunities = [
            row
            for row in path["opportunities"]
            if start <= int(row["event"]) <= stop and row["schedule_confirmed"]
        ]
        choices: list[tuple[float, int | None, int | None]] = []
        bb_events = [None, *(int(row["event"]) for row in opportunities)]
        tc_events = [None, *(int(row["event"]) for row in opportunities)]
        by_event = {int(row["event"]): row for row in opportunities}
        for bb_event in bb_events:
            for tc_event in tc_events:
                if bb_event is not None and bb_event == tc_event:
                    continue
                score = 0.0
                if bb_event is not None:
                    score += float(
                        by_event[bb_event]["forecast_uplifts"][ChipType.BENCH_BOOST.value]
                    )
                if tc_event is not None:
                    score += float(
                        by_event[tc_event]["forecast_uplifts"][
                            ChipType.TRIPLE_CAPTAIN.value
                        ]
                    )
                choices.append((score, bb_event, tc_event))
        _, bb_event, tc_event = max(
            choices,
            key=lambda row: (
                row[0],
                row[1] if row[1] is not None else -1,
                row[2] if row[2] is not None else -1,
            ),
        )
        if bb_event is not None:
            selected[bb_event] = ChipType.BENCH_BOOST.value
        if tc_event is not None:
            selected[tc_event] = ChipType.TRIPLE_CAPTAIN.value
    event_rows = []
    chip_events = []
    for opportunity in path["opportunities"]:
        event = int(opportunity["event"])
        chip = selected.get(event)
        uplift = int(opportunity["actual_uplifts"][chip]) if chip else 0
        if chip:
            chip_events.append(
                {
                    "event": event,
                    "half": 1 if event <= 19 else 2,
                    "chip": chip,
                    "forecast_uplift": opportunity["forecast_uplifts"][chip],
                    "actual_uplift": uplift,
                }
            )
        event_rows.append(
            {
                "event": event,
                "base_net_points": int(opportunity["base_net_points"]),
                "chip": chip,
                "chip_uplift": uplift,
                "net_points": int(opportunity["base_net_points"]) + uplift,
            }
        )
    return {
        "season": path["season"],
        "comparator": "best forecast-visible opportunity in each half",
        "base_net_points": sum(row["base_net_points"] for row in event_rows),
        "net_points": sum(row["net_points"] for row in event_rows),
        "chip_uplift": sum(row["chip_uplift"] for row in event_rows),
        "chip_events": chip_events,
        "events": event_rows,
    }


def _render(result: dict[str, Any]) -> str:
    gate = result["historical_gate"]
    oracle_interval = gate["test_oracle_regret_block_interval"]
    failed = [name for name, passed in gate["checks"].items() if not passed]
    return "\n".join(
        [
            "# Bench Boost and Triple Captain retained-value replay",
            "",
            f"Generated: {result['created_at']}",
            "",
            f"**{result['verdict']}**",
            "",
            (
                f"Selection uplift: {gate['selection_total_delta']:+.0f} points. Untouched test "
                f"uplift: {gate['test_total_delta']:+.0f}; four-GW block interval "
                f"{gate['test_block_interval']['p025']:+.3f} to "
                f"{gate['test_block_interval']['p975']:+.3f} points/GW."
            ),
            "",
            (
                f"Forecast-oracle test uplift: {gate['test_forecast_oracle_uplift']:+.0f}; "
                f"frozen-policy delta: {gate['test_delta_to_forecast_oracle']:+.0f}. "
                f"Four-GW oracle-regret interval: {oracle_interval['p025']:+.3f} to "
                f"{oracle_interval['p975']:+.3f} points/GW."
            ),
            "",
            f"Failed gates: {', '.join(failed) if failed else 'none'}.",
            "",
            (
                "The trigger pair is selected on 2023/24 only and tested on 2024/25. Every "
                "opportunity uses the forecast and schedule visible at that deadline; realised "
                "uplift is used only for scoring after the trigger is frozen."
            ),
            "",
            (
                "The forecast oracle is an offline retained-timing upper bound: within each "
                "half it selects the best forecast-visible Bench Boost and Triple Captain "
                "opportunities at distinct deadlines. It never enters the live policy."
            ),
            "",
            (
                "The replay isolates BB/TC on the ordinary transfer path. Joint competition with "
                "Wildcard and Free Hit and prospective 2026/27 evidence are still required for "
                "live authority."
            ),
            "",
        ]
    )


def load_team_chip_retention_results(path=RESULTS) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("version") != 1 or result.get("status") != "shadow":
        raise ValueError("team-chip retention result has an unsupported contract")
    for name, artifact in result.get("artifacts", {}).items():
        if name.endswith("_sha256"):
            continue
        expected = result["artifacts"].get(f"{name}_sha256")
        if expected and sha256_file(artifact) != expected:
            raise ValueError(f"team-chip retention artifact changed: {name}")
    return {
        **result,
        "receipt_path": str(path),
        "receipt_sha256": sha256_file(path),
    }


def run_team_chip_retention_replay() -> dict[str, Any]:
    grouped = _load_rows()
    schedule_rows = _load_schedule()
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers,
        rules=rules,
    )
    selection_path = build_team_chip_opportunity_path(
        season=SELECTION_SEASON,
        grouped=grouped,
        schedule_rows=schedule_rows,
        rules=rules,
        terminal_curve=terminal_curve,
    )
    test_path = build_team_chip_opportunity_path(
        season=TEST_SEASON,
        grouped=grouped,
        schedule_rows=schedule_rows,
        rules=rules,
        terminal_curve=terminal_curve,
    )
    bb_thresholds = (8.0, 12.0, 16.0, 20.0)
    tc_thresholds = (5.0, 6.0, 7.0, 8.0)
    candidates = {
        (bb, tc): score_team_chip_policy(
            selection_path,
            bench_boost_threshold=bb,
            triple_captain_threshold=tc,
        )
        for bb in bb_thresholds
        for tc in tc_thresholds
    }
    selected_key = max(
        candidates,
        key=lambda key: (candidates[key]["net_points"], key[0], key[1]),
    )
    selected_selection = candidates[selected_key]
    selected_test = score_team_chip_policy(
        test_path,
        bench_boost_threshold=selected_key[0],
        triple_captain_threshold=selected_key[1],
    )
    selection_oracle = score_team_chip_forecast_oracle(selection_path)
    test_oracle = score_team_chip_forecast_oracle(test_path)
    test_deltas = [row["chip_uplift"] for row in selected_test["events"]]
    interval = moving_block_mean_interval(test_deltas, seed=20260823)
    test_oracle_deltas = [
        selected["chip_uplift"] - oracle["chip_uplift"]
        for selected, oracle in zip(
            selected_test["events"], test_oracle["events"], strict=True
        )
    ]
    oracle_interval = moving_block_mean_interval(test_oracle_deltas, seed=20260824)
    schedule_coverage = {
        season: sum((season, event) in schedule_rows for event in range(1, 39)) / 38.0
        for season in (SELECTION_SEASON, TEST_SEASON)
    }
    checks = {
        "positive_selection_total": selected_selection["chip_uplift"] > 0,
        "positive_untouched_test_total": selected_test["chip_uplift"] > 0,
        "test_block_lower_bound_non_negative": interval["p025"] >= 0.0,
        "selection_schedule_coverage_at_least_90_percent": (
            schedule_coverage[SELECTION_SEASON] >= 0.90
        ),
        "test_schedule_coverage_at_least_90_percent": schedule_coverage[TEST_SEASON] >= 0.90,
        "test_uses_both_chip_types": {
            row["chip"] for row in selected_test["chip_events"]
        }
        == {ChipType.BENCH_BOOST.value, ChipType.TRIPLE_CAPTAIN.value},
        "test_within_four_points_of_forecast_oracle": sum(test_oracle_deltas) >= -4,
        "oracle_regret_block_lower_bound_above_minus_point_two_five": (
            oracle_interval["p025"] > -0.25
        ),
    }
    historical_passed = all(checks.values())
    historical_gate = {
        "passed": historical_passed,
        "checks": checks,
        "selected_bench_boost_threshold": selected_key[0],
        "selected_triple_captain_threshold": selected_key[1],
        "selection_total_delta": selected_selection["chip_uplift"],
        "test_total_delta": selected_test["chip_uplift"],
        "test_block_interval": interval,
        "selection_forecast_oracle_uplift": selection_oracle["chip_uplift"],
        "selection_delta_to_forecast_oracle": (
            selected_selection["chip_uplift"] - selection_oracle["chip_uplift"]
        ),
        "test_forecast_oracle_uplift": test_oracle["chip_uplift"],
        "test_delta_to_forecast_oracle": sum(test_oracle_deltas),
        "test_oracle_regret_block_interval": oracle_interval,
        "schedule_coverage": schedule_coverage,
    }
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "shadow",
        "verdict": "PASS_HISTORICAL_SHADOW" if historical_passed else "REJECT",
        "authority": False,
        "historical_gate": historical_gate,
        "promotion_gate": {
            "passed": False,
            "historical_passed": historical_passed,
            "prospective_2026_27_required": True,
            "joint_four_chip_replay_required": True,
        },
        "retained_value_thresholds": {
            ChipType.BENCH_BOOST.value: selected_key[0],
            ChipType.TRIPLE_CAPTAIN.value: selected_key[1],
        },
        "selection_candidates": {
            f"bb={key[0]:.0f},tc={key[1]:.0f}": {
                "chip_uplift": path["chip_uplift"],
                "chip_events": path["chip_events"],
            }
            for key, path in candidates.items()
        },
        "paths": {
            "selection": selected_selection,
            "test": selected_test,
            "selection_forecast_oracle": selection_oracle,
            "test_forecast_oracle": test_oracle,
        },
        "artifacts": {
            "forecast": str(BACKTEST_FORECAST),
            "forecast_sha256": sha256_file(BACKTEST_FORECAST),
            "schedule_opportunities": str(SCHEDULE_OPPORTUNITIES),
            "schedule_opportunities_sha256": sha256_file(SCHEDULE_OPPORTUNITIES),
        },
        "transfer_value": terminal_receipt,
        "policy": {
            "selection_season": SELECTION_SEASON,
            "untouched_test_season": TEST_SEASON,
            "one_chip_per_event": True,
            "one_each_per_current_rule_half": True,
            "future_deadline_forecasts_used_at_current_decision": False,
            "offline_comparator_uses_later_deadline_forecasts": True,
            "offline_comparator_has_live_authority": False,
            "squad_chip_competition_included": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
