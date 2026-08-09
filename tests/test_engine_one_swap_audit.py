from __future__ import annotations

import numpy as np

from fplagent_engine.one_swap_audit import (
    _configuration_identity,
    _proxy_shortlist_ids,
    _rank_configurations,
    _squad_champions,
    enumerate_legal_one_swaps,
)
from fplagent_engine.rules import SquadRules, validate_squad


def _rules() -> SquadRules:
    return SquadRules(
        budget=150,
        squad_size=15,
        starting_size=11,
        club_limit=3,
        squad_positions={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        minimum_starters={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        maximum_starters={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_free_transfers=5,
        scoring={},
    )


def _meta() -> dict[int, dict]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    teams = [1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7]
    meta = {
        element: {
            "element": element,
            "player_name": f"Player {element}",
            "position": position,
            "team_id": team,
            "market_price": 10.0,
            "can_select": True,
            "removed": False,
        }
        for element, (position, team) in enumerate(
            zip(positions, teams, strict=True), start=1
        )
    }
    meta[16] = {
        **meta[3],
        "element": 16,
        "player_name": "Legal defender",
        "team_id": 8,
    }
    meta[17] = {
        **meta[3],
        "element": 17,
        "player_name": "Too expensive",
        "team_id": 8,
        "market_price": 11.0,
    }
    meta[18] = {
        **meta[3],
        "element": 18,
        "player_name": "Club overflow",
        "team_id": 1,
    }
    meta[19] = {
        **meta[3],
        "element": 19,
        "player_name": "Unavailable",
        "team_id": 8,
        "can_select": False,
    }
    return meta


def test_one_swap_enumeration_covers_only_legal_same_position_moves() -> None:
    meta = _meta()
    selected = list(range(1, 16))

    swaps = enumerate_legal_one_swaps(selected, meta, _rules())

    assert swaps
    assert any(row["incoming"] == 16 for row in swaps)
    assert all(row["incoming"] != 17 for row in swaps)
    assert all(row["incoming"] != 19 for row in swaps)
    for row in swaps:
        assert meta[row["outgoing"]]["position"] == meta[row["incoming"]]["position"]
        validate_squad([meta[element] for element in row["selected"]], _rules())
    overflow = [row for row in swaps if row["incoming"] == 18]
    assert overflow
    assert all(meta[row["outgoing"]]["team_id"] == 1 for row in overflow)


def test_configuration_identity_is_order_independent_for_selected_and_starters() -> None:
    lineup = {
        "1": {
            "starters": list(range(1, 12)),
            "bench_order": [12, 13, 14, 15],
            "captain": 1,
            "vice_captain": 2,
        }
    }

    first = _configuration_identity(list(range(1, 16)), lineup)
    second = _configuration_identity(
        list(reversed(range(1, 16))),
        {"1": {**lineup["1"], "starters": list(reversed(range(1, 12)))}},
    )

    assert first == second


def test_proxy_shortlist_preserves_incumbent_and_each_outgoing_pressure_case() -> None:
    rows = [
        {
            "squad_id": f"SW-{index}-99",
            "outgoing": index,
            "proxy_robust_regret": float(index),
            "direct": 100.0 - index,
            "robust": 100.0 - index,
            "component": 100.0 - index,
        }
        for index in range(1, 41)
    ]
    rows.append(
        {
            "squad_id": "incumbent",
            "outgoing": None,
            "proxy_robust_regret": 999.0,
            "direct": 0.0,
            "robust": 0.0,
            "component": 0.0,
        }
    )

    chosen = _proxy_shortlist_ids(rows, "incumbent", 32)

    assert "incumbent" in chosen
    assert {f"SW-{index}-99" for index in range(1, 41)} <= set(chosen)


def test_configuration_ranking_and_squad_champions_use_balanced_family_regret() -> None:
    candidates = [
        {
            "candidate_id": "a1",
            "squad_id": "a",
            "configuration_sources": ["direct"],
        },
        {
            "candidate_id": "a2",
            "squad_id": "a",
            "configuration_sources": ["component"],
        },
        {
            "candidate_id": "b1",
            "squad_id": "b",
            "configuration_sources": ["balanced"],
        },
    ]
    residual = np.asarray(
        [
            [[10], [6], [9]],
            [[10], [6], [9]],
        ],
        dtype=np.int16,
    )
    component = np.asarray(
        [
            [[6], [10], [9]],
            [[6], [10], [9]],
        ],
        dtype=np.int16,
    )

    ranking, _, _ = _rank_configurations(
        candidates, residual, component, (1,), 0.88
    )
    champions = _squad_champions(ranking)

    assert ranking[0]["candidate_id"] == "b1"
    assert [row["squad_id"] for row in champions] == ["b", "a"]
    assert champions[0]["squad_rank"] == 1
