from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .chip_schedule_history import OPPORTUNITIES as SCHEDULE_OPPORTUNITIES
from .features import TRAINING_FEATURES
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
from .season_state import ActionBundle, ChipType, apply_action
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_actions import (
    EvaluatedAction,
    generate_squad_chip_shadow_actions,
    generate_weekly_actions,
)

OUTPUT_ROOT = MODEL_DATA / "squad_chip_replay_v1"
RESULTS = OUTPUT_ROOT / "results.json"
REPORT = REPORTS / "squad-chip-retention-replay.md"
SELECTION_SEASON = "2023-24"
TEST_SEASON = "2024-25"
SEASONS = (SELECTION_SEASON, TEST_SEASON)


def _load_rows() -> dict[tuple[str, int], list[dict[str, Any]]]:
    minutes = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row["target_minutes"]
        )
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in SEASONS
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(raw["season"])
        if season not in SEASONS:
            continue
        key = (season, int(raw["event_number"]), int(raw["element"]))
        if raw.get("market_price") is None or key not in minutes:
            continue
        score = float(raw["expected_points"])
        grouped.setdefault((season, int(raw["event_number"])), []).append(
            {
                **raw,
                "market_price": round(float(raw["market_price"])),
                "target_points": float(raw["target_points"]),
                "target_minutes": minutes[key],
                "expected_points": score,
                "robust_points": score,
                "p_play": float(raw.get("p_play", 1.0)),
                "can_select": True,
                "removed": False,
            }
        )
    for season in SEASONS:
        available = sorted(event for candidate, event in grouped if candidate == season)
        if available != list(range(1, 39)):
            raise ValueError(f"Squad-chip replay requires events 1-38 for {season}: {available}")
    return grouped


def _load_schedule() -> dict[tuple[str, int], dict[str, Any]]:
    rows = pq.read_table(SCHEDULE_OPPORTUNITIES).to_pylist()
    return {
        (str(row["season"]), int(row["decision_event"])): row
        for row in rows
        if int(row["future_event"]) == int(row["decision_event"])
    }


def _choose_action(
    ordinary: list[EvaluatedAction],
    chips: list[EvaluatedAction],
    *,
    threshold: float | None,
    minimum_wildcard_changes: int,
    schedule: dict[str, Any] | None,
) -> tuple[EvaluatedAction, dict[str, Any]]:
    baseline = ordinary[0]
    context = {
        "baseline_action_id": baseline.action_id,
        "threshold": threshold,
        "schedule_known": schedule is not None,
        "schedule_confirmed": bool(schedule and schedule["schedule_confirmed"]),
        "blank_teams": int(schedule["blank_team_count"]) if schedule else None,
        "double_teams": int(schedule["double_team_count"]) if schedule else None,
        "chip_candidates": [],
    }
    if threshold is None:
        return baseline, context
    eligible = []
    for action in chips:
        chip = action.action.chip
        edge = action.decision_utility - baseline.decision_utility
        transfer_count = len(action.action.transfers)
        reason = "eligible"
        allowed = bool(schedule and schedule["schedule_confirmed"] and edge >= threshold)
        if chip == ChipType.WILDCARD and transfer_count < minimum_wildcard_changes:
            allowed = False
            reason = "insufficient structural changes"
        elif chip == ChipType.FREE_HIT and not (
            schedule
            and schedule["schedule_confirmed"]
            and (
                int(schedule["blank_team_count"]) > 0
                or int(schedule["double_team_count"]) > 0
            )
        ):
            allowed = False
            reason = "no confirmed blank/double opportunity"
        elif edge < threshold:
            reason = "forecast edge below threshold"
        elif not schedule or not schedule["schedule_confirmed"]:
            reason = "schedule not confirmed"
        row = {
            "action_id": action.action_id,
            "chip": chip.value if chip else None,
            "forecast_edge": edge,
            "transfer_count": transfer_count,
            "eligible": allowed,
            "reason": reason,
        }
        context["chip_candidates"].append(row)
        if allowed:
            eligible.append((edge, action.action_id, action))
    if not eligible:
        return baseline, context
    _, _, selected = max(eligible, key=lambda item: (item[0], item[1]))
    return selected, context


def run_squad_chip_policy_season(
    *,
    season: str,
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
    schedule_rows: dict[tuple[str, int], dict[str, Any]],
    rules: SquadRules,
    terminal_curve: dict[int, float],
    threshold: float | None,
    minimum_wildcard_changes: int = 4,
) -> dict[str, Any]:
    first_rows = grouped[(season, 1)]
    state, initial_solution = _initial_state(season=season, rows=first_rows, rules=rules)
    event_records = []
    gross = _score_gameweek(None, state, initial_solution, first_rows)
    event_records.append(
        {
            **_event_record(
                event=1,
                gross_points=gross,
                action=None,
                state=state,
                solution=initial_solution,
            ),
            "chip": None,
            "chip_context": None,
        }
    )
    initial_outcome = apply_action(state, ActionBundle(1, state.lineup), rules)
    if initial_outcome.next_manager is None:
        raise RuntimeError("GW1 unexpectedly ended the chip replay")
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
        chips = generate_squad_chip_shadow_actions(
            state,
            rows,
            rules,
            events=(event,),
            score_field="expected_points",
            alternatives_per_chip=1,
            terminal_free_transfer_curve=terminal_curve,
        )
        action, context = _choose_action(
            ordinary,
            chips,
            threshold=threshold,
            minimum_wildcard_changes=minimum_wildcard_changes,
            schedule=schedule_rows.get((season, event)),
        )
        gross = _score_gameweek(action, state, None, rows)
        event_records.append(
            {
                **_event_record(
                    event=event,
                    gross_points=gross,
                    action=action,
                    state=state,
                ),
                "chip": action.action.chip.value if action.action.chip else None,
                "chip_context": context,
            }
        )
        if event < 38:
            if action.outcome.next_manager is None:
                raise RuntimeError(f"Missing manager state after {season} GW{event}")
            state = action.outcome.next_manager
    return {
        "season": season,
        "threshold": threshold,
        "minimum_wildcard_changes": minimum_wildcard_changes,
        "gross_points": sum(row["gross_points"] for row in event_records),
        "points_cost": sum(row["points_cost"] for row in event_records),
        "net_points": sum(row["net_points"] for row in event_records),
        "transfers": sum(row["transfer_count"] for row in event_records),
        "chips": [
            {"event": row["event"], "chip": row["chip"]}
            for row in event_records
            if row["chip"]
        ],
        "events": event_records,
    }


def _render(result: dict[str, Any]) -> str:
    gate = result["historical_gate"]
    return "\n".join(
        [
            "# Wildcard and Free Hit retained-value replay",
            "",
            f"Generated: {result['created_at']}",
            "",
            f"**{result['verdict']}**",
            "",
            (
                f"Selection delta: {gate['selection_total_delta']:+.0f} net points. "
                f"Untouched test delta: {gate['test_total_delta']:+.0f}; four-GW block interval "
                f"{gate['test_block_interval']['p025']:+.3f} to "
                f"{gate['test_block_interval']['p975']:+.3f} points/GW."
            ),
            "",
            (
                "The replay applies the current two-half chip inventory counterfactually to older "
                "seasons. It uses only one-event deadline forecasts and the schedule snapshot "
                "visible before that deadline. WC changes persist; FH squads restore immediately "
                "afterward."
            ),
            "",
            (
                "Even a passing historical gate remains shadow-only until prospective 2026/27 "
                "receipts validate the retained-value policy under the actual current rules."
            ),
            "",
        ]
    )


def load_squad_chip_retention_results(path=RESULTS) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("version") != 1 or result.get("status") != "shadow":
        raise ValueError("squad-chip retention result has an unsupported contract")
    for name, artifact in result.get("artifacts", {}).items():
        if name.endswith("_sha256"):
            continue
        expected = result["artifacts"].get(f"{name}_sha256")
        if expected and sha256_file(Path(str(artifact))) != expected:
            raise ValueError(f"squad-chip retention artifact changed: {name}")
    return {
        **result,
        "receipt_path": str(path),
        "receipt_sha256": sha256_file(path),
    }


def run_squad_chip_retention_replay() -> dict[str, Any]:
    grouped = _load_rows()
    schedule_rows = _load_schedule()
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers,
        rules=rules,
    )
    baseline_selection = run_squad_chip_policy_season(
        season=SELECTION_SEASON,
        grouped=grouped,
        schedule_rows=schedule_rows,
        rules=rules,
        terminal_curve=terminal_curve,
        threshold=None,
    )
    thresholds = (2.0, 4.0, 6.0, 8.0)
    candidates = {
        threshold: run_squad_chip_policy_season(
            season=SELECTION_SEASON,
            grouped=grouped,
            schedule_rows=schedule_rows,
            rules=rules,
            terminal_curve=terminal_curve,
            threshold=threshold,
        )
        for threshold in thresholds
    }
    selected_threshold = max(
        thresholds,
        key=lambda value: (candidates[value]["net_points"], value),
    )
    baseline_test = run_squad_chip_policy_season(
        season=TEST_SEASON,
        grouped=grouped,
        schedule_rows=schedule_rows,
        rules=rules,
        terminal_curve=terminal_curve,
        threshold=None,
    )
    selected_test = run_squad_chip_policy_season(
        season=TEST_SEASON,
        grouped=grouped,
        schedule_rows=schedule_rows,
        rules=rules,
        terminal_curve=terminal_curve,
        threshold=selected_threshold,
    )
    selection_delta = (
        candidates[selected_threshold]["net_points"] - baseline_selection["net_points"]
    )
    test_deltas = [
        selected["net_points"] - baseline["net_points"]
        for selected, baseline in zip(
            selected_test["events"], baseline_test["events"], strict=True
        )
    ]
    interval = moving_block_mean_interval(test_deltas, seed=20260822)
    schedule_coverage = {
        season: sum((season, event) in schedule_rows for event in range(2, 39)) / 37.0
        for season in SEASONS
    }
    checks = {
        "positive_selection_total": selection_delta > 0,
        "positive_untouched_test_total": sum(test_deltas) > 0,
        "test_block_lower_bound_above_minus_point_two_five": interval["p025"] > -0.25,
        "selection_schedule_coverage_at_least_90_percent": (
            schedule_coverage[SELECTION_SEASON] >= 0.90
        ),
        "test_schedule_coverage_at_least_90_percent": schedule_coverage[TEST_SEASON] >= 0.90,
        "test_policy_uses_a_squad_chip": bool(selected_test["chips"]),
    }
    historical_passed = all(checks.values())
    historical_gate = {
        "passed": historical_passed,
        "checks": checks,
        "selected_threshold": selected_threshold,
        "selection_total_delta": selection_delta,
        "test_total_delta": sum(test_deltas),
        "test_block_interval": interval,
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
        },
        "selection_candidates": {
            str(threshold): {
                "net_points": path["net_points"],
                "delta_to_no_chip": path["net_points"] - baseline_selection["net_points"],
                "chips": path["chips"],
            }
            for threshold, path in candidates.items()
        },
        "paths": {
            "selection_no_chip": baseline_selection,
            "selection_selected_policy": candidates[selected_threshold],
            "test_no_chip": baseline_test,
            "test_selected_policy": selected_test,
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
            "minimum_wildcard_changes": 4,
            "free_hit_requires_confirmed_blank_or_double": True,
            "current_2026_27_chip_rules_applied_counterfactually": True,
            "future_deadline_forecasts_used_at_current_decision": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
