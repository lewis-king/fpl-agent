from __future__ import annotations

import json
from types import SimpleNamespace

import pyarrow as pa

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file
from fplagent_data.market_telemetry import FEATURE_SCHEMA
from fplagent_engine.early_transfer import evaluate_early_transfer_shadow
from fplagent_engine.season_state import (
    EventStatus,
    Lineup,
    ManagerState,
    MarketPlayer,
    PlayerHolding,
    Transfer,
    default_chip_inventory,
)


def _state(*, bank: int = 10) -> ManagerState:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    squad = tuple(
        PlayerHolding(
            player_id=index + 1,
            position=position,
            team_id=(index // 3) + 1,
            purchase_price=50,
            current_price=50,
            selling_price=50,
        )
        for index, position in enumerate(positions)
    )
    return ManagerState(
        season="2026-27",
        event=1,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=squad,
        bank=bank,
        free_transfers=1,
        chips=default_chip_inventory(),
        lineup=Lineup(
            starters=(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15),
            bench_order=(2, 6, 7, 12),
            captain=13,
            vice_captain=8,
        ),
    )


def _feature(element: int, *, progress: float) -> dict:
    return {
        "season": "2026-27",
        "feature_at": "2026-08-08T12:00:00+00:00",
        "element": element,
        "player_name": f"Player {element}",
        "team": "TST",
        "position": "DEF",
        "data_points": 3,
        "span_hours": 0.5,
        "interval_hours": 0.25,
        "now_cost": 50 if element == 3 else 60,
        "cost_change_event": 0,
        "price_change_percent": progress,
        "selected_by_percent": 10.0,
        "ownership_delta_pp_per_hour": 0.1,
        "transfers_in_interval": 25,
        "transfers_out_interval": 1,
        "net_transfers_interval": 24,
        "net_transfer_velocity_per_hour": 96.0,
        "gross_transfer_velocity_per_hour": 104.0,
        "net_velocity_per_ownership_point": 9.6,
        "net_transfer_acceleration_per_hour2": 2.0,
        "hours_to_uk_midnight": 11.0,
        "status": "a",
        "chance_this_round": 100,
        "news": "",
    }


def _artifacts(tmp_path, *, feature_at: str = "2026-08-08T12:00:00+00:00"):
    feature_path = tmp_path / "features.parquet"
    rows = [_feature(3, progress=-101.0), _feature(16, progress=105.0)]
    for row in rows:
        row["feature_at"] = feature_at
    write_table(pa.Table.from_pylist(rows, schema=FEATURE_SCHEMA), feature_path)
    receipt_path = tmp_path / "features.json"
    receipt_path.write_text(
        json.dumps(
            {
                "status": "ready",
                "feature_at": feature_at,
                "output_sha256": sha256_file(feature_path),
            }
        ),
        encoding="utf-8",
    )
    return feature_path, receipt_path


def _selected_action(*, with_transfer: bool = True, bank: int = 0):
    transfers = (
        (Transfer(3, MarketPlayer(16, "DEF", 6, 60)),) if with_transfer else ()
    )
    return SimpleNamespace(
        action_id="test-action",
        route_type="one_free_transfer" if transfers else "roll",
        action=SimpleNamespace(transfers=transfers),
        outcome=SimpleNamespace(gameweek=SimpleNamespace(bank=bank)),
    )


def test_threshold_stress_can_flag_a_route_as_priced_out_without_authority(
    tmp_path,
) -> None:
    feature_path, receipt_path = _artifacts(tmp_path)

    result = evaluate_early_transfer_shadow(
        _state(),
        _selected_action(),
        deadline_at="2026-08-10T17:30:00+00:00",
        as_of="2026-08-08T12:10:00+00:00",
        selection_stable=True,
        feature_path=feature_path,
        feature_receipt_path=receipt_path,
        outcome_receipt_path=tmp_path / "outcomes.json",
    )

    assert result["status"] == "ready_shadow"
    assert result["threshold_stress_cost"] == 2
    assert result["bank_after_threshold_stress"] == -2
    assert result["route_blocked_by_threshold_stress"] is True
    assert result["shadow_preference"] == "move_now_candidate"
    assert result["operational_recommendation"] == "wait"
    assert result["decision_authority"] is False


def test_price_stress_is_not_applied_when_deadline_precedes_next_update(tmp_path) -> None:
    feature_path, receipt_path = _artifacts(tmp_path)

    result = evaluate_early_transfer_shadow(
        _state(),
        _selected_action(),
        deadline_at="2026-08-08T18:30:00+00:00",
        as_of="2026-08-08T12:10:00+00:00",
        selection_stable=True,
        feature_path=feature_path,
        feature_receipt_path=receipt_path,
        outcome_receipt_path=tmp_path / "outcomes.json",
    )

    assert result["status"] == "ready_shadow"
    assert result["price_change_before_deadline"] is False
    assert result["threshold_stress_cost"] == 0
    assert result["route_blocked_by_threshold_stress"] is False
    assert result["shadow_preference"] == "wait"


def test_stale_market_features_fail_closed(tmp_path) -> None:
    feature_path, receipt_path = _artifacts(
        tmp_path,
        feature_at="2026-08-08T10:00:00+00:00",
    )

    result = evaluate_early_transfer_shadow(
        _state(),
        _selected_action(),
        deadline_at="2026-08-10T17:30:00+00:00",
        as_of="2026-08-08T12:10:00+00:00",
        selection_stable=True,
        feature_path=feature_path,
        feature_receipt_path=receipt_path,
        outcome_receipt_path=tmp_path / "outcomes.json",
    )

    assert result["status"] == "not_ready"
    assert "minutes old" in result["reason"]
    assert result["operational_recommendation"] == "wait"


def test_roll_route_does_not_require_market_telemetry(tmp_path) -> None:
    result = evaluate_early_transfer_shadow(
        _state(),
        _selected_action(with_transfer=False),
        deadline_at="2026-08-10T17:30:00+00:00",
        as_of="2026-08-08T12:10:00+00:00",
        selection_stable=True,
        feature_path=tmp_path / "missing.parquet",
        feature_receipt_path=tmp_path / "missing.json",
        outcome_receipt_path=tmp_path / "outcomes.json",
    )

    assert result["status"] == "not_applicable"
    assert result["operational_recommendation"] == "wait"
    assert result["decision_authority"] is False
