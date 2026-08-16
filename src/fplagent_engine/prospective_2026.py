from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .paths import MODEL_DATA, REPORTS

VERSION = "prospective_2026_27_scoreboard_v1"
SOURCE_ROOT = MODEL_DATA / "prospective_weekly_scoring_v2"
OUTPUT_DIR = MODEL_DATA / VERSION
RESULTS = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "prospective-2026-27-scoreboard.md"
DIAGNOSTIC_EVENTS = 6
SOTA_MINIMUM_EVENTS = 19


def _latest_results(root: Path) -> list[dict[str, Any]]:
    results = []
    if not root.is_dir():
        return results
    for event_dir in sorted(root.glob("event-*")):
        files = sorted(event_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not files:
            continue
        value = json.loads(files[-1].read_text(encoding="utf-8"))
        if isinstance(value, dict):
            results.append(value)
    return sorted(results, key=lambda row: int(row["event"]))


def _frozen_before_outcome(event: dict[str, Any]) -> bool:
    evidence = event.get("frozen_evidence") or {}
    try:
        created = datetime.fromisoformat(str(evidence["decision_created_at"]))
        deadline = datetime.fromisoformat(str(evidence["official_deadline_time"]))
    except (KeyError, TypeError, ValueError):
        return False
    return bool(evidence.get("decision_sha256") and evidence.get("outcome_sha256")) and (
        created <= deadline
    )


def build_2026_prospective_scoreboard(
    *,
    source_root: Path = SOURCE_ROOT,
    results_path: Path = RESULTS,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    events = _latest_results(source_root)
    rows = [row for event in events for row in event.get("selected_squad_player_outcomes") or []]
    defcon_complete = bool(rows) and all("actual_defensive_contribution" in row for row in rows)
    bps_complete = bool(rows) and all("actual_bps" in row for row in rows)
    selected_deltas = [
        float(event["selected_comparison"]["realized_delta_to_reference"]) for event in events
    ]
    forecast_mae = [
        float(event["decision_attribution"]["forecast_diagnostics"]["expected_points_mae"])
        for event in events
    ]
    event_rows = [
        {
            "event": int(event["event"]),
            "selected_action_id": str(event["selected_action_id"]),
            "realized_delta_to_reference": float(
                event["selected_comparison"]["realized_delta_to_reference"]
            ),
            "realized_rank": int(event["selected_comparison"]["realized_rank"]),
            "forecast_mae": float(
                event["decision_attribution"]["forecast_diagnostics"]["expected_points_mae"]
            ),
            "appearance_brier": float(
                event["decision_attribution"]["forecast_diagnostics"]["appearance_brier"]
            ),
            "players_scored": len(event.get("selected_squad_player_outcomes") or []),
        }
        for event in events
    ]
    diagnostic_checks = {
        "six_final_untouched_events": len(events) >= DIAGNOSTIC_EVENTS,
        "new_defensive_contribution_field_scored": defcon_complete,
        "bps_field_scored": bps_complete,
        "frozen_before_outcome": all(_frozen_before_outcome(event) for event in events)
        if events
        else False,
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "season": "2026-27",
        "completed_events": len(events),
        "events": event_rows,
        "aggregate": {
            "selected_net_delta_to_reference": float(sum(selected_deltas)),
            "mean_delta_to_reference": float(np.mean(selected_deltas)) if selected_deltas else None,
            "mean_player_mae": float(np.mean(forecast_mae)) if forecast_mae else None,
            "player_outcomes": len(rows),
        },
        "diagnostic_gate": {
            "passed": all(diagnostic_checks.values()),
            "checks": diagnostic_checks,
            "minimum_events": DIAGNOSTIC_EVENTS,
        },
        "sota_claim_gate": {
            "passed": all(diagnostic_checks.values()) and len(events) >= SOTA_MINIMUM_EVENTS,
            "minimum_events": SOTA_MINIMUM_EVENTS,
            "reason": (
                "Six events permit diagnosis only; at least half a season is required before "
                "the prospective evidence can support a SOTA claim."
            ),
        },
        "production_changed": False,
        "rules_contract": {
            "season": "2026-27",
            "official_bps_observed": bps_complete,
            "official_defensive_contribution_observed": defcon_complete,
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# Untouched 2026/27 prospective scoring",
                "",
                f"**Final events:** {len(events)}  ",
                f"**Diagnostic gate:** {'PASS' if result['diagnostic_gate']['passed'] else 'WAIT'}  ",
                f"**SOTA sample gate:** {'PASS' if result['sota_claim_gate']['passed'] else 'WAIT'}",
                "",
                "Only decisions frozen before their official deadline are scored. Six events trigger diagnosis; half a season is the minimum claim sample.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result
