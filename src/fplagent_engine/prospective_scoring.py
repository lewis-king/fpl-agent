from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.event_outcomes import latest_event_outcome
from fplagent_data.http import sha256_file

from .current_squad_audit import enumerate_legal_xis
from .deadline_pipeline import WEEKLY_DECISION_ARCHIVE_ROOT
from .paths import MODEL_DATA, REPORTS
from .tournament import _score_candidates

VERSION = "prospective_weekly_scoring_v4"
RESULT_ROOT = MODEL_DATA / VERSION
REPORT_ROOT = REPORTS / "prospective" / "v4"


class ProspectiveScoringError(ValueError):
    """A frozen weekly decision cannot be scored against authoritative final data."""


def _aware(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProspectiveScoringError(f"{label} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise ProspectiveScoringError(f"{label} must include a timezone")
    return parsed


def latest_archived_weekly_decision(
    event: int,
    *,
    archive_root: Path = WEEKLY_DECISION_ARCHIVE_ROOT,
    deadline_time: str | None = None,
) -> Path:
    event_dir = archive_root / f"event-{event}"
    candidates = []
    version_rank = {
        "prospective_decision_contract_v1": 1,
        "prospective_decision_contract_v2": 2,
        "weekly_decision_synthesis_v3": 3,
        "weekly_decision_synthesis_v4": 4,
    }
    for path in sorted(event_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload["decision_event"]) != event:
                continue
            created = _aware(str(payload["created_at"]), "decision created_at")
            if deadline_time and created > _aware(deadline_time, "official deadline_time"):
                continue
            if payload.get("version") not in version_rank:
                continue
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates.append(
            (created, version_rank.get(str(payload.get("version")), 0), path.name, path)
        )
    if not candidates:
        raise ProspectiveScoringError(f"no archived weekly decision exists for event {event}")
    return max(candidates)[3]


def _load_decision(path: Path, *, event: int, deadline_time: str) -> dict[str, Any]:
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveScoringError(f"weekly decision is unreadable: {path}") from exc
    accepted_versions = {
        "weekly_decision_synthesis_v3",
        "weekly_decision_synthesis_v4",
        "prospective_decision_contract_v1",
        "prospective_decision_contract_v2",
    }
    if decision.get("version") not in accepted_versions:
        raise ProspectiveScoringError("decision lacks a supported prospective-scoring contract")
    if int(decision.get("decision_event", -1)) != event:
        raise ProspectiveScoringError("weekly decision event does not match the outcome event")
    created = _aware(str(decision.get("created_at")), "decision created_at")
    deadline = _aware(deadline_time, "official deadline_time")
    if created > deadline:
        raise ProspectiveScoringError("weekly decision was created after the official deadline")
    summaries = decision.get("action_summaries")
    if not isinstance(summaries, list) or not summaries:
        raise ProspectiveScoringError("weekly decision contains no action summaries")
    action_ids = [str(row.get("action_id")) for row in summaries if isinstance(row, dict)]
    if len(action_ids) != len(summaries) or len(set(action_ids)) != len(action_ids):
        raise ProspectiveScoringError("weekly decision action IDs must be present and unique")
    if str(decision.get("selected_action_id")) not in set(action_ids):
        raise ProspectiveScoringError("selected weekly action is absent from action summaries")
    return decision


def _lineup_for_event(summary: dict[str, Any], event: int) -> dict[str, Any]:
    rows = summary.get("event_lineups")
    if not isinstance(rows, list):
        raise ProspectiveScoringError("weekly action lacks event lineup projections")
    matches = [row for row in rows if isinstance(row, dict) and row.get("event") == event]
    if len(matches) != 1:
        raise ProspectiveScoringError(
            f"weekly action must contain exactly one lineup for event {event}"
        )
    return matches[0]


def _action_candidates(
    decision: dict[str, Any], event: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = []
    summaries = []
    for raw in decision["action_summaries"]:
        summary = dict(raw)
        lineup = _lineup_for_event(summary, event)
        starters = list(map(int, lineup["starter_player_ids"]))
        bench = list(map(int, lineup["bench_player_ids"]))
        selected = starters + bench
        if len(selected) != 15 or len(set(selected)) != 15:
            raise ProspectiveScoringError(
                "weekly action lineup does not partition 15 unique players"
            )
        candidates.append(
            {
                "candidate_id": str(summary["action_id"]),
                "selected": selected,
                "lineups": {
                    str(event): {
                        "starters": starters,
                        "bench_order": bench,
                        "captain": int(lineup["captain_player_id"]),
                        "vice_captain": int(lineup["vice_captain_player_id"]),
                    }
                },
            }
        )
        summaries.append({**summary, "scored_lineup": lineup})
    return candidates, summaries


def _captain_bonus(lineup: dict[str, Any], live_by_player: dict[int, dict[str, Any]]) -> int:
    captain = live_by_player[int(lineup["captain_player_id"])]
    vice = live_by_player[int(lineup["vice_captain_player_id"])]
    if int(captain["minutes"]) > 0:
        return int(captain["total_points"])
    if int(vice["minutes"]) > 0:
        return int(vice["total_points"])
    return 0


def _hindsight_configuration(
    selected: list[int],
    frozen_lineup: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    live_by_player: dict[int, dict[str, Any]],
    frozen_gross: float,
) -> dict[str, Any]:
    best: tuple[float, tuple[int, ...], int | None] | None = None
    for starters in enumerate_legal_xis(selected, meta):
        appeared = [element for element in starters if int(live_by_player[element]["minutes"]) > 0]
        captain = (
            max(
                appeared,
                key=lambda element: (int(live_by_player[element]["total_points"]), -element),
            )
            if appeared
            else None
        )
        gross = sum(int(live_by_player[element]["total_points"]) for element in starters)
        if captain is not None:
            gross += int(live_by_player[captain]["total_points"])
        row = (float(gross), starters, captain)
        if best is None or (row[0], tuple(-value for value in row[1])) > (
            best[0],
            tuple(-value for value in best[1]),
        ):
            best = row
    if best is None:
        raise ProspectiveScoringError("selected squad has no legal hindsight XI")
    frozen_captain_bonus = _captain_bonus(frozen_lineup, live_by_player)
    frozen_starters = list(map(int, frozen_lineup["starter_player_ids"]))
    best_frozen_captain = max(
        (
            int(live_by_player[element]["total_points"])
            for element in frozen_starters
            if int(live_by_player[element]["minutes"]) > 0
        ),
        default=0,
    )
    return {
        "hindsight_gross_points": best[0],
        "hindsight_starter_player_ids": list(best[1]),
        "hindsight_captain_player_id": best[2],
        "frozen_gross_points": frozen_gross,
        "configuration_regret": max(0.0, best[0] - frozen_gross),
        "frozen_captain_bonus": frozen_captain_bonus,
        "best_frozen_xi_captain_bonus": best_frozen_captain,
        "captaincy_regret_within_frozen_xi": max(
            0.0, float(best_frozen_captain - frozen_captain_bonus)
        ),
        "interpretation": (
            "Hindsight upper bound over every legal XI and captain in the selected 15. It is "
            "diagnostic and overlaps with autosub and captaincy effects; it is not a trainable label."
        ),
    }


def _shadow_policy_choices(decision: dict[str, Any]) -> dict[str, dict[str, Any]]:
    diagnostics = decision.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    choices: dict[str, dict[str, Any]] = {}
    form = diagnostics.get("form_reversion_shadow")
    if isinstance(form, dict) and form.get("status") == "ready_shadow":
        choices["form_reversion"] = {
            "action_id": str(form["leader_action_id"]),
            "source": "diagnostics.form_reversion_shadow.leader_action_id",
        }
    market = diagnostics.get("market_goal_rate_shadow")
    anchored = market.get("anchored_component_comparison") if isinstance(market, dict) else None
    if isinstance(anchored, dict) and anchored.get("market_leader"):
        choices["market_goal_rates"] = {
            "action_id": str(anchored["market_leader"]),
            "source": (
                "diagnostics.market_goal_rate_shadow.anchored_component_comparison.market_leader"
            ),
        }
    continuation = diagnostics.get("transfer_continuation")
    if (
        isinstance(continuation, dict)
        and continuation.get("complete_root_comparison") is True
        and continuation.get("status") == "ready_diagnostic"
        and continuation.get("shadow_preference")
    ):
        choices["next_deadline_recourse"] = {
            "action_id": str(continuation["shadow_preference"]),
            "source": "diagnostics.transfer_continuation.shadow_preference",
            "scope": "first_action_only",
            "interpretation": (
                "Scores the frozen first action, not a realized adaptive multiweek path. "
                "The next deadline's information and choices have not been observed here."
            ),
        }
    shared = diagnostics.get("stateful_policy_research") or {}
    ordinary = shared.get("ordinary_continuation") or {}
    if (
        shared.get("complete_requested_roots") is True
        and shared.get("same_production_worlds") is True
        and ordinary.get("selected_first_action_id")
    ):
        choices["shared_world_continuation"] = {
            "action_id": str(ordinary["selected_first_action_id"]),
            "source": "diagnostics.stateful_policy_research.ordinary_continuation.selected_first_action_id",
            "scope": "first_action_only",
            "interpretation": "Frozen first action only; future transfers, chips and multiweek policy lift are not scored.",
        }
    allocation = diagnostics.get("allocation_research") or {}
    if (allocation.get("complete_requested_families") is True
            or allocation.get("original_pool_complete") is True):
        for comparison in allocation.get("risk_weight_sensitivity", []):
            if comparison["pool"] == "original":
                choices[f"risk_weight_{comparison['worst_case_weight']:g}"] = {
                    "action_id": str(comparison["selected_action_id"]),
                    "source": "diagnostics.allocation_research.risk_weight_sensitivity",
                    "scope": "first_action_only",
                }
    return choices


def score_role_shift_diagnostic(decision, live_by_player):
    frozen = (decision.get("diagnostics") or {}).get("role_shift_research") or {}
    if frozen.get("status") != "ready_diagnostic":
        return {"status": "not_frozen", "decision_authority": False}
    rows, missing, unsupported = [], [], []
    for row in frozen.get("players", []):
        player = int(row["player_id"])
        if row.get("forecast_status") != "scorable_single_fixture":
            unsupported.append(player)
            continue
        actual = live_by_player.get(player)
        if actual is None or actual.get("minutes") is None:
            missing.append(player)
            continue
        probabilities = [float(row[k]) for k in ("champion_p_play", "challenger_p_play")]
        if any(not np.isfinite(p) or not 0 <= p <= 1 for p in probabilities):
            raise ProspectiveScoringError("Invalid frozen role-shift probability")
        y = int(actual["minutes"]) > 0
        rows.append((row, y, probabilities))
    cohorts = {}
    for name, subset in {
        "all_supported": rows,
        "predicted_regular": [r for r in rows if r[2][0] >= 0.75],
        "role_loss_watch": [r for r in rows if r[0]["signal"]["loss_of_regular_role"]],
    }.items():
        values = {}
        for index, model in enumerate(("champion", "role_shift")):
            y = np.asarray([r[1] for r in subset], dtype=float)
            p = np.asarray([r[2][index] for r in subset])
            clipped = np.clip(p, 1e-5, 1 - 1e-5)
            values[model] = {
                "brier": float(np.mean((p - y) ** 2)) if len(y) else None,
                "log_loss": float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped)))
                if len(y)
                else None,
            }
        cohorts[name] = {"rows": len(subset), **values}
    return {
        "status": "scored_shadow",
        "decision_authority": False,
        "model_sha256": frozen["model_sha256"],
        "cohorts": cohorts,
        "missing_outcome_player_ids": missing,
        "unsupported_player_ids": unsupported,
        "scope": "Appearance prediction only; no minutes, xP or policy-lift claim.",
    }


def _score_frozen_lineup(
    *,
    selected: list[int],
    lineup: dict[str, Any],
    event: int,
    meta: dict[int, dict[str, Any]],
    live_by_player: dict[int, dict[str, Any]],
) -> float:
    player_ids = sorted(selected)
    missing = set(player_ids).difference(meta) | set(player_ids).difference(live_by_player)
    if missing:
        raise ProspectiveScoringError(
            f"chip counterfactual players are missing from frozen evidence: {sorted(missing)}"
        )
    candidate = {
        "candidate_id": "chip-counterfactual",
        "selected": player_ids,
        "lineups": {
            str(event): {
                "starters": list(map(int, lineup["starter_player_ids"])),
                "bench_order": list(map(int, lineup["bench_player_ids"])),
                "captain": int(lineup["captain_player_id"]),
                "vice_captain": int(lineup["vice_captain_player_id"]),
            }
        },
    }
    points = np.asarray(
        [[[int(live_by_player[element]["total_points"]) for element in player_ids]]],
        dtype=np.int16,
    )
    played = np.asarray(
        [[[int(live_by_player[element]["minutes"]) > 0 for element in player_ids]]],
        dtype=bool,
    )
    return float(
        _score_candidates([candidate], player_ids, (event,), points, played, meta)[0, 0, 0]
    )


def score_allocation_diagnostic(decision, by_id, *, event, meta, live_by_player, champion_net):
    frozen = (decision.get("diagnostics") or {}).get("allocation_research") or {}
    if (frozen.get("complete_requested_families") is not True
            and frozen.get("original_pool_complete") is not True):
        return {"status": "not_frozen_complete", "decision_authority": False}
    proposed = {r["action_id"]: r for r in frozen.get("frozen_proposals", [])}
    comparisons = []
    for comparison in frozen.get("risk_weight_sensitivity", []):
        if (comparison["pool"] != "original"
                and frozen.get("complete_requested_families") is not True):
            comparisons.append({**comparison, "status": "incomplete_expanded_search"})
            continue
        action_id = comparison["selected_action_id"]
        if action_id in by_id:
            net = float(by_id[action_id]["realized_decision_net_points"])
        elif action_id in proposed:
            row = proposed[action_id]
            cost = row["incremental_points_cost"]
            if not isinstance(cost, int) or cost < 0 or cost % 4:
                raise ProspectiveScoringError("Invalid frozen proposal hit cost")
            net = (
                _score_frozen_lineup(
                    selected=row["selected_player_ids"],
                    lineup=row["scored_lineup"],
                    event=event,
                    meta=meta,
                    live_by_player=live_by_player,
                )
                - cost
            )
        else:
            comparisons.append({**comparison, "status": "missing_frozen_action"})
            continue
        comparisons.append(
            {
                "pool": comparison["pool"],
                "worst_case_weight": comparison["worst_case_weight"],
                "action_id": action_id,
                "status": "scored_shadow",
                "realized_net_points": net,
                "realized_delta_to_champion": net - champion_net,
            }
        )
    return {
        "status": "scored_shadow",
        "decision_authority": False,
        "comparisons": comparisons,
        "scope": "First-action net points only. Multiple frozen hypotheses do not justify post-hoc weight selection.",
    }


def _score_chip_strategy(
    *,
    decision: dict[str, Any],
    event: int,
    summaries: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
    live_by_player: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    strategy = decision.get("chip_strategy")
    if not isinstance(strategy, dict):
        return None
    selected_id = str(decision["selected_action_id"])
    summary_by_id = {str(row["action_id"]): row for row in summaries}
    selected_net = float(by_id[selected_id]["realized_manager_net_points"])
    team_by_action = {
        str(row["action_id"]): row
        for row in (decision.get("chip_shadow") or {}).get("candidates") or []
        if isinstance(row, dict) and row.get("action_id")
    }
    squad_shadow = decision.get("squad_chip_shadow") or {}
    squad_by_action = {
        str(row["action_id"]): row
        for row in squad_shadow.get("candidates") or []
        if isinstance(row, dict) and row.get("action_id")
    }
    scored_candidates = []
    configuration = (decision.get("diagnostics") or {}).get("configuration_optimisation") or {}
    configured = {row["action_id"]: row for row in configuration.get("candidates", [])}
    for candidate in strategy.get("candidates") or []:
        chip = str(candidate.get("chip"))
        action_id = str(candidate.get("action_id"))
        parent_id = candidate.get("parent_action_id") or team_by_action.get(action_id, {}).get(
            "parent_action_id"
        )
        gross = None
        chip_only_uplift = None
        points_cost = None
        frozen_lineup = None
        execution = decision.get("execution_plan") or {}
        if execution.get("configuration_action_id") == action_id:
            if execution.get("chip") != chip or execution.get("action_id") != parent_id:
                raise ProspectiveScoringError("chip execution plan does not match its parent")
            frozen_lineup = _lineup_for_event(execution, event)
        elif action_id in configured:
            key = "selected_lineups" if configuration.get("status") == "validated" else "original_lineups"
            item = next((row for row in configured[action_id][key] if row["event"] == event), None)
            if item:
                config = item["lineup"]
                frozen_lineup = {
                    "starter_player_ids": config["starters"],
                    "bench_player_ids": config["bench_order"],
                    "captain_player_id": config["captain"],
                    "vice_captain_player_id": config["vice_captain"],
                }
        if chip in {"bench_boost", "triple_captain"}:
            # A chip may be paired with a different transfer route, XI and captain.
            # Never substitute the ordinary winner when the frozen parent is absent.
            parent = summary_by_id.get(str(parent_id))
            if parent is not None and (not configuration or frozen_lineup is not None):
                lineup = frozen_lineup or parent["scored_lineup"]
                parent_score = by_id[str(parent_id)]
                selected_players = [*lineup["starter_player_ids"], *lineup["bench_player_ids"]]
                parent_players = [*parent["scored_lineup"]["starter_player_ids"], *parent["scored_lineup"]["bench_player_ids"]]
                if len(set(selected_players)) != 15 or set(selected_players) != set(parent_players):
                    raise ProspectiveScoringError("chip configuration roster differs from its parent")
                ordinary_gross = _score_frozen_lineup(selected=selected_players, lineup=lineup,
                    event=event, meta=meta, live_by_player=live_by_player)
                captain_bonus = _captain_bonus(lineup, live_by_player)
                if chip == "triple_captain":
                    gross = ordinary_gross + captain_bonus
                else:
                    players = [*lineup["starter_player_ids"], *lineup["bench_player_ids"]]
                    gross = float(
                        sum(
                            int(live_by_player[int(element)]["total_points"]) for element in players
                        )
                        + captain_bonus
                    )
                chip_only_uplift = gross - ordinary_gross
                points_cost = int(parent_score["total_points_cost"])
        if chip in {"wildcard", "free_hit"}:
            squad_candidate = squad_by_action.get(action_id)
            if squad_candidate:
                gross = _score_frozen_lineup(
                    selected=list(map(int, squad_candidate["selected_player_ids"])),
                    lineup={
                        "starter_player_ids": squad_candidate["starter_player_ids"],
                        "bench_player_ids": squad_candidate["bench_player_ids"],
                        "captain_player_id": squad_candidate["captain_player_id"],
                        "vice_captain_player_id": squad_candidate["vice_captain_player_id"],
                    },
                    event=event,
                    meta=meta,
                    live_by_player=live_by_player,
                )
                # Both squad chips waive all event transfer costs, including sunk hits.
                points_cost = 0
        actual_uplift = (
            gross - points_cost - selected_net
            if gross is not None and points_cost is not None
            else None
        )
        scored_candidates.append(
            {
                "chip": chip,
                "action_id": candidate.get("action_id"),
                "parent_action_id": parent_id,
                "comparison_action_id": selected_id,
                "status": "scored" if actual_uplift is not None else "not_scorable_missing_lineage",
                "projected_policy_uplift": candidate.get("projected_uplift"),
                "projected_joint_net_value": candidate.get("joint_net_value"),
                "actual_immediate_uplift": actual_uplift,
                "actual_chip_only_uplift": chip_only_uplift,
                "realized_gross_points": gross,
                "total_points_cost": points_cost,
                "operational_gate_passed": bool(candidate.get("operational_gate_passed")),
                "configuration_basis": "exact_frozen_chip" if frozen_lineup else "legacy_parent_or_missing",
            }
        )
    return {
        "frozen_recommendation": strategy.get("operational_recommendation"),
        "frozen_status": strategy.get("status"),
        "candidates": scored_candidates,
        "scoring_scope": (
            "Actual immediate uplift compares each frozen chip-and-transfer route's event net "
            "points with the selected ordinary route. Chip-only uplift compares BB/TC with its "
            "own no-chip parent, including autosub displacement. Projected policy uplift may "
            "span the full decision horizon and is not a like-for-like event forecast. Wildcard "
            "persistence and chip retention cannot be judged from one event."
        ),
        "decision_authority": False,
    }


def _render_report(result: dict[str, Any]) -> str:
    comparison = result["selected_comparison"]
    attribution = result["decision_attribution"]
    rows = result["actions"]
    lines = [
        f"# Gameweek {result['event']} prospective decision scorecard",
        "",
        (
            f"Decision: **{result['selected_action_id']}**. Realized rank: "
            f"**{comparison['realized_rank']} of {len(rows)}**."
        ),
        "",
        (
            "| Rank | Action | Route | Gross | Incremental cost | Decision net | "
            f"Δ {result['reference_label']} |"
        ),
        "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['realized_rank']} | {row['action_id']} | {row['route_type']} | "
            f"{row['realized_gross_points']:.1f} | {row['incremental_points_cost']} | "
            f"{row['realized_decision_net_points']:.1f} | "
            f"{row['realized_delta_to_reference']:+.1f} |"
        )
    lines.extend(
        [
            "",
            "## Selected action",
            "",
            (
                f"- Realized net difference to {result['reference_label']}: "
                f"{comparison['realized_delta_to_reference']:+.1f}"
            ),
            (
                f"- Realized opportunity cost to the best considered action: "
                f"{comparison['realized_opportunity_cost']:.1f}"
            ),
            f"- Projected event net points: {comparison['projected_event_net_points']:.2f}",
            f"- Realized event net points: {comparison['realized_decision_net_points']:.1f}",
            "",
            "## Attribution diagnostics",
            "",
            (
                f"- Best-considered action regret: "
                f"{attribution['action_selection_regret']:.1f} points"
            ),
            (
                f"- Hindsight XI/captain upper-bound regret: "
                f"{attribution['configuration']['configuration_regret']:.1f} points"
            ),
            (
                f"- Captain regret within the frozen XI: "
                f"{attribution['configuration']['captaincy_regret_within_frozen_xi']:.1f} points"
            ),
            (
                f"- Player expected-points MAE: "
                f"{attribution['forecast_diagnostics']['expected_points_mae']:.3f}; "
                f"appearance Brier: {attribution['forecast_diagnostics']['appearance_brier']:.3f}"
            ),
            "",
            (
                "This is prospective process evidence, not permission to fit the next model to one "
                "noisy Gameweek. Aggregate frozen receipts before changing a forecast or policy."
            ),
            "",
        ]
    )
    chip_score = result.get("chip_strategy_score")
    if chip_score:
        lines.extend(
            [
                "## Frozen chip counterfactuals",
                "",
                "| Chip | Parent route | Chip-only gain | Event net gain vs selected route |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for candidate in chip_score["candidates"]:
            chip_only = candidate["actual_chip_only_uplift"]
            event_gain = candidate["actual_immediate_uplift"]
            lines.append(
                f"| {candidate['chip']} | {candidate['parent_action_id'] or 'squad rebuild'} | "
                f"{f'{chip_only:+.1f}' if chip_only is not None else 'n/a'} | "
                f"{f'{event_gain:+.1f}' if event_gain is not None else 'unscorable'} |"
            )
        lines.extend(["", chip_score["scoring_scope"], ""])
    return "\n".join(lines)


def score_forecast_universe(
    meta: dict[int, dict[str, Any]],
    outcomes: dict[int, dict[str, Any]],
    *,
    selected_players: set[int],
    declared_scope: str = "legacy_frozen_subset",
) -> dict[str, Any]:
    """Score all actually frozen players; missing outcomes are never zero-filled."""
    covered = sorted(set(meta) & set(outcomes))
    missing = sorted(set(meta) - set(outcomes))
    top_forecasts = set(sorted(meta, key=lambda p: (-float(meta[p]["expected_points"]), p))[:30])
    rows = []
    for player in covered:
        forecast, actual = meta[player], outcomes[player]
        rows.append(
            {
                "element": player,
                "position": str(forecast["position"]),
                "player_name": str(forecast.get("player_name") or player),
                "selected": player in selected_players,
                "expected_points": float(forecast["expected_points"]),
                "actual_points": int(actual["total_points"]),
                "p_play": float(forecast["p_play"]),
                "appeared": int(actual["minutes"]) > 0,
                "expected_minutes": forecast.get("expected_minutes"),
                "actual_minutes": int(actual["minutes"]),
                "points_pmf": forecast.get("points_pmf"),
                "distribution_source": forecast.get("distribution_source"),
                "distribution_calibration_sha256": forecast.get("distribution_calibration_sha256"),
                "p_1_59": forecast.get("p_1_59"),
                "p_60_plus": (
                    float(forecast["p_60_89"]) + float(forecast["p_90_or_more"])
                    if "p_60_89" in forecast and "p_90_or_more" in forecast else None
                ),
            }
        )

    def metrics(sample: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(sample)
        minutes = [
            abs(float(r["expected_minutes"]) - r["actual_minutes"])
            for r in sample
            if r["expected_minutes"] is not None
        ]
        return {
            "players": count,
            "points_mae": sum(abs(r["actual_points"] - r["expected_points"]) for r in sample)
            / count
            if count
            else None,
            "points_bias": sum(r["actual_points"] - r["expected_points"] for r in sample) / count
            if count
            else None,
            "appearance_brier": sum((r["p_play"] - float(r["appeared"])) ** 2 for r in sample)
            / count
            if count
            else None,
            "minutes_mae": sum(minutes) / len(minutes) if minutes else None,
            "high_confidence_dnp_count": sum(
                r["p_play"] >= 0.75 and not r["appeared"] for r in sample
            ),
            "expected_short_appearances": sum(float(r["p_1_59"]) for r in sample if r["p_1_59"] is not None),
            "actual_short_appearances": sum(0 < r["actual_minutes"] < 60 for r in sample if r["p_1_59"] is not None),
            "minutes_bins_covered": sum(r["p_1_59"] is not None for r in sample),
            "unexpected_short_appearances": sum(
                r["p_60_plus"] is not None and r["p_60_plus"] >= 0.75
                and 0 < r["actual_minutes"] < 60 for r in sample
            ),
        }

    cohorts = {
        "all_frozen": rows,
        "selected_squad": [r for r in rows if r["selected"]],
        "not_selected": [r for r in rows if not r["selected"]],
        "predicted_regulars": [r for r in rows if r["p_play"] >= 0.75],
        "top_30_deadline_forecasts": [r for r in rows if r["element"] in top_forecasts],
        **{
            position: [r for r in rows if r["position"] == position]
            for position in ("GK", "DEF", "MID", "FWD")
        },
    }
    return {
        "scope": declared_scope,
        "status": "complete" if not missing else "partial_outcomes",
        "frozen_players": len(meta),
        "scored_players": len(rows),
        "missing_outcome_player_ids": missing,
        "cohorts": {name: metrics(sample) for name, sample in cohorts.items()},
        "player_outcomes": rows,
        "limitations": "Cohorts use frozen forecasts; older subset receipts are not full-pool evidence. One event is not a promotion test.",
    }


def score_weekly_event(
    event: int,
    *,
    decision_path: Path | None = None,
    decision_archive_root: Path = WEEKLY_DECISION_ARCHIVE_ROOT,
    outcome_root: Path | None = None,
    outcome_pointer_root: Path | None = None,
    result_root: Path = RESULT_ROOT,
    report_root: Path = REPORT_ROOT,
) -> dict[str, Any]:
    if not 1 <= event <= 38:
        raise ProspectiveScoringError("event must be in [1, 38]")
    outcome_kwargs: dict[str, Path] = {}
    if outcome_root is not None:
        outcome_kwargs["outcome_root"] = outcome_root
    if outcome_pointer_root is not None:
        outcome_kwargs["pointer_root"] = outcome_pointer_root
    outcome_dir, outcome_manifest, live = latest_event_outcome(event, **outcome_kwargs)
    if not (
        outcome_manifest.get("publishable")
        and outcome_manifest.get("finished")
        and outcome_manifest.get("data_checked")
    ):
        raise ProspectiveScoringError(
            "official event outcome is not final, checked and publishable"
        )
    chosen_decision = decision_path or latest_archived_weekly_decision(
        event, archive_root=decision_archive_root, deadline_time=str(outcome_manifest["deadline_time"])
    )
    decision = _load_decision(
        chosen_decision,
        event=event,
        deadline_time=str(outcome_manifest["deadline_time"]),
    )
    candidates, summaries = _action_candidates(decision, event)
    forecast_meta = decision.get("event_player_forecasts")
    if not isinstance(forecast_meta, dict) or not forecast_meta:
        raise ProspectiveScoringError("weekly decision lacks frozen event player forecasts")
    try:
        meta = {int(element): dict(row) for element, row in forecast_meta.items()}
        live_by_player = {int(row["id"]): row["stats"] for row in live["elements"]}
    except (KeyError, TypeError, ValueError) as exc:
        raise ProspectiveScoringError(
            "decision or official outcome player metadata is invalid"
        ) from exc
    player_ids = sorted({element for candidate in candidates for element in candidate["selected"]})
    missing_meta = set(player_ids) - set(meta)
    missing_outcomes = set(player_ids) - set(live_by_player)
    if missing_meta or missing_outcomes:
        raise ProspectiveScoringError(
            f"action players missing from evidence: forecasts={sorted(missing_meta)}, "
            f"outcomes={sorted(missing_outcomes)}"
        )
    points = np.asarray(
        [[[int(live_by_player[element]["total_points"]) for element in player_ids]]],
        dtype=np.int16,
    )
    played = np.asarray(
        [[[int(live_by_player[element]["minutes"]) > 0 for element in player_ids]]],
        dtype=bool,
    )
    gross_scores = _score_candidates(
        candidates,
        player_ids,
        (event,),
        points,
        played,
        meta,
    )[0, :, 0].astype(float)
    selected_id = str(decision["selected_action_id"])
    if decision["version"] in {"weekly_decision_synthesis_v3", "weekly_decision_synthesis_v4"}:
        reference_ids = [
            str(summary["action_id"]) for summary in summaries if summary["route_type"] == "roll"
        ]
        reference_label = "roll"
        if len(reference_ids) != 1:
            raise ProspectiveScoringError(
                "weekly prospective scoring requires exactly one roll comparator"
            )
        reference_id = reference_ids[0]
        roll_id: str | None = reference_id
    else:
        reference_id = str(decision.get("reference_action_id"))
        reference_label = str(decision.get("reference_label") or "pre-deadline reference")
        if reference_id not in {str(summary["action_id"]) for summary in summaries}:
            raise ProspectiveScoringError("prospective contract reference action is missing")
        roll_id = None
    action_rows = []
    for index, summary in enumerate(summaries):
        projected = float(summary["scored_lineup"]["projected_points"])
        incremental_cost = int(summary["incremental_points_cost"])
        total_cost = int(summary["total_points_cost"])
        action_rows.append(
            {
                "action_id": str(summary["action_id"]),
                "route_type": str(summary["route_type"]),
                "realized_gross_points": float(gross_scores[index]),
                "incremental_points_cost": incremental_cost,
                "total_points_cost": total_cost,
                "realized_decision_net_points": float(gross_scores[index] - incremental_cost),
                "realized_manager_net_points": float(gross_scores[index] - total_cost),
                "projected_event_gross_points": projected,
                "projected_event_net_points": projected - incremental_cost,
                "gross_forecast_error": float(gross_scores[index] - projected),
            }
        )
    by_id = {row["action_id"]: row for row in action_rows}
    reference_net = by_id[reference_id]["realized_decision_net_points"]
    for row in action_rows:
        row["realized_delta_to_reference"] = row["realized_decision_net_points"] - reference_net
        if roll_id is not None:
            row["realized_delta_to_roll"] = row["realized_delta_to_reference"]
    action_rows.sort(key=lambda row: (-row["realized_decision_net_points"], row["action_id"]))
    for rank, row in enumerate(action_rows, start=1):
        row["realized_rank"] = rank
    selected = by_id[selected_id]
    best_net = action_rows[0]["realized_decision_net_points"]
    selected_candidate = next(c for c in candidates if c["candidate_id"] == selected_id)
    selected_players = set(selected_candidate["selected"])
    selected_summary = next(
        summary for summary in summaries if str(summary["action_id"]) == selected_id
    )
    selected_lineup = selected_summary["scored_lineup"]
    selected_starters = set(map(int, selected_lineup["starter_player_ids"]))
    selected_bench = set(map(int, selected_lineup["bench_player_ids"]))
    selected_captain = int(selected_lineup["captain_player_id"])
    player_rows = []
    for element in sorted(selected_players):
        forecast = meta[element]
        actual = live_by_player[element]
        expected_minutes = forecast.get("expected_minutes")
        player_rows.append(
            {
                "element": element,
                "player_name": str(forecast.get("player_name") or f"#{element}"),
                "position": str(forecast["position"]),
                "decision_role": (
                    "captain"
                    if element == selected_captain
                    else "starter"
                    if element in selected_starters
                    else "bench"
                    if element in selected_bench
                    else "squad"
                ),
                "expected_points": float(forecast["expected_points"]),
                "robust_points": float(forecast["robust_points"]),
                "actual_points": int(actual["total_points"]),
                "points_error_vs_expected": int(actual["total_points"])
                - float(forecast["expected_points"]),
                "p_play": float(forecast["p_play"]),
                "expected_minutes": (
                    float(expected_minutes) if expected_minutes is not None else None
                ),
                "actual_minutes": int(actual["minutes"]),
                "appeared": int(actual["minutes"]) > 0,
                "actual_bps": int(actual.get("bps") or 0),
                "actual_defensive_contribution": int(actual.get("defensive_contribution") or 0),
                "actual_expected_goals": float(actual.get("expected_goals") or 0.0),
                "actual_expected_assists": float(actual.get("expected_assists") or 0.0),
                "points_pmf": forecast.get("points_pmf"),
                "distribution_source": forecast.get("distribution_source"),
                "distribution_calibration_sha256": forecast.get("distribution_calibration_sha256"),
            }
        )
    all_player_rows = []
    for element in player_ids:
        forecast = meta[element]
        actual = live_by_player[element]
        appeared = int(actual["minutes"]) > 0
        all_player_rows.append(
            {
                "element": element,
                "player_name": str(forecast.get("player_name") or f"#{element}"),
                "expected_points": float(forecast["expected_points"]),
                "actual_points": int(actual["total_points"]),
                "points_error": int(actual["total_points"]) - float(forecast["expected_points"]),
                "p_play": float(forecast["p_play"]),
                "appeared": appeared,
            }
        )
    point_errors = np.asarray([row["points_error"] for row in all_player_rows])
    play_errors = np.asarray(
        [float(row["p_play"]) - float(row["appeared"]) for row in all_player_rows]
    )
    worst_under = sorted(all_player_rows, key=lambda row: (-row["points_error"], row["element"]))[
        :5
    ]
    worst_over = sorted(all_player_rows, key=lambda row: (row["points_error"], row["element"]))[:5]
    configuration = _hindsight_configuration(
        list(map(int, selected_candidate["selected"])),
        selected_summary["scored_lineup"],
        meta,
        live_by_player,
        float(selected["realized_gross_points"]),
    )
    shadow_scores = {}
    for challenger, choice in _shadow_policy_choices(decision).items():
        action_id = str(choice["action_id"])
        if action_id not in by_id:
            shadow_scores[challenger] = {
                **choice,
                "status": "not_scorable",
                "reason": "the frozen challenger action is absent from action summaries",
            }
            continue
        challenger_row = by_id[action_id]
        shadow_scores[challenger] = {
            **choice,
            "status": "scored_shadow",
            "decision_authority": False,
            "realized_net_points": challenger_row["realized_decision_net_points"],
            "champion_realized_net_points": selected["realized_decision_net_points"],
            "realized_delta_to_champion": (
                challenger_row["realized_decision_net_points"]
                - selected["realized_decision_net_points"]
            ),
        }
    forecast_diagnostics = {
        "players": len(all_player_rows),
        "expected_points_mae": float(np.mean(np.abs(point_errors))),
        "expected_points_bias_actual_minus_forecast": float(np.mean(point_errors)),
        "appearance_brier": float(np.mean(np.square(play_errors))),
        "high_confidence_dnp_count": sum(
            float(row["p_play"]) >= 0.75 and not bool(row["appeared"]) for row in all_player_rows
        ),
        "surprise_appearance_count": sum(
            float(row["p_play"]) <= 0.25 and bool(row["appeared"]) for row in all_player_rows
        ),
        "largest_underforecasts": worst_under,
        "largest_overforecasts": worst_over,
    }
    decision_sha = sha256_file(chosen_decision)
    outcome_sha = sha256_file(outcome_dir / "event-live.json")
    output_path = result_root / f"event-{event}" / f"{decision_sha[:16]}-{outcome_sha[:16]}.json"
    report_path = report_root / f"event-{event}-{decision_sha[:12]}.md"
    result = {
        "version": VERSION,
        "event": event,
        "selected_action_id": selected_id,
        "roll_action_id": roll_id,
        "reference_action_id": reference_id,
        "reference_label": reference_label,
        "selected_comparison": {
            **selected,
            "realized_opportunity_cost": best_net - selected["realized_decision_net_points"],
        },
        "actions": action_rows,
        "selected_squad_player_outcomes": player_rows,
        "forecast_universe": score_forecast_universe(
            meta,
            live_by_player,
            selected_players=selected_players,
            declared_scope=(decision.get("forecast_coverage") or {}).get(
                "scope", "legacy_frozen_subset"
            ),
        ),
        "decision_attribution": {
            "action_selection_regret": best_net - selected["realized_decision_net_points"],
            "configuration": configuration,
            "forecast_diagnostics": forecast_diagnostics,
            "overlap_warning": (
                "Action, configuration and captain diagnostics are counterfactual upper bounds and "
                "must not be added together."
            ),
        },
        "challenger_policy_scores": shadow_scores,
        "role_shift_scores": score_role_shift_diagnostic(decision, live_by_player),
        "allocation_scores": score_allocation_diagnostic(
            decision,
            by_id,
            event=event,
            meta=meta,
            live_by_player=live_by_player,
            champion_net=selected["realized_decision_net_points"],
        ),
        "chip_strategy_score": _score_chip_strategy(
            decision=decision,
            event=event,
            summaries=summaries,
            by_id=by_id,
            meta=meta,
            live_by_player=live_by_player,
        ),
        "frozen_evidence": {
            "decision_path": str(chosen_decision),
            "decision_sha256": decision_sha,
            "decision_created_at": str(decision["created_at"]),
            "official_deadline_time": str(outcome_manifest["deadline_time"]),
            "outcome_path": str(outcome_dir / "event-live.json"),
            "outcome_sha256": outcome_sha,
            "outcome_observed_at": str(outcome_manifest["observed_at"]),
            "official_finished": True,
            "official_data_checked": True,
        },
        "interpretation_rule": (
            "Score frozen decisions after official finalisation, but require an aggregate sample "
            "before promoting a forecast or decision-policy change."
        ),
        "receipt_path": str(output_path),
        "report_path": str(report_path),
    }
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        frozen = existing.get("frozen_evidence", {})
        # Reobserving byte-identical outcomes may repair source lineage. Preserve
        # the original receipt's still-verifiable path/time, not a duplicate score.
        if existing.get("version") == VERSION and frozen.get("decision_sha256") == decision_sha and frozen.get("outcome_sha256") == outcome_sha:
            for kind in ("decision", "outcome"):
                old_path = Path(frozen[f"{kind}_path"])
                if sha256_file(old_path) != frozen[f"{kind}_sha256"]:
                    raise ProspectiveScoringError("Existing prospective evidence checksum changed")
                result["frozen_evidence"][f"{kind}_path"] = str(old_path)
            result["frozen_evidence"]["outcome_observed_at"] = frozen["outcome_observed_at"]
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise ProspectiveScoringError(f"immutable prospective receipt collision: {output_path}")
    if not output_path.exists():
        temporary = output_path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = _render_report(result)
    if report_path.exists() and report_path.read_text(encoding="utf-8") != report:
        raise ProspectiveScoringError(f"immutable prospective report collision: {report_path}")
    if not report_path.exists():
        temporary_report = report_path.with_suffix(".md.tmp")
        temporary_report.write_text(report, encoding="utf-8")
        temporary_report.replace(report_path)
    return result
