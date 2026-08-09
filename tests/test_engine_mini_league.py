from __future__ import annotations

import pytest

from fplagent_engine.cli import parser
from fplagent_engine.mini_league import (
    MiniLeagueStrategyError,
    evaluate_mini_league_shadow,
)


def _summary(action_id: str, projected: float, starters: list[int], captain: int) -> dict:
    bench = [element for element in range(1, 16) if element not in starters]
    return {
        "action_id": action_id,
        "route_type": "roll" if action_id == "safe" else "one_free_transfer",
        "incremental_points_cost": 0,
        "event_lineups": [
            {
                "event": 32,
                "projected_points": projected,
                "starter_player_ids": starters,
                "bench_player_ids": bench,
                "captain_player_id": captain,
                "vice_captain_player_id": starters[1],
            }
        ],
    }


def _decision() -> dict:
    safe = list(range(1, 12))
    differential = [1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 14]
    return {
        "version": "weekly_decision_synthesis_v3",
        "created_at": "2027-04-01T12:00:00+00:00",
        "decision_event": 32,
        "selected_action_id": "safe",
        "action_summaries": [
            _summary("safe", 60.0, safe, 1),
            _summary("differential", 59.5, differential, 12),
        ],
        "event_player_forecasts": {
            str(element): {"expected_points": 5.0} for element in range(1, 16)
        },
    }


def _context() -> dict:
    return {
        "version": "mini_league_context_v1",
        "decision_event": 32,
        "source_event": 31,
        "observed_at": "2027-04-01T10:00:00+00:00",
        "own_total_points": 1800,
        "target_entry_id": 2,
        "rivals": [
            {
                "entry_id": 2,
                "name": "Leader",
                "total_points": 1850,
                "starter_player_ids": list(range(1, 12)),
                "captain_player_id": 1,
            }
        ],
    }


def test_late_chasing_shadow_can_prefer_close_xp_differential_without_authority() -> None:
    result = evaluate_mini_league_shadow(_decision(), _context())

    assert result["mode"] == "chasing"
    assert result["shadow_preference"] == "differential"
    assert result["operational_recommendation"] == "safe"
    assert result["decision_authority"] is False


def test_stale_rival_lineup_context_is_rejected() -> None:
    context = _context()
    context["source_event"] = 30

    with pytest.raises(MiniLeagueStrategyError, match="immediately prior event"):
        evaluate_mini_league_shadow(_decision(), context)


def test_new_points_first_commands_are_exposed() -> None:
    assert parser().parse_args(["challenger-registry"]).command == "challenger-registry"
    assert parser().parse_args(["prospective-scoreboard"]).command == "prospective-scoreboard"
    args = parser().parse_args(
        ["mini-league-shadow", "--decision", "decision.json", "--context", "context.json"]
    )
    assert args.command == "mini-league-shadow"
