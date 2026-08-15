from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine.cli import parser
from fplagent_engine.deadline_pipeline import (
    DeadlinePipelineError,
    run_weekly_deadline_pipeline,
)
from fplagent_engine.rules import SquadRules


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


def _artifacts(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    contract = tmp_path / "manager-state.json"
    schedule = tmp_path / "schedule.json"
    rows = [{"event_number": event, "element": 1} for event in (2, 3, 4)]
    pq.write_table(pa.Table.from_pylist(rows), direct)
    pq.write_table(pa.Table.from_pylist(rows), component)
    contract.write_text('{"contract_version": 1}\n', encoding="utf-8")
    schedule.write_text('{"receipt_version": 1}\n', encoding="utf-8")
    return direct, component, contract, schedule


def _kwargs(tmp_path: Path) -> tuple[dict[str, Any], dict[str, int]]:
    direct, component, contract, schedule = _artifacts(tmp_path)
    calls = {"decisions": 0, "audits": 0, "participation": 0}

    def refresh_runner(**_: Any) -> dict[str, Any]:
        return {"official": {"snapshot_id": "snapshot-1", "publishable": True}}

    def decision_runner(rules: SquadRules, **kwargs: Any) -> dict[str, Any]:
        assert rules == _rules()
        calls["decisions"] += 1
        payload = {
            "created_at": kwargs["created_at"],
            "decision_event": kwargs["event"],
            "events": list(kwargs["events"]),
            "source_artifacts": {
                "forecast": str(direct),
                "component_forecast": str(component),
            },
        }
        Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["output_path"]).write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        return payload

    def evidence_auditor(**kwargs: Any) -> dict[str, Any]:
        calls["audits"] += 1
        result = {"publishable": True, "issues": []}
        output = kwargs.get("output_path")
        if output is not None:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(result) + "\n", encoding="utf-8")
        return result

    def participation_refresher(**_: Any) -> dict[str, Any]:
        calls["participation"] += 1
        return {"status": "shadow_consensus_ready", "production_weight": 0.0}

    return (
        {
            "manager_entry_id": 7,
            "horizon": 3,
            "as_of": "2026-08-28T16:00:00+00:00",
            "reuse_latest_official": True,
            "direct_forecast_path": direct,
            "component_forecast_path": component,
            "schedule_receipt_path": schedule,
            "published_decision_path": tmp_path / "weekly-current.json",
            "staging_root": tmp_path / "staging",
            "decision_archive_root": tmp_path / "archive",
            "pipeline_receipt_path": tmp_path / "pipeline.json",
            "deadline_status_path": tmp_path / "deadline-status.json",
            "participation_receipt_path": tmp_path / "participation-receipt.json",
            "participation_consensus_path": tmp_path / "participation-consensus.parquet",
            "refresh_runner": refresh_runner,
            "event_resolver": lambda: 2,
            "state_deriver": lambda _entry, _event: {
                "status": "ready",
                "contract_path": str(contract),
                "contract_sha256": "contract-hash",
            },
            "decision_runner": decision_runner,
            "evidence_auditor": evidence_auditor,
            "participation_refresher": participation_refresher,
            "rules_loader": _rules,
        },
        calls,
    )


def test_weekly_pipeline_publishes_only_after_gate_and_reuses_same_generation(
    tmp_path: Path,
) -> None:
    kwargs, calls = _kwargs(tmp_path)

    first = run_weekly_deadline_pipeline(**kwargs)
    published_bytes = Path(kwargs["published_decision_path"]).read_bytes()
    receipt_bytes = Path(kwargs["pipeline_receipt_path"]).read_bytes()
    second = run_weekly_deadline_pipeline(**kwargs)

    assert first["status"] == "published"
    assert first["published"] is True
    assert first["reused"] is False
    assert Path(first["archived_decision"]).read_bytes() == published_bytes
    assert second["reused"] is True
    assert calls["decisions"] == 1
    assert calls["participation"] == 2
    assert Path(kwargs["published_decision_path"]).read_bytes() == published_bytes
    assert Path(kwargs["pipeline_receipt_path"]).read_bytes() == receipt_bytes


def test_failed_staged_gate_never_replaces_active_decision(tmp_path: Path) -> None:
    kwargs, _ = _kwargs(tmp_path)
    published = Path(kwargs["published_decision_path"])
    published.write_bytes(b"previous-good-decision")
    kwargs["evidence_auditor"] = lambda **_: {
        "publishable": False,
        "issues": ["stale forecast"],
    }

    result = run_weekly_deadline_pipeline(**kwargs)

    assert result["status"] == "blocked"
    assert result["published"] is False
    assert published.read_bytes() == b"previous-good-decision"


def test_failed_final_recheck_rolls_back_decision_and_status(tmp_path: Path) -> None:
    kwargs, _ = _kwargs(tmp_path)
    published = Path(kwargs["published_decision_path"])
    status = Path(kwargs["deadline_status_path"])
    published.write_bytes(b"previous-good-decision")
    status.write_bytes(b"previous-good-status")
    audit_calls = 0

    def auditor(**kwargs: Any) -> dict[str, Any]:
        nonlocal audit_calls
        audit_calls += 1
        passed = audit_calls == 1
        if kwargs.get("output_path") is not None:
            Path(kwargs["output_path"]).write_text("bad-status", encoding="utf-8")
        return {"publishable": passed, "issues": [] if passed else ["race detected"]}

    kwargs["evidence_auditor"] = auditor

    with pytest.raises(DeadlinePipelineError, match="final evidence recheck"):
        run_weekly_deadline_pipeline(**kwargs)

    assert published.read_bytes() == b"previous-good-decision"
    assert status.read_bytes() == b"previous-good-status"


def test_incomplete_manager_state_stops_before_decision_generation(tmp_path: Path) -> None:
    kwargs, calls = _kwargs(tmp_path)
    kwargs["state_deriver"] = lambda _entry, _event: {
        "status": "not_ready",
        "message": "FPL has not exposed free transfers yet.",
    }

    result = run_weekly_deadline_pipeline(**kwargs)

    assert result["status"] == "not_ready"
    assert result["published"] is False
    assert calls["decisions"] == 0
    assert not Path(kwargs["published_decision_path"]).exists()


def test_deadline_run_is_exposed_as_one_engine_command() -> None:
    args = parser().parse_args(
        [
            "deadline-run",
            "--manager-entry-id",
            "431892",
            "--reuse-latest-official",
            "--horizon",
            "4",
        ]
    )

    assert args.command == "deadline-run"
    assert args.manager_entry_id == 431892
    assert args.reuse_latest_official is True
    assert args.horizon == 4
