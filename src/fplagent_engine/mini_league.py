from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .paths import MODEL_DATA, REPORTS, ROOT

VERSION = "mini_league_strategy_shadow_v1"
CONTEXT_VERSION = "mini_league_context_v1"
DEFAULT_CONTEXT = ROOT / "data" / "web" / "state" / "mini-league-context.json"
OUTPUT_ROOT = MODEL_DATA / VERSION
REPORT_ROOT = REPORTS / "mini-league"


class MiniLeagueStrategyError(ValueError):
    """Mini-league context is incomplete, stale or inconsistent with the decision."""


def _aware(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MiniLeagueStrategyError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise MiniLeagueStrategyError(f"{label} must include a timezone")
    return parsed


def _lineup(summary: dict[str, Any], event: int) -> dict[str, Any]:
    rows = summary.get("event_lineups")
    matches = [row for row in rows or [] if int(row.get("event", -1)) == event]
    if len(matches) != 1:
        raise MiniLeagueStrategyError(
            f"action {summary.get('action_id')} lacks one event-{event} lineup"
        )
    return matches[0]


def _multipliers(starters: list[int], captain: int) -> dict[int, float]:
    output = {element: 1.0 for element in starters}
    if captain not in output:
        raise MiniLeagueStrategyError("captain must be in the starting XI")
    output[captain] += 1.0
    return output


def _target_rival(context: dict[str, Any]) -> dict[str, Any]:
    rivals = list(context["rivals"])
    requested = context.get("target_entry_id")
    if requested is not None:
        matches = [row for row in rivals if int(row["entry_id"]) == int(requested)]
        if len(matches) != 1:
            raise MiniLeagueStrategyError("target_entry_id is absent from rivals")
        return matches[0]
    own_points = int(context["own_total_points"])
    leaders = [row for row in rivals if int(row["total_points"]) >= own_points]
    if leaders:
        return max(leaders, key=lambda row: (int(row["total_points"]), -int(row["entry_id"])))
    return max(rivals, key=lambda row: (int(row["total_points"]), -int(row["entry_id"])))


def evaluate_mini_league_shadow(
    decision: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    if decision.get("version") not in {"weekly_decision_synthesis_v3", "weekly_decision_synthesis_v4"}:
        raise MiniLeagueStrategyError("mini-league shadow needs a weekly decision v3")
    if context.get("version") != CONTEXT_VERSION:
        raise MiniLeagueStrategyError("mini-league context has an unsupported version")
    event = int(decision["decision_event"])
    if int(context.get("decision_event", -1)) != event:
        raise MiniLeagueStrategyError("mini-league context event does not match the decision")
    if int(context.get("source_event", -1)) != event - 1:
        raise MiniLeagueStrategyError("rival lineups must come from the immediately prior event")
    observed = _aware(str(context["observed_at"]), "context observed_at")
    created = _aware(str(decision["created_at"]), "decision created_at")
    if observed > created:
        raise MiniLeagueStrategyError("mini-league context was observed after the decision")
    rivals = context.get("rivals")
    if not isinstance(rivals, list) or not rivals:
        raise MiniLeagueStrategyError("mini-league context needs at least one rival")
    forecast = decision.get("event_player_forecasts")
    if not isinstance(forecast, dict) or not forecast:
        raise MiniLeagueStrategyError("weekly decision lacks frozen player forecasts")
    xp = {int(element): float(row["expected_points"]) for element, row in forecast.items()}
    rival_multipliers = []
    for rival in rivals:
        starters = list(map(int, rival["starter_player_ids"]))
        if len(starters) != 11 or len(set(starters)) != 11:
            raise MiniLeagueStrategyError("each rival needs 11 unique prior-event starters")
        rival_multipliers.append(_multipliers(starters, int(rival["captain_player_id"])))
    target = _target_rival(context)
    own_points = int(context["own_total_points"])
    gap = int(target["total_points"]) - own_points
    remaining_events = 39 - event
    if event < 31:
        mode = "points_first_early_season"
    elif gap > 5:
        mode = "chasing"
    elif gap < -5:
        mode = "protecting"
    else:
        mode = "balanced_close_race"
    pressure = min(abs(gap) / max(remaining_events, 1), 20.0) / 20.0
    risk_weight = 0.0 if event < 31 else 0.12 * pressure
    if mode == "chasing":
        sacrifice_cap = min(2.0, 0.25 + 0.15 * abs(gap) / max(remaining_events, 1))
    elif mode == "protecting":
        sacrifice_cap = min(0.75, 0.10 + 0.05 * abs(gap) / max(remaining_events, 1))
    else:
        sacrifice_cap = 0.0 if event < 31 else 0.25
    rows = []
    for summary in decision["action_summaries"]:
        lineup = _lineup(summary, event)
        starters = list(map(int, lineup["starter_player_ids"]))
        multipliers = _multipliers(starters, int(lineup["captain_player_id"]))
        relevant = set(multipliers) | {
            element for rival in rival_multipliers for element in rival if element in xp
        }
        missing = set(multipliers) - set(xp)
        if missing:
            raise MiniLeagueStrategyError(
                f"action contains players missing frozen forecasts: {sorted(missing)}"
            )
        distance = 0.0
        protection = 0.0
        for element in relevant:
            rival_average = sum(row.get(element, 0.0) for row in rival_multipliers) / len(
                rival_multipliers
            )
            own_multiplier = multipliers.get(element, 0.0)
            player_xp = xp.get(element, 0.0)
            distance += player_xp * abs(own_multiplier - rival_average)
            protection += player_xp * min(own_multiplier, rival_average)
        expected_net = float(lineup["projected_points"]) - int(
            summary["incremental_points_cost"]
        )
        rows.append(
            {
                "action_id": str(summary["action_id"]),
                "route_type": str(summary["route_type"]),
                "expected_net_points": expected_net,
                "rival_exposure_distance": distance,
                "rival_protection_exposure": protection,
            }
        )
    best_expected = max(row["expected_net_points"] for row in rows)
    for row in rows:
        row["expected_points_sacrifice"] = best_expected - row["expected_net_points"]
        row["within_sacrifice_cap"] = row["expected_points_sacrifice"] <= sacrifice_cap + 1e-9
        if mode == "chasing":
            adjustment = risk_weight * row["rival_exposure_distance"]
        elif mode == "protecting":
            adjustment = -risk_weight * row["rival_exposure_distance"]
        else:
            adjustment = 0.0
        row["shadow_utility"] = row["expected_net_points"] + adjustment
    eligible = [row for row in rows if row["within_sacrifice_cap"]]
    shadow = max(eligible, key=lambda row: (row["shadow_utility"], row["action_id"]))
    baseline = str(decision["selected_action_id"])
    return {
        "version": VERSION,
        "status": "not_applicable_early_season" if event < 31 else "ready_shadow",
        "decision_event": event,
        "decision_authority": False,
        "operational_recommendation": baseline,
        "points_first_action_id": baseline,
        "shadow_preference": shadow["action_id"],
        "shadow_differs_from_points_first": shadow["action_id"] != baseline,
        "mode": mode,
        "target_rival": {
            "entry_id": int(target["entry_id"]),
            "name": str(target.get("name") or target["entry_id"]),
            "points_gap_rival_minus_manager": gap,
        },
        "remaining_events_including_decision": remaining_events,
        "risk_weight": risk_weight,
        "expected_points_sacrifice_cap": sacrifice_cap,
        "actions": sorted(rows, key=lambda row: (-row["shadow_utility"], row["action_id"])),
        "promotion_gate": {
            "passed": False,
            "historical_rank_simulation_required": True,
            "prospective_league_receipts_required": True,
        },
        "interpretation": (
            "Prior-event rival lineups are uncertainty context, not knowledge of their next move. "
            "The points-first action remains operational until rank simulations and prospective "
            "mini-league receipts validate this shadow."
        ),
    }


def _render(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Mini-league strategy shadow — GW{result['decision_event']}",
            "",
            f"Mode: **{result['mode']}** · authority: **none**",
            "",
            f"Points-first action: `{result['points_first_action_id']}`",
            f"Shadow preference: `{result['shadow_preference']}`",
            "",
            (
                f"Target gap: {result['target_rival']['points_gap_rival_minus_manager']:+d} "
                f"points; allowed expected-points sacrifice: "
                f"{result['expected_points_sacrifice_cap']:.2f}."
            ),
            "",
            result["interpretation"],
            "",
        ]
    )


def run_mini_league_shadow(
    decision_path: Path,
    context_path: Path,
    *,
    output_root: Path = OUTPUT_ROOT,
    report_root: Path = REPORT_ROOT,
) -> dict[str, Any]:
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    result = evaluate_mini_league_shadow(decision, context)
    identity = f"{sha256_file(decision_path)}:{sha256_file(context_path)}"
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    event = int(result["decision_event"])
    output_path = output_root / f"event-{event}" / f"{fingerprint}.json"
    report_path = report_root / f"event-{event}-{fingerprint[:12]}.md"
    result["source_artifacts"] = {
        "decision": str(decision_path),
        "decision_sha256": sha256_file(decision_path),
        "context": str(context_path),
        "context_sha256": sha256_file(context_path),
    }
    result["receipt_path"] = str(output_path)
    result["report_path"] = str(report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise MiniLeagueStrategyError("immutable mini-league receipt collision")
    if not output_path.exists():
        temporary = output_path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = _render(result)
    if not report_path.exists():
        temporary_report = report_path.with_suffix(".md.tmp")
        temporary_report.write_text(report, encoding="utf-8")
        temporary_report.replace(report_path)
    return {**result, "receipt_sha256": sha256_file(output_path)}
