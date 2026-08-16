from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .picker_backtest import _solve_event


class MatchedPolicyError(ValueError):
    """Forecasts cannot be compared on an identical legal decision surface."""


def matched_legal_policy_replay(
    rows: Iterable[Mapping[str, Any]],
    *,
    champion_field: str,
    challenger_field: str,
    minimum_players: int = 100,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Score two forecasts through the same legal £100m squad/XI/captain solve.

    The input must contain one row per player-deadline and the realized FPL points.
    Any event missing either model is rejected rather than evaluated on a friendlier
    subset for one of the models.
    """
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        required = {
            "season",
            "event_number",
            "element",
            "position",
            "team_id",
            "market_price",
            "target_points",
            champion_field,
            challenger_field,
        }
        missing = required - set(row)
        if missing:
            raise MatchedPolicyError(f"matched policy row is missing {sorted(missing)}")
        if row[champion_field] is None or row[challenger_field] is None:
            raise MatchedPolicyError("matched policy comparison contains a null forecast")
        grouped[(str(row["season"]), int(row["event_number"]))].append(row)

    eligible = [
        (key, event_rows)
        for key, event_rows in sorted(grouped.items())
        if len(event_rows) >= minimum_players
    ]
    events = []
    for event_index, ((season, event), event_rows) in enumerate(eligible, start=1):
        if len({int(row["element"]) for row in event_rows}) != len(event_rows):
            raise MatchedPolicyError(f"duplicate player rows in {season} GW{event}")
        champion = _solve_event(event_rows, champion_field)
        challenger = _solve_event(event_rows, challenger_field)
        events.append(
            {
                "season": season,
                "event": event,
                "players": len(event_rows),
                "champion_actual_points": float(champion["actual_points"]),
                "challenger_actual_points": float(challenger["actual_points"]),
                "delta": float(challenger["actual_points"] - champion["actual_points"]),
                "champion_captain": champion["captain"],
                "challenger_captain": challenger["captain"],
                "squad_overlap": len(set(champion["squad"]) & set(challenger["squad"])),
            }
        )
        if progress is not None and (
            event_index == 1 or event_index == len(eligible) or event_index % 10 == 0
        ):
            progress(f"Matched policy replay: solved {event_index}/{len(eligible)} events")
    by_season: dict[str, dict[str, Any]] = {}
    for season in sorted({row["season"] for row in events}):
        values = [row["delta"] for row in events if row["season"] == season]
        by_season[season] = {
            "events": len(values),
            "total_delta": float(sum(values)),
            "mean_delta": float(sum(values) / len(values)),
            "wins": sum(value > 0 for value in values),
            "ties": sum(value == 0 for value in values),
            "losses": sum(value < 0 for value in values),
        }
    deltas = [row["delta"] for row in events]
    return {
        "matched_events": len(events),
        "events": events,
        "by_season": by_season,
        "total_delta": float(sum(deltas)),
        "mean_delta": float(sum(deltas) / len(deltas)) if deltas else None,
        "winning_events": sum(value > 0 for value in deltas),
        "losing_events": sum(value < 0 for value in deltas),
        "contract": {
            "identical_rows": True,
            "identical_budget": True,
            "identical_squad_formation_club_constraints": True,
            "identical_bench_weight": True,
            "target": "realized FPL points after legal squad, XI and captain selection",
        },
    }
