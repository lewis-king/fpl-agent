from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .component_models import CURRENT_COMPONENT_FORECAST
from .decision_synthesis import DECISION_JSON as GW1_DECISION
from .models import CURRENT_FORECAST
from .paths import DATA, REPORTS
from .rules import SquadRules, load_rules, validate_lineup, validate_squad
from .schedule_scenarios import CURRENT_SCHEDULE_RECEIPT
from .weekly_decision import run_weekly_decision

REHEARSAL_ROOT = DATA / "model" / "weekly-rehearsal"
REHEARSAL_REPORT = REPORTS / "weekly-decision-rehearsal.md"
REHEARSAL_ENTRY_ID = 999_000_001


class WeeklyRehearsalError(ValueError):
    pass


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _rehearsal_events(rows: list[dict[str, Any]], event: int, horizon: int) -> tuple[int, ...]:
    if event < 2:
        raise WeeklyRehearsalError("weekly rehearsal starts after GW1")
    if horizon < 1:
        raise WeeklyRehearsalError("weekly rehearsal horizon must be positive")
    available = sorted({int(row["event_number"]) for row in rows})
    events = tuple(value for value in available if value >= event)[:horizon]
    if not events or events[0] != event:
        raise WeeklyRehearsalError(f"forecast does not cover rehearsal event {event}")
    if events != tuple(range(event, event + len(events))):
        raise WeeklyRehearsalError("rehearsal forecast horizon is not contiguous")
    return events


def build_synthetic_manager_snapshot(
    decision: Mapping[str, Any],
    forecast_rows: list[dict[str, Any]],
    *,
    event: int,
    observed_at: str,
    rules: SquadRules,
    entry_id: int = REHEARSAL_ENTRY_ID,
) -> dict[str, Any]:
    """Convert the published GW1 squad into an explicit zero-authority GW2 state."""
    selected = decision.get("decision")
    selected = selected.get("candidate") if isinstance(selected, Mapping) else None
    if not isinstance(selected, Mapping):
        raise WeeklyRehearsalError("published GW1 decision has no selected candidate")
    lineups = selected.get("lineups")
    gw1 = lineups.get("1") if isinstance(lineups, Mapping) else None
    if not isinstance(gw1, Mapping):
        raise WeeklyRehearsalError("published GW1 candidate has no GW1 lineup")
    starters = [int(value) for value in gw1.get("starters") or []]
    bench = [int(value) for value in gw1.get("bench_order") or []]
    selected_ids = [int(value) for value in selected.get("selected") or []]
    if set(starters) | set(bench) != set(selected_ids):
        raise WeeklyRehearsalError("published GW1 lineup does not partition its selected squad")

    by_id = {
        int(row["element"]): row
        for row in forecast_rows
        if int(row["event_number"]) == event
    }
    if not set(selected_ids).issubset(by_id):
        missing = sorted(set(selected_ids).difference(by_id))
        raise WeeklyRehearsalError(f"rehearsal forecast is missing selected players: {missing}")
    squad = [by_id[element] for element in selected_ids]
    validate_squad(squad, rules, enforce_budget=False)
    validate_lineup(
        squad,
        starters,
        bench,
        int(gw1["captain"]),
        int(gw1["vice_captain"]),
        rules,
    )
    prices = {element: round(float(by_id[element]["market_price"])) for element in selected_ids}
    spend = sum(prices.values())
    if spend > rules.budget:
        raise WeeklyRehearsalError(
            f"synthetic post-GW1 squad costs {spend}; budget is {rules.budget}"
        )
    order = [*starters, *bench]
    snapshot = {
        "status": "connected",
        "observed_at": observed_at,
        "entry_id": entry_id,
        "bank": rules.budget - spend,
        "squad_value": rules.budget,
        "free_transfers": 1,
        "transfer_cost": 0,
        "chips": [
            {"name": name, "start_event": 1, "status_for_entry": "available"}
            for name in ("wildcard", "freehit", "bboost", "3xc")
        ],
        "picks": [
            {
                "element": element,
                "position": position,
                "is_captain": element == int(gw1["captain"]),
                "is_vice_captain": element == int(gw1["vice_captain"]),
                "purchase_price": prices[element],
                "selling_price": prices[element],
                "name": str(by_id[element].get("player_name") or f"#{element}"),
                "team": str(by_id[element].get("team_name") or by_id[element]["team_id"]),
            }
            for position, element in enumerate(order, start=1)
        ],
        "rehearsal": {
            "synthetic": True,
            "decision_authority": False,
            "assumptions": [
                "GW1 published squad is still owned at the GW2 deadline",
                "one free transfer is available",
                "no GW1 price changes or transfer hits have occurred",
                "all first-half chips remain available",
            ],
        },
    }
    return snapshot


def _render_report(receipt: Mapping[str, Any]) -> str:
    summary = receipt.get("selected_action") or {}
    transfers = summary.get("transfers") or []
    transfer_text = (
        ", ".join(
            f"{row.get('outgoing_name', row.get('outgoing_player_id'))} → "
            f"{row.get('incoming_name', row.get('incoming_player_id'))}"
            for row in transfers
        )
        if transfers
        else "Roll / no transfer"
    )
    return "\n".join(
        [
            "# Weekly decision rehearsal",
            "",
            "**Authority:** zero — synthetic QA only",
            f"**Event:** GW{receipt['event']}",
            f"**Status:** {receipt['status']}",
            "",
            (
                "This runs the real weekly optimiser against the published GW1 squad while "
                "emulating the manager fields that FPL will expose after GW1. It cannot publish "
                "or replace a production decision."
            ),
            "",
            "## Rehearsed output",
            "",
            f"- Selected action: `{receipt.get('selected_action_id')}`",
            f"- Transfers: {transfer_text}",
            f"- Captain: {summary.get('captain_name', summary.get('captain_player_id'))}",
            f"- Vice-captain: {summary.get('vice_captain_name', summary.get('vice_captain_player_id'))}",
            f"- Starting XI count: {len(summary.get('starter_player_ids') or [])}",
            f"- Bench count: {len(summary.get('bench_player_ids') or [])}",
            (
                f"- Simulation counts: {receipt['simulation_config']['residual_simulations']:,} "
                f"residual / {receipt['simulation_config']['component_simulations']:,} component"
            ),
            "",
            "## Synthetic assumptions",
            "",
            *[f"- {value}" for value in receipt["assumptions"]],
            "",
        ]
    )


def run_weekly_rehearsal(
    *,
    event: int = 2,
    horizon: int = 5,
    observed_at: str | None = None,
    residual_simulations: int = 10_000,
    component_simulations: int = 25_000,
    alternatives_per_transfer_count: int = 4,
    max_total_transfers: int = 5,
    max_paid_transfers: int = 2,
    forecast_path: Path = CURRENT_FORECAST,
    component_forecast_path: Path = CURRENT_COMPONENT_FORECAST,
    gw1_decision_path: Path = GW1_DECISION,
    schedule_receipt_path: Path = CURRENT_SCHEDULE_RECEIPT,
    output_root: Path = REHEARSAL_ROOT,
    report_path: Path = REHEARSAL_REPORT,
    rules_loader: Callable[[], SquadRules] = load_rules,
    decision_runner: Callable[..., Mapping[str, Any]] = run_weekly_decision,
) -> dict[str, Any]:
    created = observed_at or datetime.now(UTC).isoformat()
    rows = pq.read_table(forecast_path).to_pylist()
    events = _rehearsal_events(rows, event, horizon)
    try:
        gw1_decision = json.loads(gw1_decision_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeeklyRehearsalError("published GW1 decision is unreadable") from exc
    snapshot = build_synthetic_manager_snapshot(
        gw1_decision,
        rows,
        event=event,
        observed_at=created,
        rules=rules_loader(),
    )
    identity = {
        "version": 1,
        "event": event,
        "events": events,
        "gw1_decision_sha256": sha256_file(gw1_decision_path),
        "forecast_sha256": sha256_file(forecast_path),
        "component_forecast_sha256": sha256_file(component_forecast_path),
        "snapshot": snapshot,
        "residual_simulations": residual_simulations,
        "component_simulations": component_simulations,
        "alternatives_per_transfer_count": alternatives_per_transfer_count,
        "max_total_transfers": max_total_transfers,
        "max_paid_transfers": max_paid_transfers,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    generation = output_root / f"event-{event}" / fingerprint[:16]
    snapshot_path = generation / "synthetic-manager-snapshot.json"
    decision_path = generation / "decision.json"
    _atomic_json(snapshot_path, snapshot)
    result = dict(
        decision_runner(
            rules_loader(),
            event=event,
            events=events,
            forecast_path=forecast_path,
            manager_snapshot_path=snapshot_path,
            output_path=decision_path,
            alternatives_per_transfer_count=alternatives_per_transfer_count,
            max_total_transfers=max_total_transfers,
            max_paid_transfers=max_paid_transfers,
            residual_simulations=residual_simulations,
            component_simulations=component_simulations,
            component_forecast_path=component_forecast_path,
            schedule_receipt_path=schedule_receipt_path,
            created_at=created,
        )
    )
    summaries = {
        str(row["action_id"]): row for row in result.get("action_summaries") or []
    }
    selected_id = str(result.get("selected_action_id") or "")
    selected_action = summaries.get(selected_id, {})
    receipt = {
        "version": 1,
        "status": "complete",
        "created_at": created,
        "event": event,
        "events": list(events),
        "decision_authority": False,
        "synthetic": True,
        "input_fingerprint": fingerprint,
        "selected_action_id": selected_id,
        "selected_action": selected_action,
        "simulation_config": {
            "residual_simulations": residual_simulations,
            "component_simulations": component_simulations,
            "alternatives_per_transfer_count": alternatives_per_transfer_count,
            "max_total_transfers": max_total_transfers,
            "max_paid_transfers": max_paid_transfers,
        },
        "assumptions": snapshot["rehearsal"]["assumptions"],
        "artifacts": {
            "synthetic_manager_snapshot": str(snapshot_path),
            "synthetic_manager_snapshot_sha256": sha256_file(snapshot_path),
            "decision": str(decision_path),
            "decision_sha256": sha256_file(decision_path),
            "gw1_decision": str(gw1_decision_path),
            "gw1_decision_sha256": sha256_file(gw1_decision_path),
            "forecast": str(forecast_path),
            "forecast_sha256": sha256_file(forecast_path),
        },
    }
    receipt_path = generation / "receipt.json"
    _atomic_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = sha256_file(receipt_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(receipt), encoding="utf-8")
    receipt["report_path"] = str(report_path)
    return receipt
