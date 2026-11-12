from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .artifact_lineage import load_json_artifact
from .current_squad_audit import _captain_bonus, _simulate_families
from .current_squad_audit import _verify_lineage as _verify_current_lineage
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .team_chip_replay import RESULTS as TEAM_CHIP_RESULTS
from .tournament import _load_rows, _score_candidates

VERSION = "gw1_chip_decision_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "gw1-chip-decision.md"
EVENT = 1


def score_team_chip_variants(
    candidate: dict[str, Any],
    player_ids: list[int],
    points: np.ndarray,
    played: np.ndarray,
    meta: dict[int, dict[str, Any]],
) -> dict[str, np.ndarray]:
    """Score no-chip, BB and TC on identical worlds with exact autosubs."""

    if points.shape != played.shape or points.ndim != 3 or points.shape[1] != 1:
        raise ValueError("chip scoring requires equal single-event point/play tensors")
    lineup = candidate["lineups"][str(EVENT)]
    selected = list(map(int, candidate["selected"]))
    player_index = {element: index for index, element in enumerate(player_ids)}
    missing = set(selected) - set(player_index)
    if missing:
        raise ValueError(f"chip squad players are absent from simulations: {sorted(missing)}")

    no_chip = _score_candidates([candidate], player_ids, (EVENT,), points, played, meta)[
        :, 0, 0
    ].astype(np.float64)
    captain_bonus = _captain_bonus(
        points,
        played,
        player_index,
        int(lineup["captain"]),
        int(lineup["vice_captain"]),
    ).astype(np.float64)
    squad_indices = [player_index[element] for element in selected]
    all_fifteen = (
        np.where(
            played[:, 0, squad_indices],
            points[:, 0, squad_indices],
            0,
        )
        .astype(np.float64)
        .sum(axis=1)
    )
    bench_boost = all_fifteen + captain_bonus
    triple_captain = no_chip + captain_bonus
    return {
        "no_chip": no_chip,
        "bench_boost": bench_boost,
        "triple_captain": triple_captain,
    }


def summarize_chip_delta(chip: np.ndarray, no_chip: np.ndarray) -> dict[str, float]:
    if chip.shape != no_chip.shape or chip.ndim != 1 or len(chip) < 2:
        raise ValueError("chip and no-chip score vectors must have equal non-trivial shape")
    delta = chip.astype(np.float64) - no_chip.astype(np.float64)
    return {
        "mean": float(delta.mean()),
        "p10": float(np.quantile(delta, 0.10)),
        "median": float(np.quantile(delta, 0.50)),
        "p90": float(np.quantile(delta, 0.90)),
        "zero_probability": float(np.mean(delta == 0.0)),
        "positive_probability": float(np.mean(delta > 0.0)),
    }


def choose_gw1_chip(
    evidence: dict[str, dict[str, Any]], retention: dict[str, Any]
) -> dict[str, Any]:
    """Fail closed unless retained timing has earned authority.

    A chip always raises the current-week mean; that alone cannot establish that
    spending a once-per-half option now is better than retaining it.  Authority is
    therefore an explicit prerequisite rather than an arbitrary current-xP margin.
    """

    promotion = retention.get("promotion_gate") or {}
    authority = retention.get("authority") is True and promotion.get("passed") is True
    thresholds = retention.get("retained_value_thresholds") or {}
    qualified = []
    observed = []
    for chip in ("bench_boost", "triple_captain"):
        family_floor = min(
            float(evidence[chip][family]["mean"]) for family in ("residual", "component")
        )
        threshold = float(thresholds.get(chip, float("inf")))
        observed.append((family_floor - threshold, chip, family_floor, threshold))
        if authority and family_floor >= threshold:
            qualified.append((family_floor - threshold, chip, family_floor, threshold))
    if not qualified:
        margin, chip, family_floor, threshold = max(observed)
        return {
            "chip": None,
            "label": "NO_CHIP",
            "actionable": True,
            "reason": (
                "retained_timing_has_no_live_authority"
                if not authority
                else "no_chip_clears_retained_value_threshold"
            ),
            "retained_timing_authority": authority,
            "strongest_immediate_signal": {
                "chip": chip,
                "cross_family_floor": family_floor,
                "retained_value_threshold": threshold,
                "margin": margin,
                "status": (
                    "strong_but_not_actionable"
                    if family_floor >= threshold and not authority
                    else "below_retained_value_threshold"
                ),
            },
        }
    _, chip, family_floor, threshold = max(qualified)
    return {
        "chip": chip,
        "label": chip.upper(),
        "actionable": True,
        "reason": "current_shared_world_gain_clears_authoritative_retained_value",
        "retained_timing_authority": authority,
        "cross_family_floor": family_floor,
        "retained_value_threshold": threshold,
    }


def run_gw1_chip_decision(
    *,
    simulations: int = 25_000,
    seed: int = 20260823,
    decision_path: Path = SYNTHESIZED_DECISION,
    retention_path: Path = TEAM_CHIP_RESULTS,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if simulations < 5_000:
        raise ValueError("GW1 chip simulation count is below the safety minimum")
    ensure_engine_layout()
    decision, lineage = _verify_current_lineage(decision_path=decision_path)
    retention = load_json_artifact(retention_path, "team-chip retained-value replay")
    if retention.get("version") != 1:
        raise ValueError("team-chip retained-value replay has an unsupported contract")
    current = decision["decision"]["candidate"]
    _, loaded = _load_rows((EVENT,))
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    component_backtest = load_json_artifact(
        MODEL_DATA / "component_backtest_v1" / "metrics.json",
        "component backtest metrics",
    )
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    print("GW1 chip decision: simulating shared residual/component worlds", flush=True)
    (
        player_ids,
        residual_points,
        residual_played,
        component_points,
        diagnostics,
    ) = _simulate_families(by_player, simulations, seed, raw_weight)
    component_played = diagnostics.pop("component_played")
    residual_scores = score_team_chip_variants(
        current, player_ids, residual_points, residual_played, meta
    )
    component_scores = score_team_chip_variants(
        current, player_ids, component_points, component_played, meta
    )
    evidence = {
        chip: {
            "residual": summarize_chip_delta(residual_scores[chip], residual_scores["no_chip"]),
            "component": summarize_chip_delta(component_scores[chip], component_scores["no_chip"]),
        }
        for chip in ("bench_boost", "triple_captain")
    }
    recommendation = choose_gw1_chip(evidence, retention)
    lineup = current["lineups"][str(EVENT)]
    result = {
        "version": VERSION,
        "event": EVENT,
        "candidate_id": str(current["candidate_id"]),
        "recommendation": recommendation,
        "current_configuration": {
            "formation": str(lineup["formation"]),
            "captain": int(lineup["captain"]),
            "vice_captain": int(lineup["vice_captain"]),
            "bench_order": list(map(int, lineup["bench_order"])),
        },
        "shared_world_evidence": evidence,
        "retained_value": {
            "verdict": retention.get("verdict"),
            "status": retention.get("status"),
            "authority": retention.get("authority"),
            "promotion_gate": retention.get("promotion_gate"),
            "thresholds": retention.get("retained_value_thresholds"),
            "policy": retention.get("policy"),
        },
        "rule_contract": {
            "bench_boost_available_in_gw1": True,
            "triple_captain_available_in_gw1": True,
            "one_chip_per_event": True,
            "first_half_expiry_event": 19,
        },
        "lineage": {
            **lineage,
            "team_chip_retention_sha256": sha256_file(retention_path),
        },
        "simulation": {
            "simulations_per_family": simulations,
            "seed": seed,
            "component_raw_weight": raw_weight,
            "diagnostics": diagnostics,
        },
        "decision_rule": (
            "Current-week chip uplift is necessary but not sufficient. A live chip requires "
            "positive shared-world gain in both model families and a retained-timing policy "
            "that passed historical and prospective authority gates. Otherwise save the chip."
        ),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_report(result, meta), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any], meta: dict[int, dict[str, Any]]) -> str:
    recommendation = result["recommendation"]
    lines = [
        "# GW1 chip decision",
        "",
        f"**{recommendation['label']}** — `{recommendation['reason']}`.",
        "",
        result["decision_rule"],
        "",
        "## Current shared-world uplift",
        "",
        "| Chip | Residual mean · p10–p90 | Component mean · p10–p90 |",
        "| --- | ---: | ---: |",
    ]
    for chip in ("bench_boost", "triple_captain"):
        residual = result["shared_world_evidence"][chip]["residual"]
        component = result["shared_world_evidence"][chip]["component"]
        lines.append(
            f"| {chip.replace('_', ' ').title()} | {residual['mean']:+.2f} · "
            f"{residual['p10']:+.1f}–{residual['p90']:+.1f} | "
            f"{component['mean']:+.2f} · {component['p10']:+.1f}–"
            f"{component['p90']:+.1f} |"
        )
    config = result["current_configuration"]
    shadow = recommendation.get("strongest_immediate_signal") or {}
    lines.extend(
        [
            "",
            "## Exact configuration",
            "",
            f"- Captain: {meta[int(config['captain'])]['player_name']}",
            f"- Vice-captain: {meta[int(config['vice_captain'])]['player_name']}",
            "- Bench: "
            + ", ".join(meta[int(element)]["player_name"] for element in config["bench_order"]),
            "",
            "## Retained option gate",
            "",
            f"- Historical replay verdict: `{result['retained_value']['verdict']}`",
            f"- Live authority: `{bool(result['retained_value']['authority'])}`",
            (
                "- Thresholds: Bench Boost "
                f"{result['retained_value']['thresholds'].get('bench_boost')} · Triple Captain "
                f"{result['retained_value']['thresholds'].get('triple_captain')}"
            ),
            *(
                [
                    (
                        "- Strongest immediate signal: "
                        f"**{str(shadow['chip']).replace('_', ' ').title()}** · cross-family "
                        f"floor {float(shadow['cross_family_floor']):+.2f} · threshold "
                        f"{float(shadow['retained_value_threshold']):+.2f} · margin "
                        f"{float(shadow['margin']):+.2f} · `{shadow['status']}`"
                    )
                ]
                if shadow
                else []
            ),
            "",
            (
                "The recommendation is deliberately not changed merely because every chip has "
                "positive immediate value. The scarce option must beat keeping it for another "
                "deadline under an authority-bearing timing policy."
            ),
            "",
        ]
    )
    return "\n".join(lines)
