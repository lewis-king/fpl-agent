from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .paths import DECISIONS

SCHEDULE_RECEIPT_VERSION = 1
CURRENT_FIXTURES = PROCESSED / "fpl" / "2026-27" / "preseason" / "fixtures.parquet"
CURRENT_TEAMS = PROCESSED / "fpl" / "2026-27" / "preseason" / "teams.parquet"
CURRENT_SCHEDULE_RECEIPT = DECISIONS / "schedule" / "2026-27-current.json"
SCHEDULE_ARCHIVE_ROOT = DECISIONS / "schedule" / "archive"
LATEST_SCHEDULE_CHANGE = DECISIONS / "schedule" / "2026-27-latest-change.json"


class ScheduleValidationError(ValueError):
    """Raised when an official fixture generation cannot form a safe schedule contract."""


def _fingerprint(value: Mapping[str, Any] | Sequence[Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    rendered = json.dumps(dict(value), indent=2, sort_keys=True, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ScheduleValidationError(f"immutable schedule receipt collision: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _optional_int(value: Any, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleValidationError(f"fixture {field} must be an integer or null") from exc


def _required_int(value: Any, field: str) -> int:
    parsed = _optional_int(value, field)
    if parsed is None:
        raise ScheduleValidationError(f"fixture {field} is required")
    return parsed


def _fixture_status(row: Mapping[str, Any]) -> str:
    if row.get("event") is None or row.get("event") == "":
        return "unassigned"
    if bool(row.get("finished")):
        return "confirmed"
    if bool(row.get("provisional_start_time")) or not row.get("kickoff_time"):
        return "provisional"
    return "confirmed"


def _normalise_fixture(row: Mapping[str, Any]) -> dict[str, Any]:
    fixture_id = _required_int(row.get("id"), "id")
    home = _required_int(row.get("team_h"), "team_h")
    away = _required_int(row.get("team_a"), "team_a")
    if home == away:
        raise ScheduleValidationError(f"fixture {fixture_id} has the same home and away team")
    event = _optional_int(row.get("event"), "event")
    kickoff = row.get("kickoff_time")
    return {
        "fixture_id": fixture_id,
        "event": event,
        "kickoff_time": str(kickoff) if kickoff not in (None, "") else None,
        "team_h": home,
        "team_a": away,
        "finished": bool(row.get("finished")),
        "started": bool(row.get("started")),
        "provisional_start_time": bool(row.get("provisional_start_time")),
        "status": _fixture_status(row),
    }


def analyse_schedule_rows(
    fixture_rows: Iterable[Mapping[str, Any]],
    *,
    team_ids: Iterable[int] | None = None,
    events: Iterable[int] = range(1, 39),
    season: str = "2026-27",
    snapshot_at: str | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fixtures = sorted(
        (_normalise_fixture(row) for row in fixture_rows),
        key=lambda row: row["fixture_id"],
    )
    if not fixtures:
        raise ScheduleValidationError("official fixture schedule is empty")
    fixture_ids = [row["fixture_id"] for row in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise ScheduleValidationError("official fixture schedule contains duplicate fixture IDs")

    event_ids = sorted({int(event) for event in events})
    if not event_ids or event_ids[0] < 1:
        raise ScheduleValidationError("schedule events must be positive")
    known_teams = sorted(
        {int(team) for team in team_ids}
        if team_ids is not None
        else {int(row[field]) for row in fixtures for field in ("team_h", "team_a")}
    )
    if not known_teams:
        raise ScheduleValidationError("schedule has no known teams")
    known_team_set = set(known_teams)
    fixture_team_set = {int(row[field]) for row in fixtures for field in ("team_h", "team_a")}
    unknown = sorted(fixture_team_set.difference(known_team_set))
    if unknown:
        raise ScheduleValidationError(f"fixtures reference unknown teams: {unknown}")
    invalid_events = sorted(
        {
            int(row["event"])
            for row in fixtures
            if row["event"] is not None and int(row["event"]) not in set(event_ids)
        }
    )
    if invalid_events:
        raise ScheduleValidationError(f"fixtures reference events outside the contract: {invalid_events}")

    fixtures_by_team_event: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    unassigned_by_team: Counter[int] = Counter()
    total_by_team: Counter[int] = Counter()
    for fixture in fixtures:
        for team in (fixture["team_h"], fixture["team_a"]):
            total_by_team[int(team)] += 1
            if fixture["event"] is None:
                unassigned_by_team[int(team)] += 1
            else:
                fixtures_by_team_event[(int(team), int(fixture["event"]))].append(fixture)

    team_events: list[dict[str, Any]] = []
    for event in event_ids:
        for team in known_teams:
            assigned = fixtures_by_team_event[(team, event)]
            confirmed = sum(row["status"] == "confirmed" for row in assigned)
            provisional = sum(row["status"] == "provisional" for row in assigned)
            fixture_count = len(assigned)
            kind = (
                "blank"
                if fixture_count == 0
                else "single"
                if fixture_count == 1
                else "double"
                if fixture_count == 2
                else "triple_plus"
            )
            assigned_certainty = "confirmed" if provisional == 0 else "provisional"
            unresolved = int(unassigned_by_team[team])
            schedule_certainty = (
                "confirmed"
                if assigned_certainty == "confirmed" and unresolved == 0
                else "at_risk"
            )
            team_events.append(
                {
                    "event": event,
                    "team_id": team,
                    "kind": kind,
                    "fixture_count": fixture_count,
                    "confirmed_fixture_count": confirmed,
                    "provisional_fixture_count": provisional,
                    "unassigned_team_fixtures": unresolved,
                    "assigned_certainty": assigned_certainty,
                    "schedule_certainty": schedule_certainty,
                    "fixture_ids": [row["fixture_id"] for row in assigned],
                }
            )

    event_summaries = []
    for event in event_ids:
        rows = [row for row in team_events if row["event"] == event]
        assigned_fixtures = [row for row in fixtures if row["event"] == event]
        event_summaries.append(
            {
                "event": event,
                "fixture_count": len(assigned_fixtures),
                "confirmed_fixture_count": sum(
                    row["status"] == "confirmed" for row in assigned_fixtures
                ),
                "provisional_fixture_count": sum(
                    row["status"] == "provisional" for row in assigned_fixtures
                ),
                "blank_teams": [row["team_id"] for row in rows if row["kind"] == "blank"],
                "double_teams": [row["team_id"] for row in rows if row["kind"] == "double"],
                "triple_plus_teams": [
                    row["team_id"] for row in rows if row["kind"] == "triple_plus"
                ],
                "at_risk_teams": [
                    row["team_id"] for row in rows if row["schedule_certainty"] != "confirmed"
                ],
            }
        )

    status_counts = Counter(row["status"] for row in fixtures)
    exceptional = [
        row
        for row in team_events
        if row["kind"] != "single" or row["schedule_certainty"] != "confirmed"
    ]
    canonical_schedule = {
        "season": season,
        "teams": known_teams,
        "events": event_ids,
        "fixtures": fixtures,
    }
    body: dict[str, Any] = {
        "receipt_version": SCHEDULE_RECEIPT_VERSION,
        "season": season,
        "snapshot_at": snapshot_at,
        "source": dict(source or {}),
        "schedule_fingerprint": _fingerprint(canonical_schedule),
        "summary": {
            "teams": len(known_teams),
            "events": len(event_ids),
            "fixtures": len(fixtures),
            "confirmed_fixtures": int(status_counts["confirmed"]),
            "provisional_fixtures": int(status_counts["provisional"]),
            "unassigned_fixtures": int(status_counts["unassigned"]),
            "fully_assigned_and_timed": bool(
                status_counts["provisional"] == 0 and status_counts["unassigned"] == 0
            ),
            "minimum_team_fixtures": min(total_by_team.values(), default=0),
            "maximum_team_fixtures": max(total_by_team.values(), default=0),
            "exceptional_team_events": len(exceptional),
        },
        "fixtures": fixtures,
        "team_events": team_events,
        "event_summaries": event_summaries,
        "exceptional_team_events": exceptional,
    }
    body["receipt_fingerprint"] = _fingerprint(body)
    return body


def compare_schedule_receipts(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    previous_rows = {int(row["fixture_id"]): row for row in previous.get("fixtures", [])}
    current_rows = {int(row["fixture_id"]): row for row in current.get("fixtures", [])}
    changes: list[dict[str, Any]] = []
    fields = (
        "event",
        "kickoff_time",
        "team_h",
        "team_a",
        "provisional_start_time",
        "status",
    )
    for fixture_id in sorted(set(previous_rows) | set(current_rows)):
        before = previous_rows.get(fixture_id)
        after = current_rows.get(fixture_id)
        if before is None:
            changes.append({"fixture_id": fixture_id, "change": "added", "after": after})
            continue
        if after is None:
            changes.append({"fixture_id": fixture_id, "change": "removed", "before": before})
            continue
        changed_fields = {
            field: {"before": before.get(field), "after": after.get(field)}
            for field in fields
            if before.get(field) != after.get(field)
        }
        if changed_fields:
            changes.append(
                {"fixture_id": fixture_id, "change": "updated", "fields": changed_fields}
            )
    affected_event_values: set[int] = set()
    for change in changes:
        for payload in (change.get("before"), change.get("after")):
            if isinstance(payload, Mapping) and payload.get("event") is not None:
                affected_event_values.add(int(payload["event"]))
        event_change = change.get("fields", {}).get("event")
        if isinstance(event_change, Mapping):
            for value in (event_change.get("before"), event_change.get("after")):
                if value is not None:
                    affected_event_values.add(int(value))
    affected_events = sorted(affected_event_values)
    affected_teams = sorted(
        {
            int(row[field])
            for fixture_id in {change["fixture_id"] for change in changes}
            for row in (previous_rows.get(fixture_id), current_rows.get(fixture_id))
            if row is not None
            for field in ("team_h", "team_a")
        }
    )
    return {
        "comparison_version": 1,
        "previous_receipt_fingerprint": previous.get("receipt_fingerprint"),
        "current_receipt_fingerprint": current.get("receipt_fingerprint"),
        "changed": bool(changes),
        "change_count": len(changes),
        "affected_events": affected_events,
        "affected_teams": affected_teams,
        "changes": changes,
    }


def schedule_horizon_status(
    receipt: Mapping[str, Any],
    *,
    events: Iterable[int],
    team_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    selected_events = sorted({int(event) for event in events})
    selected_teams = {int(team) for team in team_ids} if team_ids is not None else None
    rows = [
        row
        for row in receipt.get("team_events", [])
        if int(row["event"]) in selected_events
        and (selected_teams is None or int(row["team_id"]) in selected_teams)
    ]
    expected_teams = selected_teams or {int(row["team_id"]) for row in receipt.get("team_events", [])}
    expected_rows = len(selected_events) * len(expected_teams)
    issues = []
    if len(rows) != expected_rows:
        issues.append(
            f"schedule horizon has {len(rows)} team-event rows; expected {expected_rows}"
        )
    at_risk = [row for row in rows if row.get("schedule_certainty") != "confirmed"]
    if at_risk:
        issues.append(f"{len(at_risk)} team-event schedule opportunities remain at risk")
    return {
        "events": selected_events,
        "teams": sorted(expected_teams),
        "rows": len(rows),
        "fully_confirmed": not issues,
        "issues": issues,
        "at_risk_team_events": at_risk,
        "blank_team_events": [row for row in rows if row.get("kind") == "blank"],
        "double_team_events": [row for row in rows if row.get("kind") == "double"],
        "triple_plus_team_events": [
            row for row in rows if row.get("kind") == "triple_plus"
        ],
    }


def load_schedule_receipt(
    path: Path = CURRENT_SCHEDULE_RECEIPT,
    *,
    expected_fixtures_path: Path | None = CURRENT_FIXTURES,
    expected_snapshot_at: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScheduleValidationError(f"schedule receipt is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("receipt_version") != SCHEDULE_RECEIPT_VERSION:
        raise ScheduleValidationError("schedule receipt has an unsupported version")
    recorded_fingerprint = payload.get("receipt_fingerprint")
    body = {key: value for key, value in payload.items() if key != "receipt_fingerprint"}
    if recorded_fingerprint != _fingerprint(body):
        raise ScheduleValidationError("schedule receipt fingerprint does not match its contents")
    if expected_fixtures_path is not None:
        if not expected_fixtures_path.is_file():
            raise ScheduleValidationError(
                f"expected fixture artifact is missing: {expected_fixtures_path}"
            )
        expected_hash = sha256_file(expected_fixtures_path)
        if payload.get("source", {}).get("fixtures_sha256") != expected_hash:
            raise ScheduleValidationError(
                "schedule receipt does not reference the active fixture artifact bytes"
            )
    if expected_snapshot_at is not None and str(payload.get("snapshot_at")) != str(
        expected_snapshot_at
    ):
        raise ScheduleValidationError(
            "schedule receipt snapshot does not match the active forecast generation"
        )
    return payload


def build_schedule_receipt(
    *,
    fixtures_path: Path = CURRENT_FIXTURES,
    teams_path: Path = CURRENT_TEAMS,
    current_path: Path = CURRENT_SCHEDULE_RECEIPT,
    archive_root: Path = SCHEDULE_ARCHIVE_ROOT,
    change_path: Path = LATEST_SCHEDULE_CHANGE,
    events: Iterable[int] = range(1, 39),
) -> dict[str, Any]:
    try:
        fixture_table = pq.read_table(fixtures_path)
        team_table = pq.read_table(teams_path, columns=["id"])
    except (OSError, pa.ArrowException) as exc:
        raise ScheduleValidationError("official fixture or team schedule artifact is unreadable") from exc
    rows = fixture_table.to_pylist()
    snapshot_values = {
        str(value)
        for value in fixture_table["snapshot_at"].to_pylist()
        if value not in (None, "")
    } if "snapshot_at" in fixture_table.column_names else set()
    if len(snapshot_values) > 1:
        raise ScheduleValidationError("fixture artifact contains multiple snapshot_at values")
    source_hash = sha256_file(fixtures_path)
    receipt = analyse_schedule_rows(
        rows,
        team_ids=(int(value) for value in team_table["id"].to_pylist()),
        events=events,
        snapshot_at=next(iter(snapshot_values), None),
        source={"fixtures_path": str(fixtures_path), "fixtures_sha256": source_hash},
    )
    archive_path = archive_root / f"{source_hash}.json"
    previous: dict[str, Any] | None = None
    if current_path.is_file():
        try:
            loaded = json.loads(current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            previous = loaded
    _write_immutable_json(archive_path, receipt)
    _atomic_json(current_path, receipt)
    comparison = compare_schedule_receipts(previous, receipt) if previous else None
    if comparison is not None:
        _atomic_json(change_path, comparison)
    return {
        **receipt,
        "current_path": str(current_path),
        "archive_path": str(archive_path),
        "comparison": comparison,
    }
