from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path

import duckdb

from .contracts import CatalogPlayer, ImportedPlayer, ScreenshotTeamProposal

ELEMENT_TYPE_TO_POSITION = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def derive_formation(players: Iterable[ImportedPlayer]) -> str | None:
    """Derive formation from a complete resolved starting XI, never screen geometry."""
    starters = tuple(player for player in players if player.squad_role == "starter")
    if len(starters) != 11 or any(player.position is None for player in starters):
        return None
    counts = Counter(player.position for player in starters)
    if counts["GK"] != 1:
        return None
    return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"


def normalize_player_name(value: str) -> str:
    value = re.sub(
        r"\s+[A-Z]{2,4}\s*\([HA]\)\s*$",
        "",
        " ".join(value.splitlines()),
        flags=re.IGNORECASE,
    )
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower().replace("…", ""))


def _aliases(player: CatalogPlayer) -> tuple[str, ...]:
    values = {
        player.web_name,
        player.first_name,
        player.second_name,
        f"{player.first_name} {player.second_name}",
    }
    if player.known_name:
        values.add(player.known_name)
    return tuple(sorted({normalize_player_name(value) for value in values if value.strip()}))


def _score_name(source_text: str, player: CatalogPlayer) -> float:
    query = normalize_player_name(source_text)
    if not query:
        return 0.0
    best = 0.0
    for alias in _aliases(player):
        if query == alias:
            return 1.0
        if len(query) >= 5 and alias.startswith(query):
            best = max(best, 0.97)
        if len(alias) >= 5 and query.startswith(alias):
            best = max(best, 0.94)
        best = max(best, SequenceMatcher(None, query, alias).ratio())
    return best


def resolve_player(
    source_text: str,
    catalog: Iterable[CatalogPlayer],
    position: str | None = None,
    minimum_score: float = 0.84,
    minimum_margin: float = 0.04,
) -> tuple[CatalogPlayer | None, float]:
    candidates = [
        (player, _score_name(source_text, player))
        for player in catalog
        if player.can_select and (position is None or player.position == position)
    ]
    candidates.sort(key=lambda item: (-item[1], item[0].player_id))
    if not candidates or candidates[0][1] < minimum_score:
        return None, candidates[0][1] if candidates else 0.0
    runner_up = candidates[1][1] if len(candidates) > 1 else 0.0
    if candidates[0][1] - runner_up < minimum_margin:
        return None, candidates[0][1]
    return candidates[0]


def resolve_proposal(
    proposal: ScreenshotTeamProposal,
    catalog: Iterable[CatalogPlayer],
) -> ScreenshotTeamProposal:
    catalog_rows = tuple(catalog)
    resolved: list[ImportedPlayer] = []
    unresolved: list[str] = []
    for player in proposal.players:
        if player.player_id is not None:
            resolved.append(player)
            continue
        match, confidence = resolve_player(player.source_text, catalog_rows, player.position)
        if match is None:
            unresolved.append(player.source_text)
            resolved.append(replace(player, confidence=confidence))
        else:
            resolved.append(
                replace(
                    player,
                    player_id=match.player_id,
                    position=match.position,
                    confidence=confidence,
                )
            )
    return replace(proposal, players=tuple(resolved), unresolved=tuple(unresolved))


def load_current_catalog(database_path: Path) -> tuple[CatalogPlayer, ...]:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT id, web_name, first_name, second_name, known_name,
                   element_type, team, now_cost, can_select
            FROM fpl_current_players
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        CatalogPlayer(
            player_id=int(row[0]),
            web_name=str(row[1]),
            first_name=str(row[2]),
            second_name=str(row[3]),
            known_name=str(row[4]) if row[4] else None,
            position=ELEMENT_TYPE_TO_POSITION[int(row[5])],
            team_id=int(row[6]),
            price_tenths=int(row[7]),
            can_select=bool(row[8]),
        )
        for row in rows
    )
