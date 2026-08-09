from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
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

VERSION = 1
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
    stability = _scenario_stability(scenario)
    if not stability["baseline_stable"] or not stability["moderate_stable"]:
        issues.append("published decision is not stable in baseline and moderate role scenarios")

    if issues:
        status = "refresh_required"
        action = "refresh_and_rerun_availability_evidence"
    elif official_risks:
        status = "official_attention"
        action = "rerun_full_deadline_pipeline_if_official_evidence_changed"
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
