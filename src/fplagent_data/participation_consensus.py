from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .arrow import write_rows
from .http import USER_AGENT, sha256_file
from .paths import MANIFESTS, PROCESSED, RAW, ensure_layout
from .preseason_lineups import match_sofascore_player

SEASON = "2026-27"
VERSION = "participation_consensus_v1"
FFSCOUT_URL = "https://cdn.fantasyfootballscout.co.uk/team-news"
ROTOWIRE_URL = "https://www.rotowire.com/soccer/lineups.php?league=EPL"
SOURCE_URLS = {
    "fantasy_football_scout": FFSCOUT_URL,
    "rotowire": ROTOWIRE_URL,
}
SOURCE_UPDATED_MAX_AGE = timedelta(days=7)

FPL_DIR = PROCESSED / "fpl" / SEASON / "preseason"
PLAYERS = FPL_DIR / "players.parquet"
TEAMS = FPL_DIR / "teams.parquet"
EVENTS = FPL_DIR / "events.parquet"
FIXTURES = FPL_DIR / "fixtures.parquet"
FORECAST = Path(__file__).resolve().parents[2] / "data" / "model" / "forecasts" / (
    f"{SEASON}-preseason.parquet"
)
RAW_DIR = RAW / "supporting" / "participation" / SEASON
ARCHIVE_DIR = RAW_DIR / "archive"
OUT_DIR = PROCESSED / "supporting" / "participation" / SEASON
OBSERVATIONS = OUT_DIR / "predicted_lineup_observations.parquet"
CONSENSUS = OUT_DIR / "participation_consensus.parquet"
SNAPSHOT_DIR = OUT_DIR / "snapshots"
RECEIPT = MANIFESTS / "participation_consensus_current.json"

TEAM_CODE_ALIASES = {
    "not": "NFO",
}

OBSERVATION_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("event", pa.int16()),
        ("deadline_time", pa.string()),
        ("observed_at", pa.string()),
        ("source_id", pa.string()),
        ("source_url", pa.string()),
        ("source_updated_at", pa.string()),
        ("source_freshness", pa.string()),
        ("source_team_code", pa.string()),
        ("team_id", pa.int16()),
        ("team_short_name", pa.string()),
        ("fixture_id", pa.int32()),
        ("opponent_team_id", pa.int16()),
        ("lineup_status", pa.string()),
        ("source_complete", pa.bool_()),
        ("source_player_name", pa.string()),
        ("fpl_element", pa.int32()),
        ("match_method", pa.string()),
        ("match_score", pa.float64()),
        ("predicted_start", pa.bool_()),
        ("decision_eligible", pa.bool_()),
    ]
)


class ParticipationConsensusError(ValueError):
    """Participation evidence could not be aligned to an official FPL generation."""


def _aware(value: str | datetime, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ParticipationConsensusError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _clean_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def parse_ffscout_lineups(payload: bytes | str) -> dict[str, Any]:
    """Parse the server-rendered FFScout team-news page without executing scripts."""
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    modified = re.search(r'"dateModified"\s*:\s*"([^"]+)"', text)
    starts = list(
        re.finditer(r'<li\s+class="team-news-item"\s+data-team-code="([^"]+)"', text)
    )
    teams = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.end() : end]
        names = [
            _clean_text(value)
            for value in re.findall(
                r'<span\s+class="player-name[^"]*"[^>]*>(.*?)</span>',
                block,
                flags=re.DOTALL,
            )
        ]
        teams.append(
            {
                "source_team_code": match.group(1).upper(),
                "lineup_status": "predicted",
                "players": [name for name in names if name][:11],
            }
        )
    return {
        "source_id": "fantasy_football_scout",
        "source_updated_at": modified.group(1) if modified else None,
        "teams": teams,
    }


def parse_rotowire_lineups(payload: bytes | str) -> dict[str, Any]:
    """Parse fixture-level predicted/confirmed XIs from RotoWire's public page."""
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    starts = list(re.finditer(r'<div\s+class="lineup is-soccer"', text))
    teams = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start() : end]
        codes = re.findall(r'<div\s+class="lineup__abbr">\s*([^<]+)', block)
        lists = re.findall(
            r'<ul\s+class="lineup__list\s+(is-home|is-visit)"[^>]*>(.*?)</ul>',
            block,
            flags=re.DOTALL,
        )
        if len(codes) < 2 or len(lists) < 2:
            continue
        for side, body in lists[:2]:
            team_index = 0 if side == "is-home" else 1
            status_match = re.search(
                r'lineup__status[^>]*>.*?(Predicted|Confirmed)\s+Lineup',
                body,
                flags=re.DOTALL | re.IGNORECASE,
            )
            starters = body.split('class="lineup__title is-middle"', 1)[0]
            names = [
                _clean_text(value)
                for value in re.findall(
                    r'<a\s+title="([^"]+)"\s+href="/soccer/player/', starters
                )
            ]
            teams.append(
                {
                    "source_team_code": codes[team_index].strip().upper(),
                    "opponent_team_code": codes[1 - team_index].strip().upper(),
                    "lineup_status": (
                        status_match.group(1).lower() if status_match else "unknown"
                    ),
                    "players": names[:11],
                }
            )
    return {"source_id": "rotowire", "source_updated_at": None, "teams": teams}


def _fetch_html(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise ParticipationConsensusError(f"{url} returned HTTP {response.status}")
        return response.read()


def _archive(source_id: str, body: bytes, archive_dir: Path) -> dict[str, Any]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body).hexdigest()
    path = archive_dir / f"{source_id}-{digest}.html"
    if not path.exists():
        temporary = path.with_suffix(".html.tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    return {
        "archive_path": str(path),
        "sha256": digest,
        "bytes": len(body),
    }


def _event_context(
    events: list[dict[str, Any]], fixtures: list[dict[str, Any]], event: int | None
) -> tuple[int, str, dict[int, list[tuple[int, int]]]]:
    if event is None:
        candidates = [row for row in events if row.get("is_next") or row.get("is_current")]
        if not candidates:
            candidates = [row for row in events if not row.get("finished")]
        if not candidates:
            raise ParticipationConsensusError("no current or future official event exists")
        event = min(int(row["id"]) for row in candidates)
    matches = [row for row in events if int(row["id"]) == event]
    if len(matches) != 1:
        raise ParticipationConsensusError(f"official events contain no unique event {event}")
    deadline = str(matches[0]["deadline_time"])
    fixture_by_team: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row in fixtures:
        if row.get("event") is None or int(row["event"]) != event:
            continue
        home, away, fixture_id = int(row["team_h"]), int(row["team_a"]), int(row["id"])
        fixture_by_team[home].append((fixture_id, away))
        fixture_by_team[away].append((fixture_id, home))
    return event, deadline, fixture_by_team


def _source_code(value: str) -> str:
    normalized = value.strip().casefold()
    return TEAM_CODE_ALIASES.get(normalized, normalized.upper())


def normalize_source_lineups(
    parsed_sources: list[dict[str, Any]],
    *,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    events: list[dict[str, Any]],
    observed_at: str | datetime,
    event: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observed = _aware(observed_at, "observed_at")
    event, deadline_text, fixture_by_team = _event_context(events, fixtures, event)
    deadline = _aware(deadline_text, "deadline_time")
    team_by_code = {
        str(row["short_name"]).upper(): row for row in teams if row.get("short_name")
    }
    players_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        players_by_team[int(player["team"])].append(player)

    rows: list[dict[str, Any]] = []
    source_coverage: dict[str, dict[str, Any]] = {}
    for source in parsed_sources:
        source_id = str(source["source_id"])
        source_updated_at = source.get("source_updated_at")
        source_freshness = "observation_timestamp_only"
        source_current = True
        if source_updated_at:
            try:
                updated = _aware(str(source_updated_at), "source_updated_at")
                source_current = timedelta(0) <= observed - updated <= SOURCE_UPDATED_MAX_AGE
                source_freshness = (
                    "source_timestamp_current"
                    if source_current
                    else "source_timestamp_stale"
                )
            except (ParticipationConsensusError, ValueError):
                source_current = False
                source_freshness = "invalid_source_timestamp"
        coverage = {
            "source_id": source_id,
            "teams_seen": 0,
            "teams_aligned_to_event": 0,
            "complete_teams": 0,
            "players_seen": 0,
            "players_matched": 0,
            "unmatched_players": [],
            "source_freshness": source_freshness,
            "decision_eligible": observed < deadline and source_current,
            "ambiguous_multi_fixture_teams": [],
        }
        for source_team in source.get("teams", []):
            coverage["teams_seen"] += 1
            code = _source_code(str(source_team.get("source_team_code") or ""))
            team = team_by_code.get(code)
            if team is None:
                continue
            team_id = int(team["id"])
            team_fixtures = fixture_by_team.get(team_id) or []
            if not team_fixtures:
                continue
            opponent_code = source_team.get("opponent_team_code")
            if opponent_code:
                opponent = team_by_code.get(_source_code(str(opponent_code)))
                matching_fixtures = (
                    [row for row in team_fixtures if row[1] == int(opponent["id"])]
                    if opponent is not None
                    else []
                )
                if len(matching_fixtures) != 1:
                    continue
                fixture = matching_fixtures[0]
            elif len(team_fixtures) == 1:
                fixture = team_fixtures[0]
            else:
                coverage["ambiguous_multi_fixture_teams"].append(code)
                continue
            coverage["teams_aligned_to_event"] += 1
            source_names = list(map(str, source_team.get("players") or []))
            matched: list[tuple[str, int | None, str, float | None]] = []
            for name in source_names:
                element, method, score = match_sofascore_player(
                    name, players_by_team[team_id]
                )
                matched.append((name, element, method, score))
                coverage["players_seen"] += 1
                if element is None:
                    coverage["unmatched_players"].append(
                        {"team": code, "source_player_name": name, "method": method}
                    )
                else:
                    coverage["players_matched"] += 1
            elements = [element for _, element, _, _ in matched if element is not None]
            complete = (
                len(source_names) == 11
                and len(elements) == 11
                and len(set(elements)) == 11
                and source_team.get("lineup_status") in {"predicted", "confirmed"}
            )
            coverage["complete_teams"] += int(complete)
            for name, element, method, score in matched:
                rows.append(
                    {
                        "season": SEASON,
                        "event": event,
                        "deadline_time": deadline.isoformat(),
                        "observed_at": observed.isoformat(),
                        "source_id": source_id,
                        "source_url": SOURCE_URLS.get(source_id, ""),
                        "source_updated_at": source_updated_at,
                        "source_freshness": source_freshness,
                        "source_team_code": code,
                        "team_id": team_id,
                        "team_short_name": str(team["short_name"]),
                        "fixture_id": fixture[0],
                        "opponent_team_id": fixture[1],
                        "lineup_status": str(source_team.get("lineup_status") or "unknown"),
                        "source_complete": complete,
                        "source_player_name": name,
                        "fpl_element": element,
                        "match_method": method,
                        "match_score": score,
                        "predicted_start": True,
                        "decision_eligible": observed < deadline and source_current,
                    }
                )
        source_coverage[source_id] = coverage
    return rows, {
        "event": event,
        "deadline_time": deadline.isoformat(),
        "decision_eligible": observed < deadline,
        "sources": source_coverage,
    }


def _official_status(player: Mapping[str, Any]) -> tuple[str, int]:
    chance = next(
        (
            int(player[field])
            for field in (
                "chance_of_playing_this_round",
                "chance_of_playing_next_round",
            )
            if player.get(field) is not None
        ),
        100 if player.get("status") == "a" else 0,
    )
    if (
        player.get("removed") is True
        or player.get("can_select") is False
        or player.get("status") == "u"
        or chance == 0
    ):
        return "unavailable", chance
    if player.get("status") != "a" or chance < 100 or str(player.get("news") or "").strip():
        return "doubt_or_news", chance
    return "clear", chance


def build_consensus_rows(
    observations: list[dict[str, Any]],
    *,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    forecasts: list[dict[str, Any]],
    event: int,
) -> list[dict[str, Any]]:
    team_name = {int(row["id"]): str(row["name"]) for row in teams}
    forecast_by_id = {
        int(row["element"]): row
        for row in forecasts
        if int(row.get("event_number") or -1) == event
    }
    positive: dict[int, set[str]] = defaultdict(set)
    complete_team_sources: dict[int, set[str]] = defaultdict(set)
    for row in observations:
        if not row["decision_eligible"]:
            continue
        if row["source_complete"]:
            complete_team_sources[int(row["team_id"])].add(str(row["source_id"]))
        if row.get("fpl_element") is not None:
            positive[int(row["fpl_element"])].add(str(row["source_id"]))

    result = []
    for player in players:
        element = int(player["id"])
        team_id = int(player["team"])
        start_sources = positive[element]
        eligible_sources = complete_team_sources[team_id]
        not_start_sources = eligible_sources - start_sources
        if len(start_sources) >= 2 and not not_start_sources:
            consensus = "predicted_start_consensus"
        elif len(not_start_sources) >= 2 and not start_sources:
            consensus = "predicted_bench_consensus"
        elif start_sources and not_start_sources:
            consensus = "source_disagreement"
        elif len(start_sources) == 1:
            consensus = "single_source_start"
        elif len(not_start_sources) == 1:
            consensus = "single_source_bench"
        else:
            consensus = "insufficient_coverage"
        official, chance = _official_status(player)
        attention = []
        if official == "unavailable":
            attention.append("official_unavailable")
        elif official == "doubt_or_news":
            attention.append("official_doubt_or_news")
        if consensus == "predicted_bench_consensus":
            attention.append("predicted_bench_consensus_shadow")
        elif consensus == "source_disagreement":
            attention.append("predicted_lineup_disagreement")
        forecast = forecast_by_id.get(element, {})
        p_start = (
            float(forecast.get("p_60_89") or 0.0)
            + float(forecast.get("p_90_or_more") or 0.0)
            if forecast
            else None
        )
        result.append(
            {
                "season": SEASON,
                "event": event,
                "element": element,
                "player_name": str(player.get("web_name") or player.get("second_name") or ""),
                "team_id": team_id,
                "team_name": team_name.get(team_id, str(team_id)),
                "position": str(forecast.get("position") or ""),
                "market_price": (
                    float(forecast["market_price"])
                    if forecast.get("market_price") is not None
                    else None
                ),
                "champion_expected_points": (
                    float(forecast["expected_points"])
                    if forecast.get("expected_points") is not None
                    else None
                ),
                "official_status": official,
                "official_chance": chance,
                "official_news": str(player.get("news") or ""),
                "predicted_start_sources": sorted(start_sources),
                "predicted_not_start_sources": sorted(not_start_sources),
                "complete_source_count": len(eligible_sources),
                "consensus": consensus,
                "attention": attention,
                "champion_p_play": (
                    float(forecast["p_play"]) if forecast.get("p_play") is not None else None
                ),
                "champion_p_start": p_start,
                "production_weight": 0.0,
                "production_adjustment_authorized": False,
            }
        )
    return result


def collect_participation_consensus(
    *,
    event: int | None = None,
    observed_at: str | datetime | None = None,
    players_path: Path = PLAYERS,
    teams_path: Path = TEAMS,
    events_path: Path = EVENTS,
    fixtures_path: Path = FIXTURES,
    forecast_path: Path = FORECAST,
    observations_path: Path = OBSERVATIONS,
    consensus_path: Path = CONSENSUS,
    receipt_path: Path = RECEIPT,
    archive_dir: Path = ARCHIVE_DIR,
    snapshot_dir: Path = SNAPSHOT_DIR,
    fetcher: Callable[[str], bytes] = _fetch_html,
) -> dict[str, Any]:
    """Capture two independent lineup feeds and freeze a zero-authority consensus."""
    ensure_layout()
    observed = _aware(observed_at or datetime.now(tz=UTC), "observed_at")
    for path, label in (
        (players_path, "official players"),
        (teams_path, "official teams"),
        (events_path, "official events"),
        (fixtures_path, "official fixtures"),
        (forecast_path, "production forecast"),
    ):
        if not path.is_file():
            raise ParticipationConsensusError(f"missing {label}: {path}")
    players = pq.read_table(players_path).to_pylist()
    teams = pq.read_table(teams_path).to_pylist()
    events = pq.read_table(events_path).to_pylist()
    fixtures = pq.read_table(fixtures_path).to_pylist()
    forecasts = pq.read_table(forecast_path).to_pylist()

    parsed = []
    source_receipts: dict[str, Any] = {}
    parsers = {
        "fantasy_football_scout": parse_ffscout_lineups,
        "rotowire": parse_rotowire_lineups,
    }
    for source_id, url in SOURCE_URLS.items():
        try:
            body = fetcher(url)
            archive = _archive(source_id, body, archive_dir)
            source = parsers[source_id](body)
            parsed.append(source)
            source_receipts[source_id] = {
                "status": "captured",
                "url": url,
                **archive,
                "source_updated_at": source.get("source_updated_at"),
                "teams_parsed": len(source.get("teams") or []),
            }
        except (
            OSError,
            ParticipationConsensusError,
            UnicodeError,
            ValueError,
            urllib.error.URLError,
        ) as exc:  # Network/source failure must not corrupt official evidence.
            source_receipts[source_id] = {
                "status": "unavailable",
                "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            }

    observations, context = normalize_source_lineups(
        parsed,
        players=players,
        teams=teams,
        fixtures=fixtures,
        events=events,
        observed_at=observed,
        event=event,
    )
    for source_id, coverage in context["sources"].items():
        if source_id in source_receipts:
            source_receipts[source_id]["source_freshness"] = coverage[
                "source_freshness"
            ]
            source_receipts[source_id]["decision_eligible"] = coverage[
                "decision_eligible"
            ]
    consensus_rows = build_consensus_rows(
        observations,
        players=players,
        teams=teams,
        forecasts=forecasts,
        event=int(context["event"]),
    )
    write_rows(observations, observations_path, schema=OBSERVATION_SCHEMA)
    write_rows(consensus_rows, consensus_path)

    snapshot_id = observed.strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = snapshot_dir / f"event-{context['event']}" / snapshot_id
    snapshot.mkdir(parents=True, exist_ok=True)
    snapshot_observations = snapshot / OBSERVATIONS.name
    snapshot_consensus = snapshot / CONSENSUS.name
    write_rows(observations, snapshot_observations, schema=OBSERVATION_SCHEMA)
    write_rows(consensus_rows, snapshot_consensus)

    summary = {
        "players": len(consensus_rows),
        "predicted_start_consensus": sum(
            row["consensus"] == "predicted_start_consensus" for row in consensus_rows
        ),
        "predicted_bench_consensus": sum(
            row["consensus"] == "predicted_bench_consensus" for row in consensus_rows
        ),
        "source_disagreement": sum(
            row["consensus"] == "source_disagreement" for row in consensus_rows
        ),
        "official_attention": sum(row["official_status"] != "clear" for row in consensus_rows),
    }
    receipt = {
        "version": VERSION,
        "season": SEASON,
        "event": context["event"],
        "observed_at": observed.isoformat(),
        "deadline_time": context["deadline_time"],
        "decision_eligible": context["decision_eligible"],
        "status": (
            "shadow_consensus_ready"
            if sum(
                value.get("status") == "captured" and value.get("decision_eligible")
                for value in source_receipts.values()
            )
            >= 2
            else "shadow_consensus_partial"
        ),
        "authority": {
            "official_fpl_status": "production",
            "predicted_lineup_consensus": "prospective_shadow",
            "production_weight": 0.0,
            "reason": (
                "No point-in-time historical archive with matching provenance exists. The feed "
                "must beat the frozen minute model prospectively before it can alter forecasts."
            ),
        },
        "promotion_gate": {
            "minimum_completed_events": 6,
            "requires_two_independent_sources": True,
            "requires_positive_lineup_hit_lift": True,
            "requires_non_negative_event_floor": True,
            "passed": False,
            "state": "awaiting_prospective_outcomes",
        },
        "sources": source_receipts,
        "coverage": context["sources"],
        "summary": summary,
        "inputs": {
            "official_players_sha256": sha256_file(players_path),
            "official_teams_sha256": sha256_file(teams_path),
            "official_events_sha256": sha256_file(events_path),
            "official_fixtures_sha256": sha256_file(fixtures_path),
            "forecast_sha256": sha256_file(forecast_path),
        },
        "outputs": {
            "observations_path": str(observations_path),
            "observations_sha256": sha256_file(observations_path),
            "consensus_path": str(consensus_path),
            "consensus_sha256": sha256_file(consensus_path),
            "snapshot_path": str(snapshot),
            "snapshot_observations_sha256": sha256_file(snapshot_observations),
            "snapshot_consensus_sha256": sha256_file(snapshot_consensus),
        },
    }
    _atomic_json(snapshot / "manifest.json", receipt)
    receipt["outputs"]["snapshot_manifest_sha256"] = sha256_file(
        snapshot / "manifest.json"
    )
    _atomic_json(receipt_path, receipt)
    return receipt


def latest_consensus_age(
    receipt: Mapping[str, Any], *, as_of: str | datetime
) -> timedelta:
    return _aware(as_of, "as_of") - _aware(str(receipt["observed_at"]), "observed_at")
