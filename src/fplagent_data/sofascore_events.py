from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .arrow import write_table
from .http import sha256_file
from .paths import MANIFESTS, PROCESSED, RAW, ensure_layout
from .preseason_lineups import match_sofascore_player, normalize_name

SOURCE_ID = "sofascore_public_web_api"
SOURCE_BASE = "https://www.sofascore.com/api/v1"
TOURNAMENT_ID = 17
SEASON = "2026-27"
RAW_ROOT = RAW / "supporting" / "sofascore" / "player-events"
OUT_ROOT = PROCESSED / "supporting" / "sofascore" / "player-events"
RECEIPT_ROOT = MANIFESTS / "sofascore-player-events"
CURRENT_RECEIPT = MANIFESTS / "sofascore-player-events-current.json"

# Stable, reviewed aliases. Name matching is always restricted to the already
# matched club, so a coincidentally similar name at another club cannot join.
TEAM_ALIASES = {
    "afc bournemouth": "bournemouth",
    "brighton & hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "ipswich town": "ipswich",
    "leeds united": "leeds",
    "leicester city": "leicester",
    "liverpool fc": "liverpool",
    "luton town": "luton",
    "manchester city": "man city",
    "manchester united": "man utd",
    "newcastle united": "newcastle",
    "nottingham forest": "nottm forest",
    "sheffield united": "sheffield utd",
    "tottenham hotspur": "spurs",
    "west ham united": "west ham",
    "wolverhampton": "wolves",
}

EVENT_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("source", pa.string()),
        ("source_season_id", pa.int64()),
        ("event_id", pa.int64()),
        ("round", pa.int16()),
        ("kickoff_time", pa.string()),
        ("available_after", pa.string()),
        ("home_source_team_id", pa.int64()),
        ("home_team_name", pa.string()),
        ("away_source_team_id", pa.int64()),
        ("away_team_name", pa.string()),
        ("home_score", pa.int16()),
        ("away_score", pa.int16()),
        ("status", pa.string()),
        ("lineup_confirmed", pa.bool_()),
    ]
)

PLAYER_EVENT_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("source", pa.string()),
        ("event_id", pa.int64()),
        ("round", pa.int16()),
        ("kickoff_time", pa.string()),
        ("available_after", pa.string()),
        ("home", pa.bool_()),
        ("source_team_id", pa.int64()),
        ("source_team_name", pa.string()),
        ("opponent_source_team_id", pa.int64()),
        ("opponent_name", pa.string()),
        ("source_player_id", pa.int64()),
        ("source_player_name", pa.string()),
        ("fpl_element", pa.int64()),
        ("mapping_method", pa.string()),
        ("mapping_score", pa.float64()),
        ("position", pa.string()),
        ("starter", pa.bool_()),
        ("substitute", pa.bool_()),
        ("minutes", pa.int16()),
        ("goals", pa.int16()),
        ("assists", pa.int16()),
        ("expected_goals", pa.float64()),
        ("expected_assists", pa.float64()),
        ("shots", pa.int16()),
        ("key_passes", pa.int16()),
        ("touches", pa.int16()),
        ("tackles", pa.int16()),
        ("interceptions", pa.int16()),
        ("clearances", pa.int16()),
        ("saves", pa.int16()),
        ("rating", pa.float64()),
    ]
)

MAPPING_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("source", pa.string()),
        ("source_team_id", pa.int64()),
        ("source_team_name", pa.string()),
        ("fpl_team_id", pa.int64()),
        ("source_player_id", pa.int64()),
        ("source_player_name", pa.string()),
        ("fpl_element", pa.int64()),
        ("mapping_method", pa.string()),
        ("mapping_score", pa.float64()),
        ("stable", pa.bool_()),
    ]
)


class SofaScoreEventError(ValueError):
    """The independent event feed could not be frozen without ambiguity."""


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _fetch_json(url: str) -> tuple[dict[str, Any], bytes]:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "--fail-with-body",
            "--retry",
            "3",
            "--retry-delay",
            "1",
            "--max-time",
            "60",
            "-H",
            "User-Agent: Mozilla/5.0",
            "-H",
            "Accept: application/json",
            url,
        ],
        check=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise SofaScoreEventError(f"SofaScore returned a non-object for {url}")
    return payload, result.stdout


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive(body: bytes, *, raw_root: Path) -> dict[str, Any]:
    digest = hashlib.sha256(body).hexdigest()
    path = raw_root / "archive" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    elif path.read_bytes() != body:
        raise SofaScoreEventError(f"immutable archive collision: {path}")
    return {"path": str(path), "sha256": digest, "bytes": len(body)}


def discover_season_id(payload: Mapping[str, Any], season: str) -> int:
    start, end = season.split("-", 1)
    wanted = {
        season.replace("-", "/"),
        f"{start[-2:]}/{end[-2:]}",
        start,
    }
    candidates = payload.get("seasons")
    if not isinstance(candidates, list):
        raise SofaScoreEventError("SofaScore season discovery returned no seasons")
    for row in candidates:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").replace("–", "/").replace("-", "/")
        year = str(row.get("year") or "").replace("–", "/").replace("-", "/")
        if wanted & {name, year}:
            return int(row["id"])
    raise SofaScoreEventError(f"SofaScore has no discoverable EPL season {season}")


def _team_key(value: str) -> str:
    normalized = normalize_name(value).replace("'", "")
    return TEAM_ALIASES.get(normalized, normalized)


def build_team_mapping(
    source_teams: Sequence[Mapping[str, Any]], fpl_teams: Sequence[Mapping[str, Any]]
) -> dict[int, int]:
    by_name: dict[str, list[int]] = defaultdict(list)
    for row in fpl_teams:
        for value in (row.get("name"), row.get("short_name")):
            if value:
                by_name[_team_key(str(value))].append(int(row["id"]))
    mapping: dict[int, int] = {}
    for row in source_teams:
        source_id = int(row["id"])
        hits = set(by_name.get(_team_key(str(row.get("name") or "")), []))
        if len(hits) != 1:
            raise SofaScoreEventError(
                f"team mapping for {row.get('name')!r} is {'ambiguous' if hits else 'missing'}"
            )
        mapping[source_id] = hits.pop()
    return mapping


def build_stable_player_mapping(
    player_rows: Sequence[Mapping[str, Any]],
    *,
    fpl_players: Sequence[Mapping[str, Any]],
    team_mapping: Mapping[int, int],
    prior_mapping: Sequence[Mapping[str, Any]] = (),
    season: str = SEASON,
) -> list[dict[str, Any]]:
    candidates: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in fpl_players:
        candidates[int(row["team"])].append(dict(row))
    prior = {
        int(row["source_player_id"]): int(row["fpl_element"])
        for row in prior_mapping
        if row.get("fpl_element") is not None and row.get("stable", True)
    }
    identities: dict[int, Mapping[str, Any]] = {}
    for row in player_rows:
        identities.setdefault(int(row["source_player_id"]), row)
    output = []
    for source_player_id, row in sorted(identities.items()):
        source_team_id = int(row["source_team_id"])
        fpl_team = team_mapping.get(source_team_id)
        if fpl_team is None:
            element, method, score = None, "unmapped_team", None
        elif source_player_id in prior:
            element, method, score = prior[source_player_id], "stable_provider_id", 1.0
            if not any(int(value["id"]) == element for value in candidates[fpl_team]):
                raise SofaScoreEventError(
                    f"stable mapping moved player {source_player_id} to a different club"
                )
        else:
            element, method, score = match_sofascore_player(
                str(row["source_player_name"]), candidates[fpl_team]
            )
        output.append(
            {
                "season": season,
                "source": SOURCE_ID,
                "source_team_id": source_team_id,
                "source_team_name": str(row["source_team_name"]),
                "fpl_team_id": fpl_team,
                "source_player_id": source_player_id,
                "source_player_name": str(row["source_player_name"]),
                "fpl_element": element,
                "mapping_method": method,
                "mapping_score": score,
                "stable": element is not None,
            }
        )
    return output


def parse_finished_event(
    event: Mapping[str, Any],
    lineup: Mapping[str, Any],
    *,
    season: str,
    source_season_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    event_id = int(event["id"])
    kickoff = datetime.fromtimestamp(int(event["startTimestamp"]), UTC)
    # Historical feature rows become legal only after the match is safely over.
    available_after = kickoff + timedelta(hours=3)
    home = event["homeTeam"]
    away = event["awayTeam"]
    event_row = {
        "season": season,
        "source": SOURCE_ID,
        "source_season_id": source_season_id,
        "event_id": event_id,
        "round": _integer((event.get("roundInfo") or {}).get("round")),
        "kickoff_time": kickoff.isoformat(),
        "available_after": available_after.isoformat(),
        "home_source_team_id": int(home["id"]),
        "home_team_name": str(home["name"]),
        "away_source_team_id": int(away["id"]),
        "away_team_name": str(away["name"]),
        "home_score": _integer((event.get("homeScore") or {}).get("current")),
        "away_score": _integer((event.get("awayScore") or {}).get("current")),
        "status": str((event.get("status") or {}).get("type") or ""),
        "lineup_confirmed": bool(lineup.get("confirmed")),
    }
    rows: list[dict[str, Any]] = []
    for side, is_home in (("home", True), ("away", False)):
        team = home if is_home else away
        opponent = away if is_home else home
        for item in (lineup.get(side) or {}).get("players", []):
            player = item.get("player") or {}
            if player.get("id") is None:
                continue
            stats = item.get("statistics") or {}
            rows.append(
                {
                    "season": season,
                    "source": SOURCE_ID,
                    "event_id": event_id,
                    "round": event_row["round"],
                    "kickoff_time": event_row["kickoff_time"],
                    "available_after": event_row["available_after"],
                    "home": is_home,
                    "source_team_id": int(team["id"]),
                    "source_team_name": str(team["name"]),
                    "opponent_source_team_id": int(opponent["id"]),
                    "opponent_name": str(opponent["name"]),
                    "source_player_id": int(player["id"]),
                    "source_player_name": str(player.get("name") or ""),
                    "fpl_element": None,
                    "mapping_method": "unmapped",
                    "mapping_score": None,
                    "position": str(player.get("position") or ""),
                    "starter": not bool(item.get("substitute")),
                    "substitute": bool(item.get("substitute")),
                    "minutes": _integer(stats.get("minutesPlayed")),
                    "goals": _integer(stats.get("goals")),
                    "assists": _integer(stats.get("goalAssist")),
                    "expected_goals": _number(stats.get("expectedGoals")),
                    "expected_assists": _number(stats.get("expectedAssists")),
                    "shots": _integer(stats.get("totalShots")),
                    "key_passes": _integer(stats.get("keyPass")),
                    "touches": _integer(stats.get("touches")),
                    "tackles": _integer(stats.get("totalTackle")),
                    "interceptions": _integer(stats.get("interceptionWon")),
                    "clearances": _integer(stats.get("totalClearance")),
                    "saves": _integer(stats.get("saves")),
                    "rating": _number(stats.get("rating")),
                }
            )
    return event_row, rows


def point_in_time_folds(
    rows: Sequence[Mapping[str, Any]], deadlines: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Return auditable folds in which every training row predates the target deadline."""
    parsed_rows = [(datetime.fromisoformat(str(row["available_after"])), row) for row in rows]
    folds = []
    for target in sorted(deadlines, key=lambda row: (str(row["season"]), int(row["event"]))):
        deadline = datetime.fromisoformat(str(target["deadline_time"]))
        if deadline.tzinfo is None:
            raise SofaScoreEventError("deadline_time must include a timezone")
        eligible = [row for available, row in parsed_rows if available < deadline]
        leakage = [
            row for available, row in parsed_rows if row in eligible and available >= deadline
        ]
        folds.append(
            {
                "season": str(target["season"]),
                "event": int(target["event"]),
                "deadline_time": deadline.isoformat(),
                "training_rows": len(eligible),
                "maximum_available_after": max(
                    (str(row["available_after"]) for row in eligible), default=None
                ),
                "leakage_rows": len(leakage),
                "passed": not leakage,
            }
        )
    return folds


def collect_sofascore_player_events(
    *,
    season: str = SEASON,
    fpl_players_path: Path | None = None,
    fpl_teams_path: Path | None = None,
    observed_at: str | datetime | None = None,
    fetcher: Callable[[str], tuple[dict[str, Any], bytes]] = _fetch_json,
    raw_root: Path = RAW_ROOT,
    out_root: Path = OUT_ROOT,
    receipt_root: Path = RECEIPT_ROOT,
    current_receipt: Path = CURRENT_RECEIPT,
) -> dict[str, Any]:
    ensure_layout()
    observed = (
        observed_at
        if isinstance(observed_at, datetime)
        else datetime.fromisoformat(observed_at)
        if observed_at
        else datetime.now(UTC)
    )
    if observed.tzinfo is None:
        raise SofaScoreEventError("observed_at must include a timezone")
    observed = observed.astimezone(UTC)
    if season == SEASON:
        fpl_dir = PROCESSED / "fpl" / season / "preseason"
        players_path = fpl_players_path or fpl_dir / "players.parquet"
        teams_path = fpl_teams_path or fpl_dir / "teams.parquet"
    else:
        players_path = fpl_players_path or PROCESSED / "vaastav" / "players.parquet"
        teams_path = fpl_teams_path or PROCESSED / "vaastav" / "teams.parquet"
    fpl_players = [
        row
        for row in pq.read_table(players_path).to_pylist()
        if row.get("season") in (None, season)
    ]
    fpl_teams = [
        row for row in pq.read_table(teams_path).to_pylist() if row.get("season") in (None, season)
    ]
    if not fpl_players or not fpl_teams:
        raise SofaScoreEventError(f"no FPL identity rows exist for {season}")
    requests = []

    seasons_url = f"{SOURCE_BASE}/unique-tournament/{TOURNAMENT_ID}/seasons"
    seasons_payload, body = fetcher(seasons_url)
    requests.append({"url": seasons_url, **_archive(body, raw_root=raw_root)})
    source_season_id = discover_season_id(seasons_payload, season)
    events: dict[int, dict[str, Any]] = {}
    page = 0
    while True:
        future_probe = False
        url = (
            f"{SOURCE_BASE}/unique-tournament/{TOURNAMENT_ID}/season/"
            f"{source_season_id}/events/last/{page}"
        )
        try:
            payload, body = fetcher(url)
        except subprocess.CalledProcessError:
            if page != 0:
                raise
            # Before the first match SofaScore has no `last` page. A successful
            # `next` response still proves the live season endpoint and schema.
            url = (
                f"{SOURCE_BASE}/unique-tournament/{TOURNAMENT_ID}/season/"
                f"{source_season_id}/events/next/0"
            )
            payload, body = fetcher(url)
            future_probe = True
        requests.append({"url": url, **_archive(body, raw_root=raw_root)})
        for event in payload.get("events") or []:
            if (event.get("status") or {}).get("type") == "finished":
                events[int(event["id"])] = event
        if future_probe or not payload.get("hasNextPage"):
            break
        page += 1
        if page > 20:
            raise SofaScoreEventError("SofaScore pagination exceeded 20 pages")

    event_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    for event_id, event in sorted(events.items()):
        url = f"{SOURCE_BASE}/event/{event_id}/lineups"
        lineup, body = fetcher(url)
        requests.append({"url": url, **_archive(body, raw_root=raw_root)})
        event_row, parsed = parse_finished_event(
            event, lineup, season=season, source_season_id=source_season_id
        )
        event_rows.append(event_row)
        player_rows.extend(parsed)

    source_teams: dict[int, dict[str, Any]] = {}
    for row in player_rows:
        source_teams[int(row["source_team_id"])] = {
            "id": int(row["source_team_id"]),
            "name": str(row["source_team_name"]),
        }
    team_mapping = (
        build_team_mapping(list(source_teams.values()), fpl_teams) if source_teams else {}
    )
    season_out = out_root / season
    mapping_path = season_out / "player_mapping.parquet"
    prior_mapping = pq.read_table(mapping_path).to_pylist() if mapping_path.is_file() else []
    mapping_rows = build_stable_player_mapping(
        player_rows,
        fpl_players=fpl_players,
        team_mapping=team_mapping,
        prior_mapping=prior_mapping,
        season=season,
    )
    by_source = {int(row["source_player_id"]): row for row in mapping_rows}
    for row in player_rows:
        mapped = by_source[int(row["source_player_id"])]
        row.update(
            {
                "fpl_element": mapped["fpl_element"],
                "mapping_method": mapped["mapping_method"],
                "mapping_score": mapped["mapping_score"],
            }
        )

    events_path = season_out / "events.parquet"
    player_events_path = season_out / "player_events.parquet"
    write_table(pa.Table.from_pylist(event_rows, schema=EVENT_SCHEMA), events_path)
    write_table(pa.Table.from_pylist(player_rows, schema=PLAYER_EVENT_SCHEMA), player_events_path)
    write_table(pa.Table.from_pylist(mapping_rows, schema=MAPPING_SCHEMA), mapping_path)
    observation_id = observed.strftime("%Y%m%dT%H%M%SZ")
    receipt_path = receipt_root / season / f"{observation_id}.json"
    mapped = sum(row["fpl_element"] is not None for row in mapping_rows)
    receipt = {
        "receipt_version": 1,
        "source": SOURCE_ID,
        "season": season,
        "source_season_id": source_season_id,
        "observed_at": observed.isoformat(),
        "current": True,
        "finished_events": len(event_rows),
        "player_event_rows": len(player_rows),
        "mapping": {
            "players": len(mapping_rows),
            "mapped": mapped,
            "rate": mapped / len(mapping_rows) if mapping_rows else None,
            "ambiguous_or_unmatched": len(mapping_rows) - mapped,
            "fail_closed": True,
        },
        "point_in_time": {
            "available_after_rule": "kickoff plus three hours",
            "future_rows_allowed": False,
        },
        "requests": requests,
        "outputs": {
            "events": str(events_path),
            "events_sha256": sha256_file(events_path),
            "player_events": str(player_events_path),
            "player_events_sha256": sha256_file(player_events_path),
            "player_mapping": str(mapping_path),
            "player_mapping_sha256": sha256_file(mapping_path),
        },
        "production_authority": False,
        "promotion_requirement": (
            "Must improve a timestamp-safe legal-policy replay and then pass prospective monitoring."
        ),
    }
    _atomic_json(receipt_path, receipt)
    if season == SEASON:
        _atomic_json(current_receipt, {**receipt, "receipt_path": str(receipt_path)})
    return receipt
