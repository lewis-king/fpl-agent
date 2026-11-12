from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import sparse

from fplagent_data.http import sha256_file
from fplagent_data.participation_consensus import CONSENSUS as PARTICIPATION_CONSENSUS

from .acceleration import (
    cuda_device,
    policy_worker_count,
    release_cuda_memory,
    sparse_dense_matmul,
)
from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_hash,
)
from .capital_efficiency import candidate_publication_role_risks
from .component_candidates import (
    COMPONENT_CANDIDATES_JSON,
    _component_means,
)
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    _blend_scenario_scores,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
    train_goal_model,
)
from .global_search import (
    generate_global_squads,
    minimum_distance,
)
from .models import CURRENT_FORECAST, require_cuda
from .optimizer import _solve
from .paths import DECISIONS, MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules, validate_lineup, validate_squad
from .tournament import (
    CANDIDATES_JSON,
    DEFAULT_EVENTS,
    _lineup_for_squad,
    _load_rows,
    _score_candidates,
    _simulate_player_outcomes,
    calibrate_residuals,
)

VERSION = "robust_search_v2_global"
RESULT_DIR = MODEL_DATA / VERSION
GLOBAL_PARQUET = RESULT_DIR / "global-squads.parquet"
DISCOVERY_PARQUET = RESULT_DIR / "discovery-squads.parquet"
SCREENING_PARQUET = RESULT_DIR / "screening-metrics.parquet"
SELECTION_PARQUET = RESULT_DIR / "component-selection-metrics.parquet"
SHORTLIST_JSON = RESULT_DIR / "shortlist.json"
RESULTS_JSON = RESULT_DIR / "results.json"
DECISION_JSON = DECISIONS / "2026-27-gw1-global-robust-search.json"
REPORT = REPORTS / "gw1-global-robust-search.md"
ADAPTIVE_RESULTS = MODEL_DATA / "adaptive_preseason_v1" / "results.json"
ADAPTIVE_ORIGIN = "adaptive-lead-shadow"

SCENARIO_WEIGHTS = {
    "base_evidence_open": 0.30,
    "base_evidence_roll_gw2": 0.20,
    "base_evidence_fixed": 0.10,
    "base_raw_open": 0.10,
    "base_anchored_open": 0.15,
    "high_goal_open": 0.075,
    "high_goal_roll_gw2": 0.05,
    "high_goal_fixed": 0.025,
}
CENTRAL_REGRET_CAP = 1.0
BENCHMARK_ORIGINS = {
    "C007",
    "C005",
    "C009",
    "S028",
    "S001",
    ADAPTIVE_ORIGIN,
}
GLOBAL_ORIGINS = {"global-milp", "global-evolution"}
PROTECTED_ORIGIN_PREFIXES = (
    "archetype-",
    "omission-player-",
    "captain-counterfactual-",
    "club-stack-",
    "role-safe-",
)
PROTECTED_CLUB_STACKS = 10
CLUB_STACK_COUNTS = (2, 3)
ROLE_SAFE_FINALIST_MINIMUM = 8


def protected_candidate(
    candidate: dict[str, Any], mandatory_origins: set[str] | None = None
) -> bool:
    origins = set(map(str, candidate.get("origin_ids") or []))
    return bool((mandatory_origins or set()) & origins) or any(
        origin.startswith(PROTECTED_ORIGIN_PREFIXES) for origin in origins
    )


def _candidate_id(squad: Iterable[int]) -> str:
    encoded = ",".join(map(str, sorted(map(int, squad)))).encode()
    return f"R-{hashlib.sha1(encoded).hexdigest()[:10]}"


def _squad_key(squad: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(map(int, squad)))


def _formation(lineup: dict[str, Any]) -> str:
    return str(lineup["formation"])


def _bench_band(value: float) -> str:
    if value <= 18.5:
        return "lean"
    if value <= 20.0:
        return "historical"
    if value <= 22.0:
        return "medium"
    return "deep"


def _load_seed_squads(
    current_forecast_sha256: str | None = None,
) -> tuple[dict[tuple[int, ...], set[str]], list[tuple[int, ...]]]:
    origins: dict[tuple[int, ...], set[str]] = defaultdict(set)
    order: list[tuple[int, ...]] = []
    for path in (CANDIDATES_JSON, COMPONENT_CANDIDATES_JSON):
        payload = load_json_artifact(path, f"seed candidate artifact {path.name}")
        if current_forecast_sha256 is not None:
            require_recorded_hash(
                payload,
                ("forecast_sha256",),
                current_forecast_sha256,
                f"seed candidate artifact {path.name}",
            )
        for candidate in payload["candidates"]:
            key = _squad_key(candidate["selected"])
            if key not in origins:
                order.append(key)
            origins[key].add(str(candidate["candidate_id"]))
    if current_forecast_sha256 is not None and ADAPTIVE_RESULTS.is_file():
        adaptive = load_json_artifact(ADAPTIVE_RESULTS, "adaptive preseason challenger")
        gate = adaptive.get("tournament", {}).get("full_pipeline_request_gate", {})
        same_forecast = (
            adaptive.get("lineage", {}).get("current_forecast_sha256") == current_forecast_sha256
        )
        if (
            adaptive.get("verdict") == "REQUEST_FULL_PIPELINE"
            and gate.get("passed") is True
            and same_forecast
        ):
            challenger = adaptive["tournament"]["leader"]["candidate"]
            key = _squad_key(challenger["selected"])
            if key not in origins:
                order.append(key)
            origins[key].update(
                {ADAPTIVE_ORIGIN, str(adaptive["tournament"]["leader"]["candidate_id"])}
            )
    if not order:
        raise FileNotFoundError(
            "No seed candidates exist. Run the residual and component candidate generators first."
        )
    return origins, order


def _eligible_meta(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(row["element"]): row
        for row in rows
        if int(row["event_number"]) == DEFAULT_EVENTS[0]
        and bool(row.get("can_select", True))
        and not bool(row.get("removed", False))
    }


def _legal_swap_neighbours(
    squad: tuple[int, ...],
    meta: dict[int, dict[str, Any]],
    eligible_by_position: dict[str, list[int]],
    *,
    budget: float,
    club_limit: int,
) -> Iterable[tuple[int, ...]]:
    selected = set(squad)
    cost = sum(float(meta[element]["market_price"]) for element in squad)
    clubs = Counter(int(meta[element]["team_id"]) for element in squad)
    for outgoing in squad:
        row = meta[outgoing]
        old_club = int(row["team_id"])
        old_price = float(row["market_price"])
        for incoming in eligible_by_position[str(row["position"])]:
            if incoming in selected:
                continue
            incoming_row = meta[incoming]
            new_club = int(incoming_row["team_id"])
            if clubs[new_club] - int(new_club == old_club) >= club_limit:
                continue
            if cost - old_price + float(incoming_row["market_price"]) > budget + 1e-8:
                continue
            yield _squad_key((*selected.difference({outgoing}), incoming))


def _proxy_utilities(
    rows: list[dict[str, Any]], player_ids: list[int]
) -> tuple[np.ndarray, list[dict[str, float]]]:
    by_key = {(int(row["element"]), int(row["event_number"])): row for row in rows}
    raw = _component_means()
    definitions = []
    raw_weights = (0.0, 0.05, 0.10, 0.15, 0.25, 0.50, 0.75, 1.0)
    decays = (0.76, 0.82, 0.88, 0.94, 1.0)
    risk_weights = (0.0, 0.35)
    # A balanced deterministic grid is preferable here: this stage only prevents
    # obviously dominated squads from consuming simulation budget.
    for raw_weight in raw_weights:
        for decay in decays:
            risk_weight = risk_weights[(len(definitions) // len(decays)) % 2]
            definitions.append(
                {"raw_weight": raw_weight, "decay": decay, "risk_weight": risk_weight}
            )
    utilities = np.zeros((len(player_ids), len(definitions)), dtype=np.float32)
    for player_offset, element in enumerate(player_ids):
        for scenario_offset, definition in enumerate(definitions):
            total = 0.0
            for event in DEFAULT_EVENTS:
                row = by_key[(element, event)]
                xp = float(row["expected_points"])
                component = float(raw[(element, event)])
                blended = (
                    definition["raw_weight"] * component + (1.0 - definition["raw_weight"]) * xp
                )
                risk_adjusted = (1.0 - definition["risk_weight"]) * blended + definition[
                    "risk_weight"
                ] * float(row["robust_points"])
                total += definition["decay"] ** (event - DEFAULT_EVENTS[0]) * risk_adjusted
            utilities[player_offset, scenario_offset] = total
    return utilities, definitions


def _prefilter_squads(
    squads: Iterable[tuple[int, ...]],
    player_index: dict[int, int],
    utilities: np.ndarray,
    limit: int,
    mandatory: set[tuple[int, ...]],
) -> tuple[list[tuple[int, ...]], dict[tuple[int, ...], float]]:
    keys = list(dict.fromkeys(squads))
    if len(keys) <= limit:
        return keys, {key: 0.0 for key in keys}
    row_indices = np.repeat(np.arange(len(keys), dtype=np.int32), 15)
    column_indices = np.fromiter(
        (player_index[element] for key in keys for element in key),
        dtype=np.int32,
        count=len(keys) * 15,
    )
    membership = sparse.csr_matrix(
        (np.ones(len(column_indices), dtype=np.int8), (row_indices, column_indices)),
        shape=(len(keys), len(player_index)),
    )
    scores, _ = sparse_dense_matmul(
        membership,
        utilities,
        label="squad utility screen",
    )
    scores = np.asarray(scores, dtype=np.float32)
    scale = np.maximum(scores.std(axis=0), 1e-6)
    standardized = (scores - scores.max(axis=0)) / scale
    aggregate = standardized.mean(axis=1)
    chosen: set[int] = {index for index, key in enumerate(keys) if key in mandatory}
    per_scenario = max(24, math.ceil((limit - len(chosen)) / (2 * scores.shape[1])))
    for scenario in range(scores.shape[1]):
        count = min(per_scenario, len(keys))
        chosen.update(np.argpartition(scores[:, scenario], -count)[-count:].tolist())
    if len(chosen) < limit:
        for index in np.argsort(-aggregate, kind="stable"):
            chosen.add(int(index))
            if len(chosen) >= limit:
                break
    elif len(chosen) > limit:
        mandatory_indices = {index for index in chosen if keys[index] in mandatory}
        remaining = sorted(
            chosen - mandatory_indices, key=lambda index: aggregate[index], reverse=True
        )
        chosen = mandatory_indices | set(remaining[: max(0, limit - len(mandatory_indices))])
    ordered = sorted(chosen, key=lambda index: aggregate[index], reverse=True)
    proxy = {keys[index]: float(aggregate[index]) for index in ordered}
    return [keys[index] for index in ordered], proxy


def _record_candidate(
    squad: tuple[int, ...],
    by_player: dict[int, dict[int, dict[str, Any]]],
    meta: dict[int, dict[str, Any]],
    origins: set[str],
    proxy_score: float,
    forced_captain: int | None = None,
) -> dict[str, Any]:
    rules = load_rules()
    selected = list(squad)
    lineups = {
        str(event): _lineup_for_squad(selected, event, by_player, rules) for event in DEFAULT_EVENTS
    }
    gw1 = lineups[str(DEFAULT_EVENTS[0])]
    if forced_captain is not None:
        forced_captain = int(forced_captain)
        if forced_captain not in set(map(int, gw1["starters"])):
            raise ValueError("forced captain must be in the GW1 starting XI")
        old_captain = int(gw1["captain"])
        gw1["captain"] = forced_captain
        if int(gw1["vice_captain"]) == forced_captain:
            gw1["vice_captain"] = old_captain
        gw1["expected_points"] = sum(
            float(by_player[int(element)][1]["expected_points"]) for element in gw1["starters"]
        ) + float(by_player[forced_captain][1]["expected_points"])
    bench = [int(element) for element in gw1["bench_order"]]
    budget_spent = sum(float(meta[element]["market_price"]) for element in selected) / 10.0
    bench_spend = sum(float(meta[element]["market_price"]) for element in bench) / 10.0
    captain = meta[int(gw1["captain"])]["player_name"]
    formation = _formation(gw1)
    return {
        "candidate_id": (
            f"{_candidate_id(squad)}:captain-{forced_captain}"
            if forced_captain is not None
            else _candidate_id(squad)
        ),
        "display_name": f"{formation} · {captain} captain · £{bench_spend:.1f}m bench",
        "archetype": "robust-neighbourhood",
        "origin_ids": sorted(origins) if origins else ["swap-neighbourhood"],
        "selected": selected,
        "lineups": lineups,
        "budget_spent": budget_spent,
        "bank": (rules.budget / 10.0) - budget_spent,
        "gw1_bench_spend": bench_spend,
        "gw1_outfield_bench_spend": sum(
            float(meta[element]["market_price"])
            for element in bench
            if meta[element]["position"] != "GK"
        )
        / 10.0,
        "gw1_formation": formation,
        "proxy_score": proxy_score,
        "forced_gw1_captain": forced_captain,
    }


_EXACT_COUNTERFACTUAL_ROWS: list[dict[str, Any]] | None = None


def _initialize_exact_counterfactual_worker(rows: list[dict[str, Any]]) -> None:
    global _EXACT_COUNTERFACTUAL_ROWS
    _EXACT_COUNTERFACTUAL_ROWS = rows


def _solve_exact_counterfactual_worker(
    task: dict[str, Any],
) -> tuple[str, tuple[int, ...]]:
    if _EXACT_COUNTERFACTUAL_ROWS is None:
        raise RuntimeError("exact counterfactual worker was not initialized")
    solution = _solve(
        _EXACT_COUNTERFACTUAL_ROWS,
        list(DEFAULT_EVENTS),
        required_players=set(map(int, task.get("required_players") or [])),
        excluded_players=set(map(int, task.get("excluded_players") or [])),
        initial_club_counts={
            int(team_id): int(count)
            for team_id, count in (task.get("initial_club_counts") or {}).items()
        },
        highs_threads=1,
    )
    return str(task["key"]), _squad_key(solution["selected"])


def _solve_exact_counterfactuals(
    rows: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    progress_label: str,
) -> dict[str, tuple[int, ...]]:
    """Solve protected initial structures with lineup/captain/transfer economics."""

    if not tasks:
        return {}
    workers = min(policy_worker_count(), len(tasks))
    if workers <= 1:
        _initialize_exact_counterfactual_worker(rows)
        return dict(_solve_exact_counterfactual_worker(task) for task in tasks)
    print(
        f"Acceleration: {progress_label} using {workers} CPU workers for "
        f"{len(tasks)} exact policy MILPs",
        flush=True,
    )
    solved: dict[str, tuple[int, ...]] = {}
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=_initialize_exact_counterfactual_worker,
        initargs=(rows,),
    ) as executor:
        futures = {
            executor.submit(_solve_exact_counterfactual_worker, task): task for task in tasks
        }
        interval = max(1, len(tasks) // 6)
        for completed, future in enumerate(as_completed(futures), start=1):
            key, squad = future.result()
            solved[key] = squad
            if completed % interval == 0 or completed == len(tasks):
                print(
                    f"{progress_label}: solved {completed}/{len(tasks)} structures",
                    flush=True,
                )
    return solved


def _generate_archetype_squads(
    *,
    rows: list[dict[str, Any]],
    player_ids: list[int],
    eligible_meta: dict[int, dict[str, Any]],
    by_player: dict[int, dict[int, dict[str, Any]]],
) -> tuple[dict[tuple[int, ...], set[str]], set[tuple[int, ...]], list[int], int]:
    """Build exact premium, captain and no-leader structures before pruning."""

    # Omission protection deliberately reaches below the normal high-confidence
    # starter band. A material, currently available player must be deeply tested
    # even when the very signal under audit has pushed his p(play) below 0.35.
    all_by_price = sorted(
        player_ids,
        key=lambda element: float(eligible_meta[element]["market_price"]),
        reverse=True,
    )
    all_by_ownership = sorted(
        player_ids,
        key=lambda element: float(by_player[element][1].get("ownership_percentile") or 0.0),
        reverse=True,
    )
    material_counterfactuals = {
        element
        for element in {*all_by_price[:15], *all_by_ownership[:15]}
        if str(by_player[element][1].get("status") or "a") == "a"
    }
    eligible = [
        element
        for element in player_ids
        if float(by_player[element][1]["p_play"]) >= 0.35 or element in material_counterfactuals
    ]
    by_points = sorted(
        eligible,
        key=lambda element: float(by_player[element][1]["expected_points"]),
        reverse=True,
    )
    by_price = sorted(
        eligible,
        key=lambda element: float(eligible_meta[element]["market_price"]),
        reverse=True,
    )
    by_ownership = sorted(
        eligible,
        key=lambda element: float(by_player[element][1].get("ownership_percentile") or 0.0),
        reverse=True,
    )
    disagreement_risks = [
        element
        for element in eligible
        if str(by_player[element][1].get("live_participation_consensus")) == "source_disagreement"
        and float(eligible_meta[element]["market_price"]) >= 70.0
    ]
    captain_players = {
        *by_points[:10],
        *[
            element
            for element in by_price
            if str(eligible_meta[element]["position"]) in {"MID", "FWD"}
        ][:8],
    }
    archetype_players = list(
        dict.fromkeys(
            [
                *by_points[:15],
                *by_price[:15],
                *by_ownership[:15],
                *disagreement_risks,
            ]
        )
    )
    leader = by_points[0]
    origins: dict[tuple[int, ...], set[str]] = defaultdict(set)
    mandatory: set[tuple[int, ...]] = set()
    tasks = [
        {"key": f"player-{element}", "required_players": [element]} for element in archetype_players
    ]
    tasks.append({"key": f"no-leader-{leader}", "excluded_players": [leader]})
    solved = _solve_exact_counterfactuals(
        rows,
        tasks,
        progress_label="Exact premium counterfactuals",
    )
    for element in archetype_players:
        squad = solved[f"player-{element}"]
        prefix = "archetype-player" if element in captain_players else "omission-player"
        origins[squad].add(f"{prefix}-{element}")
        mandatory.add(squad)
    no_leader = solved[f"no-leader-{leader}"]
    origins[no_leader].add(f"archetype-no-leader-{leader}")
    mandatory.add(no_leader)
    return origins, mandatory, archetype_players, leader


def _strong_club_outlook(
    by_player: dict[int, dict[int, dict[str, Any]]],
    meta: dict[int, dict[str, Any]],
    *,
    limit: int = PROTECTED_CLUB_STACKS,
) -> list[dict[str, Any]]:
    """Rank clubs from fixture-level attack and clean-sheet opportunity.

    This is deliberately independent of which individual players currently look
    selectable. It prevents uncertain roles at a strong club from eliminating
    the very multi-player counterfactual that the deep tournament should test.
    """

    if limit < 1:
        raise ValueError("protected club-stack limit must be positive")
    team_events: dict[tuple[int, int], dict[str, Any]] = {}
    for player_events in by_player.values():
        for event in DEFAULT_EVENTS:
            row = player_events[event]
            team_events.setdefault((int(row["team_id"]), event), row)
    scores: dict[int, float] = defaultdict(float)
    for (team_id, event), row in team_events.items():
        weight = 0.88 ** (event - DEFAULT_EVENTS[0])
        attack = float(row.get("team_expected_goals") or 0.0)
        clean_sheet = float(row.get("team_clean_sheet_probability") or 0.0)
        scores[team_id] += weight * (attack + 2.0 * clean_sheet)
    ranked = sorted(scores, key=lambda team_id: (-scores[team_id], team_id))[:limit]
    return [
        {
            "team_id": team_id,
            "team_name": str(
                next(
                    row.get("team_name") or row.get("team_short_name") or team_id
                    for row in meta.values()
                    if int(row["team_id"]) == team_id
                )
            ),
            "outlook_score": scores[team_id],
        }
        for team_id in ranked
    ]


def _generate_club_stack_squads(
    *,
    rows: list[dict[str, Any]],
    eligible_meta: dict[int, dict[str, Any]],
    by_player: dict[int, dict[int, dict[str, Any]]],
    club_limit_count: int = PROTECTED_CLUB_STACKS,
) -> tuple[
    dict[tuple[int, ...], set[str]],
    set[tuple[int, ...]],
    list[dict[str, Any]],
]:
    """Generate exact two/three-player stacks and protect them through holdout."""

    clubs = _strong_club_outlook(by_player, eligible_meta, limit=club_limit_count)
    origins: dict[tuple[int, ...], set[str]] = defaultdict(set)
    mandatory: set[tuple[int, ...]] = set()
    audit: list[dict[str, Any]] = []
    tasks = [
        {
            "key": f"club-{int(club['team_id'])}-{count}",
            "initial_club_counts": {int(club["team_id"]): count},
        }
        for club in clubs
        for count in CLUB_STACK_COUNTS
    ]
    solved = _solve_exact_counterfactuals(
        rows,
        tasks,
        progress_label="Exact club-stack counterfactuals",
    )
    for club in clubs:
        team_id = int(club["team_id"])
        for count in CLUB_STACK_COUNTS:
            origin = f"club-stack-{team_id}-{count}"
            squad = solved[f"club-{team_id}-{count}"]
            origins[squad].add(origin)
            mandatory.add(squad)
            audit.append(
                {
                    **club,
                    "count": count,
                    "origin_id": origin,
                    "candidate_id": _candidate_id(squad),
                    "selected_club_players": [
                        int(element)
                        for element in squad
                        if int(eligible_meta[element]["team_id"]) == team_id
                    ],
                }
            )
    return origins, mandatory, audit


def _fast_nominal_scores(
    candidates: list[dict[str, Any]],
    player_ids: list[int],
    points: np.ndarray,
) -> np.ndarray:
    player_index = {element: index for index, element in enumerate(player_ids)}
    simulations = points.shape[0]
    total = np.zeros((simulations, len(candidates)), dtype=np.int16)
    for event_offset, event in enumerate(DEFAULT_EVENTS):
        rows: list[int] = []
        columns: list[int] = []
        values: list[int] = []
        for candidate_offset, candidate in enumerate(candidates):
            lineup = candidate["lineups"][str(event)]
            for element in lineup["starters"]:
                rows.append(candidate_offset)
                columns.append(player_index[int(element)])
                values.append(2 if int(element) == int(lineup["captain"]) else 1)
        weights = sparse.csr_matrix(
            (np.asarray(values, dtype=np.int8), (rows, columns)),
            shape=(len(candidates), len(player_ids)),
        )
        event_scores, _ = sparse_dense_matmul(
            weights,
            points[:, event_offset, :].T,
            label=f"nominal GW{event} candidate scoring",
        )
        total += np.rint(event_scores.T).astype(np.int16)
    return total


def _distribution_metrics(scores: np.ndarray) -> dict[str, np.ndarray]:
    cutoff = max(1, math.ceil(scores.shape[0] * 0.10))
    partitioned = np.partition(scores, cutoff - 1, axis=0)
    return {
        "mean": scores.mean(axis=0),
        "p10": partitioned[cutoff - 1].astype(np.float64),
        "cvar10": partitioned[:cutoff].mean(axis=0),
        "p90": np.quantile(scores, 0.90, axis=0),
        "sd": scores.std(axis=0),
    }


def _zscore(values: np.ndarray) -> np.ndarray:
    scale = float(values.std())
    return (values - values.mean()) / (scale if scale > 1e-9 else 1.0)


def _diverse_indices(
    candidates: list[dict[str, Any]],
    metrics: dict[str, np.ndarray],
    limit: int,
    mandatory_origins: set[str],
) -> list[int]:
    score = (
        0.75 * _zscore(metrics["mean"])
        + 0.20 * _zscore(metrics["cvar10"])
        - 0.05 * _zscore(metrics["sd"])
    )
    chosen: set[int] = {
        index
        for index, candidate in enumerate(candidates)
        if protected_candidate(candidate, mandatory_origins)
    }

    def add_ranked(values: np.ndarray, count: int, *, descending: bool = True) -> None:
        order = np.argsort(-values if descending else values, kind="stable")
        for index in order[:count]:
            chosen.add(int(index))

    add_ranked(score, max(1, limit // 2))
    add_ranked(metrics["mean"], max(1, limit // 5))
    add_ranked(metrics["cvar10"], max(1, limit // 8))
    add_ranked(metrics["p90"], max(1, limit // 12))
    for formation in sorted({candidate["gw1_formation"] for candidate in candidates}):
        eligible = np.asarray(
            [
                index
                for index, candidate in enumerate(candidates)
                if candidate["gw1_formation"] == formation
            ]
        )
        if len(eligible):
            for index in eligible[np.argsort(-score[eligible])[:8]]:
                chosen.add(int(index))
    for band in ("lean", "historical", "medium", "deep"):
        eligible = np.asarray(
            [
                index
                for index, candidate in enumerate(candidates)
                if _bench_band(float(candidate["gw1_bench_spend"])) == band
            ]
        )
        if len(eligible):
            for index in eligible[np.argsort(-score[eligible])[:8]]:
                chosen.add(int(index))
    global_protected: set[int] = set()
    for origin in sorted(GLOBAL_ORIGINS):
        eligible = np.asarray(
            [
                index
                for index, candidate in enumerate(candidates)
                if origin in set(candidate["origin_ids"])
            ],
            dtype=np.int32,
        )
        if len(eligible):
            leaders = eligible[np.argsort(-score[eligible])[:8]]
            chosen.update(map(int, leaders))
            global_protected.update(map(int, leaders))
    if len(chosen) < limit:
        for index in np.argsort(-score, kind="stable"):
            chosen.add(int(index))
            if len(chosen) >= limit:
                break
    mandatory = {
        index for index in chosen if protected_candidate(candidates[index], mandatory_origins)
    } | global_protected
    remaining = sorted(chosen - mandatory, key=lambda index: score[index], reverse=True)
    output = [*sorted(mandatory, key=lambda index: score[index], reverse=True)]
    output.extend(remaining[: max(0, limit - len(output))])
    return output


def _summarize_component_scores(
    raw_scores: np.ndarray,
    anchored_scores: np.ndarray,
    raw_weight: float,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    evidence = _blend_scenario_scores(raw_scores, anchored_scores, raw_weight)
    raw_total = raw_scores.sum(axis=2)
    anchored_total = anchored_scores.sum(axis=2)
    evidence_total = evidence.sum(axis=2)
    metrics = _distribution_metrics(evidence_total)
    metrics.update(
        {
            "raw_mean": raw_total.mean(axis=0),
            "anchored_mean": anchored_total.mean(axis=0),
            "evidence_mean": evidence_total.mean(axis=0),
        }
    )
    return metrics, evidence


def _component_finalist_indices(
    candidates: list[dict[str, Any]],
    metrics: dict[str, np.ndarray],
    limit: int,
    mandatory_origins: set[str] | None = None,
) -> list[int]:
    mandatory_origins = mandatory_origins or set()
    score = (
        0.65 * _zscore(metrics["evidence_mean"])
        + 0.15 * _zscore(metrics["cvar10"])
        + 0.10 * _zscore(metrics["raw_mean"])
        + 0.10 * _zscore(metrics["anchored_mean"])
    )
    mandatory = {
        index
        for index, candidate in enumerate(candidates)
        if protected_candidate(candidate, mandatory_origins)
    }
    if len(mandatory) > limit:
        raise ValueError("mandatory finalists exceed finalist limit")
    global_rankings: dict[str, list[int]] = {}
    for origin in sorted(GLOBAL_ORIGINS):
        eligible = np.asarray(
            [
                index
                for index, candidate in enumerate(candidates)
                if origin in set(candidate.get("origin_ids", []))
            ],
            dtype=np.int32,
        )
        global_rankings[origin] = (
            list(map(int, eligible[np.argsort(-score[eligible])])) if len(eligible) else []
        )
    for depth in range(4):
        for origin in sorted(GLOBAL_ORIGINS):
            if len(mandatory) >= limit:
                break
            ranking = global_rankings[origin]
            if depth < len(ranking):
                mandatory.add(ranking[depth])
    chosen: set[int] = set(mandatory)
    for key, share in (
        ("evidence_mean", 0.50),
        ("cvar10", 0.18),
        ("raw_mean", 0.12),
        ("anchored_mean", 0.12),
    ):
        count = max(1, math.ceil(limit * share))
        chosen.update(np.argsort(-metrics[key], kind="stable")[:count].tolist())
    for formation in sorted({candidate["gw1_formation"] for candidate in candidates}):
        eligible = np.asarray(
            [i for i, candidate in enumerate(candidates) if candidate["gw1_formation"] == formation]
        )
        if len(eligible):
            chosen.update(eligible[np.argsort(-score[eligible])[:3]].tolist())
    if len(chosen) < limit:
        for index in np.argsort(-score, kind="stable"):
            chosen.add(int(index))
            if len(chosen) >= limit:
                break
    remaining = sorted(chosen - mandatory, key=lambda index: score[index], reverse=True)
    output = [*sorted(mandatory, key=lambda index: score[index], reverse=True)]
    output.extend(remaining[: max(0, limit - len(output))])
    return output


def _protect_role_safe_finalists(
    candidates: list[dict[str, Any]],
    metrics: dict[str, np.ndarray],
    safe_indices: list[int],
    *,
    limit: int,
    minimum: int = ROLE_SAFE_FINALIST_MINIMUM,
    mandatory_origins: set[str] | None = None,
) -> list[int]:
    """Protect a competitively ranked role-safe field before the deep holdout.

    Role integrity is part of the legal decision policy, not an after-the-fact report. The global
    search still retains its deliberately unsafe premium/captain counterfactuals for diagnosis,
    while reserving enough finalist capacity for candidates that can actually be published.
    """

    if minimum < 1 or limit < minimum:
        raise ValueError("role-safe finalist minimum must fit inside the finalist limit")
    unique_safe = sorted(set(map(int, safe_indices)))
    if len(unique_safe) < minimum:
        raise RuntimeError(
            f"role-safe discovery guard found only {len(unique_safe)} candidates; "
            f"at least {minimum} are required"
        )
    existing_mandatory = {
        index
        for index, candidate in enumerate(candidates)
        if protected_candidate(candidate, mandatory_origins)
    }
    if len(existing_mandatory) + minimum > limit:
        raise RuntimeError(
            "role-safe finalist reserve does not fit beside the protected benchmark field"
        )
    ranked_safe = sorted(
        unique_safe,
        key=lambda index: (
            float(metrics["evidence_mean"][index]),
            float(metrics["cvar10"][index]),
            str(candidates[index].get("candidate_id") or index),
        ),
        reverse=True,
    )
    protected = ranked_safe[:minimum]
    for index in protected:
        candidates[index]["origin_ids"] = sorted(
            {*map(str, candidates[index].get("origin_ids") or []), "role-safe-finalist"}
        )
    return protected


def _transfer_policy(solution: dict[str, Any]) -> dict[str, Any]:
    return {
        str(event): {
            "available": int(plan["available"]),
            "used": int(plan["used"]),
            "in": [
                {
                    "element": int(element),
                    "name": solution["player_meta"][element]["player_name"],
                }
                for element in plan["in"]
            ],
            "out": [
                {
                    "element": int(element),
                    "name": solution["player_meta"][element]["player_name"],
                }
                for element in plan["out"]
            ],
        }
        for event, plan in solution["transfers"].items()
    }


def _policy_variant(
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
    kind: str,
    events: tuple[int, ...] = DEFAULT_EVENTS,
    *,
    highs_threads: int | None = None,
) -> dict[str, Any]:
    output = dict(candidate)
    output["root_candidate_id"] = candidate["candidate_id"]
    output["variant_kind"] = kind
    output["candidate_id"] = f"{candidate['candidate_id']}:{kind}"
    if kind == "fixed":
        output["transfer_policy"] = {}
        output["transfer_count_after_gw1"] = 0
        return output
    solution = _solve(
        rows,
        list(events),
        initial_squad=set(map(int, candidate["selected"])),
        forbid_transfer_events={events[1]} if kind == "roll-gw2" else set(),
        highs_threads=highs_threads,
    )
    output["planned_squads"] = {
        str(event): list(solution["planned_squads"][event]) for event in events
    }
    output["lineups"] = {str(event): dict(solution["lineups"][event]) for event in events}
    output["transfer_policy"] = _transfer_policy(solution)
    output["transfer_count_after_gw1"] = sum(
        int(plan["used"]) for plan in output["transfer_policy"].values()
    )
    return output


_POLICY_WORKER_ROWS: list[dict[str, Any]] | None = None
_POLICY_WORKER_EVENTS: tuple[int, ...] | None = None


def _initialize_policy_worker(
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
) -> None:
    global _POLICY_WORKER_ROWS, _POLICY_WORKER_EVENTS
    _POLICY_WORKER_ROWS = rows
    _POLICY_WORKER_EVENTS = events


def _solve_policy_worker(task: tuple[int, dict[str, Any], str]) -> tuple[int, str, dict[str, Any]]:
    index, candidate, kind = task
    if _POLICY_WORKER_ROWS is None or _POLICY_WORKER_EVENTS is None:
        raise RuntimeError("policy worker was not initialized")
    return (
        index,
        kind,
        _policy_variant(
            candidate,
            _POLICY_WORKER_ROWS,
            kind,
            _POLICY_WORKER_EVENTS,
            highs_threads=1,
        ),
    )


def parallel_policy_variants(
    candidates: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    events: tuple[int, ...] = DEFAULT_EVENTS,
    *,
    progress_label: str = "Policy solve",
) -> list[dict[str, Any]]:
    """Solve independent open/roll policies across CPU processes in stable order."""

    fixed = {
        index: _policy_variant(candidate, rows, "fixed", events)
        for index, candidate in enumerate(candidates)
    }
    tasks = [
        (index, candidate, kind)
        for index, candidate in enumerate(candidates)
        for kind in ("open", "roll-gw2")
    ]
    workers = min(policy_worker_count(), len(tasks))
    if workers <= 1:
        solved = {
            (index, kind): _policy_variant(candidate, rows, kind, events)
            for index, candidate, kind in tasks
        }
    else:
        print(
            f"Acceleration: {progress_label} using {workers} CPU workers "
            f"for {len(tasks)} independent MILPs",
            flush=True,
        )
        solved: dict[tuple[int, str], dict[str, Any]] = {}
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_initialize_policy_worker,
            initargs=(rows, events),
        ) as executor:
            futures = {executor.submit(_solve_policy_worker, task): task for task in tasks}
            interval = max(1, len(tasks) // 12)
            for completed, future in enumerate(as_completed(futures), start=1):
                index, kind, variant = future.result()
                solved[(index, kind)] = variant
                if completed % interval == 0 or completed == len(tasks):
                    print(
                        f"{progress_label}: solved {completed}/{len(tasks)} policies",
                        flush=True,
                    )
    return [
        fixed[index] if kind == "fixed" else solved[(index, kind)]
        for index in range(len(candidates))
        for kind in ("fixed", "open", "roll-gw2")
    ]


def _weighted_regret(
    scenario_values: dict[str, float], scenario_bests: dict[str, float]
) -> dict[str, Any]:
    regrets = {
        name: float(scenario_bests[name] - scenario_values[name]) for name in SCENARIO_WEIGHTS
    }
    weighted_mean = sum(SCENARIO_WEIGHTS[name] * regrets[name] for name in SCENARIO_WEIGHTS)
    worst = max(regrets.values())
    return {
        "scenario_regrets": regrets,
        "weighted_mean_regret": weighted_mean,
        "worst_scenario_regret": worst,
        "robust_regret": 0.75 * weighted_mean + 0.25 * worst,
    }


def _paired_comparison(challenger: np.ndarray, incumbent: np.ndarray) -> dict[str, float]:
    delta = challenger.astype(np.float64) - incumbent.astype(np.float64)
    standard_error = float(delta.std(ddof=1) / math.sqrt(len(delta)))
    return {
        "mean_delta": float(delta.mean()),
        "delta_95ci_low": float(delta.mean() - 1.96 * standard_error),
        "delta_95ci_high": float(delta.mean() + 1.96 * standard_error),
        "beat_probability": float(np.mean(delta > 0)),
        "tie_probability": float(np.mean(delta == 0)),
    }


def _metric_rows(candidates: list[dict[str, Any]], metrics: dict[str, np.ndarray]) -> list[dict]:
    return [
        {
            "candidate_id": candidate["candidate_id"],
            "display_name": candidate["display_name"],
            "gw1_formation": candidate["gw1_formation"],
            "gw1_bench_spend": candidate["gw1_bench_spend"],
            **{key: float(value[index]) for key, value in metrics.items()},
        }
        for index, candidate in enumerate(candidates)
    ]


def _write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")


def _validate_config(
    discovery_candidates: int,
    screen_simulations: int,
    shortlist: int,
    selection_simulations: int,
    finalists: int,
    holdout_simulations: int,
    global_restarts: int,
    evolution_population: int,
    evolution_generations: int,
    evolution_offspring: int,
    minimum_seed_distance: int,
) -> None:
    if discovery_candidates < 500:
        raise ValueError("discovery_candidates must be at least 500")
    if screen_simulations < 500:
        raise ValueError("screen_simulations must be at least 500")
    if not 32 <= shortlist < discovery_candidates:
        raise ValueError("shortlist must be at least 32 and smaller than discovery_candidates")
    if selection_simulations < 1_000:
        raise ValueError("selection_simulations must be at least 1,000")
    if not 8 <= finalists < shortlist:
        raise ValueError("finalists must be at least 8 and smaller than shortlist")
    if holdout_simulations < 5_000:
        raise ValueError("holdout_simulations must be at least 5,000")
    if global_restarts < 32:
        raise ValueError("global_restarts must be at least 32")
    if evolution_population < 32:
        raise ValueError("evolution_population must be at least 32")
    if evolution_generations < 1:
        raise ValueError("evolution_generations must be at least 1")
    if evolution_offspring < evolution_population:
        raise ValueError("evolution_offspring must be at least evolution_population")
    if not 3 <= minimum_seed_distance <= 8:
        raise ValueError("minimum_seed_distance must be in [3, 8]")


def run_robust_search(
    *,
    discovery_candidates: int = 10_000,
    screen_simulations: int = 2_000,
    shortlist: int = 512,
    selection_simulations: int = 5_000,
    finalists: int = 64,
    holdout_simulations: int = 25_000,
    discovery_seed: int = 20260804,
    selection_seed: int = 20260805,
    holdout_seed: int = 20260806,
    stress_goal_multiplier: float = 1.15,
    global_restarts: int = 256,
    evolution_population: int = 256,
    evolution_generations: int = 10,
    evolution_offspring: int = 2_048,
    minimum_seed_distance: int = 3,
    participation_consensus_path: Path = PARTICIPATION_CONSENSUS,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    _validate_config(
        discovery_candidates,
        screen_simulations,
        shortlist,
        selection_simulations,
        finalists,
        holdout_simulations,
        global_restarts,
        evolution_population,
        evolution_generations,
        evolution_offspring,
        minimum_seed_distance,
    )
    if len({discovery_seed, selection_seed, holdout_seed}) != 3:
        raise ValueError("discovery, selection and holdout seeds must be distinct")
    if stress_goal_multiplier <= 1.0:
        raise ValueError("stress_goal_multiplier must be greater than one")
    ensure_engine_layout()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    residual_payload = load_json_artifact(CANDIDATES_JSON, "residual seed candidates")
    current_forecast_sha256 = require_current_forecast(
        residual_payload, CURRENT_FORECAST, "residual seed candidates"
    )
    component_payload = load_json_artifact(COMPONENT_CANDIDATES_JSON, "component seed candidates")
    require_recorded_hash(
        component_payload,
        ("forecast_sha256",),
        current_forecast_sha256,
        "component seed candidates",
    )
    cuda = require_cuda()
    print("Robust search: loading forecasts and seed squads", flush=True)
    rows, loaded = _load_rows(DEFAULT_EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    if not participation_consensus_path.is_file():
        raise FileNotFoundError(
            "Run participation-consensus collection before robust search: "
            f"{participation_consensus_path}"
        )
    participation_consensus = {
        int(row["element"]): str(row.get("consensus") or "not_covered")
        for row in pq.read_table(participation_consensus_path).to_pylist()
        if int(row["event"]) == 1
    }
    role_gate_forecasts = {
        int(row["element"]): {
            **row,
            "live_participation_consensus": participation_consensus.get(
                int(row["element"]), "not_covered"
            ),
        }
        for row in rows
        if int(row["event_number"]) == 1
    }
    eligible_meta = _eligible_meta(rows)
    player_ids = sorted(eligible_meta)
    player_index = {element: index for index, element in enumerate(player_ids)}
    eligible_by_position: dict[str, list[int]] = defaultdict(list)
    for element in player_ids:
        eligible_by_position[str(eligible_meta[element]["position"])].append(element)
    rules = load_rules()
    origins, seeds = _load_seed_squads(current_forecast_sha256)
    mandatory = set(seeds)
    utilities, scenario_definitions = _proxy_utilities(rows, player_ids)
    (
        archetype_origins,
        archetype_squads,
        archetype_players,
        incumbent_captain_leader,
    ) = _generate_archetype_squads(
        rows=[row for row in rows if int(row["element"]) in eligible_meta],
        player_ids=player_ids,
        eligible_meta=eligible_meta,
        by_player=by_player,
    )
    for squad, labels in archetype_origins.items():
        origins[squad].update(labels)
    mandatory.update(archetype_squads)
    print(
        "Robust search: generated "
        f"{len(archetype_squads)} protected premium/captain archetype squads",
        flush=True,
    )
    club_stack_origins, club_stack_squads, club_stack_audit = _generate_club_stack_squads(
        rows=[row for row in rows if int(row["element"]) in eligible_meta],
        eligible_meta=eligible_meta,
        by_player=by_player,
    )
    for squad, labels in club_stack_origins.items():
        origins[squad].update(labels)
    mandatory.update(club_stack_squads)
    print(
        "Robust search: generated "
        f"{len(club_stack_squads)} protected two/three-player club-stack squads",
        flush=True,
    )

    print(
        "Robust search: generating globally distant MILP and evolutionary squads",
        flush=True,
    )
    global_result = generate_global_squads(
        seeds,
        eligible_meta,
        utilities,
        budget=float(rules.budget),
        club_limit=int(rules.club_limit),
        restarts=global_restarts,
        population_size=evolution_population,
        generations=evolution_generations,
        offspring_per_generation=evolution_offspring,
        minimum_seed_distance=minimum_seed_distance,
        seed=discovery_seed + 17,
    )
    global_milp = set(global_result.milp_squads)
    global_evolution = set(global_result.evolution_squads)
    global_universe = global_milp | global_evolution | archetype_squads | club_stack_squads
    for squad in global_milp:
        origins[squad].add("global-milp")
    for squad in global_evolution:
        origins[squad].add("global-evolution")
    global_anchors, global_proxy = _prefilter_squads(
        global_universe,
        player_index,
        utilities,
        min(256, len(global_universe)),
        mandatory=set(),
    )
    global_anchor_set = set(global_anchors)
    mandatory.update(global_anchors)
    seed_sets = [set(seed) for seed in seeds]
    global_rows = []
    for squad in sorted(global_universe):
        sources = []
        if squad in global_milp:
            sources.append("global-milp")
        if squad in global_evolution:
            sources.append("global-evolution")
        sources.extend(sorted(archetype_origins.get(squad, set())))
        sources.extend(sorted(club_stack_origins.get(squad, set())))
        global_rows.append(
            {
                "candidate_id": _candidate_id(squad),
                "source": sources,
                "selected": list(squad),
                "minimum_seed_swap_distance": minimum_distance(squad, seed_sets),
                "budget_spent": sum(
                    float(eligible_meta[element]["market_price"]) for element in squad
                )
                / 10.0,
                "proxy_anchor": squad in global_anchor_set,
                "proxy_score": global_proxy.get(squad),
            }
        )
    _write_parquet(global_rows, GLOBAL_PARQUET)
    print(
        f"Robust search: generated {len(global_milp):,} distant MILP squads and "
        f"{len(global_evolution):,} evolutionary squads",
        flush=True,
    )

    first_universe: set[tuple[int, ...]] = set(seeds)
    for seed_squad in seeds:
        first_universe.update(
            _legal_swap_neighbours(
                seed_squad,
                eligible_meta,
                eligible_by_position,
                budget=float(rules.budget),
                club_limit=int(rules.club_limit),
            )
        )
    print(
        f"Robust search: generated {len(first_universe):,} legal one-swap squads",
        flush=True,
    )
    expansion_bases, _ = _prefilter_squads(
        first_universe,
        player_index,
        utilities,
        min(128, len(first_universe)),
        mandatory=set(),
    )
    expanded_universe = set(first_universe)
    for base in expansion_bases:
        expanded_universe.update(
            _legal_swap_neighbours(
                base,
                eligible_meta,
                eligible_by_position,
                budget=float(rules.budget),
                club_limit=int(rules.club_limit),
            )
        )
    local_expanded_count = len(expanded_universe)
    expanded_universe.update(global_universe)
    print(
        f"Robust search: combined {local_expanded_count:,} local and "
        f"{len(global_universe):,} global squads into {len(expanded_universe):,} candidates",
        flush=True,
    )
    prefilter_limit = min(len(expanded_universe), max(20_000, discovery_candidates * 3))
    prefiltered, _ = _prefilter_squads(
        expanded_universe, player_index, utilities, prefilter_limit, mandatory
    )
    discovered, proxy_scores = _prefilter_squads(
        prefiltered, player_index, utilities, discovery_candidates, mandatory
    )
    print(
        f"Robust search: retained {len(discovered):,} multi-objective discovery candidates",
        flush=True,
    )
    records = []
    discovery_rows = []
    for squad in discovered:
        candidate_origins = origins.get(squad, set())
        distance = 15 - max(len(set(squad) & seed) for seed in seed_sets)
        candidate_records = [
            _record_candidate(
                squad, by_player, meta, candidate_origins, proxy_scores.get(squad, 0.0)
            )
        ]
        base_captain = int(candidate_records[0]["lineups"]["1"]["captain"])
        starters = set(map(int, candidate_records[0]["lineups"]["1"]["starters"]))
        forced = {
            int(origin.rsplit("-", 1)[1])
            for origin in candidate_origins
            if origin.startswith("archetype-player-")
        }
        for element in sorted(forced & starters):
            if element == base_captain:
                continue
            forced_origins = {
                *candidate_origins,
                f"captain-counterfactual-{element}",
            }
            candidate_records.append(
                _record_candidate(
                    squad,
                    by_player,
                    meta,
                    forced_origins,
                    proxy_scores.get(squad, 0.0),
                    forced_captain=element,
                )
            )
        for record in candidate_records:
            record["minimum_seed_swap_distance"] = distance
            records.append(record)
            discovery_rows.append(
                {
                    "candidate_id": record["candidate_id"],
                    "display_name": record["display_name"],
                    "origin_ids": record["origin_ids"],
                    "selected": record["selected"],
                    "budget_spent": record["budget_spent"],
                    "bank": record["bank"],
                    "gw1_bench_spend": record["gw1_bench_spend"],
                    "gw1_formation": record["gw1_formation"],
                    "proxy_score": record["proxy_score"],
                    "minimum_seed_swap_distance": distance,
                    "forced_gw1_captain": record["forced_gw1_captain"],
                }
            )
            squad_rows = [meta[element] for element in record["selected"]]
            validate_squad(squad_rows, rules)
            for event in DEFAULT_EVENTS:
                lineup = record["lineups"][str(event)]
                validate_lineup(
                    squad_rows,
                    lineup["starters"],
                    lineup["bench_order"],
                    lineup["captain"],
                    lineup["vice_captain"],
                    rules,
                )
    _write_parquet(discovery_rows, DISCOVERY_PARQUET)

    calibration = calibrate_residuals()
    residual_player_ids = sorted(by_player)
    residual_points, _ = _simulate_player_outcomes(
        residual_player_ids,
        DEFAULT_EVENTS,
        by_player,
        calibration,
        screen_simulations,
        discovery_seed + 101,
    )
    fast_scores = _fast_nominal_scores(records, residual_player_ids, residual_points)
    screening_metrics = _distribution_metrics(fast_scores)
    screening_indices = _diverse_indices(
        records,
        screening_metrics,
        shortlist,
        BENCHMARK_ORIGINS,
    )
    screening_rows = _metric_rows(records, screening_metrics)
    _write_parquet(screening_rows, SCREENING_PARQUET)
    shortlisted = [records[index] for index in screening_indices]
    print(
        f"Robust search: residual screen retained {len(shortlisted):,} candidates",
        flush=True,
    )
    SHORTLIST_JSON.write_text(
        json.dumps(
            {
                "version": VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "discovery_seed": discovery_seed,
                "screen_simulations": screen_simulations,
                "candidate_count": len(shortlisted),
                "forecast_sha256": current_forecast_sha256,
                "candidates": shortlisted,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    goal_metrics = train_goal_model(force=False, seed=selection_seed)
    component_backtest = json.loads(COMPONENT_BACKTEST_METRICS.read_text(encoding="utf-8"))
    evidence_raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, DEFAULT_EVENTS)
    empirical = calibrate_empirical_components()
    (
        component_player_ids,
        selection_raw_points,
        selection_anchored_points,
        selection_played,
        _,
        selection_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        DEFAULT_EVENTS,
        goal_rates,
        empirical,
        selection_simulations,
        selection_seed + 301,
    )
    selection_raw_scores = _score_candidates(
        shortlisted,
        component_player_ids,
        DEFAULT_EVENTS,
        selection_raw_points,
        selection_played,
        meta,
    )
    selection_anchored_scores = _score_candidates(
        shortlisted,
        component_player_ids,
        DEFAULT_EVENTS,
        selection_anchored_points,
        selection_played,
        meta,
    )
    component_selection_metrics, _ = _summarize_component_scores(
        selection_raw_scores, selection_anchored_scores, evidence_raw_weight
    )
    role_safe_indices = [
        index
        for index, candidate in enumerate(shortlisted)
        if not candidate_publication_role_risks(
            candidate,
            role_gate_forecasts,
            meta,
        )
    ]
    protected_role_safe_indices = _protect_role_safe_finalists(
        shortlisted,
        component_selection_metrics,
        role_safe_indices,
        limit=finalists,
        mandatory_origins=BENCHMARK_ORIGINS,
    )
    SHORTLIST_JSON.write_text(
        json.dumps(
            {
                "version": VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "discovery_seed": discovery_seed,
                "screen_simulations": screen_simulations,
                "candidate_count": len(shortlisted),
                "forecast_sha256": current_forecast_sha256,
                "role_safe_candidates": len(role_safe_indices),
                "protected_role_safe_candidates": len(protected_role_safe_indices),
                "participation_consensus_sha256": sha256_file(participation_consensus_path),
                "candidates": shortlisted,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Robust search: protected "
        f"{len(protected_role_safe_indices)}/{len(role_safe_indices)} publication-eligible "
        "shortlist candidates",
        flush=True,
    )
    finalist_indices = _component_finalist_indices(
        shortlisted,
        component_selection_metrics,
        finalists,
        BENCHMARK_ORIGINS,
    )
    selection_rows = _metric_rows(shortlisted, component_selection_metrics)
    _write_parquet(selection_rows, SELECTION_PARQUET)
    finalist_candidates = [shortlisted[index] for index in finalist_indices]
    finalist_origin_ids = {
        str(origin)
        for candidate in finalist_candidates
        for origin in candidate.get("origin_ids", [])
    }
    expected_stack_origins = {str(item["origin_id"]) for item in club_stack_audit}
    missing_stack_origins = sorted(expected_stack_origins - finalist_origin_ids)
    if missing_stack_origins:
        raise RuntimeError(
            "club-stack publication guard failed; protected stacks did not reach deep holdout: "
            + ", ".join(missing_stack_origins)
        )
    finalist_captains = Counter(
        int(candidate["lineups"]["1"]["captain"]) for candidate in finalist_candidates
    )
    captain_counterfactuals = [
        candidate
        for candidate in finalist_candidates
        if any(
            str(origin).startswith("captain-counterfactual-") for origin in candidate["origin_ids"]
        )
    ]
    no_leader_finalists = [
        candidate
        for candidate in finalist_candidates
        if incumbent_captain_leader not in set(map(int, candidate["selected"]))
    ]
    if len(finalist_captains) < 3 or len(captain_counterfactuals) < 2:
        raise RuntimeError(
            "captain-diversity publication guard failed: the deep holdout requires at "
            "least three captains and two explicit captain counterfactuals"
        )
    if not no_leader_finalists:
        raise RuntimeError(
            "squad-diversity publication guard failed: no deep finalist excludes the "
            "incumbent mean-xP leader"
        )
    captain_diversity_audit = {
        "passed": True,
        "distinct_captains": len(finalist_captains),
        "captain_counts": {
            str(element): {
                "player_name": str(meta[element]["player_name"]),
                "finalists": count,
            }
            for element, count in finalist_captains.items()
        },
        "explicit_captain_counterfactuals": len(captain_counterfactuals),
        "no_incumbent_leader_finalists": len(no_leader_finalists),
        "incumbent_leader": {
            "element": incumbent_captain_leader,
            "player_name": str(meta[incumbent_captain_leader]["player_name"]),
        },
        "protected_archetype_players": [
            {
                "element": element,
                "player_name": str(meta[element]["player_name"]),
                "position": str(meta[element]["position"]),
                "price": float(meta[element]["market_price"]) / 10.0,
            }
            for element in archetype_players
        ],
    }
    print(
        f"Robust search: component selection retained {len(finalist_candidates):,} finalists",
        flush=True,
    )

    print("Robust search: solving open and rolled-GW2 transfer policies", flush=True)
    variants = parallel_policy_variants(
        finalist_candidates,
        rows,
        progress_label="Robust policy solve",
    )
    (
        holdout_player_ids,
        holdout_raw_points,
        holdout_anchored_points,
        holdout_played,
        _,
        holdout_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        DEFAULT_EVENTS,
        goal_rates,
        empirical,
        holdout_simulations,
        holdout_seed + 301,
    )
    holdout_raw_scores = _score_candidates(
        variants,
        holdout_player_ids,
        DEFAULT_EVENTS,
        holdout_raw_points,
        holdout_played,
        meta,
    )
    holdout_anchored_scores = _score_candidates(
        variants,
        holdout_player_ids,
        DEFAULT_EVENTS,
        holdout_anchored_points,
        holdout_played,
        meta,
    )
    holdout_evidence_scores = _blend_scenario_scores(
        holdout_raw_scores, holdout_anchored_scores, evidence_raw_weight
    )
    print("Robust search: base holdout complete; running high-goal stress", flush=True)
    stress_rates = {
        key: (home * stress_goal_multiplier, away * stress_goal_multiplier)
        for key, (home, away) in goal_rates.items()
    }
    (
        stress_player_ids,
        stress_raw_points,
        _,
        stress_played,
        _,
        stress_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        DEFAULT_EVENTS,
        stress_rates,
        empirical,
        holdout_simulations,
        holdout_seed + 701,
    )
    stress_scores = _score_candidates(
        variants,
        stress_player_ids,
        DEFAULT_EVENTS,
        stress_raw_points,
        stress_played,
        meta,
    )
    variant_index = {
        (variant["root_candidate_id"], variant["variant_kind"]): index
        for index, variant in enumerate(variants)
    }
    scenario_by_candidate: dict[str, dict[str, float]] = {}
    central_paths: dict[str, np.ndarray] = {}
    candidate_by_id = {candidate["candidate_id"]: candidate for candidate in finalist_candidates}
    for candidate in finalist_candidates:
        candidate_id = candidate["candidate_id"]
        fixed = variant_index[(candidate_id, "fixed")]
        opened = variant_index[(candidate_id, "open")]
        rolled = variant_index[(candidate_id, "roll-gw2")]
        central = holdout_evidence_scores[:, opened, :].sum(axis=1)
        central_paths[candidate_id] = central
        scenario_by_candidate[candidate_id] = {
            "base_evidence_open": float(central.mean()),
            "base_evidence_roll_gw2": float(
                holdout_evidence_scores[:, rolled, :].sum(axis=1).mean()
            ),
            "base_evidence_fixed": float(holdout_evidence_scores[:, fixed, :].sum(axis=1).mean()),
            "base_raw_open": float(holdout_raw_scores[:, opened, :].sum(axis=1).mean()),
            "base_anchored_open": float(holdout_anchored_scores[:, opened, :].sum(axis=1).mean()),
            "high_goal_open": float(stress_scores[:, opened, :].sum(axis=1).mean()),
            "high_goal_roll_gw2": float(stress_scores[:, rolled, :].sum(axis=1).mean()),
            "high_goal_fixed": float(stress_scores[:, fixed, :].sum(axis=1).mean()),
        }
    scenario_bests = {
        name: max(values[name] for values in scenario_by_candidate.values())
        for name in SCENARIO_WEIGHTS
    }
    robust_rows = []
    for candidate_id, scenario_values in scenario_by_candidate.items():
        regret = _weighted_regret(scenario_values, scenario_bests)
        path = central_paths[candidate_id]
        candidate = candidate_by_id[candidate_id]
        robust_rows.append(
            {
                "candidate_id": candidate_id,
                "display_name": candidate["display_name"],
                "origin_ids": candidate["origin_ids"],
                "gw1_formation": candidate["gw1_formation"],
                "gw1_bench_spend": candidate["gw1_bench_spend"],
                "base_p10": float(np.quantile(path, 0.10)),
                "base_p90": float(np.quantile(path, 0.90)),
                "base_cvar10": float(path[path <= np.quantile(path, 0.10)].mean()),
                "scenario_values": scenario_values,
                **regret,
            }
        )
    robust_rows.sort(
        key=lambda row: (
            row["scenario_regrets"]["base_evidence_open"] > CENTRAL_REGRET_CAP,
            row["robust_regret"],
            -row["scenario_values"]["base_evidence_open"],
        )
    )
    leader = robust_rows[0]
    runner_up = robust_rows[1]
    sensitivity = {"worst_case_penalty": [], "leave_one_scenario_out": []}
    for penalty in (0.0, 0.10, 0.25, 0.50):
        ranked = sorted(
            robust_rows,
            key=lambda row: (
                row["scenario_regrets"]["base_evidence_open"] > CENTRAL_REGRET_CAP,
                (1.0 - penalty) * row["weighted_mean_regret"]
                + penalty * row["worst_scenario_regret"],
            ),
        )
        sensitivity["worst_case_penalty"].append(
            {"penalty": penalty, "winner": ranked[0]["candidate_id"]}
        )
    for excluded in SCENARIO_WEIGHTS:
        retained = {name: weight for name, weight in SCENARIO_WEIGHTS.items() if name != excluded}
        normalizer = sum(retained.values())

        def ablated_score(
            row: dict[str, Any],
            weights: dict[str, float] = retained,
            total_weight: float = normalizer,
        ) -> float:
            regrets = row["scenario_regrets"]
            mean = sum(weights[name] * regrets[name] for name in weights) / total_weight
            worst = max(regrets[name] for name in weights)
            return 0.75 * mean + 0.25 * worst

        ranked = sorted(
            robust_rows,
            key=lambda row: (
                row["scenario_regrets"]["base_evidence_open"] > CENTRAL_REGRET_CAP,
                ablated_score(row),
            ),
        )
        sensitivity["leave_one_scenario_out"].append(
            {"excluded": excluded, "winner": ranked[0]["candidate_id"]}
        )
    comparison = _paired_comparison(
        central_paths[leader["candidate_id"]], central_paths[runner_up["candidate_id"]]
    )
    robust_rank = {row["candidate_id"]: rank for rank, row in enumerate(robust_rows, start=1)}
    club_stack_challenge = []
    for stack in club_stack_audit:
        origin = str(stack["origin_id"])
        eligible = [row for row in robust_rows if origin in set(row["origin_ids"])]
        if not eligible:
            raise RuntimeError(f"protected club stack {origin} has no deep-holdout result")
        best = min(eligible, key=lambda row: robust_rank[row["candidate_id"]])
        club_stack_challenge.append(
            {
                **stack,
                "deep_candidate_id": best["candidate_id"],
                "robust_rank": robust_rank[best["candidate_id"]],
                "central_mean": best["scenario_values"]["base_evidence_open"],
                "robust_regret": best["robust_regret"],
            }
        )
    benchmark_comparisons = []
    for origin in sorted(BENCHMARK_ORIGINS):
        benchmark = next(
            (row for row in robust_rows if origin in set(row["origin_ids"])),
            None,
        )
        if benchmark is None:
            continue
        benchmark_comparisons.append(
            {
                "origin_id": origin,
                "candidate_id": benchmark["candidate_id"],
                "robust_rank": robust_rank[benchmark["candidate_id"]],
                "robust_regret": benchmark["robust_regret"],
                "central_mean": benchmark["scenario_values"]["base_evidence_open"],
                "leader_minus_benchmark": _paired_comparison(
                    central_paths[leader["candidate_id"]],
                    central_paths[benchmark["candidate_id"]],
                ),
            }
        )
    global_finalist_rows = [row for row in robust_rows if GLOBAL_ORIGINS & set(row["origin_ids"])]
    best_global = global_finalist_rows[0] if global_finalist_rows else None
    global_challenge = {
        "milp_generated": len(global_milp),
        "evolution_generated": len(global_evolution),
        "evolution_generations": global_result.generations_completed,
        "attempted_offspring": global_result.attempted_offspring,
        "rejected_near_seed": global_result.rejected_near_seed,
        "rejected_illegal": global_result.rejected_illegal,
        "minimum_seed_distance_required": minimum_seed_distance,
        "discovery_candidates": sum(
            bool(GLOBAL_ORIGINS & set(record["origin_ids"])) for record in records
        ),
        "shortlist_candidates": sum(
            bool(GLOBAL_ORIGINS & set(record["origin_ids"])) for record in shortlisted
        ),
        "finalists": len(global_finalist_rows),
        "best_finalist": best_global,
        "leader_minus_best_global": (
            _paired_comparison(
                central_paths[leader["candidate_id"]],
                central_paths[best_global["candidate_id"]],
            )
            if best_global is not None
            else None
        ),
    }
    leader_candidate = candidate_by_id[leader["candidate_id"]]
    leader_variants = {
        kind: variants[variant_index[(leader["candidate_id"], kind)]]
        for kind in ("fixed", "open", "roll-gw2")
    }
    all_squad_sets = [set(record["selected"]) for record in records]
    array_acceleration = cuda_device()
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "seeds": {
            "discovery": discovery_seed,
            "selection": selection_seed,
            "holdout": holdout_seed,
            "independent": len({discovery_seed, selection_seed, holdout_seed}) == 3,
        },
        "funnel": {
            "seed_squads": len(seeds),
            "one_swap_universe": len(first_universe),
            "local_two_swap_universe": local_expanded_count,
            "global_milp_squads": len(global_milp),
            "global_evolution_squads": len(global_evolution),
            "combined_universe": len(expanded_universe),
            "proxy_scenarios": len(scenario_definitions),
            "discovery_candidates": len(records),
            "screen_simulations": screen_simulations,
            "shortlist": len(shortlisted),
            "selection_simulations": selection_simulations,
            "finalists": len(finalist_candidates),
            "holdout_simulations": holdout_simulations,
            "stress_simulations": holdout_simulations,
            "policy_variants_per_finalist": 3,
            "role_safe_shortlist_candidates": len(role_safe_indices),
            "protected_role_safe_finalists": len(protected_role_safe_indices),
        },
        "diversity": {
            "unique_players": len(set().union(*all_squad_sets)),
            "formations": dict(Counter(record["gw1_formation"] for record in records)),
            "bench_bands": dict(
                Counter(_bench_band(float(record["gw1_bench_spend"])) for record in records)
            ),
            "maximum_seed_swap_distance": max(
                int(record["minimum_seed_swap_distance"]) for record in records
            ),
            "captain_publication_guard": captain_diversity_audit,
            "club_stack_publication_guard": {
                "passed": True,
                "protected_clubs": len({item["team_id"] for item in club_stack_audit}),
                "protected_stack_constraints": len(club_stack_audit),
                "stack_counts": list(CLUB_STACK_COUNTS),
            },
        },
        "model": {
            "evidence_raw_weight": evidence_raw_weight,
            "stress_goal_multiplier": stress_goal_multiplier,
            "scenario_weights": SCENARIO_WEIGHTS,
            "central_regret_cap": CENTRAL_REGRET_CAP,
            "cuda": cuda,
            "array_acceleration": array_acceleration or {"backend": "numpy"},
            "goal_model_acceptance": goal_metrics["acceptance"],
            "goal_rate_diagnostics": goal_diagnostics,
        },
        "leader": leader,
        "runner_up": runner_up,
        "central_paired_comparison": comparison,
        "benchmark_comparisons": benchmark_comparisons,
        "global_challenge": global_challenge,
        "club_stack_challenge": club_stack_challenge,
        "decision_sensitivity": sensitivity,
        "leader_candidate": leader_candidate,
        "leader_transfer_policies": {
            kind: variant.get("transfer_policy", {}) for kind, variant in leader_variants.items()
        },
        "finalist_metrics": robust_rows,
        "diagnostics": {
            "component_selection": selection_diagnostics,
            "component_holdout": holdout_diagnostics,
            "high_goal_stress": stress_diagnostics,
        },
        "artifacts": {
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
            "residual_candidates_sha256": sha256_file(CANDIDATES_JSON),
            "component_candidates_sha256": sha256_file(COMPONENT_CANDIDATES_JSON),
            "global_shortlist_sha256": sha256_file(SHORTLIST_JSON),
            "participation_consensus_sha256": sha256_file(participation_consensus_path),
            "discovery": str(DISCOVERY_PARQUET),
            "screening": str(SCREENING_PARQUET),
            "selection": str(SELECTION_PARQUET),
            "global": str(GLOBAL_PARQUET),
        },
        "decision_status": "robust_challenger_provisional",
        "deadline_rule": (
            "Refresh live forecasts and rerun the complete funnel. Promote only if the robust leader "
            "remains near-optimal across central, no-GW2-transfer and scoring-environment scenarios."
        ),
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DECISION_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(result, meta), encoding="utf-8")
    print(
        f"Robust search: complete; leader {leader['candidate_id']} ({leader['display_name']})",
        flush=True,
    )
    release_cuda_memory()
    return result


def _render_report(result: dict[str, Any], meta: dict[int, dict[str, Any]]) -> str:
    funnel = result["funnel"]
    leader = result["leader"]
    candidate = result["leader_candidate"]
    gw1 = candidate["lineups"]["1"]
    starters = [int(element) for element in gw1["starters"]]
    bench = [int(element) for element in gw1["bench_order"]]
    lines = [
        "# GW1 global robust-search funnel",
        "",
        f"**Built:** {result['created_at']}<br>",
        f"**Status:** {result['decision_status']}<br>",
        f"**Leader:** {leader['candidate_id']} · {leader['display_name']}",
        "",
        "## Verdict",
        "",
        (
            f"The robust funnel recommends **{leader['candidate_id']}**. It was selected after "
            f"{funnel['combined_universe']:,} legal local/global combinations were "
            f"reduced to {funnel['discovery_candidates']:,} discovery candidates, "
            f"{funnel['shortlist']} component-selection candidates and {funnel['finalists']} "
            "deep-holdout finalists."
        ),
        "",
        (
            f"Its central paired edge over {result['runner_up']['candidate_id']} is "
            f"{result['central_paired_comparison']['mean_delta']:+.3f} points "
            f"(95% CI {result['central_paired_comparison']['delta_95ci_low']:+.3f} to "
            f"{result['central_paired_comparison']['delta_95ci_high']:+.3f})."
        ),
        (
            f"The regret optimizer is constrained to candidates within "
            f"{result['model']['central_regret_cap']:.1f} point of the best central forecast, "
            "preventing an extreme stress winner from displacing a materially stronger base squad."
        ),
        "",
        "## Funnel",
        "",
        "| Stage | Candidates/worlds | Purpose |",
        "|---|---:|---|",
        f"| Seed squads | {funnel['seed_squads']:,} | Prior residual and component optima |",
        f"| One-swap legal universe | {funnel['one_swap_universe']:,} | Exhaustive same-position neighbours |",
        f"| Local two-swap universe | {funnel['local_two_swap_universe']:,} | Neighbours of 128 proxy leaders |",
        f"| Distant MILP restarts | {funnel['global_milp_squads']:,} | At least {result['global_challenge']['minimum_seed_distance_required']} swaps from every seed |",
        f"| Evolutionary squads | {funnel['global_evolution_squads']:,} | Legal crossover and mutation |",
        f"| Combined universe | {funnel['combined_universe']:,} | Deduplicated local and global field |",
        f"| Discovery field | {funnel['discovery_candidates']:,} | {funnel['proxy_scenarios']} deterministic assumption views |",
        f"| Fast screen | {funnel['screen_simulations']:,} worlds | Approximate nominal-XI residual screen |",
        f"| Component selection | {funnel['shortlist']:,} × {funnel['selection_simulations']:,} | Exact autosubs and football identities |",
        f"| Deep holdout | {funnel['finalists']:,} × {funnel['holdout_simulations']:,} | Untouched base evaluation |",
        f"| High-goal stress | {funnel['finalists']:,} × {funnel['stress_simulations']:,} | Goal rates ×{result['model']['stress_goal_multiplier']:.2f} |",
        "",
        "## Robust scenarios",
        "",
        "| Scenario | Leader points | Leader regret | Weight |",
        "|---|---:|---:|---:|",
    ]
    for name, weight in SCENARIO_WEIGHTS.items():
        lines.append(
            f"| {name.replace('_', ' ')} | {leader['scenario_values'][name]:.2f} | "
            f"{leader['scenario_regrets'][name]:.2f} | {100 * weight:.1f}% |"
        )
    lines.extend(
        [
            "",
            "## Protected benchmark audit",
            "",
            (
                "These named incumbents were protected from both elimination cuts and received "
                "the same policy solves and untouched holdout worlds as the challenger. A negative "
                "central delta means the robust leader deliberately surrendered a small amount of "
                "central mean to reduce cross-scenario regret."
            ),
            "",
            "| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for benchmark in result["benchmark_comparisons"]:
        paired = benchmark["leader_minus_benchmark"]
        lines.append(
            f"| {benchmark['origin_id']} | {benchmark['robust_rank']} | "
            f"{benchmark['central_mean']:.2f} | {benchmark['robust_regret']:.2f} | "
            f"{paired['mean_delta']:+.2f} | {paired['delta_95ci_low']:+.2f} to "
            f"{paired['delta_95ci_high']:+.2f} |"
        )
    global_challenge = result["global_challenge"]
    lines.extend(
        [
            "",
            "## Global challenger audit",
            "",
            (
                f"The remote search generated {global_challenge['milp_generated']:,} optimizer "
                f"squads and {global_challenge['evolution_generated']:,} legal evolutionary "
                f"squads across {global_challenge['evolution_generations']} generations. "
                f"{global_challenge['discovery_candidates']:,} reached discovery, "
                f"{global_challenge['shortlist_candidates']:,} reached exact component selection "
                f"and {global_challenge['finalists']:,} received the deep holdout."
            ),
            "",
        ]
    )
    if global_challenge["best_finalist"] is not None:
        global_best = global_challenge["best_finalist"]
        paired = global_challenge["leader_minus_best_global"]
        lines.extend(
            [
                (
                    f"Best remote finalist: **{global_best['candidate_id']}** · "
                    f"{global_best['display_name']} · robust regret "
                    f"{global_best['robust_regret']:.3f}."
                ),
                (
                    f"Leader minus remote challenger in the paired central holdout: "
                    f"{paired['mean_delta']:+.3f} points (95% CI "
                    f"{paired['delta_95ci_low']:+.3f} to {paired['delta_95ci_high']:+.3f})."
                ),
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Top ten",
            "",
            "| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, row in enumerate(result["finalist_metrics"][:10], start=1):
        lines.append(
            f"| {rank} | {row['candidate_id']} | {row['gw1_formation']} | "
            f"£{row['gw1_bench_spend']:.1f}m | "
            f"{row['scenario_values']['base_evidence_open']:.2f} | "
            f"{row['weighted_mean_regret']:.2f} | {row['worst_scenario_regret']:.2f} | "
            f"{row['robust_regret']:.2f} |"
        )
    lines.extend(["", "## GW1 starting XI", ""])
    for position in ("GK", "DEF", "MID", "FWD"):
        names = [
            str(meta[element]["player_name"])
            + (" (C)" if element == int(gw1["captain"]) else "")
            + (" (V)" if element == int(gw1["vice_captain"]) else "")
            for element in starters
            if meta[element]["position"] == position
        ]
        lines.append(f"- **{position}:** {', '.join(names)}")
    lines.extend(["", "## Bench", ""])
    for order, element in enumerate(bench, start=1):
        row = meta[element]
        lines.append(
            f"{order}. {row['player_name']} ({row['team_short_name']}, "
            f"£{float(row['market_price']) / 10.0:.1f}m)"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "The robust rank is not simply the highest central mean. It minimizes a declared "
                "regret function across open-transfer, rolled-GW2, fixed-squad, raw-component, "
                "anchored and high-scoring environments. The weights are explicit in the receipt "
                "and should be sensitivity-tested rather than treated as natural constants."
            ),
            "",
            (
                "The discovery screen deliberately uses a cheap nominal-XI approximation. No "
                "candidate is promoted from that approximation: the shortlist is re-evaluated with "
                "exact autosubs and component simulation, followed by an independent deep holdout."
            ),
            "",
            f"**Deadline rule:** {result['deadline_rule']}",
            "",
        ]
    )
    return "\n".join(lines)
