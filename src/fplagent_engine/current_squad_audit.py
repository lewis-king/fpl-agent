from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations, permutations, product
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)
from .component_models import CURRENT_COMPONENT_FORECAST
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
)
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .horizon_audit import RESULTS_JSON as HORIZON_RESULTS
from .models import CURRENT_FORECAST
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import RESULTS_JSON as ROBUST_RESULTS
from .rules import SquadRules, load_rules
from .tournament import (
    _load_rows,
    _score_candidates,
    _simulate_player_outcomes,
    calibrate_residuals,
)

VERSION = "current_squad_adversarial_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "current-squad-xi-captain-bench-audit.md"
EVENT = 1


def enumerate_legal_xis(
    selected: list[int],
    meta: dict[int, dict[str, Any]],
    rules: SquadRules | None = None,
) -> list[tuple[int, ...]]:
    """Enumerate every legal starting XI for one valid 15-player squad."""
    rules = rules or load_rules()
    by_position = {
        position: sorted(element for element in selected if meta[element]["position"] == position)
        for position in rules.squad_positions
    }
    lineups: list[tuple[int, ...]] = []
    for goalkeeper in combinations(by_position["GK"], 1):
        for defenders in range(
            rules.minimum_starters["DEF"], rules.maximum_starters["DEF"] + 1
        ):
            for midfielders in range(
                rules.minimum_starters["MID"], rules.maximum_starters["MID"] + 1
            ):
                forwards = rules.starting_size - 1 - defenders - midfielders
                if not (
                    rules.minimum_starters["FWD"]
                    <= forwards
                    <= rules.maximum_starters["FWD"]
                ):
                    continue
                for groups in product(
                    combinations(by_position["DEF"], defenders),
                    combinations(by_position["MID"], midfielders),
                    combinations(by_position["FWD"], forwards),
                ):
                    lineups.append((*goalkeeper, *groups[0], *groups[1], *groups[2]))
    return lineups


def _formation(starters: tuple[int, ...], meta: dict[int, dict[str, Any]]) -> str:
    return "-".join(
        str(sum(meta[element]["position"] == position for element in starters))
        for position in ("DEF", "MID", "FWD")
    )


def _candidate(
    selected: list[int],
    starters: tuple[int, ...],
    bench_order: tuple[int, ...],
    captain: int,
    vice: int,
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    identity = {
        "starters": sorted(starters),
        "bench_order": list(bench_order),
        "captain": captain,
        "vice_captain": vice,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return {
        "candidate_id": f"XI-{digest}",
        "selected": list(selected),
        "lineups": {
            str(EVENT): {
                **identity,
                "formation": _formation(starters, meta),
            }
        },
    }


def _bench_orders(
    selected: list[int], starters: tuple[int, ...], meta: dict[int, dict[str, Any]]
) -> list[tuple[int, ...]]:
    bench = set(selected) - set(starters)
    outfield = sorted(element for element in bench if meta[element]["position"] != "GK")
    reserve_goalkeepers = sorted(
        element for element in bench if meta[element]["position"] == "GK"
    )
    if len(outfield) != 3 or len(reserve_goalkeepers) != 1:
        raise ValueError("A legal FPL XI must leave three outfield substitutes and one goalkeeper")
    return [(*order, reserve_goalkeepers[0]) for order in permutations(outfield)]


def _captain_bonus(
    points: np.ndarray,
    played: np.ndarray,
    player_index: dict[int, int],
    captain: int,
    vice: int,
) -> np.ndarray:
    captain_index = player_index[captain]
    vice_index = player_index[vice]
    return np.where(
        played[:, 0, captain_index],
        points[:, 0, captain_index],
        np.where(played[:, 0, vice_index], points[:, 0, vice_index], 0),
    )


def _choice_leaders(family_means: np.ndarray, limit: int = 3) -> list[int]:
    """Return the minimax-balanced choice plus each family-specific leader."""
    leaders = family_means.max(axis=0)
    regrets = leaders[None, :] - family_means
    scores = 0.8 * regrets.mean(axis=1) + 0.2 * regrets.max(axis=1)
    ordered = list(np.argsort(scores, kind="stable"))
    family_leaders = [int(np.argmax(family_means[:, index])) for index in range(2)]
    output: list[int] = []
    for index in [*ordered, *family_leaders]:
        value = int(index)
        if value not in output:
            output.append(value)
        if len(output) == limit:
            break
    return output


def _rank_candidates(
    candidates: list[dict[str, Any]], residual_scores: np.ndarray, component_scores: np.ndarray
) -> list[dict[str, Any]]:
    means = np.column_stack(
        (residual_scores[:, :, 0].mean(axis=0), component_scores[:, :, 0].mean(axis=0))
    )
    leaders = means.max(axis=0)
    regrets = leaders[None, :] - means
    robust = 0.8 * regrets.mean(axis=1) + 0.2 * regrets.max(axis=1)
    rows = []
    for index, candidate in enumerate(candidates):
        lineup = candidate["lineups"][str(EVENT)]
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "formation": lineup["formation"],
                "starters": list(map(int, lineup["starters"])),
                "bench_order": list(map(int, lineup["bench_order"])),
                "captain": int(lineup["captain"]),
                "vice_captain": int(lineup["vice_captain"]),
                "residual_mean": float(means[index, 0]),
                "component_mean": float(means[index, 1]),
                "residual_regret": float(regrets[index, 0]),
                "component_regret": float(regrets[index, 1]),
                "robust_regret": float(robust[index]),
            }
        )
    rows.sort(key=lambda row: (row["robust_regret"], row["candidate_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _paired_delta(challenger: np.ndarray, incumbent: np.ndarray) -> dict[str, float]:
    delta = challenger.astype(np.float64) - incumbent.astype(np.float64)
    mean = float(delta.mean())
    standard_error = float(delta.std(ddof=1) / math.sqrt(len(delta)))
    return {
        "mean": mean,
        "ci95_low": mean - 1.96 * standard_error,
        "ci95_high": mean + 1.96 * standard_error,
        "beat_probability": float(np.mean(delta > 0)),
        "tie_probability": float(np.mean(delta == 0)),
    }


def _player_labels(elements: list[int], meta: dict[int, dict[str, Any]]) -> list[str]:
    return [str(meta[element]["player_name"]) for element in elements]


def _simulate_families(
    by_player: dict[int, dict[int, dict[str, Any]]],
    simulations: int,
    seed: int,
    raw_weight: float,
) -> tuple[list[int], np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    events = (EVENT,)
    player_ids = sorted(by_player)
    residual_points, residual_played = _simulate_player_outcomes(
        player_ids,
        events,
        by_player,
        calibrate_residuals(),
        simulations,
        seed,
    )
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, events)
    (
        component_player_ids,
        component_raw,
        component_anchored,
        component_played,
        _,
        component_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        events,
        goal_rates,
        calibrate_empirical_components(),
        simulations,
        seed + 10_000,
    )
    if component_player_ids != player_ids:
        raise RuntimeError("Residual and component simulation player order differs")
    component_evidence = component_anchored + raw_weight * (
        component_raw - component_anchored
    )
    diagnostics = {
        "goal_rates": goal_diagnostics,
        "component": component_diagnostics,
    }
    return (
        player_ids,
        residual_points,
        residual_played,
        component_evidence,
        {**diagnostics, "component_played": component_played},
    )


def _verify_lineage(
    *, decision_path: Path = SYNTHESIZED_DECISION
) -> tuple[dict[str, Any], dict[str, str]]:
    decision = load_json_artifact(decision_path, "synthesized GW1 decision")
    robust_sha = require_recorded_file(
        decision,
        ("source_artifacts", "robust_results_sha256"),
        ROBUST_RESULTS,
        "synthesized decision robust input",
    )
    horizon_sha = require_recorded_file(
        decision,
        ("source_artifacts", "horizon_results_sha256"),
        HORIZON_RESULTS,
        "synthesized decision horizon input",
    )
    robust = load_json_artifact(ROBUST_RESULTS, "global robust-search results")
    horizon = load_json_artifact(HORIZON_RESULTS, "horizon-audit results")
    forecast_sha = require_current_forecast(
        robust,
        CURRENT_FORECAST,
        "global robust-search results",
        fields=("artifacts", "forecast_sha256"),
    )
    require_current_forecast(
        horizon,
        CURRENT_FORECAST,
        "horizon-audit results",
        fields=("artifacts", "forecast_sha256"),
    )
    return decision, {
        "decision_sha256": sha256_file(decision_path),
        "forecast_sha256": forecast_sha,
        "component_forecast_sha256": sha256_file(CURRENT_COMPONENT_FORECAST),
        "robust_results_sha256": robust_sha,
        "horizon_results_sha256": horizon_sha,
    }


def run_current_squad_audit(
    *,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    finalists: int = 64,
    selection_seed: int = 20260810,
    holdout_seed: int = 20260811,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if selection_simulations < 2_000 or holdout_simulations < 5_000:
        raise ValueError("Current-squad audit simulation counts are too small")
    ensure_engine_layout()
    decision, lineage = _verify_lineage()
    current = decision["decision"]["candidate"]
    selected = list(map(int, current["selected"]))
    current_lineup = current["lineups"][str(EVENT)]
    _, loaded = _load_rows((EVENT,))
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    if not set(selected) <= set(by_player):
        raise ValueError("Published squad contains a player missing from the current forecast")

    component_backtest = load_json_artifact(
        COMPONENT_BACKTEST_METRICS, "component backtest metrics"
    )
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    print("Current-squad audit: simulating selection worlds", flush=True)
    (
        player_ids,
        residual_points,
        residual_played,
        component_points,
        selection_diagnostics,
    ) = _simulate_families(by_player, selection_simulations, selection_seed, raw_weight)
    component_played = selection_diagnostics.pop("component_played")
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
            tuple(bench_candidates[start + index]["lineups"][str(EVENT)]["bench_order"])
            for index in _choice_leaders(bench_means)
        ]
        captain_pairs = list(permutations(starters, 2))
        captain_means = []
        for captain, vice in captain_pairs:
            residual_bonus = _captain_bonus(
                residual_points, residual_played, player_index, captain, vice
            )
            component_bonus = _captain_bonus(
                component_points, component_played, player_index, captain, vice
            )
            captain_means.append((float(residual_bonus.mean()), float(component_bonus.mean())))
        captain_choices = [captain_pairs[index] for index in _choice_leaders(np.asarray(captain_means))]
        for bench_order, (captain, vice) in product(bench_choices, captain_choices):
            candidate = _candidate(
                selected, starters, bench_order, captain, vice, meta
            )
            candidates_by_id[candidate["candidate_id"]] = candidate

    published = _candidate(
        selected,
        tuple(map(int, current_lineup["starters"])),
        tuple(map(int, current_lineup["bench_order"])),
        int(current_lineup["captain"]),
        int(current_lineup["vice_captain"]),
        meta,
    )
    candidates_by_id[published["candidate_id"]] = published
    candidates = list(candidates_by_id.values())
    residual_selection_scores = _score_candidates(
        candidates, player_ids, (EVENT,), residual_points, residual_played, meta
    )
    component_selection_scores = _score_candidates(
        candidates, player_ids, (EVENT,), component_points, component_played, meta
    )
    selection_rows = _rank_candidates(
        candidates, residual_selection_scores, component_selection_scores
    )
    selection_champion_id = selection_rows[0]["candidate_id"]
    finalist_ids = [row["candidate_id"] for row in selection_rows[:finalists]]
    if published["candidate_id"] not in finalist_ids:
        finalist_ids.append(published["candidate_id"])
    finalists_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    finalist_candidates = [finalists_by_id[candidate_id] for candidate_id in finalist_ids]

    del residual_bench_scores, component_bench_scores
    del residual_selection_scores, component_selection_scores
    print("Current-squad audit: simulating independent holdout worlds", flush=True)
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
        candidate["candidate_id"]: index for index, candidate in enumerate(finalist_candidates)
    }
    champion_index = finalist_index[selection_champion_id]
    published_index = finalist_index[published["candidate_id"]]
    residual_delta = _paired_delta(
        residual_holdout_scores[:, champion_index, 0],
        residual_holdout_scores[:, published_index, 0],
    )
    component_delta = _paired_delta(
        component_holdout_scores[:, champion_index, 0],
        component_holdout_scores[:, published_index, 0],
    )
    champion = finalists_by_id[selection_champion_id]
    champion_lineup = champion["lineups"][str(EVENT)]
    exact_match = selection_champion_id == published["candidate_id"]
    supported_change = (
        not exact_match
        and residual_delta["ci95_low"] > 0.0
        and component_delta["ci95_low"] > 0.0
    )
    if exact_match:
        verdict = "published_configuration_is_selection_champion"
    elif supported_change:
        verdict = "challenger_supported_in_both_independent_families"
    else:
        verdict = "published_configuration_retained_no_cross_family_holdout_challenge"

    names = {
        str(element): str(meta[element]["player_name"])
        for element in selected
    }
    result = {
        "version": VERSION,
        "event": EVENT,
        "verdict": verdict,
        "read_only": True,
        "lineage": lineage,
        "search": {
            "legal_xis": len(xis),
            "bench_orders_scored": len(bench_candidates),
            "joint_configurations_scored": len(candidates),
            "holdout_finalists": len(finalist_candidates),
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "component_raw_weight": raw_weight,
        },
        "published": {
            "source_candidate_id": str(current["candidate_id"]),
            "audit_candidate_id": published["candidate_id"],
            "formation": str(current_lineup["formation"]),
            "starters": _player_labels(list(map(int, current_lineup["starters"])), meta),
            "bench_order": _player_labels(
                list(map(int, current_lineup["bench_order"])), meta
            ),
            "captain": names[str(current_lineup["captain"])],
            "vice_captain": names[str(current_lineup["vice_captain"])],
        },
        "selection_champion": {
            "candidate_id": selection_champion_id,
            "formation": champion_lineup["formation"],
            "starters": _player_labels(list(champion_lineup["starters"]), meta),
            "bench_order": _player_labels(list(champion_lineup["bench_order"]), meta),
            "captain": names[str(champion_lineup["captain"])],
            "vice_captain": names[str(champion_lineup["vice_captain"])],
            "holdout_delta_to_published": {
                "residual": residual_delta,
                "component": component_delta,
            },
        },
        "selection_top": selection_rows[:20],
        "holdout_top": holdout_rows[:20],
        "player_names": names,
        "diagnostics": {
            "selection": selection_diagnostics,
            "holdout": holdout_diagnostics,
        },
        "decision_rule": (
            "Do not alter the published squad from this audit. Change its XI, bench priority, "
            "captain or vice only when the preselected challenger has a positive paired 95% "
            "holdout interval in both the residual and component simulation families."
        ),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    published = result["published"]
    champion = result["selection_champion"]
    residual = champion["holdout_delta_to_published"]["residual"]
    component = champion["holdout_delta_to_published"]["component"]
    return "\n".join(
        [
            "# Current squad XI, captain and bench audit",
            "",
            f"Verdict: **{result['verdict']}**.",
            "",
            (
                "This is a read-only, checksum-bound audit of the currently published 15. It does "
                "not replace the squad or use a stale optimizer incumbent."
            ),
            "",
            "## Published configuration",
            "",
            f"- Formation: {published['formation']}",
            f"- Captain / vice: {published['captain']} / {published['vice_captain']}",
            f"- XI: {', '.join(published['starters'])}",
            f"- Bench order: {', '.join(published['bench_order'])}",
            "",
            "## Selection champion",
            "",
            f"- Formation: {champion['formation']}",
            f"- Captain / vice: {champion['captain']} / {champion['vice_captain']}",
            f"- XI: {', '.join(champion['starters'])}",
            f"- Bench order: {', '.join(champion['bench_order'])}",
            "",
            "## Independent holdout difference versus published",
            "",
            "| Family | Mean | 95% CI | Beat probability |",
            "| --- | ---: | ---: | ---: |",
            (
                f"| Residual | {residual['mean']:+.3f} | "
                f"[{residual['ci95_low']:+.3f}, {residual['ci95_high']:+.3f}] | "
                f"{residual['beat_probability']:.1%} |"
            ),
            (
                f"| Component | {component['mean']:+.3f} | "
                f"[{component['ci95_low']:+.3f}, {component['ci95_high']:+.3f}] | "
                f"{component['beat_probability']:.1%} |"
            ),
            "",
            "## Coverage",
            "",
            f"- Legal XIs: {result['search']['legal_xis']}",
            f"- Bench orders scored: {result['search']['bench_orders_scored']}",
            f"- Joint configurations scored: {result['search']['joint_configurations_scored']}",
            f"- Holdout finalists: {result['search']['holdout_finalists']}",
            "",
            result["decision_rule"],
            "",
        ]
    )
