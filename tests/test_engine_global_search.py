from __future__ import annotations

import numpy as np

from fplagent_engine.global_search import (
    crossover_squads,
    is_legal_squad,
    minimum_distance,
    mutate_squad,
    select_evolution_population,
    solve_global_proxy_squad,
    squad_key,
)


def _pool() -> tuple[dict[int, dict], dict[str, list[int]]]:
    meta: dict[int, dict] = {}
    by_position: dict[str, list[int]] = {}
    element = 1
    for position, count in (("GK", 6), ("DEF", 14), ("MID", 14), ("FWD", 10)):
        by_position[position] = []
        for offset in range(count):
            meta[element] = {
                "position": position,
                "team_id": 1 + (offset % 10),
                "market_price": 40 + (offset % 5) * 5,
            }
            by_position[position].append(element)
            element += 1
    return meta, by_position


def _squad(by_position: dict[str, list[int]], offset: int) -> tuple[int, ...]:
    return squad_key(
        [
            *by_position["GK"][offset : offset + 2],
            *by_position["DEF"][offset : offset + 5],
            *by_position["MID"][offset : offset + 5],
            *by_position["FWD"][offset : offset + 3],
        ]
    )


def test_global_proxy_solver_respects_legality_and_seed_distance() -> None:
    meta, by_position = _pool()
    players = sorted(meta)
    incumbent = _squad(by_position, 0)
    objective = np.linspace(0.0, 1.0, len(players))

    solution = solve_global_proxy_squad(
        players,
        meta,
        objective,
        budget=1_000,
        club_limit=3,
        distant_from=[set(incumbent)],
        minimum_seed_distance=3,
    )

    assert is_legal_squad(solution, meta, budget=1_000, club_limit=3)
    assert minimum_distance(solution, [set(incumbent)]) >= 3


def test_global_proxy_solver_honours_exact_club_count() -> None:
    meta, _ = _pool()
    players = sorted(meta)
    objective = np.arange(len(players), dtype=np.float64)

    solution = solve_global_proxy_squad(
        players,
        meta,
        objective,
        budget=1_000,
        club_limit=3,
        distant_from=[],
        minimum_seed_distance=1,
        exact_club_counts={1: 2},
    )

    assert sum(int(meta[element]["team_id"]) == 1 for element in solution) == 2
    assert is_legal_squad(solution, meta, budget=1_000, club_limit=3)


def test_crossover_and_mutation_keep_squads_legal() -> None:
    meta, by_position = _pool()
    left = _squad(by_position, 0)
    right = _squad(by_position, 3)
    players = sorted(meta)
    player_index = {element: index for index, element in enumerate(players)}
    utility = np.linspace(-1.0, 1.0, len(players))
    rng = np.random.default_rng(20260807)

    child = crossover_squads(
        left,
        right,
        meta,
        player_index,
        utility,
        rng,
        budget=1_000,
        club_limit=3,
    )
    assert child is not None
    assert is_legal_squad(child, meta, budget=1_000, club_limit=3)

    mutant = mutate_squad(
        child,
        meta,
        by_position,
        player_index,
        utility,
        rng,
        budget=1_000,
        club_limit=3,
        steps=3,
    )
    assert mutant is not None
    assert is_legal_squad(mutant, meta, budget=1_000, club_limit=3)


def test_evolution_population_retains_scenario_specialists() -> None:
    meta, by_position = _pool()
    squads = [_squad(by_position, offset) for offset in range(6)]
    players = sorted(meta)
    player_index = {element: index for index, element in enumerate(players)}
    utilities = np.column_stack(
        (
            np.linspace(-1.0, 1.0, len(players)),
            np.linspace(1.0, -1.0, len(players)),
        )
    )

    selected = select_evolution_population(squads, utilities, player_index, 4)

    assert len(selected) == 4
    assert len(set(selected)) == 4
