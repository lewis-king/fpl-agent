from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.participation_consensus import (
    CONSENSUS as PARTICIPATION_CONSENSUS,
)
from fplagent_data.participation_consensus import RECEIPT as PARTICIPATION_RECEIPT
from fplagent_data.paths import MANIFESTS, PROCESSED
from fplagent_data.preseason_lineups import fpl_role_mapping_fingerprint

from .decision_synthesis import DECISION_JSON
from .models import CURRENT_FORECAST
from .preseason_role_scenario import (
    FLAG_NOT_LISTED,
    FLAG_ROLE_WATCH,
    FLAG_UNCOVERED,
    ROLE_EVIDENCE,
    ROLE_RECEIPT,
    derive_role_flags,
)
from .preseason_role_scenario import RESULTS_JSON as SCENARIO_RESULTS
from .preseason_role_threshold import RESULTS_JSON as THRESHOLD_RESULTS

VERSION = 2
EVENT = 1
PLAYERS = PROCESSED / "fpl" / "2026-27" / "preseason" / "players.parquet"
TEAMS = PROCESSED / "fpl" / "2026-27" / "preseason" / "teams.parquet"
EVENTS = PROCESSED / "fpl" / "2026-27" / "preseason" / "events.parquet"
RECEIPT = MANIFESTS / "fpl-availability-watch.json"
DEFAULT_ADVISORY_MAX_AGE = timedelta(hours=72)


class AvailabilityWatchError(ValueError):
    """The availability watch could not establish a coherent evidence generation."""


def _aware(value: str | datetime, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise AvailabilityWatchError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path, label: str, issues: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        issues.append(f"missing {label}: {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"invalid {label}: {exc}")
        return None
    if not isinstance(value, dict):
        issues.append(f"invalid {label}: expected a JSON object")
        return None
    return value


def _load_parquet(path: Path, label: str, issues: list[str]) -> list[dict[str, Any]]:
    if not path.is_file():
        issues.append(f"missing {label}: {path}")
        return []
    try:
        return pq.read_table(path).to_pylist()
    except (OSError, pa.ArrowException) as exc:
        issues.append(f"invalid {label}: {exc}")
        return []


def _single_text(rows: list[dict[str, Any]], field: str) -> str | None:
    values = {str(row[field]) for row in rows if row.get(field) not in (None, "")}
    return next(iter(values)) if len(values) == 1 else None


def _effective_official_chance(player: Mapping[str, Any]) -> int:
    for field in (
        "chance_of_playing_this_round",
        "chance_of_playing_next_round",
    ):
        value = player.get(field)
        if value is not None:
            return int(value)
    return 100 if player.get("status") == "a" else 0


def _attention_labels(
    player: Mapping[str, Any], role_flag: str
) -> list[str]:
    labels: list[str] = []
    chance = _effective_official_chance(player)
    if (
        player.get("removed") is True
        or player.get("can_select") is False
        or player.get("status") == "u"
        or chance == 0
    ):
        labels.append("official_unavailable")
    elif (
        player.get("status") != "a"
        or chance < 100
        or bool(str(player.get("news") or "").strip())
    ):
        labels.append("official_doubt_or_news")
    if role_flag == FLAG_NOT_LISTED:
        labels.append("three_plus_lineup_absence")
    elif role_flag == FLAG_ROLE_WATCH:
        labels.append("low_recent_start_share")
    elif role_flag == FLAG_UNCOVERED:
        labels.append("uncovered_club_feed")
    return labels


def _decision_frontier(
    decision: Mapping[str, Any],
    *,
    player_by_id: Mapping[int, Mapping[str, Any]],
    forecast_by_id: Mapping[int, Mapping[str, Any]],
    role_by_id: Mapping[int, Mapping[str, Any]],
    participation_by_id: Mapping[int, Mapping[str, Any]],
    issues: list[str],
) -> dict[str, Any]:
    """Audit evidence for every player who can win the final synthesis, not just its leader."""
    published = ((decision.get("decision") or {}).get("candidate") or {})
    ranking = list(decision.get("ranking") or [])
    requested_ids = [str(row["candidate_id"]) for row in ranking if row.get("candidate_id")]
    if not requested_ids and published.get("candidate_id"):
        requested_ids = [str(published["candidate_id"])]

    candidates: dict[str, Mapping[str, Any]] = {}
    if published.get("candidate_id"):
        candidates[str(published["candidate_id"])] = published
    source = decision.get("source_artifacts") or {}
    shortlist_value = source.get("robust_shortlist")
    shortlist_sha = source.get("robust_shortlist_sha256")
    if shortlist_value:
        shortlist_path = Path(str(shortlist_value))
        if not shortlist_path.is_file():
            issues.append(f"missing synthesis frontier shortlist: {shortlist_path}")
        elif shortlist_sha and sha256_file(shortlist_path) != shortlist_sha:
            issues.append("synthesis frontier shortlist differs from the decision receipt")
        else:
            try:
                shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
                candidates.update(
                    {
                        str(candidate["candidate_id"]): candidate
                        for candidate in shortlist.get("candidates") or []
                    }
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                issues.append(f"invalid synthesis frontier shortlist: {exc}")

    missing_candidates = sorted(set(requested_ids) - set(candidates))
    if missing_candidates:
        issues.append(
            "synthesis frontier candidates missing from the checksum-bound shortlist: "
            f"{missing_candidates}"
        )
    frontier = [candidates[candidate_id] for candidate_id in requested_ids if candidate_id in candidates]
    exposure: dict[int, dict[str, int]] = {}
    for candidate in frontier:
        selected = set(map(int, candidate.get("selected") or []))
        lineup = (candidate.get("lineups") or {}).get(str(EVENT)) or {}
        starters = set(map(int, lineup.get("starters") or []))
        captain = int(lineup["captain"]) if lineup.get("captain") is not None else None
        for element in selected:
            counts = exposure.setdefault(
                element, {"squads": 0, "starts": 0, "captaincies": 0}
            )
            counts["squads"] += 1
            counts["starts"] += int(element in starters)
            counts["captaincies"] += int(element == captain)

    frontier_elements = set(exposure)
    missing_layers = {
        "official": sorted(frontier_elements - set(player_by_id)),
        "forecast": sorted(frontier_elements - set(forecast_by_id)),
        "role": sorted(frontier_elements - set(role_by_id)),
    }
    for layer, elements in missing_layers.items():
        if elements:
            issues.append(f"frontier players missing from {layer} evidence: {elements}")

    flags = (
        derive_role_flags(list(role_by_id.values()), frontier_elements)
        if frontier_elements and not missing_layers["role"]
        else {}
    )
    rows = []
    denominator = max(len(frontier), 1)
    for element, counts in exposure.items():
        if element not in player_by_id or element not in forecast_by_id:
            continue
        official = player_by_id[element]
        forecast = forecast_by_id[element]
        predicted = participation_by_id.get(element)
        attention = _attention_labels(official, flags.get(element, FLAG_UNCOVERED))
        if float(forecast.get("p_play") or 0.0) < 0.75:
            attention.append("model_p_play_below_75pct")
        if predicted is not None:
            for label in map(str, predicted.get("attention") or []):
                if label not in attention:
                    attention.append(label)
        rows.append(
            {
                "element": element,
                "name": str(forecast.get("player_name") or official.get("web_name") or element),
                "team": str(forecast.get("team_name") or official.get("team") or ""),
                "position": str(forecast.get("position") or ""),
                "squad_exposure": counts["squads"] / denominator,
                "start_exposure": counts["starts"] / denominator,
                "captain_exposure": counts["captaincies"] / denominator,
                "p_play": float(forecast.get("p_play") or 0.0),
                "expected_points": float(forecast.get("expected_points") or 0.0),
                "role_flag": flags.get(element),
                "predicted_lineup_consensus": (
                    str(predicted.get("consensus")) if predicted is not None else None
                ),
                "attention": attention,
            }
        )
    rows.sort(
        key=lambda row: (
            not bool(row["attention"]),
            -float(row["captain_exposure"]),
            -float(row["start_exposure"]),
            -float(row["squad_exposure"]),
            str(row["name"]),
        )
    )
    return {
        "candidate_count": len(frontier),
        "requested_candidate_count": len(requested_ids),
        "player_count": len(frontier_elements),
        "complete_official_forecast_role_coverage": not any(missing_layers.values()),
        "predicted_lineup_coverage": sum(element in participation_by_id for element in exposure),
        "attention_player_count": sum(bool(row["attention"]) for row in rows),
        "players": rows,
        "missing": missing_layers,
        "authority": (
            "Official, forecast and role coverage are publication gates. Predicted lineups are "
            "shown across the entire decision frontier but retain zero production weight."
        ),
    }


def _scenario_stability(scenario: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = scenario.get("scenarios")
    if not isinstance(scenarios, Mapping):
        return {
            "baseline_stable": False,
            "moderate_stable": False,
            "supported_deep_scenarios": [],
        }
    baseline = scenarios.get("baseline")
    moderate = scenarios.get("moderate_role_stress")

    def retained(row: Any) -> bool:
        return bool(
            isinstance(row, Mapping)
            and not row.get("configuration", {}).get(
                "cross_family_holdout_support", False
            )
            and not row.get("squad", {}).get("cross_family_holdout_support", False)
            and not (
                isinstance(row.get("deep_squad_replay"), Mapping)
                and row["deep_squad_replay"].get("cross_family_holdout_support")
            )
        )

    return {
        "baseline_stable": retained(baseline),
        "moderate_stable": retained(moderate),
        "baseline_exact_selection_match": bool(
            isinstance(baseline, Mapping)
            and baseline.get("configuration", {}).get("exact_published_match")
            and baseline.get("squad", {}).get("exact_published_match")
        ),
        "moderate_exact_selection_match": bool(
            isinstance(moderate, Mapping)
            and moderate.get("configuration", {}).get("exact_published_match")
            and moderate.get("squad", {}).get("exact_published_match")
        ),
        "supported_deep_scenarios": list(
            map(str, scenario.get("supported_deep_squad_scenarios") or [])
        ),
    }


def _configuration_names(value: Any) -> set[str]:
    if not isinstance(value, Mapping):
        return set()
    return {
        str(name)
        for field in ("starters", "bench_order")
        for name in (value.get(field) or [])
        if name not in (None, "")
    }


def _synthesis_tradeoff(
    decision: Mapping[str, Any] | None,
    challenger_squad_id: str,
) -> dict[str, Any]:
    if not isinstance(decision, Mapping):
        return {}
    selected_id = str(
        ((decision.get("decision") or {}).get("candidate_id") or "")
        if isinstance(decision.get("decision"), Mapping)
        else ""
    )
    ranking = decision.get("ranking")
    if not selected_id or not isinstance(ranking, list):
        return {}
    rows = {
        str(row.get("candidate_id") or ""): row
        for row in ranking
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    selected = rows.get(selected_id)
    challenger = rows.get(challenger_squad_id)
    if not isinstance(selected, Mapping) or not isinstance(challenger, Mapping):
        return {}

    def delta(field: str) -> float | None:
        if selected.get(field) is None or challenger.get(field) is None:
            return None
        return float(challenger[field]) - float(selected[field])

    synthesis_delta = delta("synthesis_regret")
    robust_delta = delta("robust_family_regret")
    horizon_delta = delta("horizon_family_regret")
    rank = int(challenger["rank"]) if challenger.get("rank") is not None else None
    why = None
    if synthesis_delta is not None and synthesis_delta > 0:
        rank_text = f"ranked {rank}" if rank is not None else "ranked below the winner"
        why = (
            f"Review only: the alternative is {rank_text} in the multi-gameweek synthesis "
            f"and carries {synthesis_delta:.3f} more synthesis regret than the selected squad."
        )
    return {
        "challenger_synthesis_rank": rank,
        "synthesis_regret_delta": synthesis_delta,
        "five_week_regret_delta": robust_delta,
        "eight_week_regret_delta": horizon_delta,
        "why_not_selected": why,
    }


def _decision_impacts(
    scenario: Mapping[str, Any],
    decision: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Summarise supported scenario reversals without granting them authority.

    The scenario artifact is intentionally verbose because it is a research receipt.  This
    projection gives API/UI consumers the smallest actionable description of a reversal while
    preserving the fact that every scenario is a counterfactual sensitivity bound.
    """
    values = scenario.get("scenarios")
    if not isinstance(values, Mapping):
        return []
    impacts: list[dict[str, Any]] = []
    for scenario_name in (
        "baseline",
        "moderate_role_stress",
        "severe_role_stress",
        "not_listed_dnp_boundary",
    ):
        row = values.get(scenario_name)
        if not isinstance(row, Mapping):
            continue
        replay = row.get("deep_squad_replay")
        if not isinstance(replay, Mapping) or not replay.get("cross_family_holdout_support"):
            continue
        incumbent = replay.get("incumbent_configuration")
        challenger = replay.get("challenger_configuration")
        incumbent_names = _configuration_names(incumbent)
        challenger_names = _configuration_names(challenger)
        deltas = replay.get("holdout_delta_challenger_to_incumbent") or {}
        family_means = [
            float(metric["mean"])
            for metric in deltas.values()
            if isinstance(metric, Mapping) and metric.get("mean") is not None
        ]
        challenger_squad_id = str(replay.get("challenger_squad_id") or "")
        impacts.append(
            {
                "scenario": scenario_name,
                "description": str(row.get("description") or ""),
                "challenger_squad_id": challenger_squad_id,
                "incoming": sorted(challenger_names - incumbent_names),
                "outgoing": sorted(incumbent_names - challenger_names),
                "formation": (
                    str(challenger.get("formation") or "")
                    if isinstance(challenger, Mapping)
                    else ""
                ),
                "captain": (
                    str(challenger.get("captain") or "")
                    if isinstance(challenger, Mapping)
                    else ""
                ),
                "vice_captain": (
                    str(challenger.get("vice_captain") or "")
                    if isinstance(challenger, Mapping)
                    else ""
                ),
                "minimum_family_gain": min(family_means) if family_means else None,
                "counterfactual_not_probability": True,
                **_synthesis_tradeoff(decision, challenger_squad_id),
            }
        )
    return impacts


def audit_availability_watch(
    *,
    as_of: str | datetime | None = None,
    advisory_max_age: timedelta = DEFAULT_ADVISORY_MAX_AGE,
    players_path: Path = PLAYERS,
    teams_path: Path = TEAMS,
    events_path: Path = EVENTS,
    forecast_path: Path = CURRENT_FORECAST,
    decision_path: Path = DECISION_JSON,
    role_receipt_path: Path = ROLE_RECEIPT,
    role_evidence_path: Path = ROLE_EVIDENCE,
    scenario_results_path: Path = SCENARIO_RESULTS,
    threshold_results_path: Path = THRESHOLD_RESULTS,
    participation_receipt_path: Path | None = None,
    participation_consensus_path: Path | None = None,
    output_path: Path | None = RECEIPT,
) -> dict[str, Any]:
    checked = _aware(as_of or datetime.now(tz=UTC), "as_of")
    if advisory_max_age <= timedelta(0):
        raise AvailabilityWatchError("advisory_max_age must be positive")
    issues: list[str] = []
    warnings: list[str] = []
    decision = _load_json(decision_path, "decision", issues)
    role_receipt = _load_json(role_receipt_path, "preseason role receipt", issues)
    scenario = _load_json(scenario_results_path, "preseason scenario results", issues)
    threshold = _load_json(
        threshold_results_path, "preseason threshold results", issues
    )
    players = _load_parquet(players_path, "official players table", issues)
    teams = _load_parquet(teams_path, "official teams table", issues)
    events = _load_parquet(events_path, "official events table", issues)
    forecasts = _load_parquet(forecast_path, "direct forecast", issues)
    role_rows = _load_parquet(role_evidence_path, "preseason role evidence", issues)

    # Third-party predicted lineups are deliberately optional and shadow-only.  The live
    # default consumes them when present, while isolated historical/unit replays do not
    # accidentally inherit a workstation's current receipt.
    if (
        participation_receipt_path is None
        and participation_consensus_path is None
        and players_path == PLAYERS
        and forecast_path == CURRENT_FORECAST
    ):
        participation_receipt_path = PARTICIPATION_RECEIPT
        participation_consensus_path = PARTICIPATION_CONSENSUS
    participation_receipt: dict[str, Any] | None = None
    participation_rows: list[dict[str, Any]] = []
    participation_current = False
    participation_issues: list[str] = []
    if participation_receipt_path is not None or participation_consensus_path is not None:
        if participation_receipt_path is None or participation_consensus_path is None:
            participation_issues.append(
                "participation receipt and consensus paths must be supplied together"
            )
        elif not participation_receipt_path.is_file() or not participation_consensus_path.is_file():
            participation_issues.append("predicted-lineup consensus has not been collected")
        else:
            loaded = _load_json(
                participation_receipt_path,
                "participation consensus receipt",
                participation_issues,
            )
            participation_receipt = loaded
            participation_rows = _load_parquet(
                participation_consensus_path,
                "participation consensus",
                participation_issues,
            )

    if issues:
        result = {
            "receipt_version": VERSION,
            "checked_at": checked.isoformat(),
            "status": "refresh_required",
            "current": False,
            "decision_action": "refresh_and_rerun_availability_evidence",
            "decision_change_authorized": False,
            "issues": issues,
            "warnings": warnings,
            "players": [],
        }
        if output_path is not None:
            _atomic_json(output_path, result)
        return result

    assert decision is not None
    assert role_receipt is not None
    assert scenario is not None
    assert threshold is not None

    decision_sha = sha256_file(decision_path)
    forecast_sha = sha256_file(forecast_path)
    players_sha = sha256_file(players_path)
    role_evidence_sha = sha256_file(role_evidence_path)
    role_receipt_sha = sha256_file(role_receipt_path)
    scenario_sha = sha256_file(scenario_results_path)
    threshold_sha = sha256_file(threshold_results_path)
    receipt_inputs = role_receipt.get("inputs") or {}
    receipt_outputs = role_receipt.get("outputs") or {}
    scenario_lineage = scenario.get("lineage") or {}
    threshold_lineage = threshold.get("lineage") or {}
    expected = [
        (
            receipt_outputs.get("role_evidence_sha256"),
            role_evidence_sha,
            "preseason role evidence differs from its receipt",
        ),
        (
            scenario_lineage.get("preseason_receipt_sha256"),
            role_receipt_sha,
            "preseason scenario uses a different role receipt",
        ),
        (
            scenario_lineage.get("preseason_role_evidence_sha256"),
            role_evidence_sha,
            "preseason scenario uses different role evidence",
        ),
        (
            scenario_lineage.get("decision_sha256"),
            decision_sha,
            "preseason scenario does not describe the current decision",
        ),
        (
            threshold_lineage.get("preseason_role_scenario_sha256"),
            scenario_sha,
            "preseason threshold uses a different scenario receipt",
        ),
        (
            threshold_lineage.get("preseason_role_evidence_sha256"),
            role_evidence_sha,
            "preseason threshold uses different role evidence",
        ),
        (
            threshold_lineage.get("decision_sha256"),
            decision_sha,
            "preseason threshold does not describe the current decision",
        ),
        (
            threshold_lineage.get("forecast_sha256"),
            forecast_sha,
            "preseason threshold does not describe the current forecast",
        ),
    ]
    if participation_receipt is not None and participation_consensus_path is not None:
        participation_output = participation_receipt.get("outputs") or {}
        participation_input = participation_receipt.get("inputs") or {}
        if participation_receipt.get("event") != EVENT:
            participation_issues.append("predicted-lineup consensus describes another event")
        if participation_output.get("consensus_sha256") != sha256_file(
            participation_consensus_path
        ):
            participation_issues.append("predicted-lineup consensus differs from its receipt")
        if participation_input.get("official_players_sha256") != players_sha:
            participation_issues.append(
                "predicted-lineup consensus uses a different official player generation"
            )
        if participation_input.get("forecast_sha256") != forecast_sha:
            participation_issues.append(
                "predicted-lineup consensus uses a different forecast generation"
            )
        try:
            participation_observed = _aware(
                str(participation_receipt["observed_at"]),
                "participation observed_at",
            )
            participation_age = checked - participation_observed
            if participation_age < -timedelta(minutes=5):
                participation_issues.append(
                    "predicted-lineup consensus was observed in the future"
                )
            elif participation_age > advisory_max_age:
                participation_issues.append(
                    "predicted-lineup consensus is stale: "
                    f"{int(participation_age.total_seconds())}s exceeds "
                    f"{int(advisory_max_age.total_seconds())}s"
                )
        except (AvailabilityWatchError, KeyError, ValueError) as exc:
            participation_issues.append(str(exc))
        participation_current = not participation_issues
    if participation_issues:
        warnings.extend(participation_issues)
    mapping_fingerprint = receipt_inputs.get("role_mapping_fingerprint")
    if mapping_fingerprint:
        current_mapping = fpl_role_mapping_fingerprint(teams, players, events)
        if mapping_fingerprint != current_mapping:
            issues.append("preseason role receipt uses a stale official mapping generation")
    elif receipt_inputs.get("players_sha256") != players_sha:
        issues.append("preseason role receipt uses stale official players")
    issues.extend(message for recorded, actual, message in expected if recorded != actual)
    if threshold.get("production_changed") is not False:
        issues.append("preseason threshold is not a read-only receipt")
    if threshold.get("promotion_ready") is not False:
        issues.append("preseason threshold unexpectedly authorizes promotion")

    player_snapshot = _single_text(players, "snapshot_at")
    forecast_snapshot = _single_text(
        [row for row in forecasts if int(row.get("event_number") or -1) == EVENT],
        "snapshot_at",
    )
    if player_snapshot is None:
        issues.append("official players table does not identify one snapshot")
    if forecast_snapshot is None:
        issues.append("GW1 forecast does not identify one snapshot")
    if player_snapshot != forecast_snapshot:
        issues.append("GW1 forecast is not aligned to the official players snapshot")

    try:
        collected_at = _aware(str(role_receipt["created_at"]), "role receipt created_at")
        if collected_at > checked + timedelta(minutes=5):
            issues.append("preseason role receipt was created in the future")
        age = max(timedelta(0), checked - collected_at)
        if age > advisory_max_age:
            issues.append(
                "preseason role receipt is stale: "
                f"{int(age.total_seconds())}s exceeds "
                f"{int(advisory_max_age.total_seconds())}s"
            )
    except (AvailabilityWatchError, KeyError, ValueError) as exc:
        issues.append(str(exc))
        collected_at = None

    candidate = (decision.get("decision") or {}).get("candidate") or {}
    selected = list(map(int, candidate.get("selected") or []))
    if len(selected) != 15 or len(set(selected)) != 15:
        issues.append("current decision does not contain 15 unique selected players")
    player_by_id = {int(row["id"]): row for row in players if row.get("id") is not None}
    forecast_by_id = {
        int(row["element"]): row
        for row in forecasts
        if int(row.get("event_number") or -1) == EVENT
        and row.get("element") is not None
    }
    role_by_id = {
        int(row["fpl_element"]): row
        for row in role_rows
        if row.get("fpl_element") is not None
    }
    participation_by_id = (
        {
            int(row["element"]): row
            for row in participation_rows
            if row.get("element") is not None and int(row.get("event") or -1) == EVENT
        }
        if participation_current
        else {}
    )
    frontier = _decision_frontier(
        decision,
        player_by_id=player_by_id,
        forecast_by_id=forecast_by_id,
        role_by_id=role_by_id,
        participation_by_id=participation_by_id,
        issues=issues,
    )
    missing = {
        "official": sorted(set(selected) - set(player_by_id)),
        "forecast": sorted(set(selected) - set(forecast_by_id)),
        "role": sorted(set(selected) - set(role_by_id)),
    }
    for layer, elements in missing.items():
        if elements:
            issues.append(f"selected players missing from {layer} evidence: {elements}")

    flags = (
        derive_role_flags(role_rows, set(selected))
        if selected and not missing["role"]
        else {}
    )
    boundary = threshold.get("boundary") or {}
    highest_supported = boundary.get("highest_supported_retention")
    boundary_point = next(
        (
            row
            for row in threshold.get("threshold_points") or []
            if row.get("not_listed_retention") == highest_supported
        ),
        {},
    )
    mechanical_rates = boundary_point.get("mechanical_appearance_rates") or {}

    player_rows: list[dict[str, Any]] = []
    for element in selected:
        if element not in player_by_id or element not in forecast_by_id or element not in role_by_id:
            continue
        official = player_by_id[element]
        forecast = forecast_by_id[element]
        role = role_by_id[element]
        flag = flags[element]
        attention = _attention_labels(official, flag)
        predicted = participation_by_id.get(element)
        if predicted is not None:
            predicted_attention = list(map(str, predicted.get("attention") or []))
            attention.extend(label for label in predicted_attention if label not in attention)
        mechanical = mechanical_rates.get(str(element)) or {}
        player_rows.append(
            {
                "element": element,
                "name": str(forecast.get("player_name") or official.get("web_name")),
                "team": str(forecast.get("team_name") or official.get("team")),
                "position": str(forecast.get("position") or ""),
                "official": {
                    "status": str(official.get("status") or ""),
                    "chance": _effective_official_chance(official),
                    "news": str(official.get("news") or ""),
                    "news_added": official.get("news_added"),
                    "can_select": bool(official.get("can_select")),
                    "removed": bool(official.get("removed")),
                },
                "forecast": {
                    "p_play": float(forecast["p_play"]),
                    "expected_points": float(forecast["expected_points"]),
                    "robust_points": float(forecast["robust_points"]),
                },
                "preseason": {
                    "flag": flag,
                    "evidence_status": str(role["evidence_status"]),
                    "eligible_team_matches": int(role["eligible_team_matches"]),
                    "squad_listings": int(role["squad_listings"]),
                    "starts": int(role["starts"]),
                    "appearances": int(role["appearances"]),
                    "last_match_listed": role["last_match_listed"],
                    "last_match_started": role["last_match_started"],
                    "minutes_data_complete": bool(role["minutes_data_complete"]),
                },
                "supported_edge_sensitivity": (
                    {
                        "retention_factor": float(mechanical["retention_factor"]),
                        "mechanically_retained_p_play": float(
                            mechanical["mechanically_retained_p_play"]
                        ),
                    }
                    if mechanical
                    else None
                ),
                "predicted_lineups": (
                    {
                        "consensus": str(predicted["consensus"]),
                        "predicted_start_sources": list(
                            map(str, predicted.get("predicted_start_sources") or [])
                        ),
                        "predicted_not_start_sources": list(
                            map(str, predicted.get("predicted_not_start_sources") or [])
                        ),
                        "complete_source_count": int(
                            predicted.get("complete_source_count") or 0
                        ),
                        "production_weight": 0.0,
                        "production_adjustment_authorized": False,
                    }
                    if predicted is not None
                    else None
                ),
                "attention": attention,
            }
        )

    official_risks = [
        row
        for row in player_rows
        if any(label.startswith("official_") for label in row["attention"])
    ]
    role_verification = [
        row
        for row in player_rows
        if row["preseason"]["flag"] in {FLAG_NOT_LISTED, FLAG_ROLE_WATCH}
    ]
    uncovered = [
        row for row in player_rows if row["preseason"]["flag"] == FLAG_UNCOVERED
    ]
    if role_verification:
        warnings.append(
            f"{len(role_verification)} selected players require attributable role verification"
        )
    if uncovered:
        warnings.append(
            f"{len(uncovered)} selected players have no confirmed preseason club feed"
        )
    predicted_bench = [
        row
        for row in player_rows
        if (row.get("predicted_lineups") or {}).get("consensus")
        == "predicted_bench_consensus"
    ]
    predicted_disagreement = [
        row
        for row in player_rows
        if (row.get("predicted_lineups") or {}).get("consensus")
        == "source_disagreement"
    ]
    if predicted_bench:
        warnings.append(
            f"{len(predicted_bench)} selected players have a two-source predicted-bench flag; "
            "this remains shadow evidence pending prospective calibration"
        )
    if predicted_disagreement:
        warnings.append(
            f"{len(predicted_disagreement)} selected players have contradictory predicted lineups"
        )
    stability = _scenario_stability(scenario)
    participation_sources = (
        participation_receipt.get("sources")
        if participation_receipt is not None
        and isinstance(participation_receipt.get("sources"), Mapping)
        else {}
    )
    if not stability["baseline_stable"] or not stability["moderate_stable"]:
        warnings.append(
            "independent role replay identifies supported baseline or moderate alternatives; "
            "these counterfactuals require review but do not make aligned evidence stale"
        )

    if issues:
        status = "refresh_required"
        action = "refresh_and_rerun_availability_evidence"
    elif official_risks:
        status = "official_attention"
        action = "rerun_full_deadline_pipeline_if_official_evidence_changed"
    elif not stability["baseline_stable"] or not stability["moderate_stable"]:
        status = "scenario_attention"
        action = "retain_decision_and_review_supported_alternatives"
    elif role_verification:
        status = "verification_required"
        action = "retain_decision_and_verify_flagged_players"
    elif uncovered:
        status = "advisory_gaps"
        action = "retain_decision_with_explicit_unknowns"
    else:
        status = "current_no_material_advisory_flag"
        action = "retain_current_decision"

    result = {
        "receipt_version": VERSION,
        "checked_at": checked.isoformat(),
        "status": status,
        "current": not issues,
        "decision_action": action,
        "decision_change_authorized": False,
        "authority": (
            "Official status is already represented by the aligned forecast. Preseason lineup "
            "evidence and sensitivity factors are advisory and cannot directly change production."
        ),
        "evidence_hierarchy": {
            "production": [
                "official_fpl_status_and_news",
                "historically_validated_minute_model",
            ],
            "deadline_override_requires": (
                "timestamped official club, manager press-conference or official FPL evidence"
            ),
            "context_only": ["preseason_friendly_lineups"],
            "prospective_shadow": ["independent_predicted_lineup_consensus"],
            "predicted_lineup_production_weight": 0.0,
            "preseason_friendly_production_weight": 0.0,
            "reason": (
                "The historical role-feature challenger lost points in exact legal replay; "
                "post-tournament return schedules and experimental friendly teams are confounders."
            ),
        },
        "lineage": {
            "decision_sha256": decision_sha,
            "forecast_sha256": forecast_sha,
            "official_players_sha256": players_sha,
            "role_receipt_sha256": role_receipt_sha,
            "role_evidence_sha256": role_evidence_sha,
            "scenario_results_sha256": scenario_sha,
            "threshold_results_sha256": threshold_sha,
            "official_snapshot_at": player_snapshot,
            "forecast_snapshot_at": forecast_snapshot,
            "role_collected_at": (
                collected_at.isoformat() if collected_at is not None else None
            ),
        },
        "scenario_stability": stability,
        "predicted_lineup_consensus": {
            "collected": participation_receipt is not None,
            "current": participation_current,
            "status": (
                participation_receipt.get("status")
                if participation_receipt is not None
                else "not_collected"
            ),
            "production_weight": 0.0,
            "production_adjustment_authorized": False,
            "promotion_gate": (
                participation_receipt.get("promotion_gate") or {}
                if participation_receipt is not None
                else {}
            ),
            "summary": (
                participation_receipt.get("summary") or {}
                if participation_receipt is not None
                else {}
            ),
            "eligible_source_count": (
                sum(
                    bool(source.get("decision_eligible"))
                    for source in participation_sources.values()
                    if isinstance(source, Mapping)
                )
                if participation_receipt is not None
                else 0
            ),
            "captured_source_count": (
                sum(
                    source.get("status") == "captured"
                    for source in participation_sources.values()
                    if isinstance(source, Mapping)
                )
                if participation_receipt is not None
                else 0
            ),
            "issues": participation_issues,
        },
        "decision_frontier": frontier,
        "decision_impacts": _decision_impacts(scenario, decision),
        "coverage": {
            "teams": (scenario.get("coverage") or {}).get("teams"),
            "teams_with_confirmed_lineups": (scenario.get("coverage") or {}).get(
                "teams_with_confirmed_lineups"
            ),
            "teams_without_confirmed_lineups": list(
                map(
                    str,
                    (scenario.get("coverage") or {}).get(
                        "teams_without_confirmed_lineups"
                    )
                    or [],
                )
            ),
        },
        "threshold_boundary": {
            "classification": boundary.get("classification"),
            "highest_supported_not_listed_retention": highest_supported,
            "highest_supported_role_watch_retention": boundary.get(
                "highest_supported_role_watch_retention"
            ),
            "next_unsupported_not_listed_retention": boundary.get(
                "next_tested_unsupported_retention"
            ),
            "counterfactual_not_probability": True,
        },
        "summary": {
            "selected_players": len(player_rows),
            "official_attention": len(official_risks),
            "role_verification": len(role_verification),
            "uncovered_club_feed": len(uncovered),
            "no_attention": sum(not row["attention"] for row in player_rows),
        },
        "players": player_rows,
        "issues": issues,
        "warnings": warnings,
    }
    if output_path is not None:
        _atomic_json(output_path, result)
    return result
