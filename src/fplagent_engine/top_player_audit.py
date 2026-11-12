from __future__ import annotations

import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.participation_consensus import CONSENSUS as PARTICIPATION_CONSENSUS
from fplagent_data.participation_consensus import RECEIPT as PARTICIPATION_RECEIPT

from .availability_watch import PLAYERS as OFFICIAL_PLAYERS
from .capital_efficiency import (
    STARTER_MINUTES,
    candidate_capital_role_risks,
    candidate_publication_role_risks,
    capital_role_risk_requires_publication_block,
)
from .decision_synthesis import DECISION_JSON
from .market_feature_challenger import ATTACKER_RESULTS
from .models import CURRENT_FORECAST
from .participation_policy import (
    _appearance_points,
    _expected_minutes,
    _probabilities,
    _target_distribution,
)
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import RESULT_DIR as ROBUST_RESULT_DIR
from .robust_search import RESULTS_JSON as ROBUST_RESULTS

VERSION = 2
OUTPUT_DIR = MODEL_DATA / "top_player_omission_audit_v1"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "top-player-omission-audit.md"
SHORTLIST = ROBUST_RESULT_DIR / "shortlist.json"
EVENT = 1
TOP_BAND = 15


class TopPlayerAuditError(ValueError):
    """The important-player omission audit could not establish coherent evidence."""


def selected_role_watch_required(row: dict[str, Any]) -> bool:
    """Return whether a selected player has a material role assumption to reverify.

    Positive one-source starts are useful supporting evidence, not a reason to label every member
    of a squad unresolved. Negative or contradictory evidence is always watched. Missing coverage
    becomes actionable only when the underlying play probability or expected minutes is already
    below the position's starter-grade floor.
    """

    consensus = str(row.get("participation_consensus") or "not_covered")
    if consensus in {
        "source_disagreement",
        "predicted_bench_consensus",
        "single_source_bench",
    }:
        return True
    if consensus not in {"insufficient_coverage", "not_covered"}:
        return False
    position = str(row.get("position") or "")
    return float(row.get("p_play") or 0.0) < 0.85 or float(
        row.get("expected_minutes") or 0.0
    ) < STARTER_MINUTES.get(position, 55.0)


def _publication_synthesis_metrics(
    ranking: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return only challengers that are legal to beat the published decision."""

    return {
        str(row["candidate_id"]): dict(row)
        for row in ranking
        if bool(row.get("publication_eligible", True))
    }


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise TopPlayerAuditError(f"missing {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TopPlayerAuditError(f"invalid {label}: expected a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _full_start_counterfactual(row: dict[str, Any]) -> tuple[float, float]:
    target, _, _ = _target_distribution(
        {
            "official_status": "clear",
            "official_chance": 100,
            "consensus": "predicted_start_consensus",
        },
        row,
    )
    if target is None:
        return float(row["expected_points"]), _expected_minutes(_probabilities(row))
    current = _probabilities(row)
    old_minutes = _expected_minutes(current)
    new_minutes = _expected_minutes(target)
    ratio = min(max(new_minutes / max(old_minutes, 5.0), 0.35), 2.0)
    expected_points = (
        _appearance_points(target)
        + (float(row["expected_points"]) - _appearance_points(current)) * ratio
    )
    return max(expected_points, 0.0), new_minutes


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# GW1 top-player omission audit",
        "",
        f"Generated: {result['created_at']}",
        f"Verdict: **{result['verdict']}**",
        "",
        (
            "This audit exists to stop an important player disappearing because of a bad minutes "
            "estimate, a source-mapping mistake or an early search cut. A missing star is acceptable "
            "only when the evidence and the best deeply tested squad containing him are visible."
        ),
        "",
        "## Publication checks",
        "",
    ]
    for name, passed in result["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend(
        [
            "",
            "## Important omitted players",
            "",
            "| Player | Pos | £ | Own | GW1 xP | Minutes | Role evidence | Best joint XV | Synthesis Δ | Why omitted now |",
            "|---|---:|---:|---:|---:|---:|---|---|---:|---|",
        ]
    )
    for row in result["omissions"]:
        deep = row.get("best_deep_counterfactual") or {}
        role = str(row.get("participation_consensus") or "no consensus")
        if row.get("full_start_counterfactual_xp") is not None:
            role += f"; start case {row['full_start_counterfactual_xp']:.2f} xP"
        lines.append(
            "| {name} | {position} | {price:.1f} | {ownership:.1f}% | {xp:.2f} | "
            "{minutes:.1f} | {role} | {candidate} | {delta} | {reason} |".format(
                name=row["player_name"],
                position=row["position"],
                price=row["price"],
                ownership=row["ownership_percent"],
                xp=row["expected_points"],
                minutes=row["expected_minutes"],
                role=role,
                candidate=deep.get("candidate_id", "NOT DEEPLY TESTED"),
                delta=(
                    f"{float(deep['synthesis_regret_delta']):+.3f}"
                    if deep.get("synthesis_regret_delta") is not None
                    else "—"
                ),
                reason=row["explanation"],
            )
        )
    lines.extend(["", "## Closest legal alternatives", ""])
    if not result["near_misses"]:
        lines.append("No omitted important player finished within +0.500 synthesis regret.")
    for row in result["near_misses"]:
        deep = row["best_deep_counterfactual"]
        lines.append(
            f"- **{row['player_name']}** — {deep['candidate_id']} finished "
            f"{deep['synthesis_regret_delta']:+.3f} behind. Incoming: "
            f"{', '.join(deep['players_in'])}; outgoing: {', '.join(deep['players_out'])}."
        )
    lines.extend(["", "## Premium capital role gate", ""])
    if not result["selected_capital_role_warnings"]:
        lines.append(
            "No selected premium player is below 60 expected minutes or 85% play probability."
        )
    hard_risk_keys = {
        (int(row["element"]), tuple(row["reasons"]))
        for row in result["selected_capital_role_risks"]
    }
    for row in result["selected_capital_role_warnings"]:
        severity = (
            "FAIL" if (int(row["element"]), tuple(row["reasons"])) in hard_risk_keys else "WATCH"
        )
        lines.append(
            f"- **{severity} — {row['player_name']}** costs £{row['price']:.1f}m but carries "
            f"{row['expected_minutes']:.1f} expected minutes and {row['p_play']:.1%} play "
            f"probability ({', '.join(row['reasons'])})."
        )
    lines.extend(["", "## Actionable lineup role gate", ""])
    if not result["selected_action_role_risks"]:
        lines.append("Every starter, armband and active substitute clears its role floor.")
    for row in result["selected_action_role_risks"]:
        lines.append(
            f"- **FAIL — {row['player_name']} / {row.get('action', 'role')}** — "
            f"{row['expected_minutes']:.1f} expected minutes, {row['p_play']:.1%} play "
            f"probability ({', '.join(row['reasons'])})."
        )
    lines.extend(["", "## Selected squad role watch", ""])
    if not result["selected_role_watch"]:
        lines.append("Every selected player has a clear two-source start consensus.")
    for row in result["selected_role_watch"]:
        exclusion = row.get("best_exclusion_counterfactual") or {}
        sensitivity = (
            f" Confirmed-start sensitivity: {row['full_start_counterfactual_xp']:.2f} xP."
            if row.get("full_start_counterfactual_xp") is not None
            else ""
        )
        exclusion_text = (
            f" Best jointly tested XV without him: {exclusion['candidate_id']} "
            f"({exclusion['synthesis_regret_delta']:+.3f} synthesis regret)."
            if exclusion
            else " No jointly tested exclusion XV was available."
        )
        lines.append(
            f"- **{row['player_name']}** — {row['participation_consensus']}; "
            f"{row['p_play']:.1%} play probability and {row['expected_minutes']:.1f} "
            f"expected minutes.{sensitivity}{exclusion_text} Reverify before the deadline."
        )
    lines.extend(
        [
            "",
            "## Role assumptions that could change the decision",
            "",
        ]
    )
    if not result["role_watch"]:
        lines.append("No material predicted-role sensitivity is currently open.")
    for row in result["role_watch"]:
        lines.append(
            f"- **{row['player_name']}**: incumbent {row['expected_points']:.2f} xP / "
            f"{row['expected_minutes']:.1f} minutes; confirmed-start sensitivity "
            f"{row['full_start_counterfactual_xp']:.2f} xP / "
            f"{row['full_start_counterfactual_minutes']:.1f} minutes. "
            f"Consensus: {row['participation_consensus']}. Start: "
            f"{', '.join(row['predicted_start_sources']) or 'none'}; bench: "
            f"{', '.join(row['predicted_not_start_sources']) or 'none'}."
        )
    lines.extend(
        [
            "",
            "## How to read the synthesis delta",
            "",
            (
                "A positive synthesis delta means the best jointly simulated squad containing that "
                "player was worse than the published choice after both five- and eight-week audit "
                "families were combined. It includes the "
                "opportunity cost of the transfers needed to afford the player, captaincy, bench "
                "order, autosubs and the same correlated match worlds—not just the player's "
                "isolated xP."
            ),
            "",
            (
                "The report does not claim an omission can never become wrong. Predicted lineups, "
                "official status and markets are refreshed again before the deadline; any changed "
                "input invalidates this receipt and forces a new decision run."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def run_top_player_omission_audit(
    *,
    forecast_path: Path = CURRENT_FORECAST,
    official_players_path: Path = OFFICIAL_PLAYERS,
    participation_consensus_path: Path = PARTICIPATION_CONSENSUS,
    participation_receipt_path: Path = PARTICIPATION_RECEIPT,
    robust_results_path: Path = ROBUST_RESULTS,
    shortlist_path: Path = SHORTLIST,
    decision_path: Path = DECISION_JSON,
    attacker_market_path: Path = ATTACKER_RESULTS,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    ensure_engine_layout()
    robust = _load(robust_results_path, "robust results")
    shortlist = _load(shortlist_path, "robust shortlist")
    decision = _load(decision_path, "decision")
    participation_receipt = _load(participation_receipt_path, "participation receipt")
    attacker_market = _load(attacker_market_path, "attacker market receipt")
    forecasts = [
        dict(row)
        for row in pq.read_table(forecast_path).to_pylist()
        if int(row["event_number"]) == EVENT
    ]
    official = {
        int(row["id"]): dict(row) for row in pq.read_table(official_players_path).to_pylist()
    }
    consensus = {
        int(row["element"]): dict(row)
        for row in pq.read_table(participation_consensus_path).to_pylist()
        if int(row["event"]) == EVENT
    }
    if len(forecasts) != len({int(row["element"]) for row in forecasts}):
        raise TopPlayerAuditError("GW1 forecast contains duplicate players")

    squad = decision["decision"]["squad"]
    selected = {int(player["element"]) for player in [*squad["starters"], *squad["bench"]]}
    selected_names = {
        int(player["element"]): str(player["name"])
        for player in [*squad["starters"], *squad["bench"]]
    }
    robust_metrics = {str(row["candidate_id"]): dict(row) for row in robust["finalist_metrics"]}
    synthesis_metrics = _publication_synthesis_metrics(decision.get("ranking") or [])
    deep_candidates = [
        dict(candidate)
        for candidate in shortlist["candidates"]
        if str(candidate["candidate_id"]) in robust_metrics
    ]
    deep_by_player: dict[int, list[dict[str, Any]]] = {}
    for candidate in deep_candidates:
        for element in map(int, candidate["selected"]):
            deep_by_player.setdefault(element, []).append(candidate)

    xp_rank = {
        int(row["element"]): rank
        for rank, row in enumerate(
            sorted(forecasts, key=lambda item: float(item["expected_points"]), reverse=True),
            start=1,
        )
    }
    price_rank = {
        int(row["element"]): rank
        for rank, row in enumerate(
            sorted(
                forecasts,
                key=lambda item: int(official[int(item["element"])]["now_cost"]),
                reverse=True,
            ),
            start=1,
        )
    }
    ownership_rank = {
        int(row["element"]): rank
        for rank, row in enumerate(
            sorted(
                forecasts,
                key=lambda item: float(
                    official[int(item["element"])].get("selected_by_percent") or 0.0
                ),
                reverse=True,
            ),
            start=1,
        )
    }
    material_ids = {
        element
        for element in xp_rank
        if xp_rank[element] <= TOP_BAND
        or price_rank[element] <= TOP_BAND
        or ownership_rank[element] <= TOP_BAND
        or element in selected
    }
    robust_leader_regret = float(robust["leader"]["robust_regret"])
    selected_synthesis_regret = float(decision["decision"]["synthesis_regret"])
    player_rows = []
    for forecast in forecasts:
        element = int(forecast["element"])
        if element not in material_ids:
            continue
        player = official[element]
        evidence = consensus.get(element, {})
        probabilities = _probabilities(forecast)
        minutes = _expected_minutes(probabilities)
        candidates = [
            candidate
            for candidate in deep_by_player.get(element, [])
            if str(candidate["candidate_id"]) in synthesis_metrics
        ]
        best = min(
            candidates,
            key=lambda candidate: float(
                synthesis_metrics[str(candidate["candidate_id"])]["synthesis_regret"]
            ),
            default=None,
        )
        deep: dict[str, Any] | None = None
        if best is not None:
            metric = robust_metrics[str(best["candidate_id"])]
            synthesis_metric = synthesis_metrics[str(best["candidate_id"])]
            best_selected = set(map(int, best["selected"]))
            deep = {
                "candidate_id": str(best["candidate_id"]),
                "display_name": str(best["display_name"]),
                "robust_regret": float(metric["robust_regret"]),
                "robust_regret_delta_to_five_week_leader": (
                    float(metric["robust_regret"]) - robust_leader_regret
                ),
                "synthesis_regret": float(synthesis_metric["synthesis_regret"]),
                "synthesis_regret_delta": (
                    float(synthesis_metric["synthesis_regret"]) - selected_synthesis_regret
                ),
                "gw1_expected_points": float(best["lineups"]["1"]["expected_points"]),
                "players_in": [
                    str(official[player_id]["web_name"])
                    for player_id in sorted(best_selected - selected)
                ],
                "players_out": [
                    selected_names[player_id] for player_id in sorted(selected - best_selected)
                ],
            }
        consensus_name = str(evidence.get("consensus") or "insufficient_coverage")
        deep_test_required = bool(
            element not in selected
            and str(evidence.get("official_status") or "clear") != "unavailable"
            and (
                xp_rank[element] <= TOP_BAND
                or price_rank[element] <= TOP_BAND
                or ownership_rank[element] <= TOP_BAND
            )
        )
        full_start_xp = None
        full_start_minutes = None
        if consensus_name in {"source_disagreement", "predicted_bench_consensus"}:
            full_start_xp, full_start_minutes = _full_start_counterfactual(forecast)
        if element in selected:
            explanation = "Selected in the published XV."
        elif str(evidence.get("official_status")) == "unavailable":
            explanation = "Officially unavailable; no legal upside case is assumed."
        elif consensus_name == "predicted_bench_consensus":
            explanation = "Both independent lineup sources predict a bench role."
        elif consensus_name == "source_disagreement":
            explanation = "Lineup sources disagree, so the incumbent role probability is retained."
        elif deep is None and deep_test_required:
            explanation = "No deep counterfactual survived; publication must fail."
        elif deep is None:
            explanation = (
                "Outside the protected top bands; reported for selected-squad transparency."
            )
        else:
            explanation = (
                "The best jointly tested squad containing him lost after the five- and eight-week "
                "families, budget, lineup, autosub and multi-scenario opportunity costs were combined."
            )
        player_rows.append(
            {
                "element": element,
                "player_name": str(forecast["player_name"]),
                "position": str(forecast["position"]),
                "team_name": str(forecast["team_name"]),
                "price": float(player["now_cost"]) / 10.0,
                "ownership_percent": float(player.get("selected_by_percent") or 0.0),
                "expected_points": float(forecast["expected_points"]),
                "robust_points": float(forecast["robust_points"]),
                "p_play": float(forecast["p_play"]),
                "expected_minutes": minutes,
                "xp_rank": xp_rank[element],
                "price_rank": price_rank[element],
                "ownership_rank": ownership_rank[element],
                "selected": element in selected,
                "deep_test_required": deep_test_required,
                "participation_consensus": consensus_name,
                "participation_applied": bool(forecast.get("live_participation_applied")),
                "predicted_start_sources": list(evidence.get("predicted_start_sources") or []),
                "predicted_not_start_sources": list(
                    evidence.get("predicted_not_start_sources") or []
                ),
                "full_start_counterfactual_xp": full_start_xp,
                "full_start_counterfactual_minutes": full_start_minutes,
                "best_deep_counterfactual": deep,
                "explanation": explanation,
            }
        )

    omissions = sorted(
        (row for row in player_rows if not row["selected"]),
        key=lambda row: (
            min(row["xp_rank"], row["price_rank"], row["ownership_rank"]),
            -row["expected_points"],
        ),
    )
    role_watch = sorted(
        (
            row
            for row in omissions
            if row["participation_consensus"]
            in {"source_disagreement", "predicted_bench_consensus"}
            and row["full_start_counterfactual_xp"] is not None
        ),
        key=lambda row: float(row["full_start_counterfactual_xp"]),
        reverse=True,
    )
    near_misses = sorted(
        (
            row
            for row in omissions
            if row.get("best_deep_counterfactual") is not None
            and float(row["best_deep_counterfactual"]["synthesis_regret_delta"]) <= 0.5
        ),
        key=lambda row: float(row["best_deep_counterfactual"]["synthesis_regret_delta"]),
    )
    selected_role_watch = sorted(
        (row for row in player_rows if row["selected"] and selected_role_watch_required(row)),
        key=lambda row: (float(row["p_play"]), float(row["expected_minutes"])),
    )
    joint_candidates = [
        candidate
        for candidate in deep_candidates
        if str(candidate["candidate_id"]) in synthesis_metrics
    ]
    for row in selected_role_watch:
        element = int(row["element"])
        best_exclusion = min(
            (
                candidate
                for candidate in joint_candidates
                if element not in set(map(int, candidate["selected"]))
            ),
            key=lambda candidate: float(
                synthesis_metrics[str(candidate["candidate_id"])]["synthesis_regret"]
            ),
            default=None,
        )
        if best_exclusion is None:
            row["best_exclusion_counterfactual"] = None
            continue
        exclusion_selected = set(map(int, best_exclusion["selected"]))
        exclusion_metric = synthesis_metrics[str(best_exclusion["candidate_id"])]
        row["best_exclusion_counterfactual"] = {
            "candidate_id": str(best_exclusion["candidate_id"]),
            "display_name": str(best_exclusion["display_name"]),
            "synthesis_regret": float(exclusion_metric["synthesis_regret"]),
            "synthesis_regret_delta": (
                float(exclusion_metric["synthesis_regret"]) - selected_synthesis_regret
            ),
            "players_in": [
                str(official[player_id]["web_name"])
                for player_id in sorted(exclusion_selected - selected)
            ],
            "players_out": [
                selected_names[player_id] for player_id in sorted(selected - exclusion_selected)
            ],
        }
    material_excluded = [
        row
        for row in omissions
        if str((consensus.get(int(row["element"])) or {}).get("official_status") or "clear")
        != "unavailable"
        and (
            row["xp_rank"] <= TOP_BAND
            or row["price_rank"] <= TOP_BAND
            or row["ownership_rank"] <= TOP_BAND
        )
    ]
    market_rows = [row for row in forecasts if bool(row.get("market_attacker_applied"))]
    clear_two_source_starts = []
    for forecast in forecasts:
        evidence = consensus.get(int(forecast["element"]), {})
        if (
            evidence.get("consensus") == "predicted_start_consensus"
            and evidence.get("official_status") == "clear"
        ):
            clear_two_source_starts.append(
                {
                    "position": str(forecast["position"]),
                    "expected_minutes": _expected_minutes(_probabilities(forecast)),
                    "incumbent_expected_minutes": float(
                        forecast.get("incumbent_expected_minutes_before_live_participation")
                        if forecast.get("incumbent_expected_minutes_before_live_participation")
                        is not None
                        else _expected_minutes(_probabilities(forecast))
                    ),
                    "participation_applied": bool(forecast.get("live_participation_applied")),
                }
            )
    probability_rows_valid = all(
        all(
            math.isfinite(float(row[field])) and 0.0 <= float(row[field]) <= 1.0
            for field in ("p_dnp", "p_1_59", "p_60_89", "p_90_or_more", "p_play")
        )
        and abs(
            sum(float(row[field]) for field in ("p_dnp", "p_1_59", "p_60_89", "p_90_or_more")) - 1.0
        )
        <= 1e-6
        and abs(float(row["p_play"]) - (1.0 - float(row["p_dnp"]))) <= 1e-6
        for row in forecasts
    )
    position_name = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    role_gate_forecasts = {
        int(row["element"]): {
            **row,
            "live_participation_consensus": str(
                (consensus.get(int(row["element"])) or {}).get("consensus") or "not_covered"
            ),
        }
        for row in forecasts
    }
    selected_capital_role_warnings = candidate_capital_role_risks(
        decision["decision"]["candidate"],
        role_gate_forecasts,
        {
            int(element): {
                "player_name": str(row["web_name"]),
                "position": position_name[int(row["element_type"])],
                "market_price": float(row["now_cost"]),
            }
            for element, row in official.items()
        },
    )
    selected_capital_role_risks = [
        risk
        for risk in selected_capital_role_warnings
        if capital_role_risk_requires_publication_block(risk)
    ]
    selected_action_role_risks = candidate_publication_role_risks(
        decision["decision"]["candidate"],
        role_gate_forecasts,
        {
            int(element): {
                "player_name": str(row["web_name"]),
                "position": position_name[int(row["element_type"])],
                "market_price": float(row["now_cost"]),
            }
            for element, row in official.items()
        },
    )
    selected_positions = Counter(
        position_name[int(official[element]["element_type"])] for element in selected
    )
    starter_ids = {int(player["element"]) for player in squad["starters"]}
    starter_positions = Counter(
        position_name[int(official[element]["element_type"])] for element in starter_ids
    )
    selected_teams = Counter(int(official[element]["team"]) for element in selected)
    expected_attacker_weights = {
        position: float(weight)
        for position, weight in attacker_market["production_weights"].items()
    }
    checks = {
        "forecast_rows_unique": len(forecasts) == len({int(row["element"]) for row in forecasts}),
        "forecast_values_are_finite": all(
            all(
                math.isfinite(float(row[field]))
                for field in ("expected_points", "robust_points", "model_sd")
            )
            for row in forecasts
        ),
        "forecast_probability_distributions_are_valid": probability_rows_valid,
        "official_identity_mapping_is_complete": (
            {int(row["element"]) for row in forecasts}
            == {element for element, row in official.items() if bool(row["can_select"])}
        ),
        "role_evidence_mapping_is_complete": (
            {int(row["element"]) for row in forecasts}.issubset(consensus)
        ),
        "gw1_fixture_count_is_coherent": all(
            float(row["fixture_count"]) == 1.0 for row in forecasts
        ),
        "selected_squad_has_fifteen_unique_players": len(selected) == 15,
        "selected_squad_has_legal_position_counts": selected_positions
        == Counter({"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}),
        "selected_squad_respects_three_player_club_cap": (
            max(selected_teams.values(), default=0) <= 3
        ),
        "selected_squad_is_within_budget": float(squad["budget_spent"]) <= 100.0,
        "selected_squad_players_are_selectable": all(
            bool(official[element]["can_select"]) for element in selected
        ),
        "selected_squad_has_no_unresolved_role_capital": not selected_capital_role_risks,
        "selected_actionable_lineup_has_no_role_integrity_risk": (not selected_action_role_risks),
        "starting_lineup_is_legal": (
            len(starter_ids) == 11
            and starter_positions["GK"] == 1
            and 3 <= starter_positions["DEF"] <= 5
            and 2 <= starter_positions["MID"] <= 5
            and 1 <= starter_positions["FWD"] <= 3
        ),
        "clear_two_source_starts_receive_production_adjustment": all(
            row["participation_applied"] for row in clear_two_source_starts
        ),
        "clear_two_source_start_minutes_are_player_bounded": all(
            row["incumbent_expected_minutes"] - 1e-6
            <= row["expected_minutes"]
            <= min(
                90.0 if row["position"] == "GK" else 88.0,
                row["incumbent_expected_minutes"] + 36.001,
            )
            for row in clear_two_source_starts
        ),
        "attacking_market_adjustment_is_bounded": all(
            0.965 <= float(row.get("market_attacking_factor") or 1.0) <= 1.035
            for row in market_rows
        ),
        "attacker_market_authority_matches_receipt": (
            all(str(row["position"]) == "FWD" for row in market_rows)
            and expected_attacker_weights == {"MID": 0.0, "FWD": 0.05}
            and all(
                bool(row.get("market_attacker_applied")) == (str(row["position"]) == "FWD")
                for row in forecasts
            )
        ),
        "material_omissions_have_deep_counterfactuals": all(
            row["best_deep_counterfactual"] is not None for row in material_excluded
        ),
        "material_omissions_have_joint_five_eight_week_counterfactuals": all(
            row["best_deep_counterfactual"] is not None for row in material_excluded
        ),
        "joint_counterfactuals_do_not_beat_published_synthesis": all(
            float(row["best_deep_counterfactual"]["synthesis_regret_delta"]) >= -1e-9
            for row in material_excluded
            if row["best_deep_counterfactual"] is not None
        ),
        "selected_role_watches_have_joint_exclusion_counterfactuals": all(
            row.get("best_exclusion_counterfactual") is not None for row in selected_role_watch
        ),
        "captain_diversity_guard_passed": bool(
            (robust.get("diversity") or {}).get("captain_publication_guard", {}).get("passed")
        ),
        "participation_receipt_matches_consensus": (
            (participation_receipt.get("outputs") or {}).get("consensus_sha256")
            == sha256_file(participation_consensus_path)
        ),
        "authored_fpl_xp_absent_from_forecast": not {
            "ep_this",
            "ep_next",
        }.intersection(pq.read_schema(forecast_path).names),
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "event": EVENT,
        "verdict": "PASS_WITH_ROLE_WATCH" if all(checks.values()) else "BLOCK",
        "publishable": all(checks.values()),
        "checks": checks,
        "summary": {
            "material_players": len(player_rows),
            "selected_players": len(selected),
            "omissions": len(omissions),
            "material_excluded": len(material_excluded),
            "open_role_assumptions": len(role_watch),
            "selected_role_watches": len(selected_role_watch),
            "near_misses": len(near_misses),
            "deep_finalists": len(deep_candidates),
            "joint_five_eight_week_finalists": len(joint_candidates),
        },
        "selected_candidate_id": decision["decision"]["candidate_id"],
        "robust_leader_id": robust["leader"]["candidate_id"],
        "robust_leader_regret": robust_leader_regret,
        "selected_synthesis_regret": selected_synthesis_regret,
        "players": player_rows,
        "omissions": omissions,
        "role_watch": role_watch,
        "near_misses": near_misses,
        "selected_role_watch": selected_role_watch,
        "selected_capital_role_warnings": selected_capital_role_warnings,
        "selected_capital_role_risks": selected_capital_role_risks,
        "selected_action_role_risks": selected_action_role_risks,
        "lineage": {
            "forecast_sha256": sha256_file(forecast_path),
            "official_players_sha256": sha256_file(official_players_path),
            "participation_consensus_sha256": sha256_file(participation_consensus_path),
            "participation_receipt_sha256": sha256_file(participation_receipt_path),
            "attacker_market_receipt_sha256": sha256_file(attacker_market_path),
            "robust_results_sha256": sha256_file(robust_results_path),
            "shortlist_sha256": sha256_file(shortlist_path),
            "decision_sha256": sha256_file(decision_path),
        },
    }
    _atomic_json(results_path, result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render(result), encoding="utf-8")
    return result
