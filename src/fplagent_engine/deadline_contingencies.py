from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .artifact_lineage import ArtifactLineageError, load_json_artifact
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .participation_break_even import (
    RESULTS_JSON as BREAK_EVEN_RESULTS,
)
from .participation_break_even import _candidate_names
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .preseason_role_scenario import RESULTS_JSON as ROLE_SCENARIO_RESULTS
from .preseason_role_threshold import reconstruct_named_configuration
from .robust_search import SHORTLIST_JSON
from .rules import load_rules, validate_lineup, validate_squad
from .tournament import _load_rows

VERSION = "deadline_contingencies_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "gw1-deadline-contingencies.md"
EVENT = 1


def validate_named_route(route: dict[str, Any], meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    selected = [int(row["element"]) for row in route["selected"]]
    squad_rows = [meta[element] for element in selected]
    rules = load_rules()
    validate_squad(squad_rows, rules)
    validate_lineup(
        squad_rows,
        route["starter_elements"],
        route["bench_elements"],
        int(route["captain_element"]),
        int(route["vice_captain_element"]),
        rules,
    )
    spend_tenths = round(sum(float(meta[element]["market_price"]) for element in selected))
    if spend_tenths != round(float(route["budget"]) * 10.0):
        raise ValueError("contingency budget differs from current official player prices")
    if spend_tenths > rules.budget:
        raise ValueError("contingency exceeds the official budget")
    return {
        "legal": True,
        "players": len(selected),
        "budget": spend_tenths / 10.0,
        "bank": (rules.budget - spend_tenths) / 10.0,
        "position_counts": dict(
            sorted(Counter(str(meta[element]["position"]) for element in selected).items())
        ),
        "maximum_club_count": max(
            Counter(int(meta[element]["team_id"]) for element in selected).values()
        ),
    }


def _call_name(label: str, route: dict[str, Any]) -> str:
    captain = str(route["captain"]).split()[-1]
    return f"{label} · {route['formation']} · {captain} C"


def _supported_fallback(player: dict[str, Any]) -> dict[str, Any] | None:
    boundary = player.get("boundary") or {}
    if (
        boundary.get("classification") != "challenger_boundary_bracketed"
        or boundary.get("actionable") is not True
    ):
        return None
    threshold = float(boundary["highest_supported_challenger_minutes"])
    supported = [
        point
        for point in player["points"]
        if point.get("deep_squad_replay") is not None
        and point["deep_squad_replay"].get("cross_family_holdout_support") is True
        and float(point["target_expected_minutes"]) <= threshold
    ]
    if not supported:
        return None
    return max(supported, key=lambda point: float(point["target_expected_minutes"]))


def _synthesis_tradeoff(
    decision: dict[str, Any],
    *,
    challenger_id: str,
    replay: dict[str, Any],
) -> dict[str, Any]:
    ranking = {
        str(row["candidate_id"]): row for row in decision.get("ranking") or []
    }
    selected_id = str(decision["decision"]["candidate_id"])
    if selected_id not in ranking or challenger_id not in ranking:
        raise ArtifactLineageError("contingency candidates are missing synthesis rankings")
    selected_regret = float(ranking[selected_id]["synthesis_regret"])
    challenger_regret = float(ranking[challenger_id]["synthesis_regret"])
    regret_delta = challenger_regret - selected_regret
    deltas = replay["holdout_delta_challenger_to_incumbent"]
    minimum_gw1_gain = min(float(deltas[family]["mean"]) for family in ("residual", "component"))
    net_margin = minimum_gw1_gain - regret_delta
    return {
        "minimum_gw1_holdout_gain": minimum_gw1_gain,
        "multiweek_synthesis_regret_delta": regret_delta,
        "net_declared_margin": net_margin,
        "actionable": minimum_gw1_gain > 0.0 and net_margin >= 0.0,
    }


def build_deadline_contingencies(
    *,
    break_even_path: Path = BREAK_EVEN_RESULTS,
    scenario_path: Path = ROLE_SCENARIO_RESULTS,
    decision_path: Path = SYNTHESIZED_DECISION,
    shortlist_path: Path = SHORTLIST_JSON,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    ensure_engine_layout()
    break_even = load_json_artifact(break_even_path, "participation break-even audit")
    scenario = load_json_artifact(scenario_path, "preseason role scenario audit")
    decision = load_json_artifact(decision_path, "synthesized GW1 decision")
    shortlist = load_json_artifact(shortlist_path, "global robust-search shortlist")
    if break_even.get("version") != "participation_break_even_v1":
        raise ArtifactLineageError("unsupported participation break-even contract")
    decision_sha = sha256_file(decision_path)
    if (break_even.get("lineage") or {}).get("decision_sha256") != decision_sha:
        raise ArtifactLineageError("participation break-even uses a stale decision")
    current_id = str(decision["decision"]["candidate_id"])
    if str(break_even.get("decision_candidate_id")) != current_id:
        raise ArtifactLineageError("break-even and synthesized decisions disagree")

    _, loaded = _load_rows((EVENT,))
    meta = loaded["meta"]
    current_route = dict(break_even["decision"])
    current_check = validate_named_route(current_route, meta)
    routes: list[dict[str, Any]] = [
        {
            "route_id": "central",
            "call_name": _call_name("Central", current_route),
            "status": "current_recommendation",
            "trigger": "No material evidence moves a watched player across a tested boundary.",
            "source": "synthesized_decision",
            "route": current_route,
            "validation": current_check,
        }
    ]

    for player in break_even["players"].values():
        fallback = _supported_fallback(player)
        if fallback is None:
            boundary = player.get("boundary") or {}
            causal_note = (
                "A GW1 challenger already exists at the live production anchor, so it is a "
                "known multiweek trade-off rather than a causal minute threshold."
                if boundary.get("classification")
                == "general_gw1_challenger_at_production_anchor"
                else "No causal, monotone roster reversal exists on the tested minute path."
            )
            routes.append(
                {
                    "route_id": f"{int(player['element'])}-watch",
                    "call_name": f"{player['name']} watch · retain central",
                    "status": "monitor_only",
                    "trigger": (
                        f"{player['name']} role evidence changes: {causal_note} Run the complete "
                        "pipeline again before changing the squad."
                    ),
                    "source": "isolated_minutes_break_even",
                    "threshold": player["boundary"],
                    "route": current_route,
                    "validation": current_check,
                }
            )
            continue
        replay = fallback["deep_squad_replay"]
        route = dict(replay["challenger"])
        route["squad_id"] = str(replay["challenger_squad_id"])
        validation = validate_named_route(route, meta)
        threshold = float(fallback["target_expected_minutes"])
        tradeoff = _synthesis_tradeoff(
            decision,
            challenger_id=str(replay["challenger_squad_id"]),
            replay=replay,
        )
        actionable = tradeoff["actionable"] is True
        routes.append(
            {
                "route_id": f"{int(player['element'])}-minutes",
                "call_name": _call_name(f"{player['name']} ≤{threshold:.0f}m", route),
                "status": "precomputed_fallback" if actionable else "monitor_only",
                "trigger": (
                    f"Attributable deadline evidence places {player['name']} at or below "
                    f"the causal {threshold:.0f}-minute boundary."
                    if actionable
                    else (
                        f"Evidence reaches the causal {threshold:.0f}-minute boundary, but "
                        "the GW1 gain does not repay the alternative's multiweek regret; "
                        "rerun the complete pipeline before changing the squad."
                    )
                ),
                "source": "isolated_minutes_break_even",
                "threshold": player["boundary"],
                "holdout_delta": replay["holdout_delta_challenger_to_incumbent"],
                "synthesis_tradeoff": tradeoff,
                "route": route,
                "validation": validation,
            }
        )

    combined = (scenario.get("scenarios") or {}).get("severe_role_stress") or {}
    replay = combined.get("deep_squad_replay")
    if replay and replay.get("cross_family_holdout_support") is True:
        challenger_id = str(replay["challenger_squad_id"])
        by_id = {str(candidate["candidate_id"]): candidate for candidate in shortlist["candidates"]}
        if challenger_id not in by_id:
            raise ArtifactLineageError("combined-stress challenger is missing from shortlist")
        challenger = by_id[challenger_id]
        normalized = reconstruct_named_configuration(
            list(map(int, challenger["selected"])),
            replay["challenger_configuration"],
            meta,
        )
        route = _candidate_names(normalized, meta)
        route["squad_id"] = challenger_id
        tradeoff = _synthesis_tradeoff(
            decision,
            challenger_id=challenger_id,
            replay=replay,
        )
        actionable = tradeoff["actionable"] is True
        routes.append(
            {
                "route_id": "combined-severe-role",
                "call_name": _call_name("Combined role stress", route),
                "status": "precomputed_fallback" if actionable else "monitor_only",
                "trigger": (
                    "Multiple watched participation assumptions weaken together to the "
                    "declared severe-role stress boundary."
                    if actionable
                    else (
                        "The severe-role GW1 challenger does not repay its multiweek regret; "
                        "rerun the complete pipeline if multiple assumptions weaken."
                    )
                ),
                "source": "joint_role_scenario",
                "scenario": "severe_role_stress",
                "holdout_delta": replay["holdout_delta_challenger_to_incumbent"],
                "synthesis_tradeoff": tradeoff,
                "route": route,
                "validation": validate_named_route(route, meta),
            }
        )

    result = {
        "version": VERSION,
        "event": EVENT,
        "decision_candidate_id": current_id,
        "routes": routes,
        "summary": {
            "routes": len(routes),
            "precomputed_fallbacks": sum(
                route["status"] == "precomputed_fallback" for route in routes
            ),
            "monitor_only": sum(route["status"] == "monitor_only" for route in routes),
            "all_legal": all(route["validation"]["legal"] for route in routes),
            "all_actionable_routes_repay_multiweek_regret": all(
                route["status"] != "precomputed_fallback"
                or (route.get("synthesis_tradeoff") or {}).get("actionable") is True
                for route in routes
            ),
        },
        "lineage": {
            "decision_sha256": decision_sha,
            "break_even_sha256": sha256_file(break_even_path),
            "role_scenario_sha256": sha256_file(scenario_path),
            "global_shortlist_sha256": sha256_file(shortlist_path),
        },
        "decision_rule": (
            "Use only a precomputed fallback whose trigger is supported by fresh attributable "
            "evidence. Otherwise retain the central route. Every route is a complete legal FPL "
            "squad, XI, ordered bench, captain and vice-captain at current prices."
        ),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# GW1 executable deadline contingencies",
        "",
        result["decision_rule"],
        "",
    ]
    for route in result["routes"]:
        squad = route["route"]
        lines.extend(
            [
                f"## {route['call_name']}",
                "",
                f"**{route['status']}** — {route['trigger']}",
                "",
                (
                    f"Budget £{route['validation']['budget']:.1f}m · bank "
                    f"£{route['validation']['bank']:.1f}m · `{squad['squad_id']}`."
                ),
                "",
                "| XI | Bench |",
                "| --- | --- |",
                (
                    "| "
                    + ", ".join(squad["starters"])
                    + " | "
                    + " → ".join(squad["bench_order"])
                    + " |"
                ),
                "",
                f"Captain **{squad['captain']}** · vice **{squad['vice_captain']}**.",
                "",
            ]
        )
    return "\n".join(lines)
