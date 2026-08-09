from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_data.http import sha256_file
from fplagent_engine.season_state import ChipType
from fplagent_engine.weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from fplagent_engine.weekly_decision import (
    require_weekly_forecast_lineage,
    summarize_market_shadow_scenario,
    synthesize_squad_chip_shadow,
    synthesize_team_chip_shadow,
    synthesize_weekly_decision,
)
from fplagent_engine.weekly_simulation import ActionPathMetric


def _lineage_artifacts(tmp_path: Path) -> tuple[Path, Path, Path, list[dict], list[dict]]:
    direct_path = tmp_path / "direct.parquet"
    component_path = tmp_path / "component.parquet"
    model_path = tmp_path / "component-model.joblib"
    snapshot_at = "2026-08-07T12:00:00+00:00"
    direct_rows = [
        {
            "event_number": event,
            "element": element,
            "expected_points": 4.0,
            "snapshot_at": snapshot_at,
        }
        for event in (2, 3)
        for element in (101, 102)
    ]
    pq.write_table(pa.Table.from_pylist(direct_rows), direct_path)
    model_path.write_bytes(b"component-model-v1")
    component_rows = [
        {
            "event_number": row["event_number"],
            "element": row["element"],
            "snapshot_at": snapshot_at,
            "direct_forecast_sha256": sha256_file(direct_path),
            "component_model_sha256": sha256_file(model_path),
            "component_model_version": "component-v1",
            "component_model_created_at": "2026-08-07T11:00:00+00:00",
            "component_forecast_created_at": "2026-08-07T12:01:00+00:00",
        }
        for row in direct_rows
    ]
    pq.write_table(pa.Table.from_pylist(component_rows), component_path)
    return direct_path, component_path, model_path, direct_rows, component_rows


def _metric(action, *, regret: float, delta: float, low: float, beat: float):
    return ActionPathMetric(
        action_id=action.action_id,
        route_type=action.route_type,
        mean_net_points=100.0 + delta,
        median_net_points=100.0 + delta,
        p10_net_points=80.0,
        p90_net_points=120.0,
        downside_cvar10=75.0,
        standard_deviation=10.0,
        mean_rank=1.5,
        top_action_probability=0.5,
        mean_delta_to_roll=delta,
        delta_to_roll_95ci_low=low,
        delta_to_roll_95ci_high=delta + 0.2,
        beat_roll_probability=beat,
        tie_roll_probability=0.0,
        incremental_points_cost=action.incremental_points_cost,
        total_points_cost=action.total_points_cost,
        scenario_regret=regret,
    )


def _actions(*, free_transfers: int = 1, max_transfers: int = 1):
    return generate_weekly_actions(
        _state(free_transfers=free_transfers),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=max_transfers,
        max_paid_transfers=1,
    )


def test_market_action_shadow_summary_detects_changed_leader() -> None:
    actions = _actions()
    roll = next(action for action in actions if action.route_type == "roll")
    transfer = next(action for action in actions if action.route_type == "one_free_transfer")
    incumbent = [
        _metric(roll, regret=0.0, delta=1.0, low=0.0, beat=0.0),
        _metric(transfer, regret=1.0, delta=0.0, low=0.0, beat=0.0),
    ]
    market = [
        _metric(roll, regret=1.0, delta=0.0, low=0.0, beat=0.0),
        _metric(transfer, regret=0.0, delta=2.0, low=0.0, beat=0.0),
    ]

    summary = summarize_market_shadow_scenario(incumbent, market)

    assert summary["incumbent_leader"] == roll.action_id
    assert summary["market_leader"] == transfer.action_id
    assert summary["leader_changed"] is True


def test_stable_free_transfer_is_promoted_over_roll() -> None:
    actions = _actions()
    roll = next(action for action in actions if action.route_type == "roll")
    transfer = next(action for action in actions if action.route_type == "one_free_transfer")
    scenario_metrics = {
        name: [
            _metric(roll, regret=1.0, delta=0.0, low=0.0, beat=0.0),
            _metric(transfer, regret=0.0, delta=1.0, low=0.4, beat=0.62),
        ]
        for name in ("residual", "component_anchored", "component_raw")
    }

    result = synthesize_weekly_decision(
        actions,
        scenario_metrics,
        scenario_weights={
            "residual": 0.5,
            "component_anchored": 0.45,
            "component_raw": 0.05,
        },
    )

    assert result["selected_action_id"] == transfer.action_id
    assert result["version"] == "weekly_decision_synthesis_v3"
    assert result["promotion_gate"]["passed"] is True
    assert result["strongest_rejected"]["action_id"] == roll.action_id
    summaries = {row["action_id"]: row for row in result["action_summaries"]}
    assert summaries[transfer.action_id]["transfer_count"] == 1
    assert summaries[transfer.action_id]["captain_player_id"] in summaries[transfer.action_id][
        "starter_player_ids"
    ]
    assert result["scenario_metrics_by_action"]["residual"][transfer.action_id][
        "mean_delta_to_roll"
    ] == 1.0
    assert summaries[transfer.action_id]["event_lineups"][0]["event"] == 2
    assert summaries[transfer.action_id]["event_lineups"][0]["projected_points"] > 0.0


def test_ambiguous_paid_transfer_falls_back_to_roll() -> None:
    actions = _actions(free_transfers=0, max_transfers=1)
    roll = next(action for action in actions if action.route_type == "roll")
    hit = next(action for action in actions if action.route_type == "paid_transfer")
    central = [
        _metric(roll, regret=1.0, delta=0.0, low=0.0, beat=0.0),
        _metric(hit, regret=0.0, delta=0.4, low=-0.2, beat=0.52),
    ]
    raw_hit = replace(_metric(hit, regret=0.0, delta=-0.1, low=-0.5, beat=0.48))
    scenario_metrics = {
        "residual": central,
        "component_anchored": central,
        "component_raw": [
            _metric(roll, regret=1.0, delta=0.0, low=0.0, beat=0.0),
            raw_hit,
        ],
    }

    result = synthesize_weekly_decision(
        actions,
        scenario_metrics,
        scenario_weights={
            "residual": 0.5,
            "component_anchored": 0.45,
            "component_raw": 0.05,
        },
    )

    assert result["robust_leader_action_id"] == hit.action_id
    assert result["selected_action_id"] == roll.action_id
    assert result["promotion_gate"]["status"] == "roll_due_to_uncertainty"


def test_roll_can_be_the_robust_leader_without_a_transfer_gate() -> None:
    actions = _actions()
    roll = next(action for action in actions if action.route_type == "roll")
    transfer = next(action for action in actions if action.route_type == "one_free_transfer")
    scenario_metrics = {
        "central": [
            _metric(roll, regret=0.0, delta=0.0, low=0.0, beat=0.0),
            _metric(transfer, regret=2.0, delta=-2.0, low=-2.5, beat=0.2),
        ]
    }

    result = synthesize_weekly_decision(
        actions,
        scenario_metrics,
        scenario_weights={"central": 1.0},
    )

    assert result["selected_action_id"] == roll.action_id
    assert result["promotion_gate"]["status"] == "roll_is_robust_leader"


def test_weekly_forecast_lineage_accepts_one_exact_generation(tmp_path: Path) -> None:
    direct, component, model, direct_rows, _ = _lineage_artifacts(tmp_path)

    lineage = require_weekly_forecast_lineage(
        direct,
        component,
        events=(2, 3),
        component_model_path=model,
    )

    assert lineage["direct_forecast_sha256"] == sha256_file(direct)
    assert lineage["component_model_sha256"] == sha256_file(model)
    assert lineage["rows"] == len(direct_rows)
    assert lineage["events"] == [2, 3]


def test_weekly_forecast_lineage_rejects_changed_direct_bytes(tmp_path: Path) -> None:
    direct, component, model, direct_rows, _ = _lineage_artifacts(tmp_path)
    direct_rows[0]["expected_points"] = 9.0
    pq.write_table(pa.Table.from_pylist(direct_rows), direct)

    with pytest.raises(ValueError, match="exact direct forecast bytes"):
        require_weekly_forecast_lineage(
            direct,
            component,
            events=(2, 3),
            component_model_path=model,
        )


def test_weekly_forecast_lineage_rejects_incomplete_component_grid(tmp_path: Path) -> None:
    direct, component, model, _, component_rows = _lineage_artifacts(tmp_path)
    pq.write_table(pa.Table.from_pylist(component_rows[:-1]), component)

    with pytest.raises(ValueError, match="keys do not exactly match"):
        require_weekly_forecast_lineage(
            direct,
            component,
            events=(2, 3),
            component_model_path=model,
        )


def test_weekly_forecast_lineage_rejects_changed_component_model(tmp_path: Path) -> None:
    direct, component, model, _, _ = _lineage_artifacts(tmp_path)
    model.write_bytes(b"component-model-v2")

    with pytest.raises(ValueError, match="exact component model bytes"):
        require_weekly_forecast_lineage(
            direct,
            component,
            events=(2, 3),
            component_model_path=model,
        )


def test_team_chip_shadow_requires_complete_half_and_retention_adjusted_edge() -> None:
    state = _state()
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    raw_variants = generate_team_chip_shadow_actions(
        state,
        base,
        _rows(),
        _rules(),
        events=(2, 3),
    )
    variants = [
        replace(variant, chip_horizon_complete=True, retained_chip_proxy_value=5.0)
        for variant in raw_variants
    ]
    columns = [base[0], *variants]
    totals = np.full((2_000, len(columns)), 100.0)
    for index, action in enumerate(columns):
        if action.action.chip == ChipType.BENCH_BOOST:
            totals[:, index] += 10.0
        elif action.action.chip == ChipType.TRIPLE_CAPTAIN:
            totals[:, index] += 6.0
    scenario_totals = {
        "residual": totals,
        "component_anchored": totals,
        "component_raw": totals,
    }
    weights = {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05}

    passed = synthesize_team_chip_shadow(
        base,
        variants,
        scenario_totals,
        scenario_weights=weights,
        schedule_status={"fully_confirmed": True, "issues": []},
    )
    retained = synthesize_team_chip_shadow(
        base,
        raw_variants,
        scenario_totals,
        scenario_weights=weights,
        schedule_status={"fully_confirmed": True, "issues": []},
    )

    assert passed["status"] == "shadow_gate_passed_not_promoted"
    assert passed["shadow_preference"]["chip"] == ChipType.BENCH_BOOST.value
    assert passed["operational_recommendation"] == "no_chip"
    assert retained["status"] == "retain_chip"
    assert any(
        check["name"] == "chip-half horizon complete" and not check["passed"]
        for check in retained["candidates"][0]["checks"]
    )


def test_team_chip_shadow_is_blocked_by_unresolved_schedule() -> None:
    state = _state()
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    variants = [
        replace(variant, chip_horizon_complete=True, retained_chip_proxy_value=0.0)
        for variant in generate_team_chip_shadow_actions(
            state, base, _rows(), _rules(), events=(2, 3)
        )
    ]
    totals = np.full((2_000, 1 + len(variants)), 100.0)
    totals[:, 1:] += 10.0
    scenario_totals = {
        "residual": totals,
        "component_anchored": totals,
        "component_raw": totals,
    }

    result = synthesize_team_chip_shadow(
        base,
        variants,
        scenario_totals,
        scenario_weights={"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        schedule_status={
            "fully_confirmed": False,
            "issues": ["one postponed fixture is unassigned"],
        },
    )

    assert result["status"] == "retain_chip"
    assert all(not candidate["shadow_gate_passed"] for candidate in result["candidates"])
    assert any(
        check["name"] == "schedule horizon confirmed" and not check["passed"]
        for check in result["candidates"][0]["checks"]
    )


def test_team_chip_shadow_uses_historical_threshold_but_waits_for_promotion() -> None:
    state = _state()
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    variants = [
        replace(variant, chip_horizon_complete=True, retained_chip_proxy_value=0.0)
        for variant in generate_team_chip_shadow_actions(
            state, base, _rows(), _rules(), events=(2, 3)
        )
    ]
    totals = np.full((2_000, 1 + len(variants)), 100.0)
    totals[:, 1:] += 20.0
    scenarios = {
        "residual": totals,
        "component_anchored": totals,
        "component_raw": totals,
    }

    result = synthesize_team_chip_shadow(
        base,
        variants,
        scenarios,
        scenario_weights={"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        schedule_status={"fully_confirmed": True, "issues": []},
        retention_calibration={
            "verdict": "PASS_HISTORICAL_SHADOW",
            "historical_gate": {"passed": True},
            "promotion_gate": {"passed": False},
            "retained_value_thresholds": {"bench_boost": 8.0, "triple_captain": 6.0},
            "receipt_path": "retention.json",
            "receipt_sha256": "abc",
        },
    )

    assert result["status"] == "retain_chip"
    by_chip = {row["chip"]: row for row in result["candidates"]}
    assert by_chip["bench_boost"]["retained_chip_proxy_value"] == 8.0
    assert by_chip["triple_captain"]["retained_chip_proxy_value"] == 6.0
    assert all(not row["shadow_gate_passed"] for row in result["candidates"])
    assert any(
        check["name"] == "retention policy promoted" and not check["passed"]
        for check in result["candidates"][0]["checks"]
    )


def test_squad_chip_shadow_exposes_raw_edge_but_cannot_spend_uncalibrated_chip() -> None:
    state = _state(bank=20)
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    variants = generate_squad_chip_shadow_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_chip=1,
    )
    evaluated = [*base, *variants]
    totals = np.full((2_000, len(evaluated)), 100.0)
    for index, action in enumerate(evaluated):
        if action.action.chip == ChipType.WILDCARD:
            totals[:, index] += 12.0
        elif action.action.chip == ChipType.FREE_HIT:
            totals[:, index] += 8.0
    scenario_totals = {
        "residual": totals,
        "component_anchored": totals,
        "component_raw": totals,
    }

    result = synthesize_squad_chip_shadow(
        base,
        variants,
        evaluated,
        scenario_totals,
        scenario_weights={"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05},
        schedule_status={"fully_confirmed": True, "issues": []},
    )

    assert result["status"] == "retain_chip_uncalibrated_option_value"
    assert result["shadow_preference"]["chip"] == ChipType.WILDCARD.value
    assert result["operational_recommendation"] == "no_chip"
    assert result["decision_authority"] is False
    assert result["candidates"][0]["weighted_raw_delta_to_best_ordinary"] == 12.0
    assert all(not candidate["shadow_gate_passed"] for candidate in result["candidates"])
    assert any(
        check["name"] == "retained chip option value calibrated"
        and not check["passed"]
        for check in result["candidates"][0]["checks"]
    )
