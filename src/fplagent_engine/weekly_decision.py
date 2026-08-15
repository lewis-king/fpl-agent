from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .challenger_registry import RESULTS as CHALLENGER_REGISTRY
from .component_models import CURRENT_COMPONENT_FORECAST
from .component_models import MODEL_FILE as COMPONENT_EVENT_MODEL_FILE
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    GOAL_MODEL_FILE,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
    train_goal_model,
)
from .early_transfer import evaluate_early_transfer_shadow
from .form_reversion import evaluate_form_reversion_shadow
from .manager_state_adapter import manager_state_from_snapshot, player_catalog_from_rows
from .manager_state_store import load_manager_state_contract
from .market_odds import (
    CURRENT_FPL_EVENTS,
    CURRENT_MARKET_RATES,
    CURRENT_MARKET_RECEIPT,
    apply_current_market_decision_rates,
    apply_current_market_shadow_rates,
)
from .mini_league import (
    DEFAULT_CONTEXT as DEFAULT_MINI_LEAGUE_CONTEXT,
)
from .mini_league import (
    MiniLeagueStrategyError,
    evaluate_mini_league_shadow,
)
from .prospective_dashboard import RESULTS as PROSPECTIVE_SCOREBOARD
from .rules import SquadRules
from .schedule_rearrangement import evaluate_rearrangement_shadow
from .schedule_scenarios import (
    CURRENT_FIXTURES as CURRENT_SCHEDULE_FIXTURES,
)
from .schedule_scenarios import (
    CURRENT_SCHEDULE_RECEIPT,
    load_schedule_receipt,
    schedule_horizon_status,
)
from .squad_chip_replay import load_squad_chip_retention_results
from .team_chip_replay import load_team_chip_retention_results
from .tournament import _simulate_player_outcomes, calibrate_residuals
from .transfer_value import ARTIFACT as TRANSFER_VALUE_ARTIFACT
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_actions import (
    EvaluatedAction,
    _forecast_grid,
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from .weekly_simulation import (
    ActionPathMetric,
    combine_scenario_regret,
    evaluate_action_paths,
)

DEFAULT_SCENARIO_WEIGHTS = {
    "residual": 0.50,
    "component_anchored": 0.45,
    "component_raw": 0.05,
}


def summarize_market_shadow_scenario(
    incumbent: list[ActionPathMetric],
    challenger: list[ActionPathMetric],
) -> dict[str, Any]:
    """Compact an action-policy comparison while retaining decision-relevant changes."""
    incumbent_by_id = {row.action_id: row for row in incumbent}
    challenger_by_id = {row.action_id: row for row in challenger}
    if set(incumbent_by_id) != set(challenger_by_id):
        raise ValueError("Market shadow and incumbent action IDs do not match")
    incumbent_order = sorted(
        incumbent_by_id, key=lambda key: (-incumbent_by_id[key].mean_net_points, key)
    )
    challenger_order = sorted(
        challenger_by_id, key=lambda key: (-challenger_by_id[key].mean_net_points, key)
    )
    incumbent_rank = {key: index + 1 for index, key in enumerate(incumbent_order)}
    challenger_rank = {key: index + 1 for index, key in enumerate(challenger_order)}
    changes = [
        {
            "action_id": key,
            "incumbent_mean_net_points": incumbent_by_id[key].mean_net_points,
            "market_mean_net_points": challenger_by_id[key].mean_net_points,
            "mean_net_points_shift": (
                challenger_by_id[key].mean_net_points
                - incumbent_by_id[key].mean_net_points
            ),
            "incumbent_rank": incumbent_rank[key],
            "market_rank": challenger_rank[key],
            "rank_shift": incumbent_rank[key] - challenger_rank[key],
        }
        for key in incumbent_by_id
    ]
    changes.sort(key=lambda row: (-abs(row["mean_net_points_shift"]), row["action_id"]))
    return {
        "incumbent_leader": incumbent_order[0],
        "market_leader": challenger_order[0],
        "leader_changed": incumbent_order[0] != challenger_order[0],
        "incumbent_leader_market_rank": challenger_rank[incumbent_order[0]],
        "market_leader_incumbent_rank": incumbent_rank[challenger_order[0]],
        "maximum_absolute_action_value_shift": max(
            abs(row["mean_net_points_shift"]) for row in changes
        ),
        "largest_action_value_shifts": changes[:10],
    }


def _unique_strings(table: pa.Table, column: str) -> set[str]:
    if column not in table.column_names:
        return set()
    return {str(value) for value in table[column].to_pylist() if value not in (None, "")}


def _forecast_keys(table: pa.Table, *, label: str) -> set[tuple[int, int]]:
    required = {"event_number", "element"}
    missing = required.difference(table.column_names)
    if missing:
        raise ValueError(f"{label} is missing key columns: {sorted(missing)}")
    try:
        keys = {
            (int(event), int(element))
            for event, element in zip(
                table["event_number"].to_pylist(),
                table["element"].to_pylist(),
                strict=True,
            )
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} contains invalid event/player keys") from exc
    if len(keys) != table.num_rows:
        raise ValueError(f"{label} contains duplicate event/player rows")
    return keys


def require_weekly_forecast_lineage(
    forecast_path: Path,
    component_forecast_path: Path,
    *,
    events: tuple[int, ...],
    component_model_path: Path = COMPONENT_EVENT_MODEL_FILE,
) -> dict[str, Any]:
    """Fail closed unless the weekly forecast artifacts form one exact generation."""
    if not events or len(set(events)) != len(events):
        raise ValueError("Weekly decision events must be non-empty and unique")
    try:
        direct = pq.read_table(forecast_path)
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"Direct forecast is unreadable: {forecast_path}") from exc
    try:
        component = pq.read_table(component_forecast_path)
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"Component forecast is unreadable: {component_forecast_path}") from exc

    direct_keys = _forecast_keys(direct, label="Direct forecast")
    component_keys = _forecast_keys(component, label="Component forecast")
    if component_keys != direct_keys:
        raise ValueError("Component forecast keys do not exactly match the direct forecast grid")
    missing_events = set(events).difference({event for event, _ in direct_keys})
    if missing_events:
        raise ValueError(f"Forecast grid does not cover requested events: {sorted(missing_events)}")

    direct_hash = sha256_file(forecast_path)
    referenced_hashes = _unique_strings(component, "direct_forecast_sha256")
    if referenced_hashes != {direct_hash}:
        raise ValueError("Component forecast does not reference the exact direct forecast bytes")
    direct_snapshots = _unique_strings(direct, "snapshot_at")
    component_snapshots = _unique_strings(component, "snapshot_at")
    if len(direct_snapshots) != 1 or component_snapshots != direct_snapshots:
        raise ValueError("Direct and component forecasts do not share one source snapshot")

    component_versions = _unique_strings(component, "component_model_version")
    component_created = _unique_strings(component, "component_model_created_at")
    component_forecast_created = _unique_strings(component, "component_forecast_created_at")
    if not all(
        len(values) == 1
        for values in (component_versions, component_created, component_forecast_created)
    ):
        raise ValueError("Component forecast must identify exactly one model generation")
    if not component_model_path.is_file():
        raise ValueError(f"Component event model is missing: {component_model_path}")
    component_model_hash = sha256_file(component_model_path)
    recorded_model_hashes = _unique_strings(component, "component_model_sha256")
    if recorded_model_hashes != {component_model_hash}:
        raise ValueError("Component forecast does not reference the exact component model bytes")

    return {
        "direct_forecast_sha256": direct_hash,
        "component_forecast_sha256": sha256_file(component_forecast_path),
        "component_model_sha256": component_model_hash,
        "snapshot_at": next(iter(direct_snapshots)),
        "component_model_version": next(iter(component_versions)),
        "component_model_created_at": next(iter(component_created)),
        "component_forecast_created_at": next(iter(component_forecast_created)),
        "rows": direct.num_rows,
        "events": sorted({event for event, _ in direct_keys}),
    }


def _rules_sha256(rules: SquadRules) -> str:
    payload = json.dumps(asdict(rules), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_weekly_manager_state(
    manager_state_path: Path,
    *,
    forecast_path: Path,
    event: int,
    rules: SquadRules,
    forecast_rows: list[dict[str, Any]] | None = None,
) -> tuple[Any, str]:
    """Load either the exact derived contract or the legacy raw snapshot input."""
    try:
        manager_payload = json.loads(manager_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Manager state input is unreadable: {manager_state_path}") from exc
    if manager_payload.get("contract_version") is not None:
        state = load_manager_state_contract(
            manager_state_path,
            rules=rules,
            expected_event=event,
            expected_forecast_path=forecast_path,
        )
        return state, "manager_state_contract"
    rows = forecast_rows if forecast_rows is not None else pq.read_table(forecast_path).to_pylist()
    state = manager_state_from_snapshot(
        manager_payload,
        event=event,
        player_catalog=player_catalog_from_rows(rows, event=event),
        rules=rules,
    )
    return state, "manager_snapshot"


def _metric_map(metrics: list[ActionPathMetric]) -> dict[str, ActionPathMetric]:
    return {metric.action_id: metric for metric in metrics}


def _promotion_gate(
    leader: EvaluatedAction,
    scenario_metrics: dict[str, list[ActionPathMetric]],
    scenario_weights: dict[str, float],
) -> dict[str, Any]:
    if leader.route_type == "roll":
        return {
            "passed": True,
            "status": "roll_is_robust_leader",
            "checks": [
                {
                    "name": "roll comparator",
                    "passed": True,
                    "evidence": "roll has the lowest cross-scenario robust regret",
                }
            ],
        }
    mapped = {name: _metric_map(metrics) for name, metrics in scenario_metrics.items()}
    leader_metrics = {name: values[leader.action_id] for name, values in mapped.items()}
    central_name = max(scenario_weights, key=scenario_weights.get)
    weighted_delta = sum(
        scenario_weights[name] * metric.mean_delta_to_roll
        for name, metric in leader_metrics.items()
    )
    worst_delta = min(metric.mean_delta_to_roll for metric in leader_metrics.values())
    central = leader_metrics[central_name]
    checks = [
        {
            "name": "positive weighted after-cost gain",
            "passed": weighted_delta > 0.0,
            "evidence": f"weighted mean delta to roll={weighted_delta:+.3f}",
        },
        {
            "name": "no material scenario reversal",
            "passed": worst_delta >= -0.25,
            "evidence": f"worst scenario mean delta to roll={worst_delta:+.3f}",
        },
        {
            "name": "central paired uncertainty",
            "passed": central.delta_to_roll_95ci_low > -0.05,
            "evidence": (
                f"{central_name} paired 95% CI="
                f"[{central.delta_to_roll_95ci_low:+.3f}, "
                f"{central.delta_to_roll_95ci_high:+.3f}]"
            ),
        },
    ]
    if leader.incremental_points_cost > 0:
        paid_checks = [
            {
                "name": "paid move positive in every scenario",
                "passed": worst_delta > 0.0,
                "evidence": f"worst after-hit mean delta={worst_delta:+.3f}",
            },
            {
                "name": "paid move central interval excludes zero",
                "passed": central.delta_to_roll_95ci_low > 0.0,
                "evidence": (
                    f"{central_name} lower confidence bound={central.delta_to_roll_95ci_low:+.3f}"
                ),
            },
            {
                "name": "paid move beats roll often enough",
                "passed": central.beat_roll_probability >= 0.55,
                "evidence": (
                    f"{central_name} beat-roll probability={central.beat_roll_probability:.1%}"
                ),
            },
        ]
        checks.extend(paid_checks)
    passed = all(bool(check["passed"]) for check in checks)
    return {
        "passed": passed,
        "status": "promoted" if passed else "roll_due_to_uncertainty",
        "weighted_mean_delta_to_roll": weighted_delta,
        "worst_scenario_mean_delta_to_roll": worst_delta,
        "central_scenario": central_name,
        "checks": checks,
    }


def synthesize_weekly_decision(
    actions: list[EvaluatedAction],
    scenario_metrics: dict[str, list[ActionPathMetric]],
    *,
    scenario_weights: dict[str, float],
    worst_case_weight: float = 0.25,
    created_at: str | None = None,
) -> dict[str, Any]:
    ranking = combine_scenario_regret(
        scenario_metrics,
        scenario_weights=scenario_weights,
        worst_case_weight=worst_case_weight,
    )
    by_action = {action.action_id: action for action in actions}
    if set(by_action) != {row["action_id"] for row in ranking}:
        raise ValueError("Action objects and scenario ranking contain different action IDs")
    roll = next((action for action in actions if action.route_type == "roll"), None)
    if roll is None:
        raise ValueError("Weekly decision synthesis requires a roll action")
    robust_leader = by_action[ranking[0]["action_id"]]
    gate = _promotion_gate(robust_leader, scenario_metrics, scenario_weights)
    selected = robust_leader if gate["passed"] else roll
    selected_rank = next(row for row in ranking if row["action_id"] == selected.action_id)
    rejected = next((row for row in ranking if row["action_id"] != selected.action_id), None)
    metric_by_scenario = {
        name: asdict(_metric_map(metrics)[selected.action_id])
        for name, metrics in scenario_metrics.items()
    }
    all_scenario_metrics = {
        name: {metric.action_id: asdict(metric) for metric in metrics}
        for name, metrics in scenario_metrics.items()
    }
    action_summaries = [
        {
            "action_id": action.action_id,
            "route_type": action.route_type,
            "transfer_count": len(action.action.transfers),
            "transfers": [
                {
                    "outgoing_player_id": transfer.outgoing_player_id,
                    "incoming_player_id": transfer.incoming.player_id,
                    "incoming_position": transfer.incoming.position,
                    "incoming_team_id": transfer.incoming.team_id,
                    "incoming_price": transfer.incoming.current_price,
                }
                for transfer in action.action.transfers
            ],
            "formation": action.lineups[0].formation,
            "captain_player_id": action.lineups[0].lineup.captain,
            "vice_captain_player_id": action.lineups[0].lineup.vice_captain,
            "starter_player_ids": list(action.lineups[0].lineup.starters),
            "bench_player_ids": list(action.lineups[0].lineup.bench_order),
            "incremental_points_cost": action.incremental_points_cost,
            "total_points_cost": action.total_points_cost,
            "next_free_transfers": action.next_free_transfers,
            "terminal_free_transfers": action.terminal_free_transfers,
            "terminal_transfer_value": action.terminal_transfer_value,
            "gross_horizon_utility": action.gross_horizon_utility,
            "decision_utility": action.decision_utility,
            "event_lineups": [
                {
                    "event": item.event,
                    "formation": item.formation,
                    "projected_points": item.projected_points,
                    "starter_player_ids": list(item.lineup.starters),
                    "bench_player_ids": list(item.lineup.bench_order),
                    "captain_player_id": item.lineup.captain,
                    "vice_captain_player_id": item.lineup.vice_captain,
                }
                for item in action.lineups
            ],
        }
        for action in actions
    ]
    return {
        "version": "weekly_decision_synthesis_v3",
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "decision_event": selected.action.event,
        "selected_action_id": selected.action_id,
        "selected_route_type": selected.route_type,
        "robust_leader_action_id": robust_leader.action_id,
        "roll_action_id": roll.action_id,
        "promotion_gate": gate,
        "selected_action": asdict(selected),
        "action_summaries": action_summaries,
        "scenario_metrics_by_action": all_scenario_metrics,
        "selected_scenario_metrics": metric_by_scenario,
        "selected_robust_metrics": selected_rank,
        "strongest_rejected": rejected,
        "ranking": ranking,
        "method": {
            "scenario_weights": scenario_weights,
            "worst_case_weight": worst_case_weight,
            "points_cost_basis": "incremental points cost; previously committed hits are sunk",
            "roll_is_mandatory_comparator": True,
        },
    }


def synthesize_team_chip_shadow(
    base_actions: list[EvaluatedAction],
    chip_actions: list[EvaluatedAction],
    scenario_totals: dict[str, np.ndarray],
    *,
    scenario_weights: dict[str, float],
    schedule_status: dict[str, Any] | None = None,
    retention_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not chip_actions:
        return {
            "status": "no_available_team_chip_variants",
            "operational_recommendation": "no_chip",
            "candidates": [],
        }
    all_actions = [*base_actions, *chip_actions]
    if any(values.shape[1] != len(all_actions) for values in scenario_totals.values()):
        raise ValueError("Chip shadow totals do not match the evaluated action order")
    if set(scenario_totals) != set(scenario_weights):
        raise ValueError("Chip shadow totals and scenario weights differ")
    index = {action.action_id: offset for offset, action in enumerate(all_actions)}
    if len(index) != len(all_actions):
        raise ValueError("Chip shadow actions must have unique IDs")
    central_name = max(scenario_weights, key=scenario_weights.get)
    schedule_confirmed = bool(schedule_status and schedule_status.get("fully_confirmed"))
    schedule_issues = list(schedule_status.get("issues", [])) if schedule_status else [
        "no schedule status was supplied"
    ]
    rows = []
    historical_retention_passed = bool(
        retention_calibration
        and (retention_calibration.get("historical_gate") or {}).get("passed")
    )
    promotion_retention_passed = bool(
        retention_calibration
        and (retention_calibration.get("promotion_gate") or {}).get("passed")
    )
    calibrated_thresholds = (
        retention_calibration.get("retained_value_thresholds", {})
        if historical_retention_passed
        else {}
    )
    for action in chip_actions:
        if action.parent_action_id not in index:
            raise ValueError(f"Chip action {action.action_id} has no evaluated parent")
        variant_index = index[action.action_id]
        parent_index = index[action.parent_action_id]
        chip_name = action.action.chip.value if action.action.chip else ""
        retained_value = max(
            action.retained_chip_proxy_value,
            float(calibrated_thresholds.get(chip_name, 0.0)),
        )
        scenario_rows = {}
        for name, totals in scenario_totals.items():
            raw_delta = totals[:, variant_index] - totals[:, parent_index]
            net_delta = raw_delta - retained_value
            mean = float(net_delta.mean())
            standard_error = (
                float(net_delta.std(ddof=1) / math.sqrt(len(net_delta)))
                if len(net_delta) > 1
                else 0.0
            )
            scenario_rows[name] = {
                "mean_current_chip_uplift": float(raw_delta.mean()),
                "retained_chip_proxy_value": retained_value,
                "mean_net_value": mean,
                "net_value_95ci_low": mean - 1.96 * standard_error,
                "net_value_95ci_high": mean + 1.96 * standard_error,
                "probability_current_beats_retention_proxy": float(np.mean(net_delta > 0)),
            }
        weighted = sum(
            scenario_weights[name] * values["mean_net_value"]
            for name, values in scenario_rows.items()
        )
        worst = min(values["mean_net_value"] for values in scenario_rows.values())
        central = scenario_rows[central_name]
        checks = [
            {
                "name": "chip-half horizon complete",
                "passed": action.chip_horizon_complete,
                "evidence": (
                    "forecast covers every remaining event before chip expiry"
                    if action.chip_horizon_complete
                    else "forecast does not cover every remaining event before chip expiry"
                ),
            },
            {
                "name": "schedule horizon confirmed",
                "passed": schedule_confirmed,
                "evidence": (
                    "every team-event fixture opportunity in the evaluated horizon is confirmed"
                    if schedule_confirmed
                    else "; ".join(schedule_issues)
                ),
            },
            {
                "name": "positive weighted value after retention proxy",
                "passed": weighted > 0.0,
                "evidence": f"weighted net chip value={weighted:+.3f}",
            },
            {
                "name": "no scenario reversal",
                "passed": worst > 0.0,
                "evidence": f"worst scenario net chip value={worst:+.3f}",
            },
            {
                "name": "central paired interval excludes zero",
                "passed": central["net_value_95ci_low"] > 0.0,
                "evidence": (
                    f"{central_name} 95% CI=[{central['net_value_95ci_low']:+.3f}, "
                    f"{central['net_value_95ci_high']:+.3f}]"
                ),
            },
        ]
        if retention_calibration is not None:
            checks.append(
                {
                    "name": "retention policy promoted",
                    "passed": promotion_retention_passed,
                    "evidence": (
                        f"historical verdict={retention_calibration.get('verdict')}; "
                        "joint four-chip and prospective gates remain required"
                    ),
                }
            )
        rows.append(
            {
                "action_id": action.action_id,
                "parent_action_id": action.parent_action_id,
                "chip": action.action.chip.value if action.action.chip else None,
                "route_type": action.route_type,
                "current_proxy_uplift": action.chip_current_proxy_uplift,
                "retained_chip_proxy_value": retained_value,
                "historical_retention_threshold": calibrated_thresholds.get(chip_name),
                "chip_horizon_complete": action.chip_horizon_complete,
                "weighted_mean_net_value": weighted,
                "worst_scenario_net_value": worst,
                "scenario_metrics": scenario_rows,
                "checks": checks,
                "shadow_gate_passed": all(check["passed"] for check in checks),
            }
        )
    rows.sort(
        key=lambda row: (
            not row["shadow_gate_passed"],
            -row["weighted_mean_net_value"],
            row["action_id"],
        )
    )
    leader = rows[0]
    status = (
        "shadow_gate_passed_not_promoted"
        if leader["shadow_gate_passed"]
        else "retain_chip"
    )
    return {
        "status": status,
        "operational_recommendation": "no_chip",
        "shadow_preference": {
            "action_id": leader["action_id"],
            "chip": leader["chip"],
            "parent_action_id": leader["parent_action_id"],
        },
        "central_scenario": central_name,
        "schedule_status": schedule_status,
        "retention_calibration": (
            {
                "verdict": retention_calibration.get("verdict"),
                "historical_gate": retention_calibration.get("historical_gate"),
                "promotion_gate": retention_calibration.get("promotion_gate"),
                "retained_value_thresholds": retention_calibration.get(
                    "retained_value_thresholds"
                ),
                "receipt_path": retention_calibration.get("receipt_path"),
                "receipt_sha256": retention_calibration.get("receipt_sha256"),
            }
            if retention_calibration
            else None
        ),
        "candidates": rows,
        "promotion_policy": (
            "Team-chip routes remain shadow-only until their retention proxy is historically "
            "calibrated and prospective receipts validate the gate. Incomplete half-season "
            "horizon coverage or unresolved fixture scheduling always forces no-chip."
        ),
    }


def synthesize_squad_chip_shadow(
    base_actions: list[EvaluatedAction],
    squad_chip_actions: list[EvaluatedAction],
    evaluated_actions: list[EvaluatedAction],
    scenario_totals: dict[str, np.ndarray],
    *,
    scenario_weights: dict[str, float],
    schedule_status: dict[str, Any] | None = None,
    retention_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare exact WC/FH searches while retaining both chips operationally."""
    if not squad_chip_actions:
        return {
            "status": "no_available_squad_chip_variants",
            "operational_recommendation": "no_chip",
            "decision_authority": False,
            "candidates": [],
        }
    if any(values.shape[1] != len(evaluated_actions) for values in scenario_totals.values()):
        raise ValueError("Squad-chip totals do not match the evaluated action order")
    if set(scenario_totals) != set(scenario_weights):
        raise ValueError("Squad-chip totals and scenario weights differ")
    index = {action.action_id: offset for offset, action in enumerate(evaluated_actions)}
    if len(index) != len(evaluated_actions):
        raise ValueError("Squad-chip evaluation actions must have unique IDs")
    if not base_actions or any(action.action_id not in index for action in base_actions):
        raise ValueError("Squad-chip comparison requires evaluated ordinary actions")
    if any(action.action_id not in index for action in squad_chip_actions):
        raise ValueError("Squad-chip comparison is missing an evaluated chip action")

    weighted_base_means = {
        action.action_id: sum(
            scenario_weights[name]
            * float(values[:, index[action.action_id]].mean())
            for name, values in scenario_totals.items()
        )
        for action in base_actions
    }
    baseline_id = max(
        weighted_base_means,
        key=lambda action_id: (weighted_base_means[action_id], action_id),
    )
    baseline_index = index[baseline_id]
    central_name = max(scenario_weights, key=scenario_weights.get)
    schedule_confirmed = bool(schedule_status and schedule_status.get("fully_confirmed"))
    schedule_issues = (
        list(schedule_status.get("issues", []))
        if schedule_status
        else ["no schedule status was supplied"]
    )
    retention_passed = bool(
        retention_calibration
        and (retention_calibration.get("promotion_gate") or {}).get("passed")
    )
    retention_evidence = (
        (
            f"historical verdict={retention_calibration.get('verdict')}; "
            f"test delta={(retention_calibration.get('historical_gate') or {}).get('test_total_delta')}; "
            "prospective promotion gate remains closed"
        )
        if retention_calibration
        else "no checksum-validated retained-value replay was available"
    )
    rows = []
    for action in squad_chip_actions:
        scenario_rows = {}
        action_index = index[action.action_id]
        for name, totals in scenario_totals.items():
            delta = totals[:, action_index] - totals[:, baseline_index]
            mean = float(delta.mean())
            standard_error = (
                float(delta.std(ddof=1) / math.sqrt(len(delta))) if len(delta) > 1 else 0.0
            )
            scenario_rows[name] = {
                "mean_raw_delta_to_best_ordinary": mean,
                "raw_delta_95ci_low": mean - 1.96 * standard_error,
                "raw_delta_95ci_high": mean + 1.96 * standard_error,
                "probability_beats_best_ordinary": float(np.mean(delta > 0)),
            }
        weighted = sum(
            scenario_weights[name] * values["mean_raw_delta_to_best_ordinary"]
            for name, values in scenario_rows.items()
        )
        worst = min(
            values["mean_raw_delta_to_best_ordinary"]
            for values in scenario_rows.values()
        )
        central = scenario_rows[central_name]
        checks = [
            {
                "name": "chip-half opportunity horizon complete",
                "passed": action.chip_horizon_complete,
                "evidence": (
                    "forecast covers every remaining event before chip expiry"
                    if action.chip_horizon_complete
                    else "future chip opportunities before expiry are outside the forecast horizon"
                ),
            },
            {
                "name": "schedule horizon confirmed",
                "passed": schedule_confirmed,
                "evidence": (
                    "all evaluated fixture allocations are confirmed"
                    if schedule_confirmed
                    else "; ".join(schedule_issues)
                ),
            },
            {
                "name": "positive raw weighted edge",
                "passed": weighted > 0.0,
                "evidence": f"weighted raw delta={weighted:+.3f}",
            },
            {
                "name": "no model-world reversal",
                "passed": worst > 0.0,
                "evidence": f"worst model-world raw delta={worst:+.3f}",
            },
            {
                "name": "central paired interval excludes zero",
                "passed": central["raw_delta_95ci_low"] > 0.0,
                "evidence": (
                    f"{central_name} 95% CI=[{central['raw_delta_95ci_low']:+.3f}, "
                    f"{central['raw_delta_95ci_high']:+.3f}]"
                ),
            },
            {
                "name": "retained chip option value calibrated",
                "passed": retention_passed,
                "evidence": retention_evidence,
            },
        ]
        rows.append(
            {
                "action_id": action.action_id,
                "chip": action.action.chip.value if action.action.chip else None,
                "route_type": action.route_type,
                "transfer_count": len(action.action.transfers),
                "transfers": [
                    {
                        "outgoing_player_id": transfer.outgoing_player_id,
                        "incoming_player_id": transfer.incoming.player_id,
                        "incoming_price": transfer.incoming.current_price,
                    }
                    for transfer in action.action.transfers
                ],
                "selected_player_ids": list(action.selected_player_ids),
                "starter_player_ids": list(action.action.lineup.starters),
                "bench_player_ids": list(action.action.lineup.bench_order),
                "captain_player_id": action.action.lineup.captain,
                "vice_captain_player_id": action.action.lineup.vice_captain,
                "bank_after_chip_squad": action.outcome.gameweek.bank,
                "next_free_transfers": action.next_free_transfers,
                "future_event_squads": {
                    str(event): list(selected) for event, selected in action.event_squads
                },
                "chip_horizon_complete": action.chip_horizon_complete,
                "weighted_raw_delta_to_best_ordinary": weighted,
                "worst_model_world_raw_delta": worst,
                "scenario_metrics": scenario_rows,
                "checks": checks,
                "shadow_gate_passed": all(check["passed"] for check in checks),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["weighted_raw_delta_to_best_ordinary"],
            row["action_id"],
        )
    )
    leader = rows[0]
    return {
        "status": "retain_chip_uncalibrated_option_value",
        "operational_recommendation": "no_chip",
        "decision_authority": False,
        "best_ordinary_action_id": baseline_id,
        "best_ordinary_weighted_mean": weighted_base_means[baseline_id],
        "shadow_preference": {
            "action_id": leader["action_id"],
            "chip": leader["chip"],
        },
        "central_scenario": central_name,
        "schedule_status": schedule_status,
        "retention_calibration": (
            {
                "verdict": retention_calibration.get("verdict"),
                "historical_gate": retention_calibration.get("historical_gate"),
                "promotion_gate": retention_calibration.get("promotion_gate"),
                "receipt_path": retention_calibration.get("receipt_path"),
                "receipt_sha256": retention_calibration.get("receipt_sha256"),
            }
            if retention_calibration
            else None
        ),
        "candidates": rows,
        "promotion_policy": (
            "Wildcard and Free Hit searches are exact legal counterfactuals, not recommendations. "
            "Promotion requires point-in-time retained-chip calibration, schedule completeness and "
            "prospective net-points validation; raw current-horizon uplift is insufficient."
        ),
    }


def simulate_production_weekly_scenarios(
    actions: list[EvaluatedAction],
    rows: list[dict[str, Any]],
    *,
    events: tuple[int, ...],
    residual_simulations: int = 10_000,
    component_simulations: int = 25_000,
    residual_seed: int = 20260811,
    component_seed: int = 20260812,
    horizon_decay: float = 0.88,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
) -> tuple[
    dict[str, list[ActionPathMetric]],
    dict[str, Any],
    dict[str, float],
    dict[str, np.ndarray],
]:
    if residual_simulations < 1_000 or component_simulations < 5_000:
        raise ValueError("Production weekly simulation counts are below the safety minimum")
    if residual_seed == component_seed:
        raise ValueError("Residual and component simulations require independent seeds")
    by_player, meta = _forecast_grid(rows, events)
    player_ids = sorted(by_player)
    residual_calibration = calibrate_residuals()
    residual_points, residual_played = _simulate_player_outcomes(
        player_ids,
        events,
        by_player,
        residual_calibration,
        residual_simulations,
        residual_seed,
    )
    residual_metrics, residual_totals = evaluate_action_paths(
        actions,
        player_ids=player_ids,
        events=events,
        points=residual_points,
        played=residual_played,
        player_meta=meta,
        horizon_decay=horizon_decay,
    )
    form_reversion_shadow = evaluate_form_reversion_shadow(
        actions,
        rows,
        player_ids=player_ids,
        events=events,
        points=residual_points,
        played=residual_played,
        player_meta=meta,
        horizon_decay=horizon_decay,
    )

    train_goal_model(force=False, seed=component_seed)
    incumbent_goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, events)
    goal_rates, market_decision = apply_current_market_decision_rates(
        incumbent_goal_rates,
        events=events,
    )
    empirical = calibrate_empirical_components()
    (
        component_player_ids,
        raw_points,
        anchored_points,
        component_played,
        _,
        component_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        events,
        goal_rates,
        empirical,
        component_simulations,
        component_seed,
        component_forecast_path=component_forecast_path,
    )
    raw_metrics, raw_totals = evaluate_action_paths(
        actions,
        player_ids=component_player_ids,
        events=events,
        points=raw_points,
        played=component_played,
        player_meta=meta,
        horizon_decay=horizon_decay,
    )
    anchored_metrics, anchored_totals = evaluate_action_paths(
        actions,
        player_ids=component_player_ids,
        events=events,
        points=anchored_points,
        played=component_played,
        player_meta=meta,
        horizon_decay=horizon_decay,
    )
    market_goal_rates, market_shadow = apply_current_market_shadow_rates(
        incumbent_goal_rates,
        events=events,
    )
    market_shadow["production_application"] = market_decision
    if market_shadow["status"] == "ready_shadow":
        (
            market_player_ids,
            market_raw_points,
            market_anchored_points,
            market_played,
            _,
            market_component_diagnostics,
        ) = simulate_component_outcomes(
            by_player,
            events,
            market_goal_rates,
            empirical,
            component_simulations,
            component_seed,
            component_forecast_path=component_forecast_path,
        )
        if market_player_ids != component_player_ids:
            raise ValueError("Market shadow changed the component player universe")
        market_raw_metrics, _ = evaluate_action_paths(
            actions,
            player_ids=market_player_ids,
            events=events,
            points=market_raw_points,
            played=market_played,
            player_meta=meta,
            horizon_decay=horizon_decay,
        )
        market_anchored_metrics, _ = evaluate_action_paths(
            actions,
            player_ids=market_player_ids,
            events=events,
            points=market_anchored_points,
            played=market_played,
            player_meta=meta,
            horizon_decay=horizon_decay,
        )
        market_shadow.update(
            {
                "simulations": component_simulations,
                "seed": component_seed,
                "paired_random_stream": True,
                "raw_component_comparison": summarize_market_shadow_scenario(
                    raw_metrics, market_raw_metrics
                ),
                "anchored_component_comparison": summarize_market_shadow_scenario(
                    anchored_metrics, market_anchored_metrics
                ),
                "component_diagnostics": market_component_diagnostics,
            }
        )
    component_backtest = json.loads(COMPONENT_BACKTEST_METRICS.read_text(encoding="utf-8"))
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    if not 0.0 <= raw_weight <= 1.0:
        raise ValueError("Historically selected raw-component weight must be in [0, 1]")
    weights = {
        "residual": 0.50,
        "component_anchored": 0.50 * (1.0 - raw_weight),
        "component_raw": 0.50 * raw_weight,
    }
    return (
        {
            "residual": residual_metrics,
            "component_anchored": anchored_metrics,
            "component_raw": raw_metrics,
        },
        {
            "residual_simulations": residual_simulations,
            "component_simulations": component_simulations,
            "residual_seed": residual_seed,
            "component_seed": component_seed,
            "historically_selected_component_raw_weight": raw_weight,
            "goal_rate_diagnostics": goal_diagnostics,
            "component_diagnostics": component_diagnostics,
            "form_reversion_shadow": form_reversion_shadow,
            "market_goal_rate_shadow": market_shadow,
        },
        weights,
        {
            "residual": residual_totals,
            "component_anchored": anchored_totals,
            "component_raw": raw_totals,
        },
    )


def run_weekly_decision(
    rules: SquadRules,
    *,
    event: int,
    events: tuple[int, ...],
    forecast_path: Path,
    manager_snapshot_path: Path,
    output_path: Path,
    alternatives_per_transfer_count: int = 4,
    max_total_transfers: int = 5,
    max_paid_transfers: int = 2,
    residual_simulations: int = 10_000,
    component_simulations: int = 25_000,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
    component_model_path: Path = COMPONENT_EVENT_MODEL_FILE,
    schedule_receipt_path: Path = CURRENT_SCHEDULE_RECEIPT,
    schedule_fixtures_path: Path = CURRENT_SCHEDULE_FIXTURES,
    created_at: str | None = None,
) -> dict[str, Any]:
    if event not in events:
        raise ValueError("Decision event must be included in the forecast horizon")
    lineage = require_weekly_forecast_lineage(
        forecast_path,
        component_forecast_path,
        events=events,
        component_model_path=component_model_path,
    )
    rows = pq.read_table(forecast_path).to_pylist()
    schedule_receipt = load_schedule_receipt(
        schedule_receipt_path,
        expected_fixtures_path=schedule_fixtures_path,
        expected_snapshot_at=lineage["snapshot_at"],
    )
    horizon_schedule = schedule_horizon_status(
        schedule_receipt,
        events=events,
        team_ids={
            int(row["team_id"])
            for row in rows
            if int(row["event_number"]) in events
        },
    )
    rearrangement_shadow = evaluate_rearrangement_shadow(
        schedule_receipt,
        current_event=event,
        events=events,
    )
    horizon_schedule["rearrangement_shadow"] = rearrangement_shadow
    state, manager_source_label = load_weekly_manager_state(
        manager_snapshot_path,
        forecast_path=forecast_path,
        event=event,
        rules=rules,
        forecast_rows=rows,
    )
    terminal_transfer_curve, terminal_transfer_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers,
        rules=rules,
    )
    actions = generate_weekly_actions(
        state,
        rows,
        rules,
        events=events,
        alternatives_per_transfer_count=alternatives_per_transfer_count,
        max_total_transfers=max_total_transfers,
        max_paid_transfers=max_paid_transfers,
        terminal_free_transfer_curve=terminal_transfer_curve,
    )
    chip_actions = generate_team_chip_shadow_actions(
        state,
        actions,
        rows,
        rules,
        events=events,
    )
    squad_chip_actions = generate_squad_chip_shadow_actions(
        state,
        rows,
        rules,
        events=events,
        alternatives_per_chip=alternatives_per_transfer_count,
        terminal_free_transfer_curve=terminal_transfer_curve,
    )
    all_actions = [*actions, *chip_actions, *squad_chip_actions]
    (
        all_scenario_metrics,
        diagnostics,
        scenario_weights,
        scenario_totals,
    ) = simulate_production_weekly_scenarios(
        all_actions,
        rows,
        events=events,
        residual_simulations=residual_simulations,
        component_simulations=component_simulations,
        component_forecast_path=component_forecast_path,
    )
    action_ids = {action.action_id for action in actions}
    scenario_metrics = {}
    for name, metrics in all_scenario_metrics.items():
        base_metrics = [metric for metric in metrics if metric.action_id in action_ids]
        base_best = max(metric.mean_net_points for metric in base_metrics)
        scenario_metrics[name] = [
            replace(metric, scenario_regret=base_best - metric.mean_net_points)
            for metric in base_metrics
        ]
    result = synthesize_weekly_decision(
        actions,
        scenario_metrics,
        scenario_weights=scenario_weights,
        created_at=created_at,
    )
    team_chip_columns = len(actions) + len(chip_actions)
    team_chip_totals = {
        name: values[:, :team_chip_columns] for name, values in scenario_totals.items()
    }
    result["chip_shadow"] = synthesize_team_chip_shadow(
        actions,
        chip_actions,
        team_chip_totals,
        scenario_weights=scenario_weights,
        schedule_status=horizon_schedule,
        retention_calibration=(
            load_team_chip_retention_results() if chip_actions else None
        ),
    )
    result["squad_chip_shadow"] = synthesize_squad_chip_shadow(
        actions,
        squad_chip_actions,
        all_actions,
        scenario_totals,
        scenario_weights=scenario_weights,
        schedule_status=horizon_schedule,
        retention_calibration=(
            load_squad_chip_retention_results() if squad_chip_actions else None
        ),
    )
    player_names = {
        int(row["element"]): str(row.get("player_name") or f"#{row['element']}")
        for row in rows
        if int(row["event_number"]) == event
    }
    event_rows = {
        int(row["element"]): row
        for row in rows
        if int(row["event_number"]) == event
    }
    for summary in result["action_summaries"]:
        summary["captain_name"] = player_names.get(
            int(summary["captain_player_id"]),
            f"#{summary['captain_player_id']}",
        )
        summary["vice_captain_name"] = player_names.get(
            int(summary["vice_captain_player_id"]),
            f"#{summary['vice_captain_player_id']}",
        )
        for transfer in summary["transfers"]:
            transfer["outgoing_name"] = player_names.get(
                int(transfer["outgoing_player_id"]),
                f"#{transfer['outgoing_player_id']}",
            )
            transfer["incoming_name"] = player_names.get(
                int(transfer["incoming_player_id"]),
                f"#{transfer['incoming_player_id']}",
            )
    for candidate in result["squad_chip_shadow"]["candidates"]:
        candidate["captain_name"] = player_names.get(
            int(candidate["captain_player_id"]),
            f"#{candidate['captain_player_id']}",
        )
        candidate["vice_captain_name"] = player_names.get(
            int(candidate["vice_captain_player_id"]),
            f"#{candidate['vice_captain_player_id']}",
        )
        candidate["selected_player_names"] = [
            player_names.get(int(element), f"#{element}")
            for element in candidate["selected_player_ids"]
        ]
        for transfer in candidate["transfers"]:
            transfer["outgoing_name"] = player_names.get(
                int(transfer["outgoing_player_id"]),
                f"#{transfer['outgoing_player_id']}",
            )
            transfer["incoming_name"] = player_names.get(
                int(transfer["incoming_player_id"]),
                f"#{transfer['incoming_player_id']}",
            )
    relevant_players = sorted(
        {
            int(element)
            for summary in result["action_summaries"]
            for element in (
                *summary["starter_player_ids"],
                *summary["bench_player_ids"],
            )
        }
        | {
            int(element)
            for candidate in result["squad_chip_shadow"]["candidates"]
            for element in candidate["selected_player_ids"]
        }
    )
    result["event_player_forecasts"] = {
        str(element): {
            "element": element,
            "player_name": player_names.get(element, f"#{element}"),
            "position": str(event_rows[element]["position"]),
            "team_id": int(event_rows[element]["team_id"]),
            "expected_points": float(event_rows[element]["expected_points"]),
            "robust_points": float(
                event_rows[element].get("robust_points", event_rows[element]["expected_points"])
            ),
            "p_play": float(event_rows[element].get("p_play", 1.0)),
            "expected_minutes": (
                float(event_rows[element]["expected_minutes"])
                if event_rows[element].get("expected_minutes") is not None
                else None
            ),
        }
        for element in relevant_players
    }
    result["diagnostics"] = diagnostics
    result["diagnostics"]["schedule_rearrangement_shadow"] = rearrangement_shadow
    if DEFAULT_MINI_LEAGUE_CONTEXT.is_file():
        try:
            mini_league_context = json.loads(
                DEFAULT_MINI_LEAGUE_CONTEXT.read_text(encoding="utf-8")
            )
            result["diagnostics"]["mini_league_strategy_shadow"] = (
                evaluate_mini_league_shadow(result, mini_league_context)
            )
        except (OSError, json.JSONDecodeError, MiniLeagueStrategyError) as exc:
            result["diagnostics"]["mini_league_strategy_shadow"] = {
                "status": "blocked_invalid_context",
                "decision_authority": False,
                "operational_recommendation": result["selected_action_id"],
                "reason": str(exc),
            }
    else:
        result["diagnostics"]["mini_league_strategy_shadow"] = {
            "status": "context_missing",
            "decision_authority": False,
            "operational_recommendation": result["selected_action_id"],
            "required_context": str(DEFAULT_MINI_LEAGUE_CONTEXT),
        }
    selected_action = next(
        action for action in actions if action.action_id == result["selected_action_id"]
    )
    event_deadline = next(
        str(row["deadline_time"])
        for row in pq.read_table(CURRENT_FPL_EVENTS).to_pylist()
        if int(row["id"]) == event
    )
    result["diagnostics"]["early_transfer_shadow"] = evaluate_early_transfer_shadow(
        state,
        selected_action,
        deadline_at=event_deadline,
        as_of=str(result["created_at"]),
        selection_stable=bool(result["promotion_gate"]["passed"]),
    )
    result["diagnostics"]["terminal_free_transfer_value"] = terminal_transfer_receipt
    result["forecast_lineage"] = lineage
    result["schedule_lineage"] = {
        "receipt_fingerprint": schedule_receipt["receipt_fingerprint"],
        "schedule_fingerprint": schedule_receipt["schedule_fingerprint"],
        "snapshot_at": schedule_receipt["snapshot_at"],
        "horizon": horizon_schedule,
    }
    result["source_artifacts"] = {
        "forecast": str(forecast_path),
        "forecast_sha256": lineage["direct_forecast_sha256"],
        manager_source_label: str(manager_snapshot_path),
        f"{manager_source_label}_sha256": sha256_file(manager_snapshot_path),
        "component_forecast": str(component_forecast_path),
        "component_forecast_sha256": lineage["component_forecast_sha256"],
        "component_event_model": str(component_model_path),
        "component_event_model_sha256": lineage["component_model_sha256"],
        "schedule_receipt": str(schedule_receipt_path),
        "schedule_receipt_sha256": sha256_file(schedule_receipt_path),
        "schedule_fixtures": str(schedule_fixtures_path),
        "schedule_fixtures_sha256": sha256_file(schedule_fixtures_path),
        "component_backtest": str(COMPONENT_BACKTEST_METRICS),
        "component_backtest_sha256": sha256_file(COMPONENT_BACKTEST_METRICS),
        "goal_model": str(GOAL_MODEL_FILE),
        "goal_model_sha256": sha256_file(GOAL_MODEL_FILE),
        "runtime_rules_sha256": _rules_sha256(rules),
    }
    if TRANSFER_VALUE_ARTIFACT.is_file():
        result["source_artifacts"].update(
            {
                "terminal_transfer_value": str(TRANSFER_VALUE_ARTIFACT),
                "terminal_transfer_value_sha256": sha256_file(TRANSFER_VALUE_ARTIFACT),
            }
        )
    if CHALLENGER_REGISTRY.is_file():
        result["source_artifacts"].update(
            {
                "forecast_challenger_registry": str(CHALLENGER_REGISTRY),
                "forecast_challenger_registry_sha256": sha256_file(
                    CHALLENGER_REGISTRY
                ),
            }
        )
    if PROSPECTIVE_SCOREBOARD.is_file():
        result["source_artifacts"].update(
            {
                "prospective_scoreboard": str(PROSPECTIVE_SCOREBOARD),
                "prospective_scoreboard_sha256": sha256_file(
                    PROSPECTIVE_SCOREBOARD
                ),
            }
        )
    mini_league_shadow = result["diagnostics"].get(
        "mini_league_strategy_shadow", {}
    )
    if DEFAULT_MINI_LEAGUE_CONTEXT.is_file() and mini_league_shadow.get("status") in {
        "ready_shadow",
        "not_applicable_early_season",
    }:
        result["source_artifacts"].update(
            {
                "mini_league_context": str(DEFAULT_MINI_LEAGUE_CONTEXT),
                "mini_league_context_sha256": sha256_file(
                    DEFAULT_MINI_LEAGUE_CONTEXT
                ),
            }
        )
    reversion_shadow = result["diagnostics"].get("form_reversion_shadow", {})
    if (
        reversion_shadow.get("status") == "ready_shadow"
        and reversion_shadow.get("artifact")
        and reversion_shadow.get("artifact_sha256")
    ):
        result["source_artifacts"].update(
            {
                "form_reversion_shadow": reversion_shadow["artifact"],
                "form_reversion_shadow_sha256": reversion_shadow[
                    "artifact_sha256"
                ],
            }
        )
    market_shadow = result["diagnostics"].get("market_goal_rate_shadow", {})
    if market_shadow.get("status") == "ready_shadow":
        result["source_artifacts"].update(
            {
                "market_goal_rate_shadow": str(CURRENT_MARKET_RATES),
                "market_goal_rate_shadow_sha256": market_shadow["artifact_sha256"],
                "market_goal_rate_receipt": str(CURRENT_MARKET_RECEIPT),
                "market_goal_rate_receipt_sha256": market_shadow["receipt_sha256"],
            }
        )
    timing_shadow = result["diagnostics"].get("early_transfer_shadow", {})
    if timing_shadow.get("status") == "ready_shadow":
        result["source_artifacts"].update(
            {
                "early_transfer_market_features": timing_shadow[
                    "feature_artifact"
                ],
                "early_transfer_market_features_sha256": timing_shadow[
                    "feature_artifact_sha256"
                ],
                "early_transfer_market_feature_receipt": timing_shadow[
                    "feature_receipt"
                ],
                "early_transfer_market_feature_receipt_sha256": timing_shadow[
                    "feature_receipt_sha256"
                ],
            }
        )
    rearrangement = result["diagnostics"].get("schedule_rearrangement_shadow", {})
    if rearrangement.get("status") == "ready_shadow":
        result["source_artifacts"].update(
            {
                "schedule_rearrangement_model": rearrangement["model_path"],
                "schedule_rearrangement_model_sha256": rearrangement["model_sha256"],
                "schedule_rearrangement_episodes": rearrangement["episode_path"],
                "schedule_rearrangement_episodes_sha256": rearrangement[
                    "episode_sha256"
                ],
            }
        )
    squad_chip_retention = result.get("squad_chip_shadow", {}).get(
        "retention_calibration"
    )
    if squad_chip_retention and squad_chip_retention.get("receipt_path"):
        result["source_artifacts"].update(
            {
                "squad_chip_retention_replay": squad_chip_retention["receipt_path"],
                "squad_chip_retention_replay_sha256": squad_chip_retention[
                    "receipt_sha256"
                ],
            }
        )
    team_chip_retention = result.get("chip_shadow", {}).get("retention_calibration")
    if team_chip_retention and team_chip_retention.get("receipt_path"):
        result["source_artifacts"].update(
            {
                "team_chip_retention_replay": team_chip_retention["receipt_path"],
                "team_chip_retention_replay_sha256": team_chip_retention[
                    "receipt_sha256"
                ],
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return result
