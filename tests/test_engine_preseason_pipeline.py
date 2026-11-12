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
    participation_receipt = tmp_path / "participation-receipt.json"
    participation_consensus = tmp_path / "participation-consensus.parquet"
    forecast_manifest = tmp_path / "forecast-manifest.json"
    forecast_manifest.write_text("{}\n", encoding="utf-8")
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

    def participation_refresher(**kwargs: Any) -> dict[str, Any]:
        calls.append("participation_consensus")
        Path(kwargs["receipt_path"]).write_text(
            '{"status":"shadow_consensus_ready"}\n', encoding="utf-8"
        )
        pq.write_table(
            pa.Table.from_pylist([{"event": 1, "element": 1}]),
            Path(kwargs["consensus_path"]),
        )
        return {"status": "shadow_consensus_ready", "production_weight": 0.0}

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
            "forecast_manifest_path": forecast_manifest,
            "published_decision_path": tmp_path / "current-decision.json",
            "published_results_path": tmp_path / "current-results.json",
            "published_report_path": tmp_path / "current-report.md",
            "published_configuration_path": tmp_path / "simulation-configuration.json",
            "published_configuration_report_path": tmp_path / "simulation-configuration.md",
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
            "published_robust_report_path": tmp_path / "robust-search.md",
            "published_horizon_report_path": tmp_path / "horizon-audit.md",
            "published_bench_allocation_path": tmp_path / "bench-allocation.json",
            "published_bench_allocation_report_path": tmp_path / "bench-allocation.md",
            "published_structure_stress_path": tmp_path / "structure-stress.json",
            "published_structure_stress_report_path": tmp_path / "structure-stress.md",
            "published_top_player_audit_path": tmp_path / "top-player-audit.json",
            "published_top_player_audit_report_path": tmp_path / "top-player-audit.md",
            "availability_watch_path": tmp_path / "availability-watch.json",
            "participation_receipt_path": participation_receipt,
            "participation_consensus_path": participation_consensus,
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
            "configuration_runner": artifact_runner(
                "simulation_configuration",
                {
                    "verdict": "simulation_champion_promoted_after_independent_holdout",
                    "publishable": True,
                    "production_changed": True,
                    "selection_champion": {"candidate_id": "XI-test"},
                },
            ),
            "bench_allocation_runner": artifact_runner(
                "bench_allocation",
                {
                    "verdict": {
                        "status": "SUPPORTED_AS_ROTATION_SQUAD_NOT_AS_A_DEEP_BENCH_RULE",
                        "promotable": True,
                        "checks": {"targeted_holdout": True},
                    },
                    "targeted_winner": {"candidate_id": "R-test"},
                },
            ),
            "structure_stress_runner": artifact_runner(
                "structure_stress",
                {
                    "verdict": "PASS",
                    "publishable": True,
                    "stress_leader_id": "R-gw1",
                    "supported_reversal": True,
                    "reconciliation": {
                        "passed": True,
                        "status": "gw1_edge_recorded_multiweek_selector_retains_published",
                    },
                },
            ),
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
            "participation_refresher": participation_refresher,
            "availability_auditor": availability_auditor,
            "top_player_auditor": artifact_runner(
                "top_player_omission_audit",
                {
                    "verdict": "PASS_WITH_ROLE_WATCH",
                    "publishable": True,
                    "checks": {"material_omissions_have_deep_counterfactuals": True},
                    "summary": {"material_players": 20},
                },
            ),
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
        "participation_consensus",
        "initial_squad",
        "residual_tournament",
        "component_tournament",
        "component_candidates",
        "component_tournament",
        "robust_search",
        "horizon_audit",
        "synthesis",
        "simulation_configuration",
        "bench_allocation",
        "structure_stress",
        "preseason_role_scenario",
        "preseason_role_threshold",
        "top_player_omission_audit",
        "prospective_freeze",
    ]
    assert calls == [*first_calls, "refresh", "participation_consensus"]
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
        "simulation_configuration",
        "bench_allocation",
        "structure_stress",
        "preseason_role_scenario",
        "preseason_role_threshold",
        "availability_watch",
        "top_player_omission_audit",
    ]


def test_gw1_pipeline_reuses_when_only_forecast_provenance_timestamps_change(
    tmp_path: Path,
) -> None:
    kwargs, calls, _ = _kwargs(tmp_path)

    first = run_gw1_deadline_pipeline(**kwargs)
    heavy_calls = list(calls)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event_number": 1,
                    "element": 1,
                    "snapshot_at": "2026-08-07T12:00:00+00:00",
                    "forecast_created_at": "2026-08-07T12:00:01+00:00",
                }
            ]
        ),
        kwargs["direct_forecast_path"],
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event_number": 1,
                    "element": 1,
                    "snapshot_at": "2026-08-07T12:00:00+00:00",
                    "component_forecast_created_at": "2026-08-07T12:00:02+00:00",
                }
            ]
        ),
        kwargs["component_forecast_path"],
    )

    second = run_gw1_deadline_pipeline(**kwargs)

    assert first["published"] is True
    assert second["reused"] is True
    assert calls == [*heavy_calls, "refresh", "participation_consensus"]
    runtime_reports = {path.name for path in (tmp_path / "staging").rglob("runtime-reports/*.md")}
    assert runtime_reports == {
        "residual-tournament.md",
        "component-selection.md",
        "component-holdout.md",
        "robust-search.md",
        "horizon-audit.md",
    }
    assert Path(kwargs["published_robust_report_path"]).read_text(encoding="utf-8") == (
        "# robust_search\n"
    )
    assert Path(kwargs["published_horizon_report_path"]).read_text(encoding="utf-8") == (
        "# horizon_audit\n"
    )
    assert (
        Path(kwargs["published_structure_stress_report_path"]).read_text(encoding="utf-8")
        == "# structure_stress\n"
    )


def test_interrupted_post_synthesis_run_resumes_without_repeating_search(
    tmp_path: Path,
) -> None:
    kwargs, calls, _ = _kwargs(tmp_path)
    first = run_gw1_deadline_pipeline(**kwargs)
    receipt_path = Path(kwargs["pipeline_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "running"
    receipt["published"] = False
    receipt["stages"] = receipt["stages"][:8]
    receipt["current_stage"] = "bench_allocation"
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    stage_dir = Path(kwargs["staging_root"]) / first["input_fingerprint"][:16]
    for name in (
        "simulation-configuration.json",
        "simulation-configuration.md",
        "bench-allocation.json",
        "bench-allocation.md",
        "structure-stress.json",
        "structure-stress.md",
        "preseason-role-scenario.json",
        "preseason-role-scenario.md",
        "preseason-role-threshold.json",
        "preseason-role-threshold.md",
        "availability-watch.json",
        "top-player-omission-audit.json",
        "top-player-omission-audit.md",
    ):
        (stage_dir / name).unlink(missing_ok=True)
    calls.clear()

    resumed = run_gw1_deadline_pipeline(**kwargs)

    assert resumed["status"] == "published"
    assert calls == [
        "refresh",
        "participation_consensus",
        "simulation_configuration",
        "bench_allocation",
        "structure_stress",
        "preseason_role_scenario",
        "preseason_role_threshold",
        "top_player_omission_audit",
        "prospective_freeze",
    ]
    assert [stage["name"] for stage in resumed["stages"]] == [
        "initial_squad",
        "residual_tournament",
        "component_selection",
        "component_candidates",
        "component_holdout",
        "robust_search",
        "horizon_audit",
        "synthesis",
        "simulation_configuration",
        "bench_allocation",
        "structure_stress",
        "preseason_role_scenario",
        "preseason_role_threshold",
        "availability_watch",
        "top_player_omission_audit",
    ]


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


def test_unstable_simulation_configuration_blocks_publication(tmp_path: Path) -> None:
    kwargs, _, _ = _kwargs(tmp_path)
    active = Path(kwargs["published_decision_path"])
    active.write_bytes(b"previous-good-decision")

    def unstable_configuration(**runner_kwargs: Any) -> dict[str, Any]:
        result = {
            "verdict": "configuration_selection_and_holdout_disagree_publication_blocked",
            "publishable": False,
            "production_changed": False,
            "selection_champion": {"candidate_id": "XI-selection"},
        }
        Path(runner_kwargs["results_path"]).write_text(json.dumps(result) + "\n", encoding="utf-8")
        Path(runner_kwargs["report_path"]).write_text(
            "# unstable configuration\n", encoding="utf-8"
        )
        return result

    kwargs["configuration_runner"] = unstable_configuration

    with pytest.raises(PreseasonPipelineError, match="simulation-authoritative"):
        run_gw1_deadline_pipeline(**kwargs)

    assert active.read_bytes() == b"previous-good-decision"


def test_failed_new_generation_retains_published_forecast_pair(tmp_path: Path) -> None:
    kwargs, _, _ = _kwargs(tmp_path)
    first = run_gw1_deadline_pipeline(**kwargs)
    published_direct = Path(first["published_artifacts"]["direct_forecast"]["path"])
    published_component = Path(first["published_artifacts"]["component_forecast"]["path"])
    prior_direct = published_direct.read_bytes()
    prior_component = published_component.read_bytes()
    pq.write_table(
        pa.Table.from_pylist(
            [{"event_number": 1, "element": 2, "snapshot_at": "2026-08-07T11:30:00+00:00"}]
        ),
        kwargs["direct_forecast_path"],
    )
    kwargs["evidence_auditor"] = lambda **_: {
        "publishable": False,
        "issues": ["new generation rejected"],
    }

    result = run_gw1_deadline_pipeline(**kwargs)

    assert result["status"] == "blocked"
    assert published_direct.read_bytes() == prior_direct
    assert published_component.read_bytes() == prior_component


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
    assert calls[:4] == [
        "refresh",
        "role_evidence_refresh",
        "participation_consensus",
        "initial_squad",
    ]


def test_fresh_official_run_reuses_valid_advisory_role_evidence(
    tmp_path: Path,
) -> None:
    kwargs, calls, _ = _kwargs(tmp_path)
    validation_calls = 0

    def validator(**_: Any) -> dict[str, Any]:
        nonlocal validation_calls
        validation_calls += 1
        return {"status": "current", "role_evidence_sha256": "fresh"}

    def refresher() -> dict[str, Any]:
        calls.append("role_evidence_refresh")
        return {"created_at": "2026-08-07T11:30:01+00:00"}

    kwargs["reuse_latest_official"] = False
    kwargs["role_lineage_validator"] = validator
    kwargs["role_evidence_refresher"] = refresher

    result = run_gw1_deadline_pipeline(**kwargs)

    assert result["status"] == "published"
    assert validation_calls == 1
    assert calls[:3] == ["refresh", "participation_consensus", "initial_squad"]
    assert result["role_evidence_preflight"]["refreshed"] is False


def test_stale_advisory_roles_still_attempt_an_explicit_repair(
    tmp_path: Path,
) -> None:
    kwargs, calls, _ = _kwargs(tmp_path)
    validation_calls = 0

    def validator(**_: Any) -> dict[str, Any]:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            raise ValueError("stale FPL mapping generation")
        return {"status": "current", "role_evidence_sha256": "repaired"}

    def repair() -> dict[str, Any]:
        calls.append("role_evidence_refresh")
        return {"created_at": "2026-08-07T11:30:01+00:00"}

    kwargs["reuse_latest_official"] = False
    kwargs["role_lineage_validator"] = validator
    kwargs["role_evidence_refresher"] = repair

    result = run_gw1_deadline_pipeline(**kwargs)

    assert result["status"] == "published"
    assert validation_calls == 2
    assert calls[:4] == [
        "refresh",
        "role_evidence_refresh",
        "participation_consensus",
        "initial_squad",
    ]
    assert result["role_evidence_preflight"]["refreshed"] is True


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
        "robust": Path(kwargs["published_robust_report_path"]),
        "horizon": Path(kwargs["published_horizon_report_path"]),
        "structure": Path(kwargs["published_structure_stress_path"]),
        "structure_report": Path(kwargs["published_structure_stress_report_path"]),
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
        "robust": Path(kwargs["published_robust_report_path"]),
        "horizon": Path(kwargs["published_horizon_report_path"]),
        "structure": Path(kwargs["published_structure_stress_path"]),
        "structure_report": Path(kwargs["published_structure_stress_report_path"]),
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
