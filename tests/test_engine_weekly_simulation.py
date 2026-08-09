from __future__ import annotations

import numpy as np
import pytest

from fplagent_engine.rules import SquadRules
from fplagent_engine.season_state import (
    ChipType,
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    default_chip_inventory,
)
from fplagent_engine.weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from fplagent_engine.weekly_simulation import (
    combine_scenario_regret,
    evaluate_action_paths,
)


def _rules() -> SquadRules:
    return SquadRules(
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


def _state(*, free_transfers: int = 1, bank: int = 250) -> ManagerState:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    squad = tuple(
        PlayerHolding(
            player_id=index + 1,
            position=position,
            team_id=(index // 3) + 1,
            purchase_price=50,
            current_price=50,
            selling_price=50,
        )
        for index, position in enumerate(positions)
    )
    return ManagerState(
        season="2026-27",
        event=2,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=squad,
        bank=bank,
        free_transfers=free_transfers,
        chips=default_chip_inventory(),
        lineup=Lineup(
            starters=(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15),
            bench_order=(2, 6, 7, 12),
            captain=13,
            vice_captain=8,
        ),
    )


def _rows() -> list[dict]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    definitions = [
        (index + 1, position, (index // 3) + 1, 50, 2.0) for index, position in enumerate(positions)
    ]
    definitions.extend(
        [
            (16, "DEF", 6, 60, 9.0),
            (17, "MID", 7, 50, 8.0),
            (18, "FWD", 8, 60, 7.0),
        ]
    )
    rows = []
    for event in (2, 3):
        for element, position, team_id, price, score in definitions:
            player_score = 12.0 if element == 12 else 0.1 if element == 3 else score
            rows.append(
                {
                    "element": element,
                    "event_number": event,
                    "position": position,
                    "team_id": team_id,
                    "market_price": price,
                    "robust_points": player_score,
                    "expected_points": player_score,
                    "p_play": 0.95,
                    "can_select": True,
                    "removed": False,
                }
            )
    return rows


def _paths(actions, simulations: int = 2_000):
    rows = _rows()
    player_ids = sorted({int(row["element"]) for row in rows})
    meta = {}
    means = {}
    for row in rows:
        meta[int(row["element"])] = row
        means[(int(row["element"]), int(row["event_number"]))] = float(row["robust_points"])
    rng = np.random.default_rng(31)
    points = np.zeros((simulations, 2, len(player_ids)), dtype=np.int8)
    for player_offset, element in enumerate(player_ids):
        for event_offset, event in enumerate((2, 3)):
            points[:, event_offset, player_offset] = rng.poisson(
                means[(element, event)], simulations
            ).astype(np.int8)
    played = np.ones_like(points, dtype=bool)
    return evaluate_action_paths(
        actions,
        player_ids=player_ids,
        events=(2, 3),
        points=points,
        played=played,
        player_meta=meta,
    )


def test_shared_worlds_score_after_cost_routes_against_roll() -> None:
    actions = generate_weekly_actions(
        _state(free_transfers=1),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=2,
        max_paid_transfers=1,
    )
    metrics, totals = _paths(actions)

    assert totals.shape == (2_000, 3)
    roll = next(metric for metric in metrics if metric.route_type == "roll")
    free = next(metric for metric in metrics if metric.route_type == "one_free_transfer")
    hit = next(metric for metric in metrics if metric.route_type == "paid_transfer")
    assert roll.mean_delta_to_roll == 0.0
    assert free.mean_delta_to_roll > 0.0
    assert hit.incremental_points_cost == 4
    assert 0.0 <= hit.beat_roll_probability <= 1.0
    assert hit.delta_to_roll_95ci_low <= hit.mean_delta_to_roll
    assert hit.delta_to_roll_95ci_high >= hit.mean_delta_to_roll


def test_robust_synthesis_penalizes_scenario_brittleness() -> None:
    actions = generate_weekly_actions(
        _state(free_transfers=1),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=1,
    )
    central, _ = _paths(actions)
    stressed = [
        metric
        if metric.route_type == "roll"
        else metric.__class__(
            **{
                **metric.__dict__,
                "scenario_regret": metric.scenario_regret + 100.0,
            }
        )
        for metric in central
    ]

    rows = combine_scenario_regret(
        {"central": central, "stress": stressed},
        scenario_weights={"central": 0.5, "stress": 0.5},
        worst_case_weight=0.25,
    )

    assert rows[0]["action_id"] == next(
        metric.action_id for metric in central if metric.route_type == "roll"
    )


def test_action_path_evaluation_requires_one_roll_comparator() -> None:
    actions = generate_weekly_actions(
        _state(),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=1,
    )
    actions = [action for action in actions if action.route_type != "roll"]
    player_ids = sorted({int(row["element"]) for row in _rows()})
    points = np.zeros((2, 2, len(player_ids)), dtype=np.int8)
    played = np.ones_like(points, dtype=bool)
    meta = {int(row["element"]): row for row in _rows()}

    with pytest.raises(ValueError, match="exactly one roll"):
        evaluate_action_paths(
            actions,
            player_ids=player_ids,
            events=(2, 3),
            points=points,
            played=played,
            player_meta=meta,
        )


def test_free_hit_simulation_restores_the_original_squad_after_current_event() -> None:
    state = _state(bank=20)
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    free_hit = next(
        action
        for action in generate_squad_chip_shadow_actions(
            state,
            _rows(),
            _rules(),
            events=(2, 3),
            alternatives_per_chip=1,
        )
        if action.action.chip == ChipType.FREE_HIT
    )
    player_ids = sorted({int(row["element"]) for row in _rows()})
    points = np.zeros((4, 2, len(player_ids)), dtype=np.int8)
    points[:, :, player_ids.index(16)] = 10
    played = np.ones_like(points, dtype=bool)
    meta = {int(row["element"]): row for row in _rows()}

    _, totals = evaluate_action_paths(
        [base[0], free_hit],
        player_ids=player_ids,
        events=(2, 3),
        points=points,
        played=played,
        player_meta=meta,
    )

    assert 16 in free_hit.selected_player_ids
    assert 16 not in dict(free_hit.event_squads)[3]
    assert np.all(totals[:, 1] - totals[:, 0] == 10.0)


def test_scenario_synthesis_rejects_silently_dropped_actions() -> None:
    actions = generate_weekly_actions(
        _state(),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=1,
    )
    metrics, _ = _paths(actions)

    with pytest.raises(ValueError, match="same action IDs"):
        combine_scenario_regret(
            {"central": metrics, "incomplete": metrics[:-1]},
            scenario_weights={"central": 0.5, "incomplete": 0.5},
        )


def test_bench_boost_and_triple_captain_receive_exact_simulated_scoring() -> None:
    state = _state()
    rows = _rows()
    base_actions = generate_weekly_actions(
        state,
        rows,
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    variants = generate_team_chip_shadow_actions(
        state,
        base_actions,
        rows,
        _rules(),
        events=(2, 3),
    )
    actions = [*base_actions, *variants]
    player_ids = sorted({int(row["element"]) for row in rows})
    points = np.full((2, 2, len(player_ids)), 2, dtype=np.int8)
    played = np.ones_like(points, dtype=bool)
    meta = {int(row["element"]): row for row in rows}

    _, totals = evaluate_action_paths(
        actions,
        player_ids=player_ids,
        events=(2, 3),
        points=points,
        played=played,
        player_meta=meta,
    )
    indices = {action.action.chip: index for index, action in enumerate(actions)}
    base_index = indices[None]

    assert np.all(totals[:, indices[ChipType.TRIPLE_CAPTAIN]] - totals[:, base_index] == 2)
    assert np.all(totals[:, indices[ChipType.BENCH_BOOST]] - totals[:, base_index] == 8)
