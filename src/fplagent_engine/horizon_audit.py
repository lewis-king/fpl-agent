from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    _blend_scenario_scores,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
    train_goal_model,
)
from .models import CURRENT_FORECAST
from .neighbours import enumerate_legal_one_swaps
from .paths import DECISIONS, MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import (
    BENCHMARK_ORIGINS,
    _candidate_id,
    _distribution_metrics,
    _paired_comparison,
    _policy_variant,
    _zscore,
)
from .rules import load_rules, validate_lineup, validate_squad
from .tournament import (
    _lineup_for_squad,
    _load_rows,
    _score_candidates,
    _solve_static,
)

VERSION = "horizon_audit_v1"
EVENTS = tuple(range(1, 9))
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
SELECTION_PARQUET = RESULT_DIR / "selection-metrics.parquet"
FINAL_PARQUET = RESULT_DIR / "finalist-metrics.parquet"
DECISION_JSON = DECISIONS / "2026-27-gw1-horizon-audit.json"
REPORT = REPORTS / "gw1-horizon-adequacy-audit.md"
GLOBAL_RESULTS = MODEL_DATA / "robust_search_v2_global" / "results.json"
GLOBAL_SHORTLIST = MODEL_DATA / "robust_search_v2_global" / "shortlist.json"

SCENARIO_WEIGHTS = {
    "gw1_3_open_d088": 0.10,
    "gw1_5_open_d088": 0.15,
    "gw1_8_open_d070": 0.10,
    "gw1_8_open_d080": 0.10,
    "gw1_8_open_d088": 0.15,
    "gw1_8_open_d094": 0.10,
    "gw6_8_open_equal": 0.10,
    "gw1_8_fixed_d088": 0.05,
    "gw1_8_roll_gw2_d088": 0.15,
}
CENTRAL_SCENARIO = "gw1_8_open_d088"
CENTRAL_REGRET_CAP = 1.5


def horizon_weights(events: tuple[int, ...], decay: float) -> np.ndarray:
    if not events or not 0.0 < decay <= 1.0:
        raise ValueError("events and decay must define a valid horizon")
    first = min(events)
    return np.asarray([decay ** (event - first) for event in events], dtype=np.float64)


def weighted_totals(
    scores: np.ndarray,
    all_events: tuple[int, ...],
    selected_events: tuple[int, ...],
    decay: float,
) -> np.ndarray:
    offsets = [all_events.index(event) for event in selected_events]
    weights = horizon_weights(selected_events, decay)
    if scores.ndim == 3:
        return np.sum(scores[:, :, offsets] * weights, axis=2)
    if scores.ndim == 2:
        return np.sum(scores[:, offsets] * weights, axis=1)
    raise ValueError("scores must be simulation×event or simulation×candidate×event")


def _candidate_record(
    squad: list[int],
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    origin_ids: list[str],
) -> dict[str, Any]:
    rules = load_rules()
    selected = sorted(map(int, squad))
    lineups = {
        str(event): _lineup_for_squad(selected, event, by_player, rules) for event in EVENTS
    }
    gw1 = lineups["1"]
    bench = list(map(int, gw1["bench_order"]))
    budget = sum(float(meta[element]["market_price"]) for element in selected) / 10.0
    bench_spend = sum(float(meta[element]["market_price"]) for element in bench) / 10.0
    captain = meta[int(gw1["captain"])]["player_name"]
    return {
        "candidate_id": _candidate_id(selected),
        "display_name": f"{gw1['formation']} · {captain} captain · £{bench_spend:.1f}m bench",
        "origin_ids": sorted(set(origin_ids)),
        "selected": selected,
        "lineups": lineups,
        "budget_spent": budget,
        "bank": (rules.budget / 10.0) - budget,
        "gw1_bench_spend": bench_spend,
        "gw1_formation": gw1["formation"],
    }


def _load_incumbent_candidates(
    by_player: dict[int, dict[int, dict]], meta: dict[int, dict]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not GLOBAL_RESULTS.exists() or not GLOBAL_SHORTLIST.exists():
        raise FileNotFoundError("Run the global robust search before the horizon audit")
    result = load_json_artifact(GLOBAL_RESULTS, "global robust-search results")
    require_current_forecast(
        result,
        CURRENT_FORECAST,
        "global robust-search results",
        fields=("artifacts", "forecast_sha256"),
    )
    require_recorded_file(
        result,
        ("artifacts", "global_shortlist_sha256"),
        GLOBAL_SHORTLIST,
        "global robust-search shortlist",
    )
    shortlist_payload = load_json_artifact(GLOBAL_SHORTLIST, "global robust-search shortlist")
    require_current_forecast(
        shortlist_payload, CURRENT_FORECAST, "global robust-search shortlist"
    )
    shortlist = shortlist_payload["candidates"]
    finalist_ids = {row["candidate_id"] for row in result["finalist_metrics"]}
    candidates = [
        _candidate_record(
            list(map(int, candidate["selected"])),
            by_player,
            meta,
            list(map(str, candidate["origin_ids"])),
        )
        for candidate in shortlist
        if candidate["candidate_id"] in finalist_ids
    ]
    if result["leader"]["candidate_id"] not in {row["candidate_id"] for row in candidates}:
        raise RuntimeError("Global robust leader is missing from its recorded shortlist")
    return candidates, result


def _generate_horizon_candidates(
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    incumbents: list[dict[str, Any]],
    count: int,
    seed: int,
) -> list[dict[str, Any]]:
    rules = load_rules()
    rng = np.random.default_rng(seed)
    seen = {tuple(candidate["selected"]) for candidate in incumbents}
    generated: list[dict[str, Any]] = []
    exclusions = [set(candidate["selected"]) for candidate in incumbents]
    decays = (0.65, 0.72, 0.80, 0.88, 0.94, 1.00)
    scales = (0.08, 0.16, 0.28, 0.45, 0.70, 1.00)
    bench_bands = (
        None,
        (None, 185.0),
        (186.0, 200.0),
        (201.0, 220.0),
        (221.0, None),
    )

    def perturbed_scores(scale: float) -> dict[tuple[int, int], float]:
        player_shift = {element: rng.normal(0.0, scale) for element in meta}
        return {
            (element, event): max(
                0.0,
                float(row["expected_points"])
                + player_shift[element]
                + rng.normal(0.0, scale * 0.30),
            )
            for element, event_rows in by_player.items()
            for event, row in event_rows.items()
        }

    attempts = 0
    maximum_attempts = count * 14
    while len(generated) < count and attempts < maximum_attempts:
        decay = decays[attempts % len(decays)]
        scale = scales[(attempts // len(decays)) % len(scales)]
        bench_band = bench_bands[
            (attempts // (len(decays) * len(scales))) % len(bench_bands)
        ]
        try:
            solution = _solve_static(
                by_player,
                meta,
                EVENTS,
                rules,
                score_by_player_event=perturbed_scores(scale),
                excluded_squads=exclusions,
                bench_spend=bench_band,
                horizon_decay=decay,
                bench_weight=0.0,
            )
        except RuntimeError:
            attempts += 1
            continue
        key = tuple(sorted(map(int, solution["selected"])))
        if key not in seen:
            seen.add(key)
            exclusions.append(set(key))
            generated.append(
                _candidate_record(
                    list(key),
                    by_player,
                    meta,
                    [f"horizon-optimizer:d{decay:.2f}:n{scale:.2f}"],
                )
            )
        attempts += 1
    if len(generated) < count:
        raise RuntimeError(f"Only generated {len(generated)} horizon challengers")
    return generated


def _deterministic_horizon_metrics(
    candidate: dict[str, Any],
    by_player: dict[int, dict[int, dict]],
) -> dict[str, float]:
    definitions = {
        "gw1_3_d088": ((1, 2, 3), 0.88),
        "gw1_5_d088": ((1, 2, 3, 4, 5), 0.88),
        "gw1_8_d080": (EVENTS, 0.80),
        "gw1_8_d088": (EVENTS, 0.88),
        "gw1_8_d094": (EVENTS, 0.94),
        "gw6_8_equal": ((6, 7, 8), 1.00),
    }
    output: dict[str, float] = {}
    for name, (events, decay) in definitions.items():
        weights = horizon_weights(events, decay)
        total = 0.0
        for offset, event in enumerate(events):
            lineup = candidate["lineups"][str(event)]
            event_total = sum(
                float(by_player[int(element)][event]["expected_points"])
                for element in lineup["starters"]
            )
            event_total += float(
                by_player[int(lineup["captain"])][event]["expected_points"]
            )
            total += float(weights[offset]) * event_total
        output[name] = total
    return output


def _select_horizon_neighbour_records(
    records: list[dict[str, Any]],
    metrics: list[dict[str, float]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1 or len(records) != len(metrics):
        raise ValueError("Horizon-neighbour selection needs aligned records and a positive limit")
    if not records:
        return []
    names = tuple(metrics[0])
    values = np.asarray(
        [[float(row[name]) for name in names] for row in metrics], dtype=np.float64
    )
    scale = np.maximum(values.std(axis=0), 1e-9)
    aggregate = ((values - values.max(axis=0)) / scale).mean(axis=1)
    mandatory: set[int] = set()
    roots = sorted(
        {
            origin
            for record in records
            for origin in record["origin_ids"]
            if str(origin).startswith("horizon-neighbour:")
        }
    )
    for root in roots:
        eligible = [
            index
            for index, record in enumerate(records)
            if root in set(record["origin_ids"])
        ]
        if eligible:
            mandatory.add(max(eligible, key=lambda index: aggregate[index]))
    if len(mandatory) > limit:
        mandatory = set(
            sorted(mandatory, key=lambda index: aggregate[index], reverse=True)[:limit]
        )
    chosen = set(mandatory)
    per_scenario = max(2, limit // max(1, len(names) * 3))
    for column in range(len(names)):
        chosen.update(
            map(int, np.argsort(-values[:, column], kind="stable")[:per_scenario])
        )
    for index in np.argsort(-aggregate, kind="stable"):
        chosen.add(int(index))
        if len(chosen) >= limit:
            break
    ordered = sorted(
        chosen,
        key=lambda index: (aggregate[index], records[index]["candidate_id"]),
        reverse=True,
    )[:limit]
    return [records[index] for index in ordered]


def _generate_horizon_neighbours(
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    incumbents: list[dict[str, Any]],
    robust_result: dict[str, Any],
    *,
    count: int,
    source_seeds: int,
) -> list[dict[str, Any]]:
    if count == 0:
        return []
    if count < 8 or source_seeds < 1:
        raise ValueError(
            "Horizon-neighbour generation needs at least eight candidates and one source seed"
        )
    incumbent_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in incumbents
    }
    ranked_ids = [
        str(row["candidate_id"])
        for row in robust_result["finalist_metrics"]
        if str(row["candidate_id"]) in incumbent_by_id
    ][:source_seeds]
    if not ranked_ids:
        raise RuntimeError("No robust finalists are available for horizon-neighbour generation")
    incumbent_keys = {tuple(candidate["selected"]) for candidate in incumbents}
    origins_by_squad: dict[tuple[int, ...], set[str]] = {}
    rules = load_rules()
    for candidate_id in ranked_ids:
        seed_candidate = incumbent_by_id[candidate_id]
        for swap in enumerate_legal_one_swaps(seed_candidate["selected"], meta, rules):
            key = tuple(map(int, swap["selected"]))
            if key in incumbent_keys:
                continue
            origins_by_squad.setdefault(key, set()).add(
                f"horizon-neighbour:{candidate_id}"
            )
    records = [
        _candidate_record(list(squad), by_player, meta, sorted(origins))
        for squad, origins in sorted(origins_by_squad.items())
    ]
    metrics = [
        _deterministic_horizon_metrics(candidate, by_player)
        for candidate in records
    ]
    return _select_horizon_neighbour_records(records, metrics, limit=min(count, len(records)))


def _scenario_totals(scores_by_kind: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    opened = scores_by_kind["open"]
    fixed = scores_by_kind["fixed"]
    rolled = scores_by_kind["roll-gw2"]
    return {
        "gw1_3_open_d088": weighted_totals(opened, EVENTS, (1, 2, 3), 0.88),
        "gw1_5_open_d088": weighted_totals(opened, EVENTS, (1, 2, 3, 4, 5), 0.88),
        "gw1_8_open_d070": weighted_totals(opened, EVENTS, EVENTS, 0.70),
        "gw1_8_open_d080": weighted_totals(opened, EVENTS, EVENTS, 0.80),
        "gw1_8_open_d088": weighted_totals(opened, EVENTS, EVENTS, 0.88),
        "gw1_8_open_d094": weighted_totals(opened, EVENTS, EVENTS, 0.94),
        "gw6_8_open_equal": weighted_totals(opened, EVENTS, (6, 7, 8), 1.00),
        "gw1_8_fixed_d088": weighted_totals(fixed, EVENTS, EVENTS, 0.88),
        "gw1_8_roll_gw2_d088": weighted_totals(rolled, EVENTS, EVENTS, 0.88),
    }


def _selection_indices(
    candidates: list[dict[str, Any]],
    evidence_scores: np.ndarray,
    incumbent_id: str,
    limit: int,
) -> tuple[list[int], dict[str, np.ndarray]]:
    fixed = {"fixed": evidence_scores, "open": evidence_scores, "roll-gw2": evidence_scores}
    totals = _scenario_totals(fixed)
    metrics = {name: values.mean(axis=0) for name, values in totals.items()}
    h8_distribution = _distribution_metrics(totals[CENTRAL_SCENARIO])
    aggregate = (
        0.15 * _zscore(metrics["gw1_3_open_d088"])
        + 0.20 * _zscore(metrics["gw1_5_open_d088"])
        + 0.35 * _zscore(metrics[CENTRAL_SCENARIO])
        + 0.15 * _zscore(metrics["gw6_8_open_equal"])
        + 0.15 * _zscore(h8_distribution["cvar10"])
    )
    mandatory = {
        index
        for index, candidate in enumerate(candidates)
        if candidate["candidate_id"] == incumbent_id
        or BENCHMARK_ORIGINS & set(candidate["origin_ids"])
    }
    horizon_indices = [
        index
        for index, candidate in enumerate(candidates)
        if any(
            str(origin).startswith(("horizon-optimizer", "horizon-neighbour"))
            for origin in candidate["origin_ids"]
        )
    ]
    for index in sorted(horizon_indices, key=lambda item: aggregate[item], reverse=True)[:8]:
        mandatory.add(index)
    chosen = set(mandatory)
    for name in SCENARIO_WEIGHTS:
        for index in np.argsort(-metrics[name], kind="stable")[: max(4, limit // 6)]:
            chosen.add(int(index))
    for index in np.argsort(-h8_distribution["cvar10"], kind="stable")[: max(4, limit // 6)]:
        chosen.add(int(index))
    for index in np.argsort(-aggregate, kind="stable"):
        chosen.add(int(index))
        if len(chosen) >= limit:
            break
    remaining = sorted(chosen - mandatory, key=lambda item: aggregate[item], reverse=True)
    selected = [*sorted(mandatory, key=lambda item: aggregate[item], reverse=True)]
    selected.extend(remaining[: max(0, limit - len(selected))])
    metrics["aggregate"] = aggregate
    metrics["h8_cvar10"] = h8_distribution["cvar10"]
    return selected, metrics


def _historical_evidence() -> dict[str, Any]:
    top_picks = PROCESSED / "vaastav" / "top_manager_picks.parquet"
    top_gameweeks = PROCESSED / "vaastav" / "top_manager_gameweeks.parquet"
    genius_receipts = PROCESSED / "fpl_genius" / "receipts.parquet"
    genius_transfers = PROCESSED / "fpl_genius" / "transfers.parquet"
    connection = duckdb.connect()
    try:
        retention = connection.execute(
            f"""
            WITH gw1 AS (
                SELECT team_id, player_id FROM read_parquet('{top_picks}') WHERE gw = 1
            ), later AS (
                SELECT team_id, gw, player_id FROM read_parquet('{top_picks}')
                WHERE gw BETWEEN 2 AND 8
            ), manager_retention AS (
                SELECT l.team_id, l.gw,
                       count(*) FILTER (WHERE g.player_id IS NOT NULL) AS retained
                FROM later l LEFT JOIN gw1 g USING (team_id, player_id)
                GROUP BY l.team_id, l.gw
            )
            SELECT gw, avg(retained) AS mean_retained,
                   quantile_cont(retained, 0.5) AS median_retained,
                   min(retained) AS minimum_retained,
                   max(retained) AS maximum_retained
            FROM manager_retention GROUP BY gw ORDER BY gw
            """
        ).fetchall()
        early_chips = connection.execute(
            f"""
            SELECT gw, chip, count(*) AS managers
            FROM read_parquet('{top_gameweeks}')
            WHERE gw <= 8 AND chip IS NOT NULL
            GROUP BY gw, chip ORDER BY gw, chip
            """
        ).fetchall()
        transfer_activity = connection.execute(
            f"""
            WITH moves AS (
                SELECT event, count(*) AS moves, count(DISTINCT manager_id) AS managers
                FROM read_parquet('{genius_transfers}') WHERE event <= 8 GROUP BY event
            ), rolls AS (
                SELECT event, count(DISTINCT manager_id) AS rollers
                FROM read_parquet('{genius_receipts}')
                WHERE event <= 8 AND decision_type = 'squad_value'
                  AND action_label = 'Rolled the transfer'
                GROUP BY event
            )
            SELECT coalesce(m.event, r.event) AS event, coalesce(m.moves, 0),
                   coalesce(m.managers, 0), coalesce(r.rollers, 0)
            FROM moves m FULL JOIN rolls r USING (event) ORDER BY event
            """
        ).fetchall()
    finally:
        connection.close()
    return {
        "vaastav_2019_20_top10_retention": [
            {
                "event": int(event),
                "mean_retained": float(mean),
                "median_retained": float(median),
                "minimum_retained": int(minimum),
                "maximum_retained": int(maximum),
            }
            for event, mean, median, minimum, maximum in retention
        ],
        "vaastav_2019_20_early_chips": [
            {"event": int(event), "chip": str(chip), "managers": int(managers)}
            for event, chip, managers in early_chips
        ],
        "fpl_genius_2025_26_top100_activity": [
            {
                "event": int(event),
                "transfer_rows": int(moves),
                "managers_making_transfers": int(managers),
                "managers_rolling": int(rollers),
            }
            for event, moves, managers, rollers in transfer_activity
        ],
        "caveat": (
            "The 2019/20 cohort contains only ten elite managers and unusually early wildcard use; "
            "the 2025/26 top-100 trail is richer but transfer rows include wildcard restructures. "
            "These data inform decay and adaptability, not a causal optimal horizon."
        ),
    }


def run_horizon_audit(
    *,
    horizon_candidates: int = 128,
    horizon_neighbours: int = 32,
    horizon_neighbour_seeds: int = 8,
    selection_simulations: int = 5_000,
    finalists: int = 48,
    holdout_simulations: int = 25_000,
    candidate_seed: int = 20260807,
    selection_seed: int = 20260808,
    holdout_seed: int = 20260809,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if horizon_candidates < 32 or selection_simulations < 1_000:
        raise ValueError("horizon audit needs at least 32 challengers and 1,000 selection worlds")
    if horizon_neighbours != 0 and horizon_neighbours < 8:
        raise ValueError("horizon neighbours must be zero or at least eight")
    if horizon_neighbour_seeds < 1:
        raise ValueError("horizon neighbour seeds must be positive")
    if finalists < 16 or holdout_simulations < 5_000:
        raise ValueError("horizon audit needs at least 16 finalists and 5,000 holdout worlds")
    if len({candidate_seed, selection_seed, holdout_seed}) != 3:
        raise ValueError("horizon audit seeds must be distinct")
    ensure_engine_layout()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    print("Horizon audit: loading GW1-8 forecasts and five-week finalists", flush=True)
    rows, loaded = _load_rows(EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    incumbents, global_result = _load_incumbent_candidates(by_player, meta)
    generated = _generate_horizon_candidates(
        by_player, meta, incumbents, horizon_candidates, candidate_seed
    )
    print(
        f"Horizon audit: generated {len(generated)} GW1-8-specific challengers",
        flush=True,
    )
    neighbours = _generate_horizon_neighbours(
        by_player,
        meta,
        incumbents,
        global_result,
        count=horizon_neighbours,
        source_seeds=horizon_neighbour_seeds,
    )
    print(
        f"Horizon audit: retained {len(neighbours)} protected legal neighbours from "
        f"the top {horizon_neighbour_seeds} robust seeds",
        flush=True,
    )
    candidates_by_id: dict[str, dict[str, Any]] = {}
    for candidate in [*incumbents, *generated, *neighbours]:
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in candidates_by_id:
            candidates_by_id[candidate_id]["origin_ids"] = sorted(
                set(candidates_by_id[candidate_id]["origin_ids"])
                | set(candidate["origin_ids"])
            )
        else:
            candidates_by_id[candidate_id] = candidate
    candidates = list(candidates_by_id.values())
    rules = load_rules()
    for candidate in candidates:
        squad_rows = [meta[element] for element in candidate["selected"]]
        validate_squad(squad_rows, rules)
        for event in EVENTS:
            lineup = candidate["lineups"][str(event)]
            validate_lineup(
                squad_rows,
                lineup["starters"],
                lineup["bench_order"],
                lineup["captain"],
                lineup["vice_captain"],
                rules,
            )

    train_goal_model(force=False, seed=selection_seed)
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, EVENTS)
    empirical = calibrate_empirical_components()
    backtest = json.loads(COMPONENT_BACKTEST_METRICS.read_text(encoding="utf-8"))
    raw_weight = float(backtest["blend_selection"]["selected_raw_weight"])
    (
        player_ids,
        selection_raw,
        selection_anchored,
        selection_played,
        _,
        selection_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        EVENTS,
        goal_rates,
        empirical,
        selection_simulations,
        selection_seed,
    )
    raw_scores = _score_candidates(
        candidates, player_ids, EVENTS, selection_raw, selection_played, meta
    )
    anchored_scores = _score_candidates(
        candidates, player_ids, EVENTS, selection_anchored, selection_played, meta
    )
    evidence_scores = _blend_scenario_scores(raw_scores, anchored_scores, raw_weight)
    selected_indices, selection_metrics = _selection_indices(
        candidates,
        evidence_scores,
        global_result["leader"]["candidate_id"],
        min(finalists, len(candidates)),
    )
    selection_rows = [
        {
            "candidate_id": candidate["candidate_id"],
            "origin_ids": candidate["origin_ids"],
            "gw1_formation": candidate["gw1_formation"],
            "gw1_bench_spend": candidate["gw1_bench_spend"],
            **{
                name: float(values[index])
                for name, values in selection_metrics.items()
            },
        }
        for index, candidate in enumerate(candidates)
    ]
    pq.write_table(pa.Table.from_pylist(selection_rows), SELECTION_PARQUET, compression="zstd")
    finalist_candidates = [candidates[index] for index in selected_indices]
    print(
        f"Horizon audit: exact selection retained {len(finalist_candidates)} finalists",
        flush=True,
    )

    variants = []
    for index, candidate in enumerate(finalist_candidates, start=1):
        for kind in ("fixed", "open", "roll-gw2"):
            variants.append(_policy_variant(candidate, rows, kind, EVENTS))
        if index % 4 == 0 or index == len(finalist_candidates):
            print(
                f"Horizon audit: solved eight-week policies for {index}/"
                f"{len(finalist_candidates)} finalists",
                flush=True,
            )
    (
        holdout_player_ids,
        holdout_raw,
        holdout_anchored,
        holdout_played,
        _,
        holdout_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        EVENTS,
        goal_rates,
        empirical,
        holdout_simulations,
        holdout_seed,
    )
    variant_raw_scores = _score_candidates(
        variants, holdout_player_ids, EVENTS, holdout_raw, holdout_played, meta
    )
    variant_anchored_scores = _score_candidates(
        variants, holdout_player_ids, EVENTS, holdout_anchored, holdout_played, meta
    )
    variant_evidence_scores = _blend_scenario_scores(
        variant_raw_scores, variant_anchored_scores, raw_weight
    )
    print("Horizon audit: untouched eight-week holdout complete", flush=True)
    variant_index = {
        (variant["root_candidate_id"], variant["variant_kind"]): index
        for index, variant in enumerate(variants)
    }
    scenario_values: dict[str, dict[str, float]] = {}
    scenario_paths: dict[str, dict[str, np.ndarray]] = {}
    for candidate in finalist_candidates:
        candidate_id = candidate["candidate_id"]
        scores_by_kind = {
            kind: variant_evidence_scores[:, variant_index[(candidate_id, kind)], :]
            for kind in ("fixed", "open", "roll-gw2")
        }
        totals = _scenario_totals(scores_by_kind)
        scenario_paths[candidate_id] = totals
        scenario_values[candidate_id] = {
            name: float(values.mean()) for name, values in totals.items()
        }
    scenario_bests = {
        name: max(values[name] for values in scenario_values.values())
        for name in SCENARIO_WEIGHTS
    }
    finalist_by_id = {candidate["candidate_id"]: candidate for candidate in finalist_candidates}
    rows_out = []
    for candidate_id, values in scenario_values.items():
        regrets = {
            name: float(scenario_bests[name] - values[name]) for name in SCENARIO_WEIGHTS
        }
        weighted_regret = sum(
            SCENARIO_WEIGHTS[name] * regrets[name] for name in SCENARIO_WEIGHTS
        )
        worst_regret = max(regrets.values())
        central = scenario_paths[candidate_id][CENTRAL_SCENARIO]
        candidate = finalist_by_id[candidate_id]
        rows_out.append(
            {
                "candidate_id": candidate_id,
                "display_name": candidate["display_name"],
                "origin_ids": candidate["origin_ids"],
                "gw1_formation": candidate["gw1_formation"],
                "gw1_bench_spend": candidate["gw1_bench_spend"],
                "scenario_values": values,
                "scenario_regrets": regrets,
                "weighted_mean_regret": weighted_regret,
                "worst_scenario_regret": worst_regret,
                "robust_regret": 0.80 * weighted_regret + 0.20 * worst_regret,
                "central_p10": float(np.quantile(central, 0.10)),
                "central_p90": float(np.quantile(central, 0.90)),
            }
        )
    rows_out.sort(
        key=lambda row: (
            row["scenario_regrets"][CENTRAL_SCENARIO] > CENTRAL_REGRET_CAP,
            row["robust_regret"],
            -row["scenario_values"][CENTRAL_SCENARIO],
        )
    )
    leader = rows_out[0]
    incumbent = next(
        row for row in rows_out if row["candidate_id"] == global_result["leader"]["candidate_id"]
    )
    comparison = _paired_comparison(
        scenario_paths[leader["candidate_id"]][CENTRAL_SCENARIO],
        scenario_paths[incumbent["candidate_id"]][CENTRAL_SCENARIO],
    )
    leader_candidate = finalist_by_id[leader["candidate_id"]]
    leader_open = variants[variant_index[(leader["candidate_id"], "open")]]
    incumbent_open = variants[variant_index[(incumbent["candidate_id"], "open")]]
    same = leader["candidate_id"] == incumbent["candidate_id"]
    materially_better = comparison["delta_95ci_low"] > 0.0
    verdict = (
        "five_week_leader_confirmed"
        if same
        else "long_horizon_challenger_promoted"
        if materially_better
        else "horizon_sensitive_no_clear_replacement"
    )
    historical = _historical_evidence()
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "events": list(EVENTS),
        "scenario_weights": SCENARIO_WEIGHTS,
        "central_scenario": CENTRAL_SCENARIO,
        "central_regret_cap": CENTRAL_REGRET_CAP,
        "seeds": {
            "candidate": candidate_seed,
            "selection": selection_seed,
            "holdout": holdout_seed,
        },
        "funnel": {
            "five_week_incumbent_finalists": len(incumbents),
            "horizon_specific_candidates": len(generated),
            "protected_horizon_neighbours": len(neighbours),
            "horizon_neighbour_source_seeds": horizon_neighbour_seeds,
            "combined_candidates": len(candidates),
            "selection_simulations": selection_simulations,
            "deep_finalists": len(finalist_candidates),
            "holdout_simulations": holdout_simulations,
            "policy_variants_per_finalist": 3,
        },
        "leader": leader,
        "incumbent": incumbent,
        "leader_candidate": leader_candidate,
        "leader_transfer_policy": leader_open.get("transfer_policy", {}),
        "incumbent_transfer_policy": incumbent_open.get("transfer_policy", {}),
        "leader_minus_incumbent_central": comparison,
        "verdict": verdict,
        "historical_evidence": historical,
        "finalist_metrics": rows_out,
        "goal_rate_diagnostics": goal_diagnostics,
        "selection_diagnostics": selection_diagnostics,
        "holdout_diagnostics": holdout_diagnostics,
        "model": {
            "evidence_raw_weight": raw_weight,
            "score_definition": (
                "Exact component simulation with autosubs and captaincy; scenario-specific "
                "horizon decay is applied after event scoring."
            ),
        },
        "deadline_rule": (
            "Rerun after the final pre-GW1 forecast refresh. Do not promote a horizon challenger "
            "unless its paired eight-week interval excludes zero and it remains within the "
            "declared central-regret cap."
        ),
        "artifacts": {
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
            "robust_results_sha256": sha256_file(GLOBAL_RESULTS),
            "global_shortlist_sha256": sha256_file(GLOBAL_SHORTLIST),
        },
    }
    pq.write_table(pa.Table.from_pylist(rows_out), FINAL_PARQUET, compression="zstd")
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DECISION_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(result, meta), encoding="utf-8")
    print(
        f"Horizon audit: complete; {verdict}; leader {leader['candidate_id']}",
        flush=True,
    )
    return result


def _render_report(result: dict[str, Any], meta: dict[int, dict]) -> str:
    leader = result["leader"]
    incumbent = result["incumbent"]
    comparison = result["leader_minus_incumbent_central"]
    historical = result["historical_evidence"]
    lines = [
        "# GW1 horizon-adequacy audit",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Verdict:** {result['verdict']}  ",
        f"**Leader:** {leader['candidate_id']} · {leader['display_name']}",
        "",
        (
            "**Scope note:** this is the horizon-family verdict, not the final cross-model decision. "
            "See `reports/gw1-synthesized-decision.md` for the synthesis with scoring-environment "
            "and component-model stress."
        ),
        "",
        "## Answer",
        "",
        (
            "This audit does not assume that five equal gameweeks are the correct outset. It "
            "re-simulates GW1–8 and evaluates short, medium, decayed long, late-fixture, fixed-squad "
            "and forced-GW2-bank views."
        ),
        "",
        (
            f"The eight-week leader is **{leader['candidate_id']}**. Against the five-week incumbent "
            f"**{incumbent['candidate_id']}**, its paired central delta is "
            f"{comparison['mean_delta']:+.3f} points (95% CI "
            f"{comparison['delta_95ci_low']:+.3f} to {comparison['delta_95ci_high']:+.3f})."
        ),
        "",
        "## Evaluation funnel",
        "",
        "| Stage | Count |",
        "|---|---:|",
        f"| Five-week finalists carried forward | {result['funnel']['five_week_incumbent_finalists']} |",
        f"| New horizon-specific squads | {result['funnel']['horizon_specific_candidates']} |",
        f"| Protected legal neighbours | {result['funnel']['protected_horizon_neighbours']} |",
        f"| Selection worlds | {result['funnel']['selection_simulations']:,} |",
        f"| Deep finalists | {result['funnel']['deep_finalists']} |",
        f"| Eight-week holdout worlds | {result['funnel']['holdout_simulations']:,} |",
        "",
        "## Scenario comparison",
        "",
        "| Scenario | Leader | Incumbent | Leader regret | Weight |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, weight in SCENARIO_WEIGHTS.items():
        lines.append(
            f"| {name.replace('_', ' ')} | {leader['scenario_values'][name]:.2f} | "
            f"{incumbent['scenario_values'][name]:.2f} | "
            f"{leader['scenario_regrets'][name]:.2f} | {weight:.0%} |"
        )
    lines.extend(
        [
            "",
            "## What strong managers historically did",
            "",
            (
                "The public 2019/20 top-ten squads retained the following number of their original "
                "15 players. Early wildcard use is reported separately because it explains much of "
                "the sharp drop."
            ),
            "",
            "| GW | Mean retained | Median | Range |",
            "|---:|---:|---:|---:|",
        ]
    )
    for row in historical["vaastav_2019_20_top10_retention"]:
        lines.append(
            f"| {row['event']} | {row['mean_retained']:.1f} | "
            f"{row['median_retained']:.1f} | {row['minimum_retained']}–{row['maximum_retained']} |"
        )
    chip_text = ", ".join(
        f"GW{row['event']} {row['chip']} ×{row['managers']}"
        for row in historical["vaastav_2019_20_early_chips"]
    )
    lines.extend(
        [
            "",
            f"Early chips in that cohort: {chip_text}.",
            "",
            (
                "The 2025/26 top-100 trail shows that 61 managers rolled in GW2, while only 22 did "
                "so in GW3 and 19 in GW4. Strong managers therefore preserved optionality initially "
                "but adapted quickly when evidence arrived."
            ),
            "",
            f"**Evidence caveat:** {historical['caveat']}",
            "",
            "## GW1 team",
            "",
        ]
    )
    gw1 = result["leader_candidate"]["lineups"]["1"]
    for position in ("GK", "DEF", "MID", "FWD"):
        names = [
            str(meta[element]["player_name"])
            + (" (C)" if element == int(gw1["captain"]) else "")
            + (" (V)" if element == int(gw1["vice_captain"]) else "")
            for element in gw1["starters"]
            if meta[element]["position"] == position
        ]
        lines.append(f"- **{position}:** {', '.join(names)}")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "GW6–8 are included, but discounted because current information about minutes, "
                "form and injuries is materially weaker. The separate equal-weight GW6–8 scenario "
                "prevents an easy opening run from hiding a poor late fixture block. Fixed and "
                "forced-bank scenarios prevent the audit from assuming perfect transfer execution."
            ),
            "",
            f"**Deadline rule:** {result['deadline_rule']}",
            "",
        ]
    )
    return "\n".join(lines)
