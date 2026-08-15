from __future__ import annotations

import pytest

from fplagent_data.understat import UnderstatDataError, normalize_league_payload


def _payload() -> dict:
    return {
        "players": [
            {
                "id": "10",
                "player_name": "Example Player",
                "games": "20",
                "time": "1500",
                "goals": "7",
                "npg": "6",
                "assists": "4",
                "shots": "50",
                "key_passes": "30",
                "yellow_cards": "2",
                "red_cards": "0",
                "position": "M",
                "team_title": "Example FC",
                "xG": "8.2",
                "npxG": "7.4",
                "xA": "5.1",
                "xGChain": "14.0",
                "xGBuildup": "6.5",
            }
        ],
        "teams": {
            "1": {
                "id": "1",
                "title": "Example FC",
                "history": [
                    {
                        "h_a": "h",
                        "xG": 1.5,
                        "xGA": 0.7,
                        "npxG": 1.5,
                        "npxGA": 0.7,
                        "ppda": {"att": 100, "def": 10},
                        "ppda_allowed": {"att": 180, "def": 20},
                        "deep": 8,
                        "deep_allowed": 3,
                        "scored": 2,
                        "missed": 0,
                        "xpts": 2.1,
                        "result": "w",
                        "date": "2025-08-15 20:00:00",
                    }
                ],
            }
        },
        "dates": [
            {
                "id": "99",
                "isResult": False,
                "h": {"id": "1", "title": "Example FC"},
                "a": {"id": "2", "title": "Other FC"},
                "goals": {"h": None, "a": None},
                "xG": {"h": None, "a": None},
                "datetime": "2026-08-15 20:00:00",
                "forecast": {"w": "0.5", "d": "0.3", "l": "0.2"},
            }
        ],
    }


def test_understat_normalization_keeps_external_provenance_and_null_outcomes() -> None:
    result = normalize_league_payload(
        _payload(),
        season_start=2025,
        observed_at="2026-08-15T10:00:00+00:00",
    )

    player = result["players"][0]
    fixture = result["fixtures"][0]
    assert player["provider"] == "Understat"
    assert player["xg"] == pytest.approx(8.2)
    assert player["minutes"] == 1500
    assert fixture["is_result"] is False
    assert fixture["home_xg"] is None
    assert fixture["home_goals"] is None


def test_understat_schema_change_fails_closed() -> None:
    payload = _payload()
    del payload["players"][0]["xA"]

    with pytest.raises(UnderstatDataError, match="changed schema"):
        normalize_league_payload(
            payload,
            season_start=2025,
            observed_at="2026-08-15T10:00:00+00:00",
        )
