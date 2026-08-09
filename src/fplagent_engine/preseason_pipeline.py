from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS
from fplagent_data.preseason_lineups import collect_preseason_lineups

from .availability_watch import PLAYERS as OFFICIAL_PLAYERS
from .availability_watch import RECEIPT as AVAILABILITY_WATCH_RECEIPT
from .availability_watch import audit_availability_watch
from .component_candidates import generate_component_candidates
from .component_models import CURRENT_COMPONENT_FORECAST
from .component_simulator import run_component_tournament
from .deadline_evidence import DEADLINE_STATUS_RECEIPT, audit_deadline_evidence
from .deadline_pipeline import (
    _atomic_json,
    _atomic_publish,
    _aware,
    _fingerprint,
    _generation_time,
    _read_json,
    _restore_published,
    _rules_hash,
    refresh_current_generation,
)
from .decision_synthesis import (
    DECISION_JSON as SYNTHESIZED_DECISION,
)
from .decision_synthesis import (
    REPORT as SYNTHESIZED_REPORT,
)
from .decision_synthesis import (
    RESULTS_JSON as SYNTHESIZED_RESULTS,
)
from .decision_synthesis import run_decision_synthesis
from .horizon_audit import run_horizon_audit
from .models import CURRENT_FORECAST
from .optimizer import select_initial_squad
from .paths import DECISIONS
from .preseason_role_scenario import REPORT as ROLE_SCENARIO_REPORT
from .preseason_role_scenario import RESULTS_JSON as ROLE_SCENARIO_RESULTS
from .preseason_role_scenario import (
    ROLE_EVIDENCE,
    ROLE_RECEIPT,
    run_preseason_role_scenario_audit,
    validate_preseason_role_lineage,
)
from .preseason_role_threshold import REPORT as ROLE_THRESHOLD_REPORT
from .preseason_role_threshold import RESULTS_JSON as ROLE_THRESHOLD_RESULTS
from .preseason_role_threshold import run_preseason_role_threshold_audit
from .prospective_contract import freeze_gw1_prospective_contract
from .robust_search import run_robust_search
from .rules import SquadRules, load_rules
from .tournament import run_tournament

PIPELINE_VERSION = 1
GW1_STAGING_ROOT = DECISIONS / "staging" / "gw1"
GW1_PIPELINE_RECEIPT = MANIFESTS / "fpl-gw1-deadline-pipeline.json"

TOURNAMENT_CONFIG = {
    "candidate_count": 128,
    "selection_simulations": 5_000,
    "holdout_simulations": 25_000,
    "seed": 20260802,
}
COMPONENT_SELECTION_CONFIG = {
    "simulations": 5_000,
    "seed": 20260802,
    "force_goal_model": False,
}
COMPONENT_HOLDOUT_CONFIG = {
    "simulations": 25_000,
    "seed": 20260803,
    "force_goal_model": False,
}
ROBUST_CONFIG = {
    "discovery_candidates": 10_000,
    "screen_simulations": 2_000,
    "shortlist": 512,
    "selection_simulations": 5_000,
    "finalists": 64,
    "holdout_simulations": 25_000,
    "discovery_seed": 20260804,
    "selection_seed": 20260805,
    "holdout_seed": 20260806,
    "stress_goal_multiplier": 1.15,
    "global_restarts": 256,
    "evolution_population": 256,
    "evolution_generations": 10,
    "evolution_offspring": 2_048,
    "minimum_seed_distance": 3,
}
HORIZON_CONFIG = {
    "horizon_candidates": 128,
    "selection_simulations": 5_000,
    "finalists": 48,
    "holdout_simulations": 25_000,
    "candidate_seed": 20260807,
    "selection_seed": 20260808,
    "holdout_seed": 20260809,
}
SYNTHESIS_CONFIG = {"horizon_family_weight": 0.50, "family_worst_weight": 0.20}
ROLE_SCENARIO_CONFIG = {
    "selection_simulations": 5_000,
    "holdout_simulations": 25_000,
    "finalists": 64,
    "selection_seed": 20260812,
    "holdout_seed": 20260813,
}
ROLE_THRESHOLD_CONFIG = {
    "selection_simulations": 5_000,
    "holdout_simulations": 25_000,
    "selection_seed": 20260814,
    "holdout_seed": 20260815,
}
GW1_STAGE_ORDER = (
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
)


class PreseasonPipelineError(ValueError):
    """The GW1 deadline pipeline cannot safely proceed or publish."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "preseason_pipeline_blocked",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _implementation_hash() -> str:
    files = {
        Path(__file__).resolve(),
        Path(select_initial_squad.__code__.co_filename).resolve(),
        Path(run_tournament.__code__.co_filename).resolve(),
        Path(run_component_tournament.__code__.co_filename).resolve(),
        Path(generate_component_candidates.__code__.co_filename).resolve(),
        Path(run_robust_search.__code__.co_filename).resolve(),
        Path(run_horizon_audit.__code__.co_filename).resolve(),
        Path(run_decision_synthesis.__code__.co_filename).resolve(),
        Path(run_preseason_role_scenario_audit.__code__.co_filename).resolve(),
        Path(run_preseason_role_threshold_audit.__code__.co_filename).resolve(),
        Path(audit_availability_watch.__code__.co_filename).resolve(),
        Path(freeze_gw1_prospective_contract.__code__.co_filename).resolve(),
    }
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _compact_stage(name: str, result: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"name": name, "status": "completed"}
    if name == "initial_squad":
        summary.update(
            budget_spent=result.get("budget_spent"),
            bank=result.get("bank"),
            gw1_expected_points=(result.get("gameweeks") or {}).get("1", {}).get("expected_points"),
        )
    elif name == "residual_tournament":
        summary["recommended_candidate"] = (result.get("recommendation") or {}).get("candidate_id")
    elif name in {"component_selection", "component_holdout"}:
        summary["recommended_candidate"] = result.get("recommended_candidate")
        summary["promotion_status"] = (result.get("promotion_gate") or {}).get("status")
    elif name == "component_candidates":
        summary["candidate_count"] = result.get("candidate_count")
    elif name == "robust_search":
        summary["leader"] = (result.get("leader") or {}).get("candidate_id")
    elif name == "horizon_audit":
        summary["leader"] = (result.get("leader") or {}).get("candidate_id")
        summary["verdict"] = result.get("verdict")
    elif name == "synthesis":
        summary["leader"] = (result.get("decision") or {}).get("candidate_id")
        summary["verdict"] = result.get("verdict")
    elif name == "preseason_role_scenario":
        summary["verdict"] = result.get("verdict")
        summary["supported_deep_squad_scenarios"] = result.get("supported_deep_squad_scenarios")
    elif name == "preseason_role_threshold":
        summary["verdict"] = result.get("verdict")
        summary["boundary"] = result.get("boundary")
    elif name == "availability_watch":
        summary["evidence_status"] = result.get("status")
        summary["current"] = result.get("current")
        summary["summary"] = result.get("summary")
    return summary


def _record_progress(
    receipt_path: Path,
    *,
    checked_at: str,
    input_fingerprint: str,
    input_identity: Mapping[str, Any],
    stages: list[dict[str, Any]],
    current_stage: str | None,
) -> None:
    _atomic_json(
        receipt_path,
        {
            "pipeline_version": PIPELINE_VERSION,
            "status": "running",
            "checked_at": checked_at,
            "input_fingerprint": input_fingerprint,
            "input_identity": input_identity,
            "stages": stages,
            "current_stage": current_stage,
            "completed_stage_count": len(stages),
            "total_stages": len(GW1_STAGE_ORDER),
            "published": False,
        },
    )


def _call_with_report_path(
    runner: Callable[..., Mapping[str, Any]],
    *args: Any,
    report_path: Path,
    **kwargs: Any,
) -> Mapping[str, Any]:
    """Redirect runtime prose when a runner supports an explicit report destination."""
    parameters = inspect.signature(runner).parameters.values()
    if any(
        parameter.name == "report_path" or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    ):
        kwargs["report_path"] = report_path
    return runner(*args, **kwargs)


def _ensure_role_evidence_current(
    *,
    role_receipt_path: Path,
    role_evidence_path: Path,
    validator: Callable[..., Mapping[str, Any]],
    refresher: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        return {
            "refreshed": False,
            **dict(
                validator(
                    role_receipt_path=role_receipt_path,
                    role_evidence_path=role_evidence_path,
                )
            ),
        }
    except (KeyError, OSError, ValueError) as stale_error:
        print(
            "GW1 pipeline: preseason role evidence is stale; refreshing it before simulations",
            flush=True,
        )
        try:
            refresh = dict(refresher())
        except Exception as refresh_error:
            raise PreseasonPipelineError(
                "Preseason role evidence is stale and its source refresh failed before any "
                f"tournament started: {refresh_error}",
                code="preseason_role_evidence_refresh_failed",
                retryable=True,
            ) from refresh_error
        try:
            current = dict(
                validator(
                    role_receipt_path=role_receipt_path,
                    role_evidence_path=role_evidence_path,
                )
            )
        except (KeyError, OSError, ValueError) as validation_error:
            raise PreseasonPipelineError(
                "Preseason role evidence remained incoherent after refresh; expensive "
                f"simulation was not started: {validation_error}",
                code="preseason_role_evidence_incoherent",
                retryable=False,
            ) from validation_error
        return {
            "refreshed": True,
            "previous_issue": str(stale_error),
            "refresh_created_at": refresh.get("created_at"),
            **current,
        }


def run_gw1_deadline_pipeline(
    *,
    as_of: str | None = None,
    reuse_latest_official: bool = False,
    stability_samples: int = 20,
    direct_forecast_path: Path = CURRENT_FORECAST,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
    published_decision_path: Path = SYNTHESIZED_DECISION,
    published_results_path: Path = SYNTHESIZED_RESULTS,
    published_report_path: Path = SYNTHESIZED_REPORT,
    staging_root: Path = GW1_STAGING_ROOT,
    pipeline_receipt_path: Path = GW1_PIPELINE_RECEIPT,
    deadline_status_path: Path = DEADLINE_STATUS_RECEIPT,
    official_players_path: Path = OFFICIAL_PLAYERS,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    published_role_scenario_path: Path = ROLE_SCENARIO_RESULTS,
    published_role_scenario_report_path: Path = ROLE_SCENARIO_REPORT,
    published_role_threshold_path: Path = ROLE_THRESHOLD_RESULTS,
    published_role_threshold_report_path: Path = ROLE_THRESHOLD_REPORT,
    availability_watch_path: Path = AVAILABILITY_WATCH_RECEIPT,
    refresh_runner: Callable[..., Mapping[str, Any]] = refresh_current_generation,
    initial_squad_runner: Callable[..., Mapping[str, Any]] = select_initial_squad,
    tournament_runner: Callable[..., Mapping[str, Any]] = run_tournament,
    component_tournament_runner: Callable[..., Mapping[str, Any]] = run_component_tournament,
    component_candidate_runner: Callable[..., Mapping[str, Any]] = generate_component_candidates,
    robust_runner: Callable[..., Mapping[str, Any]] = run_robust_search,
    horizon_runner: Callable[..., Mapping[str, Any]] = run_horizon_audit,
    synthesis_runner: Callable[..., Mapping[str, Any]] = run_decision_synthesis,
    role_scenario_runner: Callable[..., Mapping[str, Any]] = (run_preseason_role_scenario_audit),
    role_threshold_runner: Callable[..., Mapping[str, Any]] = (run_preseason_role_threshold_audit),
    role_lineage_validator: Callable[..., Mapping[str, Any]] = (validate_preseason_role_lineage),
    role_evidence_refresher: Callable[[], Mapping[str, Any]] = (collect_preseason_lineups),
    availability_auditor: Callable[..., Mapping[str, Any]] = audit_availability_watch,
    evidence_auditor: Callable[..., Mapping[str, Any]] = audit_deadline_evidence,
    prospective_freezer: Callable[..., Mapping[str, Any]] = freeze_gw1_prospective_contract,
    rules_loader: Callable[[], SquadRules] = load_rules,
) -> dict[str, Any]:
    checked = _aware(as_of)
    checked_text = checked.isoformat()
    if stability_samples < 1:
        raise PreseasonPipelineError("stability_samples must be positive")

    refresh = dict(
        refresh_runner(
            reuse_latest_official=reuse_latest_official,
            horizon=8,
            as_of=checked_text,
        )
    )
    for path, label in (
        (direct_forecast_path, "direct forecast"),
        (component_forecast_path, "component forecast"),
    ):
        if not path.is_file():
            raise PreseasonPipelineError(f"{label} is missing after refresh: {path}")

    role_preflight = _ensure_role_evidence_current(
        role_receipt_path=role_receipt_path,
        role_evidence_path=role_evidence_path,
        validator=role_lineage_validator,
        refresher=role_evidence_refresher,
    )
    print(
        "GW1 pipeline: preseason role evidence "
        + ("refreshed and passed preflight" if role_preflight["refreshed"] else "passed preflight"),
        flush=True,
    )

    rules = rules_loader()
    decision_created_at = _generation_time(
        direct_forecast_path,
        component_forecast_path,
        minimum=datetime(1970, 1, 1, tzinfo=UTC),
    ).isoformat()
    input_identity = {
        "pipeline_version": PIPELINE_VERSION,
        "season": "2026-27",
        "event": 1,
        "direct_forecast_sha256": sha256_file(direct_forecast_path),
        "component_forecast_sha256": sha256_file(component_forecast_path),
        "market_goal_rate_status": (refresh.get("market_goal_rates") or {}).get("status"),
        "market_goal_rate_raw_sha256": (refresh.get("market_goal_rates") or {}).get("raw_sha256"),
        "market_goal_rate_rates_sha256": (refresh.get("market_goal_rates") or {}).get(
            "rates_sha256"
        ),
        "market_goal_rate_ready_events": (refresh.get("market_goal_rates") or {}).get(
            "ready_events", []
        ),
        "runtime_rules_sha256": _rules_hash(rules),
        "implementation_sha256": _implementation_hash(),
        "stability_samples": stability_samples,
        "tournament": TOURNAMENT_CONFIG,
        "component_selection": COMPONENT_SELECTION_CONFIG,
        "component_holdout": COMPONENT_HOLDOUT_CONFIG,
        "robust": ROBUST_CONFIG,
        "horizon": HORIZON_CONFIG,
        "synthesis": SYNTHESIS_CONFIG,
        "preseason_role_scenario": ROLE_SCENARIO_CONFIG,
        "preseason_role_threshold": ROLE_THRESHOLD_CONFIG,
        "role_receipt_sha256": sha256_file(role_receipt_path),
        "role_evidence_sha256": sha256_file(role_evidence_path),
        "decision_created_at": decision_created_at,
    }
    input_fingerprint = _fingerprint(input_identity)
    previous = _read_json(pipeline_receipt_path)
    published_paths = {
        "decision": published_decision_path,
        "results": published_results_path,
        "report": published_report_path,
        "role_scenario": published_role_scenario_path,
        "role_scenario_report": published_role_scenario_report_path,
        "role_threshold": published_role_threshold_path,
        "role_threshold_report": published_role_threshold_report_path,
        "availability_watch": availability_watch_path,
    }
    if (
        previous
        and previous.get("status") == "published"
        and previous.get("input_fingerprint") == input_fingerprint
        and all(path.is_file() for path in published_paths.values())
        and all(
            previous.get("published_artifacts", {}).get(name, {}).get("sha256") == sha256_file(path)
            for name, path in published_paths.items()
        )
        and Path(str(previous.get("prospective_contract", {}).get("path", ""))).is_file()
        and previous.get("prospective_contract", {}).get("sha256")
        == sha256_file(Path(str(previous["prospective_contract"]["path"])))
    ):
        current_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=None,
                direct_forecast_path=direct_forecast_path,
                component_forecast_path=component_forecast_path,
                decision_path=published_decision_path,
                output_path=None,
            )
        )
        current_availability = dict(
            availability_auditor(
                as_of=checked_text,
                players_path=official_players_path,
                forecast_path=direct_forecast_path,
                decision_path=published_decision_path,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                scenario_results_path=published_role_scenario_path,
                threshold_results_path=published_role_threshold_path,
                output_path=None,
            )
        )
        if current_gate.get("publishable") and current_availability.get("current"):
            print("GW1 pipeline: reusing the current publishable generation", flush=True)
            return {
                **previous,
                "checked_at": checked_text,
                "availability_watch": current_availability,
                "reused": True,
            }

    stage_dir = staging_root / input_fingerprint[:16]
    staged_decision = stage_dir / "decision.json"
    staged_results = stage_dir / "results.json"
    staged_report = stage_dir / "report.md"
    staged_role_scenario = stage_dir / "preseason-role-scenario.json"
    staged_role_scenario_report = stage_dir / "preseason-role-scenario.md"
    staged_role_threshold = stage_dir / "preseason-role-threshold.json"
    staged_role_threshold_report = stage_dir / "preseason-role-threshold.md"
    staged_availability_watch = stage_dir / "availability-watch.json"
    runtime_reports = stage_dir / "runtime-reports"
    stages: list[dict[str, Any]] = []
    _record_progress(
        pipeline_receipt_path,
        checked_at=checked_text,
        input_fingerprint=input_fingerprint,
        input_identity=input_identity,
        stages=stages,
        current_stage=GW1_STAGE_ORDER[0],
    )

    runners: list[tuple[str, Callable[[], Mapping[str, Any]]]] = [
        (
            "initial_squad",
            lambda: _call_with_report_path(
                initial_squad_runner,
                stability_samples,
                report_path=runtime_reports / "initial-squad.md",
            ),
        ),
        (
            "residual_tournament",
            lambda: _call_with_report_path(
                tournament_runner,
                **TOURNAMENT_CONFIG,
                report_path=runtime_reports / "residual-tournament.md",
            ),
        ),
        (
            "component_selection",
            lambda: _call_with_report_path(
                component_tournament_runner,
                **COMPONENT_SELECTION_CONFIG,
                report_path=runtime_reports / "component-selection.md",
            ),
        ),
        ("component_candidates", component_candidate_runner),
        (
            "component_holdout",
            lambda: _call_with_report_path(
                component_tournament_runner,
                **COMPONENT_HOLDOUT_CONFIG,
                report_path=runtime_reports / "component-holdout.md",
            ),
        ),
        (
            "robust_search",
            lambda: _call_with_report_path(
                robust_runner,
                **ROBUST_CONFIG,
                report_path=runtime_reports / "robust-search.md",
            ),
        ),
        (
            "horizon_audit",
            lambda: _call_with_report_path(
                horizon_runner,
                **HORIZON_CONFIG,
                report_path=runtime_reports / "horizon-audit.md",
            ),
        ),
        (
            "synthesis",
            lambda: synthesis_runner(
                **SYNTHESIS_CONFIG,
                results_path=staged_results,
                decision_path=staged_decision,
                report_path=staged_report,
                created_at=decision_created_at,
            ),
        ),
        (
            "preseason_role_scenario",
            lambda: role_scenario_runner(
                **ROLE_SCENARIO_CONFIG,
                decision_path=staged_decision,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                results_path=staged_role_scenario,
                report_path=staged_role_scenario_report,
            ),
        ),
        (
            "preseason_role_threshold",
            lambda: role_threshold_runner(
                **ROLE_THRESHOLD_CONFIG,
                scenario_results_path=staged_role_scenario,
                decision_path=staged_decision,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                results_path=staged_role_threshold,
                report_path=staged_role_threshold_report,
            ),
        ),
        (
            "availability_watch",
            lambda: availability_auditor(
                as_of=checked_text,
                players_path=official_players_path,
                forecast_path=direct_forecast_path,
                decision_path=staged_decision,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                scenario_results_path=staged_role_scenario,
                threshold_results_path=staged_role_threshold,
                output_path=staged_availability_watch,
            ),
        ),
    ]
    try:
        for stage_index, (name, runner) in enumerate(runners):
            _record_progress(
                pipeline_receipt_path,
                checked_at=checked_text,
                input_fingerprint=input_fingerprint,
                input_identity=input_identity,
                stages=stages,
                current_stage=name,
            )
            print(f"GW1 pipeline: starting {name.replace('_', ' ')}", flush=True)
            result = dict(runner())
            if name == "availability_watch" and not result.get("current"):
                raise PreseasonPipelineError(
                    "the staged availability watch is stale or incoherent: "
                    + "; ".join(map(str, result.get("issues") or []))
                )
            stages.append(_compact_stage(name, result))
            _record_progress(
                pipeline_receipt_path,
                checked_at=checked_text,
                input_fingerprint=input_fingerprint,
                input_identity=input_identity,
                stages=stages,
                current_stage=(
                    runners[stage_index + 1][0] if stage_index + 1 < len(runners) else None
                ),
            )
            print(f"GW1 pipeline: completed {name.replace('_', ' ')}", flush=True)
    except Exception as exc:
        _atomic_json(
            pipeline_receipt_path,
            {
                "pipeline_version": PIPELINE_VERSION,
                "status": "failed",
                "checked_at": checked_text,
                "input_fingerprint": input_fingerprint,
                "input_identity": input_identity,
                "stages": stages,
                "published": False,
                "message": f"GW1 pipeline failed before publication: {exc}",
            },
        )
        raise

    try:
        for path in (
            staged_decision,
            staged_results,
            staged_report,
            staged_role_scenario,
            staged_role_scenario_report,
            staged_role_threshold,
            staged_role_threshold_report,
            staged_availability_watch,
        ):
            if not path.is_file():
                raise PreseasonPipelineError(f"synthesis did not create staged artifact: {path}")
        staged_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=None,
                direct_forecast_path=direct_forecast_path,
                component_forecast_path=component_forecast_path,
                decision_path=staged_decision,
                output_path=None,
            )
        )
    except Exception as exc:
        _atomic_json(
            pipeline_receipt_path,
            {
                "pipeline_version": PIPELINE_VERSION,
                "status": "failed",
                "checked_at": checked_text,
                "input_fingerprint": input_fingerprint,
                "input_identity": input_identity,
                "stages": stages,
                "published": False,
                "message": f"GW1 staged evidence could not be evaluated: {exc}",
            },
        )
        raise
    if not staged_gate.get("publishable"):
        receipt = {
            "pipeline_version": PIPELINE_VERSION,
            "status": "blocked",
            "checked_at": checked_text,
            "input_fingerprint": input_fingerprint,
            "input_identity": input_identity,
            "stages": stages,
            "staged_decision": str(staged_decision),
            "staged_decision_sha256": sha256_file(staged_decision),
            "evidence": staged_gate,
            "published": False,
            "message": "The staged GW1 decision failed the deadline evidence gate.",
        }
        _atomic_json(pipeline_receipt_path, receipt)
        return receipt

    previous_bytes = {
        name: path.read_bytes() if path.is_file() else None
        for name, path in {
            **published_paths,
            "deadline_status": deadline_status_path,
        }.items()
    }
    try:
        _atomic_publish(staged_results, published_results_path)
        _atomic_publish(staged_report, published_report_path)
        _atomic_publish(staged_decision, published_decision_path)
        _atomic_publish(staged_role_scenario, published_role_scenario_path)
        _atomic_publish(staged_role_scenario_report, published_role_scenario_report_path)
        _atomic_publish(staged_role_threshold, published_role_threshold_path)
        _atomic_publish(staged_role_threshold_report, published_role_threshold_report_path)
        _atomic_publish(staged_availability_watch, availability_watch_path)
        final_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=None,
                direct_forecast_path=direct_forecast_path,
                component_forecast_path=component_forecast_path,
                decision_path=published_decision_path,
                output_path=deadline_status_path,
            )
        )
        if not final_gate.get("publishable") or not deadline_status_path.is_file():
            raise PreseasonPipelineError("published GW1 bytes failed the final evidence recheck")
        final_availability = dict(
            availability_auditor(
                as_of=checked_text,
                players_path=official_players_path,
                forecast_path=direct_forecast_path,
                decision_path=published_decision_path,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                scenario_results_path=published_role_scenario_path,
                threshold_results_path=published_role_threshold_path,
                output_path=availability_watch_path,
            )
        )
        if not final_availability.get("current") or final_availability.get("lineage") != _read_json(
            staged_availability_watch
        ).get("lineage"):
            raise PreseasonPipelineError(
                "published GW1 availability evidence changed during publication"
            )
        prospective_contract = dict(
            prospective_freezer(
                decision_path=published_decision_path,
                forecast_path=direct_forecast_path,
            )
        )
        prospective_contract_path = Path(str(prospective_contract["contract_path"]))
        if not prospective_contract_path.is_file():
            raise PreseasonPipelineError("GW1 prospective contract was not created")
    except Exception as exc:
        for name, path in {
            **published_paths,
            "deadline_status": deadline_status_path,
        }.items():
            _restore_published(path, previous_bytes[name])
        _atomic_json(
            pipeline_receipt_path,
            {
                "pipeline_version": PIPELINE_VERSION,
                "status": "failed",
                "checked_at": checked_text,
                "input_fingerprint": input_fingerprint,
                "input_identity": input_identity,
                "stages": stages,
                "published": False,
                "rolled_back": True,
                "message": f"GW1 final publication failed and was rolled back: {exc}",
            },
        )
        raise

    artifacts = {
        name: {"path": str(path), "sha256": sha256_file(path)}
        for name, path in published_paths.items()
    }
    receipt = {
        "pipeline_version": PIPELINE_VERSION,
        "status": "published",
        "checked_at": checked_text,
        "input_fingerprint": input_fingerprint,
        "input_identity": input_identity,
        "refresh": refresh,
        "stages": stages,
        "staged_decision": str(staged_decision),
        "published_artifacts": artifacts,
        "deadline_evidence": {
            "path": str(deadline_status_path),
            "sha256": sha256_file(deadline_status_path),
        },
        "prospective_contract": {
            "path": str(prospective_contract_path),
            "sha256": sha256_file(prospective_contract_path),
            "fingerprint": prospective_contract["contract_fingerprint"],
            "evaluated_candidates": len(prospective_contract["action_summaries"]),
        },
        "published": True,
        "reused": False,
        "message": "The complete GW1 decision passed every evidence gate and is now active.",
    }
    _atomic_json(pipeline_receipt_path, receipt)
    return receipt
