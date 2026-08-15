from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .appearance_role_challenger import ROLE_FEATURES, build_role_feature_table
from .artifact_lineage import load_json_artifact
from .decision_synthesis import DECISION_JSON as SYNTHESIS_RESULTS
from .features import CURRENT_FEATURES, TRAINING_FEATURES
from .horizon_audit import (
    GLOBAL_RESULTS,
    GLOBAL_SHORTLIST,
    _candidate_record,
    weighted_totals,
)
from .horizon_audit import (
    RESULTS_JSON as HORIZON_RESULTS,
)
from .lead_time_challenger import (
    MODEL_FEATURES,
)
from .lead_time_challenger import (
    MODEL_FILE as LEAD_MODEL,
)
from .lead_time_challenger import (
    RESULTS_JSON as LEAD_RESULTS,
)
from .models import CURRENT_FORECAST
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .preseason_role_scenario import (
    ROLE_EVIDENCE,
    SCENARIOS,
    apply_conditional_dnp_stress,
    derive_role_flags,
    scenario_player_factors,
)
from .robust_search import _policy_variant
from .rules import load_rules
from .tournament import (
    _score_candidates,
    _simulate_player_outcomes,
    _solve_static,
    calibrate_residuals,
)

VERSION = "adaptive_preseason_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
CURRENT_LEAD_FORECAST = OUTPUT_DIR / "current-lead-shadow.parquet"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "adaptive-preseason-lead-stress.md"

EVENTS = tuple(range(1, 9))
SIMULATIONS = 10_000
SEED = 20260825
SCENARIO_WEIGHTS = {
    "base_open": 0.30,
    "lead_open": 0.25,
    "base_fixed": 0.10,
    "lead_fixed": 0.10,
    "moderate_role_base_open": 0.25,
}


def _number(value: Any) -> float:
    return np.nan if value is None else float(value)


def _forecast_grid(
    rows: list[dict[str, Any]],
) -> tuple[dict[int, dict[int, dict[str, Any]]], dict[int, dict[str, Any]]]:
    by_player: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    meta = {}
    for row in rows:
        element = int(row["element"])
        event = int(row["event_number"])
        if event in EVENTS:
            by_player[element][event] = row
            meta[element] = row
    incomplete = {
        element: sorted(set(EVENTS) - set(event_rows))
        for element, event_rows in by_player.items()
        if set(event_rows) != set(EVENTS)
    }
    if incomplete:
        raise ValueError(f"Adaptive forecast grid is incomplete: {incomplete}")
    return dict(by_player), meta


def _latest_role_by_player_code() -> dict[int, dict[str, Any]]:
    features = pq.read_table(TRAINING_FEATURES).to_pylist()
    role_by_id = {
        int(row["row_id"]): row for row in build_role_feature_table().to_pylist()
    }
    latest: dict[int, dict[str, Any]] = {}
    order: dict[int, tuple[str, int]] = {}
    for row in features:
        code = int(row["player_code"])
        key = (str(row["season"]), int(row["event_number"]))
        if key >= order.get(code, ("", -1)):
            order[code] = key
            latest[code] = role_by_id[int(row["row_id"])]
    return latest


def build_current_lead_shadow() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lead_result = load_json_artifact(LEAD_RESULTS, "lead-time challenger")
    if lead_result.get("verdict") not in {
        "PASS_HISTORICAL_HOLD_SHADOW",
        # Backward-compatible while a just-completed v1 run is rewritten with the stricter label.
        "PROMOTE",
    }:
        raise ValueError("lead-time challenger has no historical permission for a live shadow")
    if lead_result["artifacts"]["model_sha256"] != sha256_file(LEAD_MODEL):
        raise ValueError("lead-time model does not match its result receipt")
    bundle = joblib.load(LEAD_MODEL)
    eligible_positions = set(map(str, bundle.get("eligible_positions", ())))
    feature_rows = pq.read_table(CURRENT_FEATURES).to_pylist()
    forecast_rows = pq.read_table(CURRENT_FORECAST).to_pylist()
    start_event = min(int(row["event_number"]) for row in forecast_rows)
    events = tuple(range(start_event, start_event + 8))
    if events != EVENTS:
        raise ValueError(f"Adaptive preseason stress expects events {EVENTS}, received {events}")
    feature_by_key = {
        (int(row["event_number"]), int(row["element"])): row for row in feature_rows
    }
    origin_feature = {
        int(row["element"]): row
        for row in feature_rows
        if int(row["event_number"]) == start_event
    }
    origin_forecast = {
        int(row["element"]): row
        for row in forecast_rows
        if int(row["event_number"]) == start_event
    }
    latest_role = _latest_role_by_player_code()
    output = [dict(row) for row in forecast_rows]
    grouped_indices: dict[str, list[int]] = defaultdict(list)
    design_rows: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(output):
        event = int(row["event_number"])
        element = int(row["element"])
        feature = feature_by_key[(event, element)]
        origin = origin_feature[element]
        base = origin_forecast[element]
        role = latest_role.get(int(origin["player_code"]), {})
        design = {
            "baseline_expected_points": float(row["expected_points"]),
            "origin_expected_points": float(base["expected_points"]),
            "origin_p_play": float(base["p_play"]),
            "forecast_lead": event - start_event,
            "fixture_count": float(feature["fixture_count"]),
            "home_fraction": float(feature["home_fraction"]),
            "fixture_difficulty": feature.get("fixture_difficulty"),
            **{name: origin.get(name) for name in MODEL_FEATURES if name in origin},
            **{name: role.get(name) for name in ROLE_FEATURES},
        }
        design_rows[index] = design
        if event > start_event:
            grouped_indices[str(row["position"])].append(index)
        row.update(
            {
                "incumbent_expected_points": float(row["expected_points"]),
                "lead_time_expected_points": float(row["expected_points"]),
                "lead_time_raw_expected_points": float(row["expected_points"]),
                "lead_time_weight": 0.0,
                "lead_time_applied": False,
                "lead_time_residual_sd": 0.0,
            }
        )
    for position, indices in grouped_indices.items():
        if position not in eligible_positions:
            continue
        position_bundle = bundle["positions"][position]
        matrix = np.asarray(
            [
                [_number(design_rows[index].get(feature)) for feature in MODEL_FEATURES]
                for index in indices
            ],
            dtype=np.float32,
        )
        raw = np.clip(position_bundle["model"].predict(matrix), 0.0, 15.0)
        weight = float(position_bundle["weight"])
        for offset, index in enumerate(indices):
            row = output[index]
            baseline = float(row["incumbent_expected_points"])
            score = (1.0 - weight) * baseline + weight * float(raw[offset])
            lead = int(row["event_number"]) - start_event
            residual_sd = float(position_bundle["residual_sd_by_lead"][str(lead)])
            row.update(
                {
                    "lead_time_expected_points": score,
                    "lead_time_raw_expected_points": float(raw[offset]),
                    "lead_time_weight": weight,
                    "lead_time_applied": True,
                    "lead_time_residual_sd": residual_sd,
                    "expected_points": score,
                    "robust_points": score - 0.15 * residual_sd,
                    "conditional_points_if_playing": score
                    / max(float(row["p_play"]), 0.005),
                }
            )
    return output, {
        "lead_results": str(LEAD_RESULTS),
        "lead_results_sha256": sha256_file(LEAD_RESULTS),
        "lead_model": str(LEAD_MODEL),
        "lead_model_sha256": sha256_file(LEAD_MODEL),
        "current_forecast": str(CURRENT_FORECAST),
        "current_forecast_sha256": sha256_file(CURRENT_FORECAST),
        "current_features": str(CURRENT_FEATURES),
        "current_features_sha256": sha256_file(CURRENT_FEATURES),
    }


def _candidate_pool(
    base_by_player: dict[int, dict[int, dict[str, Any]]],
    base_meta: dict[int, dict[str, Any]],
    lead_by_player: dict[int, dict[int, dict[str, Any]]],
    lead_meta: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    robust = load_json_artifact(GLOBAL_RESULTS, "global robust-search results")
    shortlist = load_json_artifact(GLOBAL_SHORTLIST, "global robust-search shortlist")
    synthesis = load_json_artifact(SYNTHESIS_RESULTS, "GW1 synthesis")
    protected_finalists = robust["finalist_metrics"][:8]
    finalist_ids = {str(row["candidate_id"]) for row in protected_finalists}
    roots = [
        row for row in shortlist["candidates"] if str(row["candidate_id"]) in finalist_ids
    ]
    roots.extend(
        [
            robust["leader_candidate"],
            synthesis["decision"]["candidate"],
        ]
    )
    rules = load_rules()
    exclusions = [set(map(int, row["selected"])) for row in roots]
    lead_solutions = []
    for decay in (0.80, 0.88, 0.94):
        for bench_weight in (0.0, 0.08):
            try:
                solution = _solve_static(
                    lead_by_player,
                    lead_meta,
                    EVENTS,
                    rules,
                    excluded_squads=exclusions,
                    horizon_decay=decay,
                    bench_weight=bench_weight,
                )
            except RuntimeError:
                continue
            selected = set(map(int, solution["selected"]))
            exclusions.append(selected)
            lead_solutions.append(
                _candidate_record(
                    list(selected),
                    lead_by_player,
                    lead_meta,
                    [f"lead-time:d{decay:.2f}:b{bench_weight:.2f}"],
                )
            )
    roots.extend(lead_solutions)
    unique: dict[tuple[int, ...], dict[str, Any]] = {}
    for row in roots:
        key = tuple(sorted(map(int, row["selected"])))
        unique.setdefault(key, row)
    production_id = str(synthesis["decision"]["candidate_id"])
    production_key = tuple(sorted(map(int, synthesis["decision"]["candidate"]["selected"])))
    candidates = []
    for index, (selected, source) in enumerate(unique.items(), start=1):
        record = _candidate_record(
            list(selected),
            base_by_player,
            base_meta,
            list(source.get("origin_ids") or [str(source.get("archetype") or "incumbent")]),
        )
        if selected == production_key:
            record["candidate_id"] = production_id
            record["production_incumbent"] = True
        else:
            record["candidate_id"] = f"AP-{index:03d}-{record['candidate_id'][2:]}"
            record["production_incumbent"] = False
        candidates.append(record)
    if sum(bool(row["production_incumbent"]) for row in candidates) != 1:
        raise ValueError("adaptive candidate pool does not contain one production incumbent")
    return candidates, {
        "robust_finalists_available": len(robust["finalist_metrics"]),
        "robust_finalists_protected": len(finalist_ids),
        "lead_generated": len(lead_solutions),
        "unique_candidates": len(candidates),
    }


def _cvar10(values: np.ndarray) -> float:
    count = max(1, int(np.ceil(0.10 * len(values))))
    return float(np.partition(values, count - 1)[:count].mean())


def _role_factors(player_ids: set[int]) -> tuple[dict[int, float], dict[str, Any]]:
    if not ROLE_EVIDENCE.is_file():
        return {}, {"status": "missing"}
    rows = pq.read_table(ROLE_EVIDENCE).to_pylist()
    available = {
        int(row["fpl_element"]) for row in rows if row.get("fpl_element") is not None
    }
    covered = player_ids & available
    flags = derive_role_flags(rows, covered)
    factors = scenario_player_factors(flags, SCENARIOS["moderate_role_stress"])
    return factors, {
        "status": "ready",
        "players_requested": len(player_ids),
        "players_covered": len(covered),
        "players_stressed": len(factors),
        "uncovered_players": len(player_ids - covered),
    }


def rank_adaptive_candidates(
    candidate_ids: list[str],
    scenario_values: dict[str, np.ndarray],
    *,
    scenario_weights: dict[str, float] = SCENARIO_WEIGHTS,
    production_id: str,
) -> list[dict[str, Any]]:
    if set(scenario_values) != set(scenario_weights):
        raise ValueError("Adaptive values and weights must describe the same scenarios")
    if not np.isclose(sum(scenario_weights.values()), 1.0):
        raise ValueError("Adaptive scenario weights must sum to one")
    if any(len(values) != len(candidate_ids) for values in scenario_values.values()):
        raise ValueError("Adaptive scenario arrays must align with candidate IDs")
    best = {name: float(values.max()) for name, values in scenario_values.items()}
    output = []
    for index, candidate_id in enumerate(candidate_ids):
        regrets = {
            name: best[name] - float(values[index])
            for name, values in scenario_values.items()
        }
        weighted = sum(scenario_weights[name] * regrets[name] for name in regrets)
        worst = max(regrets.values())
        output.append(
            {
                "candidate_id": candidate_id,
                "scenario_values": {
                    name: float(values[index]) for name, values in scenario_values.items()
                },
                "scenario_regrets": regrets,
                "weighted_mean_regret": weighted,
                "worst_scenario_regret": worst,
                "robust_regret": 0.75 * weighted + 0.25 * worst,
                "production_incumbent": candidate_id == production_id,
            }
        )
    output.sort(
        key=lambda row: (
            row["robust_regret"],
            not row["production_incumbent"],
            row["candidate_id"],
        )
    )
    return output


def full_pipeline_request_gate(
    leader: dict[str, Any], incumbent: dict[str, Any]
) -> dict[str, Any]:
    checks = {
        "leader_differs_from_incumbent": leader["candidate_id"] != incumbent["candidate_id"],
        "robust_regret_improves_by_point_two_five": (
            incumbent["robust_regret"] - leader["robust_regret"] >= 0.25
        ),
        "base_open_non_regression": (
            leader["scenario_values"]["base_open"]
            >= incumbent["scenario_values"]["base_open"] - 0.25
        ),
        "role_downside_non_regression": (
            leader["scenario_values"]["moderate_role_base_open"]
            >= incumbent["scenario_values"]["moderate_role_base_open"] - 0.25
        ),
        "lead_open_improves": (
            leader["scenario_values"]["lead_open"]
            > incumbent["scenario_values"]["lead_open"]
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "robust_regret_delta": incumbent["robust_regret"] - leader["robust_regret"],
    }


def _run_tournament(
    base_rows: list[dict[str, Any]],
    lead_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    base_by_player, base_meta = _forecast_grid(base_rows)
    lead_by_player, lead_meta = _forecast_grid(lead_rows)
    candidates, funnel = _candidate_pool(
        base_by_player,
        base_meta,
        lead_by_player,
        lead_meta,
    )
    print(
        f"Adaptive stress: retained {len(candidates)} unique initial squads; "
        "solving paired transfer policies",
        flush=True,
    )
    base_family_records = [
        _candidate_record(
            list(map(int, row["selected"])),
            base_by_player,
            base_meta,
            list(row["origin_ids"]),
        )
        for row in candidates
    ]
    lead_family_records = [
        _candidate_record(
            list(map(int, row["selected"])),
            lead_by_player,
            lead_meta,
            list(row["origin_ids"]),
        )
        for row in candidates
    ]
    for index, source in enumerate(candidates):
        base_family_records[index]["candidate_id"] = source["candidate_id"]
        lead_family_records[index]["candidate_id"] = source["candidate_id"]
    base_open = []
    lead_open = []
    for index, (base_candidate, lead_candidate) in enumerate(
        zip(base_family_records, lead_family_records, strict=True), start=1
    ):
        base_open.append(_policy_variant(base_candidate, base_rows, "open", events=EVENTS))
        lead_open.append(_policy_variant(lead_candidate, lead_rows, "open", events=EVENTS))
        if index % 8 == 0 or index == len(candidates):
            print(
                f"Adaptive stress: solved base and lead policies for "
                f"{index}/{len(candidates)} squads",
                flush=True,
            )
    player_ids = sorted(
        {
            int(element)
            for family in (base_family_records, lead_family_records, base_open, lead_open)
            for candidate in family
            for squad in [candidate["selected"], *candidate.get("planned_squads", {}).values()]
            for element in squad
        }
    )
    calibration = calibrate_residuals()
    print("Adaptive stress: simulating 10,000 paired correlated worlds", flush=True)
    base_points, base_played = _simulate_player_outcomes(
        player_ids,
        EVENTS,
        base_by_player,
        calibration,
        SIMULATIONS,
        SEED,
    )
    lead_points, lead_played = _simulate_player_outcomes(
        player_ids,
        EVENTS,
        lead_by_player,
        calibration,
        SIMULATIONS,
        SEED,
    )
    factors, role_coverage = _role_factors(set(player_ids))
    stressed_points, stressed_played, role_diagnostics = apply_conditional_dnp_stress(
        base_points,
        base_played,
        player_ids,
        factors,
        seed=SEED + 71,
    )
    scores = {
        "base_open": _score_candidates(
            base_open, player_ids, EVENTS, base_points, base_played, base_meta
        ),
        "lead_open": _score_candidates(
            lead_open, player_ids, EVENTS, lead_points, lead_played, lead_meta
        ),
        "base_fixed": _score_candidates(
            base_family_records,
            player_ids,
            EVENTS,
            base_points,
            base_played,
            base_meta,
        ),
        "lead_fixed": _score_candidates(
            lead_family_records,
            player_ids,
            EVENTS,
            lead_points,
            lead_played,
            lead_meta,
        ),
        "moderate_role_base_open": _score_candidates(
            base_open,
            player_ids,
            EVENTS,
            stressed_points,
            stressed_played,
            base_meta,
        ),
    }
    scenario_totals = {
        name: weighted_totals(values, EVENTS, EVENTS, 0.88)
        for name, values in scores.items()
    }
    scenario_means = {
        name: values.mean(axis=0) for name, values in scenario_totals.items()
    }
    production_id = next(
        str(row["candidate_id"]) for row in candidates if row["production_incumbent"]
    )
    ranking = rank_adaptive_candidates(
        [str(row["candidate_id"]) for row in candidates],
        scenario_means,
        production_id=production_id,
    )
    leader = ranking[0]
    incumbent = next(row for row in ranking if row["candidate_id"] == production_id)
    by_id = {str(row["candidate_id"]): row for row in candidates}
    gate = full_pipeline_request_gate(leader, incumbent)
    print(
        f"Adaptive stress: complete; leader {leader['candidate_id']} and full-pipeline "
        f"gate {'passed' if gate['passed'] else 'did not pass'}",
        flush=True,
    )
    distribution = {
        name: {
            str(candidates[index]["candidate_id"]): {
                "mean": float(values[:, index].mean()),
                "p10": float(np.quantile(values[:, index], 0.10)),
                "cvar10": _cvar10(values[:, index]),
                "p90": float(np.quantile(values[:, index], 0.90)),
            }
            for index in range(len(candidates))
            if candidates[index]["candidate_id"] in {leader["candidate_id"], production_id}
        }
        for name, values in scenario_totals.items()
    }
    return {
        "simulation": {
            "draws": SIMULATIONS,
            "seed": SEED,
            "events": list(EVENTS),
            "scenario_weights": SCENARIO_WEIGHTS,
            "residual_rows": calibration.rows,
            "residual_played_rows": calibration.played_rows,
        },
        "funnel": funnel,
        "role_coverage": role_coverage,
        "role_diagnostics": role_diagnostics,
        "ranking": ranking,
        "leader": {**leader, "candidate": by_id[leader["candidate_id"]]},
        "incumbent": {**incumbent, "candidate": by_id[production_id]},
        "full_pipeline_request_gate": gate,
        "leader_incumbent_distributions": distribution,
    }


def _render(result: dict[str, Any]) -> str:
    tournament = result["tournament"]
    leader = tournament["leader"]
    incumbent = tournament["incumbent"]
    gate = tournament["full_pipeline_request_gate"]
    lines = [
        "# Adaptive preseason lead-time stress",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — `{leader['candidate_id']}` leads the bounded adaptive "
            f"tournament with robust regret {leader['robust_regret']:.3f}; production "
            f"`{incumbent['candidate_id']}` has {incumbent['robust_regret']:.3f}."
        ),
        "",
        (
            "Every initial squad receives a separately solved legal GW1–8 transfer policy under "
            "the base and lead-specific forecast families. Both policies are then scored in "
            "10,000 paired correlated worlds, with fixed-squad and moderate GW1 role-downside "
            "families preventing a single optimistic future model from owning the answer."
        ),
        "",
        "| Rank | Candidate | Robust regret | Base open | Lead open | Role downside |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(tournament["ranking"][:12], start=1):
        lines.append(
            f"| {rank} | `{row['candidate_id']}` | {row['robust_regret']:.3f} | "
            f"{row['scenario_values']['base_open']:.2f} | "
            f"{row['scenario_values']['lead_open']:.2f} | "
            f"{row['scenario_values']['moderate_role_base_open']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Full-pipeline request gate",
            "",
        ]
    )
    for name, passed in gate["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend(
        [
            "",
            (
                "Passing this gate only requests equal treatment in the complete robust-search, "
                "horizon and synthesis funnel. It cannot directly replace the published squad."
            ),
            "",
        ]
    )
    resolution = result.get("full_pipeline_resolution")
    if resolution is not None:
        lines.extend(
            [
                "## Full-pipeline resolution",
                "",
                (
                    f"**{resolution['verdict']}** — the requested challenger reached the full "
                    f"robust and horizon holdouts. Robust regret was "
                    f"{resolution['robust_regret']:.3f}, horizon regret was "
                    f"{resolution['horizon_regret']:.3f}, and synthesis selected "
                    f"`{resolution['synthesis_candidate_id']}`."
                ),
                "",
            ]
        )
    return "\n".join(lines)


def run_adaptive_preseason_stress() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Adaptive stress: building current lead-specific shadow", flush=True)
    lead_rows, lineage = build_current_lead_shadow()
    pq.write_table(pa.Table.from_pylist(lead_rows), CURRENT_LEAD_FORECAST, compression="zstd")
    base_rows = pq.read_table(CURRENT_FORECAST).to_pylist()
    tournament = _run_tournament(base_rows, lead_rows)
    request = tournament["full_pipeline_request_gate"]["passed"]
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate_only",
        "verdict": "REQUEST_FULL_PIPELINE" if request else "RETAIN_INCUMBENT",
        "production_changed": False,
        "lineage": lineage,
        "tournament": tournament,
        "artifacts": {
            "current_lead_forecast": str(CURRENT_LEAD_FORECAST),
            "current_lead_forecast_sha256": sha256_file(CURRENT_LEAD_FORECAST),
        },
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result


def resolve_adaptive_full_pipeline() -> dict[str, Any]:
    result = load_json_artifact(RESULTS_JSON, "adaptive preseason stress")
    if result.get("verdict") != "REQUEST_FULL_PIPELINE":
        return result
    robust = load_json_artifact(GLOBAL_RESULTS, "global robust-search results")
    horizon = load_json_artifact(HORIZON_RESULTS, "horizon audit results")
    synthesis = load_json_artifact(SYNTHESIS_RESULTS, "GW1 synthesis")
    requested_at = datetime.fromisoformat(str(result["created_at"]))
    stage_times = {
        "robust": datetime.fromisoformat(str(robust["created_at"])),
        "horizon": datetime.fromisoformat(str(horizon["created_at"])),
        "synthesis": datetime.fromisoformat(str(synthesis["created_at"])),
    }
    if any(created_at <= requested_at for created_at in stage_times.values()):
        raise ValueError("full-pipeline artifacts do not postdate the adaptive request")
    robust_row = next(
        (
            row
            for row in robust["finalist_metrics"]
            if "adaptive-lead-shadow" in set(row.get("origin_ids", []))
        ),
        None,
    )
    horizon_row = next(
        (
            row
            for row in horizon["finalist_metrics"]
            if "adaptive-lead-shadow" in set(row.get("origin_ids", []))
        ),
        None,
    )
    if robust_row is None or horizon_row is None:
        raise ValueError("adaptive challenger did not receive both full-pipeline holdouts")
    requested_squad = tuple(
        sorted(map(int, result["tournament"]["leader"]["candidate"]["selected"]))
    )
    synthesis_squad = tuple(
        sorted(map(int, synthesis["decision"]["candidate"]["selected"]))
    )
    selected = synthesis_squad == requested_squad
    resolution = {
        "verdict": "PROMOTED" if selected else "RETAIN_INCUMBENT",
        "requested_candidate_id": str(robust_row["candidate_id"]),
        "robust_regret": float(robust_row["robust_regret"]),
        "horizon_regret": float(horizon_row["robust_regret"]),
        "synthesis_candidate_id": str(synthesis["decision"]["candidate_id"]),
        "selected_by_synthesis": selected,
        "artifacts": {
            "robust_results": str(GLOBAL_RESULTS),
            "robust_results_sha256": sha256_file(GLOBAL_RESULTS),
            "horizon_results": str(HORIZON_RESULTS),
            "horizon_results_sha256": sha256_file(HORIZON_RESULTS),
            "synthesis_results": str(SYNTHESIS_RESULTS),
            "synthesis_results_sha256": sha256_file(SYNTHESIS_RESULTS),
        },
    }
    result["verdict"] = (
        "FULL_PIPELINE_PROMOTED" if selected else "FULL_PIPELINE_RETAIN_INCUMBENT"
    )
    result["production_changed"] = False
    result["full_pipeline_resolution"] = resolution
    RESULTS_JSON.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
