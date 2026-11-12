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
    freeze_weekly_player_forecasts,
    frozen_participation_fields,
    require_weekly_forecast_lineage,
    selected_incoming_role_risks,
    summarize_market_shadow_scenario,
    synthesize_squad_chip_shadow,
    synthesize_team_chip_shadow,
    synthesize_weekly_decision,
)
from fplagent_engine.weekly_simulation import ActionPathMetric


@pytest.mark.parametrize(
    ("row", "minutes", "source"),
    [
        ({"expected_minutes": 0.0, "p_play": 0.0}, 0.0, "forecast"),
        ({"p_1_59": 0.1, "p_60_89": 0.2, "p_90_or_more": 0.6}, 71.8, "participation_bin_proxy"),
        ({"p_play": 0.8}, 60.0, "appearance_probability_proxy"),
    ],
)
def test_frozen_participation_retains_minutes_with_honest_provenance(row, minutes, source):
    frozen = frozen_participation_fields(row)
    assert frozen["expected_minutes"] == pytest.approx(minutes)
    assert frozen["minutes_source"] == source
    assert frozen["p_90_or_more"] == row.get("p_90_or_more")


def test_forecast_freeze_covers_unselected_pool_without_outcome_labels(monkeypatch):
    monkeypatch.setattr("fplagent_engine.weekly_decision.sha256_file", lambda _: "calibration")
    monkeypatch.setattr("fplagent_engine.weekly_decision.frozen_score_distribution",
                        lambda row: {"points_pmf": {"0": 1 - row["p_play"], "1": row["p_play"]}})
    rows = {r["element"]: dict(r, target_points=99) for r in _rows() if r["event_number"] == 2}
    frozen = freeze_weekly_player_forecasts(rows)
    assert len(frozen) == len(rows)
    assert set(frozen) == {str(p) for p in rows}
    assert all("target_points" not in r for r in frozen.values())
    assert all(sum(r["points_pmf"].values()) == pytest.approx(1) for r in frozen.values())


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


def test_selected_incoming_role_gate_uses_the_players_forecast_row() -> None:
    action = next(row for row in _actions() if row.route_type == "one_free_transfer")
    incoming = action.action.transfers[0].incoming
    covered_row = {
        "element": incoming.player_id,
        "player_name": "Covered incoming player",
        "position": incoming.position,
        "market_price": incoming.current_price,
        "expected_minutes": 77.2,
        "p_play": 0.944,
        "live_participation_consensus": "not_covered",
    }

    assert selected_incoming_role_risks(action, {incoming.player_id: covered_row}) == []

    missing = selected_incoming_role_risks(action, {})
    assert missing[0]["element"] == incoming.player_id
    assert missing[0]["reasons"] == ["current_event_forecast_missing"]


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
    assert result["version"] == "weekly_decision_synthesis_v4"
    assert result["promotion_gate"]["passed"] is True
    assert result["strongest_rejected"]["action_id"] == roll.action_id
    assert result["objective_tradeoff"]["mean_points_sacrificed_to_robust_ranking"] == 0
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
    assert result["objective_tradeoff"]["mean_points_sacrificed_to_safety_gates"] > 0
    assert result["objective_tradeoff"]["mean_points_sacrificed_to_robust_ranking"] == 0


@pytest.mark.parametrize("rejected_count", [1, 2])
def test_rejected_leaders_do_not_hide_an_admissible_runner_up(rejected_count) -> None:
    base = _actions()
    roll = next(action for action in base if action.route_type == "roll")
    safe = next(action for action in base if action.route_type == "one_free_transfer")
    rejected = [replace(safe, action_id=f"brittle-{i}") for i in range(rejected_count)]
    actions = [roll, safe, *rejected]
    metrics = {
        name: [
            _metric(roll, regret=4, delta=0, low=0, beat=0),
            _metric(safe, regret=3, delta=0.7, low=0.4, beat=0.6),
            *[
                _metric(action, regret=i, delta=1.5, low=-0.5, beat=0.5)
                for i, action in enumerate(rejected)
            ],
        ] for name in ("residual", "component")
    }
    result = synthesize_weekly_decision(actions, metrics,
                                        scenario_weights={"residual": 0.5, "component": 0.5})
    assert result["selected_action_id"] == safe.action_id
    assert result["robust_leader_action_id"] == rejected[0].action_id
    assert result["promotion_gate"]["status"] == "promoted_after_rejections"
    assert result["promotion_gate"]["passed"]
    assert result["selection_audit"]["selected_rank"] == rejected_count + 1
    assert result["selection_audit"]["rejected_higher_ranked_action_ids"] == [
        action.action_id for action in rejected
    ]


def test_role_rejected_leader_allows_safe_alternative() -> None:
    actions = generate_weekly_actions(
        _state(), _rows(), _rules(), events=(2, 3),
        alternatives_per_transfer_count=3, max_total_transfers=1,
    )
    roll = next(action for action in actions if action.route_type == "roll")
    transfers = [a for a in actions if a.route_type == "one_free_transfer"]
    risky = transfers[0]
    risky_in = risky.action.transfers[0].incoming.player_id
    alternatives = generate_weekly_actions(
        _state(), [row for row in _rows() if row["element"] != risky_in], _rules(),
        events=(2, 3), alternatives_per_transfer_count=1, max_total_transfers=1,
    )
    safe = next(a for a in alternatives if a.route_type == "one_free_transfer")
    actions = [risky, safe, roll]
    metrics = {"central": [
        _metric(risky, regret=0, delta=2, low=1, beat=0.7),
        _metric(safe, regret=1, delta=1, low=0.5, beat=0.6),
        _metric(roll, regret=2, delta=0, low=0, beat=0),
    ]}
    event_rows = {row["element"]: row for row in _rows() if row["event_number"] == 2}
    event_rows[risky_in] = {**event_rows[risky_in], "p_play": 0, "expected_minutes": 0}
    result = synthesize_weekly_decision(actions, metrics, scenario_weights={"central": 1},
                                        event_rows=event_rows)
    assert result["selected_action_id"] == safe.action_id
    audit = result["selection_audit"]
    assert audit["incoming_roles_checked"]
    assert not audit["gates_by_action"][risky.action_id]["passed"]
    assert not audit["gates_by_action"][risky.action_id]["checks"][-1]["passed"]


def test_rejected_paid_leader_does_not_hide_safe_free_move() -> None:
    actions = _actions(max_transfers=2)
    hit = next(a for a in actions if a.route_type == "paid_transfer")
    free = next(a for a in actions if a.route_type == "one_free_transfer")
    roll = next(a for a in actions if a.route_type == "roll")
    metrics = {"central": [
        _metric(hit, regret=0, delta=2, low=0.2, beat=0.51),
        _metric(free, regret=1, delta=1, low=0.3, beat=0.61),
        _metric(roll, regret=2, delta=0, low=0, beat=0),
    ]}
    result = synthesize_weekly_decision(actions, metrics, scenario_weights={"central": 1})
    assert result["selected_action_id"] == free.action_id
    assert not result["selection_audit"]["gates_by_action"][hit.action_id]["passed"]


def test_inadmissible_candidates_cannot_change_the_risk_reference_for_safe_moves():
    base = _actions()
    roll = next(a for a in base if a.route_type == "roll")
    move = next(a for a in base if a.route_type == "one_free_transfer")
    a, b, rejected = [replace(move, action_id=key) for key in ("safe-a", "safe-b", "rejected")]
    weights = {"residual": 0.5, "component": 0.5}

    def decide(include_rejected):
        actions = [roll, a, b, *([rejected] if include_rejected else [])]
        deltas = {roll.action_id: (0, 0), a.action_id: (7, 1), b.action_id: (3, 4),
                  rejected.action_id: (1, 100)}
        metrics = {}
        for offset, name in enumerate(weights):
            best = max(deltas[item.action_id][offset] for item in actions)
            metrics[name] = [
                _metric(item, regret=best - deltas[item.action_id][offset],
                        delta=deltas[item.action_id][offset],
                        low=-10 if item == rejected else 0.3, beat=0.65)
                for item in actions
            ]
        return synthesize_weekly_decision(actions, metrics, scenario_weights=weights)

    control, expanded = decide(False), decide(True)
    assert control["selected_action_id"] == a.action_id
    assert not expanded["selection_audit"]["gates_by_action"][rejected.action_id]["passed"]
    assert expanded["selected_action_id"] == control["selected_action_id"]
    assert expanded["selected_robust_metrics"]["robust_regret"] == pytest.approx(
        control["selected_robust_metrics"]["robust_regret"]
    )


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


def test_team_chip_search_compares_every_transfer_chip_pair_to_selected_no_chip_route() -> None:
    state = _state()
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=1,
    )
    selected = next(action for action in base if action.route_type == "roll")
    alternate = next(action for action in base if action.route_type == "one_free_transfer")
    variants = generate_team_chip_shadow_actions(
        state,
        base,
        _rows(),
        _rules(),
        events=(2, 3),
    )
    columns = [*base, *variants]
    index = {action.action_id: offset for offset, action in enumerate(columns)}
    totals = np.zeros((2_000, len(columns)))
    totals[:, index[selected.action_id]] = 100.0
    totals[:, index[alternate.action_id]] = 90.0
    for variant in variants:
        parent_total = 100.0 if variant.parent_action_id == selected.action_id else 90.0
        own_route_uplift = (
            4.0 if variant.parent_action_id == selected.action_id else 5.0
        )
        totals[:, index[variant.action_id]] = parent_total + own_route_uplift
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
        comparison_action_id=selected.action_id,
    )
    bench_boosts = [
        row for row in result["candidates"] if row["chip"] == ChipType.BENCH_BOOST.value
    ]
    winner = max(bench_boosts, key=lambda row: row["weighted_delta_to_comparison_ordinary"])
    misleading_own_route_leader = next(
        row for row in bench_boosts if row["parent_action_id"] == alternate.action_id
    )

    assert winner["parent_action_id"] == selected.action_id
    assert winner["weighted_delta_to_comparison_ordinary"] == 4.0
    assert misleading_own_route_leader["scenario_metrics"]["residual"][
        "mean_current_chip_uplift"
    ] == 5.0
    assert misleading_own_route_leader["weighted_delta_to_comparison_ordinary"] == -5.0


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
