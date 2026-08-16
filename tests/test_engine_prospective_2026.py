from __future__ import annotations

import json
from pathlib import Path

from fplagent_engine.prospective_2026 import build_2026_prospective_scoreboard


def _write_event(root: Path, event: int, *, frozen: bool = True) -> None:
    event_dir = root / f"event-{event}"
    event_dir.mkdir(parents=True)
    players = [
        {
            "element": element,
            "actual_points": 2,
            "actual_bps": 10,
            "actual_defensive_contribution": 1,
        }
        for element in range(1, 16)
    ]
    evidence = {
        "decision_sha256": "decision" if frozen else "",
        "outcome_sha256": "outcome",
        "decision_created_at": "2026-08-01T10:00:00+00:00",
        "official_deadline_time": "2026-08-01T18:00:00+00:00",
    }
    payload = {
        "event": event,
        "selected_action_id": f"action-{event}",
        "selected_comparison": {
            "realized_delta_to_reference": 1.0,
            "realized_rank": 1,
        },
        "decision_attribution": {
            "forecast_diagnostics": {
                "expected_points_mae": 1.0,
                "appearance_brier": 0.1,
            }
        },
        "selected_squad_player_outcomes": players,
        "frozen_evidence": evidence,
    }
    (event_dir / "score.json").write_text(json.dumps(payload), encoding="utf-8")


def test_six_events_are_diagnostic_but_not_sota(tmp_path: Path) -> None:
    root = tmp_path / "scores"
    for event in range(1, 7):
        _write_event(root, event)
    result = build_2026_prospective_scoreboard(
        source_root=root,
        results_path=tmp_path / "results.json",
        report_path=tmp_path / "report.md",
    )
    assert result["diagnostic_gate"]["passed"] is True
    assert result["sota_claim_gate"]["passed"] is False


def test_nineteen_untouched_events_open_first_claim_gate(tmp_path: Path) -> None:
    root = tmp_path / "scores"
    for event in range(1, 20):
        _write_event(root, event)
    result = build_2026_prospective_scoreboard(
        source_root=root,
        results_path=tmp_path / "results.json",
        report_path=tmp_path / "report.md",
    )
    assert result["completed_events"] == 19
    assert result["sota_claim_gate"]["passed"] is True


def test_missing_decision_lineage_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "scores"
    for event in range(1, 7):
        _write_event(root, event, frozen=event != 6)
    result = build_2026_prospective_scoreboard(
        source_root=root,
        results_path=tmp_path / "results.json",
        report_path=tmp_path / "report.md",
    )
    assert result["diagnostic_gate"]["passed"] is False
    assert result["diagnostic_gate"]["checks"]["frozen_before_outcome"] is False
