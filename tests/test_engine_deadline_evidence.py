from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import archive_official_payloads
from fplagent_data.manager_snapshots import archive_manager_snapshot
from fplagent_engine.deadline_evidence import audit_deadline_evidence


def _official_payloads(deadline: str) -> dict:
    return {
        "bootstrap-static.json": {
            "elements": [{"id": 101, "team": 1}, {"id": 102, "team": 2}],
            "teams": [{"id": 1}, {"id": 2}],
            "events": [{"id": 1, "deadline_time": deadline}],
            "chips": [{"id": 1}],
            "element_types": [{"id": 1}],
            "game_config": {"rules": {}, "scoring": {}, "settings": {}},
        },
        "fixtures.json": [{"id": 1, "event": 1, "team_h": 1, "team_a": 2}],
    }


def _manager_snapshot(observed_at: str) -> dict:
    return {
        "status": "connected",
        "observed_at": observed_at,
        "entry_id": 431892,
        "bank": 0,
        "squad_value": 1_000,
        "free_transfers": 1,
        "transfer_cost": 0,
        "chips": [],
        "picks": [
            {
                "element": 200 + position,
                "position": position,
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
                "purchase_price": 50,
                "selling_price": 50,
                "name": f"Player {position}",
                "team": "Test",
            }
            for position in range(1, 16)
        ],
    }


def _write_forecasts(
    direct: Path,
    component: Path,
    *,
    observed: datetime,
    model_created: datetime,
) -> None:
    direct_rows = [
        {
            "snapshot_at": observed.isoformat(),
            "model_created_at": model_created.isoformat(),
            "model_version": "test-v1",
            "forecast_created_at": model_created.isoformat(),
            "event_number": event,
            "element": element,
            "expected_points": 4.0,
        }
        for event in (1, 2)
        for element in (101, 102)
    ]
    pq.write_table(pa.Table.from_pylist(direct_rows), direct)
    direct_hash = sha256_file(direct)
    component_rows = [
        {
            "event_number": event,
            "element": element,
            "expected_minutes": 80.0,
            "snapshot_at": observed.isoformat(),
            "component_model_created_at": model_created.isoformat(),
            "component_model_version": "component-test-v1",
            "component_forecast_created_at": model_created.isoformat(),
            "direct_forecast_sha256": direct_hash,
        }
        for event in (1, 2)
        for element in (101, 102)
    ]
    pq.write_table(pa.Table.from_pylist(component_rows), component)


def _write_decision(
    decision: Path,
    source: Path,
    *,
    direct: Path,
    created_at: datetime,
) -> None:
    source.write_text(
        json.dumps({"forecast_sha256": sha256_file(direct)}) + "\n",
        encoding="utf-8",
    )
    decision.write_text(
        json.dumps(
            {
                "created_at": created_at.isoformat(),
                "decision_status": "ready",
                "source_artifacts": {
                    "search_results": str(source),
                    "search_results_sha256": sha256_file(source),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_deadline_evidence_gate_accepts_one_coherent_generation(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    deadline = observed + timedelta(days=14)
    official_root = tmp_path / "official"
    official_pointer = tmp_path / "official-pointer.json"
    manifests = tmp_path / "manifests"
    manager_root = tmp_path / "managers"
    archive_official_payloads(
        _official_payloads(deadline.isoformat()),
        observed_at=observed,
        snapshot_root=official_root,
        pointer_path=official_pointer,
    )
    archive_manager_snapshot(
        _manager_snapshot(observed.isoformat()),
        snapshot_root=manager_root,
        manifest_root=manifests,
    )
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    model_created = observed + timedelta(minutes=1)
    _write_forecasts(direct, component, observed=observed, model_created=model_created)
    decision = tmp_path / "decision.json"
    source = tmp_path / "search.json"
    _write_decision(
        decision,
        source,
        direct=direct,
        created_at=model_created + timedelta(minutes=1),
    )

    result = audit_deadline_evidence(
        as_of=observed + timedelta(minutes=5),
        manager_entry_id=431892,
        official_snapshot_root=official_root,
        official_pointer_path=official_pointer,
        manager_snapshot_root=manager_root,
        manifest_root=manifests,
        direct_forecast_path=direct,
        component_forecast_path=component,
        decision_path=decision,
        output_path=None,
    )

    assert result["publishable"] is True
    assert result["issues"] == []
    assert result["official"]["publishable"] is True
    assert result["manager"]["publishable"] is True
    assert result["direct_forecast"]["aligned_to_official"] is True
    assert result["decision"]["source_forecast_hash_match"] is True


def test_deadline_evidence_accepts_forecast_as_a_direct_binary_source(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    official_root = tmp_path / "official"
    official_pointer = tmp_path / "official-pointer.json"
    archive_official_payloads(
        _official_payloads((observed + timedelta(days=14)).isoformat()),
        observed_at=observed,
        snapshot_root=official_root,
        pointer_path=official_pointer,
    )
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    _write_forecasts(
        direct,
        component,
        observed=observed,
        model_created=observed + timedelta(minutes=1),
    )
    decision = tmp_path / "weekly.json"
    decision.write_text(
        json.dumps(
            {
                "created_at": (observed + timedelta(minutes=2)).isoformat(),
                "source_artifacts": {
                    "forecast": str(direct),
                    "forecast_sha256": sha256_file(direct),
                    "component_forecast": str(component),
                    "component_forecast_sha256": sha256_file(component),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = audit_deadline_evidence(
        as_of=observed + timedelta(minutes=5),
        official_snapshot_root=official_root,
        official_pointer_path=official_pointer,
        direct_forecast_path=direct,
        component_forecast_path=component,
        decision_path=decision,
        output_path=None,
    )

    assert result["publishable"] is True
    assert result["decision"]["source_forecast_hash_match"] is True
    assert not any("valid JSON" in issue for issue in result["decision"]["issues"])


def test_deadline_evidence_gate_rejects_mixed_generations(tmp_path: Path) -> None:
    official_observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    forecast_observed = official_observed - timedelta(days=1)
    official_root = tmp_path / "official"
    official_pointer = tmp_path / "official-pointer.json"
    archive_official_payloads(
        _official_payloads((official_observed + timedelta(days=14)).isoformat()),
        observed_at=official_observed,
        snapshot_root=official_root,
        pointer_path=official_pointer,
    )
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    _write_forecasts(
        direct,
        component,
        observed=forecast_observed,
        model_created=forecast_observed + timedelta(minutes=1),
    )
    decision = tmp_path / "decision.json"
    source = tmp_path / "search.json"
    _write_decision(
        decision,
        source,
        direct=direct,
        created_at=forecast_observed + timedelta(minutes=2),
    )

    result = audit_deadline_evidence(
        as_of=official_observed + timedelta(minutes=5),
        official_snapshot_root=official_root,
        official_pointer_path=official_pointer,
        direct_forecast_path=direct,
        component_forecast_path=component,
        decision_path=decision,
        output_path=None,
    )

    assert result["publishable"] is False
    assert result["direct_forecast"]["aligned_to_official"] is False
    assert result["decision"]["publishable"] is False
    assert any("does not match" in issue for issue in result["issues"])
    assert any("decision predates" in issue for issue in result["issues"])


def test_deadline_evidence_gate_detects_decision_source_tampering(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    official_root = tmp_path / "official"
    official_pointer = tmp_path / "official-pointer.json"
    archive_official_payloads(
        _official_payloads((observed + timedelta(days=14)).isoformat()),
        observed_at=observed,
        snapshot_root=official_root,
        pointer_path=official_pointer,
    )
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    _write_forecasts(
        direct,
        component,
        observed=observed,
        model_created=observed + timedelta(minutes=1),
    )
    decision = tmp_path / "decision.json"
    source = tmp_path / "search.json"
    _write_decision(
        decision,
        source,
        direct=direct,
        created_at=observed + timedelta(minutes=2),
    )
    source.write_text("{}\n", encoding="utf-8")

    result = audit_deadline_evidence(
        as_of=observed + timedelta(minutes=5),
        official_snapshot_root=official_root,
        official_pointer_path=official_pointer,
        direct_forecast_path=direct,
        component_forecast_path=component,
        decision_path=decision,
        output_path=None,
    )

    assert result["publishable"] is False
    assert any("checksum changed" in issue for issue in result["decision"]["issues"])


def test_deadline_evidence_rejects_forecast_created_in_the_future(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    official_root = tmp_path / "official"
    official_pointer = tmp_path / "official-pointer.json"
    archive_official_payloads(
        _official_payloads((observed + timedelta(days=14)).isoformat()),
        observed_at=observed,
        snapshot_root=official_root,
        pointer_path=official_pointer,
    )
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    future = observed + timedelta(minutes=11)
    _write_forecasts(direct, component, observed=observed, model_created=future)
    decision = tmp_path / "decision.json"
    source = tmp_path / "search.json"
    _write_decision(decision, source, direct=direct, created_at=future)

    result = audit_deadline_evidence(
        as_of=observed,
        official_snapshot_root=official_root,
        official_pointer_path=official_pointer,
        direct_forecast_path=direct,
        component_forecast_path=component,
        decision_path=decision,
        output_path=None,
    )

    assert result["publishable"] is False
    assert "forecast creation time is in the future" in result["direct_forecast"]["issues"]


def test_weekly_decision_requires_manager_snapshot_after_previous_deadline(
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    official_root = tmp_path / "official"
    official_pointer = tmp_path / "official-pointer.json"
    archive_official_payloads(
        _official_payloads((observed + timedelta(days=5)).isoformat()),
        observed_at=observed,
        snapshot_root=official_root,
        pointer_path=official_pointer,
    )
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    _write_forecasts(
        direct,
        component,
        observed=observed,
        model_created=observed + timedelta(minutes=1),
    )
    manager_contract = tmp_path / "manager-state.json"
    manager_contract.write_text(
        json.dumps(
            {
                "manager_state": {"event": 3},
                "source_artifacts": {
                    "manager_snapshot_observed_at": "2026-08-28T11:00:00+00:00",
                    "manager_snapshot_minimum_observed_at": "2026-08-28T17:30:00+00:00",
                    "forecast_sha256": sha256_file(direct),
                },
            }
        ),
        encoding="utf-8",
    )
    decision = tmp_path / "weekly.json"
    decision.write_text(
        json.dumps(
            {
                "created_at": (observed + timedelta(minutes=2)).isoformat(),
                "decision_event": 3,
                "source_artifacts": {
                    "forecast": str(direct),
                    "forecast_sha256": sha256_file(direct),
                    "manager_state_contract": str(manager_contract),
                    "manager_state_contract_sha256": sha256_file(manager_contract),
                },
            }
        ),
        encoding="utf-8",
    )

    result = audit_deadline_evidence(
        as_of=observed + timedelta(minutes=5),
        official_snapshot_root=official_root,
        official_pointer_path=official_pointer,
        direct_forecast_path=direct,
        component_forecast_path=component,
        decision_path=decision,
        output_path=None,
    )

    assert result["publishable"] is False
    assert result["decision"]["manager_state_freshness"]["passed"] is False
    assert any("previous Gameweek deadline" in issue for issue in result["issues"])
