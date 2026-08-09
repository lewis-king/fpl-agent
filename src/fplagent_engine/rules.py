from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.paths import PROCESSED

RULES_PATH = PROCESSED / "fpl" / "2026-27" / "preseason" / "rules.parquet"
POSITIONS_PATH = PROCESSED / "fpl" / "2026-27" / "preseason" / "positions.parquet"


@dataclass(frozen=True)
class SquadRules:
    budget: int
    squad_size: int
    starting_size: int
    club_limit: int
    squad_positions: dict[str, int]
    minimum_starters: dict[str, int]
    maximum_starters: dict[str, int]
    max_free_transfers: int
    scoring: dict


def load_rules(
    rules_path: Path = RULES_PATH, positions_path: Path = POSITIONS_PATH
) -> SquadRules:
    rules = pq.read_table(rules_path).to_pylist()[0]
    positions = pq.read_table(positions_path).to_pylist()
    normalized = {"GKP": "GK", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
    squad_positions = {}
    minimum_starters = {}
    maximum_starters = {}
    for row in positions:
        position = normalized[row["singular_name_short"]]
        squad_positions[position] = int(row["squad_select"])
        minimum_starters[position] = int(row["squad_min_play"])
        maximum_starters[position] = int(row["squad_max_play"])
    return SquadRules(
        budget=int(rules["budget_tenths"]),
        squad_size=int(rules["squad_size"]),
        starting_size=int(rules["starting_size"]),
        club_limit=int(rules["club_player_limit"]),
        squad_positions=squad_positions,
        minimum_starters=minimum_starters,
        maximum_starters=maximum_starters,
        max_free_transfers=int(rules["max_bankable_free_transfers"]),
        scoring=json.loads(rules["scoring_json"]),
    )


def validate_squad(
    players: Iterable[dict],
    rules: SquadRules | None = None,
    *,
    enforce_budget: bool = True,
) -> None:
    rules = rules or load_rules()
    squad = list(players)
    if len(squad) != rules.squad_size:
        raise ValueError(f"Squad has {len(squad)} players; expected {rules.squad_size}")
    elements = [int(player["element"]) for player in squad]
    if len(set(elements)) != len(elements):
        raise ValueError("Squad contains duplicate players")
    if enforce_budget:
        spend = sum(float(player["market_price"]) for player in squad)
        if spend > rules.budget + 1e-6:
            raise ValueError(f"Squad costs {spend}; budget is {rules.budget}")
    for position, expected in rules.squad_positions.items():
        actual = sum(player["position"] == position for player in squad)
        if actual != expected:
            raise ValueError(f"Squad has {actual} {position}; expected {expected}")
    by_club = {}
    for player in squad:
        club = int(player["team_id"])
        by_club[club] = by_club.get(club, 0) + 1
    if any(count > rules.club_limit for count in by_club.values()):
        raise ValueError(f"Squad exceeds club limit: {by_club}")


def validate_lineup(
    squad: Iterable[dict],
    starters: Iterable[int],
    bench_order: Iterable[int],
    captain: int,
    vice_captain: int,
    rules: SquadRules | None = None,
) -> None:
    rules = rules or load_rules()
    squad_list = list(squad)
    by_id = {int(player["element"]): player for player in squad_list}
    starting_ids = list(starters)
    bench_ids = list(bench_order)
    if len(starting_ids) != rules.starting_size or len(set(starting_ids)) != len(
        starting_ids
    ):
        raise ValueError("Starting XI has the wrong size or duplicates")
    if set(starting_ids) | set(bench_ids) != set(by_id):
        raise ValueError("Starting XI and bench do not partition the squad")
    if set(starting_ids) & set(bench_ids):
        raise ValueError("A player appears in both the XI and bench")
    if captain not in starting_ids or vice_captain not in starting_ids:
        raise ValueError("Captain and vice-captain must start")
    if captain == vice_captain:
        raise ValueError("Captain and vice-captain must differ")
    for position in rules.squad_positions:
        actual = sum(by_id[element]["position"] == position for element in starting_ids)
        if not rules.minimum_starters[position] <= actual <= rules.maximum_starters[position]:
            raise ValueError(f"Illegal number of starting {position}: {actual}")


def score_fixture(
    *,
    position: str,
    minutes: int,
    goals: int = 0,
    assists: int = 0,
    clean_sheet: bool = False,
    goals_conceded: int = 0,
    saves: int = 0,
    penalties_saved: int = 0,
    penalties_missed: int = 0,
    yellow_cards: int = 0,
    red_cards: int = 0,
    own_goals: int = 0,
    bonus: int = 0,
    defensive_contribution_awarded: bool = False,
    rules: SquadRules | None = None,
) -> int:
    rules = rules or load_rules()
    scoring = rules.scoring
    api_position = "GKP" if position == "GK" else position
    if minutes <= 0:
        return 0
    points = scoring["long_play"] if minutes >= 60 else scoring["short_play"]
    points += goals * scoring["goals_scored"][api_position]
    points += assists * scoring["assists"]
    if clean_sheet and minutes >= 60:
        points += scoring["clean_sheets"][api_position]
    if position in {"GK", "DEF"}:
        points += (goals_conceded // 2) * scoring["goals_conceded"][api_position]
    if position == "GK":
        points += (saves // 3) * scoring["saves"]
    points += penalties_saved * scoring["penalties_saved"]
    points += penalties_missed * scoring["penalties_missed"]
    points += yellow_cards * scoring["yellow_cards"]
    points += red_cards * scoring["red_cards"]
    points += own_goals * scoring["own_goals"]
    points += bonus * scoring["bonus"]
    if defensive_contribution_awarded:
        points += scoring["defensive_contribution"][api_position]
    return int(points)
