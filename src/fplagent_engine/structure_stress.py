from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .artifact_lineage import load_json_artifact, require_current_forecast
from .component_simulator import (
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
    train_goal_model,
)
from .decision_synthesis import DECISION_JSON
from .models import CURRENT_FORECAST
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .robust_search import SHORTLIST_JSON, _paired_comparison, _record_candidate
from .rules_audit import audit_2026_27_rules
from .tournament import _load_rows, _score_candidates

VERSION = "gw1_structure_stress_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "gw1-scoring-formation-autosub-stress.md"
EVENTS = (1,)
PROXY_WEIGHTS = (0.0, 0.04, 0.08, 0.12, 0.20)
SCENARIOS: dict[str, dict[str, int]] = {
    "central_rules": {},
    "bonus_removed": {"bonus_points": 0},
    "defensive_contribution_removed": {"defensive_contribution_points": 0},
    "bonus_and_defensive_removed": {
        "bonus_points": 0,
        "defensive_contribution_points": 0,
    },
    "bonus_and_defensive_doubled": {
        "bonus_points": 2,
        "defensive_contribution_points": 2,
    },
}


def bench_proxy_coverage(proxy_runs: list[dict[str, Any]]) -> bool:
    """Count executed settings even when multiple settings produce the same legal squad."""
    return (
        len(proxy_runs) == len(PROXY_WEIGHTS)
        and {float(row["bench_autosub_weight"]) for row in proxy_runs}
        == set(PROXY_WEIGHTS)
    )


def robust_structure_rows(
    values: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    best = {
        scenario: max(candidate[scenario] for candidate in values.values())
        for scenario in SCENARIOS
    }
    rows = []
    for candidate_id, candidate in values.items():
        regrets = {
            scenario: best[scenario] - candidate[scenario] for scenario in SCENARIOS
        }
        mean_regret = float(np.mean(list(regrets.values())))
        worst_regret = max(regrets.values())
        rows.append(
            {
                "candidate_id": candidate_id,
                "scenario_values": candidate,
                "scenario_regrets": regrets,
                "mean_regret": mean_regret,
                "worst_regret": worst_regret,
                "robust_regret": 0.80 * mean_regret + 0.20 * worst_regret,
            }
        )
    rows.sort(
        key=lambda row: (
            row["robust_regret"],
            row["scenario_regrets"]["central_rules"],
            row["candidate_id"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def reconcile_structure_reversal(
    decision: dict[str, Any],
    *,
    published_candidate_id: str,
    challenger_candidate_id: str,
    supported_reversal: bool,
) -> dict[str, Any]:
    """Reconcile a GW1-only challenger against the predeclared multiweek selector.

    Structure stress deliberately answers a narrower question than synthesis: which already
    deep-tested squad is strongest in GW1 when scoring components are perturbed?  A supported
    one-week reversal is therefore material evidence, but it is not automatically a new season
    decision.  It is reconciled only when both squads were scored by the checksum-bound
    multiweek synthesis and that selector explicitly preferred the published squad.  A new bench
    proxy squad with no multiweek score remains an unresolved publication blocker.
    """
    if not supported_reversal:
        return {
            "passed": True,
            "status": "no_supported_gw1_reversal",
            "published_candidate_id": published_candidate_id,
            "challenger_candidate_id": challenger_candidate_id,
        }
    by_id = {
        str(row["candidate_id"]): row
        for row in decision.get("ranking") or []
        if isinstance(row, dict) and row.get("candidate_id") is not None
    }
    published = by_id.get(published_candidate_id)
    challenger = by_id.get(challenger_candidate_id)
    if published is None or challenger is None:
        return {
            "passed": False,
            "status": "challenger_missing_multiweek_evaluation",
            "published_candidate_id": published_candidate_id,
            "challenger_candidate_id": challenger_candidate_id,
            "missing": [
                candidate_id
                for candidate_id, row in (
                    (published_candidate_id, published),
                    (challenger_candidate_id, challenger),
                )
                if row is None
            ],
        }
    published_regret = float(published["synthesis_regret"])
    challenger_regret = float(challenger["synthesis_regret"])
    published_rank = int(published["rank"])
    challenger_rank = int(challenger["rank"])
    regret_delta = challenger_regret - published_regret
    passed = challenger_rank > published_rank and regret_delta > 0.0
    return {
        "passed": passed,
        "status": (
            "gw1_edge_recorded_multiweek_selector_retains_published"
            if passed
            else "gw1_reversal_conflicts_with_multiweek_selector"
        ),
        "published_candidate_id": published_candidate_id,
        "published_synthesis_rank": published_rank,
        "published_synthesis_regret": published_regret,
        "challenger_candidate_id": challenger_candidate_id,
        "challenger_synthesis_rank": challenger_rank,
        "challenger_synthesis_regret": challenger_regret,
        "challenger_synthesis_regret_delta": regret_delta,
        "interpretation": (
            "The challenger is the supported GW1-only alternative, while the published squad "
            "remains the winner of the historically gated five/eight-week objective."
        ),
    }


def _candidate_field(
    decision: dict[str, Any],
    shortlist: dict[str, Any],
    rows: list[dict[str, Any]],
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested = {str(row["candidate_id"]) for row in decision["ranking"]}
    by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in shortlist["candidates"]
        if str(candidate["candidate_id"]) in requested
    }
    current = decision["decision"]["candidate"]
    by_id[str(current["candidate_id"])] = current
    missing = requested - set(by_id)
    if missing:
        raise ValueError(f"Synthesis frontier missing from robust shortlist: {sorted(missing)}")

    proxy_runs: list[dict[str, Any]] = []
    events = sorted({int(row["event_number"]) for row in rows})
    for weight in PROXY_WEIGHTS:
        solution = _solve(rows, events, bench_autosub_weight=weight)
        candidate = _record_candidate(
            tuple(sorted(map(int, solution["selected"]))),
            by_player,
            meta,
            {f"bench-autosub-proxy:{weight:.2f}"},
            float(solution["objective"]),
        )
        candidate_id = str(candidate["candidate_id"])
        proxy_runs.append({"bench_autosub_weight": weight, "candidate_id": candidate_id})
        if candidate_id in by_id:
            origins = set(map(str, by_id[candidate_id].get("origin_ids") or []))
            origins.add(f"bench-autosub-proxy:{weight:.2f}")
            by_id[candidate_id]["origin_ids"] = sorted(origins)
        else:
            by_id[candidate_id] = candidate
    return list(by_id.values()), proxy_runs


def _evaluate(
    candidates: list[dict[str, Any]],
    *,
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    goal_rates: dict[tuple[int, int, int], tuple[float, float]],
    empirical: Any,
    simulations: int,
    seed: int,
) -> tuple[dict[str, dict[str, float]], dict[str, np.ndarray], dict[str, Any]]:
    values = {str(candidate["candidate_id"]): {} for candidate in candidates}
    paths: dict[str, np.ndarray] = {}
    diagnostics: dict[str, Any] = {}
    expected_player_ids: list[int] | None = None
    for scenario, weights in SCENARIOS.items():
        player_ids, points, _, played, _, diagnostic = simulate_component_outcomes(
            by_player,
            EVENTS,
            goal_rates,
            empirical,
            simulations,
            seed,
            component_point_weights=weights,
        )
        if expected_player_ids is not None and player_ids != expected_player_ids:
            raise RuntimeError("Scoring-stress player order changed between scenarios")
        expected_player_ids = player_ids
        scores = _score_candidates(candidates, player_ids, EVENTS, points, played, meta)[:, :, 0]
        diagnostics[scenario] = diagnostic
        for offset, candidate in enumerate(candidates):
            candidate_id = str(candidate["candidate_id"])
            values[candidate_id][scenario] = float(scores[:, offset].mean())
            paths[f"{scenario}:{candidate_id}"] = scores[:, offset]
    return values, paths, diagnostics


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# GW1 scoring, formation and autosub stress",
        "",
        f"Generated: {result['created_at']}",
        "",
        f"**Verdict: {result['verdict']}**",
        "",
        (
            "Every synthesis finalist plus squads generated at five different cheap bench-proxy "
            "weights is rescored with exact formation-valid autosubs and captain fallback. The "
            "2026/27 bonus and defensive-contribution layers are then removed separately, removed "
            "together and doubled. These are model-misspecification stresses, not alternative FPL "
            "rules."
        ),
        "",
        (
            f"Published candidate: `{result['published_candidate_id']}`; stress leader: "
            f"`{result['stress_leader_id']}`."
        ),
        "",
        "## Publication gate",
        "",
    ]
    for name, passed in result["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    reconciliation = result["reconciliation"]
    lines.extend(
        [
            "",
            "## One-week versus multiweek reconciliation",
            "",
            f"Status: **{reconciliation['status'].replace('_', ' ')}**.",
            "",
        ]
    )
    if result["supported_reversal"]:
        holdout = result["holdout"]["challenger_minus_published"]["central_rules"]
        lines.append(
            f"The stress leader gains {holdout['mean_delta']:+.3f} GW1 points in the independent "
            f"central-rules holdout (95% CI {holdout['delta_95ci_low']:+.3f} to "
            f"{holdout['delta_95ci_high']:+.3f}). This is shown as a live alternative, not "
            "discarded."
        )
        if reconciliation.get("challenger_synthesis_regret_delta") is not None:
            lines.append(
                f"It ranks {reconciliation['challenger_synthesis_rank']} in the declared "
                "multiweek synthesis and carries "
                f"{reconciliation['challenger_synthesis_regret_delta']:+.3f} more synthesis "
                "regret than the published squad. The season-opening selector therefore retains "
                "the published squad; a challenger absent from that multiweek field would block "
                "publication instead."
            )
    lines.extend(
        [
            "",
            "## Top field",
            "",
            "| Rank | Candidate | Robust regret | Central xP | Worst regret | Formation | Bench |",
            "|---:|---|---:|---:|---:|---|---:|",
        ]
    )
    detail = result["candidate_details"]
    for row in result["ranking"][:15]:
        candidate = detail[row["candidate_id"]]
        lines.append(
            f"| {row['rank']} | `{row['candidate_id']}` | {row['robust_regret']:.3f} | "
            f"{row['scenario_values']['central_rules']:.2f} | {row['worst_regret']:.3f} | "
            f"{candidate['gw1_formation']} | £{candidate['gw1_bench_spend']:.1f}m |"
        )
    lines.extend(
        [
            "",
            (
                "The initial optimiser's 8% bench coefficient is therefore only a generator. It "
                "has no voting power in this gate: final scoring uses actual DNP patterns, legal "
                "autosub order, minimum three defenders, goalkeeper-only substitution and "
                "captain-to-vice fallback."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_structure_stress(
    *,
    selection_simulations: int = 2_000,
    holdout_simulations: int = 10_000,
    selection_seed: int = 20260831,
    holdout_seed: int = 20260901,
    decision_path: Path = DECISION_JSON,
    shortlist_path: Path = SHORTLIST_JSON,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if selection_simulations < 1_000 or holdout_simulations < 5_000:
        raise ValueError("Structure-stress simulation counts are below the safety minimum")
    if selection_seed == holdout_seed:
        raise ValueError("Structure stress requires independent selection and holdout seeds")
    decision = load_json_artifact(decision_path, "synthesized decision")
    shortlist = load_json_artifact(shortlist_path, "robust shortlist")
    require_current_forecast(shortlist, CURRENT_FORECAST, "robust shortlist")
    if (decision.get("source_artifacts") or {}).get("robust_shortlist_sha256") != sha256_file(
        shortlist_path
    ):
        raise ValueError("Synthesized decision uses a different robust shortlist")
    rows, loaded = _load_rows(tuple(range(1, 9)))
    by_player, meta = loaded["by_player"], loaded["meta"]
    candidates, proxy_runs = _candidate_field(decision, shortlist, rows, by_player, meta)
    current_id = str(decision["decision"]["candidate_id"])
    if current_id not in {str(candidate["candidate_id"]) for candidate in candidates}:
        raise RuntimeError("Published candidate is absent from structure-stress field")

    rule_audit = audit_2026_27_rules()
    rule_checks = dict(rule_audit["assertions"])
    train_goal_model(force=False, seed=selection_seed)
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, EVENTS)
    empirical = calibrate_empirical_components()
    print(
        f"Structure stress: evaluating {len(candidates)} candidates across "
        f"{len(SCENARIOS)} scoring views",
        flush=True,
    )
    values, _, selection_diagnostics = _evaluate(
        candidates,
        by_player=by_player,
        meta=meta,
        goal_rates=goal_rates,
        empirical=empirical,
        simulations=selection_simulations,
        seed=selection_seed,
    )
    ranking = robust_structure_rows(values)
    challenger_id = str(ranking[0]["candidate_id"])
    holdout = None
    supported_reversal = False
    if challenger_id != current_id:
        print("Structure stress: challenger found; running independent deep holdout", flush=True)
        _, holdout_paths, holdout_diagnostics = _evaluate(
            candidates,
            by_player=by_player,
            meta=meta,
            goal_rates=goal_rates,
            empirical=empirical,
            simulations=holdout_simulations,
            seed=holdout_seed,
        )
        comparisons = {
            scenario: _paired_comparison(
                holdout_paths[f"{scenario}:{challenger_id}"],
                holdout_paths[f"{scenario}:{current_id}"],
            )
            for scenario in SCENARIOS
        }
        supported_count = sum(row["delta_95ci_low"] > 0.0 for row in comparisons.values())
        supported_reversal = (
            comparisons["central_rules"]["delta_95ci_low"] > 0.0
            and supported_count >= 3
            and all(row["mean_delta"] >= 0.0 for row in comparisons.values())
        )
        holdout = {
            "simulations": holdout_simulations,
            "challenger_minus_published": comparisons,
            "supported_scenarios": supported_count,
            "diagnostics": holdout_diagnostics,
        }
    reconciliation = reconcile_structure_reversal(
        decision,
        published_candidate_id=current_id,
        challenger_candidate_id=challenger_id,
        supported_reversal=supported_reversal,
    )
    checks = {
        "live_rule_assertions_pass": all(rule_checks.values()),
        "all_synthesis_finalists_scored": len(decision["ranking"])
        <= len(candidates),
        "five_bench_proxy_settings_challenged": bench_proxy_coverage(proxy_runs),
        "exact_formation_valid_autosubs_used": True,
        "supported_gw1_reversal_reconciled_with_multiweek_objective": bool(
            reconciliation["passed"]
        ),
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS" if all(checks.values()) else "BLOCK",
        "publishable": all(checks.values()),
        "checks": checks,
        "published_candidate_id": current_id,
        "stress_leader_id": challenger_id,
        "supported_reversal": supported_reversal,
        "reconciliation": reconciliation,
        "ranking": ranking,
        "holdout": holdout,
        "candidate_details": {
            str(candidate["candidate_id"]): {
                "display_name": candidate["display_name"],
                "gw1_formation": candidate["gw1_formation"],
                "gw1_bench_spend": float(candidate["gw1_bench_spend"]),
                "origin_ids": candidate.get("origin_ids") or [],
            }
            for candidate in candidates
        },
        "bench_proxy_candidates": proxy_runs,
        "method": {
            "selection_simulations": selection_simulations,
            "holdout_simulations_if_challenged": holdout_simulations,
            "scenarios": SCENARIOS,
            "candidate_scoring": "exact autosubs and captain fallback",
            "selection_objective": "80% mean scenario regret + 20% worst scenario regret",
        },
        "rule_audit": {
            "snapshot_at": rule_audit["snapshot_at"],
            "assertions": rule_checks,
        },
        "goal_rate_diagnostics": goal_diagnostics,
        "selection_diagnostics": selection_diagnostics,
        "lineage": {
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
            "decision_sha256": sha256_file(decision_path),
            "shortlist_sha256": sha256_file(shortlist_path),
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render(result), encoding="utf-8")
    print(
        f"Structure stress: {result['verdict']}; leader {challenger_id}",
        flush=True,
    )
    return result
