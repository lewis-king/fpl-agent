import json

import pytest
from test_engine_prospective_scoring import _bootstrap, _decision, _live

from fplagent_data.http import sha256_file
from fplagent_engine import gameweek_review as review_module
from fplagent_engine.gameweek_review import read_gameweek_review, reconcile_event
from fplagent_engine.prospective_scoring import (
    latest_archived_weekly_decision,
    score_forecast_universe,
)


def _inputs():
    live = _live()
    picks = [
        {
            "element": p,
            "position": p,
            "multiplier": 2 if p == 1 else int(p <= 11),
            "is_captain": p == 1,
            "is_vice_captain": p == 2,
        }
        for p in range(1, 16)
    ]
    gross = sum(
        r["stats"]["total_points"] * p["multiplier"] for r, p in zip(live["elements"], picks)
    )
    history = {
        "event": 2,
        "points": gross,
        "event_transfers_cost": 4,
        "total_points": 100,
        "overall_rank": 500000,
        "points_on_bench": 16,
    }
    bootstrap = _bootstrap()
    bootstrap["events"][0]["average_entry_score"] = 50
    for p in bootstrap["elements"]:
        p["web_name"] = f"Player {p['id']}"
    return {
        "history": history,
        "picks": {"picks": picks, "entry_history": dict(history)},
        "live": live,
        "bootstrap": bootstrap,
        "score": None,
    }


def test_actual_team_is_not_invented_from_saved_advice_and_hits_count_once():
    result = reconcile_event(**_inputs())
    assert result["net_points"] == 19
    assert result["recommendation_net_points"] is None
    assert result["players"][0]["contribution"] == 4
    assert all(r["expected_points"] is None for r in result["players"])


def test_missing_and_incoherent_outcomes_fail_closed():
    inputs = _inputs()
    inputs["live"]["elements"].pop()
    with pytest.raises(ValueError, match="missing"):
        reconcile_event(**inputs)
    inputs = _inputs()
    inputs["history"]["points"] += 1
    with pytest.raises(ValueError, match="reconcile"):
        reconcile_event(**inputs)


def test_live_event_is_not_reported_as_final():
    inputs = _inputs()
    inputs["bootstrap"]["events"][0]["data_checked"] = False
    with pytest.raises(ValueError, match="final"):
        reconcile_event(**inputs)


def test_post_deadline_replay_cannot_displace_last_frozen_decision(tmp_path):
    event = tmp_path / "event-2"
    event.mkdir()
    good = event / "good.json"
    good.write_text(json.dumps(_decision()))
    (event / "late.json").write_text(json.dumps(_decision(created_at="2026-08-29T16:00:00+00:00")))
    assert (
        latest_archived_weekly_decision(
            2, archive_root=tmp_path, deadline_time="2026-08-28T17:30:00+00:00"
        )
        == good
    )


def test_short_appearance_is_not_hidden_by_good_appearance_brier():
    meta = {
        1: {
            "position": "MID",
            "expected_points": 5,
            "p_play": 0.95,
            "p_1_59": 0.05,
            "p_60_89": 0.2,
            "p_90_or_more": 0.7,
        }
    }
    result = score_forecast_universe(
        meta, {1: {"total_points": 1, "minutes": 13}}, selected_players={1}
    )
    metrics = result["cohorts"]["selected_squad"]
    assert metrics["appearance_brier"] < 0.01
    assert metrics["unexpected_short_appearances"] == 1
    assert metrics["actual_short_appearances"] == 1
    assert metrics["expected_short_appearances"] == 0.05


def test_empty_cache_and_owner_isolation(tmp_path):
    assert read_gameweek_review(42, root=tmp_path)["status"] == "not_collected"
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "current.json").write_text(json.dumps({"entry_id": 43}))
    with pytest.raises(ValueError, match="different"):
        read_gameweek_review(42, root=tmp_path)


def test_cached_review_verifies_underlying_frozen_evidence(tmp_path):
    frozen = tmp_path / "decision.json"
    frozen.write_text('{"immutable":true}')
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "current.json").write_text(
        json.dumps(
            {
                "entry_id": 42,
                "evidence": [{"path": str(frozen), "sha256": sha256_file(frozen)}],
            }
        )
    )
    assert read_gameweek_review(42, root=tmp_path)["entry_id"] == 42
    frozen.write_text('{"immutable":false}')
    with pytest.raises(ValueError, match="evidence changed"):
        read_gameweek_review(42, root=tmp_path)


def test_automatic_scoring_isolates_missing_receipts_without_promoting(monkeypatch):
    from fplagent_engine import prospective_dashboard

    calls = []

    def score(event):
        calls.append(event)
        if event == 2:
            raise ValueError("Missing frozen decision")
        return {"receipt_path": f"event-{event}.json"}

    monkeypatch.setattr(review_module, "score_weekly_event", score)
    monkeypatch.setattr(
        prospective_dashboard,
        "build_prospective_scoreboard",
        lambda: {
            "status": "insufficient_evidence",
            "completed_events": [1, 3],
        },
    )
    result = review_module.sync_finalized_decision_scores([3, 1, 2, 1])
    assert calls == [1, 2, 3]
    assert [r["status"] for r in result["events"]] == ["scored", "needs_review", "scored"]
    assert result["decision_authority"] is False


def test_results_refresh_repairs_missing_feature_lineage_without_replacing_official_pointer(
    monkeypatch, tmp_path
):
    import httpx

    inputs = _inputs()
    captured = []
    official_calls = []

    def archive_official(payloads, **kwargs):
        official_calls.append(kwargs)
        path = kwargs["snapshot_root"] / "capture"
        path.mkdir(parents=True)
        (path / "bootstrap-static.json").write_text(json.dumps(payloads["bootstrap-static.json"]))
        return {"snapshot_id": "capture"}

    def missing_score(_):
        raise ValueError("No decision for this test event")

    monkeypatch.setattr(review_module, "archive_official_payloads", archive_official)
    monkeypatch.setattr(
        review_module,
        "latest_event_outcome",
        lambda _: (tmp_path, {"bootstrap_path": None}, inputs["live"]),
    )
    monkeypatch.setattr(
        review_module, "archive_event_outcome", lambda *args, **kwargs: captured.append(kwargs)
    )
    monkeypatch.setattr(review_module, "score_weekly_event", missing_score)
    payloads = {
        "/api/bootstrap-static/": inputs["bootstrap"],
        "/api/fixtures/": [],
        "/api/entry/42/history/": {"current": [inputs["history"]]},
        "/api/event/2/live/": inputs["live"],
        "/api/entry/42/event/2/picks/": inputs["picks"],
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payloads[request.url.path])
        )
    ) as client:
        result = review_module.refresh_gameweek_review(42, root=tmp_path, client=client)
    assert result["status"] == "ready"
    assert result["forecast_health"]["player_outcomes"] == 0
    assert len(captured) == 1
    assert captured[0]["bootstrap_path"].is_file()
    assert official_calls[0]["pointer_path"] == tmp_path / "42" / "official-current.json"
