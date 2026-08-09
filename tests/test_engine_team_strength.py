from datetime import UTC, datetime, timedelta

from fplagent_engine.features import MODEL_FEATURES, RAW_OR_OFFICIAL_TEAM_FEATURES
from fplagent_engine.team_strength import (
    DynamicTeamRatings,
    Fixture,
    RatingParameters,
    _run,
)


def _fixture(
    fixture_id: int,
    event: int,
    kickoff: datetime,
    home_code: int,
    away_code: int,
    home_goals: int,
    away_goals: int,
) -> Fixture:
    return Fixture(
        season="2020-21",
        event=event,
        fixture_id=fixture_id,
        kickoff=kickoff,
        home_id=home_code,
        away_id=away_code,
        home_code=home_code,
        away_code=away_code,
        home_goals=home_goals,
        away_goals=away_goals,
    )


def test_full_event_uses_one_pre_deadline_information_set() -> None:
    start = datetime(2020, 9, 12, 12, tzinfo=UTC)
    fixtures = [
        _fixture(1, 1, start, 1, 2, 3, 0),
        _fixture(2, 1, start + timedelta(days=2), 3, 4, 1, 1),
        _fixture(3, 2, start + timedelta(days=8), 1, 3, 1, 0),
    ]
    run = _run(fixtures, [], {}, RatingParameters(), (1.5, 1.1))
    late_gameweek_one = next(
        row
        for row in run.historical_rows
        if row["fixture_id"] == 2 and row["team_code"] == 3
    )
    gameweek_two = next(
        row
        for row in run.historical_rows
        if row["fixture_id"] == 3 and row["team_code"] == 1
    )
    assert late_gameweek_one["adjusted_team_attack"] == 0.0
    assert late_gameweek_one["team_rating_matches"] == 0.0
    assert gameweek_two["adjusted_team_attack"] > 0.0
    assert gameweek_two["team_rating_matches"] == 1.0


def test_current_ratings_learn_only_from_results_before_next_deadline() -> None:
    gw1_deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    gw1_result = Fixture(
        season="2026-27",
        event=1,
        fixture_id=101,
        kickoff=gw1_deadline + timedelta(hours=2),
        home_id=1,
        away_id=2,
        home_code=1,
        away_code=2,
        home_goals=4,
        away_goals=0,
    )
    gw2 = Fixture(
        season="2026-27",
        event=2,
        fixture_id=102,
        kickoff=gw1_deadline + timedelta(days=7, hours=2),
        home_id=1,
        away_id=2,
        home_code=1,
        away_code=2,
        home_goals=None,
        away_goals=None,
    )
    run = _run(
        [],
        [gw1_result, gw2],
        {
            1: gw1_deadline,
            2: gw1_deadline + timedelta(days=7),
        },
        RatingParameters(),
        (1.5, 1.1),
    )
    gw1_row = next(
        row
        for row in run.current_rows
        if row["fixture_id"] == 101 and row["team_code"] == 1
    )
    gw2_row = next(
        row
        for row in run.current_rows
        if row["fixture_id"] == 102 and row["team_code"] == 1
    )
    assert gw1_row["team_rating_matches"] == 0.0
    assert gw1_row["adjusted_team_attack"] == 0.0
    assert gw2_row["team_rating_matches"] == 1.0
    assert gw2_row["adjusted_team_attack"] > 0.0


def test_conceding_two_to_strong_attack_is_penalized_less() -> None:
    at = datetime(2020, 9, 12, 12, tzinfo=UTC)
    parameters = RatingParameters(base_learning_rate=0.05)
    strong = DynamicTeamRatings(parameters, 1.5, 1.1)
    weak = DynamicTeamRatings(parameters, 1.5, 1.1)
    for ratings in (strong, weak):
        ratings.begin_season("2020-21", {1, 2}, at)
    strong.states[1].attack = 0.50
    weak.states[1].attack = -0.50
    result = _fixture(1, 1, at, 1, 2, 2, 0)
    strong.update([result])
    weak.update([result])
    assert strong.states[2].defence > weak.states[2].defence


def test_home_and_away_residuals_are_learned_separately() -> None:
    at = datetime(2020, 9, 12, 12, tzinfo=UTC)
    ratings = DynamicTeamRatings(RatingParameters(), 1.5, 1.1)
    ratings.begin_season("2020-21", {1, 2}, at)
    ratings.update([_fixture(1, 1, at, 1, 2, 4, 0)])
    assert ratings.states[1].home_attack > 0.0
    assert ratings.states[1].away_attack == 0.0


def test_new_and_returning_clubs_receive_promoted_prior() -> None:
    at = datetime(2020, 9, 12, 12, tzinfo=UTC)
    parameters = RatingParameters(promoted_attack=-0.25, promoted_defence=-0.20)
    ratings = DynamicTeamRatings(parameters, 1.5, 1.1)
    ratings.begin_season("2020-21", {1, 2}, at)
    ratings.begin_season("2021-22", {1, 3}, at + timedelta(days=350))
    assert ratings.entrants == {3}
    assert ratings.states[3].attack == -0.25
    assert ratings.states[3].defence == -0.20
    assert ratings.states[3].matches == 0


def test_challenger_excludes_official_and_unadjusted_team_ratings() -> None:
    assert set(RAW_OR_OFFICIAL_TEAM_FEATURES).isdisjoint(MODEL_FEATURES)
    assert "team_expected_goals" in MODEL_FEATURES
    assert "adjusted_opponent_venue_defence" in MODEL_FEATURES
