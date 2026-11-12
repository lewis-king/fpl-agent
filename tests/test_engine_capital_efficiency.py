from fplagent_engine.capital_efficiency import (
    candidate_capital_role_risks,
    candidate_publication_role_risks,
    player_action_role_risk,
)


def _forecast(*, minutes_case: str, p_play: float = 0.97) -> dict:
    if minutes_case == "bench":
        probabilities = (0.22, 0.52, 0.18, 0.08)
    else:
        probabilities = (0.03, 0.03, 0.39, 0.55)
    return {
        "p_dnp": probabilities[0],
        "p_1_59": probabilities[1],
        "p_60_89": probabilities[2],
        "p_90_or_more": probabilities[3],
        "p_play": p_play,
        "live_participation_consensus": (
            "predicted_bench_consensus" if minutes_case == "bench" else "predicted_start_consensus"
        ),
    }


def test_premium_low_minute_player_blocks_candidate() -> None:
    risks = candidate_capital_role_risks(
        {"selected": [55]},
        {55: _forecast(minutes_case="bench", p_play=0.78)},
        {55: {"player_name": "Watkins", "position": "FWD", "market_price": 80.0}},
    )

    assert [row["player_name"] for row in risks] == ["Watkins"]
    assert "expected_minutes_below_60" in risks[0]["reasons"]
    assert "predicted_bench_consensus" in risks[0]["reasons"]


def test_cheap_enabler_and_clear_premium_start_are_not_blocked() -> None:
    risks = candidate_capital_role_risks(
        {"selected": [1, 2]},
        {
            1: _forecast(minutes_case="bench", p_play=0.78),
            2: _forecast(minutes_case="start"),
        },
        {
            1: {"player_name": "Enabler", "position": "MID", "market_price": 45.0},
            2: {"player_name": "Starter", "position": "MID", "market_price": 80.0},
        },
    )

    assert risks == []


def test_cheap_low_role_player_cannot_start_or_be_first_bench() -> None:
    forecast = _forecast(minutes_case="bench", p_play=0.78)
    meta = {"player_name": "Cheap risk", "position": "MID", "market_price": 45.0}

    assert player_action_role_risk(3, forecast, meta, action="starter") is not None
    assert player_action_role_risk(3, forecast, meta, action="bench_1") is not None


def test_candidate_gate_checks_lineup_captain_and_bench_roles() -> None:
    clear = _forecast(minutes_case="start")
    risky = _forecast(minutes_case="bench", p_play=0.78)
    candidate = {
        "selected": [1, 2, 3, 4],
        "lineups": {
            "1": {
                "starters": [1, 2],
                "bench_order": [3, 4],
                "captain": 1,
                "vice_captain": 2,
            }
        },
    }
    meta = {
        1: {"player_name": "Captain", "position": "MID", "market_price": 80.0},
        2: {"player_name": "Vice", "position": "FWD", "market_price": 80.0},
        3: {"player_name": "First bench", "position": "MID", "market_price": 45.0},
        4: {"player_name": "Reserve keeper", "position": "GK", "market_price": 40.0},
    }

    risks = candidate_publication_role_risks(
        candidate,
        {1: clear, 2: clear, 3: risky, 4: risky},
        meta,
    )

    assert {(row["player_name"], row.get("action")) for row in risks} == {
        ("First bench", "bench_1")
    }


def test_borderline_premium_minutes_are_reported_but_do_not_veto_publication() -> None:
    forecast = {
        **_forecast(minutes_case="start", p_play=0.887),
        "expected_minutes": 59.14,
        "live_participation_consensus": "not_covered",
    }
    candidate = {
        "selected": [427],
        "lineups": {
            "1": {
                "starters": [427],
                "bench_order": [],
                "captain": -1,
                "vice_captain": -1,
            }
        },
    }
    meta = {427: {"player_name": "Mbeumo", "position": "MID", "market_price": 80.0}}

    diagnostic = candidate_capital_role_risks(candidate, {427: forecast}, meta)
    publication = candidate_publication_role_risks(candidate, {427: forecast}, meta)

    assert diagnostic[0]["reasons"] == ["expected_minutes_below_60"]
    assert publication == []


def test_material_premium_role_risk_blocks_even_when_hidden_on_deep_bench() -> None:
    risky = {
        **_forecast(minutes_case="bench", p_play=0.78),
        "expected_minutes": 35.3,
    }
    clear = _forecast(minutes_case="start")
    candidate = {
        "selected": [1, 2, 3, 55],
        "lineups": {
            "1": {
                "starters": [1],
                "bench_order": [2, 3, 55],
                "captain": 1,
                "vice_captain": 1,
            }
        },
    }
    forecasts = {1: clear, 2: clear, 3: clear, 55: risky}
    meta = {
        1: {"player_name": "Safe starter", "position": "MID", "market_price": 60.0},
        2: {"player_name": "First bench", "position": "DEF", "market_price": 45.0},
        3: {"player_name": "Second bench", "position": "DEF", "market_price": 45.0},
        55: {"player_name": "Watkins", "position": "FWD", "market_price": 80.0},
    }

    risks = candidate_publication_role_risks(candidate, forecasts, meta)

    assert any(row["player_name"] == "Watkins" for row in risks)


def test_vice_captain_uses_starter_grade_minutes_not_captain_floor() -> None:
    forecast = {
        **_forecast(minutes_case="start", p_play=0.975),
        "expected_minutes": 64.88,
    }
    meta = {"player_name": "Consensus vice", "position": "MID", "market_price": 80.0}

    assert player_action_role_risk(5, forecast, meta, action="captain") is not None
    assert player_action_role_risk(5, forecast, meta, action="vice_captain") is None


def test_low_minute_vice_captain_still_blocks() -> None:
    forecast = {
        **_forecast(minutes_case="start", p_play=0.975),
        "expected_minutes": 54.99,
    }
    meta = {"player_name": "Low-minute vice", "position": "MID", "market_price": 80.0}

    risk = player_action_role_risk(6, forecast, meta, action="vice_captain")

    assert risk is not None
    assert "vice_expected_minutes_below_55" in risk["reasons"]


def test_borderline_midfielder_vice_uses_position_starter_floor() -> None:
    forecast = {
        **_forecast(minutes_case="start", p_play=0.887),
        "expected_minutes": 59.14,
        "live_participation_consensus": "single_source_start",
    }
    meta = {"player_name": "Mbeumo", "position": "MID", "market_price": 80.0}

    assert player_action_role_risk(427, forecast, meta, action="vice_captain") is None
