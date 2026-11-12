from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.weekly_actions import generate_weekly_actions
from fplagent_engine.weekly_continuation import ContinuationScenario, evaluate_weekly_continuation


def _setup():
    rows = _rows()
    actions = generate_weekly_actions(
        _state(),
        rows,
        _rules(),
        events=(2, 3),
        max_total_transfers=1,
        alternatives_per_transfer_count=1,
    )
    return rows, actions, next(a for a in actions if a.route_type == "roll")


def test_forecast_fingerprint_handles_live_arrow_types_and_all_role_metadata():
    from fplagent_engine.weekly_continuation import _fingerprint

    row = {
        "element": 3,
        "event_number": 4,
        "market_price": Decimal(50),
        "snapshot_at": datetime(2026, 9, 9, tzinfo=UTC),
        "missing_feature": float("nan"),
        "p_90_or_more": 0.9,
        "nested": [Decimal("0.5")],
    }
    original = _fingerprint([row], "expected_points")
    assert original == _fingerprint([dict(row)], "expected_points")
    assert original != _fingerprint([dict(row, p_90_or_more=0.1)], "expected_points")


def test_no_future_transfer_reproduces_fixed_horizon_without_double_counting():
    rows, actions, roll = _setup()
    result = evaluate_weekly_continuation(
        actions,
        rows,
        _rules(),
        events=(2, 3),
        selected_action_id=roll.action_id,
        maximum_future_transfers=0,
    )
    originals = {a.action_id: a for a in actions}
    assert result["complete_root_comparison"]
    assert not result["decision_authority"]
    for row in result["candidates"]:
        assert row["weighted_value"] == pytest.approx(originals[row["action_id"]].decision_utility)
        assert row["branches"][0]["recourse_uplift"] == pytest.approx(0)


def test_recourse_can_use_saved_transfers_and_accounts_for_hits():
    rows, actions, roll = _setup()
    result = evaluate_weekly_continuation(
        actions,
        rows,
        _rules(),
        events=(2, 3),
        selected_action_id=roll.action_id,
    )
    by_root = {r["action_id"]: r for r in result["candidates"]}
    branch = by_root[roll.action_id]["branches"][0]
    assert branch["next_free_transfers_before_action"] == 2
    assert len(branch["transfers"]) == 2
    assert branch["next_incremental_points_cost"] == 0
    assert branch["recourse_uplift"] > 0
    for row in result["candidates"]:
        branch = row["branches"][0]
        count = len(branch["transfers"])
        assert branch["next_incremental_points_cost"] == 4 * max(
            0, count - branch["next_free_transfers_before_action"]
        )
        assert branch["bank_after_action"] >= 0


def test_scenarios_reprice_exact_sales_and_choose_only_after_observation():
    rows, actions, roll = _setup()
    future = [dict(r) for r in rows if r["event_number"] == 3]
    down = [dict(r, market_price=40 if r["element"] == 3 else r["market_price"]) for r in future]
    result = evaluate_weekly_continuation(
        actions,
        rows,
        _rules(),
        events=(2, 3),
        selected_action_id=roll.action_id,
        scenarios=[
            ContinuationScenario("flat", 0.5, 3, future),
            ContinuationScenario("sale_down", 0.5, 3, down),
        ],
    )
    by_root = {r["action_id"]: r for r in result["candidates"]}
    flat, down_branch = by_root[roll.action_id]["branches"]
    assert flat["transfers"] == down_branch["transfers"]
    assert down_branch["bank_after_action"] == flat["bank_after_action"] - 10
    for row in result["candidates"]:
        assert row["weighted_value"] == pytest.approx(
            sum(0.5 * branch["root_value_with_recourse"] for branch in row["branches"])
        )
    assert (
        result["shadow_preference"]
        == max(result["candidates"], key=lambda r: r["weighted_value"])["action_id"]
    )
    assert result["probabilities_calibrated"] is False


def test_missing_player_is_not_silently_dropped():
    rows, actions, roll = _setup()
    future = [dict(r) for r in rows if r["event_number"] == 3 and r["element"] != 1]
    with pytest.raises(ValueError, match="omits a retained player"):
        evaluate_weekly_continuation(
            actions,
            rows,
            _rules(),
            events=(2, 3),
            selected_action_id=roll.action_id,
            scenarios=[ContinuationScenario("missing", 1, 3, future)],
        )


def test_future_roster_prices_cannot_silently_override_next_deadline_prices():
    rows, actions, roll = _setup()
    extended = rows + [dict(r, event_number=4) for r in rows if r["event_number"] == 3]
    future = [dict(r) for r in extended if r["event_number"] > 2]
    future[-1]["market_price"] += 1
    with pytest.raises(ValueError, match="next-deadline prices"):
        evaluate_weekly_continuation(
            actions,
            extended,
            _rules(),
            events=(2, 3, 4),
            selected_action_id=roll.action_id,
            scenarios=[ContinuationScenario("price_drift", 1, 3, future)],
        )


def test_no_recourse_preserves_terminal_transfer_value_once():
    rows = _rows()
    curve = {n: n * 1.5 for n in range(6)}
    actions = generate_weekly_actions(
        _state(),
        rows,
        _rules(),
        events=(2, 3),
        max_total_transfers=1,
        alternatives_per_transfer_count=1,
        terminal_free_transfer_curve=curve,
    )
    roll = next(a for a in actions if a.route_type == "roll")
    result = evaluate_weekly_continuation(
        actions,
        rows,
        _rules(),
        events=(2, 3),
        selected_action_id=roll.action_id,
        maximum_future_transfers=0,
        terminal_free_transfer_curve=curve,
    )
    originals = {a.action_id: a for a in actions}
    for row in result["candidates"]:
        assert row["weighted_value"] == pytest.approx(originals[row["action_id"]].decision_utility)


@pytest.mark.parametrize("case", ["outcome", "probability", "event", "price"])
def test_rejects_leaked_or_invalid_scenario_assumptions(case):
    rows, actions, roll = _setup()
    future = [dict(r) for r in rows if r["event_number"] == 3]
    if case == "outcome":
        future[0]["target_points"] = 18
    if case == "price":
        future[0]["market_price"] = 40.5
    with pytest.raises(ValueError):
        evaluate_weekly_continuation(
            actions,
            rows,
            _rules(),
            events=(2, 3),
            selected_action_id=roll.action_id,
            scenarios=[
                ContinuationScenario(
                    "invalid",
                    0.9 if case == "probability" else 1,
                    4 if case == "event" else 3,
                    future,
                )
            ],
        )


def test_budget_exhaustion_does_not_publish_partial_winner(monkeypatch):
    from fplagent_engine import weekly_continuation

    rows, actions, roll = _setup()
    counter = iter([0, 100, 100])
    monkeypatch.setattr(weekly_continuation.time, "monotonic", lambda: next(counter))
    result = evaluate_weekly_continuation(
        actions,
        rows,
        _rules(),
        events=(2, 3),
        selected_action_id=roll.action_id,
    )
    assert result["status"] == "incomplete_diagnostic"
    assert result["shadow_preference"] is None
    assert result["time_budget_exhausted"]
    assert result["operational_action_id"] == roll.action_id


def test_free_hit_root_requires_separate_persistent_chip_planner():
    from fplagent_engine.season_state import ChipType

    rows, actions, roll = _setup()
    bad = replace(roll, action=replace(roll.action, chip=ChipType.FREE_HIT))
    with pytest.raises(ValueError, match="ordinary roots only"):
        evaluate_weekly_continuation(
            [bad, *[a for a in actions if a != roll]],
            rows,
            _rules(),
            events=(2, 3),
            selected_action_id=roll.action_id,
        )
