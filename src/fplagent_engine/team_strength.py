from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.database import DATABASE

from .paths import NORMALIZED, ensure_engine_layout

HISTORICAL_TEAM_STRENGTH = NORMALIZED / "opponent_adjusted_team_strength.parquet"
CURRENT_TEAM_STRENGTH = NORMALIZED / "current_opponent_adjusted_team_strength.parquet"
TEAM_STRENGTH_METRICS = NORMALIZED / "team_strength_metrics.json"


@dataclass(frozen=True)
class RatingParameters:
    base_learning_rate: float = 0.045
    venue_learning_rate: float = 0.018
    global_learning_rate: float = 0.002
    half_life_days: float = 420.0
    venue_half_life_days: float = 240.0
    promoted_attack: float = -0.20
    promoted_defence: float = -0.16
    promoted_prior_strength: float = 6.0
    returning_club_weight: float = 0.20
    error_clip: float = 2.5


@dataclass
class TeamState:
    attack: float = 0.0
    defence: float = 0.0
    home_attack: float = 0.0
    away_attack: float = 0.0
    home_defence: float = 0.0
    away_defence: float = 0.0
    matches: int = 0
    last_time: datetime | None = None
    last_match_time: datetime | None = None


@dataclass(frozen=True)
class Fixture:
    season: str
    event: int
    fixture_id: int
    kickoff: datetime
    home_id: int
    away_id: int
    home_code: int
    away_code: int
    home_goals: int | None
    away_goals: int | None


@dataclass
class RatingRun:
    historical_rows: list[dict] = field(default_factory=list)
    current_rows: list[dict] = field(default_factory=list)
    evaluation_rows: list[dict] = field(default_factory=list)
    promoted_priors: list[dict] = field(default_factory=list)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _poisson_deviance(actual: np.ndarray, expected: np.ndarray) -> float:
    expected = np.clip(expected.astype(float), 1e-6, None)
    actual = actual.astype(float)
    terms = expected - actual
    positive = actual > 0
    terms[positive] += actual[positive] * np.log(
        actual[positive] / expected[positive]
    )
    return float(2.0 * np.mean(terms))


def _metric_summary(rows: list[dict], seasons: Iterable[str]) -> dict:
    selected_seasons = set(seasons)
    selected = [row for row in rows if row["season"] in selected_seasons]
    actual = np.asarray(
        [value for row in selected for value in (row["home_goals"], row["away_goals"])],
        dtype=float,
    )
    expected = np.asarray(
        [
            value
            for row in selected
            for value in (row["expected_home_goals"], row["expected_away_goals"])
        ],
        dtype=float,
    )
    clean_sheet_actual = np.asarray(
        [
            value
            for row in selected
            for value in (
                float(row["away_goals"] == 0),
                float(row["home_goals"] == 0),
            )
        ],
        dtype=float,
    )
    clean_sheet_probability = np.asarray(
        [
            value
            for row in selected
            for value in (
                math.exp(-row["expected_away_goals"]),
                math.exp(-row["expected_home_goals"]),
            )
        ],
        dtype=float,
    )
    return {
        "fixtures": len(selected),
        "poisson_deviance": _poisson_deviance(actual, expected),
        "goal_mae": float(np.mean(np.abs(actual - expected))),
        "clean_sheet_brier": float(
            np.mean(np.square(clean_sheet_actual - clean_sheet_probability))
        ),
    }


class DynamicTeamRatings:
    """Leakage-safe online hierarchical Poisson team ratings.

    Positive attack is better and positive defence is stronger. Each rating has a
    shared component and a smaller home/away residual. Match errors update both
    the scoring team and its opponent, which is what adjusts a five-match record
    for the quality of the teams faced.
    """

    def __init__(
        self,
        parameters: RatingParameters,
        initial_home_rate: float,
        initial_away_rate: float,
    ) -> None:
        self.parameters = parameters
        self.log_home_rate = math.log(initial_home_rate)
        self.log_away_rate = math.log(initial_away_rate)
        self.states: dict[int, TeamState] = {}
        self.previous_season_codes: set[int] | None = None
        self.season_codes: set[int] = set()
        self.entrants: set[int] = set()
        self.entrant_cohorts: list[tuple[float, float]] = []

    def _decay(self, state: TeamState, at: datetime) -> None:
        if state.last_time is None:
            state.last_time = at
            return
        days = max(0.0, (at - state.last_time).total_seconds() / 86400.0)
        base_decay = math.pow(0.5, days / self.parameters.half_life_days)
        venue_decay = math.pow(0.5, days / self.parameters.venue_half_life_days)
        state.attack *= base_decay
        state.defence *= base_decay
        state.home_attack *= venue_decay
        state.away_attack *= venue_decay
        state.home_defence *= venue_decay
        state.away_defence *= venue_decay
        state.last_time = at

    def _promoted_prior(self) -> tuple[float, float]:
        if not self.entrant_cohorts:
            return (
                self.parameters.promoted_attack,
                self.parameters.promoted_defence,
            )
        attack = np.asarray([item[0] for item in self.entrant_cohorts], dtype=float)
        defence = np.asarray([item[1] for item in self.entrant_cohorts], dtype=float)
        # Six prior-equivalent clubs stop one unusually strong or weak promoted
        # class from rewriting the prior. More recent cohorts receive more weight.
        recency = np.power(0.82, np.arange(len(attack) - 1, -1, -1))
        observed_weight = float(recency.sum())
        prior_weight = self.parameters.promoted_prior_strength
        return (
            float(
                (
                    np.dot(attack, recency)
                    + prior_weight * self.parameters.promoted_attack
                )
                / (observed_weight + prior_weight)
            ),
            float(
                (
                    np.dot(defence, recency)
                    + prior_weight * self.parameters.promoted_defence
                )
                / (observed_weight + prior_weight)
            ),
        )

    def begin_season(
        self, season: str, codes: set[int], at: datetime
    ) -> tuple[float, float]:
        if self.previous_season_codes is not None:
            for code in self.entrants:
                state = self.states[code]
                self.entrant_cohorts.append((state.attack, state.defence))
        prior_attack, prior_defence = self._promoted_prior()
        self.entrants = (
            set() if self.previous_season_codes is None else codes - self.previous_season_codes
        )
        for code in codes:
            old = self.states.get(code)
            if code in self.entrants:
                if old is not None:
                    self._decay(old, at)
                    weight = self.parameters.returning_club_weight
                    attack = weight * old.attack + (1.0 - weight) * prior_attack
                    defence = weight * old.defence + (1.0 - weight) * prior_defence
                else:
                    attack, defence = prior_attack, prior_defence
                self.states[code] = TeamState(
                    attack=attack,
                    defence=defence,
                    last_time=at,
                )
            elif old is None:
                self.states[code] = TeamState(last_time=at)
            else:
                self._decay(old, at)
        self.previous_season_codes = set(codes)
        self.season_codes = set(codes)
        return prior_attack, prior_defence

    def _rates(self, home_code: int, away_code: int) -> tuple[float, float]:
        home = self.states[home_code]
        away = self.states[away_code]
        expected_home = math.exp(
            self.log_home_rate
            + home.attack
            + home.home_attack
            - away.defence
            - away.away_defence
        )
        expected_away = math.exp(
            self.log_away_rate
            + away.attack
            + away.away_attack
            - home.defence
            - home.home_defence
        )
        return (
            float(np.clip(expected_home, 0.20, 4.50)),
            float(np.clip(expected_away, 0.15, 4.00)),
        )

    def snapshot(self, fixture: Fixture, at: datetime) -> tuple[dict, dict, dict]:
        home = self.states[fixture.home_code]
        away = self.states[fixture.away_code]
        self._decay(home, at)
        self._decay(away, at)
        expected_home, expected_away = self._rates(
            fixture.home_code, fixture.away_code
        )
        home_row = self._side_row(
            fixture,
            at,
            team=home,
            opponent=away,
            team_id=fixture.home_id,
            opponent_id=fixture.away_id,
            team_code=fixture.home_code,
            opponent_code=fixture.away_code,
            home=True,
            expected_for=expected_home,
            expected_against=expected_away,
        )
        away_row = self._side_row(
            fixture,
            at,
            team=away,
            opponent=home,
            team_id=fixture.away_id,
            opponent_id=fixture.home_id,
            team_code=fixture.away_code,
            opponent_code=fixture.home_code,
            home=False,
            expected_for=expected_away,
            expected_against=expected_home,
        )
        evaluation = {
            "season": fixture.season,
            "event": fixture.event,
            "fixture_id": fixture.fixture_id,
            "home_goals": fixture.home_goals,
            "away_goals": fixture.away_goals,
            "expected_home_goals": expected_home,
            "expected_away_goals": expected_away,
        }
        return home_row, away_row, evaluation

    def _side_row(
        self,
        fixture: Fixture,
        at: datetime,
        *,
        team: TeamState,
        opponent: TeamState,
        team_id: int,
        opponent_id: int,
        team_code: int,
        opponent_code: int,
        home: bool,
        expected_for: float,
        expected_against: float,
    ) -> dict:
        team_attack_delta = team.home_attack if home else team.away_attack
        team_defence_delta = team.home_defence if home else team.away_defence
        opponent_attack_delta = opponent.away_attack if home else opponent.home_attack
        opponent_defence_delta = (
            opponent.away_defence if home else opponent.home_defence
        )
        return {
            "season": fixture.season,
            "event": fixture.event,
            "fixture_id": fixture.fixture_id,
            "rating_at": at.isoformat(),
            "kickoff_time": fixture.kickoff.isoformat(),
            "team_id": team_id,
            "opponent_id": opponent_id,
            "team_code": team_code,
            "opponent_code": opponent_code,
            "home": float(home),
            "adjusted_team_attack": team.attack,
            "adjusted_team_defence": team.defence,
            "adjusted_team_venue_attack": team.attack + team_attack_delta,
            "adjusted_team_venue_defence": team.defence + team_defence_delta,
            "adjusted_opponent_attack": opponent.attack,
            "adjusted_opponent_defence": opponent.defence,
            "adjusted_opponent_venue_attack": opponent.attack
            + opponent_attack_delta,
            "adjusted_opponent_venue_defence": opponent.defence
            + opponent_defence_delta,
            "team_expected_goals": expected_for,
            "team_expected_goals_against": expected_against,
            "team_clean_sheet_probability": math.exp(-expected_against),
            "team_promoted_prior": float(team_code in self.entrants),
            "opponent_promoted_prior": float(opponent_code in self.entrants),
            "team_rating_matches": float(team.matches),
            "opponent_rating_matches": float(opponent.matches),
            "team_rating_days_since_match": (
                None
                if team.last_match_time is None
                else (at - team.last_match_time).total_seconds() / 86400.0
            ),
            "opponent_rating_days_since_match": (
                None
                if opponent.last_match_time is None
                else (at - opponent.last_match_time).total_seconds() / 86400.0
            ),
        }

    def update(self, fixtures: list[Fixture]) -> None:
        """Update a kickoff batch only after every expectation is calculated."""
        changes: defaultdict[tuple[int, str], float] = defaultdict(float)
        home_global_error = 0.0
        away_global_error = 0.0
        for fixture in fixtures:
            home = self.states[fixture.home_code]
            away = self.states[fixture.away_code]
            self._decay(home, fixture.kickoff)
            self._decay(away, fixture.kickoff)
            expected_home, expected_away = self._rates(
                fixture.home_code, fixture.away_code
            )
            error_home = float(
                np.clip(
                    fixture.home_goals - expected_home,
                    -self.parameters.error_clip,
                    self.parameters.error_clip,
                )
            )
            error_away = float(
                np.clip(
                    fixture.away_goals - expected_away,
                    -self.parameters.error_clip,
                    self.parameters.error_clip,
                )
            )
            base = self.parameters.base_learning_rate
            venue = self.parameters.venue_learning_rate
            changes[(fixture.home_code, "attack")] += base * error_home
            changes[(fixture.away_code, "defence")] -= base * error_home
            changes[(fixture.home_code, "home_attack")] += venue * error_home
            changes[(fixture.away_code, "away_defence")] -= venue * error_home
            changes[(fixture.away_code, "attack")] += base * error_away
            changes[(fixture.home_code, "defence")] -= base * error_away
            changes[(fixture.away_code, "away_attack")] += venue * error_away
            changes[(fixture.home_code, "home_defence")] -= venue * error_away
            home_global_error += error_home
            away_global_error += error_away
        for (code, attribute), change in changes.items():
            state = self.states[code]
            setattr(state, attribute, float(np.clip(getattr(state, attribute) + change, -1.2, 1.2)))
        for fixture in fixtures:
            for code in (fixture.home_code, fixture.away_code):
                state = self.states[code]
                state.matches += 1
                state.last_match_time = fixture.kickoff
        batch_size = max(1, len(fixtures))
        global_lr = self.parameters.global_learning_rate
        self.log_home_rate += global_lr * home_global_error / batch_size
        self.log_away_rate += global_lr * away_global_error / batch_size
        self.log_home_rate = float(
            np.clip(self.log_home_rate, math.log(0.9), math.log(2.2))
        )
        self.log_away_rate = float(
            np.clip(self.log_away_rate, math.log(0.7), math.log(1.8))
        )


def _load_historical(connection: duckdb.DuckDBPyConnection) -> list[Fixture]:
    rows = connection.execute(
        """
        SELECT
            f.season, f.event::INTEGER, f.id::INTEGER,
            cast(f.kickoff_time AS VARCHAR),
            f.team_h::INTEGER, f.team_a::INTEGER,
            ht.code::INTEGER, away_team.code::INTEGER,
            f.team_h_score::INTEGER, f.team_a_score::INTEGER
        FROM vaastav_fixtures f
        JOIN vaastav_teams ht ON f.season = ht.season AND f.team_h = ht.id
        JOIN vaastav_teams away_team
          ON f.season = away_team.season AND f.team_a = away_team.id
        WHERE f.event IS NOT NULL AND f.kickoff_time IS NOT NULL
          AND f.team_h_score IS NOT NULL AND f.team_a_score IS NOT NULL
        ORDER BY f.season, f.kickoff_time, f.id
        """
    ).fetchall()
    return [
        Fixture(
            season=row[0],
            event=row[1],
            fixture_id=row[2],
            kickoff=_parse_time(row[3]),
            home_id=row[4],
            away_id=row[5],
            home_code=row[6],
            away_code=row[7],
            home_goals=row[8],
            away_goals=row[9],
        )
        for row in rows
    ]


def _load_current(
    connection: duckdb.DuckDBPyConnection, horizon: int
) -> tuple[list[Fixture], dict[int, datetime]]:
    rows = connection.execute(
        """
        SELECT
            f.season, f.event::INTEGER, f.id::INTEGER, f.kickoff_time,
            f.team_h::INTEGER, f.team_a::INTEGER,
            ht.code::INTEGER, away_team.code::INTEGER,
            f.team_h_score::INTEGER, f.team_a_score::INTEGER
        FROM fpl_current_fixtures f
        JOIN fpl_current_teams ht ON f.team_h = ht.id
        JOIN fpl_current_teams away_team ON f.team_a = away_team.id
        WHERE f.event BETWEEN 1 AND ? AND f.kickoff_time IS NOT NULL
        ORDER BY f.event, f.kickoff_time, f.id
        """,
        [horizon],
    ).fetchall()
    deadlines = {
        int(event): _parse_time(deadline)
        for event, deadline in connection.execute(
            """
            SELECT id::INTEGER, deadline_time FROM fpl_current_events
            WHERE id BETWEEN 1 AND ?
            """,
            [horizon],
        ).fetchall()
    }
    return (
        [
            Fixture(
                season=row[0],
                event=row[1],
                fixture_id=row[2],
                kickoff=_parse_time(row[3]),
                home_id=row[4],
                away_id=row[5],
                home_code=row[6],
                away_code=row[7],
                home_goals=row[8],
                away_goals=row[9],
            )
            for row in rows
        ],
        deadlines,
    )


def _initial_rates(connection: duckdb.DuckDBPyConnection) -> tuple[float, float]:
    home, away = connection.execute(
        """
        SELECT avg(team_h_score)::DOUBLE, avg(team_a_score)::DOUBLE
        FROM vaastav_fixtures WHERE season = '2018-19'
        """
    ).fetchone()
    return float(home or 1.50), float(away or 1.15)


def _run(
    fixtures: list[Fixture],
    current: list[Fixture],
    current_deadlines: dict[int, datetime],
    parameters: RatingParameters,
    initial_rates: tuple[float, float],
) -> RatingRun:
    ratings = DynamicTeamRatings(parameters, *initial_rates)
    result = RatingRun()
    by_season: defaultdict[str, list[Fixture]] = defaultdict(list)
    for fixture in fixtures:
        by_season[fixture.season].append(fixture)

    for season in sorted(by_season):
        season_fixtures = by_season[season]
        codes = {
            code
            for fixture in season_fixtures
            for code in (fixture.home_code, fixture.away_code)
        }
        first_time = min(fixture.kickoff for fixture in season_fixtures)
        prior_attack, prior_defence = ratings.begin_season(season, codes, first_time)
        result.promoted_priors.append(
            {
                "season": season,
                "entrant_codes": sorted(ratings.entrants),
                "attack": prior_attack,
                "defence": prior_defence,
            }
        )
        by_event: defaultdict[int, list[Fixture]] = defaultdict(list)
        for fixture in season_fixtures:
            by_event[fixture.event].append(fixture)
        pending = sorted(season_fixtures, key=lambda item: (item.kickoff, item.fixture_id))
        consumed: set[int] = set()
        for event, event_fixtures in sorted(
            by_event.items(),
            key=lambda item: min(fixture.kickoff for fixture in item[1]),
        ):
            # Every side in an FPL event receives the exact same pre-deadline
            # information set, including double gameweeks and rearranged matches.
            cutoff = min(fixture.kickoff for fixture in event_fixtures) - timedelta(seconds=1)
            eligible = [
                fixture
                for fixture in pending
                if fixture.fixture_id not in consumed and fixture.kickoff < cutoff
            ]
            for kickoff in sorted({fixture.kickoff for fixture in eligible}):
                batch = [fixture for fixture in eligible if fixture.kickoff == kickoff]
                ratings.update(batch)
                consumed.update(fixture.fixture_id for fixture in batch)
            for fixture in event_fixtures:
                home, away, evaluation = ratings.snapshot(fixture, cutoff)
                result.historical_rows.extend((home, away))
                result.evaluation_rows.append(evaluation)
        remaining = [
            fixture for fixture in pending if fixture.fixture_id not in consumed
        ]
        for kickoff in sorted({fixture.kickoff for fixture in remaining}):
            batch = [fixture for fixture in remaining if fixture.kickoff == kickoff]
            ratings.update(batch)

    if current:
        season = current[0].season
        codes = {
            code for fixture in current for code in (fixture.home_code, fixture.away_code)
        }
        first_deadline = min(current_deadlines.values())
        prior_attack, prior_defence = ratings.begin_season(
            season, codes, first_deadline
        )
        result.promoted_priors.append(
            {
                "season": season,
                "entrant_codes": sorted(ratings.entrants),
                "attack": prior_attack,
                "defence": prior_defence,
            }
        )
        by_event: defaultdict[int, list[Fixture]] = defaultdict(list)
        for fixture in current:
            by_event[fixture.event].append(fixture)
        completed = sorted(
            (
                fixture
                for fixture in current
                if fixture.home_goals is not None and fixture.away_goals is not None
            ),
            key=lambda item: (item.kickoff, item.fixture_id),
        )
        consumed: set[int] = set()
        for event in sorted(by_event):
            at = current_deadlines[event]
            # Only results knowable at this event's deadline may update the
            # ratings. This lets GW2 learn from GW1 while keeping every fixture
            # within a GW on the same pre-deadline information set.
            eligible = [
                fixture
                for fixture in completed
                if fixture.fixture_id not in consumed and fixture.kickoff < at
            ]
            for kickoff in sorted({fixture.kickoff for fixture in eligible}):
                batch = [fixture for fixture in eligible if fixture.kickoff == kickoff]
                ratings.update(batch)
                consumed.update(fixture.fixture_id for fixture in batch)
            for fixture in by_event[event]:
                home, away, _ = ratings.snapshot(fixture, at)
                result.current_rows.extend((home, away))
    return result


def _calibrate(
    fixtures: list[Fixture], initial_rates: tuple[float, float]
) -> tuple[RatingParameters, list[dict]]:
    candidates = []
    for base_learning_rate in (0.030, 0.045, 0.060):
        for venue_learning_rate in (0.010, 0.018, 0.026):
            for half_life_days in (300.0, 420.0, 540.0):
                parameters = RatingParameters(
                    base_learning_rate=base_learning_rate,
                    venue_learning_rate=venue_learning_rate,
                    half_life_days=half_life_days,
                )
                run = _run(fixtures, [], {}, parameters, initial_rates)
                validation = _metric_summary(
                    run.evaluation_rows, ("2021-22", "2022-23")
                )
                candidates.append(
                    {
                        "parameters": asdict(parameters),
                        "validation": validation,
                    }
                )
    candidates.sort(
        key=lambda item: (
            item["validation"]["poisson_deviance"],
            item["validation"]["clean_sheet_brier"],
        )
    )
    return RatingParameters(**candidates[0]["parameters"]), candidates


def build_team_strength(horizon: int = 8, calibrate: bool = True) -> dict:
    ensure_engine_layout()
    connection = duckdb.connect(str(DATABASE), read_only=True)
    try:
        fixtures = _load_historical(connection)
        current, current_deadlines = _load_current(connection, horizon)
        initial_rates = _initial_rates(connection)
    finally:
        connection.close()
    parameters, candidates = (
        _calibrate(fixtures, initial_rates)
        if calibrate
        else (RatingParameters(), [])
    )
    run = _run(
        fixtures,
        current,
        current_deadlines,
        parameters,
        initial_rates,
    )
    pq.write_table(
        pa.Table.from_pylist(run.historical_rows),
        HISTORICAL_TEAM_STRENGTH,
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(run.current_rows),
        CURRENT_TEAM_STRENGTH,
        compression="zstd",
    )
    frozen = _metric_summary(
        run.evaluation_rows, ("2023-24", "2024-25", "2025-26")
    )
    by_season = {
        season: _metric_summary(run.evaluation_rows, (season,))
        for season in ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
    }
    metrics = {
        "created_at": datetime.now(UTC).isoformat(),
        "algorithm": "online_hierarchical_poisson_v1",
        "information_cutoff": "one shared snapshot before each FPL event",
        "official_fpl_strength_fields_used": False,
        "initial_rates_from_season": "2018-19",
        "initial_home_goals": initial_rates[0],
        "initial_away_goals": initial_rates[1],
        "calibration_seasons": ["2021-22", "2022-23"],
        "frozen_test_seasons": ["2023-24", "2024-25", "2025-26"],
        "parameters": asdict(parameters),
        "validation": _metric_summary(
            run.evaluation_rows, ("2021-22", "2022-23")
        ),
        "frozen_test": frozen,
        "by_season": by_season,
        "calibration_candidates": candidates,
        "promoted_priors": run.promoted_priors,
        "historical_rows": len(run.historical_rows),
        "current_rows": len(run.current_rows),
    }
    TEAM_STRENGTH_METRICS.write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metrics
