from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import highspy
import numpy as np

from .optimizer import POSITION_SQUAD

Squad = tuple[int, ...]


@dataclass(frozen=True)
class GlobalSearchResult:
    milp_squads: tuple[Squad, ...]
    evolution_squads: tuple[Squad, ...]
    generations_completed: int
    attempted_offspring: int
    rejected_near_seed: int
    rejected_illegal: int


def squad_key(elements: Iterable[int]) -> Squad:
    return tuple(sorted(map(int, elements)))


def minimum_distance(squad: Iterable[int], references: Iterable[set[int]]) -> int:
    selected = set(map(int, squad))
    return 15 - max((len(selected & reference) for reference in references), default=0)


def is_legal_squad(
    squad: Iterable[int],
    meta: dict[int, dict[str, Any]],
    *,
    budget: float,
    club_limit: int,
) -> bool:
    selected = squad_key(squad)
    if len(selected) != 15 or len(set(selected)) != 15:
        return False
    if any(element not in meta for element in selected):
        return False
    if Counter(str(meta[element]["position"]) for element in selected) != Counter(
        POSITION_SQUAD
    ):
        return False
    if sum(float(meta[element]["market_price"]) for element in selected) > budget + 1e-8:
        return False
    clubs = Counter(int(meta[element]["team_id"]) for element in selected)
    return max(clubs.values(), default=0) <= club_limit


def _position_standardize(
    values: np.ndarray, player_ids: list[int], meta: dict[int, dict[str, Any]]
) -> np.ndarray:
    output = values.astype(np.float64, copy=True)
    for position in POSITION_SQUAD:
        indices = np.asarray(
            [
                index
                for index, element in enumerate(player_ids)
                if str(meta[element]["position"]) == position
            ],
            dtype=np.int32,
        )
        scale = float(output[indices].std())
        output[indices] = (output[indices] - output[indices].mean()) / max(scale, 1e-6)
    return output


def diversified_utility(
    utilities: np.ndarray,
    player_ids: list[int],
    meta: dict[int, dict[str, Any]],
    rng: np.random.Generator,
    restart: int,
) -> np.ndarray:
    scenario_weights = rng.dirichlet(np.full(utilities.shape[1], 0.30, dtype=np.float64))
    blended = np.asarray(utilities @ scenario_weights, dtype=np.float64)
    standardized = _position_standardize(blended, player_ids, meta)
    noise_scale = (0.10, 0.22, 0.40, 0.70, 1.05, 1.45)[restart % 6]
    noise = rng.normal(0.0, noise_scale, len(player_ids))
    price = _position_standardize(
        np.asarray([float(meta[element]["market_price"]) for element in player_ids]),
        player_ids,
        meta,
    )
    price_tilt = (-0.25, -0.10, 0.0, 0.10, 0.25)[(restart // 6) % 5]
    return standardized + noise + price_tilt * price


def solve_global_proxy_squad(
    player_ids: list[int],
    meta: dict[int, dict[str, Any]],
    objective: np.ndarray,
    *,
    budget: float,
    club_limit: int,
    distant_from: list[set[int]],
    minimum_seed_distance: int,
    excluded_squads: list[set[int]] | None = None,
    random_seed: int = 2026,
) -> Squad:
    if len(objective) != len(player_ids):
        raise ValueError("objective must have one value per player")
    if not 1 <= minimum_seed_distance <= 15:
        raise ValueError("minimum_seed_distance must be in [1, 15]")
    player_index = {element: index for index, element in enumerate(player_ids)}
    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    highs.setOptionValue("random_seed", int(random_seed))
    highs.setOptionValue("mip_rel_gap", 1e-8)
    highs.setOptionValue("time_limit", 15.0)
    selected = highs.addVariables(
        len(player_ids),
        lb=0,
        ub=1,
        type=highspy.HighsVarType.kInteger,
        out_array=True,
    )

    def variable(element: int):
        return selected[player_index[element]]

    highs.addConstr(sum(variable(element) for element in player_ids) == 15)
    for position, count in POSITION_SQUAD.items():
        highs.addConstr(
            sum(
                variable(element)
                for element in player_ids
                if str(meta[element]["position"]) == position
            )
            == count
        )
    for club in sorted({int(meta[element]["team_id"]) for element in player_ids}):
        highs.addConstr(
            sum(
                variable(element)
                for element in player_ids
                if int(meta[element]["team_id"]) == club
            )
            <= club_limit
        )
    highs.addConstr(
        sum(float(meta[element]["market_price"]) * variable(element) for element in player_ids)
        <= budget
    )
    maximum_overlap = 15 - minimum_seed_distance
    for reference in distant_from:
        highs.addConstr(
            sum(variable(element) for element in reference if element in player_index)
            <= maximum_overlap
        )
    for old_squad in excluded_squads or []:
        highs.addConstr(
            sum(variable(element) for element in old_squad if element in player_index) <= 14
        )
    highs.maximize(
        sum(float(objective[index]) * selected[index] for index in range(len(player_ids)))
    )
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"Global proxy solve failed: {highs.getModelStatus()}")
    solution = squad_key(
        element for element in player_ids if highs.val(variable(element)) > 0.5
    )
    if not is_legal_squad(solution, meta, budget=budget, club_limit=club_limit):
        raise RuntimeError("Global proxy solve returned an illegal squad")
    return solution


def _weighted_sample_without_replacement(
    values: list[int], scores: np.ndarray, count: int, rng: np.random.Generator
) -> list[int]:
    if len(values) < count:
        return []
    shifted = scores - scores.max()
    probabilities = np.exp(np.clip(shifted, -12.0, 0.0))
    probabilities /= probabilities.sum()
    return list(map(int, rng.choice(values, size=count, replace=False, p=probabilities)))


def crossover_squads(
    left: Squad,
    right: Squad,
    meta: dict[int, dict[str, Any]],
    player_index: dict[int, int],
    utility: np.ndarray,
    rng: np.random.Generator,
    *,
    budget: float,
    club_limit: int,
    attempts: int = 96,
) -> Squad | None:
    union = set(left) | set(right)
    for _ in range(attempts):
        child: list[int] = []
        for position, count in POSITION_SQUAD.items():
            eligible = [
                element for element in union if str(meta[element]["position"]) == position
            ]
            jitter = rng.normal(0.0, 0.65, len(eligible))
            scores = np.asarray(
                [utility[player_index[element]] for element in eligible], dtype=np.float64
            ) + jitter
            child.extend(
                _weighted_sample_without_replacement(eligible, scores, count, rng)
            )
        key = squad_key(child)
        if (
            key != left
            and key != right
            and is_legal_squad(key, meta, budget=budget, club_limit=club_limit)
        ):
            return key
    return None


def mutate_squad(
    parent: Squad,
    meta: dict[int, dict[str, Any]],
    eligible_by_position: dict[str, list[int]],
    player_index: dict[int, int],
    utility: np.ndarray,
    rng: np.random.Generator,
    *,
    budget: float,
    club_limit: int,
    steps: int,
) -> Squad | None:
    current = parent
    for _ in range(steps):
        changed = False
        for _ in range(96):
            outgoing = int(rng.choice(current))
            position = str(meta[outgoing]["position"])
            pool = [element for element in eligible_by_position[position] if element not in current]
            if not pool:
                continue
            pool_scores = np.asarray(
                [utility[player_index[element]] for element in pool], dtype=np.float64
            )
            incoming = _weighted_sample_without_replacement(pool, pool_scores, 1, rng)[0]
            candidate = squad_key((*set(current).difference({outgoing}), incoming))
            if is_legal_squad(candidate, meta, budget=budget, club_limit=club_limit):
                current = candidate
                changed = True
                break
        if not changed:
            return None
    return current if current != parent else None


def _proxy_scores(
    squads: list[Squad],
    utilities: np.ndarray,
    player_index: dict[int, int],
) -> np.ndarray:
    return np.asarray(
        [
            utilities[[player_index[element] for element in squad]].sum(axis=0)
            for squad in squads
        ],
        dtype=np.float64,
    )


def select_evolution_population(
    squads: Iterable[Squad],
    utilities: np.ndarray,
    player_index: dict[int, int],
    limit: int,
) -> list[Squad]:
    unique = list(dict.fromkeys(squads))
    if len(unique) <= limit:
        return unique
    scores = _proxy_scores(unique, utilities, player_index)
    scale = np.maximum(scores.std(axis=0), 1e-6)
    standardized = (scores - scores.max(axis=0)) / scale
    aggregate = standardized.mean(axis=1) + 0.15 * standardized.min(axis=1)
    chosen: set[int] = set()
    per_scenario = max(2, math.ceil(limit / (2 * scores.shape[1])))
    for scenario in range(scores.shape[1]):
        chosen.update(
            np.argsort(-scores[:, scenario], kind="stable")[:per_scenario].tolist()
        )
    ordered = np.argsort(-aggregate, kind="stable")
    for index in ordered:
        chosen.add(int(index))
        if len(chosen) >= limit:
            break
    selected = sorted(chosen, key=lambda index: aggregate[index], reverse=True)[:limit]
    return [unique[index] for index in selected]


def generate_global_squads(
    seeds: list[Squad],
    meta: dict[int, dict[str, Any]],
    utilities: np.ndarray,
    *,
    budget: float,
    club_limit: int,
    restarts: int,
    population_size: int,
    generations: int,
    offspring_per_generation: int,
    minimum_seed_distance: int,
    seed: int,
) -> GlobalSearchResult:
    if restarts < 1 or population_size < 2 or generations < 0 or offspring_per_generation < 1:
        raise ValueError("invalid global-search configuration")
    player_ids = sorted(meta)
    player_index = {element: index for index, element in enumerate(player_ids)}
    eligible_by_position = {
        position: [
            element
            for element in player_ids
            if str(meta[element]["position"]) == position
        ]
        for position in POSITION_SQUAD
    }
    seed_sets = [set(squad) for squad in seeds]
    rng = np.random.default_rng(seed)
    milp: list[Squad] = []
    for restart in range(restarts):
        objective = diversified_utility(utilities, player_ids, meta, rng, restart)
        try:
            solution = solve_global_proxy_squad(
                player_ids,
                meta,
                objective,
                budget=budget,
                club_limit=club_limit,
                distant_from=seed_sets,
                minimum_seed_distance=minimum_seed_distance,
                excluded_squads=[set(squad) for squad in milp],
                random_seed=seed + restart,
            )
        except RuntimeError:
            continue
        if solution not in milp:
            milp.append(solution)
    if len(milp) < min(8, restarts):
        raise RuntimeError(f"Only generated {len(milp)} distant global MILP squads")

    population = select_evolution_population(milp, utilities, player_index, population_size)
    evolution: set[Squad] = set()
    rejected_near_seed = 0
    rejected_illegal = 0
    attempted = 0
    completed = 0
    for generation in range(generations):
        offspring: set[Squad] = set()
        attempts = 0
        maximum_attempts = offspring_per_generation * 8
        while len(offspring) < offspring_per_generation and attempts < maximum_attempts:
            attempts += 1
            attempted += 1
            left_index, right_index = rng.integers(0, len(population), size=2)
            left = population[int(left_index)]
            right = population[int(right_index)]
            scenario = int(rng.integers(0, utilities.shape[1]))
            utility = utilities[:, scenario]
            child = crossover_squads(
                left,
                right,
                meta,
                player_index,
                utility,
                rng,
                budget=budget,
                club_limit=club_limit,
            )
            if child is None:
                child = left
            mutated = mutate_squad(
                child,
                meta,
                eligible_by_position,
                player_index,
                utility,
                rng,
                budget=budget,
                club_limit=club_limit,
                steps=int(rng.integers(1, 5)),
            )
            if mutated is None or not is_legal_squad(
                mutated, meta, budget=budget, club_limit=club_limit
            ):
                rejected_illegal += 1
                continue
            if minimum_distance(mutated, seed_sets) < minimum_seed_distance:
                rejected_near_seed += 1
                continue
            if mutated not in milp:
                offspring.add(mutated)
        evolution.update(offspring)
        population = select_evolution_population(
            [*population, *offspring], utilities, player_index, population_size
        )
        completed = generation + 1
    return GlobalSearchResult(
        milp_squads=tuple(milp),
        evolution_squads=tuple(sorted(evolution)),
        generations_completed=completed,
        attempted_offspring=attempted,
        rejected_near_seed=rejected_near_seed,
        rejected_illegal=rejected_illegal,
    )
