from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file

from .chip_schedule_history import HISTORICAL_FIXTURES
from .paths import MODEL_DATA

OUTPUT_ROOT = MODEL_DATA / "schedule_rearrangement_v1"
EPISODES = OUTPUT_ROOT / "episodes.parquet"
MODEL = OUTPUT_ROOT / "model.json"

EPISODE_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("fixture_id", pa.int64()),
        ("team_h", pa.int64()),
        ("team_a", pa.int64()),
        ("episode_start_event", pa.int64()),
        ("episode_last_unassigned_event", pa.int64()),
        ("resolved_at_decision_event", pa.int64()),
        ("assigned_event", pa.int64()),
        ("resolution_delay_events", pa.int64()),
        ("assignment_lead_events", pa.int64()),
        ("target_offset_from_start", pa.int64()),
        ("resolved", pa.bool_()),
        ("resolution_batch_size", pa.int64()),
        ("episode_weight", pa.float64()),
    ]
)


def _aware(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("fixture snapshot times must include a timezone")
    return parsed.astimezone(UTC)


def _weighted_support(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[int, int], float] = defaultdict(float)
    for row in rows:
        if not row["resolved"]:
            continue
        key = (int(row["resolution_delay_events"]), int(row["assignment_lead_events"]))
        counts[key] += float(row["episode_weight"])
    total = sum(counts.values())
    if total <= 0:
        return []
    return [
        {
            "resolution_delay_events": delay,
            "assignment_lead_events": lead,
            "probability": weight / total,
        }
        for (delay, lead), weight in sorted(counts.items())
    ]


def build_rearrangement_model(
    *,
    fixture_path: Path = HISTORICAL_FIXTURES,
    episode_path: Path = EPISODES,
    model_path: Path = MODEL,
) -> dict[str, Any]:
    """Build one weighted episode per unassigned-to-assigned fixture transition."""
    raw_rows = pq.read_table(fixture_path).to_pylist()
    if not raw_rows:
        raise ValueError("historical fixture snapshots are empty")
    by_fixture: dict[tuple[str, int], dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in raw_rows:
        if row.get("decision_event") is None:
            continue
        if _aware(row["observed_at"]) >= _aware(row["deadline_at"]):
            raise ValueError("historical rearrangement input contains post-deadline evidence")
        key = (str(row["season"]), int(row["id"]))
        event = int(row["decision_event"])
        if event in by_fixture[key]:
            raise ValueError(f"fixture {key} has duplicate decision-event observations")
        by_fixture[key][event] = row

    episodes: list[dict[str, Any]] = []
    for (season, fixture_id), observations in sorted(by_fixture.items()):
        active: tuple[int, int, dict[str, Any]] | None = None
        for decision_event in sorted(observations):
            row = observations[decision_event]
            if row.get("event") is None:
                if active is None:
                    active = (decision_event, decision_event, row)
                else:
                    active = (active[0], decision_event, active[2])
                continue
            if active is None:
                continue
            start, last_unassigned, first_row = active
            assigned_event = int(row["event"])
            episodes.append(
                {
                    "season": season,
                    "fixture_id": fixture_id,
                    "team_h": int(first_row["team_h"]),
                    "team_a": int(first_row["team_a"]),
                    "episode_start_event": start,
                    "episode_last_unassigned_event": last_unassigned,
                    "resolved_at_decision_event": decision_event,
                    "assigned_event": assigned_event,
                    "resolution_delay_events": decision_event - start,
                    "assignment_lead_events": assigned_event - decision_event,
                    "target_offset_from_start": assigned_event - start,
                    "resolved": True,
                }
            )
            active = None
        if active is not None:
            start, last_unassigned, first_row = active
            episodes.append(
                {
                    "season": season,
                    "fixture_id": fixture_id,
                    "team_h": int(first_row["team_h"]),
                    "team_a": int(first_row["team_a"]),
                    "episode_start_event": start,
                    "episode_last_unassigned_event": last_unassigned,
                    "resolved_at_decision_event": None,
                    "assigned_event": None,
                    "resolution_delay_events": None,
                    "assignment_lead_events": None,
                    "target_offset_from_start": None,
                    "resolved": False,
                }
            )
    if not episodes:
        raise ValueError("historical snapshots contain no unassigned fixture episodes")
    batch_sizes = Counter(
        (
            row["season"],
            row["episode_start_event"],
            row["resolved_at_decision_event"],
            row["assigned_event"],
        )
        for row in episodes
        if row["resolved"]
    )
    for row in episodes:
        batch_key = (
            row["season"],
            row["episode_start_event"],
            row["resolved_at_decision_event"],
            row["assigned_event"],
        )
        batch_size = batch_sizes.get(batch_key, 1)
        row["resolution_batch_size"] = batch_size
        row["episode_weight"] = 1.0 / batch_size if row["resolved"] else 0.0
    episodes.sort(key=lambda row: (row["season"], row["episode_start_event"], row["fixture_id"]))
    write_table(pa.Table.from_pylist(episodes, schema=EPISODE_SCHEMA), episode_path)

    resolved = [row for row in episodes if row["resolved"]]
    batches = {
        (
            row["season"],
            row["episode_start_event"],
            row["resolved_at_decision_event"],
            row["assigned_event"],
        )
        for row in resolved
    }
    support = _weighted_support(episodes)
    represented_seasons = sorted({row["season"] for row in resolved})
    gate = {
        "passed": len(batches) >= 20 and len(represented_seasons) >= 3,
        "minimum_independent_batches": 20,
        "minimum_seasons": 3,
        "observed_independent_batches": len(batches),
        "observed_seasons": len(represented_seasons),
    }
    model = {
        "model_version": 1,
        "status": "ready_shadow",
        "input_path": str(fixture_path),
        "input_sha256": sha256_file(fixture_path),
        "episode_path": str(episode_path),
        "episode_sha256": sha256_file(episode_path),
        "episodes": len(episodes),
        "resolved_episodes": len(resolved),
        "unresolved_episodes": len(episodes) - len(resolved),
        "independent_resolution_batches": len(batches),
        "represented_seasons": represented_seasons,
        "support": support,
        "promotion_gate": gate,
        "authority": False,
        "information_policy": (
            "Episodes use only successive fixture snapshots captured before each deadline. "
            "Fixtures resolved in the same announcement batch share one unit of weight."
        ),
        "limitation": (
            "The support is a sparse empirical shadow and assumes a currently unassigned fixture "
            "has just entered an episode; it cannot authorize a speculative event assignment."
        ),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_suffix(model_path.suffix + ".tmp")
    temporary.write_text(json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(model_path)
    return model


def evaluate_rearrangement_shadow(
    schedule_receipt: Mapping[str, Any],
    *,
    current_event: int,
    events: tuple[int, ...],
    model: Mapping[str, Any] | None = None,
    model_path: Path = MODEL,
    simulations: int = 2_000,
    seed: int = 20260821,
) -> dict[str, Any]:
    """Sample unassigned fixtures into future events without changing the official schedule."""
    if simulations < 500:
        raise ValueError("rearrangement shadow requires at least 500 simulations")
    if not events or events[0] != current_event:
        raise ValueError("rearrangement events must start at the current decision event")
    unassigned = [row for row in schedule_receipt.get("fixtures", []) if row.get("event") is None]
    base = {
        "decision_authority": False,
        "official_schedule_unchanged": True,
        "current_event": current_event,
        "events": list(events),
        "unassigned_fixtures": len(unassigned),
    }
    if not unassigned:
        return {
            **base,
            "status": "not_applicable",
            "reason": "The official schedule has no unassigned fixtures.",
        }
    model_lineage: dict[str, Any] = {}
    if model is not None:
        loaded = dict(model)
    else:
        try:
            loaded = json.loads(model_path.read_text(encoding="utf-8"))
            episode_path = Path(str(loaded["episode_path"]))
            if sha256_file(episode_path) != loaded.get("episode_sha256"):
                raise ValueError("rearrangement episode artifact no longer matches its model")
            model_lineage = {
                "model_path": str(model_path),
                "model_sha256": sha256_file(model_path),
                "episode_path": str(episode_path),
                "episode_sha256": loaded["episode_sha256"],
            }
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            return {**base, "status": "not_ready", "reason": str(error)}
    support = list(loaded.get("support", []))
    if not support:
        return {**base, "status": "not_ready", "reason": "No empirical resolution support."}
    probabilities = np.asarray([float(row["probability"]) for row in support], dtype=float)
    probabilities /= probabilities.sum()
    target_events = np.asarray(
        [
            current_event
            + int(row["resolution_delay_events"])
            + int(row["assignment_lead_events"])
            for row in support
        ],
        dtype=int,
    )
    rng = np.random.default_rng(seed)
    draws = rng.choice(len(support), size=(simulations, len(unassigned)), p=probabilities)
    assigned_draws = target_events[draws]

    teams = sorted(
        {
            int(row[field])
            for row in schedule_receipt.get("fixtures", [])
            for field in ("team_h", "team_a")
        }
    )
    base_counts = {(team, event): 0 for team in teams for event in events}
    for fixture in schedule_receipt.get("fixtures", []):
        if fixture.get("event") in events:
            event = int(fixture["event"])
            base_counts[(int(fixture["team_h"]), event)] += 1
            base_counts[(int(fixture["team_a"]), event)] += 1
    count_samples = {
        key: np.full(simulations, value, dtype=np.int8) for key, value in base_counts.items()
    }
    fixture_rows = []
    for offset, fixture in enumerate(unassigned):
        sampled = assigned_draws[:, offset]
        event_probabilities = {
            str(event): float(np.mean(sampled == event)) for event in events
        }
        fixture_rows.append(
            {
                "fixture_id": int(fixture["fixture_id"]),
                "team_h": int(fixture["team_h"]),
                "team_a": int(fixture["team_a"]),
                "event_probabilities": event_probabilities,
                "probability_outside_horizon": float(np.mean(~np.isin(sampled, events))),
            }
        )
        for event in events:
            indicator = (sampled == event).astype(np.int8)
            count_samples[(int(fixture["team_h"]), event)] += indicator
            count_samples[(int(fixture["team_a"]), event)] += indicator
    team_events = []
    for (team, event), values in sorted(
        count_samples.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        team_events.append(
            {
                "event": event,
                "team_id": team,
                "official_fixture_count": base_counts[(team, event)],
                "probability_blank": float(np.mean(values == 0)),
                "probability_single": float(np.mean(values == 1)),
                "probability_double": float(np.mean(values == 2)),
                "probability_triple_plus": float(np.mean(values >= 3)),
            }
        )
    fingerprint_payload = {
        "seed": seed,
        "simulations": simulations,
        "fixture_rows": fixture_rows,
        "team_events": team_events,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **base,
        "status": "ready_shadow",
        "simulations": simulations,
        "seed": seed,
        "model_promotion_gate": loaded.get("promotion_gate"),
        "model_authority": bool(loaded.get("authority", False)),
        "fixture_scenarios": fixture_rows,
        "team_event_probabilities": team_events,
        "scenario_fingerprint": fingerprint,
        **model_lineage,
        "operational_policy": (
            "Probabilities are sensitivity evidence only. Official unassigned fixtures remain "
            "unassigned and every affected chip gate remains blocked."
        ),
    }
