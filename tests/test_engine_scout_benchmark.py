import json
from datetime import UTC, datetime

import pytest
from test_engine_weekly_configuration import _setup

from fplagent_engine import scout_benchmark as scout


def fixture():
    state, raw, rules, _, _, _ = _setup()
    rows = [{**r, "player_name": f"Player {r['element']}", "season": "2026-27", "player_code": r["element"] * 100,
             "team_code": r["team_id"] * 10, "snapshot_at": "2026-10-21T08:00:00+00:00",
             "forecast_created_at": "2026-10-21T08:10:00+00:00"} for r in raw]
    players = [{"e": r["element"], "c": r["player_code"], "p": r["position"],
                "tb": r["team_code"], "pr": r["market_price"] / 10, "mn": 2500,
                "xp": [None, float(r["expected_points"]), float(r["expected_points"])]}
               for r in rows if r["event_number"] == 2]
    meta = {"season": "2026-27", "currentGw": 2, "projGw": 2, "isMember": True, "isLoggedIn": True}
    kwargs = {"held_ids": [p.player_id for p in state.squad], "events": (2, 3),
              "observed_at": "2026-10-21T09:00:00+00:00", "deadline": "2026-10-23T17:30:00Z",
              "rules": rules}
    return meta, players, rows, kwargs


def page(meta, players, **extra):
    return ("window.FPL_PROJ_META = " + json.dumps(meta) + ";\nwindow.FPL_PROJ_PLAYERS = "
            + json.dumps({"isMember": True, "hasProjections": True, "players": players, **extra}) + ";")


def test_json_only_parser_requires_member_and_unique_identity():
    meta, players, _, _ = fixture()
    assert scout.parse_page(page(meta, players))[0] == meta
    with pytest.raises(ValueError, match="authorized"):
        scout.parse_page(page({**meta, "isMember": False}, players))
    with pytest.raises(ValueError, match="ambiguous"):
        scout.parse_page(page(meta, [*players, players[0]]))
    with pytest.raises(ValueError, match="JSON"):
        scout.parse_page('window.FPL_PROJ_META = alert("no eval");')


def test_comparable_capture_freezes_legal_same_squad_controls():
    meta, players, rows, kwargs = fixture()
    result = scout.build_comparison(meta, players, rows, **kwargs)
    assert result["status"] == "contemporaneous_capture"
    assert result["source_published_at"] is None
    assert not result["decision_authority"]
    assert result["lineup_controls"]["own"] == result["lineup_controls"]["scout"]
    assert len(result["lineup_controls"]["scout"]["starters"]) == 11
    assert result["rows"][0]["scout_aggregate_minutes_unverified_window"] == 2500


@pytest.mark.parametrize("change,issue", [
    ("old", "local_forecast_not_contemporaneous"), ("future", "local_forecast_not_contemporaneous"),
    ("price", "price_mismatch"), ("missing", "scout_missing"), ("late", "capture_not_before_deadline")])
def test_unmatched_comparison_cannot_claim_a_decision_winner(change, issue):
    meta, players, rows, kwargs = fixture()
    if change in {"old", "future"}:
        for row in rows:
            row["snapshot_at"] = f"2026-10-{17 if change == 'old' else 22}T08:00:00Z"
    elif change == "price":
        players[0]["pr"] += .1
    elif change == "missing":
        players[0]["xp"][1] = None
    else:
        kwargs["observed_at"] = "2026-10-24T00:00:00Z"
    result = scout.build_comparison(meta, players, rows, **kwargs)
    assert result["status"] == "unmatched"
    assert result["lineup_controls"] is None
    assert any(i.startswith(issue) for i in result["issues"])


@pytest.mark.parametrize("field,value", [("c", 99999), ("p", "FWD"), ("tb", 999)])
def test_no_fuzzy_player_identity_join(field, value):
    meta, players, rows, kwargs = fixture()
    players[0][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        scout.build_comparison(meta, players, rows, **kwargs)


def test_page_current_event_cannot_hide_stale_projection_event():
    meta, players, rows, kwargs = fixture()
    with pytest.raises(ValueError, match="events differ"):
        scout.build_comparison({**meta, "projGw": 1}, players, rows, **kwargs)


def test_cookie_permissions_and_redirect_are_closed_without_leaking_secret(tmp_path, monkeypatch):
    path = tmp_path / "cookie"
    path.write_text("test-secret")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        scout.fetch_page(path)
    path.chmod(0o600)
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs)
        return type("Response", (), {"status_code": 302})()
    monkeypatch.setattr(scout.httpx, "get", get)
    with pytest.raises(ValueError, match="302") as error:
        scout.fetch_page(path)
    assert "test-secret" not in str(error.value)
    assert calls[0]["follow_redirects"] is False


def test_capture_is_private_immutable_and_does_not_store_cookie_or_html(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    meta, players, rows, kwargs = fixture()
    forecast = tmp_path / "forecast.parquet"
    pq.write_table(pa.Table.from_pylist(rows), forecast)
    result = scout.capture(forecast_path=forecast, held_ids=kwargs["held_ids"], events=kwargs["events"],
                           deadline=kwargs["deadline"], rules=kwargs["rules"], root=tmp_path / "private",
                           fetcher=lambda _: page(meta, players) + "SECRET_HTML",
                           now=datetime(2026, 10, 21, 9, tzinfo=UTC))
    from pathlib import Path
    path = Path(result["path"])
    assert path.stat().st_mode & 0o777 == 0o600
    assert "SECRET_HTML" not in path.read_text()
    payload = json.loads(path.read_text())
    assert scout.save_private(payload, path.parent) == path


def test_absent_session_disables_optional_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(scout, "COOKIE", tmp_path / "missing")
    monkeypatch.setattr(scout, "score_available", lambda: {"scored": 1})
    result = scout.optional_capture(forecast_path=None, contract_path=None, events=(8,), rules=None)
    assert result["status"] == "not_configured"
    assert result["previous_captures_scored"] == {"scored": 1}


def test_prospective_scoring_requires_finality_and_uses_captain_fallback_and_autosubs():
    meta, players, rows, kwargs = fixture()
    payload = scout.build_comparison(meta, players, rows, **kwargs)
    captain = payload["lineup_controls"]["scout"]["captain"]
    history = [{"season": "2026-27", "event": 2, "element": r["element"],
                "player_code": r["player_code"], "points": 0 if r["element"] == captain else 2,
                "minutes": 0 if r["element"] == captain else 90}
               for r in rows if r["event_number"] == 2]
    assert scout.score_comparison(payload, history, final_events=set())["status"] == "awaiting_final_outcomes"
    result = scout.score_comparison(payload, history, final_events={2})
    # 11 scoring players after legal substitution, plus vice's two points.
    assert result["scores"]["scout"]["legal_lineup_points_including_autosubs_captain_fallback"] == 24
    assert result["scores"]["own"] == result["scores"]["scout"]
    assert scout.score_comparison({**payload, "status": "unmatched"}, history,
                                   final_events={2})["status"] == "ineligible_unmatched"


def test_real_contract_wrapper_and_optional_capture_failure(monkeypatch, tmp_path):
    cookie = tmp_path / "cookie"
    cookie.touch()
    monkeypatch.setattr(scout, "COOKIE", cookie)
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"manager_state": {"squad": [{"player_id": p} for p in range(1, 16)]}}))
    (tmp_path / "bootstrap-static.json").write_text(json.dumps({"events": [{"id": 8, "deadline_time": "2026-10-23T17:30:00Z"}]}))
    monkeypatch.setattr("fplagent_data.live_snapshots.latest_official_snapshot", lambda: (tmp_path, None))
    calls = []
    monkeypatch.setattr(scout, "capture", lambda **k: calls.append(k) or {"status": "contemporaneous_capture"})
    monkeypatch.setattr(scout, "score_available", dict)
    assert scout.optional_capture(forecast_path=None, contract_path=contract, events=(8, 9), rules=None)["status"] == "contemporaneous_capture"
    assert calls[0]["held_ids"] == list(range(1, 16))
    def fail(**kwargs):
        raise ValueError("SECRET_RAW_RESPONSE")
    monkeypatch.setattr(scout, "capture", fail)
    result = scout.optional_capture(forecast_path=None, contract_path=contract, events=(8,), rules=None)
    assert result["status"] == "unavailable"
    assert "SECRET" not in json.dumps(result)


def test_modified_capture_cannot_be_scored_as_frozen(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    meta, players, rows, kwargs = fixture()
    payload = scout.build_comparison(meta, players, rows, **kwargs)
    path = scout.save_private(payload, tmp_path / "private")
    path.write_text(path.read_text() + " ")
    history = tmp_path / "history.parquet"
    pq.write_table(pa.table({"element": []}), history)
    receipt = tmp_path / "history.json"
    receipt.write_text(json.dumps({"status": "ready", "events": [2],
                                   "output_sha256": scout.sha256_file(history)}))
    monkeypatch.setattr("fplagent_data.event_outcomes.CURRENT_PLAYER_HISTORY", history)
    monkeypatch.setattr("fplagent_data.event_outcomes.CURRENT_PLAYER_HISTORY_RECEIPT", receipt)
    with pytest.raises(ValueError, match="content changed"):
        scout.score_available(path.parent)
