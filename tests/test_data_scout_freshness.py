from datetime import UTC, datetime

import pytest
from test_data_participation_consensus import _events, _fixtures, _players, _teams

from fplagent_data.participation_consensus import (
    _scout_team_timestamp,
    normalize_source_lineups,
    parse_ffscout_lineups,
)


def _page(*, date="Thu 20th Aug", fixture="Beta (H)", count=11):
    return (
        '<script>{"dateModified":"2026-06-01T00:00:00+00:00"}</script>'
        '<li class="team-news-item" data-team-code="alp">'
        f'<div class="next-match"><strong>Next Match:</strong> {fixture}</div>'
        + "".join(f'<span class="player-name">Player {p}</span>' for p in range(1, count + 1))
        + f"<em>Last Updated {date}</em></li>"
    )


def _normalise(page, observed="2026-08-20T12:00:00+00:00"):
    return normalize_source_lineups(
        [parse_ffscout_lineups(page)],
        players=_players(),
        teams=_teams(),
        fixtures=_fixtures(),
        events=_events(),
        event=1,
        observed_at=observed,
    )


def test_team_update_replaces_old_article_date_not_fetch_time():
    rows, context = _normalise(_page())
    assert len(rows) == 11
    assert all(r["decision_eligible"] and r["source_complete"] for r in rows)
    assert rows[0]["source_updated_at"] == "2026-08-19T23:00:00+00:00"
    assert context["sources"]["fantasy_football_scout"]["source_freshness"] == "team_date_current"


@pytest.mark.parametrize("fixture", ["Beta (A)", "Gamma (H)", "", "Beta"])
def test_old_or_unidentified_fixture_is_not_attached_to_next_event(fixture):
    rows, context = _normalise(_page(fixture=fixture))
    assert not rows
    assert context["sources"]["fantasy_football_scout"]["decision_eligible"] is False


@pytest.mark.parametrize("date", ["", "Fri 21st Aug", "Thu 1st Jan", "Fri 20th Aug"])
def test_bad_stale_future_or_wrong_weekday_dates_do_not_vote(date):
    rows, _ = _normalise(_page(date=date))
    assert not any(r["decision_eligible"] for r in rows)


def test_day_precision_is_not_fabricated_as_a_recent_timestamp():
    rows, _ = _normalise(_page(), observed="2026-08-21T12:00:00+00:00")
    assert rows[0]["source_freshness"] == "team_date_stale_or_imprecise"
    assert not rows[0]["decision_eligible"]


def test_twelve_names_are_not_silently_truncated_into_a_complete_xi():
    rows, _ = _normalise(_page(count=12))
    assert len(rows) == 12
    assert not any(r["source_complete"] for r in rows)


def test_date_inference_handles_year_boundary_and_british_timezone():
    assert (
        _scout_team_timestamp("Thu 31st Dec", datetime(2027, 1, 1, 8, tzinfo=UTC)).isoformat()
        == "2026-12-31T00:00:00+00:00"
    )
