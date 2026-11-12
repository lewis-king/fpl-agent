from dataclasses import replace

import pytest
from test_engine_weekly_simulation import _rows, _state

from fplagent_engine import historical_blank_holdings as module


def setup(monkeypatch):
    state = replace(_state(), season="2024-25")
    rows = [r for r in _rows() if r["element"] != 1]
    base = dict(_rows()[0], event_number=1, target_points=99, target_minutes=90)
    inputs = {
        "forecast_by_event": {("2024-25", 1): [base]},
        "feature_by_key": {},
        "fixture_by_snapshot": {},
        "available_snapshots": {},
    }
    monkeypatch.setattr(
        module,
        "_schedule_at_origin",
        lambda **kw: (
            {(2, 1): {"fixture_count": 1.0, "home_fraction": 0.5, "fixture_difficulty": 3.0}},
            2,
        ),
    )
    monkeypatch.setattr(module, "_prior_neutral_rate", lambda **kw: 4.0)
    monkeypatch.setattr(
        module, "_fixture_multiplier", lambda position, n, home, difficulty, coefficients: n
    )
    catalog = [
        {
            "season": "2024-25",
            "id": 1,
            "team": 1,
            "decision_event": 2,
            "now_cost": 55,
            "observed_at": "2024-08-18T12:00:00Z",
            "deadline_at": "2024-08-20T12:00:00Z",
            "snapshot_sha": "asof",
        }
    ]
    finals = [
        {"season": "2024-25", "id": i, "event": 3, "team_h": h, "team_a": a, "finished": True}
        for i, (h, a) in enumerate((h, a) for h in range(1, 21) for a in range(1, 21) if h != a)
    ]
    return state, rows, inputs, catalog, finals


def test_certified_actual_blank_does_not_leak_into_asof_forecast(monkeypatch):
    state, rows, inputs, catalog, finals = setup(monkeypatch)
    repaired, actual, report = module.complete_blank_holdings(
        state, rows, [], inputs, {}, catalog_rows=catalog, final_fixtures=finals
    )
    player = next(r for r in repaired if r["element"] == 1 and r["event_number"] == 2)
    assert player["expected_points"] == 4 and player["p_play"] == 0.95
    assert player["market_price"] == 55
    assert not any(k.startswith("target_") for k in player)
    assert actual[0]["target_minutes"] == actual[0]["target_points"] == 0
    assert report[0]["actual_blank_certified"]
    catalog.append(dict(catalog[0], decision_event=3, now_cost=100))
    assert module.complete_blank_holdings(
        state, rows, [], inputs, {}, catalog_rows=catalog, final_fixtures=finals
    ) == (repaired, actual, report)


def test_missing_or_played_fixture_is_not_zero_filled(monkeypatch):
    state, rows, inputs, catalog, finals = setup(monkeypatch)
    with pytest.raises(ValueError, match="380-match"):
        module.complete_blank_holdings(
            state, rows, [], inputs, {}, catalog_rows=catalog, final_fixtures=finals[:-1]
        )
    finals[0]["event"] = 2
    with pytest.raises(ValueError, match="not a certified"):
        module.complete_blank_holdings(
            state, rows, [], inputs, {}, catalog_rows=catalog, final_fixtures=finals
        )


def test_postdeadline_catalog_is_rejected(monkeypatch):
    state, rows, inputs, catalog, finals = setup(monkeypatch)
    catalog[0]["observed_at"] = "2024-08-21T12:00:00Z"
    with pytest.raises(ValueError, match="after its declared deadline"):
        module.complete_blank_holdings(
            state, rows, [], inputs, {}, catalog_rows=catalog, final_fixtures=finals
        )
