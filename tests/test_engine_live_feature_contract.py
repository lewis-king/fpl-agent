import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_data.http import sha256_file
from fplagent_engine.live_feature_contract import (
    LiveFeatureContractError,
    audit_live_feature_contract,
)


def _parquet(path: Path, rows: list[dict]) -> Path:
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _connection(*, finalized: bool) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE fpl_current_events "
        "(id INTEGER, finished BOOLEAN, data_checked BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO fpl_current_events VALUES (1, ?, ?)",
        [finalized, finalized],
    )
    connection.execute(
        "CREATE TABLE fpl_current_players "
        "(code INTEGER, total_points DOUBLE, minutes DOUBLE, "
        "expected_goals VARCHAR, expected_assists VARCHAR)"
    )
    return connection


def test_live_feature_contract_is_ready_before_first_final_event(tmp_path: Path) -> None:
    connection = _connection(finalized=False)
    try:
        result = audit_live_feature_contract(
            connection,
            current_features_path=_parquet(
                tmp_path / "features.parquet", [{"event_number": 1}]
            ),
            team_strength_path=_parquet(
                tmp_path / "strength.parquet", [{"event": 1}]
            ),
            player_history_path=tmp_path / "not-created-yet.parquet",
            player_history_receipt_path=tmp_path / "not-created-yet.json",
            output_path=tmp_path / "contract.json",
            start_event=1,
            end_event=1,
        )
    finally:
        connection.close()
    assert result["publishable"] is True
    assert result["finalized_events"] == []
    assert result["checks"]["current_player_history"]["required"] is False


def test_live_feature_contract_blocks_missing_final_event_history(tmp_path: Path) -> None:
    connection = _connection(finalized=True)
    try:
        with pytest.raises(LiveFeatureContractError, match="player history is missing"):
            audit_live_feature_contract(
                connection,
                current_features_path=_parquet(
                    tmp_path / "features.parquet", [{"event_number": 2}]
                ),
                team_strength_path=_parquet(
                    tmp_path / "strength.parquet", [{"event": 2}]
                ),
                player_history_path=tmp_path / "missing.parquet",
                player_history_receipt_path=tmp_path / "missing.json",
                output_path=tmp_path / "contract.json",
                start_event=2,
                end_event=2,
            )
    finally:
        connection.close()


def test_live_feature_contract_blocks_finished_but_provisional_event(
    tmp_path: Path,
) -> None:
    connection = _connection(finalized=False)
    connection.execute(
        "UPDATE fpl_current_events SET finished = true, data_checked = false"
    )
    try:
        with pytest.raises(LiveFeatureContractError, match="awaiting FPL's data-checked"):
            audit_live_feature_contract(
                connection,
                current_features_path=_parquet(
                    tmp_path / "features.parquet", [{"event_number": 2}]
                ),
                team_strength_path=_parquet(
                    tmp_path / "strength.parquet", [{"event": 2}]
                ),
                player_history_path=tmp_path / "missing.parquet",
                player_history_receipt_path=tmp_path / "missing.json",
                output_path=tmp_path / "contract.json",
                start_event=2,
                end_event=2,
            )
    finally:
        connection.close()


def test_live_feature_contract_reconciles_and_proves_feature_delivery(
    tmp_path: Path,
) -> None:
    connection = _connection(finalized=True)
    history = _parquet(
        tmp_path / "history.parquet",
        [
            {
                "event": 1,
                "player_code": 101,
                "event_kickoff": "2026-08-21T19:00:00+00:00",
                "points": 6.0,
                "minutes": 90.0,
                "goals": 1.0,
                "assists": 0.0,
                "xg": 0.52,
                "xa": 0.11,
                "bps": 30.0,
                "clean_sheets": 0.0,
                "defensive_contribution": 1.0,
            }
        ],
    )
    history_receipt = tmp_path / "history.json"
    history_receipt.write_text(
        json.dumps(
            {
                "status": "ready",
                "events": [1],
                "output_sha256": sha256_file(history),
            }
        ),
        encoding="utf-8",
    )
    connection.execute(
        "INSERT INTO fpl_current_players VALUES (101, 6, 90, '0.52', '0.11')"
    )
    try:
        result = audit_live_feature_contract(
            connection,
            current_features_path=_parquet(
                tmp_path / "features.parquet",
                [{"event_number": 2, "player_code": 101, "last_points": 6.0}],
            ),
            team_strength_path=_parquet(
                tmp_path / "strength.parquet", [{"event": 2}]
            ),
            player_history_path=history,
            player_history_receipt_path=history_receipt,
            output_path=tmp_path / "contract.json",
            start_event=2,
            end_event=2,
        )
    finally:
        connection.close()
    assert result["publishable"] is True
    assert result["checks"]["event_live_coverage"]["passed"] is True
    assert result["checks"]["official_cumulative_reconciliation"]["passed"] is True
    assert result["checks"]["history_reached_forecast_features"]["passed"] is True


def test_live_feature_contract_accepts_finalized_history_as_live_cumulative_prefix(
    tmp_path: Path,
) -> None:
    connection = _connection(finalized=True)
    connection.execute("ALTER TABLE fpl_current_events ADD COLUMN is_current BOOLEAN")
    connection.execute("UPDATE fpl_current_events SET is_current = false")
    connection.execute(
        "INSERT INTO fpl_current_events VALUES (2, false, false, true)"
    )
    history = _parquet(
        tmp_path / "history.parquet",
        [
            {
                "event": 1,
                "player_code": 101,
                "event_kickoff": "2026-08-21T19:00:00+00:00",
                "points": 6.0,
                "minutes": 90.0,
                "goals": 1.0,
                "assists": 0.0,
                "xg": 0.52,
                "xa": 0.11,
                "bps": 30.0,
                "clean_sheets": 0.0,
                "defensive_contribution": 1.0,
            }
        ],
    )
    history_receipt = tmp_path / "history.json"
    history_receipt.write_text(
        json.dumps(
            {
                "status": "ready",
                "events": [1],
                "output_sha256": sha256_file(history),
            }
        ),
        encoding="utf-8",
    )
    connection.execute(
        "INSERT INTO fpl_current_players VALUES (101, 8, 120, '0.60', '0.15')"
    )
    try:
        result = audit_live_feature_contract(
            connection,
            current_features_path=_parquet(
                tmp_path / "features.parquet",
                [{"event_number": 2, "player_code": 101, "last_points": 6.0}],
            ),
            team_strength_path=_parquet(
                tmp_path / "strength.parquet", [{"event": 2}]
            ),
            player_history_path=history,
            player_history_receipt_path=history_receipt,
            output_path=tmp_path / "contract.json",
            start_event=2,
            end_event=2,
        )
    finally:
        connection.close()

    reconciliation = result["checks"]["official_cumulative_reconciliation"]
    assert result["publishable"] is True
    assert reconciliation["mode"] == "finalized_history_is_prefix_of_live_cumulative"
    assert reconciliation["exact_match"] is False
    assert reconciliation["prefix_violations"] == 0


def test_live_feature_contract_blocks_history_larger_than_live_cumulative(
    tmp_path: Path,
) -> None:
    connection = _connection(finalized=True)
    connection.execute("ALTER TABLE fpl_current_events ADD COLUMN is_current BOOLEAN")
    connection.execute("UPDATE fpl_current_events SET is_current = false")
    connection.execute(
        "INSERT INTO fpl_current_events VALUES (2, false, false, true)"
    )
    history = _parquet(
        tmp_path / "history.parquet",
        [
            {
                "event": 1,
                "player_code": 101,
                "event_kickoff": "2026-08-21T19:00:00+00:00",
                "points": 6.0,
                "minutes": 90.0,
                "goals": 1.0,
                "assists": 0.0,
                "xg": 0.52,
                "xa": 0.11,
                "bps": 30.0,
                "clean_sheets": 0.0,
                "defensive_contribution": 1.0,
            }
        ],
    )
    history_receipt = tmp_path / "history.json"
    history_receipt.write_text(
        json.dumps(
            {
                "status": "ready",
                "events": [1],
                "output_sha256": sha256_file(history),
            }
        ),
        encoding="utf-8",
    )
    connection.execute(
        "INSERT INTO fpl_current_players VALUES (101, 6, 80, '0.40', '0.10')"
    )
    try:
        with pytest.raises(LiveFeatureContractError, match="does not reconcile"):
            audit_live_feature_contract(
                connection,
                current_features_path=_parquet(
                    tmp_path / "features.parquet",
                    [{"event_number": 2, "player_code": 101, "last_points": 6.0}],
                ),
                team_strength_path=_parquet(
                    tmp_path / "strength.parquet", [{"event": 2}]
                ),
                player_history_path=history,
                player_history_receipt_path=history_receipt,
                output_path=tmp_path / "contract.json",
                start_event=2,
                end_event=2,
            )
    finally:
        connection.close()
