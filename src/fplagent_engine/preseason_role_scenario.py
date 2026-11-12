from __future__ import annotations

import json
import time
from collections import Counter
from itertools import permutations, product
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
from joblib import Parallel, delayed, parallel_config

from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS, PROCESSED
from fplagent_data.preseason_lineups import fpl_role_mapping_fingerprint

from .acceleration import role_scenario_worker_count
from .artifact_lineage import load_json_artifact
from .current_squad_audit import (
    _bench_orders,
    _candidate,
    _captain_bonus,
    _choice_leaders,
    _paired_delta,
    _rank_candidates,
    _simulate_families,
    enumerate_legal_xis,
)
from .current_squad_audit import _verify_lineage as _verify_current_lineage
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import SHORTLIST_JSON
from .tournament import _load_rows, _score_candidates

VERSION = "preseason_role_scenario_v1"
EVENT = 1
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "preseason-role-scenario-audit.md"
ROLE_RECEIPT = MANIFESTS / "preseason_lineups_current.json"
ROLE_EVIDENCE = (
    PROCESSED
    / "supporting"
    / "sofascore"
    / "2026-27"
    / "preseason_role_evidence.parquet"
)
FPL_DIR = PROCESSED / "fpl" / "2026-27" / "preseason"
_LAST_WORKER_CPU_SECONDS = 0.0

FLAG_NOT_LISTED = "not_listed_three_plus"
FLAG_ROLE_WATCH = "low_recent_start_share"
FLAG_UNCOVERED = "no_confirmed_club_lineups"
FLAG_OTHER = "observed_or_insufficient"

# These are counterfactual retention factors conditional on an appearance in the
# production simulation. They are not posterior estimates and carry no scenario weights.
SCENARIOS: dict[str, dict[str, Any]] = {
    "baseline": {
        "description": "Production appearance worlds unchanged.",
        "factors": {FLAG_NOT_LISTED: 1.0, FLAG_ROLE_WATCH: 1.0},
    },
    "moderate_role_stress": {
        "description": (
            "Retain 75% of simulated appearances for three-plus-lineup absences and "
            "90% for low-recent-start flags."
        ),
        "factors": {FLAG_NOT_LISTED: 0.75, FLAG_ROLE_WATCH: 0.90},
    },
    "severe_role_stress": {
        "description": (
            "Retain 50% of simulated appearances for three-plus-lineup absences and "
            "75% for low-recent-start flags."
        ),
        "factors": {FLAG_NOT_LISTED: 0.50, FLAG_ROLE_WATCH: 0.75},
    },
    "not_listed_dnp_boundary": {
        "description": (
            "Force three-plus-lineup absence flags to DNP while leaving role-watch "
            "players at production appearance rates."
        ),
        "factors": {FLAG_NOT_LISTED: 0.0, FLAG_ROLE_WATCH: 1.0},
    },
}


def consume_role_scenario_worker_cpu_seconds() -> float:
    """Return and clear CPU time spent in loky children during the last audit.

    Persistent loky workers are not reaped at the stage boundary, so POSIX
    ``RUSAGE_CHILDREN`` cannot observe their CPU time yet. The pipeline consumes
    this explicit counter once when it builds stage telemetry.
    """

    global _LAST_WORKER_CPU_SECONDS
    value = _LAST_WORKER_CPU_SECONDS
    _LAST_WORKER_CPU_SECONDS = 0.0
    return value


def derive_role_flags(
    role_rows: list[dict[str, Any]], candidate_pool: set[int]
) -> dict[int, str]:
    by_element = {int(row["fpl_element"]): row for row in role_rows}
    missing = candidate_pool - set(by_element)
    if missing:
        raise ValueError(f"Candidate players missing role evidence: {sorted(missing)}")
    flags: dict[int, str] = {}
    for element in sorted(candidate_pool):
        row = by_element[element]
        eligible = int(row["eligible_team_matches"])
        status = str(row["evidence_status"])
        if status == "no_confirmed_team_lineups":
            flags[element] = FLAG_UNCOVERED
        elif status == "not_listed_in_eligible_lineups" and eligible >= 3:
            flags[element] = FLAG_NOT_LISTED
        elif (
            status == "observed_in_lineup"
            and eligible >= 2
            and row["recency_weighted_start_share"] is not None
            and float(row["recency_weighted_start_share"]) < 0.50
            and row["last_match_started"] is False
        ):
            flags[element] = FLAG_ROLE_WATCH
        else:
            flags[element] = FLAG_OTHER
    return flags


def scenario_player_factors(
    flags: dict[int, str], scenario: dict[str, Any]
) -> dict[int, float]:
    category_factors = scenario["factors"]
    factors = {
        element: float(category_factors[flag])
        for element, flag in flags.items()
        if flag in category_factors and float(category_factors[flag]) < 1.0
    }
    if any(not 0.0 <= factor <= 1.0 for factor in factors.values()):
        raise ValueError("Scenario appearance-retention factors must be in [0, 1]")
    return factors


def apply_conditional_dnp_stress(
    points: np.ndarray,
    played: np.ndarray,
    player_ids: list[int],
    factors: dict[int, float],
    *,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if points.shape != played.shape or points.ndim != 3 or points.shape[1] < 1:
        raise ValueError("Points and played must be equal simulation/event/player tensors")
    player_index = {element: index for index, element in enumerate(player_ids)}
    unknown = set(factors) - set(player_index)
    if unknown:
        raise ValueError(f"Stress factors reference unknown players: {sorted(unknown)}")
    if any(not 0.0 <= factor <= 1.0 for factor in factors.values()):
        raise ValueError("Conditional appearance-retention factors must be in [0, 1]")

    stressed_points = points.copy()
    stressed_played = played.copy()
    rng = np.random.default_rng(seed)
    diagnostics: dict[str, Any] = {}
    for element in sorted(factors):
        factor = factors[element]
        index = player_index[element]
        keep = rng.random(points.shape[0]) < factor
        before = stressed_played[:, 0, index].copy()
        after = before & keep
        stressed_played[:, 0, index] = after
        stressed_points[:, 0, index] = np.where(
            after, stressed_points[:, 0, index], 0
        )
        diagnostics[str(element)] = {
            "conditional_retention_factor": factor,
            "base_appearance_rate": float(before.mean()),
            "stressed_appearance_rate": float(after.mean()),
        }
    return stressed_points, stressed_played, diagnostics


def _scenario_worlds(
    player_ids: list[int],
    residual_points: np.ndarray,
    residual_played: np.ndarray,
    component_points: np.ndarray,
    component_played: np.ndarray,
    factors: dict[int, float],
    *,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    residual_stressed, residual_stressed_played, residual_diagnostics = (
        apply_conditional_dnp_stress(
            residual_points,
            residual_played,
            player_ids,
            factors,
            seed=seed,
        )
    )
    component_stressed, component_stressed_played, component_diagnostics = (
        apply_conditional_dnp_stress(
            component_points,
            component_played,
            player_ids,
            factors,
            seed=seed,
        )
    )
    return (
        residual_stressed,
        residual_stressed_played,
        component_stressed,
        component_stressed_played,
        {
            "residual": residual_diagnostics,
            "component": component_diagnostics,
        },
    )


def _build_configuration_candidates(
    selected: list[int],
    published: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    player_ids: list[int],
    residual_points: np.ndarray,
    residual_played: np.ndarray,
    component_points: np.ndarray,
    component_played: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    player_index = {element: index for index, element in enumerate(player_ids)}
    xis = enumerate_legal_xis(selected, meta)
    bench_candidates: list[dict[str, Any]] = []
    bench_ranges: list[tuple[int, int]] = []
    for starters in xis:
        start = len(bench_candidates)
        arbitrary_captain, arbitrary_vice = starters[:2]
        for order in _bench_orders(selected, starters, meta):
            bench_candidates.append(
                _candidate(
                    selected,
                    starters,
                    order,
                    arbitrary_captain,
                    arbitrary_vice,
                    meta,
                )
            )
        bench_ranges.append((start, len(bench_candidates)))
    residual_bench_scores = _score_candidates(
        bench_candidates,
        player_ids,
        (EVENT,),
        residual_points,
        residual_played,
        meta,
    )
    component_bench_scores = _score_candidates(
        bench_candidates,
        player_ids,
        (EVENT,),
        component_points,
        component_played,
        meta,
    )

    candidates_by_id: dict[str, dict[str, Any]] = {}
    for starters, (start, end) in zip(xis, bench_ranges, strict=True):
        bench_means = np.column_stack(
            (
                residual_bench_scores[:, start:end, 0].mean(axis=0),
                component_bench_scores[:, start:end, 0].mean(axis=0),
            )
        )
        bench_choices = [
            tuple(
                bench_candidates[start + index]["lineups"][str(EVENT)][
                    "bench_order"
                ]
            )
            for index in _choice_leaders(bench_means)
        ]
        captain_pairs = list(permutations(starters, 2))
        captain_means = []
        for captain, vice in captain_pairs:
            residual_bonus = _captain_bonus(
                residual_points,
                residual_played,
                player_index,
                captain,
                vice,
            )
            component_bonus = _captain_bonus(
                component_points,
                component_played,
                player_index,
                captain,
                vice,
            )
            captain_means.append(
                (float(residual_bonus.mean()), float(component_bonus.mean()))
            )
        captain_choices = [
            captain_pairs[index]
            for index in _choice_leaders(np.asarray(captain_means))
        ]
        for bench_order, (captain, vice) in product(
            bench_choices, captain_choices
        ):
            candidate = _candidate(
                selected,
                starters,
                bench_order,
                captain,
                vice,
                meta,
            )
            candidates_by_id[candidate["candidate_id"]] = candidate

    published_candidate = _candidate(
        selected,
        tuple(map(int, published["starters"])),
        tuple(map(int, published["bench_order"])),
        int(published["captain"]),
        int(published["vice_captain"]),
        meta,
    )
    candidates_by_id[published_candidate["candidate_id"]] = published_candidate
    return list(candidates_by_id.values()), {
        "legal_xis": len(xis),
        "bench_orders_scored": len(bench_candidates),
        "joint_configurations_scored": len(candidates_by_id),
    }


def _configuration_audit(
    selected: list[int],
    published_lineup: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    player_ids: list[int],
    residual_selection_points: np.ndarray,
    residual_selection_played: np.ndarray,
    component_selection_points: np.ndarray,
    component_selection_played: np.ndarray,
    residual_holdout_points: np.ndarray,
    residual_holdout_played: np.ndarray,
    component_holdout_points: np.ndarray,
    component_holdout_played: np.ndarray,
    *,
    finalists: int,
) -> dict[str, Any]:
    candidates, search = _build_configuration_candidates(
        selected,
        published_lineup,
        meta,
        player_ids,
        residual_selection_points,
        residual_selection_played,
        component_selection_points,
        component_selection_played,
    )
    residual_selection_scores = _score_candidates(
        candidates,
        player_ids,
        (EVENT,),
        residual_selection_points,
        residual_selection_played,
        meta,
    )
    component_selection_scores = _score_candidates(
        candidates,
        player_ids,
        (EVENT,),
        component_selection_points,
        component_selection_played,
        meta,
    )
    selection_rows = _rank_candidates(
        candidates, residual_selection_scores, component_selection_scores
    )
    selection_champion_id = selection_rows[0]["candidate_id"]
    published_candidate = _candidate(
        selected,
        tuple(map(int, published_lineup["starters"])),
        tuple(map(int, published_lineup["bench_order"])),
        int(published_lineup["captain"]),
        int(published_lineup["vice_captain"]),
        meta,
    )
    finalist_ids = [row["candidate_id"] for row in selection_rows[:finalists]]
    if published_candidate["candidate_id"] not in finalist_ids:
        finalist_ids.append(published_candidate["candidate_id"])
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    finalist_candidates = [by_id[candidate_id] for candidate_id in finalist_ids]
    residual_holdout_scores = _score_candidates(
        finalist_candidates,
        player_ids,
        (EVENT,),
        residual_holdout_points,
        residual_holdout_played,
        meta,
    )
    component_holdout_scores = _score_candidates(
        finalist_candidates,
        player_ids,
        (EVENT,),
        component_holdout_points,
        component_holdout_played,
        meta,
    )
    holdout_rows = _rank_candidates(
        finalist_candidates, residual_holdout_scores, component_holdout_scores
    )
    finalist_index = {
        candidate["candidate_id"]: index
        for index, candidate in enumerate(finalist_candidates)
    }
    champion_index = finalist_index[selection_champion_id]
    published_index = finalist_index[published_candidate["candidate_id"]]
    residual_delta = _paired_delta(
        residual_holdout_scores[:, champion_index, 0],
        residual_holdout_scores[:, published_index, 0],
    )
    component_delta = _paired_delta(
        component_holdout_scores[:, champion_index, 0],
        component_holdout_scores[:, published_index, 0],
    )
    champion = by_id[selection_champion_id]["lineups"][str(EVENT)]
    names = {element: str(meta[element]["player_name"]) for element in selected}
    supported = (
        selection_champion_id != published_candidate["candidate_id"]
        and residual_delta["ci95_low"] > 0.0
        and component_delta["ci95_low"] > 0.0
    )
    return {
        "selection_champion": {
            "candidate_id": selection_champion_id,
            "formation": champion["formation"],
            "starters": [names[int(element)] for element in champion["starters"]],
            "bench_order": [
                names[int(element)] for element in champion["bench_order"]
            ],
            "captain": names[int(champion["captain"])],
            "vice_captain": names[int(champion["vice_captain"])],
        },
        "selection_champion_candidate": by_id[selection_champion_id],
        "published_audit_candidate_id": published_candidate["candidate_id"],
        "exact_published_match": (
            selection_champion_id == published_candidate["candidate_id"]
        ),
        "holdout_delta_to_published": {
            "residual": residual_delta,
            "component": component_delta,
        },
        "cross_family_holdout_support": supported,
        "search": {**search, "holdout_finalists": len(finalist_candidates)},
        "selection_top": selection_rows[:10],
        "holdout_top": holdout_rows[:10],
    }


def _deep_configuration_comparison(
    challenger: dict[str, Any],
    incumbent: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    player_ids: list[int],
    residual_holdout_points: np.ndarray,
    residual_holdout_played: np.ndarray,
    component_holdout_points: np.ndarray,
    component_holdout_played: np.ndarray,
) -> dict[str, Any]:
    comparison = [challenger, incumbent]
    residual_scores = _score_candidates(
        comparison,
        player_ids,
        (EVENT,),
        residual_holdout_points,
        residual_holdout_played,
        meta,
    )
    component_scores = _score_candidates(
        comparison,
        player_ids,
        (EVENT,),
        component_holdout_points,
        component_holdout_played,
        meta,
    )
    residual_delta = _paired_delta(
        residual_scores[:, 0, 0], residual_scores[:, 1, 0]
    )
    component_delta = _paired_delta(
        component_scores[:, 0, 0], component_scores[:, 1, 0]
    )
    return {
        "holdout_delta_challenger_to_incumbent": {
            "residual": residual_delta,
            "component": component_delta,
        },
        "cross_family_holdout_support": (
            residual_delta["ci95_low"] > 0.0
            and component_delta["ci95_low"] > 0.0
        ),
    }


def _squad_audit(
    candidates: list[dict[str, Any]],
    published_id: str,
    meta: dict[int, dict[str, Any]],
    player_ids: list[int],
    residual_selection_points: np.ndarray,
    residual_selection_played: np.ndarray,
    component_selection_points: np.ndarray,
    component_selection_played: np.ndarray,
    residual_holdout_points: np.ndarray,
    residual_holdout_played: np.ndarray,
    component_holdout_points: np.ndarray,
    component_holdout_played: np.ndarray,
) -> dict[str, Any]:
    residual_selection_scores = _score_candidates(
        candidates,
        player_ids,
        (EVENT,),
        residual_selection_points,
        residual_selection_played,
        meta,
    )
    component_selection_scores = _score_candidates(
        candidates,
        player_ids,
        (EVENT,),
        component_selection_points,
        component_selection_played,
        meta,
    )
    selection_rows = _rank_candidates(
        candidates, residual_selection_scores, component_selection_scores
    )
    selection_champion_id = selection_rows[0]["candidate_id"]
    residual_holdout_scores = _score_candidates(
        candidates,
        player_ids,
        (EVENT,),
        residual_holdout_points,
        residual_holdout_played,
        meta,
    )
    component_holdout_scores = _score_candidates(
        candidates,
        player_ids,
        (EVENT,),
        component_holdout_points,
        component_holdout_played,
        meta,
    )
    holdout_rows = _rank_candidates(
        candidates, residual_holdout_scores, component_holdout_scores
    )
    index = {
        candidate["candidate_id"]: offset
        for offset, candidate in enumerate(candidates)
    }
    champion_index = index[selection_champion_id]
    published_index = index[published_id]
    residual_delta = _paired_delta(
        residual_holdout_scores[:, champion_index, 0],
        residual_holdout_scores[:, published_index, 0],
    )
    component_delta = _paired_delta(
        component_holdout_scores[:, champion_index, 0],
        component_holdout_scores[:, published_index, 0],
    )
    champion = candidates[champion_index]
    published = candidates[published_index]
    champion_set = set(map(int, champion["selected"]))
    published_set = set(map(int, published["selected"]))
    supported = (
        selection_champion_id != published_id
        and residual_delta["ci95_low"] > 0.0
        and component_delta["ci95_low"] > 0.0
    )
    return {
        "screen_method": (
            "All synthesis finalists retain their frozen GW1 XI, bench and captaincy for the "
            "squad screen. The published 15 is separately reoptimized exhaustively. A screen "
            "reversal identifies a squad for deeper scenario-specific configuration replay; it "
            "is not a direct squad recommendation."
        ),
        "selection_champion_id": selection_champion_id,
        "exact_published_match": selection_champion_id == published_id,
        "players_in": [
            str(meta[element]["player_name"])
            for element in sorted(champion_set - published_set)
        ],
        "players_out": [
            str(meta[element]["player_name"])
            for element in sorted(published_set - champion_set)
        ],
        "holdout_delta_to_published": {
            "residual": residual_delta,
            "component": component_delta,
        },
        "cross_family_holdout_support": supported,
        "selection_top": selection_rows[:10],
        "holdout_top": holdout_rows[:10],
    }


def _verify_role_lineage(
    *,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    fpl_dir: Path = FPL_DIR,
) -> tuple[dict[str, Any], str]:
    receipt = load_json_artifact(role_receipt_path, "preseason lineup receipt")
    expected = str(role_evidence_path.resolve())
    recorded = str(Path(receipt["outputs"]["role_evidence"]).resolve())
    if recorded != expected:
        raise ValueError("Preseason receipt points to a different role-evidence table")
    evidence_sha = sha256_file(role_evidence_path)
    if receipt["outputs"]["role_evidence_sha256"] != evidence_sha:
        raise ValueError("Preseason role-evidence checksum differs from its receipt")
    mapping_fingerprint = receipt.get("inputs", {}).get("role_mapping_fingerprint")
    if mapping_fingerprint:
        current_mapping = fpl_role_mapping_fingerprint(
            pq.read_table(fpl_dir / "teams.parquet").to_pylist(),
            pq.read_table(fpl_dir / "players.parquet").to_pylist(),
            pq.read_table(fpl_dir / "events.parquet").to_pylist(),
        )
        if mapping_fingerprint != current_mapping:
            raise ValueError("Preseason role evidence uses a stale FPL mapping generation")
    else:
        for name in ("teams", "players", "events"):
            actual = sha256_file(fpl_dir / f"{name}.parquet")
            if receipt["inputs"][f"{name}_sha256"] != actual:
                raise ValueError(f"Preseason role evidence uses stale FPL {name} data")
    return receipt, evidence_sha


def validate_preseason_role_lineage(
    *,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    fpl_dir: Path = FPL_DIR,
) -> dict[str, Any]:
    """Validate the cheap role-evidence contract before any simulation starts."""
    receipt, evidence_sha = _verify_role_lineage(
        role_receipt_path=role_receipt_path,
        role_evidence_path=role_evidence_path,
        fpl_dir=fpl_dir,
    )
    return {
        "status": "current",
        "created_at": receipt.get("created_at"),
        "role_evidence_sha256": evidence_sha,
        "role_mapping_fingerprint": (receipt.get("inputs") or {}).get(
            "role_mapping_fingerprint"
        ),
    }


def _load_synthesis_candidates(
    decision: dict[str, Any],
    maximum_candidates: int | None,
    *,
    shortlist_path: Path = SHORTLIST_JSON,
) -> list[dict[str, Any]]:
    ranking = decision["ranking"]
    if maximum_candidates is not None:
        if maximum_candidates < 2:
            raise ValueError("At least two synthesis candidates are required")
        ranking = ranking[:maximum_candidates]
    candidate_ids = [str(row["candidate_id"]) for row in ranking]
    shortlist = load_json_artifact(shortlist_path, "global robust-search shortlist")
    by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in shortlist["candidates"]
    }
    published = decision["decision"]["candidate"]
    by_id[str(published["candidate_id"])] = published
    missing = set(candidate_ids) - set(by_id)
    if missing:
        raise ValueError(f"Synthesis candidates missing from shortlist: {sorted(missing)}")
    return [by_id[candidate_id] for candidate_id in candidate_ids]


def run_preseason_role_scenario_audit(
    *,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    finalists: int = 64,
    selection_seed: int = 20260812,
    holdout_seed: int = 20260813,
    maximum_candidates: int | None = None,
    decision_path: Path = SYNTHESIZED_DECISION,
    shortlist_path: Path = SHORTLIST_JSON,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    fpl_dir: Path = FPL_DIR,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    global _LAST_WORKER_CPU_SECONDS
    _LAST_WORKER_CPU_SECONDS = 0.0
    if selection_simulations < 2_000 or holdout_simulations < 5_000:
        raise ValueError("Preseason scenario simulation counts are below the safety minimum")
    if selection_seed == holdout_seed:
        raise ValueError("Selection and holdout require independent seeds")
    ensure_engine_layout()
    decision, lineage = _verify_current_lineage(decision_path=decision_path)
    role_receipt, role_evidence_sha = _verify_role_lineage(
        role_receipt_path=role_receipt_path,
        role_evidence_path=role_evidence_path,
        fpl_dir=fpl_dir,
    )
    if sha256_file(decision_path) != lineage["decision_sha256"]:
        raise ValueError("Current decision changed during scenario lineage validation")
    candidates = _load_synthesis_candidates(
        decision, maximum_candidates, shortlist_path=shortlist_path
    )
    current = decision["decision"]["candidate"]
    published_id = str(current["candidate_id"])
    if published_id not in {str(candidate["candidate_id"]) for candidate in candidates}:
        raise ValueError("Published candidate is absent from the scenario field")

    _, loaded = _load_rows((EVENT,))
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    candidate_pool = {
        int(element) for candidate in candidates for element in candidate["selected"]
    }
    role_rows = pq.read_table(role_evidence_path).to_pylist()
    flags = derive_role_flags(role_rows, candidate_pool)
    role_by_element = {int(row["fpl_element"]): row for row in role_rows}

    component_backtest = load_json_artifact(
        MODEL_DATA / "component_backtest_v1" / "metrics.json",
        "component backtest metrics",
    )
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    print("Preseason scenario audit: simulating selection worlds", flush=True)
    (
        player_ids,
        residual_selection_points,
        residual_selection_played,
        component_selection_points,
        selection_diagnostics,
    ) = _simulate_families(
        by_player, selection_simulations, selection_seed, raw_weight
    )
    component_selection_played = selection_diagnostics.pop("component_played")
    print("Preseason scenario audit: simulating holdout worlds", flush=True)
    (
        holdout_player_ids,
        residual_holdout_points,
        residual_holdout_played,
        component_holdout_points,
        holdout_diagnostics,
    ) = _simulate_families(by_player, holdout_simulations, holdout_seed, raw_weight)
    component_holdout_played = holdout_diagnostics.pop("component_played")
    if holdout_player_ids != player_ids:
        raise RuntimeError("Selection and holdout simulation player order differs")

    scenarios: dict[str, Any] = {}
    candidate_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in candidates
    }
    selected = list(map(int, current["selected"]))
    published_lineup = current["lineups"][str(EVENT)]
    def evaluate_scenario(
        name: str, specification: dict[str, Any]
    ) -> tuple[str, dict[str, Any], float]:
        cpu_started = time.process_time()
        factors = scenario_player_factors(flags, specification)
        (
            residual_selection_stressed,
            residual_selection_stressed_played,
            component_selection_stressed,
            component_selection_stressed_played,
            selection_stress_diagnostics,
        ) = _scenario_worlds(
            player_ids,
            residual_selection_points,
            residual_selection_played,
            component_selection_points,
            component_selection_played,
            factors,
            seed=selection_seed + 100_000,
        )
        (
            residual_holdout_stressed,
            residual_holdout_stressed_played,
            component_holdout_stressed,
            component_holdout_stressed_played,
            holdout_stress_diagnostics,
        ) = _scenario_worlds(
            player_ids,
            residual_holdout_points,
            residual_holdout_played,
            component_holdout_points,
            component_holdout_played,
            factors,
            seed=holdout_seed + 100_000,
        )
        configuration = _configuration_audit(
            selected,
            published_lineup,
            meta,
            player_ids,
            residual_selection_stressed,
            residual_selection_stressed_played,
            component_selection_stressed,
            component_selection_stressed_played,
            residual_holdout_stressed,
            residual_holdout_stressed_played,
            component_holdout_stressed,
            component_holdout_stressed_played,
            finalists=finalists,
        )
        squad = _squad_audit(
            candidates,
            published_id,
            meta,
            player_ids,
            residual_selection_stressed,
            residual_selection_stressed_played,
            component_selection_stressed,
            component_selection_stressed_played,
            residual_holdout_stressed,
            residual_holdout_stressed_played,
            component_holdout_stressed,
            component_holdout_stressed_played,
        )
        deep_replay = None
        screen_champion_id = str(squad["selection_champion_id"])
        if screen_champion_id != published_id:
            screen_champion = candidate_by_id[screen_champion_id]
            challenger_configuration = _configuration_audit(
                list(map(int, screen_champion["selected"])),
                screen_champion["lineups"][str(EVENT)],
                meta,
                player_ids,
                residual_selection_stressed,
                residual_selection_stressed_played,
                component_selection_stressed,
                component_selection_stressed_played,
                residual_holdout_stressed,
                residual_holdout_stressed_played,
                component_holdout_stressed,
                component_holdout_stressed_played,
                finalists=finalists,
            )
            comparison = _deep_configuration_comparison(
                challenger_configuration["selection_champion_candidate"],
                configuration["selection_champion_candidate"],
                meta,
                player_ids,
                residual_holdout_stressed,
                residual_holdout_stressed_played,
                component_holdout_stressed,
                component_holdout_stressed_played,
            )
            deep_replay = {
                "challenger_squad_id": screen_champion_id,
                "incumbent_squad_id": published_id,
                "challenger_configuration": challenger_configuration[
                    "selection_champion"
                ],
                "incumbent_configuration": configuration["selection_champion"],
                "challenger_search": challenger_configuration["search"],
                **comparison,
            }
        row = {
            "description": specification["description"],
            "counterfactual_not_probability_estimate": True,
            "stressed_players": {
                str(element): {
                    "name": str(meta[element]["player_name"]),
                    "flag": flags[element],
                    "conditional_retention_factor": factor,
                }
                for element, factor in sorted(factors.items())
            },
            "configuration": configuration,
            "squad": squad,
            "deep_squad_replay": deep_replay,
            "diagnostics": {
                "selection": selection_stress_diagnostics,
                "holdout": holdout_stress_diagnostics,
            },
        }
        return name, row, time.process_time() - cpu_started

    workers = min(len(SCENARIOS), role_scenario_worker_count())
    items = list(SCENARIOS.items())
    if workers == 1:
        evaluated = []
        for name, specification in items:
            print(f"Preseason scenario audit: evaluating {name}", flush=True)
            evaluated_name, row, _ = evaluate_scenario(name, specification)
            evaluated.append((evaluated_name, row))
    else:
        print(
            f"Acceleration: role scenario audit using {workers} memmapped CPU processes",
            flush=True,
        )
        completed: dict[str, dict[str, Any]] = {}
        # Loky starts clean Python interpreters, avoiding the GIL and unsafe CUDA
        # state inheritance. Joblib transparently memory-maps the large immutable
        # simulation tensors instead of serializing a private copy to every worker.
        # Each process intentionally receives one native thread: parallelism belongs
        # at the four independent scenario boundary, not inside BLAS.
        with parallel_config(backend="loky", inner_max_num_threads=1):
            results = Parallel(
                n_jobs=workers,
                return_as="generator_unordered",
                max_nbytes="16M",
                mmap_mode="r",
            )(
                delayed(evaluate_scenario)(name, specification)
                for name, specification in items
            )
            for name, row, worker_cpu_seconds in results:
                _LAST_WORKER_CPU_SECONDS += worker_cpu_seconds
                completed[name] = row
                print(f"Preseason scenario audit: completed {name}", flush=True)
        evaluated = [(name, completed[name]) for name, _ in items]
    scenarios.update(evaluated)

    flag_rows = []
    for element in sorted(candidate_pool):
        flag = flags[element]
        if flag == FLAG_OTHER:
            continue
        evidence = role_by_element[element]
        flag_rows.append(
            {
                "element": element,
                "name": str(meta[element]["player_name"]),
                "team": str(meta[element]["team_name"]),
                "flag": flag,
                "eligible_team_matches": int(evidence["eligible_team_matches"]),
                "squad_listings": int(evidence["squad_listings"]),
                "starts": int(evidence["starts"]),
                "recency_weighted_start_share": (
                    float(evidence["recency_weighted_start_share"])
                    if evidence["recency_weighted_start_share"] is not None
                    else None
                ),
                "last_match_started": evidence["last_match_started"],
            }
        )
    supported_configuration_scenarios = [
        name
        for name, row in scenarios.items()
        if row["configuration"]["cross_family_holdout_support"]
    ]
    supported_squad_screen_scenarios = [
        name
        for name, row in scenarios.items()
        if row["squad"]["cross_family_holdout_support"]
    ]
    supported_deep_squad_scenarios = [
        name
        for name, row in scenarios.items()
        if row["deep_squad_replay"] is not None
        and row["deep_squad_replay"]["cross_family_holdout_support"]
    ]
    result = {
        "version": VERSION,
        "event": EVENT,
        "read_only": True,
        "production_changed": False,
        "promotion_ready": False,
        "verdict": (
            "material_counterfactual_reversal_requires_live_verification"
            if supported_configuration_scenarios or supported_deep_squad_scenarios
            else "published_decision_stable_in_declared_role_scenarios"
        ),
        "lineage": {
            **lineage,
            "preseason_receipt_sha256": sha256_file(role_receipt_path),
            "preseason_role_evidence_sha256": role_evidence_sha,
            "preseason_collected_at": role_receipt["created_at"],
        },
        "coverage": role_receipt["coverage"],
        "candidate_squads": len(candidates),
        "candidate_player_pool": len(candidate_pool),
        "flag_counts": dict(sorted(Counter(flags.values()).items())),
        "flags": flag_rows,
        "scenario_policy": {
            "scenario_weights": None,
            "statement": (
                "Scenarios are counterfactual sensitivity bounds, not posterior probabilities. "
                "Uncovered clubs are not penalized. No scenario can mutate production."
            ),
            "definitions": SCENARIOS,
        },
        "candidate_field_method": (
            "The 37 squads are the synthesis finalists measured by both existing audit families. "
            "Their frozen GW1 configurations form a fast squad screen; only the published 15 is "
            "exhaustively reoptimized across every legal XI in this audit."
        ),
        "scenarios": scenarios,
        "supported_configuration_scenarios": supported_configuration_scenarios,
        "supported_squad_screen_scenarios": supported_squad_screen_scenarios,
        "supported_deep_squad_scenarios": supported_deep_squad_scenarios,
        "supported_squad_scenarios": supported_deep_squad_scenarios,
        "simulation": {
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "component_raw_weight": raw_weight,
            "selection_diagnostics": selection_diagnostics,
            "holdout_diagnostics": holdout_diagnostics,
        },
        "decision_rule": (
            "A supported stress reversal is a deadline verification trigger, not a promotion. "
            "Refresh official and preseason evidence, specify an attributable availability "
            "assumption, rebuild forecasts and rerun the complete GW1 decision pipeline before "
            "changing squad, XI, bench or captaincy."
        ),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result


def _format_interval(metric: dict[str, float]) -> str:
    return (
        f"{metric['mean']:+.3f} "
        f"[{metric['ci95_low']:+.3f}, {metric['ci95_high']:+.3f}]"
    )


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Preseason role scenario audit",
        "",
        f"**Verdict:** `{result['verdict']}`  ",
        "**Production changed:** no",
        "",
        (
            "This checksum-bound audit applies declared conditional-DNP perturbations to the "
            "same residual and component worlds. They are sensitivity bounds, not estimated "
            "player probabilities."
        ),
        "",
        "## Evidence flags in the synthesis player pool",
        "",
        "| Player | Team | Flag | Eligible | Listed | Starts | Recent start share | Latest start |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in result["flags"]:
        recent = row["recency_weighted_start_share"]
        recent_label = "n/a" if recent is None else f"{recent:.0%}"
        latest = row["last_match_started"]
        latest_label = "n/a" if latest is None else "yes" if latest else "no"
        lines.append(
            f"| {row['name']} | {row['team']} | {row['flag']} | "
            f"{row['eligible_team_matches']} | {row['squad_listings']} | "
            f"{row['starts']} | {recent_label} | {latest_label} |"
        )
    lines.extend(
        [
            "",
            (
                "Uncovered clubs receive no negative factor. A player missing from a friendly "
                "lineup is not labelled injured or unavailable."
            ),
            "",
            "## Counterfactual results",
            "",
            (
                "Each leader was chosen on the selection sample. The table reports its paired "
                "holdout difference to the published configuration/squad in the independent "
                "residual and component families."
            ),
            "",
            (
                "The configuration column exhaustively reoptimizes the published 15. The squad "
                "column is a screen over each synthesis finalist's frozen GW1 configuration; a "
                "screen reversal requires a deeper scenario-specific replay before it could be "
                "considered."
            ),
            "",
            "| Scenario | Configuration leader | Config residual | Config component | Frozen-config squad screen | Squad residual | Squad component |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for name, row in result["scenarios"].items():
        configuration = row["configuration"]
        squad = row["squad"]
        configuration_delta = configuration["holdout_delta_to_published"]
        squad_delta = squad["holdout_delta_to_published"]
        lines.append(
            f"| {name} | {configuration['selection_champion']['formation']} · "
            f"{configuration['selection_champion']['captain']} | "
            f"{_format_interval(configuration_delta['residual'])} | "
            f"{_format_interval(configuration_delta['component'])} | "
            f"{squad['selection_champion_id']} | "
            f"{_format_interval(squad_delta['residual'])} | "
            f"{_format_interval(squad_delta['component'])} |"
        )
    lines.extend(
        [
            "",
            "## Exhaustive challenger configuration replay",
            "",
            (
                "Every non-incumbent squad that wins the frozen-configuration screen is then "
                "given the same exhaustive 550-XI, bench-order, captain and vice search as the "
                "published 15. Its preselected configuration is compared with the incumbent's "
                "preselected configuration on the independent holdout."
            ),
            "",
            "| Scenario | Challenger | Challenger shape/captain | Incumbent shape/captain | Residual delta | Component delta | Supported |",
            "| --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    deep_rows = 0
    for name, row in result["scenarios"].items():
        replay = row["deep_squad_replay"]
        if replay is None:
            continue
        deep_rows += 1
        delta = replay["holdout_delta_challenger_to_incumbent"]
        challenger = replay["challenger_configuration"]
        incumbent = replay["incumbent_configuration"]
        lines.append(
            f"| {name} | {replay['challenger_squad_id']} | "
            f"{challenger['formation']} · {challenger['captain']} | "
            f"{incumbent['formation']} · {incumbent['captain']} | "
            f"{_format_interval(delta['residual'])} | "
            f"{_format_interval(delta['component'])} | "
            f"{replay['cross_family_holdout_support']} |"
        )
    if not deep_rows:
        lines.append("| none | — | — | — | — | — | — |")
    lines.extend(
        [
            "",
            "## Scenario details",
            "",
        ]
    )
    for name, row in result["scenarios"].items():
        configuration = row["configuration"]["selection_champion"]
        squad = row["squad"]
        lines.extend(
            [
                f"### {name}",
                "",
                row["description"],
                "",
                f"- XI: {', '.join(configuration['starters'])}",
                f"- Bench: {', '.join(configuration['bench_order'])}",
                (
                    f"- Captain / vice: {configuration['captain']} / "
                    f"{configuration['vice_captain']}"
                ),
                f"- Squad leader: `{squad['selection_champion_id']}`",
                (
                    f"- Squad changes: {', '.join(squad['players_out']) or 'none'} out; "
                    f"{', '.join(squad['players_in']) or 'none'} in"
                ),
                (
                    "- Cross-family configuration support: "
                    f"{row['configuration']['cross_family_holdout_support']}"
                ),
                (
                    "- Frozen-config squad screen support: "
                    f"{row['squad']['cross_family_holdout_support']}"
                ),
                (
                    "- Deep squad support: "
                    f"{row['deep_squad_replay']['cross_family_holdout_support']}"
                    if row["deep_squad_replay"] is not None
                    else "- Deep squad support: not required"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Operational rule",
            "",
            result["decision_rule"],
            "",
            (
                f"Selection used {result['simulation']['selection_simulations_per_family']:,} "
                "worlds per family; holdout used "
                f"{result['simulation']['holdout_simulations_per_family']:,}."
            ),
            "",
        ]
    )
    return "\n".join(lines)
