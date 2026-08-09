from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .artifact_lineage import ArtifactLineageError, load_json_artifact
from .component_models import CURRENT_COMPONENT_FORECAST
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
)
from .current_squad_audit import _paired_delta
from .current_squad_audit import _verify_lineage as _verify_current_lineage
from .neighbours import enumerate_legal_one_swaps
from .neighbours import squad_key as _squad_key
from .optimizer import DEFAULT_HORIZON_DECAY, _weights
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import SquadRules, load_rules, validate_squad
from .tournament import (
    _lineup_for_squad,
    _load_rows,
    _score_candidates,
    _simulate_player_outcomes,
    calibrate_residuals,
)

VERSION = "one_swap_audit_v1"
EVENTS = tuple(range(1, 9))
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "gw1-one-swap-adversarial-audit.md"


def _configuration_identity(
    selected: list[int], lineups: dict[str, dict[str, Any]]
) -> str:
    payload = {
        "selected": sorted(map(int, selected)),
        "lineups": {
            str(event): {
                "starters": sorted(map(int, lineup["starters"])),
                "bench_order": list(map(int, lineup["bench_order"])),
                "captain": int(lineup["captain"]),
                "vice_captain": int(lineup["vice_captain"]),
            }
            for event, lineup in sorted(lineups.items(), key=lambda item: int(item[0]))
        },
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"OSC-{hashlib.sha256(rendered.encode()).hexdigest()[:12]}"


def _configuration(
    squad: dict[str, Any],
    source: str,
    by_player: dict[int, dict[int, dict[str, Any]]],
    events: tuple[int, ...],
    rules: SquadRules,
) -> dict[str, Any]:
    selected = list(map(int, squad["selected"]))
    lineups = {
        str(event): _lineup_for_squad(selected, event, by_player, rules)
        for event in events
    }
    return {
        "candidate_id": _configuration_identity(selected, lineups),
        "squad_id": str(squad["squad_id"]),
        "configuration_source": source,
        "selected": selected,
        "lineups": lineups,
    }


def _metric_by_player(
    by_player: dict[int, dict[int, dict[str, Any]]],
    *,
    metric: str,
) -> dict[int, dict[int, dict[str, Any]]]:
    return {
        element: {
            event: {**row, "expected_points": float(row[metric])}
            for event, row in event_rows.items()
        }
        for element, event_rows in by_player.items()
    }


def _component_by_player(
    by_player: dict[int, dict[int, dict[str, Any]]],
    component_rows: list[dict[str, Any]],
    events: tuple[int, ...],
) -> dict[int, dict[int, dict[str, Any]]]:
    component = {
        (int(row["element"]), int(row["event_number"])): row
        for row in component_rows
        if int(row["event_number"]) in events
    }
    expected_keys = {
        (element, event) for element in by_player for event in events
    }
    if set(component) != expected_keys:
        missing = sorted(expected_keys - set(component))[:10]
        extra = sorted(set(component) - expected_keys)[:10]
        raise ArtifactLineageError(
            f"Component forecast grid differs from direct forecast: missing={missing}, extra={extra}"
        )
    return {
        element: {
            event: {
                **row,
                "expected_points": float(component[(element, event)]["expected_points"]),
                "p_play": float(component[(element, event)]["p_play"]),
            }
            for event, row in event_rows.items()
        }
        for element, event_rows in by_player.items()
    }


def _proxy_score(
    candidate: dict[str, Any],
    by_player: dict[int, dict[int, dict[str, Any]]],
    events: tuple[int, ...],
    decay: float,
) -> float:
    weights = _weights(list(events), decay)
    total = 0.0
    for event in events:
        lineup = candidate["lineups"][str(event)]
        value = sum(
            float(by_player[int(element)][event]["expected_points"])
            for element in lineup["starters"]
        )
        value += float(
            by_player[int(lineup["captain"])][event]["expected_points"]
        )
        total += weights[event] * value
    return total


def _build_squad_configurations(
    squads: list[dict[str, Any]],
    direct_by_player: dict[int, dict[int, dict[str, Any]]],
    robust_by_player: dict[int, dict[int, dict[str, Any]]],
    component_by_player: dict[int, dict[int, dict[str, Any]]],
    events: tuple[int, ...],
    rules: SquadRules,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    sources = {
        "direct_xp": direct_by_player,
        "robust_xp": robust_by_player,
        "component_xp": component_by_player,
    }
    configurations: dict[str, list[dict[str, Any]]] = {}
    proxy_rows: list[dict[str, Any]] = []
    for squad in squads:
        by_id: dict[str, dict[str, Any]] = {}
        origins: dict[str, list[str]] = defaultdict(list)
        for source, source_rows in sources.items():
            candidate = _configuration(squad, source, source_rows, events, rules)
            candidate_id = str(candidate["candidate_id"])
            by_id[candidate_id] = candidate
            origins[candidate_id].append(source)
        squad_configurations = list(by_id.values())
        for candidate in squad_configurations:
            candidate["configuration_sources"] = sorted(
                origins[str(candidate["candidate_id"])]
            )
        configurations[str(squad["squad_id"])] = squad_configurations
        family_best = {
            "direct": max(
                _proxy_score(candidate, direct_by_player, events, DEFAULT_HORIZON_DECAY)
                for candidate in squad_configurations
            ),
            "robust": max(
                _proxy_score(candidate, robust_by_player, events, DEFAULT_HORIZON_DECAY)
                for candidate in squad_configurations
            ),
            "component": max(
                _proxy_score(candidate, component_by_player, events, DEFAULT_HORIZON_DECAY)
                for candidate in squad_configurations
            ),
        }
        proxy_rows.append({**squad, **family_best})
    leaders = {
        family: max(float(row[family]) for row in proxy_rows)
        for family in ("direct", "robust", "component")
    }
    for row in proxy_rows:
        regrets = [leaders[family] - float(row[family]) for family in leaders]
        row["proxy_robust_regret"] = 0.8 * float(np.mean(regrets)) + 0.2 * max(
            regrets
        )
    proxy_rows.sort(key=lambda row: (row["proxy_robust_regret"], row["squad_id"]))
    for rank, row in enumerate(proxy_rows, start=1):
        row["proxy_rank"] = rank
    return configurations, proxy_rows


def _proxy_shortlist_ids(
    proxy_rows: list[dict[str, Any]],
    incumbent_id: str,
    maximum_squads: int,
) -> list[str]:
    if maximum_squads < 32:
        raise ValueError("One-swap proxy shortlist must contain at least 32 squads")
    chosen = [str(row["squad_id"]) for row in proxy_rows[:maximum_squads]]
    by_outgoing: dict[int, dict[str, Any]] = {}
    for row in proxy_rows:
        outgoing = row.get("outgoing")
        if outgoing is not None:
            by_outgoing.setdefault(int(outgoing), row)
    family_leaders = [
        max(proxy_rows, key=lambda row: float(row[family]))
        for family in ("direct", "robust", "component")
    ]
    for squad_id in [
        incumbent_id,
        *(str(row["squad_id"]) for row in by_outgoing.values()),
        *(str(row["squad_id"]) for row in family_leaders),
    ]:
        if squad_id not in chosen:
            chosen.append(squad_id)
    return chosen


def _simulate_families(
    by_player: dict[int, dict[int, dict[str, Any]]],
    events: tuple[int, ...],
    simulations: int,
    seed: int,
    raw_weight: float,
) -> tuple[
    list[int],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    dict[str, Any],
]:
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
    component_points = component_anchored + raw_weight * (
        component_raw - component_anchored
    )
    return (
        player_ids,
        residual_points,
        residual_played,
        component_points,
        component_played,
        {"goal_rates": goal_diagnostics, "component": component_diagnostics},
    )


def _weighted_totals(
    scores: np.ndarray, events: tuple[int, ...], decay: float
) -> np.ndarray:
    weights = _weights(list(events), decay)
    vector = np.asarray([weights[event] for event in events], dtype=np.float64)
    return np.tensordot(scores.astype(np.float64), vector, axes=([2], [0]))


def _rank_configurations(
    candidates: list[dict[str, Any]],
    residual_scores: np.ndarray,
    component_scores: np.ndarray,
    events: tuple[int, ...],
    decay: float,
) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    residual_total = _weighted_totals(residual_scores, events, decay)
    component_total = _weighted_totals(component_scores, events, decay)
    means = np.column_stack(
        (residual_total.mean(axis=0), component_total.mean(axis=0))
    )
    leaders = means.max(axis=0)
    regrets = leaders[None, :] - means
    robust = 0.8 * regrets.mean(axis=1) + 0.2 * regrets.max(axis=1)
    rows = [
        {
            "candidate_id": str(candidate["candidate_id"]),
            "squad_id": str(candidate["squad_id"]),
            "configuration_sources": candidate["configuration_sources"],
            "residual_mean": float(means[index, 0]),
            "component_mean": float(means[index, 1]),
            "residual_regret": float(regrets[index, 0]),
            "component_regret": float(regrets[index, 1]),
            "robust_regret": float(robust[index]),
        }
        for index, candidate in enumerate(candidates)
    ]
    rows.sort(key=lambda row: (row["robust_regret"], row["candidate_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows, residual_total, component_total


def _squad_champions(
    ranking: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    champions: dict[str, dict[str, Any]] = {}
    for row in ranking:
        champions.setdefault(str(row["squad_id"]), row)
    output = list(champions.values())
    output.sort(key=lambda row: (row["rank"], row["squad_id"]))
    for rank, row in enumerate(output, start=1):
        row["squad_rank"] = rank
    return output


def _configuration_summary(
    candidate: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    events: tuple[int, ...],
) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate["candidate_id"]),
        "configuration_sources": candidate["configuration_sources"],
        "lineups": {
            str(event): {
                "formation": candidate["lineups"][str(event)]["formation"],
                "starters": [
                    str(meta[int(element)]["player_name"])
                    for element in candidate["lineups"][str(event)]["starters"]
                ],
                "bench_order": [
                    str(meta[int(element)]["player_name"])
                    for element in candidate["lineups"][str(event)]["bench_order"]
                ],
                "captain": str(
                    meta[int(candidate["lineups"][str(event)]["captain"])][
                        "player_name"
                    ]
                ),
                "vice_captain": str(
                    meta[int(candidate["lineups"][str(event)]["vice_captain"])][
                        "player_name"
                    ]
                ),
            }
            for event in events
        },
    }


def _delta_by_event(
    challenger: np.ndarray,
    incumbent: np.ndarray,
    events: tuple[int, ...],
) -> dict[str, dict[str, float]]:
    return {
        str(event): _paired_delta(
            challenger[:, offset].astype(np.float64),
            incumbent[:, offset].astype(np.float64),
        )
        for offset, event in enumerate(events)
    }


def run_one_swap_audit(
    *,
    events: tuple[int, ...] = EVENTS,
    proxy_squads: int = 512,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    finalists: int = 64,
    selection_seed: int = 20260816,
    holdout_seed: int = 20260817,
    decay: float = DEFAULT_HORIZON_DECAY,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if not events or tuple(sorted(set(events))) != events:
        raise ValueError("One-swap events must be unique and ascending")
    if selection_simulations < 2_000 or holdout_simulations < 5_000:
        raise ValueError("One-swap simulation counts are below the safety minimum")
    if selection_seed == holdout_seed:
        raise ValueError("Selection and holdout require independent seeds")
    if finalists < 8:
        raise ValueError("One-swap holdout requires at least eight finalists")
    ensure_engine_layout()
    decision, lineage = _verify_current_lineage()
    current = decision["decision"]["candidate"]
    incumbent_source_id = str(current["candidate_id"])
    selected = list(map(int, current["selected"]))
    _, loaded = _load_rows(events)
    direct_by_player = loaded["by_player"]
    meta = loaded["meta"]
    rules = load_rules()
    validate_squad([meta[element] for element in selected], rules)
    component_rows = pq.read_table(CURRENT_COMPONENT_FORECAST).to_pylist()
    component_by_player = _component_by_player(
        direct_by_player, component_rows, events
    )
    robust_by_player = _metric_by_player(
        direct_by_player, metric="robust_points"
    )
    swaps = enumerate_legal_one_swaps(selected, meta, rules)
    incumbent_id = f"INC-{incumbent_source_id}"
    incumbent_squad = {
        "squad_id": incumbent_id,
        "selected": list(_squad_key(selected)),
        "outgoing": None,
        "incoming": None,
        "position": None,
        "budget_spent": sum(
            float(meta[element]["market_price"]) for element in selected
        )
        / 10.0,
        "bank": (
            rules.budget
            - sum(float(meta[element]["market_price"]) for element in selected)
        )
        / 10.0,
    }
    squads = [incumbent_squad, *swaps]
    print(
        f"One-swap audit: building proxy configurations for {len(squads):,} squads",
        flush=True,
    )
    configurations, proxy_rows = _build_squad_configurations(
        squads,
        direct_by_player,
        robust_by_player,
        component_by_player,
        events,
        rules,
    )
    proxy_ids = _proxy_shortlist_ids(proxy_rows, incumbent_id, proxy_squads)
    proxy_id_set = set(proxy_ids)
    selection_candidates = [
        candidate
        for squad_id in proxy_ids
        for candidate in configurations[squad_id]
    ]
    candidate_by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in selection_candidates
    }
    if len(candidate_by_id) != len(selection_candidates):
        raise ArtifactLineageError("One-swap configurations are not uniquely identified")
    raw_weight = float(
        load_json_artifact(
            COMPONENT_BACKTEST_METRICS, "component backtest metrics"
        )["blend_selection"]["selected_raw_weight"]
    )
    print("One-swap audit: simulating selection worlds", flush=True)
    (
        player_ids,
        residual_selection_points,
        residual_selection_played,
        component_selection_points,
        component_selection_played,
        selection_diagnostics,
    ) = _simulate_families(
        direct_by_player,
        events,
        selection_simulations,
        selection_seed,
        raw_weight,
    )
    residual_selection_scores = _score_candidates(
        selection_candidates,
        player_ids,
        events,
        residual_selection_points,
        residual_selection_played,
        meta,
    )
    component_selection_scores = _score_candidates(
        selection_candidates,
        player_ids,
        events,
        component_selection_points,
        component_selection_played,
        meta,
    )
    selection_ranking, _, _ = _rank_configurations(
        selection_candidates,
        residual_selection_scores,
        component_selection_scores,
        events,
        decay,
    )
    selection_squads = _squad_champions(selection_ranking)
    selection_champion = selection_squads[0]
    finalist_rows = selection_squads[:finalists]
    if incumbent_id not in {str(row["squad_id"]) for row in finalist_rows}:
        incumbent_row = next(
            row for row in selection_squads if str(row["squad_id"]) == incumbent_id
        )
        finalist_rows.append(incumbent_row)
    finalist_candidates = [
        candidate_by_id[str(row["candidate_id"])] for row in finalist_rows
    ]
    print("One-swap audit: simulating independent holdout worlds", flush=True)
    (
        holdout_player_ids,
        residual_holdout_points,
        residual_holdout_played,
        component_holdout_points,
        component_holdout_played,
        holdout_diagnostics,
    ) = _simulate_families(
        direct_by_player,
        events,
        holdout_simulations,
        holdout_seed,
        raw_weight,
    )
    if holdout_player_ids != player_ids:
        raise RuntimeError("Selection and holdout simulation player order differs")
    residual_holdout_scores = _score_candidates(
        finalist_candidates,
        player_ids,
        events,
        residual_holdout_points,
        residual_holdout_played,
        meta,
    )
    component_holdout_scores = _score_candidates(
        finalist_candidates,
        player_ids,
        events,
        component_holdout_points,
        component_holdout_played,
        meta,
    )
    holdout_ranking, residual_total, component_total = _rank_configurations(
        finalist_candidates,
        residual_holdout_scores,
        component_holdout_scores,
        events,
        decay,
    )
    finalist_index = {
        str(candidate["candidate_id"]): index
        for index, candidate in enumerate(finalist_candidates)
    }
    incumbent_finalist = next(
        candidate
        for candidate in finalist_candidates
        if str(candidate["squad_id"]) == incumbent_id
    )
    champion_candidate = candidate_by_id[str(selection_champion["candidate_id"])]
    champion_index = finalist_index[str(champion_candidate["candidate_id"])]
    incumbent_index = finalist_index[str(incumbent_finalist["candidate_id"])]
    residual_delta = _paired_delta(
        residual_total[:, champion_index], residual_total[:, incumbent_index]
    )
    component_delta = _paired_delta(
        component_total[:, champion_index], component_total[:, incumbent_index]
    )
    champion_squad = next(
        row for row in squads if row["squad_id"] == selection_champion["squad_id"]
    )
    supported = (
        str(selection_champion["squad_id"]) != incumbent_id
        and residual_delta["ci95_low"] > 0.0
        and component_delta["ci95_low"] > 0.0
    )
    finalist_evidence = []
    squad_by_id = {str(row["squad_id"]): row for row in squads}
    holdout_by_candidate = {
        str(row["candidate_id"]): row for row in holdout_ranking
    }
    for row, candidate in zip(finalist_rows, finalist_candidates, strict=True):
        index = finalist_index[str(candidate["candidate_id"])]
        squad = squad_by_id[str(candidate["squad_id"])]
        finalist_evidence.append(
            {
                "selection_squad_rank": int(row["squad_rank"]),
                "holdout_configuration_rank": int(
                    holdout_by_candidate[str(candidate["candidate_id"])]["rank"]
                ),
                "squad_id": str(candidate["squad_id"]),
                "candidate_id": str(candidate["candidate_id"]),
                "outgoing": (
                    str(meta[int(squad["outgoing"])]["player_name"])
                    if squad["outgoing"] is not None
                    else None
                ),
                "incoming": (
                    str(meta[int(squad["incoming"])]["player_name"])
                    if squad["incoming"] is not None
                    else None
                ),
                "position": squad["position"],
                "budget_spent": float(squad["budget_spent"]),
                "bank": float(squad["bank"]),
                "holdout_delta_to_incumbent": {
                    "residual": _paired_delta(
                        residual_total[:, index], residual_total[:, incumbent_index]
                    ),
                    "component": _paired_delta(
                        component_total[:, index], component_total[:, incumbent_index]
                    ),
                },
            }
        )
    finalist_evidence.sort(
        key=lambda row: (row["selection_squad_rank"], row["squad_id"])
    )
    pressure_by_outgoing = []
    for outgoing in selected:
        relevant = [
            row
            for row in proxy_rows
            if row.get("outgoing") is not None and int(row["outgoing"]) == outgoing
        ]
        leader = min(
            relevant,
            key=lambda row: (row["proxy_robust_regret"], row["squad_id"]),
        )
        pressure_by_outgoing.append(
            {
                "outgoing": str(meta[outgoing]["player_name"]),
                "incoming": str(meta[int(leader["incoming"])]["player_name"]),
                "position": str(meta[outgoing]["position"]),
                "proxy_rank": int(leader["proxy_rank"]),
                "proxy_robust_regret": float(leader["proxy_robust_regret"]),
            }
        )
    pressure_by_outgoing.sort(
        key=lambda row: (row["proxy_rank"], row["outgoing"])
    )

    if str(selection_champion["squad_id"]) == incumbent_id:
        verdict = "incumbent_is_selection_champion"
    elif supported:
        verdict = "supported_one_swap_requires_full_pipeline_replay"
    else:
        verdict = "no_cross_family_holdout_one_swap_challenge"
    result = {
        "version": VERSION,
        "events": list(events),
        "read_only": True,
        "production_changed": False,
        "promotion_ready": False,
        "verdict": verdict,
        "lineage": {
            **lineage,
            "component_forecast_sha256": sha256_file(CURRENT_COMPONENT_FORECAST),
        },
        "incumbent": {
            "source_candidate_id": incumbent_source_id,
            "squad_id": incumbent_id,
            "selected": [str(meta[element]["player_name"]) for element in selected],
            "budget_spent": float(incumbent_squad["budget_spent"]),
            "bank": float(incumbent_squad["bank"]),
            "configuration": _configuration_summary(
                incumbent_finalist, meta, events
            ),
        },
        "selection_champion": {
            "squad_id": str(selection_champion["squad_id"]),
            "outgoing": (
                str(meta[int(champion_squad["outgoing"])]["player_name"])
                if champion_squad["outgoing"] is not None
                else None
            ),
            "incoming": (
                str(meta[int(champion_squad["incoming"])]["player_name"])
                if champion_squad["incoming"] is not None
                else None
            ),
            "position": champion_squad["position"],
            "budget_spent": float(champion_squad["budget_spent"]),
            "bank": float(champion_squad["bank"]),
            "configuration": _configuration_summary(
                champion_candidate, meta, events
            ),
            "holdout_delta_to_incumbent": {
                "residual": residual_delta,
                "component": component_delta,
            },
            "holdout_delta_by_event": {
                "residual": _delta_by_event(
                    residual_holdout_scores[:, champion_index, :],
                    residual_holdout_scores[:, incumbent_index, :],
                    events,
                ),
                "component": _delta_by_event(
                    component_holdout_scores[:, champion_index, :],
                    component_holdout_scores[:, incumbent_index, :],
                    events,
                ),
            },
            "cross_family_holdout_support": supported,
        },
        "search": {
            "legal_one_swaps": len(swaps),
            "full_proxy_squads": len(squads),
            "proxy_shortlist_squads": len(proxy_id_set),
            "selection_configurations": len(selection_candidates),
            "holdout_finalists": len(finalist_candidates),
            "configuration_sources": ["direct_xp", "robust_xp", "component_xp"],
            "proxy_squads_requested": proxy_squads,
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "horizon_decay": decay,
            "component_raw_weight": raw_weight,
        },
        "proxy_top": [
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "selected",
                        "outgoing",
                        "incoming",
                    }
                },
                "outgoing": (
                    str(meta[int(row["outgoing"])]["player_name"])
                    if row["outgoing"] is not None
                    else None
                ),
                "incoming": (
                    str(meta[int(row["incoming"])]["player_name"])
                    if row["incoming"] is not None
                    else None
                ),
            }
            for row in proxy_rows[:50]
        ],
        "selection_squad_top": selection_squads[:50],
        "holdout_finalists": finalist_evidence,
        "pressure_by_outgoing": pressure_by_outgoing,
        "diagnostics": {
            "selection": selection_diagnostics,
            "holdout": holdout_diagnostics,
        },
        "decision_rule": (
            "This read-only audit cannot promote a swap. A non-incumbent must be preselected on "
            "the selection worlds and clear a paired 95% interval above zero in both independent "
            "holdout families. Even then, rerun the complete robust-search, horizon and synthesis "
            "pipeline with refreshed deadline evidence before changing production."
        ),
        "method_limit": (
            "Every legal one-player replacement is proxy-scored. The proxy shortlist receives "
            "direct-, robust- and component-optimized event lineups with exact simulated autosubs "
            "and captain fallback. This is an adversarial membership audit, not a replacement for "
            "the complete global squad-search funnel."
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
    champion = result["selection_champion"]
    delta = champion["holdout_delta_to_incumbent"]
    change = (
        "incumbent retained"
        if champion["outgoing"] is None
        else f"{champion['outgoing']} → {champion['incoming']}"
    )
    lines = [
        "# GW1 one-swap adversarial audit",
        "",
        f"**Verdict:** `{result['verdict']}`  ",
        "**Production changed:** no",
        "",
        result["method_limit"],
        "",
        "## Preselected champion",
        "",
        f"- Change: {change}",
        f"- Residual holdout: {_format_interval(delta['residual'])}",
        f"- Component holdout: {_format_interval(delta['component'])}",
        (
            "- Cross-family support: "
            f"{champion['cross_family_holdout_support']}"
        ),
        "",
        "## Search coverage",
        "",
        f"- Legal one-player replacements enumerated: {result['search']['legal_one_swaps']:,}",
        f"- Proxy shortlist squads: {result['search']['proxy_shortlist_squads']:,}",
        f"- Selection configurations: {result['search']['selection_configurations']:,}",
        f"- Independent holdout finalists: {result['search']['holdout_finalists']:,}",
        "",
        "## Selection finalists",
        "",
        "| Selection rank | Swap | Position | Bank | Residual delta | Component delta |",
        "| ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for row in result["holdout_finalists"][:20]:
        swap = (
            "incumbent"
            if row["outgoing"] is None
            else f"{row['outgoing']} → {row['incoming']}"
        )
        evidence = row["holdout_delta_to_incumbent"]
        lines.append(
            f"| {row['selection_squad_rank']} | {swap} | {row['position'] or '—'} | "
            f"£{row['bank']:.1f}m | {_format_interval(evidence['residual'])} | "
            f"{_format_interval(evidence['component'])} |"
        )
    lines.extend(
        [
            "",
            "## Replacement pressure by selected player",
            "",
            "This is the best deterministic proxy replacement for each incumbent player, not a recommendation.",
            "",
            "| Selected player | Best proxy replacement | Position | Global proxy rank |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for row in result["pressure_by_outgoing"]:
        lines.append(
            f"| {row['outgoing']} | {row['incoming']} | {row['position']} | "
            f"{row['proxy_rank']} |"
        )
    lines.extend(
        [
            "",
            "## Decision rule",
            "",
            result["decision_rule"],
            "",
        ]
    )
    return "\n".join(lines)
