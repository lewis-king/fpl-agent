from __future__ import annotations

from fplagent_engine.prospective_dashboard import (
    aggregate_prospective_receipts,
    build_prospective_scoreboard,
)


def _receipt(event: int, created: str, *, regret: float, challenger: float) -> dict:
    return {
        "event": event,
        "selected_action_id": f"selected-{event}",
        "actions": [{}, {}],
        "selected_comparison": {
            "realized_rank": 1,
            "realized_delta_to_reference": 2.0,
            "realized_opportunity_cost": regret,
        },
        "decision_attribution": {
            "action_selection_regret": regret,
            "configuration": {
                "configuration_regret": 3.0,
                "captaincy_regret_within_frozen_xi": 1.0,
            },
            "forecast_diagnostics": {
                "expected_points_mae": 2.5,
                "appearance_brier": 0.1,
            },
        },
        "challenger_policy_scores": {
            "form_reversion": {
                "status": "scored_shadow",
                "realized_delta_to_champion": challenger,
            }
        },
        "frozen_evidence": {"decision_created_at": created},
        "_receipt_path": f"event-{event}-{created}.json",
        "_sha256": "abc",
    }


def test_scoreboard_keeps_latest_predeadline_receipt_per_event() -> None:
    result = aggregate_prospective_receipts(
        [
            _receipt(2, "2026-08-20T10:00:00+00:00", regret=9.0, challenger=-5.0),
            _receipt(2, "2026-08-20T11:00:00+00:00", regret=1.0, challenger=2.0),
            _receipt(3, "2026-08-27T11:00:00+00:00", regret=2.0, challenger=1.0),
        ]
    )

    assert result["completed_events"] == 2
    assert result["season_summary"]["total_action_selection_regret"] == 3.0
    assert result["challenger_summaries"]["form_reversion"][
        "total_delta_to_champion"
    ] == 3.0
    assert result["diagnostic_learning_gate"]["passed"] is False


def test_empty_scoreboard_reuses_identical_input_fingerprint(tmp_path) -> None:
    output = tmp_path / "scoreboard.json"
    report = tmp_path / "scoreboard.md"
    first = build_prospective_scoreboard(
        scoring_roots=(tmp_path / "receipts",),
        output_path=output,
        report_path=report,
    )
    first_bytes = output.read_bytes()
    second = build_prospective_scoreboard(
        scoring_roots=(tmp_path / "receipts",),
        output_path=output,
        report_path=report,
    )

    assert first["reused"] is False
    assert second["reused"] is True
    assert output.read_bytes() == first_bytes
