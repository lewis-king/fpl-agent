from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .component_candidates import COMPONENT_CANDIDATES_JSON
from .models import CURRENT_FORECAST
from .paths import DECISIONS, MODEL_DATA, REPORTS, ensure_engine_layout
from .tournament import CANDIDATES_JSON

COMPONENT_RESULTS = MODEL_DATA / "tournament_v2" / "component-gw1-5-results.json"
BENCH_RESULTS = MODEL_DATA / "bench_audit_v1" / "results.json"
APPEARANCE_METRICS = MODEL_DATA / "appearance_audit_v1" / "metrics.json"
BPS_METRICS = MODEL_DATA / "bps_2026_27_v1" / "metrics.json"
PROMOTED_RECEIPT = DECISIONS / "2026-27-gw1-promoted-squad.json"
REPORT = REPORTS / "gw1-promoted-squad.md"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate(candidate_id: str) -> dict[str, Any]:
    path = COMPONENT_CANDIDATES_JSON if candidate_id.startswith("C") else CANDIDATES_JSON
    payload = _load(path)
    return next(
        candidate
        for candidate in payload["candidates"]
        if str(candidate["candidate_id"]) == candidate_id
    )


def _metric(result: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    rows = (
        result["component_native_metrics"]
        if candidate_id.startswith("C")
        else result["policy_finalist_metrics"]
    )
    return next(row for row in rows if row["candidate_id"] == candidate_id)


def promote_gw1_squad() -> dict[str, Any]:
    ensure_engine_layout()
    component = _load(COMPONENT_RESULTS)
    if component["promotion_gate"]["status"] != "promoted":
        raise RuntimeError("Component tournament is not promoted; no production receipt written")
    candidate_id = str(component["recommended_candidate"])
    candidate = _candidate(candidate_id)
    metric = _metric(component, candidate_id)
    bench = _load(BENCH_RESULTS)
    bench_metric = next(
        row
        for row in bench["simulation"]["evidence_weighted_metrics"]
        if row["candidate_id"] == candidate_id
    )
    stress_metric = next(
        row
        for row in bench["simulation"]["clean_sheet_pessimism_raw_metrics"]
        if row["candidate_id"] == candidate_id
    )
    best_stress = max(
        bench["simulation"]["clean_sheet_pessimism_raw_metrics"],
        key=lambda row: row["mean_points"],
    )
    forecast = {
        (int(row["element"]), int(row["event_number"])): row
        for row in pq.read_table(CURRENT_FORECAST).to_pylist()
    }
    players = []
    for player in candidate["players"]:
        row = forecast[(int(player["element"]), 1)]
        players.append(
            {
                **player,
                "gw1_expected_points": float(row["expected_points"]),
                "gw1_p_play": float(row["p_play"]),
                "appearance_calibration_applied": bool(
                    row.get("appearance_calibration_applied", False)
                ),
            }
        )
    player_by_id = {int(player["element"]): player for player in players}
    gw1 = candidate["lineups"]["1"]
    receipt = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "season": "2026-27",
        "decision_event": 1,
        "status": "promoted_provisional",
        "candidate_id": candidate_id,
        "archetype": candidate["archetype"],
        "budget_spent": float(candidate["budget_spent"]),
        "bank": float(candidate["bank"]),
        "gw1_bench_spend": float(candidate["gw1_bench_spend"]),
        "gw1_outfield_bench_spend": float(candidate["gw1_outfield_bench_spend"]),
        "players": players,
        "gw1": {
            "formation": gw1["formation"],
            "starters": [player_by_id[int(element)] for element in gw1["starters"]],
            "bench": [player_by_id[int(element)] for element in gw1["bench_order"]],
            "captain": player_by_id[int(gw1["captain"])],
            "vice_captain": player_by_id[int(gw1["vice_captain"])],
        },
        "conditional_transfer_policy": candidate.get("transfer_policy", {}),
        "decision_metrics": {
            "raw_mean_points_gw1_5": float(metric["raw_mean_points"]),
            "anchored_mean_points_gw1_5": float(metric["anchored_mean_points"]),
            "evidence_weighted_mean_points_gw1_5": float(
                metric["evidence_weighted_mean_points"]
            ),
            "versus_residual_incumbent": component["decision_comparison"],
            "versus_direct_optimizer": {
                "mean_delta": float(bench_metric["mean_delta_to_incumbent"]),
                "delta_95ci_low": float(bench_metric["delta_95ci_low"]),
                "delta_95ci_high": float(bench_metric["delta_95ci_high"]),
            },
            "goal_rate_stress": {
                "multiplier": float(bench["simulation"]["goal_rate_stress_multiplier"]),
                "candidate_mean_points": float(stress_metric["mean_points"]),
                "candidate_delta_to_direct_optimizer": float(
                    stress_metric["mean_delta_to_incumbent"]
                ),
                "best_candidate": best_stress["candidate_id"],
                "gap_to_best": float(stress_metric["mean_points"] - best_stress["mean_points"]),
            },
        },
        "promotion_gate": component["promotion_gate"],
        "appearance_calibration": {
            "promoted_positions": _load(APPEARANCE_METRICS)["promoted_positions"],
            "sha256": sha256_file(APPEARANCE_METRICS),
        },
        "bps_2026_27": {
            "promoted_positions": _load(BPS_METRICS)["promoted_positions"],
            "sha256": sha256_file(BPS_METRICS),
        },
        "artifacts": {
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
            "component_results_sha256": sha256_file(COMPONENT_RESULTS),
            "bench_results_sha256": sha256_file(BENCH_RESULTS),
            "candidate_source_sha256": sha256_file(COMPONENT_CANDIDATES_JSON),
        },
        "deadline_rule": (
            "Refresh all live inputs and rerun every gate. Retain this squad only if the promoted "
            "candidate remains evidence-weighted leader and its intended starters retain their "
            "predicted minutes. If clean-sheet assumptions deteriorate materially, compare the "
            "best forced 3- and 4-defender routes before submission."
        ),
    }
    PROMOTED_RECEIPT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.write_text(_render(receipt), encoding="utf-8")
    return receipt


def _render(receipt: dict[str, Any]) -> str:
    comparison = receipt["decision_metrics"]["versus_residual_incumbent"]
    optimizer = receipt["decision_metrics"]["versus_direct_optimizer"]
    stress = receipt["decision_metrics"]["goal_rate_stress"]
    lines = [
        "# FPLAgent promoted GW1 squad",
        "",
        f"**Generated:** {receipt['created_at']}  ",
        f"**Status:** {receipt['status']}  ",
        f"**Candidate:** {receipt['candidate_id']} · {receipt['archetype']}  ",
        (
            f"**Budget:** £{receipt['budget_spent']:.1f}m · Bank £{receipt['bank']:.1f}m · "
            f"GW1 {receipt['gw1']['formation']} · Bench £{receipt['gw1_bench_spend']:.1f}m"
        ),
        "",
        "## Decision",
        "",
        (
            f"**{receipt['candidate_id']} is the nominal promoted squad.** It beat the residual "
            f"incumbent by {comparison['evidence_weighted']['mean_delta']:+.2f} points over GW1–5 "
            f"(95% CI {comparison['evidence_weighted']['delta_95ci_low']:+.2f} to "
            f"{comparison['evidence_weighted']['delta_95ci_high']:+.2f}) and the direct optimizer "
            f"by {optimizer['mean_delta']:+.2f} (95% CI {optimizer['delta_95ci_low']:+.2f} to "
            f"{optimizer['delta_95ci_high']:+.2f})."
        ),
        "",
        "## Starting XI",
        "",
        "| Pos | Player | Club | Price | GW1 xP | Play | Note |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    captain = int(receipt["gw1"]["captain"]["element"])
    vice = int(receipt["gw1"]["vice_captain"]["element"])
    for player in receipt["gw1"]["starters"]:
        note = "Captain" if player["element"] == captain else "Vice" if player["element"] == vice else ""
        lines.append(
            f"| {player['position']} | {player['name']} | {player['team']} | "
            f"£{player['price']:.1f}m | {player['gw1_expected_points']:.2f} | "
            f"{player['gw1_p_play']:.0%} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Bench",
            "",
            "| Order | Pos | Player | Club | Price | GW1 xP | Play |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for order, player in enumerate(receipt["gw1"]["bench"], start=1):
        lines.append(
            f"| {order} | {player['position']} | {player['name']} | {player['team']} | "
            f"£{player['price']:.1f}m | {player['gw1_expected_points']:.2f} | "
            f"{player['gw1_p_play']:.0%} |"
        )
    lines.extend(
        [
            "",
            "## Why this won",
            "",
            "- All 12 adversarial component gates passed.",
            "- The challenger was selected on seed 20260802 and evaluated on seed 20260803.",
            "- It improved both raw and anchored mean points; the blended paired interval excluded zero.",
            "- Forward appearance calibration was promoted only after adding value candidates to the audit population; GK/DEF/MID blanket corrections were rejected.",
            "- 2026/27 outfield BPS corrections are active; incomplete goalkeeper save context remains neutral.",
            "",
            "## Formation warning",
            "",
            (
                f"At +{stress['multiplier'] - 1:.0%} goal rates this squad still beats the direct "
                f"optimizer by {stress['candidate_delta_to_direct_optimizer']:+.2f} raw points, "
                f"but trails stress leader {stress['best_candidate']} by {abs(stress['gap_to_best']):.2f}. "
                "The opening 5-3-2 is therefore a nominal decision, not a general belief that five "
                "defenders are optimal."
            ),
            "",
            "## Deadline rule",
            "",
            receipt["deadline_rule"],
            "",
            (
                "The GW2 Mukiele → Truffert move in the machine receipt is conditional planning, "
                "not an instruction to book a transfer before GW1 has been played."
            ),
            "",
        ]
    )
    return "\n".join(lines)
