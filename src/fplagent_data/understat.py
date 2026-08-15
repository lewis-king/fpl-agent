from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .arrow import write_rows
from .http import sha256_file
from .paths import MANIFESTS, PROCESSED, RAW

PROVIDER = "Understat"
LEAGUE = "EPL"
BASE_URL = "https://understat.com"
RAW_ROOT = RAW / "understat" / LEAGUE
PROCESSED_ROOT = PROCESSED / "understat" / LEAGUE


class UnderstatDataError(ValueError):
    """A public Understat response is missing or structurally unsafe."""


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value: Any, *, integer: bool = False) -> int | float:
    if value in (None, ""):
        return 0 if integer else 0.0
    return int(value) if integer else float(value)


def _nullable_number(value: Any, *, integer: bool = False) -> int | float | None:
    if value in (None, ""):
        return None
    return int(value) if integer else float(value)


def validate_league_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnderstatDataError("Understat league data must be one JSON object")
    if not isinstance(value.get("players"), list) or not value["players"]:
        raise UnderstatDataError("Understat league data has no players")
    if not isinstance(value.get("teams"), dict) or not value["teams"]:
        raise UnderstatDataError("Understat league data has no teams")
    if not isinstance(value.get("dates"), list) or not value["dates"]:
        raise UnderstatDataError("Understat league data has no fixtures")
    required_player = {"id", "player_name", "games", "time", "xG", "xA", "team_title"}
    if any(required_player - set(row) for row in value["players"]):
        raise UnderstatDataError("Understat player rows changed schema")
    required_fixture = {"id", "h", "a", "datetime", "isResult"}
    if any(required_fixture - set(row) for row in value["dates"]):
        raise UnderstatDataError("Understat fixture rows changed schema")
    return value


def normalize_league_payload(
    payload: dict[str, Any],
    *,
    season_start: int,
    observed_at: str,
) -> dict[str, list[dict[str, Any]]]:
    value = validate_league_payload(payload)
    common = {
        "provider": PROVIDER,
        "competition": LEAGUE,
        "source_season_start": int(season_start),
        "observed_at": observed_at,
    }
    players = []
    for row in value["players"]:
        players.append(
            {
                **common,
                "understat_player_id": int(row["id"]),
                "player_name": str(row["player_name"]),
                "team_title": str(row["team_title"]),
                "position": str(row.get("position") or ""),
                "games": _number(row.get("games"), integer=True),
                "minutes": _number(row.get("time"), integer=True),
                "goals": _number(row.get("goals"), integer=True),
                "non_penalty_goals": _number(row.get("npg"), integer=True),
                "assists": _number(row.get("assists"), integer=True),
                "shots": _number(row.get("shots"), integer=True),
                "key_passes": _number(row.get("key_passes"), integer=True),
                "yellow_cards": _number(row.get("yellow_cards"), integer=True),
                "red_cards": _number(row.get("red_cards"), integer=True),
                "xg": _number(row.get("xG")),
                "npxg": _number(row.get("npxG")),
                "xa": _number(row.get("xA")),
                "xg_chain": _number(row.get("xGChain")),
                "xg_buildup": _number(row.get("xGBuildup")),
            }
        )
    team_matches = []
    for team in value["teams"].values():
        for row in team.get("history") or []:
            ppda = row.get("ppda") or {}
            ppda_allowed = row.get("ppda_allowed") or {}
            team_matches.append(
                {
                    **common,
                    "understat_team_id": int(team["id"]),
                    "team_name": str(team["title"]),
                    "kickoff_time": str(row["date"]),
                    "home_away": str(row["h_a"]),
                    "xg": _number(row.get("xG")),
                    "xga": _number(row.get("xGA")),
                    "npxg": _number(row.get("npxG")),
                    "npxga": _number(row.get("npxGA")),
                    "deep": _number(row.get("deep"), integer=True),
                    "deep_allowed": _number(row.get("deep_allowed"), integer=True),
                    "ppda_att": _number(ppda.get("att"), integer=True),
                    "ppda_def": _number(ppda.get("def"), integer=True),
                    "ppda_allowed_att": _number(ppda_allowed.get("att"), integer=True),
                    "ppda_allowed_def": _number(ppda_allowed.get("def"), integer=True),
                    "goals_for": _number(row.get("scored"), integer=True),
                    "goals_against": _number(row.get("missed"), integer=True),
                    "expected_points": _number(row.get("xpts")),
                    "result": str(row.get("result") or ""),
                }
            )
    fixtures = []
    for row in value["dates"]:
        forecast = row.get("forecast") or {}
        goals = row.get("goals") or {}
        expected = row.get("xG") or {}
        fixtures.append(
            {
                **common,
                "understat_fixture_id": int(row["id"]),
                "kickoff_time": str(row["datetime"]),
                "is_result": bool(row["isResult"]),
                "home_team_id": int(row["h"]["id"]),
                "home_team": str(row["h"]["title"]),
                "away_team_id": int(row["a"]["id"]),
                "away_team": str(row["a"]["title"]),
                "home_goals": _nullable_number(goals.get("h"), integer=True),
                "away_goals": _nullable_number(goals.get("a"), integer=True),
                "home_xg": _nullable_number(expected.get("h")),
                "away_xg": _nullable_number(expected.get("a")),
                "forecast_home_win": _nullable_number(forecast.get("w")),
                "forecast_draw": _nullable_number(forecast.get("d")),
                "forecast_away_win": _nullable_number(forecast.get("l")),
            }
        )
    return {"players": players, "team_matches": team_matches, "fixtures": fixtures}


def _fetch_payload(season_start: int) -> tuple[dict[str, Any], dict[str, str | int | None]]:
    url = f"{BASE_URL}/getLeagueData/{LEAGUE}/{season_start}/"
    headers = {
        "User-Agent": "fplagent-data/0.1 (public-data research)",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/league/{LEAGUE}/{season_start}",
    }
    response = httpx.get(url, headers=headers, timeout=60.0, follow_redirects=True)
    response.raise_for_status()
    payload = validate_league_payload(response.json())
    return payload, {
        "url": url,
        "http_status": response.status_code,
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
        "content_length": len(response.content),
        "content_sha256": hashlib.sha256(response.content).hexdigest(),
    }


def collect_understat_season(
    season_start: int,
    *,
    observed_at: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not 2014 <= season_start <= datetime.now(UTC).year:
        raise ValueError("Understat EPL season_start is outside the supported range")
    observed = observed_at or datetime.now(UTC).isoformat()
    manifest_path = MANIFESTS / f"understat-{LEAGUE}-{season_start}.json"
    cached = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file() and not force
        else None
    )
    raw_path = Path(str((cached or {}).get("raw", {}).get("path") or ""))
    if cached is not None and raw_path.is_file():
        payload = validate_league_payload(json.loads(raw_path.read_text(encoding="utf-8")))
        source = cached["source"]
    else:
        payload, source = _fetch_payload(season_start)
        raw_path = RAW_ROOT / str(season_start) / f"{source['content_sha256']}.json"
        if not raw_path.is_file():
            _atomic_json(raw_path, payload)
    normalized = normalize_league_payload(
        payload,
        season_start=season_start,
        observed_at=observed,
    )
    output_dir = PROCESSED_ROOT / str(season_start)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        name: output_dir / f"{name.replace('_', '-')}.parquet" for name in normalized
    }
    counts = {name: write_rows(rows, paths[name]) for name, rows in normalized.items()}
    receipt = {
        "receipt_version": 1,
        "provider": PROVIDER,
        "competition": LEAGUE,
        "source_season_start": season_start,
        "observed_at": observed,
        "source": source,
        "raw": {"path": str(raw_path), "sha256": sha256_file(raw_path)},
        "processed": {
            name: {"path": str(path), "sha256": sha256_file(path), "rows": counts[name]}
            for name, path in paths.items()
        },
        "authority": "external_feature_challenger_only_until_time_forward_gate_passes",
    }
    _atomic_json(manifest_path, receipt)
    return receipt
