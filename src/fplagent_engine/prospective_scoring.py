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

VERSION = "prospective_weekly_scoring_v2"
RESULT_ROOT = MODEL_DATA / VERSION
REPORT_ROOT = REPORTS / "prospective"


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
) -> Path:
    event_dir = archive_root / f"event-{event}"
    candidates = []
    version_rank = {
        "prospective_decision_contract_v1": 1,
        "prospective_decision_contract_v2": 2,
        "weekly_decision_synthesis_v3": 3,
    }
    for path in sorted(event_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload["decision_event"]) != event:
                continue
            created = _aware(str(payload["created_at"]), "decision created_at")
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
    return choices


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
    return "\n".join(lines)


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
        event, archive_root=decision_archive_root
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
    if decision["version"] == "weekly_decision_synthesis_v3":
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
