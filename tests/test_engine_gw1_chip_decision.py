from __future__ import annotations

import numpy as np

from fplagent_engine.gw1_chip_decision import (
    choose_gw1_chip,
    score_team_chip_variants,
    summarize_chip_delta,
)


def _candidate() -> tuple[dict, list[int], dict[int, dict]]:
    players = list(range(1, 16))
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    meta = {
        element: {"position": position, "player_name": str(element)}
        for element, position in zip(players, positions, strict=True)
    }
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    return (
        {
            "candidate_id": "test",
            "selected": players,
            "lineups": {
                "1": {
                    "starters": starters,
                    "bench_order": [6, 7, 12, 2],
                    "captain": 8,
                    "vice_captain": 9,
                    "formation": "3-4-3",
                }
            },
        },
        players,
        meta,
    )


def test_chip_variants_apply_exact_extra_scorers() -> None:
    candidate, players, meta = _candidate()
    points = np.ones((2, 1, 15), dtype=np.int16)
    points[:, 0, 7] = 5
    played = np.ones_like(points, dtype=bool)

    scores = score_team_chip_variants(candidate, players, points, played, meta)

    # Four bench points become active under BB; TC adds one more captain copy.
    assert (scores["bench_boost"] - scores["no_chip"]).tolist() == [4.0, 4.0]
    assert (scores["triple_captain"] - scores["no_chip"]).tolist() == [5.0, 5.0]


def test_chip_variant_respects_autosub_and_vice_fallback() -> None:
    candidate, players, meta = _candidate()
    points = np.ones((1, 1, 15), dtype=np.int16)
    points[:, 0, 8] = 4
    played = np.ones_like(points, dtype=bool)
    played[:, 0, 7] = False  # captain DNP; vice (player 9) scores four
    played[:, 0, 2] = False  # one defender starter DNP; bench defender autosubs

    scores = score_team_chip_variants(candidate, players, points, played, meta)

    assert (scores["triple_captain"] - scores["no_chip"]).tolist() == [4.0]
    # Captain and a defender miss out, so two bench players already autosub; one outfielder and
    # the reserve goalkeeper are the only additional BB scorers.
    assert (scores["bench_boost"] - scores["no_chip"]).tolist() == [2.0]


def test_no_chip_when_retained_policy_has_no_authority() -> None:
    evidence = {
        chip: {family: {"mean": 20.0} for family in ("residual", "component")}
        for chip in ("bench_boost", "triple_captain")
    }
    retention = {
        "authority": False,
        "promotion_gate": {"passed": False},
        "retained_value_thresholds": {"bench_boost": 8.0, "triple_captain": 6.0},
    }

    recommendation = choose_gw1_chip(evidence, retention)

    assert recommendation["chip"] is None
    assert recommendation["strongest_immediate_signal"] == {
        "chip": "triple_captain",
        "cross_family_floor": 20.0,
        "retained_value_threshold": 6.0,
        "margin": 14.0,
        "status": "strong_but_not_actionable",
    }


def test_authoritative_policy_selects_largest_margin() -> None:
    evidence = {
        "bench_boost": {"residual": {"mean": 9.0}, "component": {"mean": 10.0}},
        "triple_captain": {"residual": {"mean": 7.5}, "component": {"mean": 8.0}},
    }
    retention = {
        "authority": True,
        "promotion_gate": {"passed": True},
        "retained_value_thresholds": {"bench_boost": 8.0, "triple_captain": 6.0},
    }

    assert choose_gw1_chip(evidence, retention)["chip"] == "triple_captain"


def test_chip_summary_exposes_tail_and_zero_probability() -> None:
    summary = summarize_chip_delta(
        np.asarray([10, 12, 14, 16], dtype=float),
        np.asarray([10, 10, 10, 10], dtype=float),
    )

    assert summary["mean"] == 3.0
    assert summary["zero_probability"] == 0.25
    assert summary["positive_probability"] == 0.75
