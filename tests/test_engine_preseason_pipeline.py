from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine.cli import parser
from fplagent_engine.preseason_pipeline import (
    PreseasonPipelineError,
    run_gw1_deadline_pipeline,
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


def _kwargs(tmp_path: Path) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    direct = tmp_path / "direct.parquet"
    component = tmp_path / "component.parquet"
    pq.write_table(pa.Table.from_pylist([{"event_number": 1, "element": 1}]), direct)
    pq.write_table(pa.Table.from_pylist([{"event_number": 1, "element": 1}]), component)
    role_receipt = tmp_path / "role-receipt.json"
    role_evidence = tmp_path / "role-evidence.parquet"
    role_receipt.write_text('{"current": true}\n', encoding="utf-8")
    pq.write_table(pa.Table.from_pylist([{"fpl_element": 1}]), role_evidence)
    calls: list[str] = []
    audit_calls = {"count": 0}

    def refresh_runner(**_: Any) -> dict[str, Any]:
        calls.append("refresh")
        return {"official": {"snapshot_id": "snapshot-1", "publishable": True}}

    def role_lineage_validator(**_: Any) -> dict[str, Any]:
        return {"status": "current", "role_evidence_sha256": "role-evidence"}

    def role_evidence_refresher() -> dict[str, Any]:
        raise AssertionError("current role evidence must not be fetched again")

    def initial_squad_runner(stability_samples: int) -> dict[str, Any]:
        assert stability_samples == 3
        calls.append("initial_squad")
        return {
            "budget_spent": 100.0,
            "bank": 0.0,
            "gameweeks": {"1": {"expected_points": 60.0}},
        }

    def named_runner(name: str, result: dict[str, Any]):
        def run(**runner_kwargs: Any) -> dict[str, Any]:
            calls.append(name)
            report_path = runner_kwargs.get("report_path")
            if report_path is not None:
                Path(report_path).parent.mkdir(parents=True, exist_ok=True)
                Path(report_path).write_text(f"# {name}\n", encoding="utf-8")
            return result

        return run

    def component_candidate_runner() -> dict[str, Any]:
        calls.append("component_candidates")
        return {"candidate_count": 21}

    def synthesis_runner(**kwargs: Any) -> dict[str, Any]:
        calls.append("synthesis")
        result = {
            "created_at": kwargs["created_at"],
            "decision": {"candidate_id": "R-test"},
            "verdict": "test winner",
        }
        rendered = json.dumps(result, sort_keys=True) + "\n"
        for key in ("results_path", "decision_path"):
            path = Path(kwargs[key])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
        report = Path(kwargs["report_path"])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# staged report\n", encoding="utf-8")
        return result

    def artifact_runner(name: str, result: dict[str, Any]):
        def run(**kwargs: Any) -> dict[str, Any]:
            calls.append(name)
            Path(kwargs["results_path"]).write_text(
                json.dumps(result, sort_keys=True) + "\n", encoding="utf-8"
            )
            Path(kwargs["report_path"]).write_text(f"# {name}\n", encoding="utf-8")
            return result

        return run

    def availability_auditor(**kwargs: Any) -> dict[str, Any]:
        result = {
            "status": "verification_required",
            "current": True,
            "lineage": {"decision": "test-generation"},
            "summary": {"selected_players": 15},
            "issues": [],
        }
        output = kwargs.get("output_path")
        if output is not None:
            Path(output).write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        return result

    def evidence_auditor(**kwargs: Any) -> dict[str, Any]:
        audit_calls["count"] += 1
        result = {"publishable": True, "issues": []}
        output = kwargs.get("output_path")
        if output is not None:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(result) + "\n", encoding="utf-8")
        return result

    def prospective_freezer(**_: Any) -> dict[str, Any]:
        calls.append("prospective_freeze")
        path = tmp_path / "prospective.json"
        path.write_text('{"contract": true}\n', encoding="utf-8")
        return {
            "contract_path": str(path),
            "contract_fingerprint": "prospective-fingerprint",
            "action_summaries": [{"action_id": "R-test"}, {"action_id": "R-other"}],
        }

    return (
        {
            "as_of": "2026-08-07T11:30:00+00:00",
            "reuse_latest_official": True,
            "stability_samples": 3,
            "direct_forecast_path": direct,
            "component_forecast_path": component,
            "published_decision_path": tmp_path / "current-decision.json",
            "published_results_path": tmp_path / "current-results.json",
            "published_report_path": tmp_path / "current-report.md",
            "staging_root": tmp_path / "staging",
            "pipeline_receipt_path": tmp_path / "pipeline.json",
            "deadline_status_path": tmp_path / "deadline-status.json",
            "official_players_path": tmp_path / "players.parquet",
            "role_receipt_path": role_receipt,
            "role_evidence_path": role_evidence,
            "published_role_scenario_path": tmp_path / "role-scenario.json",
            "published_role_scenario_report_path": tmp_path / "role-scenario.md",
            "published_role_threshold_path": tmp_path / "role-threshold.json",
            "published_role_threshold_report_path": tmp_path / "role-threshold.md",
            "availability_watch_path": tmp_path / "availability-watch.json",
            "refresh_runner": refresh_runner,
            "initial_squad_runner": initial_squad_runner,
            "tournament_runner": named_runner(
                "residual_tournament", {"recommendation": {"candidate_id": "S001"}}
            ),
            "component_tournament_runner": named_runner(
                "component_tournament",
                {
                    "recommended_candidate": "S001",
                    "promotion_gate": {"status": "shadow"},
                },
            ),
            "component_candidate_runner": component_candidate_runner,
            "robust_runner": named_runner("robust_search", {"leader": {"candidate_id": "R-five"}}),
            "horizon_runner": named_runner(
                "horizon_audit",
                {
                    "leader": {"candidate_id": "R-eight"},
                    "verdict": "long_horizon_challenger_promoted",
                },
            ),
            "synthesis_runner": synthesis_runner,
            "role_scenario_runner": artifact_runner(
                "preseason_role_scenario",
                {
                    "verdict": "stable",
                    "supported_deep_squad_scenarios": ["severe_role_stress"],
                },
            ),
            "role_threshold_runner": artifact_runner(
                "preseason_role_threshold",
                {"verdict": "bounded", "boundary": {"classification": "test"}},
            ),
            "role_lineage_validator": role_lineage_validator,
            "role_evidence_refresher": role_evidence_refresher,
            "availability_auditor": availability_auditor,
            "evidence_auditor": evidence_auditor,
            "prospective_freezer": prospective_freezer,
            "rules_loader": _rules,
        },
        calls,
        audit_calls,
    )


def test_gw1_pipeline_runs_full_order_then_reuses_same_generation(tmp_path: Path) -> None:
    kwargs, calls, audit_calls = _kwargs(tmp_path)

    first = run_gw1_deadline_pipeline(**kwargs)
    first_calls = list(calls)
    second = run_gw1_deadline_pipeline(**kwargs)

    assert first["status"] == "published"
    assert first["published"] is True
    assert first["reused"] is False
    assert second["reused"] is True
    assert first_calls == [
        "refresh",
        "initial_squad",
        "residual_tournament",
        "component_tournament",
        "component_candidates",
        "component_tournament",
        "robust_search",
        "horizon_audit",
        "synthesis",
        "preseason_role_scenario",
        "preseason_role_threshold",
        "prospective_freeze",
    ]
    assert calls == [*first_calls, "refresh"]
    assert audit_calls["count"] == 3
    assert [stage["name"] for stage in first["stages"]] == [
        "initial_squad",
        "residual_tournament",
        "component_selection",
        "component_candidates",
        "component_holdout",
        "robust_search",
        "horizon_audit",
        "synthesis",
        "preseason_role_scenario",
        "preseason_role_threshold",
        "availability_watch",
    ]
    runtime_reports = {path.name for path in (tmp_path / "staging").rglob("runtime-reports/*.md")}
    assert runtime_reports == {
        "residual-tournament.md",
        "component-selection.md",
        "component-holdout.md",
        "robust-search.md",
        "horizon-audit.md",
    }


def test_failed_staged_gate_does_not_replace_active_gw1_decision(tmp_path: Path) -> None:
    kwargs, _, _ = _kwargs(tmp_path)
    active = Path(kwargs["published_decision_path"])
    active.write_bytes(b"previous-good-decision")
    kwargs["evidence_auditor"] = lambda **_: {
        "publishable": False,
        "issues": ["stale forecast"],
    }

    result = run_gw1_deadline_pipeline(**kwargs)

    assert result["status"] == "blocked"
    assert result["published"] is False
    assert active.read_bytes() == b"previous-good-decision"


def test_stale_staged_availability_cannot_replace_active_gw1_decision(
    tmp_path: Path,
) -> None:
    kwargs, _, _ = _kwargs(tmp_path)
    active = Path(kwargs["published_decision_path"])
    active.write_bytes(b"previous-good-decision")

    def stale_availability(**kwargs: Any) -> dict[str, Any]:
        result = {
            "status": "refresh_required",
            "current": False,
            "issues": ["role receipt predates the official snapshot"],
        }
        if kwargs.get("output_path") is not None:
            Path(kwargs["output_path"]).write_text(json.dumps(result) + "\n", encoding="utf-8")
        return result

    kwargs["availability_auditor"] = stale_availability

    with pytest.raises(PreseasonPipelineError, match="staged availability watch"):
        run_gw1_deadline_pipeline(**kwargs)

    assert active.read_bytes() == b"previous-good-decision"


def test_stale_role_evidence_is_repaired_before_expensive_stages(tmp_path: Path) -> None:
    kwargs, calls, _ = _kwargs(tmp_path)
    validation_calls = 0

    def validator(**_: Any) -> dict[str, Any]:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            raise ValueError("stale FPL mapping generation")
        return {"status": "current", "role_evidence_sha256": "repaired"}

    def refresher() -> dict[str, Any]:
        calls.append("role_evidence_refresh")
        return {"created_at": "2026-08-07T11:30:01+00:00"}

    kwargs["role_lineage_validator"] = validator
    kwargs["role_evidence_refresher"] = refresher

    result = run_gw1_deadline_pipeline(**kwargs)

    assert result["status"] == "published"
    assert validation_calls == 2
    assert calls[:3] == ["refresh", "role_evidence_refresh", "initial_squad"]


def test_role_evidence_refresh_failure_stops_before_tournaments(tmp_path: Path) -> None:
    kwargs, calls, _ = _kwargs(tmp_path)

    def stale(**_: Any) -> dict[str, Any]:
        raise ValueError("stale FPL mapping generation")

    def failed_refresh() -> dict[str, Any]:
        calls.append("role_evidence_refresh")
        raise RuntimeError("lineup source unavailable")

    kwargs["role_lineage_validator"] = stale
    kwargs["role_evidence_refresher"] = failed_refresh

    with pytest.raises(PreseasonPipelineError) as caught:
        run_gw1_deadline_pipeline(**kwargs)

    assert caught.value.code == "preseason_role_evidence_refresh_failed"
    assert caught.value.retryable is True
    assert calls == ["refresh", "role_evidence_refresh"]


def test_failed_final_recheck_rolls_back_all_published_gw1_artifacts(
    tmp_path: Path,
) -> None:
    kwargs, _, _ = _kwargs(tmp_path)
    tracked = {
        "decision": Path(kwargs["published_decision_path"]),
        "results": Path(kwargs["published_results_path"]),
        "report": Path(kwargs["published_report_path"]),
        "status": Path(kwargs["deadline_status_path"]),
    }
    for name, path in tracked.items():
        path.write_bytes(f"previous-{name}".encode())
    audit_calls = 0

    def auditor(**kwargs: Any) -> dict[str, Any]:
        nonlocal audit_calls
        audit_calls += 1
        passed = audit_calls == 1
        if kwargs.get("output_path") is not None:
            Path(kwargs["output_path"]).write_text("bad-status", encoding="utf-8")
        return {"publishable": passed, "issues": [] if passed else ["race detected"]}

    kwargs["evidence_auditor"] = auditor

    with pytest.raises(PreseasonPipelineError, match="final evidence recheck"):
        run_gw1_deadline_pipeline(**kwargs)

    for name, path in tracked.items():
        assert path.read_bytes() == f"previous-{name}".encode()
    receipt = json.loads(Path(kwargs["pipeline_receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["rolled_back"] is True


def test_failed_prospective_freeze_rolls_back_published_gw1_artifacts(
    tmp_path: Path,
) -> None:
    kwargs, _, _ = _kwargs(tmp_path)
    tracked = {
        "decision": Path(kwargs["published_decision_path"]),
        "results": Path(kwargs["published_results_path"]),
        "report": Path(kwargs["published_report_path"]),
        "status": Path(kwargs["deadline_status_path"]),
    }
    for name, path in tracked.items():
        path.write_bytes(f"previous-{name}".encode())

    def failed_freezer(**_: Any) -> dict[str, Any]:
        raise ValueError("contract freeze failed")

    kwargs["prospective_freezer"] = failed_freezer
    with pytest.raises(ValueError, match="contract freeze failed"):
        run_gw1_deadline_pipeline(**kwargs)

    for name, path in tracked.items():
        assert path.read_bytes() == f"previous-{name}".encode()
    receipt = json.loads(Path(kwargs["pipeline_receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["rolled_back"] is True


def test_gw1_deadline_run_is_exposed_as_one_engine_command() -> None:
    args = parser().parse_args(
        ["gw1-deadline-run", "--reuse-latest-official", "--stability-samples", "7"]
    )

    assert args.command == "gw1-deadline-run"
    assert args.reuse_latest_official is True
    assert args.stability_samples == 7
