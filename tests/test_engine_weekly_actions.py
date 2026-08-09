from __future__ import annotations

import pytest

from fplagent_engine.rules import SquadRules
from fplagent_engine.season_state import (
    ChipStatus,
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
            player_score = score
            if element == 12:
                player_score = 12.0
            if element == 3:
                player_score = 0.1
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


def test_roll_reoptimizes_xi_and_captain_from_all_fifteen_players() -> None:
    actions = generate_weekly_actions(
        _state(),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )

    roll = actions[0]
    assert roll.route_type == "roll"
    assert 12 in roll.action.lineup.starters
    assert roll.action.lineup.captain == 12
    assert 12 not in roll.action.lineup.bench_order


def test_action_funnel_contains_roll_free_transfer_and_after_cost_hit() -> None:
    actions = generate_weekly_actions(
        _state(free_transfers=1),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=2,
        max_paid_transfers=1,
    )

    by_type = {action.route_type: action for action in actions}
    assert set(by_type) == {"roll", "one_free_transfer", "paid_transfer"}
    assert by_type["one_free_transfer"].incremental_points_cost == 0
    assert by_type["paid_transfer"].incremental_points_cost == 4
    assert len(by_type["paid_transfer"].action.transfers) == 2
    assert by_type["paid_transfer"].decision_utility == (
        by_type["paid_transfer"].gross_horizon_utility - 4
    )


def test_every_generated_action_passes_exact_state_transition() -> None:
    actions = generate_weekly_actions(
        _state(free_transfers=2),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=2,
        max_total_transfers=2,
    )

    assert actions
    for action in actions:
        assert len(action.outcome.gameweek.squad) == 15
        assert len(action.action.lineup.starters) == 11
        assert len(action.action.lineup.bench_order) == 4
        assert action.action.lineup.captain in action.action.lineup.starters


def test_exact_selling_value_and_bank_block_unaffordable_upgrade() -> None:
    rows = _rows()
    state = _state(free_transfers=1, bank=0)
    actions = generate_weekly_actions(
        state,
        rows,
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=1,
    )

    transfer = next(action for action in actions if action.route_type == "one_free_transfer")
    assert all(move.incoming.player_id != 16 for move in transfer.action.transfers)


def test_terminal_transfer_curve_values_the_bank_after_the_fixed_horizon() -> None:
    curve = {0: 0.0, 1: 1.0, 2: 2.5, 3: 3.5, 4: 4.0, 5: 4.2}
    actions = generate_weekly_actions(
        _state(free_transfers=1),
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=1,
        terminal_free_transfer_curve=curve,
    )
    roll = next(action for action in actions if action.route_type == "roll")
    transfer = next(action for action in actions if action.route_type == "one_free_transfer")

    assert roll.next_free_transfers == 2
    assert roll.terminal_free_transfers == 3
    assert transfer.next_free_transfers == 1
    assert transfer.terminal_free_transfers == 2
    assert roll.terminal_transfer_value == pytest.approx(curve[3] * 0.88**2)
    assert transfer.terminal_transfer_value == pytest.approx(curve[2] * 0.88**2)


def test_terminal_transfer_curve_rejects_missing_or_decreasing_banks() -> None:
    with pytest.raises(ValueError, match="banks 0 through 5"):
        generate_weekly_actions(
            _state(),
            _rows(),
            _rules(),
            events=(2,),
            terminal_free_transfer_curve={0: 0.0, 1: 1.0},
        )
    with pytest.raises(ValueError, match="non-decreasing"):
        generate_weekly_actions(
            _state(),
            _rows(),
            _rules(),
            events=(2,),
            terminal_free_transfer_curve={0: 0.0, 1: 1.0, 2: 0.5, 3: 1.5, 4: 2.0, 5: 2.5},
        )


def test_team_chip_variants_are_legal_shadow_actions_with_retention_evidence() -> None:
    state = _state()
    base = generate_weekly_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_transfer_count=1,
        max_total_transfers=0,
    )
    variants = generate_team_chip_shadow_actions(
        state,
        base,
        _rows(),
        _rules(),
        events=(2, 3),
    )

    assert {variant.action.chip for variant in variants} == {
        ChipType.BENCH_BOOST,
        ChipType.TRIPLE_CAPTAIN,
    }
    assert all(variant.parent_action_id == base[0].action_id for variant in variants)
    assert all(variant.chip_current_proxy_uplift > 0.0 for variant in variants)
    assert all(variant.retained_chip_proxy_value > 0.0 for variant in variants)
    assert all(variant.chip_horizon_complete is False for variant in variants)
    for variant in variants:
        matching = next(
            slot
            for slot in variant.outcome.next_manager.chips
            if slot.half == 1 and slot.chip == variant.action.chip
        )
        assert matching.status == ChipStatus.PLAYED


def test_wildcard_and_free_hit_search_have_distinct_persistent_state() -> None:
    state = _state(free_transfers=3, bank=20)
    variants = generate_squad_chip_shadow_actions(
        state,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_chip=1,
    )

    assert {variant.action.chip for variant in variants} == {
        ChipType.WILDCARD,
        ChipType.FREE_HIT,
    }
    wildcard = next(
        variant for variant in variants if variant.action.chip == ChipType.WILDCARD
    )
    free_hit = next(
        variant for variant in variants if variant.action.chip == ChipType.FREE_HIT
    )
    original = tuple(sorted(player.player_id for player in state.squad))

    assert wildcard.incremental_points_cost == 0
    assert wildcard.next_free_transfers == 3
    assert wildcard.outcome.next_manager is not None
    assert tuple(
        sorted(player.player_id for player in wildcard.outcome.next_manager.squad)
    ) == wildcard.selected_player_ids
    assert dict(wildcard.event_squads) == {
        2: wildcard.selected_player_ids,
        3: wildcard.selected_player_ids,
    }

    assert free_hit.incremental_points_cost == 0
    assert free_hit.next_free_transfers == 3
    assert free_hit.outcome.next_manager is not None
    assert free_hit.outcome.next_manager.squad == state.squad
    assert free_hit.outcome.next_manager.bank == state.bank
    assert dict(free_hit.event_squads)[2] == free_hit.selected_player_ids
    assert dict(free_hit.event_squads)[3] == original
    assert set(free_hit.lineups[1].lineup.starters) <= set(original)


def test_squad_chip_search_respects_gw1_and_consecutive_free_hit_rules() -> None:
    assert (
        generate_squad_chip_shadow_actions(
            _state(),
            _rows(),
            _rules(),
            events=(2, 3),
            alternatives_per_chip=1,
        )
        != []
    )
    event_one = _state()
    event_one = ManagerState(
        **{
            **event_one.__dict__,
            "event": 1,
        }
    )
    assert (
        generate_squad_chip_shadow_actions(
            event_one,
            [
                {**row, "event_number": int(row["event_number"]) - 1}
                for row in _rows()
            ],
            _rules(),
            events=(1, 2),
            alternatives_per_chip=1,
        )
        == []
    )

    prior_free_hit = ManagerState(
        **{
            **_state().__dict__,
            "previous_chip": ChipType.FREE_HIT,
            "previous_chip_event": 1,
        }
    )
    variants = generate_squad_chip_shadow_actions(
        prior_free_hit,
        _rows(),
        _rules(),
        events=(2, 3),
        alternatives_per_chip=1,
    )
    assert {variant.action.chip for variant in variants} == {ChipType.WILDCARD}
