from __future__ import annotations

import pytest

from fplagent_engine.prospective_contract import (
    ProspectiveContractError,
    build_gw1_prospective_contract,
)

POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _candidate(candidate_id: str, *, swap: bool = False) -> dict:
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [6, 7, 12, 2]
    if swap:
        starters[1], bench[0] = bench[0], starters[1]
    return {
        "candidate_id": candidate_id,
        "selected": list(range(1, 16)),
        "lineups": {
            "1": {
                "starters": starters,
                "bench_order": bench,
                "captain": 13,
                "vice_captain": 8,
                "formation": "3-4-3",
                "expected_points": 55.0 if not swap else 54.0,
            }
        },
    }


def _inputs(*, created_at: str = "2026-08-20T12:00:00+00:00") -> tuple[dict, dict, list]:
    decision = {
        "created_at": created_at,
        "decision": {"candidate_id": "best"},
        "ranking": [
            {"candidate_id": "best", "rank": 1, "synthesis_regret": 0.1},
            {"candidate_id": "other", "rank": 2, "synthesis_regret": 0.2},
        ],
    }
    shortlist = {"candidates": [_candidate("best"), _candidate("other", swap=True)]}
    rows = [
        {
            "event_number": 1,
            "element": element,
            "player_name": f"P{element}",
            "position": position,
            "team_id": (element - 1) // 3 + 1,
            "expected_points": 3.0,
            "robust_points": 2.8,
            "p_play": 0.95,
            "expected_minutes": 80.0,
        }
        for element, position in zip(range(1, 16), POSITIONS, strict=True)
    ]
    return decision, shortlist, rows


def test_gw1_contract_freezes_selected_and_rejected_squads_with_player_evidence() -> None:
    decision, shortlist, rows = _inputs()
    contract = build_gw1_prospective_contract(
        decision,
        shortlist,
        rows,
        deadline_time="2026-08-21T17:30:00+00:00",
    )

    assert contract["version"] == "prospective_decision_contract_v2"
    assert contract["selected_action_id"] == "best"
    assert contract["reference_action_id"] == "other"
    assert len(contract["action_summaries"]) == 2
    assert len(contract["event_player_forecasts"]) == 15
    assert contract["action_summaries"][0]["event_lineups"][0]["projected_points"] == 55.0


def test_gw1_contract_rejects_post_deadline_synthesis() -> None:
    decision, shortlist, rows = _inputs(created_at="2026-08-21T18:00:00+00:00")
    with pytest.raises(ProspectiveContractError, match="after the deadline"):
        build_gw1_prospective_contract(
            decision,
            shortlist,
            rows,
            deadline_time="2026-08-21T17:30:00+00:00",
        )


def test_gw1_contract_rejects_candidate_missing_from_bound_shortlist() -> None:
    decision, shortlist, rows = _inputs()
    shortlist["candidates"].pop()
    with pytest.raises(ProspectiveContractError, match="absent"):
        build_gw1_prospective_contract(
            decision,
            shortlist,
            rows,
            deadline_time="2026-08-21T17:30:00+00:00",
        )
