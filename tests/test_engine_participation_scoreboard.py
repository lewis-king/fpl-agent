from __future__ import annotations

from fplagent_engine.cli import parser
from fplagent_engine.participation_scoreboard import (
    _promotion_gate,
    score_participation_snapshot,
)


def _fixture() -> tuple[list[dict], list[dict], dict[int, bool]]:
    consensus = []
    observations = []
    actual = {}
    for team in (1, 2):
        first = 1 if team == 1 else 13
        starters = set(range(first, first + 11))
        bench = first + 11
        for element in range(first, bench + 1):
            is_source_start = element in starters
            consensus.append(
                {
                    "team_id": team,
                    "element": element,
                    "champion_p_start": 0.9 if element != first + 10 else 0.4,
                    "champion_p_play": 0.95,
                    "complete_source_count": 2,
                    "predicted_start_sources": (
                        ["source_a", "source_b"] if is_source_start else []
                    ),
                }
            )
            actual[element] = element in starters
        # The production model wrongly ranks the bench player over the final actual starter.
        consensus[-1]["champion_p_start"] = 0.8
        for source in ("source_a", "source_b"):
            observations.extend(
                {
                    "team_id": team,
                    "source_id": source,
                    "source_complete": True,
                    "decision_eligible": True,
                    "fpl_element": element,
                }
                for element in sorted(starters)
            )
    return consensus, observations, actual


def test_consensus_is_scored_against_champion_on_exact_starting_xis() -> None:
    consensus, observations, actual = _fixture()

    result = score_participation_snapshot(consensus, observations, actual)

    assert result["teams_scored"] == 2
    assert result["two_source_teams"] == 2
    assert result["baseline_mean_hits"] == 10.0
    assert result["consensus_mean_hits"] == 11.0
    assert result["mean_delta_to_champion"] == 1.0
    assert result["source_mean_hits"] == {"source_a": 11, "source_b": 11}


def test_prospective_pass_only_authorizes_legal_replay() -> None:
    events = [
        {
            "event": event,
            "two_source_teams": 20,
            "mean_delta_to_champion": 0.1,
        }
        for event in range(1, 7)
    ]

    gate = _promotion_gate(events)

    assert gate["passed"] is True
    assert gate["state"] == "ready_for_exact_legal_replay"
    assert gate["production_changed"] is False


def test_one_bad_event_blocks_promotion_even_with_positive_mean() -> None:
    events = [
        {
            "event": event,
            "two_source_teams": 20,
            "mean_delta_to_champion": -0.1 if event == 1 else 0.3,
        }
        for event in range(1, 7)
    ]

    gate = _promotion_gate(events)

    assert gate["passed"] is False
    assert gate["checks"]["positive_mean_lineup_hit_lift"] is True
    assert gate["checks"]["non_negative_event_floor"] is False


def test_cli_exposes_participation_scoreboard() -> None:
    assert parser().parse_args(["participation-scoreboard"]).command == (
        "participation-scoreboard"
    )
