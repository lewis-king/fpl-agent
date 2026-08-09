from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file

from .paths import MODEL_DATA

HISTORICAL_FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "vaastav_deadlines"
    / "fixture_snapshots.parquet"
)
OUTPUT_ROOT = MODEL_DATA / "chip_schedule_v1"
OPPORTUNITIES = OUTPUT_ROOT / "historical-opportunities.parquet"
RECEIPT = OUTPUT_ROOT / "receipt.json"

OPPORTUNITY_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("decision_event", pa.int64()),
        ("deadline_at", pa.string()),
        ("observed_at", pa.string()),
        ("snapshot_sha", pa.string()),
        ("future_event", pa.int64()),
        ("events_ahead", pa.int64()),
        ("current_rule_half", pa.int64()),
        ("within_current_rule_half", pa.bool_()),
        ("team_count", pa.int64()),
        ("assigned_fixture_count", pa.int64()),
        ("provisional_fixture_count", pa.int64()),
        ("unassigned_fixture_count", pa.int64()),
        ("blank_team_count", pa.int64()),
        ("double_team_count", pa.int64()),
        ("triple_plus_team_count", pa.int64()),
        ("blank_team_ids", pa.list_(pa.int64())),
        ("double_team_ids", pa.list_(pa.int64())),
        ("triple_plus_team_ids", pa.list_(pa.int64())),
        ("unassigned_team_ids", pa.list_(pa.int64())),
        ("opportunity_kind", pa.string()),
        ("schedule_confirmed", pa.bool_()),
    ]
)


def _aware(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _opportunity_kind(blanks: int, doubles: int, triples: int) -> str:
    if triples:
        return "triple_plus"
    if blanks and doubles:
        return "blank_and_double"
    if blanks:
        return "blank"
    if doubles:
        return "double"
    return "ordinary"


def build_historical_chip_schedule_opportunities(
    *,
    fixture_path: Path = HISTORICAL_FIXTURES,
    output_path: Path = OPPORTUNITIES,
    receipt_path: Path = RECEIPT,
) -> dict[str, Any]:
    """Freeze blank/double opportunities visible in each pre-deadline snapshot."""
    rows = pq.read_table(fixture_path).to_pylist()
    if not rows:
        raise ValueError("historical deadline fixture snapshots are empty")
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    metadata: dict[tuple[str, int, str], tuple[datetime, datetime]] = {}
    for row in rows:
        if row.get("decision_event") is None:
            continue
        key = (
            str(row["season"]),
            int(row["decision_event"]),
            str(row["snapshot_sha"]),
        )
        deadline = _aware(row["deadline_at"], "deadline_at")
        observed = _aware(row["observed_at"], "observed_at")
        if observed >= deadline:
            raise ValueError(
                f"fixture snapshot {key} was not observed before its decision deadline"
            )
        prior = metadata.setdefault(key, (deadline, observed))
        if prior != (deadline, observed):
            raise ValueError(f"fixture snapshot {key} mixes decision timestamps")
        grouped[key].append(row)
    if not grouped:
        raise ValueError("historical fixture snapshots have no decision-event groups")

    output_rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        season, decision_event, snapshot_sha = key
        snapshot = grouped[key]
        deadline, observed = metadata[key]
        teams = sorted(
            {
                int(row[field])
                for row in snapshot
                for field in ("team_h", "team_a")
                if row.get(field) is not None
            }
        )
        if len(teams) < 2:
            raise ValueError(f"fixture snapshot {key} has fewer than two teams")
        unassigned = [row for row in snapshot if row.get("event") is None]
        unassigned_teams = sorted(
            {
                int(row[field])
                for row in unassigned
                for field in ("team_h", "team_a")
            }
        )
        fixtures_by_event: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in snapshot:
            if row.get("event") is not None:
                fixtures_by_event[int(row["event"])].append(row)
        half = 1 if decision_event <= 19 else 2
        half_end = 19 if half == 1 else 38
        for future_event in range(decision_event, 39):
            assigned = fixtures_by_event[future_event]
            counts = {team: 0 for team in teams}
            for fixture in assigned:
                counts[int(fixture["team_h"])] += 1
                counts[int(fixture["team_a"])] += 1
            blanks = sorted(team for team, count in counts.items() if count == 0)
            doubles = sorted(team for team, count in counts.items() if count == 2)
            triples = sorted(team for team, count in counts.items() if count >= 3)
            provisional = sum(
                bool(row.get("provisional_start_time")) or row.get("kickoff_time") is None
                for row in assigned
            )
            output_rows.append(
                {
                    "season": season,
                    "decision_event": decision_event,
                    "deadline_at": deadline.isoformat(),
                    "observed_at": observed.isoformat(),
                    "snapshot_sha": snapshot_sha,
                    "future_event": future_event,
                    "events_ahead": future_event - decision_event,
                    "current_rule_half": half,
                    "within_current_rule_half": future_event <= half_end,
                    "team_count": len(teams),
                    "assigned_fixture_count": len(assigned),
                    "provisional_fixture_count": provisional,
                    "unassigned_fixture_count": len(unassigned),
                    "blank_team_count": len(blanks),
                    "double_team_count": len(doubles),
                    "triple_plus_team_count": len(triples),
                    "blank_team_ids": blanks,
                    "double_team_ids": doubles,
                    "triple_plus_team_ids": triples,
                    "unassigned_team_ids": unassigned_teams,
                    "opportunity_kind": _opportunity_kind(
                        len(blanks), len(doubles), len(triples)
                    ),
                    "schedule_confirmed": not unassigned and provisional == 0,
                }
            )
    output_rows.sort(
        key=lambda row: (
            row["season"],
            row["decision_event"],
            row["future_event"],
        )
    )
    write_table(pa.Table.from_pylist(output_rows, schema=OPPORTUNITY_SCHEMA), output_path)
    seasons = {}
    for season in sorted({row["season"] for row in output_rows}):
        season_rows = [row for row in output_rows if row["season"] == season]
        snapshots = sorted({row["decision_event"] for row in season_rows})
        exceptional = [
            row for row in season_rows if row["opportunity_kind"] != "ordinary"
        ]
        seasons[season] = {
            "decision_snapshots": len(snapshots),
            "first_decision_event": min(snapshots),
            "last_decision_event": max(snapshots),
            "future_event_rows": len(season_rows),
            "known_exceptional_rows": len(exceptional),
            "confirmed_exceptional_rows": sum(
                bool(row["schedule_confirmed"]) for row in exceptional
            ),
            "maximum_blank_teams": max(
                (row["blank_team_count"] for row in season_rows), default=0
            ),
            "maximum_double_teams": max(
                (row["double_team_count"] for row in season_rows), default=0
            ),
        }
    receipt = {
        "receipt_version": 1,
        "status": "ready",
        "input_path": str(fixture_path),
        "input_sha256": sha256_file(fixture_path),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "rows": len(output_rows),
        "decision_snapshots": len(grouped),
        "seasons": seasons,
        "information_policy": (
            "Every schedule row comes from the latest archived Git snapshot observed before that "
            "decision deadline. Final later fixture allocation is never backfilled."
        ),
        "current_rule_note": (
            "within_current_rule_half applies the 2026/27 GW19 expiry boundary as an analysis "
            "window; it does not claim historical seasons used identical chip inventories."
        ),
        "authority": False,
        "next_gate": (
            "Join these point-in-time opportunities to legal WC/FH policy replay and calibrate "
            "retained option value on selection seasons before untouched/prospective tests."
        ),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(receipt_path)
    return receipt
