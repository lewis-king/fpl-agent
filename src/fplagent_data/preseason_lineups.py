from __future__ import annotations

import hashlib
import json
import math
import subprocess
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .arrow import write_table
from .http import sha256_file
from .paths import MANIFESTS, PROCESSED, RAW, ensure_layout

SEASON = "2026-27"
SOURCE_BASE = "https://www.sofascore.com/api/v1"
RAW_DIR = RAW / "supporting" / "sofascore" / SEASON / "preseason"
ARCHIVE_DIR = RAW_DIR / "archive"
OUT_DIR = PROCESSED / "supporting" / "sofascore" / SEASON
EVENTS_OUT = OUT_DIR / "preseason_events.parquet"
LINEUPS_OUT = OUT_DIR / "preseason_lineups.parquet"
ROLE_EVIDENCE_OUT = OUT_DIR / "preseason_role_evidence.parquet"
RECEIPT = MANIFESTS / "preseason_lineups_current.json"
FPL_DIR = PROCESSED / "fpl" / SEASON / "preseason"

# Season-specific IDs verified against SofaScore search results on 7 August 2026.
SOFASCORE_TEAM_IDS = {
    1: 42,
    2: 40,
    3: 60,
    4: 50,
    5: 30,
    6: 38,
    7: 11,
    8: 7,
    9: 48,
    10: 43,
    11: 96,
    12: 32,
    13: 34,
    14: 44,
    15: 17,
    16: 35,
    17: 39,
    18: 14,
    19: 33,
    20: 41,
}

# Small, season-specific aliases verified directly against the source lineup and FPL
# player records. Keep this explicit: broad nickname expansion risks joining academy
# players to similarly named senior players.
VERIFIED_SOURCE_ALIASES = {
    10: {"ben white"},
}


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(
        unaccented.casefold()
        .replace("ø", "o")
        .replace("ð", "d")
        .replace("-", " ")
        .split()
    )


def fpl_role_mapping_fingerprint(
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    """Hash only FPL fields that can change lineup discovery or player matching."""
    payload = {
        "teams": sorted(
            [
                {
                    "id": int(row["id"]),
                    "name": str(row.get("name") or ""),
                    "short_name": str(row.get("short_name") or ""),
                }
                for row in teams
            ],
            key=lambda row: row["id"],
        ),
        "players": sorted(
            [
                {
                    field: row.get(field)
                    for field in (
                        "id",
                        "code",
                        "team",
                        "first_name",
                        "second_name",
                        "web_name",
                        "known_name",
                        "team_join_date",
                    )
                }
                for row in players
            ],
            key=lambda row: int(row["id"]),
        ),
        "events": sorted(
            [
                {
                    "id": int(row["id"]),
                    "deadline_time": row.get("deadline_time"),
                }
                for row in events
            ],
            key=lambda row: row["id"],
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _player_aliases(player: dict[str, Any]) -> set[str]:
    first = str(player.get("first_name") or "").strip()
    second = str(player.get("second_name") or "").strip()
    web = str(player.get("web_name") or "").strip()
    known = str(player.get("known_name") or "").strip()
    aliases = {
        first,
        second,
        web,
        known,
        f"{first} {second}",
        f"{second} {first}",
        f"{first} {web}",
    }
    if first and second:
        aliases.add(f"{first.split()[0]} {second.split()[0]}")
    aliases.update(VERIFIED_SOURCE_ALIASES.get(int(player["id"]), set()))
    return {normalize_name(alias) for alias in aliases if len(normalize_name(alias)) >= 4}


def _contains_multi_token_alias(left: str, right: str) -> bool:
    left_tokens = left.split()
    right_tokens = right.split()
    if min(len(left_tokens), len(right_tokens)) < 2:
        return False
    shorter, longer = (
        (left_tokens, right_tokens)
        if len(left_tokens) <= len(right_tokens)
        else (right_tokens, left_tokens)
    )
    width = len(shorter)
    return any(longer[index : index + width] == shorter for index in range(len(longer) - width + 1))


def match_sofascore_player(
    name: str, candidates: list[dict[str, Any]]
) -> tuple[int | None, str, float | None]:
    normalized = normalize_name(name)
    exact = [player for player in candidates if normalized in _player_aliases(player)]
    if len(exact) == 1:
        return int(exact[0]["id"]), "exact_alias", 1.0
    if len(exact) > 1:
        return None, "ambiguous_exact_alias", 1.0

    contained = [
        player
        for player in candidates
        if any(
            _contains_multi_token_alias(normalized, alias)
            for alias in _player_aliases(player)
        )
    ]
    if len(contained) == 1:
        return int(contained[0]["id"]), "unique_token_containment", 1.0
    if len(contained) > 1:
        return None, "ambiguous_token_containment", 1.0

    scores = []
    for player in candidates:
        aliases = _player_aliases(player)
        score = max(
            (SequenceMatcher(None, normalized, alias).ratio() for alias in aliases),
            default=0.0,
        )
        scores.append((score, int(player["id"])))
    scores.sort(reverse=True)
    if not scores:
        return None, "no_candidates", None
    best_score, best_id = scores[0]
    next_score = scores[1][0] if len(scores) > 1 else 0.0
    if best_score >= 0.86 and best_score - next_score >= 0.06:
        return best_id, "conservative_fuzzy", float(best_score)
    return None, "unmatched", float(best_score)


def filter_preseason_events(
    payload: dict[str, Any], *, start_timestamp: int, deadline_timestamp: int
) -> list[dict[str, Any]]:
    return [
        event
        for event in payload.get("events", [])
        if event.get("status", {}).get("type") == "finished"
        and start_timestamp <= int(event.get("startTimestamp") or 0) < deadline_timestamp
    ]


def parse_lineup_side(
    payload: dict[str, Any],
    *,
    side: str,
    event: dict[str, Any],
    fpl_team_id: int,
    sofascore_team_id: int,
    candidates: list[dict[str, Any]],
    observed_at: str,
) -> list[dict[str, Any]]:
    rows = []
    for item in payload.get(side, {}).get("players", []):
        player = item.get("player") or {}
        name = str(player.get("name") or "").strip()
        element, method, score = match_sofascore_player(name, candidates)
        statistics = item.get("statistics") or {}
        minutes = statistics.get("minutesPlayed")
        substitute = bool(item.get("substitute"))
        starter = not substitute
        rows.append(
            {
                "season": SEASON,
                "observed_at": observed_at,
                "source": "sofascore_public_web_api",
                "event_id": int(event["id"]),
                "kickoff_time": datetime.fromtimestamp(
                    int(event["startTimestamp"]), UTC
                ).isoformat(),
                "tournament": str(event.get("tournament", {}).get("name") or ""),
                "confirmed": bool(payload.get("confirmed")),
                "side": side,
                "fpl_team_id": fpl_team_id,
                "sofascore_team_id": sofascore_team_id,
                "opponent_name": str(
                    event["awayTeam" if side == "home" else "homeTeam"]["name"]
                ),
                "sofascore_player_id": (
                    int(player["id"]) if player.get("id") is not None else None
                ),
                "sofascore_player_name": name,
                "fpl_element": element,
                "match_method": method,
                "match_score": score,
                "shirt_number": (
                    int(item["shirtNumber"]) if item.get("shirtNumber") is not None else None
                ),
                "starter": starter,
                "substitute": substitute,
                "minutes": int(minutes) if minutes is not None else None,
                "appeared": starter or (minutes is not None and int(minutes) > 0),
            }
        )
    return rows


def _curl_json(url: str) -> tuple[dict[str, Any] | None, bytes, int]:
    result = subprocess.run(
        [
            "curl",
            "-sS",
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
            "-w",
            "\n%{http_code}",
            url,
        ],
        check=True,
        capture_output=True,
    )
    body, status_text = result.stdout.rsplit(b"\n", 1)
    status = int(status_text)
    return (json.loads(body) if status == 200 else None), body, status


def _archive(url: str, body: bytes, status: int) -> dict[str, Any]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body).hexdigest()
    path = ARCHIVE_DIR / f"{digest}.json"
    if not path.exists():
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    return {
        "url": url,
        "status": status,
        "bytes": len(body),
        "sha256": digest,
        "archive_path": str(path),
    }


def _event_side_row(
    event: dict[str, Any], *, fpl_team_id: int, sofascore_team_id: int, observed_at: str
) -> dict[str, Any]:
    home = int(event["homeTeam"]["id"]) == sofascore_team_id
    return {
        "season": SEASON,
        "observed_at": observed_at,
        "source": "sofascore_public_web_api",
        "event_id": int(event["id"]),
        "kickoff_time": datetime.fromtimestamp(int(event["startTimestamp"]), UTC).isoformat(),
        "tournament": str(event.get("tournament", {}).get("name") or ""),
        "fpl_team_id": fpl_team_id,
        "sofascore_team_id": sofascore_team_id,
        "home": home,
        "opponent_sofascore_team_id": int(
            event["awayTeam" if home else "homeTeam"]["id"]
        ),
        "opponent_name": str(event["awayTeam" if home else "homeTeam"]["name"]),
        "status": str(event.get("status", {}).get("type") or ""),
    }


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def build_role_evidence(
    players: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    lineup_rows: list[dict[str, Any]],
    *,
    deadline: datetime,
    observed_at: str,
) -> list[dict[str, Any]]:
    events_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        events_by_team[int(row["fpl_team_id"])].append(row)
    lineup_by_player: dict[tuple[int, int], dict[str, Any]] = {}
    for row in lineup_rows:
        if row["fpl_element"] is not None:
            lineup_by_player[(int(row["event_id"]), int(row["fpl_element"]))] = row

    output = []
    for player in players:
        element = int(player["id"])
        team_id = int(player["team"])
        join_date = _parse_date(player.get("team_join_date"))
        eligible = [
            event
            for event in events_by_team.get(team_id, [])
            if join_date is None
            or datetime.fromisoformat(str(event["kickoff_time"])) >= join_date
        ]
        eligible.sort(key=lambda row: str(row["kickoff_time"]))
        weights = [
            math.exp(
                -max(
                    (deadline - datetime.fromisoformat(str(event["kickoff_time"]))).days,
                    0,
                )
                / 14.0
            )
            for event in eligible
        ]
        observations = [lineup_by_player.get((int(event["event_id"]), element)) for event in eligible]
        total_weight = sum(weights)
        starts = sum(int(row is not None and row["starter"]) for row in observations)
        appearances = sum(int(row is not None and row["appeared"]) for row in observations)
        listings = sum(int(row is not None) for row in observations)
        known_minutes = sum(
            int(row["minutes"])
            for row in observations
            if row is not None and row["minutes"] is not None
        )
        minutes_observations = sum(
            int(row is not None and row["minutes"] is not None) for row in observations
        )
        minutes_data_complete = all(
            row is None or row["minutes"] is not None for row in observations
        )
        minutes = known_minutes if minutes_data_complete else None
        last = observations[-1] if observations else None
        output.append(
            {
                "season": SEASON,
                "observed_at": observed_at,
                "source": "sofascore_public_web_api",
                "fpl_element": element,
                "player_code": int(player["code"]),
                "player_name": str(player["web_name"]),
                "fpl_team_id": team_id,
                "team_join_date": player.get("team_join_date"),
                "eligible_team_matches": len(eligible),
                "squad_listings": listings,
                "starts": starts,
                "appearances": appearances,
                "minutes": minutes,
                "known_minutes": known_minutes,
                "minutes_observations": minutes_observations,
                "minutes_data_complete": minutes_data_complete,
                "squad_share": listings / len(eligible) if eligible else None,
                "start_share": starts / len(eligible) if eligible else None,
                "appearance_share": appearances / len(eligible) if eligible else None,
                "minutes_per_team_match": (
                    minutes / len(eligible)
                    if eligible and minutes is not None
                    else None
                ),
                "recency_weighted_start_share": (
                    sum(
                        weight * int(row is not None and row["starter"])
                        for weight, row in zip(weights, observations, strict=True)
                    )
                    / total_weight
                    if total_weight
                    else None
                ),
                "recency_weighted_appearance_share": (
                    sum(
                        weight * int(row is not None and row["appeared"])
                        for weight, row in zip(weights, observations, strict=True)
                    )
                    / total_weight
                    if total_weight
                    else None
                ),
                "last_team_event_id": int(eligible[-1]["event_id"]) if eligible else None,
                "last_match_listed": last is not None if observations else None,
                "last_match_started": bool(last["starter"]) if last is not None else None,
                "last_match_minutes": (
                    int(last["minutes"])
                    if last is not None and last["minutes"] is not None
                    else None
                ),
                "evidence_status": (
                    "no_confirmed_team_lineups"
                    if not eligible
                    else "observed_in_lineup"
                    if listings
                    else "not_listed_in_eligible_lineups"
                ),
            }
        )
    return output


def collect_preseason_lineups() -> dict[str, Any]:
    ensure_layout()
    observed_at = datetime.now(UTC).isoformat()
    teams = pq.read_table(FPL_DIR / "teams.parquet").to_pylist()
    players = pq.read_table(FPL_DIR / "players.parquet").to_pylist()
    events = pq.read_table(FPL_DIR / "events.parquet").to_pylist()
    if {int(team["id"]) for team in teams} != set(SOFASCORE_TEAM_IDS):
        raise ValueError("current FPL teams do not match the verified SofaScore mapping")
    deadline = datetime.fromisoformat(
        next(str(event["deadline_time"]) for event in events if int(event["id"]) == 1)
    )
    start = datetime(2026, 6, 1, tzinfo=UTC)
    inverse_team = {value: key for key, value in SOFASCORE_TEAM_IDS.items()}
    requests = []
    discovered: dict[int, dict[str, Any]] = {}
    event_rows_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for fpl_team_id, sofascore_team_id in SOFASCORE_TEAM_IDS.items():
        url = f"{SOURCE_BASE}/team/{sofascore_team_id}/events/last/0"
        payload, body, status = _curl_json(url)
        requests.append(_archive(url, body, status))
        if payload is None:
            raise RuntimeError(f"SofaScore team events request failed: {url} ({status})")
        for event in filter_preseason_events(
            payload,
            start_timestamp=int(start.timestamp()),
            deadline_timestamp=int(deadline.timestamp()),
        ):
            discovered[int(event["id"])] = event
            for side in ("home", "away"):
                event_sofascore_team_id = int(event[f"{side}Team"]["id"])
                event_fpl_team_id = inverse_team.get(event_sofascore_team_id)
                if event_fpl_team_id is None:
                    continue
                event_rows_by_key[(int(event["id"]), event_fpl_team_id)] = (
                    _event_side_row(
                        event,
                        fpl_team_id=event_fpl_team_id,
                        sofascore_team_id=event_sofascore_team_id,
                        observed_at=observed_at,
                    )
                )

    candidates_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        candidates_by_team[int(player["team"])].append(player)
    lineup_rows = []
    missing_lineups = []
    confirmed_events = set()
    for event_id, event in sorted(discovered.items()):
        url = f"{SOURCE_BASE}/event/{event_id}/lineups"
        payload, body, status = _curl_json(url)
        requests.append(_archive(url, body, status))
        if payload is None or not payload.get("confirmed"):
            missing_lineups.append({"event_id": event_id, "status": status})
            continue
        confirmed_events.add(event_id)
        for side in ("home", "away"):
            sofascore_team_id = int(event[f"{side}Team"]["id"])
            fpl_team_id = inverse_team.get(sofascore_team_id)
            if fpl_team_id is None:
                continue
            lineup_rows.extend(
                parse_lineup_side(
                    payload,
                    side=side,
                    event=event,
                    fpl_team_id=fpl_team_id,
                    sofascore_team_id=sofascore_team_id,
                    candidates=candidates_by_team[fpl_team_id],
                    observed_at=observed_at,
                )
            )

    event_rows = [
        row
        for (event_id, _), row in sorted(event_rows_by_key.items())
        if event_id in confirmed_events
    ]
    role_rows = build_role_evidence(
        players,
        event_rows,
        lineup_rows,
        deadline=deadline,
        observed_at=observed_at,
    )
    write_table(pa.Table.from_pylist(event_rows), EVENTS_OUT)
    write_table(pa.Table.from_pylist(lineup_rows), LINEUPS_OUT)
    write_table(pa.Table.from_pylist(role_rows), ROLE_EVIDENCE_OUT)
    mapped = sum(row["fpl_element"] is not None for row in lineup_rows)
    lineup_rows_with_minutes = sum(row["minutes"] is not None for row in lineup_rows)
    confirmed_team_ids = {int(row["fpl_team_id"]) for row in event_rows}
    team_names = {int(team["id"]): str(team["name"]) for team in teams}
    result = {
        "receipt_version": 1,
        "created_at": observed_at,
        "season": SEASON,
        "source": "SofaScore public web API (third-party advisory evidence)",
        "source_base": SOURCE_BASE,
        "window": {"start": start.isoformat(), "end": deadline.isoformat()},
        "inputs": {
            "official_snapshot_pointer": str(MANIFESTS / "fpl-current-snapshot.json"),
            "official_snapshot_pointer_sha256": sha256_file(
                MANIFESTS / "fpl-current-snapshot.json"
            ),
            "official_refresh_receipt": str(MANIFESTS / "fpl-current-refresh.json"),
            "official_refresh_receipt_sha256": sha256_file(
                MANIFESTS / "fpl-current-refresh.json"
            ),
            "teams_sha256": sha256_file(FPL_DIR / "teams.parquet"),
            "players_sha256": sha256_file(FPL_DIR / "players.parquet"),
            "events_sha256": sha256_file(FPL_DIR / "events.parquet"),
            "role_mapping_fingerprint": fpl_role_mapping_fingerprint(
                teams, players, events
            ),
        },
        "coverage": {
            "teams": len(teams),
            "discovered_events": len(discovered),
            "confirmed_lineup_events": len(confirmed_events),
            "confirmed_team_event_rows": len(event_rows),
            "teams_with_confirmed_lineups": len(confirmed_team_ids),
            "teams_without_confirmed_lineups": [
                team_names[team_id]
                for team_id in sorted(set(SOFASCORE_TEAM_IDS) - confirmed_team_ids)
            ],
            "missing_or_unconfirmed_lineups": missing_lineups,
            "lineup_player_rows": len(lineup_rows),
            "lineup_player_rows_with_minutes": lineup_rows_with_minutes,
            "lineup_minutes_coverage": (
                lineup_rows_with_minutes / len(lineup_rows) if lineup_rows else 0.0
            ),
            "mapped_lineup_player_rows": mapped,
            "mapping_rate": mapped / len(lineup_rows) if lineup_rows else 0.0,
            "players_with_observed_lineup": sum(
                row["evidence_status"] == "observed_in_lineup" for row in role_rows
            ),
            "players_with_complete_minutes_evidence": sum(
                row["evidence_status"] == "observed_in_lineup"
                and row["minutes_data_complete"]
                for row in role_rows
            ),
        },
        "requests": requests,
        "outputs": {
            "events": str(EVENTS_OUT),
            "events_sha256": sha256_file(EVENTS_OUT),
            "lineups": str(LINEUPS_OUT),
            "lineups_sha256": sha256_file(LINEUPS_OUT),
            "role_evidence": str(ROLE_EVIDENCE_OUT),
            "role_evidence_sha256": sha256_file(ROLE_EVIDENCE_OUT),
        },
        "policy": (
            "Advisory current-season evidence only. Absence is not proof of injury or future DNP, "
            "and this receipt cannot mutate production forecasts without a separate decision gate."
        ),
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = RECEIPT.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(RECEIPT)
    return result


def upgrade_role_receipt_mapping(
    *, receipt_path: Path = RECEIPT, fpl_dir: Path = FPL_DIR
) -> dict[str, Any]:
    """Safely add semantic lineage while the legacy physical generation still matches."""
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    inputs = receipt.get("inputs") or {}
    if inputs.get("role_mapping_fingerprint"):
        return {**receipt, "upgraded": False}
    for name in ("teams", "players", "events"):
        path = fpl_dir / f"{name}.parquet"
        if inputs.get(f"{name}_sha256") != sha256_file(path):
            raise ValueError(
                "Cannot upgrade preseason lineage after its physical FPL generation changed"
            )
    inputs["role_mapping_fingerprint"] = fpl_role_mapping_fingerprint(
        pq.read_table(fpl_dir / "teams.parquet").to_pylist(),
        pq.read_table(fpl_dir / "players.parquet").to_pylist(),
        pq.read_table(fpl_dir / "events.parquet").to_pylist(),
    )
    receipt["inputs"] = inputs
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(receipt_path)
    return {**receipt, "upgraded": True}
