"""Ordinary weekly runs refresh feedback without asking the manager to analyse it."""

from unittest.mock import Mock

import pytest

from fplagent_engine import deadline_pipeline as pipeline
from fplagent_engine import gameweek_review


@pytest.mark.parametrize("diagnostic_failure", [False, True])
def test_generation_scores_outcomes_and_builds_scouting_after_forecasting(
    monkeypatch, tmp_path, diagnostic_failure
):
    calls = []

    def stub(name, result):
        def run(*args, **kwargs):
            calls.append(name)
            return result
        return run

    official = {"snapshot_id": "same-generation", "publishable": True}
    monkeypatch.setattr(pipeline.fpl_current, "fetch", stub("fetch", {}))
    monkeypatch.setattr(pipeline, "latest_official_status", lambda **_: official)
    monkeypatch.setattr(pipeline.fpl_current, "preprocess", stub("preprocess", {}))
    monkeypatch.setattr(pipeline, "sync_finalized_event_outcomes",
                        stub("outcomes", {"finalized_events": [1, 2]}))
    scores = Mock(return_value={"events": [1, 2], "decision_authority": False})
    monkeypatch.setattr(gameweek_review, "sync_finalized_decision_scores", scores)
    monkeypatch.setattr(pipeline, "build_current_market_goal_rates", stub("markets", {}))
    monkeypatch.setattr(pipeline, "build_schedule_receipt", stub("schedule", {
        k: {} for k in ("current_path", "archive_path", "schedule_fingerprint",
                       "receipt_fingerprint", "snapshot_at", "summary", "comparison")
    }))
    for name in ("build_catalog", "build_features", "audit_features"):
        monkeypatch.setattr(pipeline, name, stub(name, {}))
    monkeypatch.setattr(pipeline, "forecast", stub("forecast", {"built": True}))
    monkeypatch.setattr(pipeline, "forecast_components", stub("components", {"built": True}))
    monkeypatch.setattr(pipeline, "current_actionable_event", lambda: 3)
    monkeypatch.setattr(pipeline, "collect_participation_consensus", stub("roles", {}))
    monkeypatch.setattr(pipeline, "SCOUTING_ROOT", tmp_path)
    (tmp_path / "current.json").write_text("previous board")

    def scouting(generation, *, forecast_path):
        calls.append("scouting")
        assert generation is official
        assert forecast_path == pipeline.CURRENT_FORECAST
        if diagnostic_failure:
            raise ValueError("missing optional evidence")
        (tmp_path / "current.json").write_text("new board")
        return {
            "status": "ready", "decision_event": 3, "players": [1, 2],
            "official_snapshot_id": generation["snapshot_id"],
            "observed_at": "2026-10-21T09:00:00Z", "built_at": "2026-10-21T09:01:00Z",
        }

    monkeypatch.setattr(pipeline, "refresh_scouting_from_generation", scouting)
    result = pipeline.refresh_current_generation(reuse_latest_official=True, horizon=5)
    scores.assert_called_once_with([1, 2])
    assert calls[-5:] == ["forecast", "roles", "forecast", "components", "scouting"]
    assert result["direct_forecast"]["built"] and result["component_forecast"]["built"]
    assert result["scouting"]["decision_authority"] is False
    if diagnostic_failure:
        assert result["scouting"]["status"] == "unavailable"
        assert result["scouting"]["previous_board_retained"]
        assert (tmp_path / "current.json").read_text() == "previous board"
    else:
        assert result["scouting"]["status"] == "ready"
        assert result["scouting"]["players"] == 2
        assert result["scouting"]["official_snapshot_id"] == "same-generation"
