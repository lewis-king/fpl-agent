from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .artifact_lineage import ArtifactLineageError, load_json_artifact
from .current_squad_audit import (
    _candidate,
    _rank_candidates,
    _simulate_families,
)
from .current_squad_audit import _verify_lineage as _verify_current_lineage
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .preseason_role_scenario import (
    EVENT,
    FLAG_NOT_LISTED,
    FLAG_ROLE_WATCH,
    FPL_DIR,
    ROLE_EVIDENCE,
    ROLE_RECEIPT,
    _deep_configuration_comparison,
    _scenario_worlds,
    _verify_role_lineage,
    derive_role_flags,
)
from .preseason_role_scenario import RESULTS_JSON as SCENARIO_RESULTS
from .preseason_role_scenario import VERSION as SCENARIO_VERSION
from .robust_search import RESULTS_JSON as ROBUST_RESULTS
from .robust_search import SHORTLIST_JSON
from .tournament import _load_rows, _score_candidates

VERSION = "preseason_role_threshold_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "preseason-role-threshold-audit.md"

# This path interpolates between the earlier severe and moderate sensitivity bounds.
# It is deliberately labelled as retention, not probability.
DEFAULT_NOT_LISTED_RETENTIONS = (
    *(round(0.50 + 0.005 * index, 3) for index in range(6)),
    *(round(0.55 + 0.025 * index, 3) for index in range(9)),
)


def coupled_role_watch_retention(not_listed_retention: float) -> float:
    """Interpolate the declared role-watch factor from severe to moderate stress."""
    if not 0.50 <= not_listed_retention <= 0.75:
        raise ValueError("The coupled threshold path is defined from 0.50 to 0.75")
    return round(0.45 + 0.60 * not_listed_retention, 3)


def build_threshold_grid(
    not_listed_retentions: Iterable[float] = DEFAULT_NOT_LISTED_RETENTIONS,
) -> list[dict[str, Any]]:
    values = [round(float(value), 3) for value in not_listed_retentions]
    if not values:
        raise ValueError("At least one threshold point is required")
    if values != sorted(set(values)):
        raise ValueError("Threshold retentions must be unique and ascending")
    return [
        {
            "threshold_id": f"retention-{round(value * 1000):04d}",
            "not_listed_retention": value,
            "role_watch_retention": coupled_role_watch_retention(value),
            "severity_fraction": round((0.75 - value) / 0.25, 3),
        }
        for value in values
    ]


def summarize_supported_boundary(points: list[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        raise ValueError("Cannot summarize an empty threshold curve")
    ordered = sorted(points, key=lambda row: row["not_listed_retention"])
    support = [bool(row["cross_family_holdout_support"]) for row in ordered]
    seen_unsupported = False
    monotone = True
    for value in support:
        if not value:
            seen_unsupported = True
        elif seen_unsupported:
            monotone = False

    supported = [row for row in ordered if row["cross_family_holdout_support"]]
    if not supported:
        return {
            "classification": "no_supported_challenger_on_tested_path",
            "support_is_monotone": monotone,
            "highest_supported_retention": None,
            "next_tested_unsupported_retention": ordered[0][
                "not_listed_retention"
            ],
        }

    highest = max(supported, key=lambda row: row["not_listed_retention"])
    next_unsupported = next(
        (
            row
            for row in ordered
            if row["not_listed_retention"]
            > highest["not_listed_retention"]
            and not row["cross_family_holdout_support"]
        ),
        None,
    )
    classification = (
        "supported_to_top_of_tested_path"
        if next_unsupported is None
        else "supported_boundary_bracketed"
    )
    if not monotone:
        classification = "non_monotone_support_requires_finer_replay"
    return {
        "classification": classification,
        "support_is_monotone": monotone,
        "highest_supported_retention": highest["not_listed_retention"],
        "highest_supported_role_watch_retention": highest[
            "role_watch_retention"
        ],
        "highest_supported_challenger_squad_id": highest[
            "challenger_squad_id"
        ],
        "next_tested_unsupported_retention": (
            next_unsupported["not_listed_retention"]
            if next_unsupported is not None
            else None
        ),
        "next_tested_unsupported_role_watch_retention": (
            next_unsupported["role_watch_retention"]
            if next_unsupported is not None
            else None
        ),
        "grid_resolution": (
            round(
                min(
                    right["not_listed_retention"]
                    - left["not_listed_retention"]
                    for left, right in pairwise(ordered)
                ),
                6,
            )
            if len(ordered) > 1
            else None
        ),
    }


def reconstruct_named_configuration(
    selected: list[int],
    named_configuration: dict[str, Any],
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    names: dict[str, list[int]] = defaultdict(list)
    for element in selected:
        names[str(meta[element]["player_name"])].append(element)

    def element_for(name: str) -> int:
        matches = names.get(str(name), [])
        if len(matches) != 1:
            raise ValueError(
                f"Configuration name {name!r} maps to {len(matches)} players in the squad"
            )
        return matches[0]

    starters = tuple(element_for(name) for name in named_configuration["starters"])
    bench_order = tuple(
        element_for(name) for name in named_configuration["bench_order"]
    )
    captain = element_for(str(named_configuration["captain"]))
    vice = element_for(str(named_configuration["vice_captain"]))
    if len(starters) != 11 or len(bench_order) != 4:
        raise ValueError("A reconstructed configuration must have 11 starters and 4 bench players")
    if set(starters) & set(bench_order) or set(starters) | set(bench_order) != set(
        selected
    ):
        raise ValueError("Reconstructed starters and bench do not partition the selected 15")
    if captain == vice or captain not in starters or vice not in starters:
        raise ValueError("Captain and vice must be distinct starters")

    candidate = _candidate(
        selected,
        starters,
        bench_order,
        captain,
        vice,
        meta,
    )
    expected_id = str(named_configuration["candidate_id"])
    if candidate["candidate_id"] != expected_id:
        raise ArtifactLineageError(
            "Named configuration does not reproduce its recorded candidate ID: "
            f"{candidate['candidate_id']} != {expected_id}"
        )
    expected_formation = str(named_configuration["formation"])
    actual_formation = str(candidate["lineups"][str(EVENT)]["formation"])
    if actual_formation != expected_formation:
        raise ArtifactLineageError(
            "Named configuration formation differs after reconstruction: "
            f"{actual_formation} != {expected_formation}"
        )
    return candidate


def _normalized_event_configuration(
    squad: dict[str, Any], meta: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    selected = list(map(int, squad["selected"]))
    lineup = squad["lineups"][str(EVENT)]
    return _candidate(
        selected,
        tuple(map(int, lineup["starters"])),
        tuple(map(int, lineup["bench_order"])),
        int(lineup["captain"]),
        int(lineup["vice_captain"]),
        meta,
    )


def _candidate_summary(
    candidate: dict[str, Any], meta: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    lineup = candidate["lineups"][str(EVENT)]
    return {
        "candidate_id": str(candidate["candidate_id"]),
        "formation": str(lineup["formation"]),
        "starters": [
            str(meta[int(element)]["player_name"]) for element in lineup["starters"]
        ],
        "bench_order": [
            str(meta[int(element)]["player_name"])
            for element in lineup["bench_order"]
        ],
        "captain": str(meta[int(lineup["captain"])]["player_name"]),
        "vice_captain": str(meta[int(lineup["vice_captain"])]["player_name"]),
    }


def _verify_threshold_lineage(
    scenario_result: dict[str, Any],
    *,
    decision_path: Path = SYNTHESIZED_DECISION,
    scenario_results_path: Path = SCENARIO_RESULTS,
    shortlist_path: Path = SHORTLIST_JSON,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    fpl_dir: Path = FPL_DIR,
) -> tuple[dict[str, Any], dict[str, str]]:
    if scenario_result.get("version") != SCENARIO_VERSION:
        raise ArtifactLineageError("Unsupported preseason role scenario version")
    decision, current_lineage = _verify_current_lineage(decision_path=decision_path)
    if sha256_file(decision_path) != current_lineage["decision_sha256"]:
        raise ArtifactLineageError("Current decision changed during threshold validation")
    for field, expected in current_lineage.items():
        if scenario_result.get("lineage", {}).get(field) != expected:
            raise ArtifactLineageError(
                f"Role scenario {field} differs from the active evidence run"
            )
    _, role_sha = _verify_role_lineage(
        role_receipt_path=role_receipt_path,
        role_evidence_path=role_evidence_path,
        fpl_dir=fpl_dir,
    )
    role_receipt_sha = sha256_file(role_receipt_path)
    if scenario_result.get("lineage", {}).get(
        "preseason_role_evidence_sha256"
    ) != role_sha:
        raise ArtifactLineageError("Role scenario uses stale preseason role evidence")
    if scenario_result.get("lineage", {}).get(
        "preseason_receipt_sha256"
    ) != role_receipt_sha:
        raise ArtifactLineageError("Role scenario uses a stale preseason receipt")
    robust = load_json_artifact(ROBUST_RESULTS, "global robust-search results")
    shortlist_sha = sha256_file(shortlist_path)
    if robust.get("artifacts", {}).get("global_shortlist_sha256") != shortlist_sha:
        raise ArtifactLineageError("Global shortlist differs from its robust-search receipt")
    if scenario_result.get("production_changed") is not False:
        raise ArtifactLineageError("Threshold source must be a read-only scenario audit")
    return decision, {
        **current_lineage,
        "preseason_role_evidence_sha256": role_sha,
        "preseason_receipt_sha256": role_receipt_sha,
        "preseason_role_scenario_sha256": sha256_file(scenario_results_path),
        "global_shortlist_sha256": shortlist_sha,
    }


def _build_configuration_portfolios(
    scenario_result: dict[str, Any],
    decision: dict[str, Any],
    shortlist: dict[str, Any],
    meta: dict[int, dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    current = decision["decision"]["candidate"]
    incumbent_id = str(current["candidate_id"])
    shortlist_by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in shortlist["candidates"]
    }
    shortlist_by_id[incumbent_id] = current

    portfolios: dict[str, dict[str, Any]] = {}

    def ensure_portfolio(squad_id: str) -> dict[str, Any]:
        if squad_id not in shortlist_by_id:
            raise ArtifactLineageError(
                f"Scenario squad {squad_id} is missing from the robust shortlist"
            )
        squad = shortlist_by_id[squad_id]
        selected = list(map(int, squad["selected"]))
        portfolio = portfolios.setdefault(
            squad_id,
            {
                "squad_id": squad_id,
                "selected": selected,
                "configurations": {},
                "origins": defaultdict(list),
            },
        )
        return portfolio

    def add(squad_id: str, candidate: dict[str, Any], origin: str) -> None:
        portfolio = ensure_portfolio(squad_id)
        if set(map(int, candidate["selected"])) != set(portfolio["selected"]):
            raise ArtifactLineageError(
                f"Configuration {candidate['candidate_id']} does not belong to {squad_id}"
            )
        candidate_id = str(candidate["candidate_id"])
        portfolio["configurations"][candidate_id] = candidate
        portfolio["origins"][candidate_id].append(origin)

    add(
        incumbent_id,
        _normalized_event_configuration(current, meta),
        "published_configuration",
    )
    for scenario_name, scenario in scenario_result["scenarios"].items():
        configuration = scenario["configuration"]["selection_champion_candidate"]
        add(incumbent_id, configuration, f"{scenario_name}:incumbent_exhaustive")
        replay = scenario.get("deep_squad_replay")
        if replay is None:
            continue
        challenger_id = str(replay["challenger_squad_id"])
        challenger_squad = shortlist_by_id.get(challenger_id)
        if challenger_squad is None:
            raise ArtifactLineageError(
                f"Deep-replay challenger {challenger_id} is missing from the shortlist"
            )
        add(
            challenger_id,
            reconstruct_named_configuration(
                list(map(int, challenger_squad["selected"])),
                replay["challenger_configuration"],
                meta,
            ),
            f"{scenario_name}:challenger_exhaustive",
        )

    for squad_id, portfolio in portfolios.items():
        squad = shortlist_by_id[squad_id]
        add(
            squad_id,
            _normalized_event_configuration(squad, meta),
            "central_frozen_configuration",
        )

    if set(portfolios) == {incumbent_id}:
        raise ArtifactLineageError("No deep-replay challenger is available for thresholding")
    output = []
    for squad_id in sorted(portfolios):
        portfolio = portfolios[squad_id]
        output.append(
            {
                "squad_id": squad_id,
                "selected": portfolio["selected"],
                "configurations": list(portfolio["configurations"].values()),
                "origins": {
                    candidate_id: sorted(origins)
                    for candidate_id, origins in portfolio["origins"].items()
                },
            }
        )
    return incumbent_id, output


def _evaluate_portfolios(
    portfolios: list[dict[str, Any]],
    incumbent_id: str,
    meta: dict[int, dict[str, Any]],
    player_ids: list[int],
    residual_selection_points: Any,
    residual_selection_played: Any,
    component_selection_points: Any,
    component_selection_played: Any,
    residual_holdout_points: Any,
    residual_holdout_played: Any,
    component_holdout_points: Any,
    component_holdout_played: Any,
) -> dict[str, Any]:
    configurations: list[dict[str, Any]] = []
    squad_by_candidate: dict[str, str] = {}
    candidate_by_id: dict[str, dict[str, Any]] = {}
    for portfolio in portfolios:
        for candidate in portfolio["configurations"]:
            candidate_id = str(candidate["candidate_id"])
            prior = squad_by_candidate.get(candidate_id)
            if prior is not None and prior != portfolio["squad_id"]:
                raise ArtifactLineageError(
                    f"Configuration {candidate_id} appears in two squad portfolios"
                )
            if candidate_id in candidate_by_id:
                continue
            configurations.append(candidate)
            candidate_by_id[candidate_id] = candidate
            squad_by_candidate[candidate_id] = str(portfolio["squad_id"])

    residual_scores = _score_candidates(
        configurations,
        player_ids,
        (EVENT,),
        residual_selection_points,
        residual_selection_played,
        meta,
    )
    component_scores = _score_candidates(
        configurations,
        player_ids,
        (EVENT,),
        component_selection_points,
        component_selection_played,
        meta,
    )
    ranking = _rank_candidates(configurations, residual_scores, component_scores)
    champions: dict[str, dict[str, Any]] = {}
    for row in ranking:
        squad_id = squad_by_candidate[str(row["candidate_id"])]
        champions.setdefault(squad_id, row)
    if incumbent_id not in champions:
        raise RuntimeError("Incumbent portfolio produced no selection champion")
    challenger_row = next(
        row
        for row in ranking
        if squad_by_candidate[str(row["candidate_id"])] != incumbent_id
    )
    challenger_id = squad_by_candidate[str(challenger_row["candidate_id"])]
    incumbent_row = champions[incumbent_id]
    challenger = candidate_by_id[str(challenger_row["candidate_id"])]
    incumbent = candidate_by_id[str(incumbent_row["candidate_id"])]
    comparison = _deep_configuration_comparison(
        challenger,
        incumbent,
        meta,
        player_ids,
        residual_holdout_points,
        residual_holdout_played,
        component_holdout_points,
        component_holdout_played,
    )
    incumbent_selected = set(map(int, incumbent["selected"]))
    challenger_selected = set(map(int, challenger["selected"]))
    return {
        "incumbent_squad_id": incumbent_id,
        "incumbent_configuration": _candidate_summary(incumbent, meta),
        "incumbent_selection_metrics": incumbent_row,
        "challenger_squad_id": challenger_id,
        "challenger_configuration": _candidate_summary(challenger, meta),
        "challenger_selection_metrics": challenger_row,
        "players_in": [
            str(meta[element]["player_name"])
            for element in sorted(challenger_selected - incumbent_selected)
        ],
        "players_out": [
            str(meta[element]["player_name"])
            for element in sorted(incumbent_selected - challenger_selected)
        ],
        **comparison,
    }


def run_preseason_role_threshold_audit(
    *,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    selection_seed: int = 20260814,
    holdout_seed: int = 20260815,
    not_listed_retentions: Iterable[
        float
    ] = DEFAULT_NOT_LISTED_RETENTIONS,
    scenario_results_path: Path = SCENARIO_RESULTS,
    decision_path: Path = SYNTHESIZED_DECISION,
    shortlist_path: Path = SHORTLIST_JSON,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    fpl_dir: Path = FPL_DIR,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if selection_simulations < 2_000 or holdout_simulations < 5_000:
        raise ValueError("Threshold simulation counts are below the safety minimum")
    if selection_seed == holdout_seed:
        raise ValueError("Selection and holdout require independent seeds")
    grid = build_threshold_grid(not_listed_retentions)
    ensure_engine_layout()
    scenario_result = load_json_artifact(
        scenario_results_path, "preseason role scenario results"
    )
    decision, lineage = _verify_threshold_lineage(
        scenario_result,
        decision_path=decision_path,
        scenario_results_path=scenario_results_path,
        shortlist_path=shortlist_path,
        role_receipt_path=role_receipt_path,
        role_evidence_path=role_evidence_path,
        fpl_dir=fpl_dir,
    )
    shortlist = load_json_artifact(shortlist_path, "global robust-search shortlist")
    _, loaded = _load_rows((EVENT,))
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    incumbent_id, portfolios = _build_configuration_portfolios(
        scenario_result, decision, shortlist, meta
    )
    candidate_pool = {
        int(element)
        for portfolio in portfolios
        for element in portfolio["selected"]
    }
    role_rows = pq.read_table(role_evidence_path).to_pylist()
    flags = derive_role_flags(role_rows, candidate_pool)
    raw_weight = float(scenario_result["simulation"]["component_raw_weight"])

    print("Preseason threshold audit: simulating selection worlds", flush=True)
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
    print("Preseason threshold audit: simulating holdout worlds", flush=True)
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

    points: list[dict[str, Any]] = []
    for threshold in grid:
        print(
            "Preseason threshold audit: evaluating "
            f"{threshold['not_listed_retention']:.3f}",
            flush=True,
        )
        factors = {
            element: (
                threshold["not_listed_retention"]
                if flag == FLAG_NOT_LISTED
                else threshold["role_watch_retention"]
            )
            for element, flag in flags.items()
            if flag in {FLAG_NOT_LISTED, FLAG_ROLE_WATCH}
        }
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
        evaluation = _evaluate_portfolios(
            portfolios,
            incumbent_id,
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
        points.append(
            {
                **threshold,
                **evaluation,
                "mechanical_appearance_rates": {
                    str(element): {
                        "name": str(meta[element]["player_name"]),
                        "flag": flags[element],
                        "base_p_play": float(by_player[element][EVENT]["p_play"]),
                        "retention_factor": factor,
                        "mechanically_retained_p_play": float(
                            by_player[element][EVENT]["p_play"] * factor
                        ),
                    }
                    for element, factor in sorted(factors.items())
                },
                "diagnostics": {
                    "selection": selection_stress_diagnostics,
                    "holdout": holdout_stress_diagnostics,
                },
            }
        )

    boundary = summarize_supported_boundary(points)
    role_flag_rows = [
        {
            "element": element,
            "name": str(meta[element]["player_name"]),
            "team": str(meta[element]["team_name"]),
            "flag": flags[element],
            "base_p_play": float(by_player[element][EVENT]["p_play"]),
        }
        for element in sorted(flags)
        if flags[element] in {FLAG_NOT_LISTED, FLAG_ROLE_WATCH}
    ]
    result = {
        "version": VERSION,
        "event": EVENT,
        "read_only": True,
        "production_changed": False,
        "promotion_ready": False,
        "verdict": boundary["classification"],
        "lineage": lineage,
        "method": {
            "statement": (
                "Fresh selection simulations choose the best configuration within each "
                "squad's preselected endpoint portfolio. Independent holdout simulations "
                "then compare the best challenger with the incumbent at each threshold."
            ),
            "scope_limit": (
                "This is a coupled sensitivity path over configurations discovered by prior "
                "exhaustive endpoint searches, not a new exhaustive squad search at every "
                "grid point and not an availability probability model."
            ),
            "same_masks_across_thresholds": True,
            "conditional_retention_not_probability": True,
            "not_listed_range": [
                grid[0]["not_listed_retention"],
                grid[-1]["not_listed_retention"],
            ],
            "role_watch_formula": "0.45 + 0.60 * not_listed_retention",
        },
        "incumbent_squad_id": incumbent_id,
        "portfolios": [
            {
                "squad_id": portfolio["squad_id"],
                "selected": [
                    str(meta[element]["player_name"])
                    for element in portfolio["selected"]
                ],
                "configuration_count": len(portfolio["configurations"]),
                "origins": portfolio["origins"],
            }
            for portfolio in portfolios
        ],
        "role_flags": role_flag_rows,
        "threshold_points": points,
        "boundary": boundary,
        "simulation": {
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "component_raw_weight": raw_weight,
            "selection_diagnostics": selection_diagnostics,
            "holdout_diagnostics": holdout_diagnostics,
        },
        "operational_rule": (
            "Do not change the published squad from this curve. Treat its supported bracket "
            "as a verification trigger: translate attributable deadline evidence into the "
            "forecast appearance model, rebuild forecasts, and rerun the complete GW1 "
            "decision pipeline before promotion."
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
    boundary = result["boundary"]
    lines = [
        "# Preseason availability-retention threshold audit",
        "",
        f"**Verdict:** `{result['verdict']}`  ",
        "**Production changed:** no",
        "",
        result["method"]["statement"],
        "",
        result["method"]["scope_limit"],
        "",
        "## Decision boundary",
        "",
    ]
    if boundary["highest_supported_retention"] is None:
        lines.append("No challenger has cross-family support on the tested path.")
    else:
        lines.extend(
            [
                (
                    "The mildest tested point still supporting the challenger retains "
                    f"{boundary['highest_supported_retention']:.1%} of simulated appearances "
                    "for three-plus-lineup absences and "
                    f"{boundary['highest_supported_role_watch_retention']:.1%} for role-watch "
                    "players."
                ),
                "",
                (
                    "The next milder tested point does not support the challenger: "
                    f"{boundary['next_tested_unsupported_retention']:.1%}."
                    if boundary["next_tested_unsupported_retention"] is not None
                    else "Support persists to the mildest end of the tested path."
                ),
            ]
        )
    lines.extend(
        [
            "",
            (
                "These factors thin appearances already present in the production "
                "simulation. They are not direct estimates of real availability."
            ),
            "",
            "## Threshold curve",
            "",
            "| Not-listed retention | Role-watch retention | Challenger | Changes | Challenger shape / captain | Incumbent shape / captain | Residual delta | Component delta | Supported |",
            "| ---: | ---: | --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for point in result["threshold_points"]:
        delta = point["holdout_delta_challenger_to_incumbent"]
        challenger = point["challenger_configuration"]
        incumbent = point["incumbent_configuration"]
        changes = (
            f"{', '.join(point['players_out'])} → {', '.join(point['players_in'])}"
        )
        lines.append(
            f"| {point['not_listed_retention']:.1%} | "
            f"{point['role_watch_retention']:.1%} | "
            f"`{point['challenger_squad_id']}` | {changes} | "
            f"{challenger['formation']} / {challenger['captain']} | "
            f"{incumbent['formation']} / {incumbent['captain']} | "
            f"{_format_interval(delta['residual'])} | "
            f"{_format_interval(delta['component'])} | "
            f"{point['cross_family_holdout_support']} |"
        )
    lines.extend(
        [
            "",
            "## Players affected by the sensitivity path",
            "",
            "| Player | Team | Evidence flag | Production p(play) |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for row in result["role_flags"]:
        lines.append(
            f"| {row['name']} | {row['team']} | {row['flag']} | "
            f"{row['base_p_play']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Operational rule",
            "",
            result["operational_rule"],
            "",
            (
                f"Selection used {result['simulation']['selection_simulations_per_family']:,} "
                "worlds per family; independent holdout used "
                f"{result['simulation']['holdout_simulations_per_family']:,}."
            ),
            "",
        ]
    )
    return "\n".join(lines)
