from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)
from .horizon_audit import RESULTS_JSON as HORIZON_RESULTS
from .models import CURRENT_FORECAST
from .paths import DECISIONS, MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import (
    RESULTS_JSON as ROBUST_RESULTS,
)
from .robust_search import (
    SHORTLIST_JSON as ROBUST_SHORTLIST,
)
from .robust_search import _policy_variant
from .tournament import _load_rows

SYNTHESIS_SELECTOR_REPLAY = MODEL_DATA / "synthesis_selector_replay_v1" / "results.json"

VERSION = "gw1_decision_synthesis_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
DECISION_JSON = DECISIONS / "2026-27-gw1-synthesized.json"
REPORT = REPORTS / "gw1-synthesized-decision.md"

DEFAULT_HORIZON_FAMILY_WEIGHT = 0.50
DEFAULT_FAMILY_WORST_WEIGHT = 0.20


def _validate_weight(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between zero and one")


def synthesis_rows(
    robust_rows: list[dict[str, Any]],
    horizon_rows: list[dict[str, Any]],
    *,
    horizon_family_weight: float,
    family_worst_weight: float,
) -> list[dict[str, Any]]:
    """Combine the two pre-registered regret families without rescaling points."""
    _validate_weight(horizon_family_weight, "horizon_family_weight")
    _validate_weight(family_worst_weight, "family_worst_weight")
    robust = {row["candidate_id"]: row for row in robust_rows}
    horizon = {row["candidate_id"]: row for row in horizon_rows}
    common = sorted(set(robust) & set(horizon))
    if not common:
        raise ValueError("The robust and horizon audits have no common finalists")

    rows = []
    for candidate_id in common:
        robust_regret = float(robust[candidate_id]["robust_regret"])
        horizon_regret = float(horizon[candidate_id]["robust_regret"])
        family_weighted = (
            1.0 - horizon_family_weight
        ) * robust_regret + horizon_family_weight * horizon_regret
        family_worst = max(robust_regret, horizon_regret)
        score = (1.0 - family_worst_weight) * family_weighted + family_worst_weight * family_worst
        rows.append(
            {
                "candidate_id": candidate_id,
                "display_name": robust[candidate_id]["display_name"],
                "origin_ids": robust[candidate_id]["origin_ids"],
                "gw1_formation": robust[candidate_id]["gw1_formation"],
                "gw1_bench_spend": float(robust[candidate_id]["gw1_bench_spend"]),
                "robust_family_regret": robust_regret,
                "horizon_family_regret": horizon_regret,
                "family_weighted_regret": family_weighted,
                "family_worst_regret": family_worst,
                "synthesis_regret": score,
            }
        )
    rows.sort(key=lambda row: (row["synthesis_regret"], row["candidate_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def champion_intervals(
    rows: list[dict[str, Any]], *, family_worst_weight: float = 0.0
) -> list[dict[str, Any]]:
    """Return exact lower-envelope intervals as horizon-family weight varies."""
    if not rows:
        raise ValueError("At least one common candidate is required")
    _validate_weight(family_worst_weight, "family_worst_weight")
    lines = [
        (
            str(row["candidate_id"]),
            (1.0 - family_worst_weight) * float(row["robust_family_regret"])
            + family_worst_weight * float(row["family_worst_regret"]),
            (1.0 - family_worst_weight)
            * (float(row["horizon_family_regret"]) - float(row["robust_family_regret"])),
        )
        for row in rows
    ]
    breakpoints = {0.0, 1.0}
    for offset, (_, intercept_a, slope_a) in enumerate(lines):
        for _, intercept_b, slope_b in lines[offset + 1 :]:
            denominator = slope_a - slope_b
            if abs(denominator) < 1e-12:
                continue
            crossing = (intercept_b - intercept_a) / denominator
            if 0.0 < crossing < 1.0:
                breakpoints.add(float(crossing))
    points = sorted(breakpoints)

    def champion(weight: float) -> tuple[str, float]:
        candidate_id, intercept, slope = min(
            lines,
            key=lambda line: (line[1] + weight * line[2], line[0]),
        )
        return candidate_id, intercept + weight * slope

    raw = []
    for lower, upper in pairwise(points):
        midpoint = (lower + upper) / 2.0
        candidate_id, _ = champion(midpoint)
        raw.append({"lower": lower, "upper": upper, "candidate_id": candidate_id})
    consolidated: list[dict[str, Any]] = []
    for interval in raw:
        if consolidated and consolidated[-1]["candidate_id"] == interval["candidate_id"]:
            consolidated[-1]["upper"] = interval["upper"]
        else:
            consolidated.append(dict(interval))
    for interval in consolidated:
        midpoint = (interval["lower"] + interval["upper"]) / 2.0
        interval["midpoint_regret"] = champion(midpoint)[1]
    return consolidated


def _named_squad(candidate: dict[str, Any], meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    lineup = candidate["lineups"]["1"]
    captain = int(lineup["captain"])
    vice = int(lineup["vice_captain"])

    def player(element: int) -> dict[str, Any]:
        row = meta[int(element)]
        return {
            "element": int(element),
            "name": str(row["player_name"]),
            "position": str(row["position"]),
            "team": str(row["team_name"]),
            "price": float(row["market_price"]) / 10.0,
            "captain": int(element) == captain,
            "vice_captain": int(element) == vice,
        }

    return {
        "formation": lineup["formation"],
        "starters": [player(element) for element in lineup["starters"]],
        "bench": [player(element) for element in lineup["bench_order"]],
        "budget_spent": float(candidate["budget_spent"]),
        "bank": float(candidate["bank"]),
    }


def _first_horizon_specific(horizon_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    generated = [
        row
        for row in horizon_rows
        if any(
            str(origin).startswith(("horizon-optimizer", "horizon-neighbour"))
            for origin in row["origin_ids"]
        )
    ]
    return min(generated, key=lambda row: row["robust_regret"], default=None)


def run_decision_synthesis(
    *,
    horizon_family_weight: float = DEFAULT_HORIZON_FAMILY_WEIGHT,
    family_worst_weight: float = DEFAULT_FAMILY_WORST_WEIGHT,
    results_path: Path = RESULTS_JSON,
    decision_path: Path = DECISION_JSON,
    report_path: Path = REPORT,
    created_at: str | None = None,
) -> dict[str, Any]:
    _validate_weight(horizon_family_weight, "horizon_family_weight")
    _validate_weight(family_worst_weight, "family_worst_weight")
    if not ROBUST_RESULTS.exists() or not HORIZON_RESULTS.exists():
        raise FileNotFoundError("Run robust-search and horizon-audit before synthesis")
    ensure_engine_layout()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    robust = load_json_artifact(ROBUST_RESULTS, "global robust-search results")
    horizon = load_json_artifact(HORIZON_RESULTS, "horizon-audit results")
    require_current_forecast(
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
    require_recorded_file(
        horizon,
        ("artifacts", "robust_results_sha256"),
        ROBUST_RESULTS,
        "horizon-audit robust-search input",
    )
    require_recorded_file(
        robust,
        ("artifacts", "global_shortlist_sha256"),
        ROBUST_SHORTLIST,
        "global robust-search shortlist",
    )
    shortlist = load_json_artifact(ROBUST_SHORTLIST, "global robust-search shortlist")
    require_current_forecast(shortlist, CURRENT_FORECAST, "global robust-search shortlist")
    selector_calibration = None
    if SYNTHESIS_SELECTOR_REPLAY.is_file():
        selector_calibration = load_json_artifact(
            SYNTHESIS_SELECTOR_REPLAY, "historical synthesis-selector replay"
        )
        production = selector_calibration.get("production_configuration") or {}
        calibrated_horizon = float(production.get("horizon_family_weight", -1.0))
        calibrated_worst = float(production.get("family_worst_weight", -1.0))
        if not (
            abs(calibrated_horizon - horizon_family_weight) < 1e-12
            and abs(calibrated_worst - family_worst_weight) < 1e-12
        ):
            raise ValueError(
                "Requested synthesis weights differ from the historically gated production "
                "configuration"
            )
    rows = synthesis_rows(
        robust["finalist_metrics"],
        horizon["finalist_metrics"],
        horizon_family_weight=horizon_family_weight,
        family_worst_weight=family_worst_weight,
    )
    intervals = champion_intervals(rows, family_worst_weight=family_worst_weight)
    leader = rows[0]
    leader_id = leader["candidate_id"]
    candidate_sources = {
        candidate["candidate_id"]: candidate for candidate in shortlist["candidates"]
    }
    if leader_id not in candidate_sources:
        raise RuntimeError("Synthesized leader is missing from the checksum-bound robust shortlist")
    selected_candidate = candidate_sources[leader_id]
    forecast_rows, loaded = _load_rows(tuple(range(1, 9)))
    named_squad = _named_squad(selected_candidate, loaded["meta"])
    selected_policy = _policy_variant(
        selected_candidate, forecast_rows, "open", tuple(range(1, 9))
    ).get("transfer_policy", {})

    robust_by_id = {row["candidate_id"]: row for row in robust["finalist_metrics"]}
    horizon_by_id = {row["candidate_id"]: row for row in horizon["finalist_metrics"]}
    long_id = horizon["leader"]["candidate_id"]
    long_global = robust_by_id.get(long_id)
    long_horizon = horizon_by_id[long_id]
    new_horizon = _first_horizon_specific(horizon["finalist_metrics"])
    central = horizon["leader_minus_incumbent_central"]
    historical = horizon["historical_evidence"]
    robust_leader_id = robust["leader"]["candidate_id"]
    if leader_id == robust_leader_id:
        verdict = "The synthesis retains the five-week robust leader."
    elif leader_id == long_id:
        verdict = "The synthesis promotes the eight-week horizon leader."
    else:
        verdict = (
            "The synthesis selects a balanced common finalist rather than either audit-family "
            "leader."
        )
    result = {
        "version": VERSION,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "decision_status": "current_evidence_provisional_until_deadline",
        "decision": {
            "candidate_id": leader_id,
            "display_name": leader["display_name"],
            "formation": leader["gw1_formation"],
            "synthesis_regret": leader["synthesis_regret"],
            "squad": named_squad,
            "candidate": selected_candidate,
            "transfer_policy": selected_policy,
        },
        "method": {
            "horizon_family_weight": horizon_family_weight,
            "robust_family_weight": 1.0 - horizon_family_weight,
            "family_worst_weight": family_worst_weight,
            "weighted_family_weight": 1.0 - family_worst_weight,
            "formula": (
                "(1-family_worst_weight) * weighted audit-family regret + "
                "family_worst_weight * maximum audit-family regret"
            ),
            "reason": (
                "The five-week audit owns scoring-environment and component-model stress; the "
                "eight-week audit owns horizon, decay, late-fixture and transfer-timing stress. "
                "They receive equal prior weight, with a minimax surcharge for family brittleness."
            ),
            "historical_selector_calibration": (
                {
                    "verdict": selector_calibration["verdict"],
                    "production_changed": selector_calibration["production_changed"],
                    "selection_seasons": selector_calibration["selection_seasons"],
                    "untouched_test_season": selector_calibration["untouched_test_season"],
                    "untouched_test_delta": selector_calibration["untouched_test_delta"],
                    "path": str(SYNTHESIS_SELECTOR_REPLAY),
                    "sha256": sha256_file(SYNTHESIS_SELECTOR_REPLAY),
                }
                if selector_calibration is not None
                else None
            ),
        },
        "candidate_coverage": {
            "robust_finalists": len(robust["finalist_metrics"]),
            "horizon_finalists": len(horizon["finalist_metrics"]),
            "common_finalists": len(rows),
            "horizon_specific_deep_finalists": sum(
                any(
                    str(origin).startswith(("horizon-optimizer", "horizon-neighbour"))
                    for origin in row["origin_ids"]
                )
                for row in horizon["finalist_metrics"]
            ),
            "horizon_optimizer_candidates": horizon["funnel"]["horizon_specific_candidates"],
            "protected_horizon_neighbours": horizon["funnel"].get(
                "protected_horizon_neighbours", 0
            ),
            "best_horizon_specific_finalist": new_horizon,
            "coverage_caveat": (
                "The synthesis ranking is restricted to squads deeply evaluated by both audit "
                "families. Horizon-only finalists are reported separately and are not assigned "
                "unmeasured five-week robustness scores."
            ),
        },
        "audit_family_leaders": {
            "five_week_robust": robust["leader"],
            "eight_week_horizon": horizon["leader"],
        },
        "long_horizon_challenger": {
            "candidate_id": long_id,
            "central_eight_week_delta": central,
            "five_week_robust": long_global,
            "eight_week_horizon": long_horizon,
        },
        "selected_family_metrics": {
            "five_week_robust": robust_by_id[leader_id],
            "eight_week_horizon": horizon_by_id[leader_id],
        },
        "ranking": rows,
        "horizon_weight_champion_intervals": intervals,
        "historical_evidence": historical,
        "source_artifacts": {
            "robust_results": str(ROBUST_RESULTS),
            "robust_results_sha256": sha256_file(ROBUST_RESULTS),
            "horizon_results": str(HORIZON_RESULTS),
            "horizon_results_sha256": sha256_file(HORIZON_RESULTS),
            "robust_shortlist": str(ROBUST_SHORTLIST),
            "robust_shortlist_sha256": sha256_file(ROBUST_SHORTLIST),
        },
        "verdict": verdict,
        "deadline_rule": (
            "This is not a lock. Refresh availability, price, forecast and fixture inputs and rerun "
            "both audit families plus this synthesis immediately before the GW1 deadline."
        ),
    }
    for path in (results_path, decision_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    results_path.write_text(rendered, encoding="utf-8")
    decision_path.write_text(rendered, encoding="utf-8")
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    decision = result["decision"]
    selected_g = result["selected_family_metrics"]["five_week_robust"]
    selected_h = result["selected_family_metrics"]["eight_week_horizon"]
    challenger = result["long_horizon_challenger"]
    challenger_g = challenger["five_week_robust"]
    challenger_h = challenger["eight_week_horizon"]
    historical = result["historical_evidence"]
    intervals = result["horizon_weight_champion_intervals"]
    selected_interval = next(
        interval for interval in intervals if interval["candidate_id"] == decision["candidate_id"]
    )
    squad = decision["squad"]
    starters_by_position = {
        position: [row for row in squad["starters"] if row["position"] == position]
        for position in ("GK", "DEF", "MID", "FWD")
    }

    def label(row: dict[str, Any]) -> str:
        suffix = " (C)" if row["captain"] else " (V)" if row["vice_captain"] else ""
        return f"{row['name']}{suffix}"

    high_goal = challenger_g["scenario_regrets"]["high_goal_open"] if challenger_g else None
    challenger_synthesis = next(
        (
            row["synthesis_regret"]
            for row in result["ranking"]
            if row["candidate_id"] == challenger["candidate_id"]
        ),
        None,
    )
    horizon_table_row = (
        f"| Horizon leader {challenger['candidate_id']} | {challenger_g['robust_regret']:.3f} | "
        f"{challenger_h['robust_regret']:.3f} | "
        f"{max(challenger_g['robust_regret'], challenger_h['robust_regret']):.3f} | "
        f"{challenger_synthesis:.3f} |"
        if challenger_g is not None and challenger_synthesis is not None
        else (
            f"| Horizon leader {challenger['candidate_id']} | not jointly tested | "
            f"{challenger_h['robust_regret']:.3f} | — | — |"
        )
    )
    new_horizon = result["candidate_coverage"]["best_horizon_specific_finalist"]
    lines = [
        "# GW1 decision synthesis: how far should we look ahead?",
        "",
        f"**Built:** {result['created_at']}<br>",
        f"**Decision:** select **{decision['candidate_id']}** · {decision['display_name']}<br>",
        f"**Status:** {result['decision_status']}",
        "",
        "## Bottom line",
        "",
        (
            "Five gameweeks on their own are too short. Eight equally trusted gameweeks are too "
            "confident about information we do not yet possess. The working outset is therefore "
            "GW1–8 with explicit decay, plus separate GW1–3, GW1–5, GW6–8, fixed-squad and forced-"
            "GW2-bank views. That horizon audit is then balanced against the original component-"
            "model and scoring-environment stress family."
        ),
        "",
        (
            f"The longer-horizon audit prefers **{challenger['candidate_id']}** by "
            f"{challenger['central_eight_week_delta']['mean_delta']:+.3f} decayed points over "
            "GW1–8. That is a real result, but not a large enough one to ignore model risk. "
            + (
                f"The challenger is {high_goal:.2f} points off the best squad in the open-transfer "
                "high-goal stress. "
                if high_goal is not None
                else ""
            )
            + f"The selected squad is {selected_h['scenario_regrets']['gw1_8_open_d088']:.2f} "
            "points off the central eight-week optimum and has the lowest declared synthesis "
            "regret across the jointly tested field."
        ),
        "",
        "## The decision in numbers",
        "",
        "| Squad | Five-week robust regret | Eight-week horizon regret | Worst family | Synthesis |",
        "|---|---:|---:|---:|---:|",
        (
            f"| Selected {decision['candidate_id']} | {selected_g['robust_regret']:.3f} | "
            f"{selected_h['robust_regret']:.3f} | "
            f"{max(selected_g['robust_regret'], selected_h['robust_regret']):.3f} | "
            f"{decision['synthesis_regret']:.3f} |"
        ),
        horizon_table_row,
        "",
        (
            f"With the declared family weights, the selected squad ranks first of "
            f"{result['candidate_coverage']['common_finalists']} jointly tested squads. The exact "
            f"weight-sensitivity envelope keeps it champion while horizon-family weight is between "
            f"{selected_interval['lower']:.1%} and {selected_interval['upper']:.1%}. Outside that "
            "interval a different finalist becomes preferable; the receipt records every switch."
        ),
        "",
        "## Why eight weeks, but decayed",
        "",
        (
            "The central decay is 0.88 per gameweek: GW1 receives weight 1.00 and GW8 receives "
            "0.41. Alternative eight-week views use 0.70, 0.80 and 0.94 decay, while a separate "
            "GW6–8 scenario gives those late fixtures equal weight. The answer therefore cannot "
            "depend on one convenient decay constant."
        ),
        "",
        "The historical evidence does not support either extreme:",
        "",
        (
            "- In the public 2019/20 elite top-ten trail, the median manager still held 13 of the "
            "original 15 players in GW3, but only 6.5 by GW6 and 5.5 by GW8."
        ),
        (
            "- That drop is not pure planned transfer activity: two of ten managers wildcarded in "
            "GW2 and four wildcarded in GW4."
        ),
        (
            "- In the richer 2025/26 top-100 decision trail, 61 managers rolled in GW2, then only "
            "22 rolled in GW3 and 19 in GW4. The observable pattern is early optionality followed "
            "by adaptation—not selecting a rigid eight-week XI on day one."
        ),
        "",
        f"**Evidence limitation:** {historical['caveat']}",
        "",
        "## Is the squad tied to an easy opening run?",
        "",
        (
            f"The selected squad is {selected_h['scenario_regrets']['gw6_8_open_equal']:.2f} "
            "points off the best candidate when GW1–5 are discarded and only GW6–8 count. It is "
            f"{selected_h['scenario_regrets']['gw1_8_roll_gw2_d088']:.2f} points off the best when a "
            f"GW2 transfer is forbidden, and {selected_h['scenario_regrets']['gw1_8_fixed_d088']:.2f} "
            "points off the best fixed-squad candidate. These values expose, rather than hide, "
            "its dependence on the opening schedule."
        ),
        "",
        "## What the horizon test still cannot know",
        "",
        (
            "The transfer optimiser respects the live free-transfer bank and maximum carry, and it "
            "never spends points on hits. It does not model future price changes. Its open path is "
            "the best sequence under today's forecasts—not a claim to know the injuries, roles and "
            "form evidence that will arrive after GW1. Fixed-squad and forced-bank scenarios are "
            "included precisely so that this imperfect future execution cannot manufacture the "
            "winner."
        ),
        "",
        "## Current GW1 team",
        "",
    ]
    for position in ("GK", "DEF", "MID", "FWD"):
        lines.append(
            f"- **{position}:** {', '.join(label(row) for row in starters_by_position[position])}"
        )
    lines.extend(
        [
            f"- **Bench:** {', '.join(label(row) for row in squad['bench'])}",
            f"- **Budget:** £{squad['budget_spent']:.1f}m spent; £{squad['bank']:.1f}m bank",
            "",
            "## What changed because of this review",
            "",
            (
                "The five-week winner was not accepted on faith. We added "
                f"{result['candidate_coverage']['horizon_optimizer_candidates']} horizon-optimizer "
                "squads plus "
                f"{result['candidate_coverage']['protected_horizon_neighbours']} protected legal "
                "neighbours, carried all robust finalists forward, and evaluated the combined "
                "field in 5,000 "
                "selection worlds, and sent 48 through 25,000 untouched GW1–8 worlds. Every finalist "
                "received fixed, open-transfer and forced-GW2-bank policies. "
                f"{result['candidate_coverage']['horizon_specific_deep_finalists']} newly generated "
                "horizon squads reached the deep final."
            ),
            "",
            (
                f"The best new horizon-only finalist was "
                f"{new_horizon['candidate_id'] if new_horizon else 'not available'}"
                + (
                    f" with horizon robust regret {new_horizon['robust_regret']:.3f}. "
                    if new_horizon
                    else ". "
                )
                + "The final choice comes from the common field because only those squads have "
                "measured regret in both independent audit families."
            ),
            "",
            "## Decision rule",
            "",
            f"{result['deadline_rule']}",
            "",
            (
                "Source machine receipts: `data/model/gw1_decision_synthesis_v1/results.json`, "
                "`data/model/robust_search_v2_global/results.json`, and "
                "`data/model/horizon_audit_v1/results.json`."
            ),
            "",
        ]
    )
    return "\n".join(lines)
