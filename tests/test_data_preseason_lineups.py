from __future__ import annotations

from datetime import UTC, datetime

from fplagent_data.preseason_lineups import (
    build_role_evidence,
    filter_preseason_events,
    fpl_role_mapping_fingerprint,
    match_sofascore_player,
    normalize_name,
    parse_lineup_side,
)


def _player(element: int = 1) -> dict:
    return {
        "id": element,
        "code": 1000 + element,
        "team": 1,
        "first_name": "David",
        "second_name": "Raya Martín",
        "web_name": "Raya",
        "known_name": "",
        "team_join_date": "2024-07-04",
    }


def _event(event_id: int = 10, timestamp: int = 1786046400) -> dict:
    return {
        "id": event_id,
        "startTimestamp": timestamp,
        "status": {"type": "finished"},
        "tournament": {"name": "Club Friendly Games"},
        "homeTeam": {"id": 42, "name": "Arsenal"},
        "awayTeam": {"id": 500, "name": "Visitors"},
    }


def test_name_matching_uses_team_scoped_aliases_and_preserves_accents() -> None:
    element, method, score = match_sofascore_player("David Raya", [_player()])

    assert element == 1
    assert method == "exact_alias"
    assert score == 1.0
    assert normalize_name("Gyökeres") == "gyokeres"


def test_role_mapping_fingerprint_ignores_snapshot_and_market_noise() -> None:
    teams = [{"id": 1, "name": "Arsenal", "short_name": "ARS"}]
    players = [{**_player(), "snapshot_at": "first", "transfers_in_event": 10}]
    events = [
        {
            "id": 1,
            "deadline_time": "2026-08-21T17:30:00+00:00",
            "snapshot_at": "first",
        }
    ]
    noisy_players = [
        {**players[0], "snapshot_at": "second", "transfers_in_event": 999}
    ]
    remapped_players = [{**players[0], "team": 2}]

    baseline = fpl_role_mapping_fingerprint(teams, players, events)

    assert baseline == fpl_role_mapping_fingerprint(teams, noisy_players, events)
    assert baseline != fpl_role_mapping_fingerprint(teams, remapped_players, events)


def test_name_matching_handles_verified_and_unique_contained_aliases() -> None:
    white = _player(element=10)
    white["first_name"] = "Benjamin"
    white["second_name"] = "White"
    white["web_name"] = "White"
    fatawu = _player(element=315)
    fatawu["first_name"] = "Abdul"
    fatawu["second_name"] = "Fatawu"
    fatawu["known_name"] = "Abdul Fatawu"
    fatawu["web_name"] = "Fatawu"

    assert match_sofascore_player("Ben White", [white]) == (
        10,
        "exact_alias",
        1.0,
    )
    assert match_sofascore_player("Abdul Fatawu Issahaku", [fatawu]) == (
        315,
        "unique_token_containment",
        1.0,
    )


def test_finished_events_are_filtered_to_the_predeadline_window() -> None:
    included = _event(timestamp=1786046400)
    future = _event(event_id=11, timestamp=1787860800)
    unfinished = _event(event_id=12, timestamp=1786046400)
    unfinished["status"] = {"type": "notstarted"}

    rows = filter_preseason_events(
        {"events": [included, future, unfinished]},
        start_timestamp=1782864000,
        deadline_timestamp=1787259600,
    )

    assert [row["id"] for row in rows] == [10]


def test_confirmed_lineup_and_join_date_produce_advisory_role_evidence() -> None:
    event = _event()
    payload = {
        "confirmed": True,
        "home": {
            "players": [
                {
                    "player": {"id": 99, "name": "David Raya"},
                    "shirtNumber": 1,
                    "substitute": False,
                    "statistics": {"minutesPlayed": 62},
                }
            ]
        },
        "away": {"players": []},
    }
    lineup = parse_lineup_side(
        payload,
        side="home",
        event=event,
        fpl_team_id=1,
        sofascore_team_id=42,
        candidates=[_player()],
        observed_at="2026-08-07T12:00:00+00:00",
    )
    event_rows = [
        {
            "event_id": 10,
            "fpl_team_id": 1,
            "kickoff_time": datetime.fromtimestamp(
                event["startTimestamp"], UTC
            ).isoformat(),
        }
    ]

    evidence = build_role_evidence(
        [_player()],
        event_rows,
        lineup,
        deadline=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
        observed_at="2026-08-07T12:00:00+00:00",
    )[0]

    assert lineup[0]["starter"] is True
    assert lineup[0]["minutes"] == 62
    assert evidence["eligible_team_matches"] == 1
    assert evidence["starts"] == 1
    assert evidence["minutes"] == 62
    assert evidence["minutes_data_complete"] is True
    assert evidence["evidence_status"] == "observed_in_lineup"


def test_missing_source_minutes_remain_unknown_in_role_evidence() -> None:
    event = _event()
    payload = {
        "confirmed": True,
        "home": {
            "players": [
                {
                    "player": {"id": 99, "name": "David Raya"},
                    "shirtNumber": 1,
                    "substitute": False,
                    "statistics": {},
                }
            ]
        },
        "away": {"players": []},
    }
    lineup = parse_lineup_side(
        payload,
        side="home",
        event=event,
        fpl_team_id=1,
        sofascore_team_id=42,
        candidates=[_player()],
        observed_at="2026-08-07T12:00:00+00:00",
    )
    event_rows = [
        {
            "event_id": 10,
            "fpl_team_id": 1,
            "kickoff_time": datetime.fromtimestamp(
                event["startTimestamp"], UTC
            ).isoformat(),
        }
    ]

    evidence = build_role_evidence(
        [_player()],
        event_rows,
        lineup,
        deadline=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
        observed_at="2026-08-07T12:00:00+00:00",
    )[0]

    assert lineup[0]["starter"] is True
    assert lineup[0]["appeared"] is True
    assert lineup[0]["minutes"] is None
    assert evidence["minutes"] is None
    assert evidence["known_minutes"] == 0
    assert evidence["minutes_observations"] == 0
    assert evidence["minutes_data_complete"] is False
    assert evidence["minutes_per_team_match"] is None
