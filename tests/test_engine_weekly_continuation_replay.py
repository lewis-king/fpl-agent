from copy import deepcopy
from dataclasses import replace

import highspy
import pytest
from test_engine_horizon_decay_replay import _coefficients
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine import (
    weekly_actions,
    weekly_continuation,
)
from fplagent_engine import (
    weekly_continuation_replay as replay,
)
from fplagent_engine.weekly_actions import WeeklySolveError, generate_weekly_actions


def _inputs():
    forecasts, features, forecast_by_event, feature_by_key = [], [], {}, {}
    fixtures = {}
    for season in ("2023-24", "2024-25", "2025-26"):
        for event in range(1, 5):
            base = [
                dict(
                    r,
                    season=season,
                    event_number=event,
                    player_name=f"Player {r['element']}",
                    target_points=int(r["expected_points"]),
                )
                for r in _rows()
                if r["event_number"] == 2
            ]
            forecast_by_event[(season, event)] = base
            forecasts.extend(base)
            for row in base:
                feature = {
                    **row,
                    "fixture_count": 1,
                    "home_fraction": 0.5,
                    "fixture_difficulty": 3,
                    "target_minutes": 90,
                }
                features.append(feature)
                feature_by_key[(season, event, int(row["element"]))] = feature
        fixtures[(season, 1)] = [
            {
                "event": event,
                "team_h": team,
                "team_a": team + 1,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
            }
            for event in range(1, 7)
            for team in range(1, 21, 2)
        ]
    return {
        "forecasts": forecasts,
        "features": features,
        "forecast_by_event": forecast_by_event,
        "feature_by_key": feature_by_key,
        "fixture_by_snapshot": fixtures,
        "available_snapshots": {s: [1] for s in ("2023-24", "2024-25", "2025-26")},
    }


def test_decision_cannot_see_future_prices_predictions_fixtures_or_any_outcomes():
    inputs = _inputs()
    config = replay.ReplayConfig(end_event=2, horizon=3)
    before, _, _ = replay.prepare_deadline(inputs, "2024-25", 2, config, _coefficients())
    changed = deepcopy(inputs)
    for event in (2, 3, 4):
        for row in changed["forecast_by_event"][("2024-25", event)]:
            row["target_points"] = 100
            changed["feature_by_key"][("2024-25", event, row["element"])]["target_minutes"] = 0
            if event > 2:
                row.update(market_price=200, expected_points=500, p_play=0)
    changed["available_snapshots"]["2024-25"].append(3)
    changed["fixture_by_snapshot"][("2024-25", 3)] = []
    after, outcomes, lineage = replay.prepare_deadline(
        changed, "2024-25", 2, config, _coefficients()
    )
    assert before == after
    assert all(r["target_points"] == 100 for r in outcomes)
    assert lineage["snapshot_event"] == 1
    assert {r["event_number"] for r in after} == {2, 3, 4}  # Not truncated at scoring-window end.
    assert not any(k.startswith(("target_", "realized_")) for r in after for k in r)


@pytest.mark.parametrize("field", ["target_points", "target_minutes"])
def test_missing_actual_is_not_scored_as_zero(field):
    inputs = _inputs()
    if field == "target_points":
        inputs["forecast_by_event"][("2024-25", 2)][0][field] = None
    else:
        inputs["feature_by_key"][("2024-25", 2, 1)][field] = None
    with pytest.raises(ValueError, match="Missing actual"):
        replay.prepare_deadline(inputs, "2024-25", 2, replay.ReplayConfig(), _coefficients())


def test_fixture_response_fit_never_sees_test_season(monkeypatch):
    seen = {}

    def fit(forecasts, features):
        seen["forecast"] = {r["season"] for r in forecasts}
        seen["features"] = {r["season"] for r in features}
        return _coefficients()

    monkeypatch.setattr(replay, "_fixture_response_coefficients", fit)
    _, training = replay.prefix_coefficients(_inputs(), "2024-25")
    assert training == ["2023-24"]
    assert seen == {"forecast": {"2023-24"}, "features": {"2023-24"}}


def test_same_initial_squad_exact_ft_carry_and_realized_net_points(monkeypatch):
    monkeypatch.setattr(replay, "_historical_rules", lambda season: _rules())
    monkeypatch.setattr(replay, "_fixture_response_coefficients", lambda *args: _coefficients())
    result = replay.paired_season(_inputs(), "2024-25", replay.ReplayConfig(end_event=3, horizon=2))
    left, right = result["paths"].values()
    assert left["events"][0] == right["events"][0]
    for path in (left, right):
        assert path["events"][0]["free_transfers_before"] == 0
        assert path["events"][1]["free_transfers_before"] == 1
        assert path["net_points"] == sum(
            r["gross_points"] - r["points_cost"] for r in path["events"]
        )
        for previous, current in zip(path["events"], path["events"][1:]):
            assert previous["free_transfers_after"] == current["free_transfers_before"]
            assert current["points_cost"] == 4 * max(
                0, len(current["transfers"]) - current["free_transfers_before"]
            )
            assert current["bank_after"] >= 0
    assert result["net_points_delta"] == right["net_points"] - left["net_points"]
    assert set(result["terminal_curve"].values()) == {0}


def test_repricing_uses_selling_profit_floor_and_rejects_missing_identity(monkeypatch):
    monkeypatch.setattr(replay, "_historical_rules", lambda season: _rules())
    state = _state()
    rows = [dict(r) for r in _rows() if r["event_number"] == state.event]
    player = state.squad[0]
    row = next(r for r in rows if r["element"] == player.player_id)
    row["market_price"] = player.purchase_price + 3
    updated = replay.reprice_state(state, rows)
    assert updated.squad[0].selling_price == player.purchase_price + 1
    row["market_price"] = player.purchase_price - 3
    assert replay.reprice_state(state, rows).squad[0].selling_price == player.purchase_price - 3
    with pytest.raises(ValueError, match="Missing holding"):
        replay.reprice_state(state, [r for r in rows if r is not row])
    row["team_id"] = 99
    club_transfer = replay.reprice_state(state, rows)
    assert club_transfer.squad[0].team_id == 99
    assert club_transfer.squad[0].purchase_price == player.purchase_price
    assert (club_transfer.free_transfers, club_transfer.bank) == (state.free_transfers, state.bank)
    row["position"] = "MID"
    with pytest.raises(ValueError, match="changes position"):
        replay.reprice_state(state, rows)


@pytest.mark.parametrize(
    "status,label",
    [
        (highspy.HighsModelStatus.kInfeasible, "infeasible"),
        (highspy.HighsModelStatus.kTimeLimit, "unresolved"),
    ],
)
def test_search_trace_distinguishes_infeasible_from_timeout(monkeypatch, status, label):
    def failed(*args, **kwargs):
        raise WeeklySolveError(status, "test")

    monkeypatch.setattr(weekly_actions, "_solve_exact_transfer_count", failed)
    search = []
    actions = generate_weekly_actions(
        _state(),
        _rows(),
        _rules(),
        events=(2, 3),
        protect_role_sale_routes=False,
        search_diagnostics=search,
    )
    assert not actions
    assert search and {s["status"] for s in search} == {label}


def test_unsolved_child_search_cannot_declare_a_complete_winner(monkeypatch):
    actions = generate_weekly_actions(
        _state(),
        _rows(),
        _rules(),
        events=(2, 3),
        max_total_transfers=1,
        alternatives_per_transfer_count=1,
    )
    real = weekly_continuation.generate_weekly_actions

    def incomplete(*args, **kwargs):
        children = real(*args, **kwargs)
        kwargs["search_diagnostics"].append({"status": "unresolved", "transfer_count": 2})
        return children

    monkeypatch.setattr(weekly_continuation, "generate_weekly_actions", incomplete)
    result = weekly_continuation.evaluate_weekly_continuation(
        actions,
        _rows(),
        _rules(),
        events=(2, 3),
        selected_action_id=actions[0].action_id,
    )
    assert not result["complete_root_comparison"]
    assert result["shadow_preference"] is None
    assert result["failures"]


@pytest.mark.parametrize(
    "changes",
    [
        {"end_event": 38},
        {"solver_seconds": float("nan")},
        {"seasons": ("2023-24",)},
        {"horizon": 8},
    ],
)
def test_experiment_rejects_unsupported_rule_windows_and_budgets(changes):
    with pytest.raises(ValueError):
        replace(replay.ReplayConfig(), **changes).validate()


def test_research_receipts_cannot_be_overwritten(tmp_path):
    existing = tmp_path / "receipt.json"
    existing.write_text("untouched")
    with pytest.raises(FileExistsError):
        replay.run_replay(existing)
    assert existing.read_text() == "untouched"
