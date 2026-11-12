import json
from datetime import UTC, datetime

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_data.http import sha256_file
from fplagent_engine import scouting
from fplagent_engine.scouting import build_board, event_record, summarize_matches


def _record(event=1, minutes=90, xg=0.4, xa=0.2):
    return {
        "event": event,
        "fixtures": 1,
        "minutes": minutes,
        "points": 2,
        "starts": int(minutes >= 60),
        "goals": 0,
        "assists": 0,
        "xg": xg,
        "xa": xa,
        "played_fixtures": int(minutes > 0),
        "defcon_hits": 0,
        "defcon_points": 0,
    }


def test_rates_use_minutes_and_include_nonappearance_in_role_denominator():
    result = summarize_matches([_record(), _record(minutes=0, xg=0, xa=0)])
    assert result["xgi_per90"] == pytest.approx(0.6)
    assert result["minutes_per_fixture"] == 45
    assert result["start_rate"] == 0.5


def test_unknown_xg_does_not_become_zero_or_pollute_rate_denominator():
    result = summarize_matches([_record(), _record(xg=None)])
    assert result["xgi_per90"] == pytest.approx(0.6)
    assert result["xgi_minutes"] == 90
    assert result["minutes"] == 180
    assert summarize_matches([])["xgi_per90"] is None


def test_double_gameweek_defcon_counts_awards_not_aggregate_threshold():
    player = {
        "stats": {
            "minutes": 180,
            "total_points": 4,
            "starts": 2,
            "goals_scored": 0,
            "assists": 0,
            "defensive_contribution": 16,
        },
        "explain": [
            {"fixture": f, "stats": [{"identifier": "minutes", "value": 90, "points": 2}]}
            for f in (1, 2)
        ],
    }
    row = event_record(1, player, 2)
    assert row["defcon_hits"] == 0
    assert row["played_fixtures"] == 2
    player["explain"][1]["stats"].append(
        {"identifier": "defensive_contribution", "value": 12, "points": 2}
    )
    row = event_record(1, player, 2)
    assert row["defcon_hits"] == 1 and row["defcon_points"] == 2
    assert summarize_matches([row])["defcon_hit_rate"] == 0.5
    assert event_record(1, player, 3)["defcon_hits"] is None


def test_current_deadline_recent_windows_missing_forecast_and_no_official_xp():
    bootstrap = {
        "teams": [{"id": 1, "short_name": "ALP"}, {"id": 2, "short_name": "BET"}],
        "events": [
            {
                "id": e,
                "deadline_time": f"2026-10-{e:02d}T10:00:00Z",
                "finished": e < 8,
                "data_checked": e < 8,
            }
            for e in range(1, 10)
        ],
        "elements": [
            {
                "id": 1,
                "web_name": "Bruno",
                "team": 1,
                "element_type": 3,
                "now_cost": 120,
                "status": "a",
                "ep_next": "999",
            }
        ],
    }
    history = {1: [_record(e) for e in range(1, 8)]}
    board = build_board(
        bootstrap,
        [{"id": 80, "event": 8, "team_h": 1, "team_a": 2}],
        history,
        [],
        observed_at="2026-10-07T18:00:00+00:00",
        now=datetime(2026, 10, 7, 18, tzinfo=UTC),
    )
    player = board["players"][0]
    assert board["decision_event"] == 8
    assert player["recent"]["events"] == 3 and player["earlier"]["events"] == 4
    assert player["horizon"][0]["xp"] is None
    assert player["horizon"][0]["fixtures"][0]["opponent"] == "BET"
    assert any("Forecast" in warning for warning in player["warnings"])


def _generation(tmp_path):
    directory = tmp_path / "snapshots" / "generation-1"
    directory.mkdir(parents=True)
    bootstrap = {
        "teams": [{"id": 1, "short_name": "ALP"}, {"id": 2, "short_name": "BET"}],
        "events": [{"id": 8, "deadline_time": "2026-10-23T18:00:00Z"}],
        "elements": [{"id": 1, "web_name": "Example", "team": 1, "element_type": 3,
                      "now_cost": 100, "status": "a", "ep_next": "999"}],
    }
    fixtures = [{"id": 80, "event": 8, "team_h": 1, "team_a": 2}]
    for filename, data in (("bootstrap-static.json", bootstrap), ("fixtures.json", fixtures)):
        (directory / filename).write_text(json.dumps(data))
    official = {
        "snapshot_id": directory.name, "publishable": True,
        "observed_at": "2026-10-21T09:00:00+00:00",
        "files": {p.name: {"sha256": sha256_file(p)} for p in directory.iterdir()},
    }
    forecast = tmp_path / "forecasts.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "element": 1, "event_number": 8, "expected_points": 4.5,
        "forecast_created_at": "2026-10-21T09:15:00+00:00",
    }]), forecast)
    return official, directory, forecast


def test_automated_scouting_uses_the_decision_generation_without_network(tmp_path, monkeypatch):
    official, directory, forecast = _generation(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("Weekly scouting must reuse existing evidence")

    monkeypatch.setattr(httpx.Client, "request", no_network)
    monkeypatch.setattr(scouting, "SCORE_SHAPE_ARTIFACT", tmp_path / "no-artifact.json")
    forecast_bytes = forecast.read_bytes()
    board = scouting.refresh_scouting_from_generation(
        official, root=tmp_path / "board", forecast_path=forecast,
        snapshot_root=directory.parent, now=datetime(2026, 10, 21, 10, tzinfo=UTC),
    )
    assert board["refresh_mode"] == "weekly_pipeline"
    assert board["official_snapshot_id"] == official["snapshot_id"]
    assert board["observed_at"] == official["observed_at"]  # not falsely freshened
    assert board["decision_authority"] is False
    assert board["players"][0]["horizon"][0]["xp"] == 4.5  # never official ep_next
    assert forecast.read_bytes() == forecast_bytes
    assert scouting.read_scouting(root=tmp_path / "board") == board

    previous = (tmp_path / "board" / "current.json").read_bytes()
    (directory / "fixtures.json").write_text("[]")
    with pytest.raises(ValueError, match="differ from the decision generation"):
        scouting.refresh_scouting_from_generation(
            official, root=tmp_path / "board", forecast_path=forecast,
            snapshot_root=directory.parent,
        )
    assert (tmp_path / "board" / "current.json").read_bytes() == previous


def test_scouting_does_not_publish_if_forecasts_change_during_build(tmp_path, monkeypatch):
    official, directory, forecast = _generation(tmp_path)
    original = scouting.build_board

    def mutate_forecast(*args, **kwargs):
        board = original(*args, **kwargs)
        forecast.write_bytes(b"different generation")
        return board

    monkeypatch.setattr(scouting, "build_board", mutate_forecast)
    with pytest.raises(ValueError, match="Forecast changed"):
        scouting.refresh_scouting_from_generation(
            official, root=tmp_path / "board", forecast_path=forecast,
            snapshot_root=directory.parent, now=datetime(2026, 10, 21, 10, tzinfo=UTC),
        )
    assert not (tmp_path / "board" / "current.json").exists()
