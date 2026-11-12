from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .artifact_lineage import load_json_artifact
from .capital_efficiency import expected_minutes
from .current_squad_audit import _simulate_families
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
    _configuration_audit,
    _deep_configuration_comparison,
    _load_synthesis_candidates,
    _squad_audit,
    _verify_role_lineage,
    derive_role_flags,
)
from .robust_search import SHORTLIST_JSON
from .tournament import _load_rows

VERSION = "participation_break_even_v1"
BOUNDARY_POLICY_VERSION = 2
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "gw1-participation-break-even.md"

MINUTE_SUPPORT = np.asarray((0.0, 28.0, 75.0, 90.0), dtype=np.float64)
PROBABILITY_FIELDS = ("p_dnp", "p_1_59", "p_60_89", "p_90_or_more")
DEFAULT_MINUTE_LADDER = (0.0, 30.0, 45.0, 60.0, 75.0, 90.0)


def normalized_minute_probabilities(row: dict[str, Any]) -> tuple[float, float, float, float]:
    values = np.asarray(
        [max(float(row.get(field) or 0.0), 0.0) for field in PROBABILITY_FIELDS],
        dtype=np.float64,
    )
    total = float(values.sum())
    if total <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    values /= total
    return tuple(map(float, values))  # type: ignore[return-value]


def minute_tilt_probabilities(
    probabilities: tuple[float, float, float, float], target_minutes: float
) -> tuple[float, float, float, float]:
    """Return the closest minute-class distribution with the requested mean.

    The exponential tilt is the minimum-relative-entropy change from the current
    forecast.  It therefore changes DNP/substitute/starter mass coherently rather
    than inventing a hand-authored start probability at every point on the ladder.
    Tiny support is added only so the 0-90 counterfactual path remains defined.
    """

    target = float(target_minutes)
    if not 0.0 <= target <= 90.0:
        raise ValueError("target expected minutes must be in [0, 90]")
    if target == 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    if target == 90.0:
        return (0.0, 0.0, 0.0, 1.0)

    base = np.maximum(np.asarray(probabilities, dtype=np.float64), 1e-9)
    base /= base.sum()
    centred = (MINUTE_SUPPORT - 45.0) / 45.0

    def tilted(value: float) -> np.ndarray:
        logits = np.log(base) + value * centred
        logits -= logits.max()
        weights = np.exp(logits)
        return weights / weights.sum()

    low, high = -80.0, 80.0
    for _ in range(100):
        middle = (low + high) / 2.0
        distribution = tilted(middle)
        mean = float(distribution @ MINUTE_SUPPORT)
        if mean < target:
            low = middle
        else:
            high = middle
    result = tilted((low + high) / 2.0)
    if not math.isclose(float(result @ MINUTE_SUPPORT), target, abs_tol=1e-6):
        raise RuntimeError("minute probability tilt failed to reach its target")
    return tuple(map(float, result))  # type: ignore[return-value]


def _appearance_points(probabilities: tuple[float, float, float, float]) -> float:
    return probabilities[1] + 2.0 * (probabilities[2] + probabilities[3])


def counterfactual_player_forecast(row: dict[str, Any], target_minutes: float) -> dict[str, Any]:
    current = normalized_minute_probabilities(row)
    adjusted = minute_tilt_probabilities(current, target_minutes)
    old_minutes = float(np.asarray(current) @ MINUTE_SUPPORT)
    new_minutes = float(np.asarray(adjusted) @ MINUTE_SUPPORT)
    old_points = float(row["expected_points"])
    old_appearance = _appearance_points(current)
    new_appearance = _appearance_points(adjusted)
    nonappearance_points = old_points - old_appearance
    minute_ratio = new_minutes / max(old_minutes, 1.0)
    new_points = max(new_appearance + nonappearance_points * minute_ratio, 0.0)
    p_play = float(sum(adjusted[1:]))

    output = dict(row)
    output.update(dict(zip(PROBABILITY_FIELDS, adjusted, strict=True)))
    output.update(
        {
            "p_play": p_play,
            "expected_points": new_points,
            "conditional_points_if_playing": new_points / max(p_play, 0.005),
            "robust_points": new_points - 0.15 * float(row.get("epistemic_uncertainty") or 0.0),
            "counterfactual_expected_minutes": new_minutes,
            "counterfactual_base_expected_minutes": old_minutes,
            "counterfactual_base_expected_points": old_points,
        }
    )
    return output


def compact_counterfactual_forecast(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "p_dnp": float(row["p_dnp"]),
        "p_1_59": float(row["p_1_59"]),
        "p_60_89": float(row["p_60_89"]),
        "p_90_or_more": float(row["p_90_or_more"]),
        "p_play": float(row["p_play"]),
        "expected_points": float(row["expected_points"]),
        "conditional_points_if_playing": float(row["conditional_points_if_playing"]),
        "expected_minutes": float(row["counterfactual_expected_minutes"]),
        "base_expected_minutes": float(row["counterfactual_base_expected_minutes"]),
        "base_expected_points": float(row["counterfactual_base_expected_points"]),
    }


def apply_player_minutes_counterfactual(
    points: np.ndarray,
    played: np.ndarray,
    player_ids: list[int],
    row: dict[str, Any],
    target_minutes: float,
    *,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Reweight one player's common-random-number worlds to a minute forecast.

    Existing conditional score worlds are retained wherever possible.  Added
    appearances draw from that player's own conditional pool and are shifted to
    the counterfactual conditional mean.  This keeps opponent/team covariance for
    retained worlds while making the approximation and its diagnostics explicit.
    """

    if points.shape != played.shape or points.ndim != 3 or points.shape[1] != 1:
        raise ValueError("points and played must be equal single-event tensors")
    element = int(row["element"])
    try:
        index = player_ids.index(element)
    except ValueError as exc:
        raise ValueError(f"counterfactual player {element} is absent from simulations") from exc

    forecast = counterfactual_player_forecast(row, target_minutes)
    current_minutes = expected_minutes(row)
    if math.isclose(float(target_minutes), current_minutes, abs_tol=1e-9):
        return (
            points.copy(),
            played.copy(),
            {
                "base_expected_minutes": current_minutes,
                "target_expected_minutes": float(target_minutes),
                "base_p_play": float(row["p_play"]),
                "target_p_play": float(forecast["p_play"]),
                "base_expected_points": float(row["expected_points"]),
                "target_expected_points": float(forecast["expected_points"]),
                "identity": True,
            },
        )

    output_points = points.copy()
    output_played = played.copy()
    before = played[:, 0, index].astype(bool)
    base_probability = float(before.mean())
    target_probability = float(forecast["p_play"])
    rng = np.random.default_rng(seed)

    latent = np.empty(len(before), dtype=np.float64)
    latent[before] = rng.uniform(0.0, max(base_probability, 1e-9), int(before.sum()))
    latent[~before] = rng.uniform(min(base_probability, 1.0), 1.0, int((~before).sum()))
    after = latent < target_probability
    output_played[:, 0, index] = after

    base_values = points[before, 0, index].astype(np.float64)
    if not len(base_values):
        base_values = np.zeros(1, dtype=np.float64)
    sampled = points[:, 0, index].astype(np.float64).copy()
    added = after & ~before
    if added.any():
        sampled[added] = base_values[rng.integers(0, len(base_values), int(added.sum()))]
    desired_conditional = float(forecast["conditional_points_if_playing"])
    base_conditional = float(base_values.mean())
    adjusted = np.clip(sampled[after] + desired_conditional - base_conditional, -3.0, 24.0)
    floors = np.floor(adjusted)
    rounded = floors + (rng.random(len(adjusted)) < (adjusted - floors))
    output_points[:, 0, index] = 0
    output_points[after, 0, index] = rounded.astype(output_points.dtype)

    return (
        output_points,
        output_played,
        {
            "base_expected_minutes": current_minutes,
            "target_expected_minutes": float(target_minutes),
            "base_p_play": float(row["p_play"]),
            "target_p_play": target_probability,
            "base_expected_points": float(row["expected_points"]),
            "target_expected_points": float(forecast["expected_points"]),
            "base_simulated_appearance_rate": base_probability,
            "target_simulated_appearance_rate": float(after.mean()),
            "base_conditional_simulated_points": base_conditional,
            "target_conditional_forecast_points": desired_conditional,
            "probabilities": {field: float(forecast[field]) for field in PROBABILITY_FIELDS},
            "identity": False,
        },
    )


def select_attention_players(
    selected: Iterable[int],
    by_player: dict[int, dict[int, dict[str, Any]]],
    flags: dict[int, str],
) -> list[int]:
    """Select material GW1 role assumptions without hard-coding player names."""

    attention: list[tuple[float, int]] = []
    for raw in selected:
        element = int(raw)
        row = by_player[element][EVENT]
        minutes = expected_minutes(row)
        consensus = str(row.get("live_participation_consensus") or "")
        ratio = float(row.get("live_role_minutes_ratio") or 1.0)
        score = 0.0
        if consensus == "source_disagreement":
            score += 8.0
        if consensus == "insufficient_coverage":
            score += 6.0
        if flags.get(element) == FLAG_NOT_LISTED:
            score += 7.0
        elif flags.get(element) == FLAG_ROLE_WATCH:
            score += 5.0
        if minutes < 70.0:
            score += 4.0 + (70.0 - minutes) / 20.0
        if ratio >= 1.30:
            score += 5.0 + ratio - 1.30
        if score > 0.0:
            attention.append((score, element))
    return [element for _, element in sorted(attention, key=lambda item: (-item[0], item[1]))]


def _point_has_supported_challenger(point: dict[str, Any]) -> bool:
    replay = point.get("deep_squad_replay")
    return bool(
        replay is not None
        and replay.get("cross_family_holdout_support") is True
        and replay.get("challenger_squad_id") != replay.get("incumbent_squad_id")
    )


def summarize_player_boundary(
    points: list[dict[str, Any]],
    *,
    base_expected_minutes: float | None = None,
) -> dict[str, Any]:
    """Classify only reversals caused by a deterioration from the production anchor.

    A challenger that already wins at the live forecast is a general GW1 trade-off, not a
    player-minute break-even. Labelling it as an executable ``<= minutes`` trigger would make
    an already-true condition look like new deadline evidence.
    """
    ordered = sorted(points, key=lambda row: float(row["target_expected_minutes"]))
    if not ordered:
        raise ValueError("participation boundary requires at least one tested point")
    anchor = next((row for row in ordered if row.get("is_production_anchor") is True), None)
    if anchor is None and base_expected_minutes is not None:
        anchor = min(
            ordered,
            key=lambda row: abs(
                float(row["target_expected_minutes"]) - float(base_expected_minutes)
            ),
        )
    if anchor is None:
        raise ValueError("participation boundary requires a production-anchor point")
    anchor_minutes = float(anchor["target_expected_minutes"])
    if _point_has_supported_challenger(anchor):
        replay = anchor["deep_squad_replay"]
        return {
            "classification": "general_gw1_challenger_at_production_anchor",
            "actionable": False,
            "production_anchor_expected_minutes": anchor_minutes,
            "production_anchor_supports_challenger": True,
            "production_anchor_challenger_squad_id": replay["challenger_squad_id"],
            "highest_supported_challenger_minutes": None,
            "next_tested_incumbent_minutes": None,
            "support_is_monotone": None,
            "reason": (
                "The challenger is already supported at the live forecast, so its GW1 edge "
                "cannot be attributed to a future deterioration in this player's minutes."
            ),
        }

    deterioration_path = [
        row for row in ordered if float(row["target_expected_minutes"]) <= anchor_minutes
    ]
    support_flags = [_point_has_supported_challenger(row) for row in deterioration_path]
    supported = [
        row for row, supported_at_point in zip(deterioration_path, support_flags, strict=True)
        if supported_at_point
    ]
    # As minutes improve toward the live anchor, a causal challenger signal may turn off once,
    # but must never turn back on. A non-monotone path is simulation noise, not a deadline rule.
    seen_unsupported = False
    monotone = True
    for supported_at_point in support_flags:
        if not supported_at_point:
            seen_unsupported = True
        elif seen_unsupported:
            monotone = False
            break
    if not monotone:
        return {
            "classification": "non_monotone_counterfactual_signal",
            "actionable": False,
            "production_anchor_expected_minutes": anchor_minutes,
            "production_anchor_supports_challenger": False,
            "highest_supported_challenger_minutes": None,
            "next_tested_incumbent_minutes": None,
            "support_is_monotone": False,
            "reason": "The challenger signal reverses direction on the tested minute path.",
        }
    if not supported:
        return {
            "classification": "incumbent_stable_on_tested_minutes",
            "actionable": False,
            "production_anchor_expected_minutes": anchor_minutes,
            "production_anchor_supports_challenger": False,
            "highest_supported_challenger_minutes": None,
            "next_tested_incumbent_minutes": deterioration_path[0][
                "target_expected_minutes"
            ],
            "support_is_monotone": True,
        }
    highest = max(supported, key=lambda row: float(row["target_expected_minutes"]))
    next_incumbent = next(
        (
            row
            for row in deterioration_path
            if float(row["target_expected_minutes"]) > float(highest["target_expected_minutes"])
            and not _point_has_supported_challenger(row)
        ),
        None,
    )
    if next_incumbent is None:
        raise RuntimeError("stable production anchor did not bracket the challenger boundary")
    return {
        "classification": "challenger_boundary_bracketed",
        "actionable": True,
        "production_anchor_expected_minutes": anchor_minutes,
        "production_anchor_supports_challenger": False,
        "highest_supported_challenger_minutes": highest["target_expected_minutes"],
        "highest_supported_challenger_squad_id": highest["deep_squad_replay"][
            "challenger_squad_id"
        ],
        "next_tested_incumbent_minutes": next_incumbent["target_expected_minutes"],
        "support_is_monotone": True,
    }


def _candidate_names(candidate: dict[str, Any], meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    lineup = candidate["lineups"][str(EVENT)]
    selected = set(map(int, candidate["selected"]))
    return {
        "squad_id": str(candidate["candidate_id"]),
        "selected": [
            {
                "element": element,
                "name": str(meta[element]["player_name"]),
                "position": str(meta[element]["position"]),
                "team": str(meta[element]["team_name"]),
                "price": float(meta[element]["market_price"]) / 10.0,
            }
            for element in sorted(selected)
        ],
        "formation": str(lineup["formation"]),
        "starter_elements": list(map(int, lineup["starters"])),
        "starters": [str(meta[int(element)]["player_name"]) for element in lineup["starters"]],
        "bench_elements": list(map(int, lineup["bench_order"])),
        "bench_order": [
            str(meta[int(element)]["player_name"]) for element in lineup["bench_order"]
        ],
        "captain_element": int(lineup["captain"]),
        "captain": str(meta[int(lineup["captain"])]["player_name"]),
        "vice_captain_element": int(lineup["vice_captain"]),
        "vice_captain": str(meta[int(lineup["vice_captain"])]["player_name"]),
        "budget": sum(float(meta[element]["market_price"]) for element in selected) / 10.0,
    }


def run_participation_break_even_audit(
    *,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    finalists: int = 64,
    selection_seed: int = 20260821,
    holdout_seed: int = 20260822,
    minute_ladder: Iterable[float] = DEFAULT_MINUTE_LADDER,
    player_ids: Iterable[int] | None = None,
    maximum_candidates: int | None = None,
    decision_path: Path = SYNTHESIZED_DECISION,
    shortlist_path: Path = SHORTLIST_JSON,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    fpl_dir: Path = FPL_DIR,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
    reuse_if_current: bool = True,
) -> dict[str, Any]:
    if selection_simulations < 2_000 or holdout_simulations < 5_000:
        raise ValueError("break-even simulation counts are below the safety minimum")
    if selection_seed == holdout_seed:
        raise ValueError("selection and holdout require independent seeds")
    grid = sorted({float(value) for value in minute_ladder})
    if not grid or grid[0] < 0.0 or grid[-1] > 90.0:
        raise ValueError("minute ladder must contain values in [0, 90]")

    ensure_engine_layout()
    decision, lineage = _verify_current_lineage(decision_path=decision_path)
    role_receipt, role_evidence_sha = _verify_role_lineage(
        role_receipt_path=role_receipt_path,
        role_evidence_path=role_evidence_path,
        fpl_dir=fpl_dir,
    )
    candidates = _load_synthesis_candidates(
        decision, maximum_candidates, shortlist_path=shortlist_path
    )
    current = decision["decision"]["candidate"]
    published_id = str(current["candidate_id"])
    candidate_by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    _, loaded = _load_rows((EVENT,))
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    candidate_pool = {int(element) for candidate in candidates for element in candidate["selected"]}
    role_rows = pq.read_table(role_evidence_path).to_pylist()
    flags = derive_role_flags(role_rows, candidate_pool)
    selected = list(map(int, current["selected"]))
    targets = (
        list(map(int, player_ids))
        if player_ids is not None
        else select_attention_players(selected, by_player, flags)
    )
    unknown = set(targets) - set(selected)
    if unknown:
        raise ValueError(f"break-even targets are not in the published squad: {sorted(unknown)}")
    if not targets:
        raise ValueError("no material participation assumptions were selected")

    if reuse_if_current and results_path.is_file():
        existing = json.loads(results_path.read_text(encoding="utf-8"))
        existing_simulation = existing.get("simulation") or {}
        existing_method = existing.get("method") or {}
        if (
            existing.get("version") == VERSION
            and (existing.get("lineage") or {}).get("decision_sha256") == lineage["decision_sha256"]
            and (existing.get("lineage") or {}).get("preseason_role_evidence_sha256")
            == role_evidence_sha
            and existing_method.get("minute_ladder") == grid
            and set(map(int, (existing.get("players") or {}).keys())) == set(targets)
            and int(existing_simulation.get("selection_simulations_per_family") or 0)
            == selection_simulations
            and int(existing_simulation.get("holdout_simulations_per_family") or 0)
            == holdout_simulations
            and int(existing_simulation.get("selection_seed") or 0) == selection_seed
            and int(existing_simulation.get("holdout_seed") or 0) == holdout_seed
        ):
            for player in (existing.get("players") or {}).values():
                player["boundary"] = summarize_player_boundary(
                    player["points"],
                    base_expected_minutes=float(player["base_expected_minutes"]),
                )
            existing.setdefault("method", {})[
                "boundary_policy_version"
            ] = BOUNDARY_POLICY_VERSION
            existing["method"]["boundary_policy"] = (
                "A minute fallback is causal only when the incumbent is supported at the "
                "production anchor and a monotone deterioration path creates a bracketed "
                "challenger reversal."
            )
            results_path.write_text(
                json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            report_path.write_text(_render_report(existing), encoding="utf-8")
            print("Participation break-even: reusing current checksum-bound audit", flush=True)
            return existing

    partial_path = results_path.with_suffix(".partial.json")
    partial_identity = {
        "version": VERSION,
        "decision_sha256": lineage["decision_sha256"],
        "selection_simulations": selection_simulations,
        "holdout_simulations": holdout_simulations,
        "selection_seed": selection_seed,
        "holdout_seed": holdout_seed,
        "minute_ladder": grid,
        "targets": targets,
    }
    partial = None
    if partial_path.is_file():
        candidate_partial = json.loads(partial_path.read_text(encoding="utf-8"))
        if candidate_partial.get("identity") == partial_identity:
            partial = candidate_partial

    component_backtest = load_json_artifact(
        MODEL_DATA / "component_backtest_v1" / "metrics.json",
        "component backtest metrics",
    )
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    print("Participation break-even: simulating shared selection worlds", flush=True)
    (
        simulation_player_ids,
        residual_selection_points,
        residual_selection_played,
        component_selection_points,
        selection_diagnostics,
    ) = _simulate_families(by_player, selection_simulations, selection_seed, raw_weight)
    component_selection_played = selection_diagnostics.pop("component_played")
    print("Participation break-even: simulating untouched holdout worlds", flush=True)
    (
        holdout_player_ids,
        residual_holdout_points,
        residual_holdout_played,
        component_holdout_points,
        holdout_diagnostics,
    ) = _simulate_families(by_player, holdout_simulations, holdout_seed, raw_weight)
    component_holdout_played = holdout_diagnostics.pop("component_played")
    if holdout_player_ids != simulation_player_ids:
        raise RuntimeError("selection and holdout simulation player order differs")

    published_lineup = current["lineups"][str(EVENT)]
    players: dict[str, Any] = dict((partial or {}).get("players") or {})
    for target_offset, element in enumerate(targets):
        if str(element) in players:
            print(
                f"Participation break-even: reusing checkpoint for {meta[element]['player_name']}",
                flush=True,
            )
            continue
        row = by_player[element][EVENT]
        base_minutes = expected_minutes(row)
        player_grid = sorted({*grid, round(base_minutes, 3)})
        points: list[dict[str, Any]] = []
        for minute_offset, target_minutes in enumerate(player_grid):
            print(
                f"Participation break-even: {meta[element]['player_name']} at "
                f"{target_minutes:.1f} minutes",
                flush=True,
            )
            scenario_seed = 900_000 + target_offset * 10_000 + minute_offset * 100
            rs_points, rs_played, rs_diag = apply_player_minutes_counterfactual(
                residual_selection_points,
                residual_selection_played,
                simulation_player_ids,
                row,
                target_minutes,
                seed=selection_seed + scenario_seed,
            )
            cs_points, cs_played, cs_diag = apply_player_minutes_counterfactual(
                component_selection_points,
                component_selection_played,
                simulation_player_ids,
                row,
                target_minutes,
                seed=selection_seed + scenario_seed + 1,
            )
            rh_points, rh_played, rh_diag = apply_player_minutes_counterfactual(
                residual_holdout_points,
                residual_holdout_played,
                simulation_player_ids,
                row,
                target_minutes,
                seed=holdout_seed + scenario_seed,
            )
            ch_points, ch_played, ch_diag = apply_player_minutes_counterfactual(
                component_holdout_points,
                component_holdout_played,
                simulation_player_ids,
                row,
                target_minutes,
                seed=holdout_seed + scenario_seed + 1,
            )
            configuration = _configuration_audit(
                selected,
                published_lineup,
                meta,
                simulation_player_ids,
                rs_points,
                rs_played,
                cs_points,
                cs_played,
                rh_points,
                rh_played,
                ch_points,
                ch_played,
                finalists=finalists,
            )
            squad = _squad_audit(
                candidates,
                published_id,
                meta,
                simulation_player_ids,
                rs_points,
                rs_played,
                cs_points,
                cs_played,
                rh_points,
                rh_played,
                ch_points,
                ch_played,
            )
            deep_replay = None
            screen_id = str(squad["selection_champion_id"])
            if screen_id != published_id:
                challenger_squad = candidate_by_id[screen_id]
                challenger_configuration = _configuration_audit(
                    list(map(int, challenger_squad["selected"])),
                    challenger_squad["lineups"][str(EVENT)],
                    meta,
                    simulation_player_ids,
                    rs_points,
                    rs_played,
                    cs_points,
                    cs_played,
                    rh_points,
                    rh_played,
                    ch_points,
                    ch_played,
                    finalists=finalists,
                )
                comparison = _deep_configuration_comparison(
                    challenger_configuration["selection_champion_candidate"],
                    configuration["selection_champion_candidate"],
                    meta,
                    simulation_player_ids,
                    rh_points,
                    rh_played,
                    ch_points,
                    ch_played,
                )
                challenger_named = _candidate_names(
                    challenger_configuration["selection_champion_candidate"], meta
                )
                challenger_named["squad_id"] = screen_id
                incumbent_named = _candidate_names(
                    configuration["selection_champion_candidate"], meta
                )
                incumbent_named["squad_id"] = published_id
                deep_replay = {
                    "challenger_squad_id": screen_id,
                    "incumbent_squad_id": published_id,
                    "challenger": challenger_named,
                    "incumbent": incumbent_named,
                    **comparison,
                }
            points.append(
                {
                    "target_expected_minutes": target_minutes,
                    "is_production_anchor": math.isclose(
                        target_minutes, base_minutes, abs_tol=0.001
                    ),
                    "target_forecast": compact_counterfactual_forecast(
                        counterfactual_player_forecast(row, target_minutes)
                    ),
                    "configuration": configuration,
                    "squad": squad,
                    "deep_squad_replay": deep_replay,
                    "diagnostics": {
                        "selection_residual": rs_diag,
                        "selection_component": cs_diag,
                        "holdout_residual": rh_diag,
                        "holdout_component": ch_diag,
                    },
                }
            )
        players[str(element)] = {
            "element": element,
            "name": str(meta[element]["player_name"]),
            "team": str(meta[element]["team_name"]),
            "position": str(meta[element]["position"]),
            "price": float(meta[element]["market_price"]) / 10.0,
            "base_expected_minutes": base_minutes,
            "base_p_play": float(row["p_play"]),
            "base_expected_points": float(row["expected_points"]),
            "role_flag": flags.get(element),
            "participation_consensus": row.get("live_participation_consensus"),
            "points": points,
            "boundary": summarize_player_boundary(
                points,
                base_expected_minutes=base_minutes,
            ),
        }
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_text(
            json.dumps(
                {"identity": partial_identity, "players": players},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    result = {
        "version": VERSION,
        "event": EVENT,
        "read_only": True,
        "production_changed": False,
        "decision_candidate_id": published_id,
        "decision": _candidate_names(current, meta),
        "lineage": {
            **lineage,
            "preseason_receipt_sha256": sha256_file(role_receipt_path),
            "preseason_role_evidence_sha256": role_evidence_sha,
            "preseason_collected_at": role_receipt["created_at"],
        },
        "method": {
            "boundary_policy_version": BOUNDARY_POLICY_VERSION,
            "boundary_policy": (
                "A minute fallback is causal only when the incumbent is supported at the "
                "production anchor and a monotone deterioration path creates a bracketed "
                "challenger reversal."
            ),
            "minute_support": MINUTE_SUPPORT.tolist(),
            "minute_ladder": grid,
            "probability_tilt": "minimum_relative_entropy",
            "statement": (
                "Each target is varied alone on common residual/component worlds. Added "
                "appearances reuse the player's own conditional score pool; every roster "
                "reversal is reconfigured and checked on an independent holdout. These are "
                "counterfactual break-even bounds, not new availability estimates."
            ),
        },
        "players": players,
        "simulation": {
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "component_raw_weight": raw_weight,
            "selection_diagnostics": selection_diagnostics,
            "holdout_diagnostics": holdout_diagnostics,
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_report(result), encoding="utf-8")
    partial_path.unlink(missing_ok=True)
    return result


def _format_delta(metric: dict[str, Any]) -> str:
    return (
        f"{float(metric['mean']):+.3f} "
        f"[{float(metric['ci95_low']):+.3f}, {float(metric['ci95_high']):+.3f}]"
    )


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# GW1 player participation break-even audit",
        "",
        f"Decision: `{result['decision_candidate_id']}`.",
        "",
        result["method"]["statement"],
        "",
    ]
    for player in result["players"].values():
        boundary = player["boundary"]
        lines.extend(
            [
                f"## {player['name']} · {player['team']}",
                "",
                (
                    f"Production: {player['base_expected_minutes']:.1f} expected minutes · "
                    f"{player['base_p_play']:.1%} plays · {player['base_expected_points']:.2f} xP."
                ),
                "",
                (
                    "Boundary: "
                    f"`{boundary['classification']}` · highest supported challenger "
                    f"{boundary.get('highest_supported_challenger_minutes')} minutes · next "
                    f"incumbent point {boundary.get('next_tested_incumbent_minutes')} minutes."
                ),
                *(
                    ["", f"Causality note: {boundary['reason']}"]
                    if boundary.get("reason")
                    else []
                ),
                "",
                "| Expected min | Plays | xP | Deep winner | Residual delta | Component delta |",
                "| ---: | ---: | ---: | --- | ---: | ---: |",
            ]
        )
        for point in player["points"]:
            forecast = point["target_forecast"]
            replay = point["deep_squad_replay"]
            if replay is None:
                winner = result["decision_candidate_id"]
                residual = component = "—"
            else:
                winner = replay["challenger_squad_id"]
                deltas = replay["holdout_delta_challenger_to_incumbent"]
                residual = _format_delta(deltas["residual"])
                component = _format_delta(deltas["component"])
            lines.append(
                f"| {point['target_expected_minutes']:.1f} | "
                f"{float(forecast['p_play']):.1%} | "
                f"{float(forecast['expected_points']):.2f} | `{winner}` | "
                f"{residual} | {component} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Decision rule",
            "",
            (
                "A fallback is executable only when the central squad is supported at the live "
                "production anchor, a monotone deterioration path creates a bracketed reversal, "
                "fresh attributable evidence moves the player below that bracket, and the "
                "challenger repays its multiweek synthesis regret. A challenger that already "
                "wins at the live anchor is a general GW1 trade-off, not a minute trigger."
            ),
            "",
        ]
    )
    return "\n".join(lines)
