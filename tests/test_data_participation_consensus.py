from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.cli import parser
from fplagent_data.participation_consensus import (
    FFSCOUT_URL,
    build_consensus_rows,
    collect_participation_consensus,
    normalize_source_lineups,
    parse_ffscout_lineups,
    parse_rotowire_lineups,
)


def _players() -> list[dict]:
    return [
        {
            "id": element,
            "team": team,
            "first_name": f"First {element}",
            "second_name": f"Player {element}",
            "web_name": f"Player {element}",
            "known_name": "",
            "status": "a",
            "chance_of_playing_this_round": None,
            "chance_of_playing_next_round": None,
            "news": "",
            "can_select": True,
            "removed": False,
        }
        for team in (1, 2)
        for element in range((team - 1) * 11 + 1, team * 11 + 1)
    ]


def _teams() -> list[dict]:
    return [
        {"id": 1, "name": "Alpha", "short_name": "ALP"},
        {"id": 2, "name": "Beta", "short_name": "BET"},
    ]


def _events() -> list[dict]:
    return [
        {
            "id": 1,
            "deadline_time": "2026-08-21T17:30:00+00:00",
            "is_next": True,
            "is_current": False,
            "finished": False,
        }
    ]


def _fixtures() -> list[dict]:
    return [{"id": 9, "event": 1, "team_h": 1, "team_a": 2}]


def _source(source_id: str, *, updated: str | None = None) -> dict:
    return {
        "source_id": source_id,
        "source_updated_at": updated,
        "teams": [
            {
                "source_team_code": "ALP",
                "opponent_team_code": "BET",
                "lineup_status": "predicted",
                "players": [f"Player {element}" for element in range(1, 12)],
            },
            {
                "source_team_code": "BET",
                "opponent_team_code": "ALP",
                "lineup_status": "predicted",
                "players": [f"Player {element}" for element in range(12, 23)],
            },
        ],
    }


def test_ffscout_parser_extracts_timestamped_team_xi() -> None:
    payload = """
    <script type="application/ld+json">{"dateModified":"2026-08-20T10:00:00+00:00"}</script>
    <li class="team-news-item" data-team-code="alp">
      <span class="player-name truncate">Player 1</span>
      <span class="player-name truncate">Player 2</span>
    </li>
    <li class="team-news-item" data-team-code="bet">
      <span class="player-name truncate">Player 12</span>
    </li>
    """

    result = parse_ffscout_lineups(payload)

    assert result["source_updated_at"] == "2026-08-20T10:00:00+00:00"
    assert result["teams"] == [
        {
            "source_team_code": "ALP",
            "lineup_status": "predicted",
            "players": ["Player 1", "Player 2"],
            "source_updated_label": None,
            "fixture_identity_required": True,
            "fixture_label": None,
        },
        {
            "source_team_code": "BET",
            "lineup_status": "predicted",
            "players": ["Player 12"],
            "source_updated_label": None,
            "fixture_identity_required": True,
            "fixture_label": None,
        },
    ]


def test_rotowire_parser_excludes_injury_list_from_xi() -> None:
    def side(kind: str, first: int) -> str:
        players = "".join(
            f'<li class="lineup__player"><a title="Player {element}" '
            f'href="/soccer/player/p-{element}">P</a></li>'
            for element in range(first, first + 11)
        )
        return (
            f'<ul class="lineup__list {kind}">'
            '<li class="lineup__status is-expected">Predicted Lineup</li>'
            f'{players}<li class="lineup__title is-middle">Injuries</li>'
            '<li class="lineup__player"><a title="Not A Starter" '
            'href="/soccer/player/injured">I</a></li></ul>'
        )

    payload = (
        '<div class="lineup is-soccer"><div class="lineup__abbr">ALP</div>'
        '<div class="lineup__abbr">BET</div>' + side("is-home", 1) + side("is-visit", 12) + "</div>"
    )

    result = parse_rotowire_lineups(payload)

    assert len(result["teams"]) == 2
    assert result["teams"][0]["players"] == [f"Player {value}" for value in range(1, 12)]
    assert "Not A Starter" not in result["teams"][0]["players"]


def test_stale_source_is_archived_but_cannot_cast_consensus_vote() -> None:
    observations, context = normalize_source_lineups(
        [
            _source("fantasy_football_scout", updated="2026-07-20T10:00:00+00:00"),
            _source("rotowire"),
        ],
        players=_players(),
        teams=_teams(),
        fixtures=_fixtures(),
        events=_events(),
        observed_at="2026-08-20T18:00:00+00:00",
        event=1,
    )
    forecasts = [
        {
            "event_number": 1,
            "element": row["id"],
            "p_play": 0.9,
            "p_60_89": 0.2,
            "p_90_or_more": 0.6,
        }
        for row in _players()
    ]

    result = build_consensus_rows(
        observations,
        players=_players(),
        teams=_teams(),
        forecasts=forecasts,
        event=1,
    )

    assert context["sources"]["fantasy_football_scout"]["source_freshness"] == (
        "source_timestamp_stale"
    )
    assert result[0]["consensus"] == "single_source_start"
    assert result[0]["production_weight"] == 1.0
    assert result[0]["production_adjustment_authorized"] is True


def test_two_current_independent_sources_form_consensus() -> None:
    observations, _ = normalize_source_lineups(
        [
            _source("fantasy_football_scout", updated="2026-08-20T10:00:00+00:00"),
            _source("rotowire"),
        ],
        players=_players(),
        teams=_teams(),
        fixtures=_fixtures(),
        events=_events(),
        observed_at="2026-08-20T12:00:00+00:00",
        event=1,
    )
    result = build_consensus_rows(
        observations,
        players=_players(),
        teams=_teams(),
        forecasts=[],
        event=1,
    )

    assert result[0]["consensus"] == "predicted_start_consensus"
    assert result[0]["predicted_start_sources"] == [
        "fantasy_football_scout",
        "rotowire",
    ]


def test_source_freshness_tightens_as_deadline_approaches() -> None:
    early, _ = normalize_source_lineups(
        [_source("fantasy_football_scout", updated="2026-08-13T12:00:00+00:00")],
        players=_players(),
        teams=_teams(),
        fixtures=_fixtures(),
        events=_events(),
        observed_at="2026-08-17T12:00:00+00:00",
        event=1,
    )
    deadline, context = normalize_source_lineups(
        [_source("fantasy_football_scout", updated="2026-08-18T12:00:00+00:00")],
        players=_players(),
        teams=_teams(),
        fixtures=_fixtures(),
        events=_events(),
        observed_at="2026-08-20T18:00:00+00:00",
        event=1,
    )

    assert all(row["decision_eligible"] for row in early)
    assert all(not row["decision_eligible"] for row in deadline)
    assert context["sources"]["fantasy_football_scout"]["maximum_source_age_seconds"] == 18 * 3600


def test_unchanged_observation_only_content_expires() -> None:
    source = _source("rotowire")
    source["content_first_observed_at"] = "2026-08-17T12:00:00+00:00"
    observations, context = normalize_source_lineups(
        [source],
        players=_players(),
        teams=_teams(),
        fixtures=_fixtures(),
        events=_events(),
        observed_at="2026-08-20T12:00:00+00:00",
        event=1,
    )

    assert all(not row["decision_eligible"] for row in observations)
    assert context["sources"]["rotowire"]["source_freshness"] == "unchanged_content_stale"


def test_collector_freezes_raw_and_normalized_lineage(tmp_path) -> None:
    players = tmp_path / "players.parquet"
    teams = tmp_path / "teams.parquet"
    events = tmp_path / "events.parquet"
    fixtures = tmp_path / "fixtures.parquet"
    forecast = tmp_path / "forecast.parquet"
    for path, rows in (
        (players, _players()),
        (teams, _teams()),
        (events, _events()),
        (fixtures, _fixtures()),
    ):
        pq.write_table(pa.Table.from_pylist(rows), path)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event_number": 1,
                    "element": row["id"],
                    "p_play": 0.9,
                    "p_60_89": 0.2,
                    "p_90_or_more": 0.6,
                }
                for row in _players()
            ]
        ),
        forecast,
    )

    ff_body = (
        '<script>{"dateModified":"2026-08-20T10:00:00+00:00"}</script>'
        + '<li class="team-news-item" data-team-code="alp">'
        + '<div class="next-match"><strong>Next Match:</strong> Beta (H)</div>'
        + "<em>Last Updated Thu 20th Aug</em>"
        + "".join(f'<span class="player-name">Player {value}</span>' for value in range(1, 12))
        + '</li><li class="team-news-item" data-team-code="bet">'
        + '<div class="next-match"><strong>Next Match:</strong> Alpha (A)</div>'
        + "<em>Last Updated Thu 20th Aug</em>"
        + "".join(f'<span class="player-name">Player {value}</span>' for value in range(12, 23))
        + "</li>"
    ).encode()

    def side(kind: str, first: int) -> str:
        return (
            f'<ul class="lineup__list {kind}">'
            '<li class="lineup__status">Predicted Lineup</li>'
            + "".join(
                f'<li class="lineup__player"><a title="Player {value}" '
                f'href="/soccer/player/{value}">P</a></li>'
                for value in range(first, first + 11)
            )
            + "</ul>"
        )

    rw_body = (
        '<div class="lineup is-soccer"><div class="lineup__abbr">ALP</div>'
        '<div class="lineup__abbr">BET</div>' + side("is-home", 1) + side("is-visit", 12) + "</div>"
    ).encode()

    result = collect_participation_consensus(
        event=1,
        observed_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        players_path=players,
        teams_path=teams,
        events_path=events,
        fixtures_path=fixtures,
        forecast_path=forecast,
        observations_path=tmp_path / "observations.parquet",
        consensus_path=tmp_path / "consensus.parquet",
        receipt_path=tmp_path / "receipt.json",
        archive_dir=tmp_path / "archive",
        snapshot_dir=tmp_path / "snapshots",
        fetcher=lambda url: ff_body if url == FFSCOUT_URL else rw_body,
    )

    assert result["status"] == "production_consensus_ready"
    assert result["summary"]["predicted_start_consensus"] == 22
    assert result["promotion_gate"]["passed"] is False
    assert result["promotion_gate"]["operator_override_active"] is True
    assert result["sources"]["rotowire"]["sha256"]
    assert result["outputs"]["snapshot_manifest_sha256"]

    # Page advertising and another team's edit must not renew an unchanged XI.
    revised_rw = rw_body.replace(b"Player 22", b"Player 23") + b"<!-- changed advert nonce -->"
    later = collect_participation_consensus(
        event=1,
        observed_at=datetime(2026, 8, 20, 14, tzinfo=UTC),
        players_path=players,
        teams_path=teams,
        events_path=events,
        fixtures_path=fixtures,
        forecast_path=forecast,
        observations_path=tmp_path / "observations.parquet",
        consensus_path=tmp_path / "consensus.parquet",
        receipt_path=tmp_path / "receipt.json",
        archive_dir=tmp_path / "archive",
        snapshot_dir=tmp_path / "snapshots",
        fetcher=lambda url: ff_body + b"<!-- new advert -->" if url == FFSCOUT_URL else revised_rw,
    )
    before_rw = result["sources"]["rotowire"]["team_content_observations"]
    after_rw = later["sources"]["rotowire"]["team_content_observations"]
    unchanged = set(before_rw) & set(after_rw)
    assert len(unchanged) == 1
    assert all(after_rw[key] == before_rw[key] for key in unchanged)
    assert len(set(after_rw) - set(before_rw)) == 1
    assert (
        later["sources"]["fantasy_football_scout"]["team_content_observations"]
        == result["sources"]["fantasy_football_scout"]["team_content_observations"]
    )


def test_cli_exposes_participation_collector() -> None:
    args = parser().parse_args(
        [
            "collect-participation-consensus",
            "--event",
            "1",
            "--observed-at",
            "2026-08-20T12:00:00+00:00",
        ]
    )

    assert args.command == "collect-participation-consensus"
    assert args.event == 1
