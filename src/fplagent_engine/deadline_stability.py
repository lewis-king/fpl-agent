from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .artifact_lineage import load_json_artifact, require_current_forecast
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    _blend_scenario_scores,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
)
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .horizon_audit import (
    EVENTS as EIGHT_EVENTS,
)
from .horizon_audit import (
    SCENARIO_WEIGHTS as HORIZON_SCENARIO_WEIGHTS,
)
from .horizon_audit import _candidate_record, _scenario_totals
from .models import CURRENT_FORECAST
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import (
    RESULTS_JSON as ROBUST_RESULTS,
)
from .robust_search import (
    SCENARIO_WEIGHTS as ROBUST_SCENARIO_WEIGHTS,
)
from .robust_search import (
    SHORTLIST_JSON as ROBUST_SHORTLIST,
)
from .robust_search import parallel_policy_variants
from .tournament import DEFAULT_EVENTS as FIVE_EVENTS
from .tournament import _load_rows, _score_candidates

VERSION = "deadline_stability_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "gw1-deadline-stability.md"
DEFAULT_SEEDS = (20260911, 20260912, 20260913)
DEFAULT_HORIZON_WEIGHTS = (0.30, 0.40, 0.50, 0.60, 0.70)
DEFAULT_WORST_WEIGHTS = (0.10, 0.20, 0.30)
PRODUCTION_HORIZON_WEIGHT = 0.50
PRODUCTION_WORST_WEIGHT = 0.20
GRID_PRACTICAL_REGRET = 0.25


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _family_regrets(
    scenario_values: dict[str, dict[str, float]],
    scenario_weights: dict[str, float],
    *,
    mean_weight: float,
) -> dict[str, float]:
    bests = {
        name: max(values[name] for values in scenario_values.values()) for name in scenario_weights
    }
    output: dict[str, float] = {}
    for candidate_id, values in scenario_values.items():
        regrets = {name: bests[name] - values[name] for name in scenario_weights}
        weighted = sum(scenario_weights[name] * regrets[name] for name in scenario_weights)
        output[candidate_id] = float(
            mean_weight * weighted + (1.0 - mean_weight) * max(regrets.values())
        )
    return output


def synthesis_ranking(
    robust_regrets: dict[str, float],
    horizon_regrets: dict[str, float],
    *,
    horizon_weight: float,
    worst_weight: float,
) -> list[dict[str, Any]]:
    if not 0.0 <= horizon_weight <= 1.0 or not 0.0 <= worst_weight <= 1.0:
        raise ValueError("stability synthesis weights must be in [0, 1]")
    common = sorted(set(robust_regrets) & set(horizon_regrets))
    if not common:
        raise ValueError("stability synthesis has no common candidates")
    rows = []
    for candidate_id in common:
        robust = float(robust_regrets[candidate_id])
        horizon = float(horizon_regrets[candidate_id])
        weighted = (1.0 - horizon_weight) * robust + horizon_weight * horizon
        rows.append(
            {
                "candidate_id": candidate_id,
                "robust_regret": robust,
                "horizon_regret": horizon,
                "synthesis_regret": (1.0 - worst_weight) * weighted
                + worst_weight * max(robust, horizon),
            }
        )
    rows.sort(key=lambda row: (row["synthesis_regret"], row["candidate_id"]))
    leader = float(rows[0]["synthesis_regret"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["regret_to_leader"] = float(row["synthesis_regret"] - leader)
    return rows


def evaluate_stability(
    *,
    decision_candidate_id: str,
    candidate_count: int,
    seed_results: list[dict[str, Any]],
    grid_practical_regret: float = GRID_PRACTICAL_REGRET,
) -> dict[str, Any]:
    production_winners = [str(row["production"][0]["candidate_id"]) for row in seed_results]
    grid_rows = [grid for row in seed_results for grid in row["weight_grid"]]
    checks = {
        "at_least_three_independent_seeds": len({int(row["seed"]) for row in seed_results}) >= 3,
        "candidate_pool_at_least_five": candidate_count >= 5,
        "selected_candidate_wins_every_production_seed": bool(seed_results)
        and all(winner == decision_candidate_id for winner in production_winners),
        "selected_candidate_within_every_weight_grid_tolerance": bool(grid_rows)
        and all(
            float(row["selected_regret_to_leader"]) <= grid_practical_regret for row in grid_rows
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "production_winner_counts": dict(sorted(Counter(production_winners).items())),
        "weight_grid_winner_counts": dict(
            sorted(Counter(str(row["winner"]) for row in grid_rows).items())
        ),
        "maximum_selected_grid_regret": max(
            (float(row["selected_regret_to_leader"]) for row in grid_rows), default=None
        ),
        "grid_practical_regret": grid_practical_regret,
    }


def _candidate_scenarios(
    candidates: list[dict[str, Any]],
    variants: list[dict[str, Any]],
    evidence_scores: np.ndarray,
    raw_scores: np.ndarray,
    anchored_scores: np.ndarray,
    stress_scores: np.ndarray,
) -> dict[str, dict[str, float]]:
    index = {
        (str(variant["root_candidate_id"]), str(variant["variant_kind"])): offset
        for offset, variant in enumerate(variants)
    }
    values: dict[str, dict[str, float]] = {}
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        fixed = index[(candidate_id, "fixed")]
        opened = index[(candidate_id, "open")]
        rolled = index[(candidate_id, "roll-gw2")]
        values[candidate_id] = {
            "base_evidence_open": float(evidence_scores[:, opened, :].sum(axis=1).mean()),
            "base_evidence_roll_gw2": float(evidence_scores[:, rolled, :].sum(axis=1).mean()),
            "base_evidence_fixed": float(evidence_scores[:, fixed, :].sum(axis=1).mean()),
            "base_raw_open": float(raw_scores[:, opened, :].sum(axis=1).mean()),
            "base_anchored_open": float(anchored_scores[:, opened, :].sum(axis=1).mean()),
            "high_goal_open": float(stress_scores[:, opened, :].sum(axis=1).mean()),
            "high_goal_roll_gw2": float(stress_scores[:, rolled, :].sum(axis=1).mean()),
            "high_goal_fixed": float(stress_scores[:, fixed, :].sum(axis=1).mean()),
        }
    return values


def _horizon_scenarios(
    candidates: list[dict[str, Any]],
    variants: list[dict[str, Any]],
    evidence_scores: np.ndarray,
) -> dict[str, dict[str, float]]:
    index = {
        (str(variant["root_candidate_id"]), str(variant["variant_kind"])): offset
        for offset, variant in enumerate(variants)
    }
    values: dict[str, dict[str, float]] = {}
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        totals = _scenario_totals(
            {
                kind: evidence_scores[:, index[(candidate_id, kind)], :]
                for kind in ("fixed", "open", "roll-gw2")
            }
        )
        values[candidate_id] = {name: float(paths.mean()) for name, paths in totals.items()}
    return values


def run_deadline_stability_audit(
    *,
    simulations_per_seed: int = 25_000,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    candidate_count: int = 5,
    stress_goal_multiplier: float = 1.15,
    horizon_weights: tuple[float, ...] = DEFAULT_HORIZON_WEIGHTS,
    worst_weights: tuple[float, ...] = DEFAULT_WORST_WEIGHTS,
    decision_path: Path = SYNTHESIZED_DECISION,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if simulations_per_seed < 5_000:
        raise ValueError("deadline stability needs at least 5,000 simulations per seed")
    if len(set(seeds)) < 3:
        raise ValueError("deadline stability needs at least three distinct seeds")
    if candidate_count < 5:
        raise ValueError("deadline stability needs at least five leading candidates")
    ensure_engine_layout()
    decision = load_json_artifact(decision_path, "synthesized GW1 decision")
    robust = load_json_artifact(ROBUST_RESULTS, "global robust search")
    forecast_sha = require_current_forecast(
        robust,
        CURRENT_FORECAST,
        "global robust search",
        fields=("artifacts", "forecast_sha256"),
    )
    shortlist = load_json_artifact(ROBUST_SHORTLIST, "global robust shortlist")
    if shortlist.get("forecast_sha256") != forecast_sha:
        raise ValueError("global robust shortlist does not match the current forecast")
    decision_candidate_id = str(decision["decision"]["candidate_id"])
    ranked_ids = [
        str(row["candidate_id"])
        for row in decision.get("ranking") or []
        if row.get("publication_eligible") is True
    ][:candidate_count]
    if decision_candidate_id not in ranked_ids:
        ranked_ids.insert(0, decision_candidate_id)
        ranked_ids = ranked_ids[:candidate_count]
    shortlist_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in shortlist["candidates"]
    }
    missing = [candidate_id for candidate_id in ranked_ids if candidate_id not in shortlist_by_id]
    if missing:
        raise ValueError(
            "stability candidates are absent from the robust shortlist: " + ", ".join(missing)
        )

    rows_five, _ = _load_rows(FIVE_EVENTS)
    rows_eight, loaded = _load_rows(EIGHT_EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    candidates = [
        _candidate_record(
            list(map(int, shortlist_by_id[candidate_id]["selected"])),
            by_player,
            meta,
            list(shortlist_by_id[candidate_id].get("origin_ids") or []),
        )
        for candidate_id in ranked_ids
    ]
    print("Deadline stability: solving five/eight-week policies for leading squads", flush=True)
    five_variants = parallel_policy_variants(
        candidates,
        rows_five,
        FIVE_EVENTS,
        progress_label="Deadline stability five-week policy solve",
    )
    eight_variants = parallel_policy_variants(
        candidates,
        rows_eight,
        EIGHT_EVENTS,
        progress_label="Deadline stability eight-week policy solve",
    )
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, EIGHT_EVENTS)
    empirical = calibrate_empirical_components()
    component_backtest = load_json_artifact(
        COMPONENT_BACKTEST_METRICS, "component backtest metrics"
    )
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    seed_results: list[dict[str, Any]] = []
    for number, seed in enumerate(seeds, start=1):
        print(
            f"Deadline stability: simulating independent seed {number}/{len(seeds)} "
            f"({simulations_per_seed:,} worlds)",
            flush=True,
        )
        player_ids, raw, anchored, played, _, _ = simulate_component_outcomes(
            by_player,
            EIGHT_EVENTS,
            goal_rates,
            empirical,
            simulations_per_seed,
            int(seed),
        )
        five_raw = _score_candidates(
            five_variants,
            player_ids,
            FIVE_EVENTS,
            raw[:, : len(FIVE_EVENTS)],
            played[:, : len(FIVE_EVENTS)],
            meta,
        )
        five_anchored = _score_candidates(
            five_variants,
            player_ids,
            FIVE_EVENTS,
            anchored[:, : len(FIVE_EVENTS)],
            played[:, : len(FIVE_EVENTS)],
            meta,
        )
        five_evidence = _blend_scenario_scores(five_raw, five_anchored, raw_weight)
        stress_rates = {
            key: (home * stress_goal_multiplier, away * stress_goal_multiplier)
            for key, (home, away) in goal_rates.items()
            if int(key[0]) in FIVE_EVENTS
        }
        stress_ids, stress_raw, _, stress_played, _, _ = simulate_component_outcomes(
            by_player,
            FIVE_EVENTS,
            stress_rates,
            empirical,
            simulations_per_seed,
            int(seed) + 100_000,
        )
        if stress_ids != player_ids:
            raise RuntimeError("base and stress stability player orders differ")
        stress_scores = _score_candidates(
            five_variants,
            stress_ids,
            FIVE_EVENTS,
            stress_raw,
            stress_played,
            meta,
        )
        robust_values = _candidate_scenarios(
            candidates,
            five_variants,
            five_evidence,
            five_raw,
            five_anchored,
            stress_scores,
        )
        robust_regrets = _family_regrets(robust_values, ROBUST_SCENARIO_WEIGHTS, mean_weight=0.75)
        eight_raw = _score_candidates(eight_variants, player_ids, EIGHT_EVENTS, raw, played, meta)
        eight_anchored = _score_candidates(
            eight_variants, player_ids, EIGHT_EVENTS, anchored, played, meta
        )
        eight_evidence = _blend_scenario_scores(eight_raw, eight_anchored, raw_weight)
        horizon_values = _horizon_scenarios(candidates, eight_variants, eight_evidence)
        horizon_regrets = _family_regrets(
            horizon_values, HORIZON_SCENARIO_WEIGHTS, mean_weight=0.80
        )
        production = synthesis_ranking(
            robust_regrets,
            horizon_regrets,
            horizon_weight=PRODUCTION_HORIZON_WEIGHT,
            worst_weight=PRODUCTION_WORST_WEIGHT,
        )
        grid = []
        for horizon_weight in horizon_weights:
            for worst_weight in worst_weights:
                ranking = synthesis_ranking(
                    robust_regrets,
                    horizon_regrets,
                    horizon_weight=horizon_weight,
                    worst_weight=worst_weight,
                )
                selected = next(
                    row for row in ranking if row["candidate_id"] == decision_candidate_id
                )
                grid.append(
                    {
                        "horizon_weight": horizon_weight,
                        "worst_weight": worst_weight,
                        "winner": ranking[0]["candidate_id"],
                        "selected_rank": selected["rank"],
                        "selected_regret_to_leader": selected["regret_to_leader"],
                    }
                )
        seed_results.append(
            {
                "seed": int(seed),
                "production": production,
                "weight_grid": grid,
            }
        )

    gate = evaluate_stability(
        decision_candidate_id=decision_candidate_id,
        candidate_count=len(candidates),
        seed_results=seed_results,
    )
    names = {int(element): str(row["player_name"]) for element, row in meta.items()}
    candidate_squads = {
        str(candidate["candidate_id"]): {
            "selected": list(map(int, candidate["selected"])),
            "players": [names[int(element)] for element in candidate["selected"]],
        }
        for candidate in candidates
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "STABLE" if gate["passed"] else "BLOCKED_UNSTABLE",
        "publishable": bool(gate["passed"]),
        "decision_candidate_id": decision_candidate_id,
        "production_policy": {
            "horizon_weight": PRODUCTION_HORIZON_WEIGHT,
            "worst_weight": PRODUCTION_WORST_WEIGHT,
        },
        "search": {
            "candidate_count": len(candidates),
            "simulations_per_seed": simulations_per_seed,
            "seeds": list(map(int, seeds)),
            "weight_grid_points_per_seed": len(horizon_weights) * len(worst_weights),
            "horizon_weights": list(horizon_weights),
            "worst_weights": list(worst_weights),
        },
        "gate": gate,
        "candidate_squads": candidate_squads,
        "seed_results": seed_results,
        "diagnostics": {"goal_rates": goal_diagnostics, "component_raw_weight": raw_weight},
        "lineage": {
            "decision_sha256": sha256_file(decision_path),
            "forecast_sha256": forecast_sha,
            "robust_results_sha256": sha256_file(ROBUST_RESULTS),
            "robust_shortlist_sha256": sha256_file(ROBUST_SHORTLIST),
        },
        "decision_rule": (
            "The published squad must win the production objective on every independent seed. "
            "Across the bounded objective-weight grid it may lose only while remaining within "
            f"{GRID_PRACTICAL_REGRET:.2f} synthesis-regret points of the seed-specific leader."
        ),
    }
    _atomic_text(results_path, json.dumps(result, indent=2, sort_keys=True) + "\n")
    _atomic_text(report_path, _render_report(result))
    return result


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# GW1 multi-seed decision stability",
        "",
        f"Verdict: **{result['verdict']}**.",
        "",
        (
            f"The leading {result['search']['candidate_count']} legal squads were rerun on "
            f"{len(result['search']['seeds'])} independent seeds with "
            f"{result['search']['simulations_per_seed']:,} worlds per seed."
        ),
        "",
        "## Production policy",
        "",
        "| Seed | Winner | Selected rank | Selected regret to winner |",
        "| ---: | --- | ---: | ---: |",
    ]
    selected_id = str(result["decision_candidate_id"])
    for seed in result["seed_results"]:
        selected = next(row for row in seed["production"] if row["candidate_id"] == selected_id)
        lines.append(
            f"| {seed['seed']} | `{seed['production'][0]['candidate_id']}` | "
            f"{selected['rank']} | {selected['regret_to_leader']:.3f} |"
        )
    lines.extend(["", "## Gate", ""])
    for name, passed in result["gate"]["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend(
        [
            "",
            (
                "Maximum selected regret across the bounded weight grid: "
                f"{float(result['gate']['maximum_selected_grid_regret'] or 0):.3f}."
            ),
            "",
            result["decision_rule"],
            "",
        ]
    )
    return "\n".join(lines)
