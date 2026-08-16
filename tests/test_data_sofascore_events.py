from datetime import UTC, datetime

from fplagent_data.cli import parser
from fplagent_data.sofascore_events import (
    build_stable_player_mapping,
    discover_season_id,
    parse_finished_event,
    point_in_time_folds,
)


def test_season_id_is_discovered_not_hardcoded() -> None:
    payload = {"seasons": [{"id": 99, "name": "26/27", "year": "26/27"}]}
    assert discover_season_id(payload, "2026-27") == 99


def test_stable_player_mapping_reuses_provider_id_and_fails_closed() -> None:
    source = [
        {
            "source_player_id": 500,
            "source_player_name": "A Player",
            "source_team_id": 10,
            "source_team_name": "Alpha",
        },
        {
            "source_player_id": 501,
            "source_player_name": "Unknown Person",
            "source_team_id": 10,
            "source_team_name": "Alpha",
        },
    ]
    players = [
        {
            "id": 1,
            "team": 1,
            "first_name": "A",
            "second_name": "Player",
            "web_name": "Player",
            "known_name": "",
        }
    ]
    result = build_stable_player_mapping(
        source,
        fpl_players=players,
        team_mapping={10: 1},
        prior_mapping=[{"source_player_id": 500, "fpl_element": 1, "stable": True}],
    )
    assert result[0]["mapping_method"] == "stable_provider_id"
    assert result[0]["fpl_element"] == 1
    assert result[1]["fpl_element"] is None


def test_event_rows_are_only_available_after_match() -> None:
    kickoff = datetime(2026, 8, 22, 14, tzinfo=UTC)
    event = {
        "id": 7,
        "startTimestamp": int(kickoff.timestamp()),
        "status": {"type": "finished"},
        "roundInfo": {"round": 1},
        "homeTeam": {"id": 10, "name": "Alpha"},
        "awayTeam": {"id": 20, "name": "Beta"},
        "homeScore": {"current": 2},
        "awayScore": {"current": 1},
    }
    lineup = {
        "confirmed": True,
        "home": {
            "players": [
                {
                    "player": {"id": 500, "name": "A Player", "position": "M"},
                    "substitute": False,
                    "statistics": {"minutesPlayed": 90, "expectedGoals": 0.4},
                }
            ]
        },
        "away": {"players": []},
    }
    event_row, players = parse_finished_event(event, lineup, season="2026-27", source_season_id=99)
    assert datetime.fromisoformat(event_row["available_after"]) == kickoff.replace(hour=17)
    folds = point_in_time_folds(
        players,
        [
            {
                "season": "2026-27",
                "event": 2,
                "deadline_time": "2026-08-28T17:30:00+00:00",
            }
        ],
    )
    assert folds[0]["training_rows"] == 1
    assert folds[0]["passed"] is True


def test_data_cli_exposes_independent_event_collection() -> None:
    args = parser().parse_args(["collect-sofascore-player-events", "--season", "2025-26"])
    assert args.season == "2025-26"
