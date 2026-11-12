from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .paths import MODEL_DATA, REPORTS

VERSION = "prospective_scoreboard_v1"
RESULT_ROOT = MODEL_DATA / VERSION
RESULTS = RESULT_ROOT / "results.json"
REPORT = REPORTS / "prospective-season-scoreboard.md"
SCORING_ROOTS = (
    MODEL_DATA / "prospective_weekly_scoring_v4",
    MODEL_DATA / "prospective_weekly_scoring_v3",
    MODEL_DATA / "prospective_weekly_scoring_v2",
    MODEL_DATA / "prospective_weekly_scoring_v1",
)


class ProspectiveDashboardError(ValueError):
    """Prospective receipts are inconsistent or have lost their frozen lineage."""


def _load_receipts(roots: Iterable[Path]) -> list[dict[str, Any]]:
    receipts = []
    for root in roots:
        for path in sorted(root.glob("event-*/*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProspectiveDashboardError(f"prospective receipt is unreadable: {path}") from exc
            if payload.get("version") not in {
                "prospective_weekly_scoring_v1",
                "prospective_weekly_scoring_v2",
                "prospective_weekly_scoring_v3",
                "prospective_weekly_scoring_v4",
            }:
                continue
            frozen = payload.get("frozen_evidence", {})
            for key in ("decision", "outcome"):
                source = Path(str(frozen.get(f"{key}_path", "")))
                expected = frozen.get(f"{key}_sha256")
                if not source.is_file() or not expected or sha256_file(source) != expected:
                    raise ProspectiveDashboardError(
                        f"prospective {key} lineage changed for {path}"
                    )
            receipts.append({**payload, "_receipt_path": str(path), "_sha256": sha256_file(path)})
    return receipts


def aggregate_prospective_receipts(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    latest_by_event: dict[int, dict[str, Any]] = {}
    for receipt in receipts:
        event = int(receipt["event"])
        frozen = receipt["frozen_evidence"]
        key = (str(frozen["decision_created_at"]), str(receipt.get("_receipt_path", "")))
        incumbent = latest_by_event.get(event)
        if incumbent is None:
            latest_by_event[event] = receipt
            continue
        incumbent_key = (
            str(incumbent["frozen_evidence"]["decision_created_at"]),
            str(incumbent.get("_receipt_path", "")),
        )
        if key > incumbent_key:
            latest_by_event[event] = receipt
    selected = [latest_by_event[event] for event in sorted(latest_by_event)]
    event_rows = []
    challenger_deltas: dict[str, list[float]] = {}
    for receipt in selected:
        comparison = receipt["selected_comparison"]
        attribution = receipt.get("decision_attribution", {})
        forecast = attribution.get("forecast_diagnostics", {})
        configuration = attribution.get("configuration", {})
        event_rows.append(
            {
                "event": int(receipt["event"]),
                "selected_action_id": str(receipt["selected_action_id"]),
                "realized_rank": int(comparison["realized_rank"]),
                "actions": len(receipt["actions"]),
                "realized_delta_to_reference": float(
                    comparison["realized_delta_to_reference"]
                ),
                "action_selection_regret": float(
                    attribution.get(
                        "action_selection_regret",
                        comparison["realized_opportunity_cost"],
                    )
                ),
                "configuration_regret": float(
                    configuration.get("configuration_regret", 0.0)
                ),
                "captaincy_regret": float(
                    configuration.get("captaincy_regret_within_frozen_xi", 0.0)
                ),
                "expected_points_mae": (
                    float(forecast["expected_points_mae"])
                    if "expected_points_mae" in forecast
                    else None
                ),
                "appearance_brier": (
                    float(forecast["appearance_brier"])
                    if "appearance_brier" in forecast
                    else None
                ),
                "receipt_path": receipt.get("_receipt_path"),
                "receipt_sha256": receipt.get("_sha256"),
            }
        )
        for name, score in receipt.get("challenger_policy_scores", {}).items():
            if score.get("status") == "scored_shadow":
                challenger_deltas.setdefault(str(name), []).append(
                    float(score["realized_delta_to_champion"])
                )
    completed = len(event_rows)
    regrets = [row["action_selection_regret"] for row in event_rows]
    reference_deltas = [row["realized_delta_to_reference"] for row in event_rows]
    maes = [row["expected_points_mae"] for row in event_rows if row["expected_points_mae"] is not None]
    briers = [row["appearance_brier"] for row in event_rows if row["appearance_brier"] is not None]
    challenger_rows = {}
    for name, values in challenger_deltas.items():
        array = np.asarray(values, dtype=np.float64)
        mean = float(array.mean())
        standard_error = float(array.std(ddof=1) / math.sqrt(len(array))) if len(array) > 1 else None
        challenger_rows[name] = {
            "events": len(values),
            "total_delta_to_champion": float(array.sum()),
            "mean_delta_to_champion": mean,
            "ci95_low": mean - 1.96 * standard_error if standard_error is not None else None,
            "ci95_high": mean + 1.96 * standard_error if standard_error is not None else None,
        }
    learning_checks = {
        "at_least_six_final_events": completed >= 6,
        "all_events_unique": completed == len({row["event"] for row in event_rows}),
        "all_receipts_have_attribution_v2": all(
            "decision_attribution" in receipt for receipt in selected
        ),
    }
    return {
        "status": "ready_diagnostic" if completed else "awaiting_final_events",
        "authority": False,
        "completed_events": completed,
        "events": event_rows,
        "season_summary": {
            "total_selected_delta_to_reference": float(sum(reference_deltas)),
            "total_action_selection_regret": float(sum(regrets)),
            "mean_action_selection_regret": (
                float(np.mean(regrets)) if regrets else None
            ),
            "mean_expected_points_mae": float(np.mean(maes)) if maes else None,
            "mean_appearance_brier": float(np.mean(briers)) if briers else None,
        },
        "challenger_summaries": challenger_rows,
        "diagnostic_learning_gate": {
            "passed": all(learning_checks.values()),
            "checks": learning_checks,
            "meaning": (
                "Enough finalized receipts for a scheduled diagnostic review; never an automatic "
                "forecast or policy promotion."
            ),
        },
    }


def _render(result: dict[str, Any]) -> str:
    summary = result["season_summary"]
    lines = [
        "# Prospective season decision scoreboard",
        "",
        f"Generated: {result['created_at']}",
        "",
        f"Status: **{result['status']}** · finalized events: **{result['completed_events']}**",
        "",
        (
            "This board scores only immutable pre-deadline decisions against final, data-checked "
            "official outcomes. It cannot promote a model automatically."
        ),
        "",
    ]
    if result["events"]:
        lines.extend(
            [
                f"- Total delta to frozen reference: {summary['total_selected_delta_to_reference']:+.1f}",
                f"- Total regret to best considered action: {summary['total_action_selection_regret']:.1f}",
                f"- Mean action regret: {summary['mean_action_selection_regret']:.3f}",
                "",
                "| GW | Selected | Rank | Δ reference | Action regret | XI upper bound | Captain |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in result["events"]:
            lines.append(
                f"| {row['event']} | {row['selected_action_id']} | {row['realized_rank']}/{row['actions']} | "
                f"{row['realized_delta_to_reference']:+.1f} | {row['action_selection_regret']:.1f} | "
                f"{row['configuration_regret']:.1f} | {row['captaincy_regret']:.1f} |"
            )
    else:
        lines.extend(
            [
                "No 2026/27 event is final yet. This is the expected preseason state.",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def build_prospective_scoreboard(
    *,
    scoring_roots: tuple[Path, ...] = SCORING_ROOTS,
    output_path: Path = RESULTS,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    receipts = _load_receipts(scoring_roots)
    input_identity = sorted(
        (
            {
                "path": str(row.get("_receipt_path", "")),
                "sha256": str(row.get("_sha256", "")),
            }
            for row in receipts
        ),
        key=lambda row: (row["path"], row["sha256"]),
    )
    fingerprint = hashlib.sha256(
        json.dumps(input_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if output_path.is_file():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if (
            existing.get("version") == VERSION
            and existing.get("input_fingerprint") == fingerprint
        ):
            return {
                **existing,
                "receipt_path": str(output_path),
                "receipt_sha256": sha256_file(output_path),
                "reused": True,
            }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "input_fingerprint": fingerprint,
        **aggregate_prospective_receipts(receipts),
        "receipt_roots": [str(path) for path in scoring_roots],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(_render(result), encoding="utf-8")
    temporary_report.replace(report_path)
    return {
        **result,
        "receipt_path": str(output_path),
        "receipt_sha256": sha256_file(output_path),
        "reused": False,
    }
