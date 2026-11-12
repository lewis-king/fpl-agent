from __future__ import annotations

import numpy as np

from fplagent_engine.current_squad_audit import (
    _apply_simulation_configuration,
    _choice_leaders,
    _paired_delta,
    enumerate_legal_xis,
    resolve_configuration_stability,
)
from fplagent_engine.rules import SquadRules


def _valid_meta() -> tuple[list[int], dict[int, dict]]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    selected = list(range(1, 16))
    return selected, {
        element: {"element": element, "position": position}
        for element, position in zip(selected, positions, strict=True)
    }


def test_enumerate_legal_xis_covers_every_formation_and_player_choice() -> None:
    selected, meta = _valid_meta()
    lineups = enumerate_legal_xis(selected, meta)

    formations = {
        tuple(
            sum(meta[element]["position"] == position for element in lineup)
            for position in ("DEF", "MID", "FWD")
        )
        for lineup in lineups
    }
    assert formations == {
        (3, 4, 3),
        (3, 5, 2),
        (4, 3, 3),
        (4, 4, 2),
        (4, 5, 1),
        (5, 2, 3),
        (5, 3, 2),
        (5, 4, 1),
    }
    assert len(lineups) == 550
    assert len(set(lineups)) == len(lineups)
    assert all(len(lineup) == 11 for lineup in lineups)


def test_choice_leaders_keeps_balanced_and_family_specific_options() -> None:
    family_means = np.asarray(
        [
            [5.0, 3.0],
            [4.4, 4.4],
            [3.0, 5.0],
        ]
    )
    assert _choice_leaders(family_means) == [1, 0, 2]


def test_paired_delta_uses_shared_world_differences() -> None:
    metrics = _paired_delta(np.asarray([2, 5, 4]), np.asarray([1, 3, 4]))
    assert metrics["mean"] == 1.0
    assert metrics["beat_probability"] == 2 / 3
    assert metrics["tie_probability"] == 1 / 3


def _configuration_row(
    candidate_id: str,
    *,
    vice: int,
    rank: int,
    regret: float,
    starters: list[int] | None = None,
    bench_order: list[int] | None = None,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "formation": "3-4-3",
        "starters": starters or list(range(1, 12)),
        "bench_order": bench_order or [12, 13, 14, 15],
        "captain": 1,
        "vice_captain": vice,
        "rank": rank,
        "robust_regret": regret,
    }


def test_configuration_stability_resolves_only_immaterial_vice_noise() -> None:
    selection = [
        _configuration_row("lac", vice=2, rank=1, regret=0.08268),
        _configuration_row("mbe", vice=3, rank=2, regret=0.08352),
    ]
    holdout = [
        _configuration_row("mbe", vice=3, rank=1, regret=0.107552),
        _configuration_row("lac", vice=2, rank=2, regret=0.112608),
    ]

    result = resolve_configuration_stability(
        selection,
        holdout,
        selection_simulations=5_000,
        holdout_simulations=25_000,
    )

    assert result["stable"] is True
    assert result["exact"] is False
    assert result["vice_only_practical_equivalence"] is True
    assert result["bench_order_only_practical_equivalence"] is False
    assert result["single_starter_bench_swap_practical_equivalence"] is False
    assert result["resolved_candidate_id"] == "mbe"


def test_configuration_stability_resolves_immaterial_bench_order_noise() -> None:
    selection = [
        _configuration_row(
            "virgil-first", vice=2, rank=1, regret=0.08268, bench_order=[12, 13, 14, 15]
        ),
        _configuration_row(
            "senesi-first", vice=2, rank=2, regret=0.08392, bench_order=[13, 12, 14, 15]
        ),
    ]
    holdout = [
        _configuration_row(
            "senesi-first", vice=2, rank=1, regret=0.107552, bench_order=[13, 12, 14, 15]
        ),
        _configuration_row(
            "virgil-first", vice=2, rank=2, regret=0.113072, bench_order=[12, 13, 14, 15]
        ),
    ]

    result = resolve_configuration_stability(
        selection,
        holdout,
        selection_simulations=25_000,
        holdout_simulations=25_000,
    )

    assert result["stable"] is True
    assert result["exact"] is False
    assert result["vice_only_practical_equivalence"] is False
    assert result["bench_order_only_practical_equivalence"] is True
    assert result["single_starter_bench_swap_practical_equivalence"] is False
    assert result["practical_equivalence_type"] == "bench_order"
    assert result["resolved_candidate_id"] == "senesi-first"


def test_configuration_stability_resolves_single_starter_bench_boundary_noise() -> None:
    selection = [
        _configuration_row(
            "forward-starts",
            vice=2,
            rank=1,
            regret=0.138144,
            bench_order=[12, 13, 14, 15],
        ),
        _configuration_row(
            "defender-starts",
            vice=2,
            rank=2,
            regret=0.148920,
            starters=[*range(1, 11), 12],
            bench_order=[11, 13, 14, 15],
        ),
    ]
    holdout = [
        _configuration_row(
            "defender-starts",
            vice=2,
            rank=1,
            regret=0.094824,
            starters=[*range(1, 11), 12],
            bench_order=[11, 13, 14, 15],
        ),
        _configuration_row(
            "forward-starts",
            vice=2,
            rank=2,
            regret=0.095104,
            bench_order=[12, 13, 14, 15],
        ),
    ]

    result = resolve_configuration_stability(
        selection,
        holdout,
        selection_simulations=50_000,
        holdout_simulations=50_000,
    )

    assert result["stable"] is True
    assert result["practical_equivalence_type"] == "single_starter_bench_swap"
    assert result["single_starter_bench_swap_practical_equivalence"] is True
    assert result["resolved_candidate_id"] == "forward-starts"


def test_configuration_stability_blocks_structural_or_material_disagreement() -> None:
    selection = [
        _configuration_row("selection", vice=2, rank=1, regret=0.0),
        _configuration_row("holdout", vice=3, rank=2, regret=0.02),
    ]
    holdout = [
        _configuration_row("holdout", vice=3, rank=1, regret=0.0, starters=[*range(1, 11), 12]),
        _configuration_row("selection", vice=2, rank=2, regret=0.02),
    ]

    result = resolve_configuration_stability(
        selection,
        holdout,
        selection_simulations=5_000,
        holdout_simulations=25_000,
    )

    assert result["stable"] is False
    assert result["vice_only_practical_equivalence"] is False
    assert result["bench_order_only_practical_equivalence"] is False
    assert result["single_starter_bench_swap_practical_equivalence"] is False


def test_simulation_configuration_updates_every_actionable_role_only() -> None:
    selected, basic_meta = _valid_meta()
    meta = {
        element: {
            **row,
            "player_name": f"Player {element}",
            "team_name": f"Team {element}",
            "market_price": 50.0,
        }
        for element, row in basic_meta.items()
    }
    published_lineup = {
        "starters": [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
        "bench_order": [6, 7, 12, 2],
        "captain": 8,
        "vice_captain": 3,
        "formation": "3-4-3",
        "expected_points": 60.0,
    }
    champion_lineup = {
        **published_lineup,
        "bench_order": [7, 6, 12, 2],
        "vice_captain": 9,
    }
    candidate = {
        "candidate_id": "R-test",
        "display_name": "3-4-3 · Player 8 captain · £20.0m bench",
        "selected": selected,
        "lineups": {"1": published_lineup, "2": {"sentinel": "future"}},
        "budget_spent": 75.0,
        "bank": 25.0,
        "gw1_bench_spend": 20.0,
        "gw1_outfield_bench_spend": 15.0,
        "gw1_formation": "3-4-3",
    }
    decision = {
        "decision": {
            "candidate_id": "R-test",
            "display_name": candidate["display_name"],
            "formation": "3-4-3",
            "candidate": candidate,
            "squad": {},
        },
        "ranking": [{"candidate_id": "R-test", "gw1_formation": "3-4-3"}],
    }
    champion = {
        "candidate_id": "XI-sim",
        "selected": selected,
        "lineups": {"1": champion_lineup},
    }
    by_player = {element: {1: {"expected_points": float(element) / 10.0}} for element in selected}
    rules = SquadRules(
        budget=1000,
        squad_size=15,
        starting_size=11,
        club_limit=3,
        squad_positions={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        minimum_starters={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        maximum_starters={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_free_transfers=5,
        scoring={},
    )

    promoted, changes = _apply_simulation_configuration(
        decision,
        champion,
        meta,
        by_player,
        {"holdout_robust_gain": 0.10},
        rules,
    )

    lineup = promoted["decision"]["candidate"]["lineups"]["1"]
    assert lineup["bench_order"] == [7, 6, 12, 2]
    assert lineup["vice_captain"] == 9
    assert promoted["decision"]["candidate"]["lineups"]["2"] == {"sentinel": "future"}
    assert promoted["decision"]["squad"]["bench"][0]["name"] == "Player 7"
    assert changes["bench_order_before"][:2] == ["Player 6", "Player 7"]
    assert changes["bench_order_after"][:2] == ["Player 7", "Player 6"]
    assert changes["vice_captain_after"] == "Player 9"
    assert decision["decision"]["candidate"]["lineups"]["1"] == published_lineup
