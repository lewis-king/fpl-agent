from __future__ import annotations

from copy import deepcopy

import pytest

from fplagent_engine.manager_state_adapter import (
    ManagerStateInputError,
    manager_state_from_snapshot,
    player_catalog_from_rows,
)
from fplagent_engine.rules import SquadRules
from fplagent_engine.season_state import ChipStatus, ChipType


def _rules() -> SquadRules:
    return SquadRules(
        budget=1000,
        squad_size=15,
        starting_size=11,
        club_limit=3,
        squad_positions={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        minimum_starters={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        maximum_starters={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_free_transfers=5,
        scoring={},
    )


def _catalog() -> dict[int, dict]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return {
        index + 1: {
            "element": index + 1,
            "event_number": 2,
            "position": position,
            "team_id": (index // 3) + 1,
            "market_price": 55 if index == 2 else 50,
        }
        for index, position in enumerate(positions)
    }


def _chips() -> list[dict]:
    return [
        {"name": name, "start_event": 1, "status_for_entry": "available"}
        for name in ("wildcard", "freehit", "bboost", "3xc")
    ]


def _snapshot() -> dict:
    pick_order = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15, 2, 6, 7, 12]
    position_by_element = {
        element: position for position, element in enumerate(pick_order, start=1)
    }
    return {
        "status": "connected",
        "entry_id": 7,
        "bank": 250,
        "free_transfers": 2,
        "transfer_cost": 0,
        "transfer_cost_per_additional": 4,
        "transfer_limit": 2,
        "transfers_made": 0,
        "transfer_accounting_version": 2,
        "chips": _chips(),
        "picks": [
            {
                "element": index,
                "position": position_by_element[index],
                "purchase_price": 50,
                "selling_price": 52 if index == 3 else 50,
                "is_captain": index == 13,
                "is_vice_captain": index == 8,
            }
            for index in range(1, 16)
        ],
    }


def test_authenticated_snapshot_becomes_exact_weekly_state() -> None:
    state = manager_state_from_snapshot(
        _snapshot(), event=2, player_catalog=_catalog(), rules=_rules()
    )

    assert state.event == 2
    assert state.bank == 250
    assert state.free_transfers == 2
    assert state.committed_points_cost == 0
    assert state.lineup.captain == 13
    assert state.lineup.vice_captain == 8
    assert [player.player_id for player in state.squad] == list(range(1, 16))
    assert state.squad[2].current_price == 55
    assert state.squad[2].selling_price == 52
    assert all(slot.status == ChipStatus.AVAILABLE for slot in state.chips if slot.half == 1)


def test_preseason_null_finance_state_fails_closed() -> None:
    snapshot = _snapshot()
    snapshot["free_transfers"] = None

    with pytest.raises(ManagerStateInputError, match="free_transfers"):
        manager_state_from_snapshot(snapshot, event=2, player_catalog=_catalog(), rules=_rules())


def test_paid_transfers_become_committed_points_cost() -> None:
    snapshot = _snapshot()
    snapshot.update(
        {
            "free_transfers": 0,
            "transfer_limit": 2,
            "transfers_made": 3,
            "transfer_cost": 4,
        }
    )

    state = manager_state_from_snapshot(
        snapshot, event=2, player_catalog=_catalog(), rules=_rules()
    )

    assert state.free_transfers == 0
    assert state.committed_points_cost == 4


def test_legacy_tariff_is_not_treated_as_committed_points() -> None:
    snapshot = _snapshot()
    for field in (
        "transfer_accounting_version",
        "transfer_cost_per_additional",
        "transfer_limit",
        "transfers_made",
    ):
        snapshot.pop(field)
    snapshot["transfer_cost"] = 4

    state = manager_state_from_snapshot(
        snapshot, event=2, player_catalog=_catalog(), rules=_rules()
    )

    assert state.free_transfers == 2
    assert state.committed_points_cost == 0


def test_ambiguous_exhausted_legacy_transfer_state_fails_closed() -> None:
    snapshot = _snapshot()
    for field in (
        "transfer_accounting_version",
        "transfer_cost_per_additional",
        "transfer_limit",
        "transfers_made",
    ):
        snapshot.pop(field)
    snapshot["free_transfers"] = 0
    snapshot["transfer_cost"] = 4

    with pytest.raises(ManagerStateInputError, match="legacy manager snapshot"):
        manager_state_from_snapshot(snapshot, event=2, player_catalog=_catalog(), rules=_rules())


def test_midseason_snapshot_requires_every_current_half_chip_state() -> None:
    snapshot = _snapshot()
    snapshot["chips"] = snapshot["chips"][:2]

    with pytest.raises(ManagerStateInputError, match="missing current-half chip states"):
        manager_state_from_snapshot(snapshot, event=2, player_catalog=_catalog(), rules=_rules())


def test_gw1_accepts_only_the_two_playable_chip_rows() -> None:
    snapshot = _snapshot()
    snapshot["chips"] = [row for row in snapshot["chips"] if row["name"] in {"bboost", "3xc"}]
    catalog = deepcopy(_catalog())
    for row in catalog.values():
        row["event_number"] = 1

    state = manager_state_from_snapshot(snapshot, event=1, player_catalog=catalog, rules=_rules())

    assert (
        next(
            slot for slot in state.chips if slot.half == 1 and slot.chip == ChipType.BENCH_BOOST
        ).status
        == ChipStatus.AVAILABLE
    )


def test_snapshot_selling_price_must_match_current_catalog_price() -> None:
    snapshot = _snapshot()
    snapshot["picks"][2]["selling_price"] = 55

    with pytest.raises(ManagerStateInputError, match="Selling price"):
        manager_state_from_snapshot(snapshot, event=2, player_catalog=_catalog(), rules=_rules())


def test_player_catalog_is_event_scoped() -> None:
    rows = list(_catalog().values()) + [
        {
            "element": 99,
            "event_number": 3,
            "position": "MID",
            "team_id": 1,
            "market_price": 50,
        }
    ]

    assert set(player_catalog_from_rows(rows, event=2)) == set(range(1, 16))
