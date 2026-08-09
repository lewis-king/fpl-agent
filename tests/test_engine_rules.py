import pytest

from fplagent_engine.rules import SquadRules, score_fixture, validate_lineup, validate_squad


def _rules() -> SquadRules:
    return SquadRules(
        budget=1000,
        squad_size=15,
        starting_size=11,
        club_limit=3,
        squad_positions={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        minimum_starters={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        maximum_starters={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_free_transfers=5,
        scoring={
            "short_play": 1,
            "long_play": 2,
            "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
            "assists": 3,
            "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
            "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
            "saves": 1,
            "penalties_saved": 5,
            "penalties_missed": -2,
            "yellow_cards": -1,
            "red_cards": -3,
            "own_goals": -2,
            "bonus": 1,
            "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        },
    )


def _squad() -> list[dict]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return [
        {
            "element": index + 1,
            "position": position,
            "team_id": (index // 3) + 1,
            "market_price": 50,
        }
        for index, position in enumerate(positions)
    ]


def test_squad_and_formation_are_legal() -> None:
    squad = _squad()
    validate_squad(squad, _rules())
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    validate_lineup(squad, starters, bench, 13, 8, _rules())


def test_illegal_four_from_one_club_is_rejected() -> None:
    squad = _squad()
    for player in squad[:4]:
        player["team_id"] = 1
    with pytest.raises(ValueError, match="club limit"):
        validate_squad(squad, _rules())


def test_current_scoring_components_are_applied() -> None:
    points = score_fixture(
        position="DEF",
        minutes=90,
        goals=1,
        clean_sheet=True,
        bonus=3,
        defensive_contribution_awarded=True,
        rules=_rules(),
    )
    assert points == 17
