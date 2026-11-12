from __future__ import annotations

import hashlib
import inspect
import resource
import shutil
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file
from fplagent_data.participation_consensus import CONSENSUS as PARTICIPATION_CONSENSUS
from fplagent_data.participation_consensus import RECEIPT as PARTICIPATION_RECEIPT
from fplagent_data.participation_consensus import collect_participation_consensus
from fplagent_data.paths import MANIFESTS
from fplagent_data.preseason_lineups import collect_preseason_lineups

from .availability_watch import PLAYERS as OFFICIAL_PLAYERS
from .availability_watch import RECEIPT as AVAILABILITY_WATCH_RECEIPT
from .availability_watch import audit_availability_watch
from .bench_allocation_audit import REPORT as BENCH_ALLOCATION_REPORT
from .bench_allocation_audit import RESULTS_JSON as BENCH_ALLOCATION_RESULTS
from .bench_allocation_audit import run_bench_allocation_audit
from .component_candidates import generate_component_candidates
from .component_models import CURRENT_COMPONENT_FORECAST
from .component_simulator import run_component_tournament
from .current_squad_audit import REPORT as CONFIGURATION_REPORT
from .current_squad_audit import RESULTS_JSON as CONFIGURATION_RESULTS
from .current_squad_audit import run_current_squad_audit
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
from .horizon_audit import REPORT as HORIZON_REPORT
from .horizon_audit import run_horizon_audit
from .market_odds import CURRENT_MARKET_RATES
from .models import CURRENT_FORECAST, CURRENT_FORECAST_MANIFEST
from .optimizer import select_initial_squad
from .paths import DECISIONS
from .preseason_role_scenario import REPORT as ROLE_SCENARIO_REPORT
from .preseason_role_scenario import RESULTS_JSON as ROLE_SCENARIO_RESULTS
from .preseason_role_scenario import (
    ROLE_EVIDENCE,
    ROLE_RECEIPT,
    consume_role_scenario_worker_cpu_seconds,
    run_preseason_role_scenario_audit,
    validate_preseason_role_lineage,
)
from .preseason_role_threshold import REPORT as ROLE_THRESHOLD_REPORT
from .preseason_role_threshold import RESULTS_JSON as ROLE_THRESHOLD_RESULTS
from .preseason_role_threshold import run_preseason_role_threshold_audit
from .prospective_contract import freeze_gw1_prospective_contract
from .robust_search import REPORT as ROBUST_REPORT
from .robust_search import run_robust_search
from .rules import SquadRules, load_rules
from .semantic_hash import semantic_parquet_sha256
from .structure_stress import REPORT as STRUCTURE_STRESS_REPORT
from .structure_stress import RESULTS_JSON as STRUCTURE_STRESS_RESULTS
from .structure_stress import run_structure_stress
from .top_player_audit import REPORT as TOP_PLAYER_AUDIT_REPORT
from .top_player_audit import RESULTS_JSON as TOP_PLAYER_AUDIT_RESULTS
from .top_player_audit import run_top_player_omission_audit
from .tournament import run_tournament

PIPELINE_VERSION = 3
GW1_STAGING_ROOT = DECISIONS / "staging" / "gw1"
GW1_PIPELINE_RECEIPT = MANIFESTS / "fpl-gw1-deadline-pipeline.json"
PUBLISHED_FORECAST_ROOT = DECISIONS / "published" / "gw1"
PUBLISHED_DIRECT_FORECAST = PUBLISHED_FORECAST_ROOT / "direct-forecast.parquet"
PUBLISHED_COMPONENT_FORECAST = PUBLISHED_FORECAST_ROOT / "component-forecast.parquet"
PUBLISHED_FORECAST_MANIFEST = PUBLISHED_FORECAST_ROOT / "direct-forecast-manifest.json"
PUBLISHED_PARTICIPATION_RECEIPT = PUBLISHED_FORECAST_ROOT / "participation-receipt.json"
PUBLISHED_PARTICIPATION_CONSENSUS = PUBLISHED_FORECAST_ROOT / "participation-consensus.parquet"

DIRECT_VOLATILE_COLUMNS = frozenset({"snapshot_at", "model_created_at", "forecast_created_at"})
COMPONENT_VOLATILE_COLUMNS = frozenset(
    {
        "snapshot_at",
        "model_created_at",
        "forecast_created_at",
        "component_model_created_at",
        "component_forecast_created_at",
        "direct_forecast_sha256",
        "component_model_sha256",
    }
)
ROLE_VOLATILE_COLUMNS = frozenset({"observed_at"})
MARKET_VOLATILE_COLUMNS = frozenset(
    {
        "source_uploaded_at",
        "source_observed_at",
        "betfair_match_last_match_at",
        "betfair_totals_last_match_at",
    }
)

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
BENCH_ALLOCATION_CONFIG = {
    "simulations": 25_000,
    "five_week_seed": 20260818,
    "eight_week_seed": 20260820,
    "top_historical_band": 24,
}
STRUCTURE_STRESS_CONFIG = {
    "selection_simulations": 2_000,
    "holdout_simulations": 10_000,
    "selection_seed": 20260831,
    "holdout_seed": 20260901,
}
ROLE_SCENARIO_CONFIG = {
    "selection_simulations": 5_000,
    "holdout_simulations": 25_000,
    "finalists": 64,
    "selection_seed": 20260812,
    "holdout_seed": 20260813,
}
CONFIGURATION_CONFIG = {
    "selection_simulations": 25_000,
    "holdout_simulations": 25_000,
    "finalists": 64,
    "selection_seed": 20260810,
    "holdout_seed": 20260811,
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
    "simulation_configuration",
    "bench_allocation",
    "structure_stress",
    "preseason_role_scenario",
    "preseason_role_threshold",
    "availability_watch",
    "top_player_omission_audit",
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


def gw1_pipeline_implementation_sha256() -> str:
    """Fingerprint every implementation file that can change the published GW1 receipt."""
    files = {
        Path(__file__).resolve(),
        Path(__file__).with_name("acceleration.py").resolve(),
        Path(__file__).with_name("capital_efficiency.py").resolve(),
        Path(__file__).with_name("semantic_hash.py").resolve(),
        Path(select_initial_squad.__code__.co_filename).resolve(),
        Path(run_tournament.__code__.co_filename).resolve(),
        Path(run_component_tournament.__code__.co_filename).resolve(),
        Path(generate_component_candidates.__code__.co_filename).resolve(),
        Path(run_robust_search.__code__.co_filename).resolve(),
        Path(run_horizon_audit.__code__.co_filename).resolve(),
        Path(run_decision_synthesis.__code__.co_filename).resolve(),
        Path(run_current_squad_audit.__code__.co_filename).resolve(),
        Path(run_bench_allocation_audit.__code__.co_filename).resolve(),
        Path(run_structure_stress.__code__.co_filename).resolve(),
        Path(run_preseason_role_scenario_audit.__code__.co_filename).resolve(),
        Path(run_preseason_role_threshold_audit.__code__.co_filename).resolve(),
        Path(audit_availability_watch.__code__.co_filename).resolve(),
        Path(run_top_player_omission_audit.__code__.co_filename).resolve(),
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
    elif name == "simulation_configuration":
        summary["verdict"] = result.get("verdict")
        summary["publishable"] = result.get("publishable")
        summary["production_changed"] = result.get("production_changed")
        summary["selection_champion"] = (result.get("selection_champion") or {}).get("candidate_id")
        summary["resolved_champion"] = (result.get("resolved_champion") or {}).get("candidate_id")
    elif name == "bench_allocation":
        summary["verdict"] = (result.get("verdict") or {}).get("status")
        summary["publishable"] = (result.get("verdict") or {}).get("promotable")
        summary["targeted_winner"] = (result.get("targeted_winner") or {}).get("candidate_id")
    elif name == "structure_stress":
        summary["leader"] = result.get("stress_leader_id")
        summary["verdict"] = result.get("verdict")
        summary["supported_reversal"] = result.get("supported_reversal")
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
    elif name == "top_player_omission_audit":
        summary["verdict"] = result.get("verdict")
        summary["publishable"] = result.get("publishable")
        summary["summary"] = result.get("summary")
    return summary


def _resumable_evidence_stages(
    previous: Mapping[str, Any] | None,
    *,
    input_fingerprint: str,
    staged_decision: Path,
    staged_results: Path,
    staged_report: Path,
    staged_configuration: Path,
    staged_configuration_report: Path,
    staged_bench_allocation: Path,
    staged_bench_allocation_report: Path,
    staged_structure_stress: Path,
    staged_structure_stress_report: Path,
    staged_role_scenario: Path,
    staged_role_scenario_report: Path,
    staged_role_threshold: Path,
    staged_role_threshold_report: Path,
    staged_availability_watch: Path,
    staged_top_player_audit: Path,
    staged_top_player_audit_report: Path,
) -> list[dict[str, Any]]:
    """Resume only after synthesis, where every dependency has a staged artifact.

    Earlier tournament stages intentionally remain all-or-nothing: several of them publish
    intermediate model artifacts outside the staging directory.  From synthesis onward the
    transaction has complete, lineage-checked files and can safely continue after an interrupted
    web worker without repeating the expensive search.
    """
    if not previous or previous.get("input_fingerprint") != input_fingerprint:
        return []
    raw_stages = previous.get("stages")
    if not isinstance(raw_stages, list):
        return []
    stages = [dict(stage) for stage in raw_stages if isinstance(stage, Mapping)]
    names = [str(stage.get("name") or "") for stage in stages]
    if names != list(GW1_STAGE_ORDER[: len(names)]) or len(names) < 8:
        return []
    required_after_count: dict[int, tuple[Path, ...]] = {
        8: (staged_decision, staged_results, staged_report),
        9: (staged_configuration, staged_configuration_report),
        10: (staged_bench_allocation, staged_bench_allocation_report),
        11: (staged_structure_stress, staged_structure_stress_report),
        12: (staged_role_scenario, staged_role_scenario_report),
        13: (staged_role_threshold, staged_role_threshold_report),
        14: (staged_availability_watch,),
        15: (staged_top_player_audit, staged_top_player_audit_report),
    }
    completed = min(len(stages), len(GW1_STAGE_ORDER))
    for count in range(8, completed + 1):
        if not all(path.is_file() for path in required_after_count.get(count, ())):
            return stages[: count - 1] if count > 8 else []
    return stages[:completed]


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
    refresh_first: bool = False,
) -> dict[str, Any]:
    if refresh_first:
        print(
            "GW1 pipeline: collecting fresh preseason role evidence before simulations",
            flush=True,
        )
        try:
            refresh = dict(refresher())
        except (OSError, RuntimeError, ValueError) as refresh_error:
            try:
                current = dict(
                    validator(
                        role_receipt_path=role_receipt_path,
                        role_evidence_path=role_evidence_path,
                    )
                )
            except (KeyError, OSError, ValueError) as validation_error:
                raise PreseasonPipelineError(
                    "Fresh preseason role evidence could not be collected and the prior "
                    f"snapshot is incoherent: {refresh_error}; {validation_error}",
                    code="preseason_role_evidence_refresh_failed",
                    retryable=True,
                ) from refresh_error
            return {
                "refreshed": False,
                "refresh_attempted": True,
                "refresh_reason": "valid_advisory_fallback",
                "refresh_error": f"{type(refresh_error).__name__}: {refresh_error}",
                **current,
            }
        try:
            current = dict(
                validator(
                    role_receipt_path=role_receipt_path,
                    role_evidence_path=role_evidence_path,
                )
            )
        except (KeyError, OSError, ValueError) as validation_error:
            raise PreseasonPipelineError(
                "Fresh preseason role evidence is incoherent; expensive simulation was not "
                f"started: {validation_error}",
                code="preseason_role_evidence_incoherent",
                retryable=False,
            ) from validation_error
        return {
            "refreshed": True,
            "refresh_reason": "fresh_official_run",
            "refresh_created_at": refresh.get("created_at"),
            **current,
        }
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
    forecast_manifest_path: Path = CURRENT_FORECAST_MANIFEST,
    published_decision_path: Path = SYNTHESIZED_DECISION,
    published_results_path: Path = SYNTHESIZED_RESULTS,
    published_report_path: Path = SYNTHESIZED_REPORT,
    published_configuration_path: Path = CONFIGURATION_RESULTS,
    published_configuration_report_path: Path = CONFIGURATION_REPORT,
    published_direct_forecast_path: Path | None = None,
    published_component_forecast_path: Path | None = None,
    published_forecast_manifest_path: Path | None = None,
    published_participation_receipt_path: Path | None = None,
    published_participation_consensus_path: Path | None = None,
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
    published_robust_report_path: Path = ROBUST_REPORT,
    published_horizon_report_path: Path = HORIZON_REPORT,
    published_bench_allocation_path: Path = BENCH_ALLOCATION_RESULTS,
    published_bench_allocation_report_path: Path = BENCH_ALLOCATION_REPORT,
    published_structure_stress_path: Path = STRUCTURE_STRESS_RESULTS,
    published_structure_stress_report_path: Path = STRUCTURE_STRESS_REPORT,
    availability_watch_path: Path = AVAILABILITY_WATCH_RECEIPT,
    published_top_player_audit_path: Path = TOP_PLAYER_AUDIT_RESULTS,
    published_top_player_audit_report_path: Path = TOP_PLAYER_AUDIT_REPORT,
    participation_receipt_path: Path = PARTICIPATION_RECEIPT,
    participation_consensus_path: Path = PARTICIPATION_CONSENSUS,
    refresh_runner: Callable[..., Mapping[str, Any]] = refresh_current_generation,
    initial_squad_runner: Callable[..., Mapping[str, Any]] = select_initial_squad,
    tournament_runner: Callable[..., Mapping[str, Any]] = run_tournament,
    component_tournament_runner: Callable[..., Mapping[str, Any]] = run_component_tournament,
    component_candidate_runner: Callable[..., Mapping[str, Any]] = generate_component_candidates,
    robust_runner: Callable[..., Mapping[str, Any]] = run_robust_search,
    horizon_runner: Callable[..., Mapping[str, Any]] = run_horizon_audit,
    synthesis_runner: Callable[..., Mapping[str, Any]] = run_decision_synthesis,
    configuration_runner: Callable[..., Mapping[str, Any]] = run_current_squad_audit,
    bench_allocation_runner: Callable[..., Mapping[str, Any]] = run_bench_allocation_audit,
    structure_stress_runner: Callable[..., Mapping[str, Any]] = run_structure_stress,
    role_scenario_runner: Callable[..., Mapping[str, Any]] = (run_preseason_role_scenario_audit),
    role_threshold_runner: Callable[..., Mapping[str, Any]] = (run_preseason_role_threshold_audit),
    role_lineage_validator: Callable[..., Mapping[str, Any]] = (validate_preseason_role_lineage),
    role_evidence_refresher: Callable[[], Mapping[str, Any]] = (collect_preseason_lineups),
    participation_refresher: Callable[..., Mapping[str, Any]] = (collect_participation_consensus),
    availability_auditor: Callable[..., Mapping[str, Any]] = audit_availability_watch,
    top_player_auditor: Callable[..., Mapping[str, Any]] = run_top_player_omission_audit,
    evidence_auditor: Callable[..., Mapping[str, Any]] = audit_deadline_evidence,
    prospective_freezer: Callable[..., Mapping[str, Any]] = freeze_gw1_prospective_contract,
    rules_loader: Callable[[], SquadRules] = load_rules,
) -> dict[str, Any]:
    checked = _aware(as_of)
    checked_text = checked.isoformat()
    if stability_samples < 1:
        raise PreseasonPipelineError("stability_samples must be positive")
    production_publish = (
        published_decision_path == SYNTHESIZED_DECISION
        and direct_forecast_path == CURRENT_FORECAST
        and component_forecast_path == CURRENT_COMPONENT_FORECAST
    )
    published_direct_forecast_path = published_direct_forecast_path or (
        PUBLISHED_DIRECT_FORECAST
        if production_publish
        else published_decision_path.with_name("published-direct-forecast.parquet")
    )
    published_component_forecast_path = published_component_forecast_path or (
        PUBLISHED_COMPONENT_FORECAST
        if production_publish
        else published_decision_path.with_name("published-component-forecast.parquet")
    )
    published_forecast_manifest_path = published_forecast_manifest_path or (
        PUBLISHED_FORECAST_MANIFEST
        if production_publish
        else published_decision_path.with_name("published-direct-forecast-manifest.json")
    )
    published_participation_receipt_path = published_participation_receipt_path or (
        PUBLISHED_PARTICIPATION_RECEIPT
        if production_publish
        else published_decision_path.with_name("published-participation-receipt.json")
    )
    published_participation_consensus_path = published_participation_consensus_path or (
        PUBLISHED_PARTICIPATION_CONSENSUS
        if production_publish
        else published_decision_path.with_name("published-participation-consensus.parquet")
    )

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
        # This friendly-lineup archive is an advisory, zero-weight stress
        # input. Validate its immutable lineage without turning an unpromoted
        # web source into a live dependency of every deadline run. Explicit
        # research collection and the stale-evidence repair path remain.
        refresh_first=False,
    )
    role_preflight_message = (
        "refreshed and passed preflight"
        if role_preflight["refreshed"]
        else (
            "source unavailable; checksum-valid advisory snapshot retained"
            if role_preflight.get("refresh_reason") == "valid_advisory_fallback"
            else "passed preflight"
        )
    )
    print(
        "GW1 pipeline: preseason role evidence " + role_preflight_message,
        flush=True,
    )
    participation_refresh = dict(refresh.get("participation_consensus") or {})
    if not participation_refresh:
        try:
            participation_refresh = dict(
                participation_refresher(
                    event=1,
                    observed_at=checked_text,
                    players_path=official_players_path,
                    forecast_path=direct_forecast_path,
                    receipt_path=participation_receipt_path,
                    consensus_path=participation_consensus_path,
                )
            )
        except (OSError, ValueError) as exc:
            participation_refresh = {
                "status": "unavailable",
                "production_weight": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            }
    print(
        "GW1 pipeline: predicted-lineup evidence "
        f"{participation_refresh.get('status') or 'unavailable'}",
        flush=True,
    )

    # A production forecast that applied lineup evidence is not a standalone file:
    # its manifest names the exact receipt and consensus bytes used to create it.
    # Validate that bundle before spending minutes on the search, then stage and
    # publish all four artifacts together below.
    try:
        forecast_manifest = _read_json(forecast_manifest_path)
        participation_policy = (forecast_manifest or {}).get("result", {}).get(
            "participation_policy"
        ) or {}
        if participation_policy.get("decision_authority"):
            expected_bundle = {
                "forecast": (
                    (forecast_manifest or {}).get("forecast_sha256"),
                    sha256_file(direct_forecast_path),
                ),
                "participation receipt": (
                    participation_policy.get("receipt_sha256"),
                    sha256_file(participation_receipt_path),
                ),
                "participation consensus": (
                    participation_policy.get("consensus_sha256"),
                    sha256_file(participation_consensus_path),
                ),
            }
            mismatches = [
                label for label, (recorded, actual) in expected_bundle.items() if recorded != actual
            ]
            if mismatches:
                raise PreseasonPipelineError(
                    "the production forecast participation bundle is incoherent: "
                    + ", ".join(mismatches)
                )
    except OSError as exc:
        raise PreseasonPipelineError(
            f"the production forecast participation bundle is incomplete: {exc}"
        ) from exc

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
        "forecast_manifest_sha256": sha256_file(forecast_manifest_path),
        "participation_receipt_sha256": sha256_file(participation_receipt_path),
        "participation_consensus_sha256": sha256_file(participation_consensus_path),
        "market_goal_rate_status": (refresh.get("market_goal_rates") or {}).get("status"),
        "market_goal_rate_raw_sha256": (refresh.get("market_goal_rates") or {}).get("raw_sha256"),
        "market_goal_rate_rates_sha256": (refresh.get("market_goal_rates") or {}).get(
            "rates_sha256"
        ),
        "market_goal_rate_ready_events": (refresh.get("market_goal_rates") or {}).get(
            "ready_events", []
        ),
        "runtime_rules_sha256": _rules_hash(rules),
        "implementation_sha256": gw1_pipeline_implementation_sha256(),
        "stability_samples": stability_samples,
        "tournament": TOURNAMENT_CONFIG,
        "component_selection": COMPONENT_SELECTION_CONFIG,
        "component_holdout": COMPONENT_HOLDOUT_CONFIG,
        "robust": ROBUST_CONFIG,
        "horizon": HORIZON_CONFIG,
        "synthesis": SYNTHESIS_CONFIG,
        "simulation_configuration": CONFIGURATION_CONFIG,
        "bench_allocation": BENCH_ALLOCATION_CONFIG,
        "structure_stress": STRUCTURE_STRESS_CONFIG,
        "preseason_role_scenario": ROLE_SCENARIO_CONFIG,
        "preseason_role_threshold": ROLE_THRESHOLD_CONFIG,
        "role_receipt_sha256": sha256_file(role_receipt_path),
        "role_evidence_sha256": sha256_file(role_evidence_path),
        "decision_created_at": decision_created_at,
    }
    fingerprint_identity = {
        "pipeline_version": PIPELINE_VERSION,
        "season": "2026-27",
        "event": 1,
        "direct_forecast_semantic_sha256": semantic_parquet_sha256(
            direct_forecast_path,
            ignored_columns=DIRECT_VOLATILE_COLUMNS,
            sort_columns=("season", "event_number", "element"),
        ),
        "component_forecast_semantic_sha256": semantic_parquet_sha256(
            component_forecast_path,
            ignored_columns=COMPONENT_VOLATILE_COLUMNS,
            sort_columns=("season", "event_number", "element"),
        ),
        "participation_consensus_semantic_sha256": semantic_parquet_sha256(
            participation_consensus_path,
            sort_columns=("season", "event", "element"),
        ),
        "forecast_participation_bundle": {
            "forecast_sha256": (forecast_manifest or {}).get("forecast_sha256"),
            "policy": participation_policy.get("policy"),
            "decision_authority": participation_policy.get("decision_authority"),
            "receipt_sha256": participation_policy.get("receipt_sha256"),
            "consensus_sha256": participation_policy.get("consensus_sha256"),
        },
        "market_goal_rate_status": input_identity["market_goal_rate_status"],
        "market_goal_rate_semantic_sha256": (
            semantic_parquet_sha256(
                CURRENT_MARKET_RATES,
                ignored_columns=MARKET_VOLATILE_COLUMNS,
                sort_columns=("season", "event", "fixture_id"),
            )
            if CURRENT_MARKET_RATES.is_file()
            else None
        ),
        "market_goal_rate_ready_events": input_identity["market_goal_rate_ready_events"],
        "runtime_rules_sha256": input_identity["runtime_rules_sha256"],
        "implementation_sha256": input_identity["implementation_sha256"],
        "stability_samples": stability_samples,
        "tournament": TOURNAMENT_CONFIG,
        "component_selection": COMPONENT_SELECTION_CONFIG,
        "component_holdout": COMPONENT_HOLDOUT_CONFIG,
        "robust": ROBUST_CONFIG,
        "horizon": HORIZON_CONFIG,
        "synthesis": SYNTHESIS_CONFIG,
        "simulation_configuration": CONFIGURATION_CONFIG,
        "bench_allocation": BENCH_ALLOCATION_CONFIG,
        "structure_stress": STRUCTURE_STRESS_CONFIG,
        "preseason_role_scenario": ROLE_SCENARIO_CONFIG,
        "preseason_role_threshold": ROLE_THRESHOLD_CONFIG,
        "role_evidence_semantic_sha256": semantic_parquet_sha256(
            role_evidence_path,
            ignored_columns=ROLE_VOLATILE_COLUMNS,
            sort_columns=("season", "fpl_element"),
        ),
    }
    input_identity["semantic"] = fingerprint_identity
    input_fingerprint = _fingerprint(fingerprint_identity)
    previous = _read_json(pipeline_receipt_path)
    published_paths = {
        "decision": published_decision_path,
        "results": published_results_path,
        "report": published_report_path,
        "simulation_configuration": published_configuration_path,
        "simulation_configuration_report": published_configuration_report_path,
        "role_scenario": published_role_scenario_path,
        "role_scenario_report": published_role_scenario_report_path,
        "role_threshold": published_role_threshold_path,
        "role_threshold_report": published_role_threshold_report_path,
        "robust_report": published_robust_report_path,
        "horizon_report": published_horizon_report_path,
        "bench_allocation": published_bench_allocation_path,
        "bench_allocation_report": published_bench_allocation_report_path,
        "structure_stress": published_structure_stress_path,
        "structure_stress_report": published_structure_stress_report_path,
        "availability_watch": availability_watch_path,
        "top_player_audit": published_top_player_audit_path,
        "top_player_audit_report": published_top_player_audit_report_path,
        "direct_forecast": published_direct_forecast_path,
        "component_forecast": published_component_forecast_path,
        "forecast_manifest": published_forecast_manifest_path,
        "participation_receipt": published_participation_receipt_path,
        "participation_consensus": published_participation_consensus_path,
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
                direct_forecast_path=published_direct_forecast_path,
                component_forecast_path=published_component_forecast_path,
                decision_path=published_decision_path,
                output_path=None,
            )
        )
        current_availability = dict(
            availability_auditor(
                as_of=checked_text,
                players_path=official_players_path,
                forecast_path=published_direct_forecast_path,
                forecast_manifest_path=published_forecast_manifest_path,
                decision_path=published_decision_path,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                scenario_results_path=published_role_scenario_path,
                threshold_results_path=published_role_threshold_path,
                participation_receipt_path=published_participation_receipt_path,
                participation_consensus_path=published_participation_consensus_path,
                output_path=None,
            )
        )
        if current_gate.get("publishable") and current_availability.get("current"):
            _atomic_json(availability_watch_path, current_availability)
            previous["published_artifacts"]["availability_watch"] = {
                "path": str(availability_watch_path),
                "sha256": sha256_file(availability_watch_path),
            }
            previous["checked_at"] = checked_text
            previous["participation_evidence"] = participation_refresh
            previous["role_evidence_preflight"] = role_preflight
            _atomic_json(pipeline_receipt_path, previous)
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
    staged_configuration = stage_dir / "simulation-configuration.json"
    staged_configuration_report = stage_dir / "simulation-configuration.md"
    staged_bench_allocation = stage_dir / "bench-allocation.json"
    staged_bench_allocation_report = stage_dir / "bench-allocation.md"
    staged_structure_stress = stage_dir / "structure-stress.json"
    staged_structure_stress_report = stage_dir / "structure-stress.md"
    staged_role_scenario = stage_dir / "preseason-role-scenario.json"
    staged_role_scenario_report = stage_dir / "preseason-role-scenario.md"
    staged_role_threshold = stage_dir / "preseason-role-threshold.json"
    staged_role_threshold_report = stage_dir / "preseason-role-threshold.md"
    staged_availability_watch = stage_dir / "availability-watch.json"
    staged_top_player_audit = stage_dir / "top-player-omission-audit.json"
    staged_top_player_audit_report = stage_dir / "top-player-omission-audit.md"
    staged_direct_forecast = stage_dir / "direct-forecast.parquet"
    staged_component_forecast = stage_dir / "component-forecast.parquet"
    staged_forecast_manifest = stage_dir / "direct-forecast-manifest.json"
    staged_participation_receipt = stage_dir / "participation-receipt.json"
    staged_participation_consensus = stage_dir / "participation-consensus.parquet"
    stage_dir.mkdir(parents=True, exist_ok=True)
    for source, destination in (
        (direct_forecast_path, staged_direct_forecast),
        (component_forecast_path, staged_component_forecast),
        (forecast_manifest_path, staged_forecast_manifest),
        (participation_receipt_path, staged_participation_receipt),
        (participation_consensus_path, staged_participation_consensus),
    ):
        if not destination.is_file():
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
    runtime_reports = stage_dir / "runtime-reports"
    staged_robust_report = runtime_reports / "robust-search.md"
    staged_horizon_report = runtime_reports / "horizon-audit.md"
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
                participation_consensus_path=staged_participation_consensus,
                report_path=staged_robust_report,
            ),
        ),
        (
            "horizon_audit",
            lambda: _call_with_report_path(
                horizon_runner,
                **HORIZON_CONFIG,
                report_path=staged_horizon_report,
            ),
        ),
        (
            "synthesis",
            lambda: synthesis_runner(
                **SYNTHESIS_CONFIG,
                results_path=staged_results,
                decision_path=staged_decision,
                report_path=staged_report,
                participation_consensus_path=staged_participation_consensus,
                created_at=decision_created_at,
            ),
        ),
        (
            "simulation_configuration",
            lambda: configuration_runner(
                **CONFIGURATION_CONFIG,
                promote=True,
                decision_path=staged_decision,
                decision_results_path=staged_results,
                decision_report_path=staged_report,
                results_path=staged_configuration,
                report_path=staged_configuration_report,
            ),
        ),
        (
            "bench_allocation",
            lambda: bench_allocation_runner(
                **BENCH_ALLOCATION_CONFIG,
                forecast_path=direct_forecast_path,
                synthesis_path=staged_results,
                participation_consensus_path=staged_participation_consensus,
                results_path=staged_bench_allocation,
                report_path=staged_bench_allocation_report,
            ),
        ),
        (
            "structure_stress",
            lambda: structure_stress_runner(
                **STRUCTURE_STRESS_CONFIG,
                decision_path=staged_decision,
                participation_consensus_path=staged_participation_consensus,
                results_path=staged_structure_stress,
                report_path=staged_structure_stress_report,
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
                forecast_path=staged_direct_forecast,
                forecast_manifest_path=staged_forecast_manifest,
                decision_path=staged_decision,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                scenario_results_path=staged_role_scenario,
                threshold_results_path=staged_role_threshold,
                participation_receipt_path=staged_participation_receipt,
                participation_consensus_path=staged_participation_consensus,
                output_path=staged_availability_watch,
            ),
        ),
        (
            "top_player_omission_audit",
            lambda: top_player_auditor(
                forecast_path=staged_direct_forecast,
                official_players_path=official_players_path,
                participation_consensus_path=staged_participation_consensus,
                participation_receipt_path=staged_participation_receipt,
                decision_path=staged_decision,
                results_path=staged_top_player_audit,
                report_path=staged_top_player_audit_report,
            ),
        ),
    ]
    stages = _resumable_evidence_stages(
        previous,
        input_fingerprint=input_fingerprint,
        staged_decision=staged_decision,
        staged_results=staged_results,
        staged_report=staged_report,
        staged_configuration=staged_configuration,
        staged_configuration_report=staged_configuration_report,
        staged_bench_allocation=staged_bench_allocation,
        staged_bench_allocation_report=staged_bench_allocation_report,
        staged_structure_stress=staged_structure_stress,
        staged_structure_stress_report=staged_structure_stress_report,
        staged_role_scenario=staged_role_scenario,
        staged_role_scenario_report=staged_role_scenario_report,
        staged_role_threshold=staged_role_threshold,
        staged_role_threshold_report=staged_role_threshold_report,
        staged_availability_watch=staged_availability_watch,
        staged_top_player_audit=staged_top_player_audit,
        staged_top_player_audit_report=staged_top_player_audit_report,
    )
    if stages:
        print(
            f"GW1 pipeline: resuming after {len(stages)} completed stages",
            flush=True,
        )
    _record_progress(
        pipeline_receipt_path,
        checked_at=checked_text,
        input_fingerprint=input_fingerprint,
        input_identity=input_identity,
        stages=stages,
        current_stage=(runners[len(stages)][0] if len(stages) < len(runners) else None),
    )
    try:
        for stage_index in range(len(stages), len(runners)):
            name, runner = runners[stage_index]
            _record_progress(
                pipeline_receipt_path,
                checked_at=checked_text,
                input_fingerprint=input_fingerprint,
                input_identity=input_identity,
                stages=stages,
                current_stage=name,
            )
            print(f"GW1 pipeline: starting {name.replace('_', ' ')}", flush=True)
            stage_started_at = datetime.now(UTC)
            wall_started = time.perf_counter()
            self_usage_before = resource.getrusage(resource.RUSAGE_SELF)
            child_usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
            if name == "preseason_role_scenario":
                consume_role_scenario_worker_cpu_seconds()
            result = dict(runner())
            if name == "simulation_configuration" and not result.get("publishable"):
                raise PreseasonPipelineError(
                    "the simulation-authoritative XI/bench/captain selection was unstable "
                    "between selection and independent holdout"
                )
            if name == "structure_stress" and not result.get("publishable"):
                raise PreseasonPipelineError(
                    "the staged structure stress contains an unresolved supported reversal: "
                    + str(
                        (result.get("reconciliation") or {}).get("status") or result.get("verdict")
                    )
                )
            if name == "bench_allocation" and not (result.get("verdict") or {}).get("promotable"):
                failed = [
                    check
                    for check, passed in ((result.get("verdict") or {}).get("checks") or {}).items()
                    if not passed
                ]
                raise PreseasonPipelineError(
                    "the staged bench-allocation audit blocked publication: " + ", ".join(failed)
                )
            if name == "availability_watch" and not result.get("current"):
                raise PreseasonPipelineError(
                    "the staged availability watch is stale or incoherent: "
                    + "; ".join(map(str, result.get("issues") or []))
                )
            if name == "top_player_omission_audit" and not result.get("publishable"):
                failed = [
                    check for check, passed in (result.get("checks") or {}).items() if not passed
                ]
                raise PreseasonPipelineError(
                    "the staged top-player omission audit blocked publication: " + ", ".join(failed)
                )
            self_usage_after = resource.getrusage(resource.RUSAGE_SELF)
            child_usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            wall_seconds = time.perf_counter() - wall_started
            cpu_seconds = (
                self_usage_after.ru_utime
                + self_usage_after.ru_stime
                - self_usage_before.ru_utime
                - self_usage_before.ru_stime
                + child_usage_after.ru_utime
                + child_usage_after.ru_stime
                - child_usage_before.ru_utime
                - child_usage_before.ru_stime
            )
            if name == "preseason_role_scenario":
                cpu_seconds += consume_role_scenario_worker_cpu_seconds()
            compact = _compact_stage(name, result)
            compact["performance"] = {
                "started_at": stage_started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "wall_seconds": round(wall_seconds, 3),
                "cpu_seconds": round(cpu_seconds, 3),
                "average_cpu_cores": round(cpu_seconds / max(wall_seconds, 1e-9), 2),
                "process_peak_rss_kib": int(self_usage_after.ru_maxrss),
            }
            stages.append(compact)
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
            staged_configuration,
            staged_configuration_report,
            staged_bench_allocation,
            staged_bench_allocation_report,
            staged_structure_stress,
            staged_structure_stress_report,
            staged_role_scenario,
            staged_role_scenario_report,
            staged_role_threshold,
            staged_role_threshold_report,
            staged_availability_watch,
            staged_top_player_audit,
            staged_top_player_audit_report,
            staged_robust_report,
            staged_horizon_report,
            staged_direct_forecast,
            staged_component_forecast,
            staged_forecast_manifest,
            staged_participation_receipt,
            staged_participation_consensus,
        ):
            if not path.is_file():
                raise PreseasonPipelineError(f"synthesis did not create staged artifact: {path}")
        staged_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=None,
                direct_forecast_path=staged_direct_forecast,
                component_forecast_path=staged_component_forecast,
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
        _atomic_publish(staged_configuration, published_configuration_path)
        _atomic_publish(
            staged_configuration_report,
            published_configuration_report_path,
        )
        _atomic_publish(staged_structure_stress, published_structure_stress_path)
        _atomic_publish(staged_structure_stress_report, published_structure_stress_report_path)
        _atomic_publish(staged_role_scenario, published_role_scenario_path)
        _atomic_publish(staged_role_scenario_report, published_role_scenario_report_path)
        _atomic_publish(staged_role_threshold, published_role_threshold_path)
        _atomic_publish(staged_role_threshold_report, published_role_threshold_report_path)
        _atomic_publish(staged_robust_report, published_robust_report_path)
        _atomic_publish(staged_horizon_report, published_horizon_report_path)
        _atomic_publish(staged_bench_allocation, published_bench_allocation_path)
        _atomic_publish(
            staged_bench_allocation_report,
            published_bench_allocation_report_path,
        )
        _atomic_publish(staged_availability_watch, availability_watch_path)
        _atomic_publish(staged_top_player_audit, published_top_player_audit_path)
        _atomic_publish(
            staged_top_player_audit_report,
            published_top_player_audit_report_path,
        )
        _atomic_publish(staged_direct_forecast, published_direct_forecast_path)
        _atomic_publish(staged_component_forecast, published_component_forecast_path)
        _atomic_publish(staged_forecast_manifest, published_forecast_manifest_path)
        _atomic_publish(staged_participation_receipt, published_participation_receipt_path)
        _atomic_publish(staged_participation_consensus, published_participation_consensus_path)
        final_gate = dict(
            evidence_auditor(
                as_of=checked_text,
                manager_entry_id=None,
                direct_forecast_path=published_direct_forecast_path,
                component_forecast_path=published_component_forecast_path,
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
                forecast_path=published_direct_forecast_path,
                forecast_manifest_path=published_forecast_manifest_path,
                decision_path=published_decision_path,
                role_receipt_path=role_receipt_path,
                role_evidence_path=role_evidence_path,
                scenario_results_path=published_role_scenario_path,
                threshold_results_path=published_role_threshold_path,
                participation_receipt_path=published_participation_receipt_path,
                participation_consensus_path=published_participation_consensus_path,
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
                forecast_path=published_direct_forecast_path,
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
        "role_evidence_preflight": role_preflight,
        "participation_evidence": participation_refresh,
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
