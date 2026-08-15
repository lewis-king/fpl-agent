from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS

from .features import (
    FEATURE_AVAILABILITY,
    FORBIDDEN_OFFICIAL_FORECAST_FEATURES,
    MODEL_FEATURES,
)
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

VERSION = "sota_readiness_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "fplagent-sota-readiness-audit.md"

FORECAST_METRICS = MODEL_DATA / "artifacts" / "forecast_v2" / "metrics.json"
PICKER_BACKTEST = MODEL_DATA / "artifacts" / "forecast_v2" / "picker-backtest.json"
DATA_QUALITY = MODEL_DATA / "normalized" / "data_quality.json"
ROBUST_RESULTS = MODEL_DATA / "robust_search_v2_global" / "results.json"
HORIZON_RESULTS = MODEL_DATA / "horizon_audit_v1" / "results.json"
STRUCTURE_RESULTS = MODEL_DATA / "gw1_structure_stress_v1" / "results.json"
PROSPECTIVE_RESULTS = MODEL_DATA / "prospective_scoreboard_v1" / "results.json"
PARTICIPATION_RESULTS = MODEL_DATA / "participation_consensus_v1" / "scoreboard.json"
MARKET_RESULTS = MODEL_DATA / "market_feature_v1" / "results.json"
DEADLINE_PACK = MANIFESTS / "gw1-deadline-pack.json"
ROBUST_REPORT = REPORTS / "gw1-global-robust-search.md"
HORIZON_REPORT = REPORTS / "gw1-horizon-adequacy-audit.md"
EXTERNAL_BENCHMARK = MODEL_DATA / "external_forecast_benchmark_v1" / "results.json"
EXTERNAL_PLAYER_DATA = MODEL_DATA / "external_player_data_v1" / "receipt.json"


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must contain one JSON object: {path}")
    return value


def _check(
    key: str,
    label: str,
    state: str,
    evidence: str,
    *,
    requirement: str,
    scope: str,
) -> dict[str, Any]:
    if state not in {"pass", "partial", "not_ready"}:
        raise ValueError(f"invalid readiness state: {state}")
    return {
        "key": key,
        "label": label,
        "state": state,
        "evidence": evidence,
        "requirement": requirement,
        "scope": scope,
    }


def _report_matches(path: Path, candidate_id: str, created_at: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return candidate_id in text and created_at in text


def _external_player_data_state(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return (
            "not_ready",
            "No checksum-bound, deadline-safe Understat/FBref-class production receipt exists.",
        )
    receipt = _load(path, "external player-data receipt")
    providers = set(map(str, receipt.get("providers") or []))
    current = bool(receipt.get("current"))
    historical = bool(receipt.get("historical_time_forward_backtest"))
    if current and historical and len(providers) >= 2:
        return "pass", f"Current and time-forward validated: {', '.join(sorted(providers))}."
    if current and historical and providers:
        return (
            "partial",
            (
                f"{', '.join(sorted(providers))} is current and has a time-forward legal-decision "
                "replay, but a second independently mapped provider is still missing."
            ),
        )
    return (
        "partial",
        (
            "An external receipt exists, but it lacks two current providers and a time-forward "
            "decision backtest."
        ),
    )


def build_sota_readiness_audit(
    *,
    forecast_metrics_path: Path = FORECAST_METRICS,
    picker_backtest_path: Path = PICKER_BACKTEST,
    data_quality_path: Path = DATA_QUALITY,
    robust_results_path: Path = ROBUST_RESULTS,
    horizon_results_path: Path = HORIZON_RESULTS,
    structure_results_path: Path = STRUCTURE_RESULTS,
    prospective_results_path: Path = PROSPECTIVE_RESULTS,
    participation_results_path: Path = PARTICIPATION_RESULTS,
    market_results_path: Path = MARKET_RESULTS,
    deadline_pack_path: Path = DEADLINE_PACK,
    feature_registry_path: Path = FEATURE_AVAILABILITY,
    robust_report_path: Path = ROBUST_REPORT,
    horizon_report_path: Path = HORIZON_REPORT,
    external_benchmark_path: Path = EXTERNAL_BENCHMARK,
    external_player_data_path: Path = EXTERNAL_PLAYER_DATA,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    """Build a falsifiable readiness gate, not a marketing score."""

    ensure_engine_layout()
    metrics = _load(forecast_metrics_path, "forecast metrics")
    picker = _load(picker_backtest_path, "picker backtest")
    quality = _load(data_quality_path, "data-quality audit")
    robust = _load(robust_results_path, "robust-search results")
    horizon = _load(horizon_results_path, "horizon-audit results")
    structure = _load(structure_results_path, "structure-stress results")
    prospective = _load(prospective_results_path, "prospective scoreboard")
    participation = _load(participation_results_path, "participation scoreboard")
    market = _load(market_results_path, "market-feature policy")
    pack = _load(deadline_pack_path, "GW1 deadline pack")

    registry = pq.read_table(feature_registry_path).to_pylist()
    official_forecast_names = FORBIDDEN_OFFICIAL_FORECAST_FEATURES
    production_official_forecasts = [
        str(row["feature"])
        for row in registry
        if str(row.get("feature")) in official_forecast_names
        and bool(row.get("production_allowed"))
    ]
    official_forecast_independent = (
        official_forecast_names.isdisjoint(set(MODEL_FEATURES))
        and not production_official_forecasts
    )
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "official_forecast_independence",
            "Independent of FPL's own xP",
            "pass" if official_forecast_independent else "not_ready",
            (
                "Neither ep_this, ep_next nor xP can enter the production feature allowlist."
                if official_forecast_independent
                else f"Production references found: {production_official_forecasts}."
            ),
            requirement="No FPL-authored expected-points forecast influences our player xP.",
            scope="production",
        )
    )
    quality_failures = list(quality.get("failed_checks") or [])
    checks.append(
        _check(
            "point_in_time_data",
            "Point-in-time data and leakage controls",
            "pass" if not quality_failures else "not_ready",
            f"{len(quality.get('checks') or [])} checks; {len(quality_failures)} failures.",
            requirement="Snapshots precede deadlines, lagged features exclude targets, and keys are exact.",
            scope="production",
        )
    )
    backtest_gate = dict(metrics.get("backtest_gate") or {})
    checks.append(
        _check(
            "player_forecast_baseline",
            "Player forecast beats the declared form baseline",
            "pass" if backtest_gate.get("passed") else "not_ready",
            (
                f"MAE wins {backtest_gate.get('mae_wins_vs_form5')}/"
                f"{backtest_gate.get('slices')}; top-k wins "
                f"{backtest_gate.get('top_k_wins_vs_form5')}/{backtest_gate.get('slices')}; "
                f"mean top-k lift {float(backtest_gate.get('mean_top_k_lift') or 0):+.3f}."
            ),
            requirement="Beat a simple time-forward form baseline on accuracy and decision utility.",
            scope="production",
        )
    )
    picker_summary = dict(picker.get("summary") or {})
    picker_seasons = len(picker.get("seasons") or [])
    picker_pass = (
        picker_seasons >= 3
        and int(picker_summary.get("form5_wins") or 0) == 0
        and float(picker_summary.get("total_actual_point_lift") or 0) >= 0
    )
    checks.append(
        _check(
            "legal_picker_replay",
            "Exact legal GW1 replay",
            "pass" if picker_pass else "not_ready",
            (
                f"{picker_seasons} seasons; model {picker_summary.get('model_wins')} wins, "
                f"{picker_summary.get('ties')} ties, {picker_summary.get('form5_wins')} losses; "
                f"{float(picker_summary.get('total_actual_point_lift') or 0):+.1f} points."
            ),
            requirement="No losing tested season against form after legal squad/XI/captain selection.",
            scope="production",
        )
    )
    funnel = dict(robust.get("funnel") or {})
    global_challenge = dict(robust.get("global_challenge") or {})
    search_pass = (
        int(funnel.get("combined_universe") or 0) >= 500_000
        and int(funnel.get("local_two_swap_universe") or 0)
        > int(funnel.get("one_swap_universe") or 0)
        and int(global_challenge.get("finalists") or 0) > 0
        and int(funnel.get("holdout_simulations") or 0) >= 25_000
    )
    checks.append(
        _check(
            "global_search",
            "Global and local roster challenge",
            "pass" if search_pass else "not_ready",
            (
                f"{int(funnel.get('combined_universe') or 0):,} legal candidates; "
                f"{int(funnel.get('local_two_swap_universe') or 0):,} local two-swap; "
                f"{int(global_challenge.get('milp_generated') or 0):,} distant MILP and "
                f"{int(global_challenge.get('evolution_generated') or 0):,} evolutionary squads."
            ),
            requirement="The incumbent must survive both neighbourhood and distant legal challengers.",
            scope="production",
        )
    )
    structure_checks = dict(structure.get("checks") or {})
    structure_pass = bool(structure.get("publishable")) and all(structure_checks.values())
    checks.append(
        _check(
            "simulation_rules",
            "Correlated simulation and exact FPL mechanics",
            "pass" if structure_pass else "not_ready",
            (
                "Exact formation-valid autosubs, captain fallback, scoring-rule ablations and "
                "independent holdout paths passed; any supported GW1-only alternative was "
                "explicitly reconciled against the declared multiweek selector."
                if structure_pass
                else "One or more scoring/formation/autosub stress checks failed."
            ),
            requirement="Shortlisted squads are rescored in shared worlds with legal autosubs and captain fallback.",
            scope="production",
        )
    )
    horizon_pass = (
        int((horizon.get("funnel") or {}).get("deep_finalists") or 0) >= 48
        and int((horizon.get("funnel") or {}).get("holdout_simulations") or 0) >= 25_000
    )
    checks.append(
        _check(
            "transfer_aware_horizon",
            "Transfer-aware multi-horizon policy",
            "pass" if horizon_pass else "not_ready",
            (
                f"{(horizon.get('funnel') or {}).get('deep_finalists')} finalists across "
                "GW1–3/5/8, decay sensitivity, fixed/open/rolled-GW2 policies."
            ),
            requirement="Do not mistake an eight-week fixed squad for an eight-week transfer policy.",
            scope="production",
        )
    )
    production_policy = dict(market.get("production_policy") or {})
    pack_market = dict(pack.get("market") or {})
    defender_feature = dict(pack_market.get("defender_feature") or {})
    market_pass = (
        market.get("verdict") == "PROMOTE_PRESEASON_ONLY"
        and production_policy.get("preseason_decision_authority") is True
        and float(production_policy.get("preseason_weight") or 0) <= 0.20
        and defender_feature.get("status") == "applied"
        and int(pack_market.get("fixture_count") or 0) == 10
    )
    checks.append(
        _check(
            "bookmaker_prior",
            "Bookmaker market is validated and bounded",
            "pass" if market_pass else "not_ready",
            (
                f"Betfair 1X2/O2.5 covers {int(pack_market.get('fixture_count') or 0)}/10 GW1 "
                f"fixtures; {100 * float(production_policy.get('preseason_weight') or 0):.0f}% "
                "DEF-only blend; weekly authority remains zero."
            ),
            requirement="Use timestamp-safe prices only where a time-forward legal-policy gate passed.",
            scope="production",
        )
    )
    pack_gates = dict(pack.get("gates") or {})
    deadline_pass = bool(pack.get("publishable")) and all(
        bool(value.get("passed")) for value in pack_gates.values() if isinstance(value, dict)
    )
    checks.append(
        _check(
            "transactional_deadline_pack",
            "Current decision is lineage-locked and publishable",
            "pass" if deadline_pass else "not_ready",
            f"Verdict {pack.get('verdict')}; {len(pack_gates)} declared gates.",
            requirement="A partial or stale run can never replace the last coherent decision.",
            scope="production",
        )
    )
    report_pass = _report_matches(
        robust_report_path,
        str((robust.get("leader") or {}).get("candidate_id")),
        str(robust.get("created_at")),
    ) and _report_matches(
        horizon_report_path,
        str((horizon.get("leader") or {}).get("candidate_id")),
        str(horizon.get("created_at")),
    )
    checks.append(
        _check(
            "human_report_lineage",
            "Human reports match machine artifacts",
            "pass" if report_pass else "not_ready",
            (
                "Canonical robust and horizon reports contain the active candidate IDs and timestamps."
                if report_pass
                else "At least one canonical report is stale relative to its authoritative JSON."
            ),
            requirement="The prose used for review must describe the exact published generation.",
            scope="production",
        )
    )

    external_state, external_evidence = _external_player_data_state(external_player_data_path)
    checks.append(
        _check(
            "independent_player_data",
            "Independent event-data enrichment",
            external_state,
            external_evidence,
            requirement="Two current, mapped sources plus point-in-time historical replay (e.g. Understat/FBref-class data).",
            scope="research_frontier",
        )
    )
    if external_benchmark_path.is_file():
        benchmark = _load(external_benchmark_path, "external forecast benchmark")
        benchmark_pass = bool(benchmark.get("passed"))
        benchmark_evidence = str(benchmark.get("summary") or "External benchmark receipt exists.")
    else:
        benchmark_pass = False
        benchmark_evidence = (
            "No matched time-forward OpenFPL/strong-public-baseline reproduction exists yet."
        )
    checks.append(
        _check(
            "external_forecast_benchmark",
            "Strong external forecast benchmark",
            "pass" if benchmark_pass else "not_ready",
            benchmark_evidence,
            requirement="Beat or match a reproduced strong public model on identical folds and legal decisions.",
            scope="research_frontier",
        )
    )
    completed_events = int(prospective.get("completed_events") or 0)
    checks.append(
        _check(
            "prospective_2026_27",
            "Untouched prospective 2026/27 evidence",
            "pass" if completed_events >= 6 else "not_ready",
            f"{completed_events} final events; six are required for the first diagnostic review.",
            requirement="Score frozen pre-deadline forecasts and decisions after at least six final events.",
            scope="research_frontier",
        )
    )
    participation_gate = dict(participation.get("promotion_gate") or {})
    checks.append(
        _check(
            "predicted_lineup_authority",
            "Predicted-lineup consensus is prospectively validated",
            "pass" if participation_gate.get("passed") else "not_ready",
            (
                f"{participation_gate.get('qualifying_events', 0)} qualifying events; "
                "current consensus remains zero-authority role evidence."
            ),
            requirement="At least six completed events and two-source coverage before any production weight.",
            scope="research_frontier",
        )
    )

    production_checks = [row for row in checks if row["scope"] == "production"]
    frontier_checks = [row for row in checks if row["scope"] == "research_frontier"]
    production_ready = all(row["state"] == "pass" for row in production_checks)
    sota_proven = production_ready and all(row["state"] == "pass" for row in frontier_checks)
    verdict = (
        "SOTA_EVIDENCE_GATE_PASSED"
        if sota_proven
        else (
            "DEADLINE_GRADE_RESEARCH_SYSTEM_NOT_SOTA_PROVEN"
            if production_ready
            else "PRODUCTION_EVIDENCE_REPAIR_REQUIRED"
        )
    )
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "production_ready": production_ready,
        "sota_proven": sota_proven,
        "claim": {
            "defensible": (
                "The best-supported GW1 squad produced by FPLAgent under its current, "
                "checksum-bound evidence and declared risk policy."
            ),
            "not_defensible": (
                "The objectively best possible squad in the world, or a forecast proven "
                "state of the art against every strong external system."
            ),
        },
        "selected_candidate_id": (pack.get("decision") or {}).get("candidate_id"),
        "checks": checks,
        "summary": {
            "production_pass": sum(row["state"] == "pass" for row in production_checks),
            "production_total": len(production_checks),
            "frontier_pass": sum(row["state"] == "pass" for row in frontier_checks),
            "frontier_total": len(frontier_checks),
        },
        "priority_gaps": [
            {
                "priority": 1,
                "name": "Independent player-event data",
                "why": "Reduces dependence on one event-data ontology and improves chance/role signals.",
                "promotion_rule": "Two live sources, stable player mapping, point-in-time folds, and legal-policy lift.",
            },
            {
                "priority": 2,
                "name": "Matched external benchmark",
                "why": "Internal baselines cannot establish a state-of-the-art claim.",
                "promotion_rule": "Reproduce OpenFPL or another strong public model on identical folds and decisions.",
            },
            {
                "priority": 3,
                "name": "Prospective 2026/27 scoring",
                "why": "New BPS/defensive-contribution rules and live behaviours need untouched outcomes.",
                "promotion_rule": "Six events for diagnosis; a materially larger sample before any SOTA claim.",
            },
            {
                "priority": 4,
                "name": "Predicted-lineup calibration",
                "why": "Watkins-like role uncertainty is currently modelled conservatively but not source-authoritative.",
                "promotion_rule": "Two-source consensus must beat the champion prospectively on role and legal decisions.",
            },
            {
                "priority": 5,
                "name": "Full distribution calibration",
                "why": "Mean xP and policy replay do not alone prove that p10/p90/CVaR tails are calibrated.",
                "promotion_rule": "Add time-forward CRPS, interval coverage and captain/bench tail calibration by position.",
            },
            {
                "priority": 6,
                "name": "Future price and liquidity scenarios",
                "why": "The horizon models points and transfer hits, but not probabilistic price moves or forced affordability loss.",
                "promotion_rule": "Replay timestamp-safe price forecasts and promote only on net points, not team value alone.",
            },
        ],
        "artifacts": {
            "deadline_pack_sha256": sha256_file(deadline_pack_path),
            "forecast_metrics_sha256": sha256_file(forecast_metrics_path),
            "robust_results_sha256": sha256_file(robust_results_path),
            "horizon_results_sha256": sha256_file(horizon_results_path),
            "feature_registry_sha256": sha256_file(feature_registry_path),
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# FPLAgent state-of-the-art readiness audit",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Verdict:** `{result['verdict']}`  ",
        f"**Current candidate:** `{result['selected_candidate_id']}`",
        "",
        "## Claim boundary",
        "",
        f"- **Defensible:** {result['claim']['defensible']}",
        f"- **Not defensible:** {result['claim']['not_defensible']}",
        "",
        "## Evidence gates",
        "",
        "| Gate | Scope | State | Evidence |",
        "|---|---|---|---|",
    ]
    for row in result["checks"]:
        lines.append(
            f"| {row['label']} | {row['scope'].replace('_', ' ')} | "
            f"**{row['state'].upper()}** | {row['evidence']} |"
        )
    lines.extend(["", "## Priority gaps", ""])
    for gap in result["priority_gaps"]:
        lines.extend(
            [
                f"### {gap['priority']}. {gap['name']}",
                "",
                gap["why"],
                "",
                f"**Promotion rule:** {gap['promotion_rule']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            (
                "This audit intentionally has no blended readiness percentage. A high average can "
                "hide one fatal weakness. Production publication requires every production gate; "
                "a SOTA claim additionally requires every research-frontier gate."
            ),
            "",
        ]
    )
    return "\n".join(lines)
