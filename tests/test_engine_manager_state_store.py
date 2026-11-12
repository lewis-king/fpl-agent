from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_data.manager_snapshots import archive_manager_snapshot
from fplagent_engine.manager_state_store import (
    ManagerStateContractError,
    current_actionable_event,
    derive_latest_manager_state,
    load_manager_state_contract,
    manager_state_pointer_path,
)
from fplagent_engine.rules import SquadRules
from fplagent_engine.weekly_decision import load_weekly_manager_state


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


def _forecast(path: Path, *, event: int = 2) -> Path:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    rows = [
        {
            "element": index,
            "event_number": event,
            "position": position,
            "team_id": ((index - 1) // 3) + 1,
            "market_price": 55 if index == 3 else 50,
        }
        for index, position in enumerate(positions, start=1)
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _snapshot(*, free_transfers: int | None = 2) -> dict:
    order = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15, 2, 6, 7, 12]
    position_by_element = {
        element: position for position, element in enumerate(order, start=1)
    }
    return {
        "status": "connected",
        "observed_at": "2026-08-28T10:00:00+00:00",
        "entry_id": 7,
        "bank": 25,
        "squad_value": 1005,
        "free_transfers": free_transfers,
        "transfer_cost": 0,
        "chips": [
            {"name": name, "start_event": 1, "status_for_entry": "available"}
            for name in ("wildcard", "freehit", "bboost", "3xc")
        ],
        "picks": [
            {
                "element": element,
                "position": position_by_element[element],
                "is_captain": element == 13,
                "is_vice_captain": element == 8,
                "purchase_price": 50,
                "selling_price": 52 if element == 3 else 50,
                "name": f"Player {element}",
                "team": f"Team {((element - 1) // 3) + 1}",
            }
            for element in range(1, 16)
        ],
    }


def _derive(tmp_path: Path, *, free_transfers: int | None = 2) -> dict:
    snapshot_root = tmp_path / "raw"
    snapshot_manifests = tmp_path / "snapshot-manifests"
    archive_manager_snapshot(
        _snapshot(free_transfers=free_transfers),
        snapshot_root=snapshot_root,
        manifest_root=snapshot_manifests,
    )
    return derive_latest_manager_state(
        7,
        2,
        forecast_path=_forecast(tmp_path / "forecast.parquet"),
        rules=_rules(),
        snapshot_root=snapshot_root,
        snapshot_manifest_root=snapshot_manifests,
        state_root=tmp_path / "states",
        state_manifest_root=tmp_path / "state-manifests",
        minimum_snapshot_observed_at="2026-08-27T17:30:00+00:00",
    )


def test_complete_snapshot_persists_exact_immutable_contract(tmp_path: Path) -> None:
    result = _derive(tmp_path)

    assert result["status"] == "ready"
    contract_path = Path(result["contract_path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    state = load_manager_state_contract(
        contract_path,
        rules=_rules(),
        expected_event=2,
        expected_forecast_path=tmp_path / "forecast.parquet",
    )
    pointer = json.loads(
        manager_state_pointer_path(7, tmp_path / "state-manifests").read_text(
            encoding="utf-8"
        )
    )

    assert contract["source_artifacts"]["manager_snapshot_sha256"]
    assert contract["source_artifacts"]["forecast_sha256"]
    assert contract["source_artifacts"]["runtime_rules_sha256"]
    assert state.event == 2
    assert state.free_transfers == 2
    assert state.squad[2].selling_price == 52
    assert pointer["generation_id"] == result["generation_id"]

    weekly_state, source_label = load_weekly_manager_state(
        contract_path,
        forecast_path=tmp_path / "forecast.parquet",
        event=2,
        rules=_rules(),
    )
    assert weekly_state == state
    assert source_label == "manager_state_contract"


def test_incomplete_preseason_state_reports_not_ready_without_contract(tmp_path: Path) -> None:
    result = _derive(tmp_path, free_transfers=None)

    assert result["status"] == "not_ready"
    assert "free_transfers" in result["unavailable_fields"]
    assert not (tmp_path / "states").exists()
    assert not manager_state_pointer_path(7, tmp_path / "state-manifests").exists()


def test_snapshot_before_previous_deadline_cannot_be_relabelled_as_next_event_state(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "raw"
    snapshot_manifests = tmp_path / "snapshot-manifests"
    archive_manager_snapshot(
        _snapshot(),
        snapshot_root=snapshot_root,
        manifest_root=snapshot_manifests,
    )

    result = derive_latest_manager_state(
        7,
        3,
        forecast_path=_forecast(tmp_path / "forecast.parquet", event=3),
        rules=_rules(),
        snapshot_root=snapshot_root,
        snapshot_manifest_root=snapshot_manifests,
        state_root=tmp_path / "states",
        state_manifest_root=tmp_path / "state-manifests",
        minimum_snapshot_observed_at="2026-08-28T17:30:00+00:00",
    )

    assert result["status"] == "not_ready"
    assert result["reason_code"] == "manager_snapshot_predates_previous_deadline"
    assert "Reconnect FPL" in result["message"]
    assert not (tmp_path / "states").exists()


def test_same_generation_rejects_content_collision(tmp_path: Path) -> None:
    result = _derive(tmp_path)
    contract_path = Path(result["contract_path"])
    tampered = json.loads(contract_path.read_text(encoding="utf-8"))
    tampered["manager_state"]["bank"] = 999
    contract_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ManagerStateContractError, match="immutable manager-state contract"):
        derive_latest_manager_state(
            7,
            2,
            forecast_path=tmp_path / "forecast.parquet",
            rules=_rules(),
            snapshot_root=tmp_path / "raw",
            snapshot_manifest_root=tmp_path / "snapshot-manifests",
            state_root=tmp_path / "states",
            state_manifest_root=tmp_path / "state-manifests",
            minimum_snapshot_observed_at="2026-08-27T17:30:00+00:00",
        )


def test_contract_fails_closed_against_different_forecast(tmp_path: Path) -> None:
    result = _derive(tmp_path)
    different = _forecast(tmp_path / "different.parquet")
    table = pq.read_table(different).to_pylist()
    table[0]["market_price"] = 51
    pq.write_table(pa.Table.from_pylist(table), different)

    with pytest.raises(ManagerStateContractError, match="forecast does not match"):
        load_manager_state_contract(
            Path(result["contract_path"]),
            rules=_rules(),
            expected_forecast_path=different,
        )


def test_current_actionable_event_requires_exactly_one_official_next_event(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE fpl_current_events (id INTEGER, is_next BOOLEAN)")
    connection.execute("INSERT INTO fpl_current_events VALUES (1, FALSE), (2, TRUE)")
    connection.close()

    assert current_actionable_event(database) == 2

    connection = duckdb.connect(str(database))
    connection.execute("UPDATE fpl_current_events SET is_next = TRUE")
    connection.close()
    with pytest.raises(ManagerStateContractError, match="expected one official next event"):
        current_actionable_event(database)
