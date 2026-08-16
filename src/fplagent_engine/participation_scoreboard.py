from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.event_outcomes import latest_event_outcome
from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import SnapshotValidationError
from fplagent_data.participation_consensus import SNAPSHOT_DIR

from .matched_policy import matched_legal_policy_replay
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

VERSION = "participation_prospective_scoreboard_v1"
OUTPUT_DIR = MODEL_DATA / "participation_consensus_v1"
RESULTS = OUTPUT_DIR / "scoreboard.json"
REPORT = REPORTS / "participation-consensus-scoreboard.md"
MINIMUM_EVENTS = 6
MINIMUM_TWO_SOURCE_TEAMS = 10


class ParticipationScoreboardError(ValueError):
    """A frozen participation snapshot or its outcome is incoherent."""


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _latest_frozen_snapshots(snapshot_root: Path) -> dict[int, Path]:
    snapshots: dict[int, tuple[datetime, Path]] = {}
    if not snapshot_root.is_dir():
        return {}
    for manifest_path in snapshot_root.glob("event-*/*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            event = int(manifest["event"])
            observed = datetime.fromisoformat(str(manifest["observed_at"]))
            deadline = datetime.fromisoformat(str(manifest["deadline_time"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if observed.tzinfo is None or deadline.tzinfo is None or observed >= deadline:
            continue
        current = snapshots.get(event)
        if current is None or observed > current[0]:
            snapshots[event] = (observed, manifest_path.parent)
    return {event: value[1] for event, value in snapshots.items()}


def _load_snapshot(path: Path) -> tuple[dict[str, Any], list[dict], list[dict]]:
    manifest_path = path / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = manifest["outputs"]
        observations_path = path / "predicted_lineup_observations.parquet"
        consensus_path = path / "participation_consensus.parquet"
        if outputs["snapshot_observations_sha256"] != sha256_file(observations_path):
            raise ParticipationScoreboardError("frozen participation observations changed")
        if outputs["snapshot_consensus_sha256"] != sha256_file(consensus_path):
            raise ParticipationScoreboardError("frozen participation consensus changed")
        observations = pq.read_table(observations_path).to_pylist()
        consensus = pq.read_table(consensus_path).to_pylist()
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ParticipationScoreboardError(f"invalid participation snapshot: {path}") from exc
    return manifest, observations, consensus


def _actual_starts(live: Mapping[str, Any]) -> dict[int, bool]:
    values = live.get("elements")
    if not isinstance(values, list) or not values:
        raise ParticipationScoreboardError("event outcome contains no players")
    result = {}
    for row in values:
        if not isinstance(row, Mapping) or not isinstance(row.get("stats"), Mapping):
            raise ParticipationScoreboardError("event outcome contains invalid player stats")
        stats = row["stats"]
        if "starts" not in stats:
            raise ParticipationScoreboardError(
                "event outcome has no official starts field; exact lineup scoring is unavailable"
            )
        result[int(row["id"])] = int(stats["starts"]) > 0
    return result


def _actual_points(live: Mapping[str, Any]) -> dict[int, float]:
    values = live.get("elements")
    if not isinstance(values, list) or not values:
        raise ParticipationScoreboardError("event outcome contains no players")
    return {
        int(row["id"]): float((row.get("stats") or {}).get("total_points") or 0.0)
        for row in values
        if isinstance(row, Mapping) and row.get("id") is not None
    }


def _consensus_expected_points(row: Mapping[str, Any]) -> float | None:
    expected = row.get("champion_expected_points")
    if expected is None:
        return None
    expected = float(expected)
    p_play = float(row.get("champion_p_play") or 0.0)
    conditional = expected / max(p_play, 0.20)
    source_count = int(row.get("complete_source_count") or 0)
    starts = len(row.get("predicted_start_sources") or [])
    benches = len(row.get("predicted_not_start_sources") or [])
    if source_count >= 2 and starts == source_count:
        consensus_play = max(p_play, 0.92)
    elif source_count >= 2 and benches == source_count:
        consensus_play = min(p_play, 0.30)
    else:
        consensus_play = p_play
    adjustment = conditional * consensus_play - expected
    bound = 0.30 * abs(expected)
    return expected + max(-bound, min(bound, adjustment))


def _legal_policy_score(
    consensus: list[dict[str, Any]], actual_points: Mapping[int, float]
) -> dict[str, Any] | None:
    rows = []
    for row in consensus:
        challenger = _consensus_expected_points(row)
        element = int(row["element"])
        required = (
            row.get("position"),
            row.get("market_price"),
            row.get("champion_expected_points"),
        )
        if (
            challenger is None
            or any(value in (None, "") for value in required)
            or element not in actual_points
        ):
            continue
        rows.append(
            {
                "season": str(row.get("season") or ""),
                "event_number": int(row["event"]),
                "element": element,
                "player_name": str(row.get("player_name") or element),
                "position": str(row["position"]),
                "team_id": int(row["team_id"]),
                "market_price": float(row["market_price"]),
                "target_points": float(actual_points[element]),
                "champion_expected_points": float(row["champion_expected_points"]),
                "consensus_expected_points": challenger,
            }
        )
    if len(rows) < 100:
        return None
    replay = matched_legal_policy_replay(
        rows,
        champion_field="champion_expected_points",
        challenger_field="consensus_expected_points",
    )
    return {
        "delta_to_champion": replay["total_delta"],
        "matched_events": replay["matched_events"],
        "contract": replay["contract"],
    }


def _top_eleven(
    rows: list[dict[str, Any]], score: Callable[[dict[str, Any]], tuple[float, float]]
) -> set[int]:
    ranked = sorted(rows, key=score, reverse=True)
    return {int(row["element"]) for row in ranked[:11]}


def score_participation_snapshot(
    consensus: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    actual_starts: Mapping[int, bool],
    actual_points: Mapping[int, float] | None = None,
) -> dict[str, Any]:
    """Compare the frozen consensus and each source with the frozen minute champion."""
    by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in consensus:
        by_team[int(row["team_id"])].append(row)
    complete_sources: dict[int, set[str]] = defaultdict(set)
    source_starts: dict[tuple[int, str], set[int]] = defaultdict(set)
    for row in observations:
        if not row.get("decision_eligible") or not row.get("source_complete"):
            continue
        team = int(row["team_id"])
        source = str(row["source_id"])
        complete_sources[team].add(source)
        if row.get("fpl_element") is not None:
            source_starts[(team, source)].add(int(row["fpl_element"]))

    team_rows = []
    source_hits: dict[str, list[int]] = defaultdict(list)
    for team, sources in sorted(complete_sources.items()):
        players = by_team.get(team, [])
        actual = {int(row["element"]) for row in players if actual_starts.get(int(row["element"]))}
        # A double gameweek has more than 11 official starts for a team and is deliberately
        # excluded until fixture-specific consensus is available.
        if len(actual) != 11 or len(players) < 11:
            continue
        baseline = _top_eleven(
            players,
            lambda row: (
                float(row.get("champion_p_start") or 0.0),
                float(row.get("champion_p_play") or 0.0),
            ),
        )

        def consensus_score(row: dict[str, Any]) -> tuple[float, float]:
            eligible = max(int(row.get("complete_source_count") or 0), 1)
            start_votes = len(row.get("predicted_start_sources") or [])
            return (
                start_votes / eligible,
                float(row.get("champion_p_start") or 0.0),
            )

        challenger = _top_eleven(players, consensus_score)
        baseline_hits = len(baseline & actual)
        challenger_hits = len(challenger & actual)
        for source in sources:
            source_hits[source].append(len(source_starts[(team, source)] & actual))
        team_rows.append(
            {
                "team_id": team,
                "source_count": len(sources),
                "baseline_hits": baseline_hits,
                "consensus_hits": challenger_hits,
                "delta": challenger_hits - baseline_hits,
            }
        )
    return {
        "teams_scored": len(team_rows),
        "two_source_teams": sum(row["source_count"] >= 2 for row in team_rows),
        "baseline_mean_hits": mean([row["baseline_hits"] for row in team_rows])
        if team_rows
        else None,
        "consensus_mean_hits": mean([row["consensus_hits"] for row in team_rows])
        if team_rows
        else None,
        "mean_delta_to_champion": mean([row["delta"] for row in team_rows]) if team_rows else None,
        "source_mean_hits": {
            source: mean(values) for source, values in sorted(source_hits.items()) if values
        },
        "teams": team_rows,
        "legal_policy": _legal_policy_score(consensus, actual_points or {}),
    }


def _promotion_gate(events: list[dict[str, Any]]) -> dict[str, Any]:
    qualifying = [
        row
        for row in events
        if row["two_source_teams"] >= MINIMUM_TWO_SOURCE_TEAMS
        and row.get("mean_delta_to_champion") is not None
    ]
    deltas = [float(row["mean_delta_to_champion"]) for row in qualifying]
    aggregate = mean(deltas) if deltas else None
    standard_error = stdev(deltas) / math.sqrt(len(deltas)) if len(deltas) >= 2 else None
    lower = aggregate - 1.96 * standard_error if standard_error is not None else None
    legal_deltas = [
        float(row["legal_policy"]["delta_to_champion"])
        for row in qualifying
        if isinstance(row.get("legal_policy"), Mapping)
    ]
    checks = {
        "minimum_six_completed_events": len(qualifying) >= MINIMUM_EVENTS,
        "two_independent_sources_on_ten_teams_per_event": len(qualifying) == len(events)
        and bool(events),
        "positive_mean_lineup_hit_lift": aggregate is not None and aggregate > 0.0,
        "non_negative_event_floor": bool(deltas) and min(deltas) >= 0.0,
        "confidence_lower_bound_non_negative": lower is not None and lower >= 0.0,
        "legal_policy_scored_for_every_qualifying_event": len(legal_deltas) == len(qualifying)
        and bool(qualifying),
        "positive_aggregate_legal_policy_lift": bool(legal_deltas) and sum(legal_deltas) > 0.0,
        "non_negative_legal_policy_event_floor": bool(legal_deltas) and min(legal_deltas) >= 0.0,
    }
    passed = all(checks.values())
    return {
        "passed": passed,
        "state": "prospectively_validated" if passed else "awaiting_prospective_evidence",
        "checks": checks,
        "qualifying_events": len(qualifying),
        "mean_delta_to_champion": aggregate,
        "ci95_low": lower,
        "legal_policy_total_delta": sum(legal_deltas) if legal_deltas else None,
        "production_changed": False,
        "authority": (
            "A pass confirms both role accuracy and legal-decision lift. It authorizes a bounded "
            "production challenger, not an unreviewed forecast replacement."
        ),
    }


def _render_report(result: Mapping[str, Any]) -> str:
    gate = result["promotion_gate"]
    lines = [
        "# Predicted-lineup prospective scoreboard",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Completed events scored:** {len(result['events'])}  ",
        f"**Gate:** {'PASS TO LEGAL REPLAY' if gate['passed'] else 'HOLD SHADOW'}  ",
        "**Production changed:** no",
        "",
        (
            "Every row is scored from the latest immutable capture made before that event's "
            "deadline. The challenger ranks each club's XI by independent-source vote share, "
            "using the production start probability only as a tie-breaker."
        ),
        "",
        "| GW | Teams | Two-source teams | Champion hits | Consensus hits | Delta |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["events"]:
        lines.append(
            f"| {row['event']} | {row['teams_scored']} | {row['two_source_teams']} | "
            f"{row['baseline_mean_hits']:.3f} | {row['consensus_mean_hits']:.3f} | "
            f"{row['mean_delta_to_champion']:+.3f} |"
        )
    if not result["events"]:
        lines.append("| — | 0 | 0 | — | — | — |")
    lines.extend(
        [
            "",
            "## Promotion gate",
            "",
            *[
                f"- [{'x' if passed else ' '}] {name.replace('_', ' ')}"
                for name, passed in gate["checks"].items()
            ],
            "",
            gate["authority"],
            "",
        ]
    )
    return "\n".join(lines)


def build_participation_scoreboard(
    *,
    snapshot_root: Path = SNAPSHOT_DIR,
    results_path: Path = RESULTS,
    report_path: Path = REPORT,
    outcome_loader: Callable[[int], tuple[Path, dict[str, Any], dict[str, Any]]] = (
        latest_event_outcome
    ),
) -> dict[str, Any]:
    ensure_engine_layout()
    events = []
    skipped = []
    for event, snapshot in sorted(_latest_frozen_snapshots(snapshot_root).items()):
        try:
            manifest, observations, consensus = _load_snapshot(snapshot)
            _, outcome_manifest, live = outcome_loader(event)
            score = score_participation_snapshot(
                consensus,
                observations,
                _actual_starts(live),
                _actual_points(live),
            )
            if not score["teams_scored"]:
                raise ParticipationScoreboardError(
                    "no single-fixture covered teams could be scored"
                )
            events.append(
                {
                    "event": event,
                    "snapshot_path": str(snapshot),
                    "snapshot_manifest_sha256": sha256_file(snapshot / "manifest.json"),
                    "observed_at": manifest["observed_at"],
                    "outcome_observed_at": outcome_manifest.get("observed_at"),
                    **score,
                }
            )
        except (OSError, SnapshotValidationError, ParticipationScoreboardError) as exc:
            skipped.append({"event": event, "reason": str(exc)})
    result = {
        "version": VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "events": events,
        "skipped": skipped,
        "promotion_gate": _promotion_gate(events),
    }
    _atomic_json(results_path, result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result
