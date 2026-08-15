from __future__ import annotations

from fplagent_engine.understat_challenger import (
    match_understat_player,
    normalize_player_name,
)


def test_understat_name_normalization_handles_accents_and_punctuation() -> None:
    assert normalize_player_name("Pascal Groß") == "pascalgross"
    assert normalize_player_name("Calvert-Lewin") == "calvertlewin"


def test_understat_matcher_uses_full_known_or_web_name_without_fuzzy_guessing() -> None:
    understat = {
        "brunofernandes": [
            {"understat_player_id": 1, "player_name": "Bruno Fernandes"}
        ]
    }
    player = {
        "first_name": "Bruno",
        "second_name": "Borges Fernandes",
        "known_name": "Bruno Fernandes",
        "web_name": "B.Fernandes",
    }

    matched, method = match_understat_player(player, understat)

    assert matched is not None
    assert matched["understat_player_id"] == 1
    assert method == "known_name"


def test_understat_matcher_fails_closed_on_ambiguous_web_name() -> None:
    understat = {
        "onana": [
            {"understat_player_id": 1, "player_name": "Onana"},
            {"understat_player_id": 2, "player_name": "Onana"},
        ]
    }
    player = {
        "first_name": "Unknown",
        "second_name": "Person",
        "known_name": "",
        "web_name": "Onana",
    }

    matched, method = match_understat_player(player, understat)

    assert matched is None
    assert method == "ambiguous"
