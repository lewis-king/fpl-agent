from __future__ import annotations

from dataclasses import replace

import pytest

from fplagent_engine.rules import SquadRules
from fplagent_engine.season_state import (
    ActionBundle,
    ChipStatus,
    ChipType,
    EventStatus,
    Lineup,
    ManagerState,
    MarketPlayer,
    PlayerHolding,
    Transfer,
    advance_gameweek_status,
    apply_action,
    calculated_selling_price,
    default_chip_inventory,
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


def _lineup(replace_player: tuple[int, int] | None = None) -> Lineup:
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    if replace_player is not None:
        outgoing, incoming = replace_player
        starters = [incoming if player == outgoing else player for player in starters]
        bench = [incoming if player == outgoing else player for player in bench]
    return Lineup(tuple(starters), tuple(bench), captain=13, vice_captain=8)


def _state(*, event: int = 2, free_transfers: int = 1, bank: int = 250) -> ManagerState:
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
    chips = default_chip_inventory()
    if event >= 20:
        chips = tuple(
            replace(slot, status=ChipStatus.EXPIRED)
            if slot.half == 1
            else replace(slot, status=ChipStatus.AVAILABLE)
            for slot in chips
        )
    return ManagerState(
        season="2026-27",
        event=event,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=squad,
        bank=bank,
        free_transfers=free_transfers,
        chips=chips,
        lineup=_lineup(),
    )


def _defender_transfer() -> Transfer:
    return Transfer(3, MarketPlayer(16, "DEF", 6, 60))


def test_selling_price_gives_half_profit_rounded_down_and_full_loss() -> None:
    assert calculated_selling_price(50, 55) == 52
    assert calculated_selling_price(50, 56) == 53
    assert calculated_selling_price(50, 47) == 47


def test_roll_and_free_transfer_use_update_the_bank_exactly() -> None:
    rolled = apply_action(_state(free_transfers=1), ActionBundle(2, _lineup()), _rules())
    used = apply_action(
        _state(free_transfers=2),
        ActionBundle(2, _lineup((3, 16)), (_defender_transfer(),)),
        _rules(),
    )

    assert rolled.next_manager is not None and rolled.next_manager.free_transfers == 2
    assert used.next_manager is not None and used.next_manager.free_transfers == 2
    assert used.next_manager.bank == 240
    assert used.gameweek.points_cost == 0


def test_transfer_bank_caps_at_five_and_extra_move_costs_four_points() -> None:
    capped = apply_action(_state(free_transfers=5), ActionBundle(2, _lineup()), _rules())
    hit_lineup = replace(_lineup((3, 16)), bench_order=(2, 17, 7, 12))
    hit = apply_action(
        _state(free_transfers=1),
        ActionBundle(
            2,
            hit_lineup,
            (
                _defender_transfer(),
                Transfer(6, MarketPlayer(17, "DEF", 7, 50)),
            ),
        ),
        _rules(),
    )

    assert capped.next_manager is not None and capped.next_manager.free_transfers == 5
    assert hit.gameweek.points_cost == 4
    assert hit.gameweek.incremental_points_cost == 4
    assert hit.next_manager is not None and hit.next_manager.free_transfers == 1


def test_already_committed_hit_is_retained_and_free_transfer_bank_can_be_zero() -> None:
    state = replace(_state(), free_transfers=0, committed_points_cost=4)
    outcome = apply_action(state, ActionBundle(2, _lineup()), _rules())

    assert outcome.gameweek.incremental_points_cost == 0
    assert outcome.gameweek.points_cost == 4
    assert outcome.next_manager is not None
    assert outcome.next_manager.free_transfers == 1


def test_appreciated_held_squad_can_exceed_the_initial_budget() -> None:
    state = _state(bank=0)
    appreciated = tuple(
        replace(
            player,
            current_price=player.current_price + 20,
            selling_price=calculated_selling_price(
                player.purchase_price,
                player.current_price + 20,
            ),
        )
        for player in state.squad
    )
    state = replace(state, squad=appreciated)

    outcome = apply_action(state, ActionBundle(2, _lineup()), _rules())

    assert outcome.gameweek.squad == appreciated
    assert outcome.next_manager.committed_points_cost == 0


def test_wildcard_is_permanent_free_and_preserves_saved_transfer_count() -> None:
    outcome = apply_action(
        _state(event=2, free_transfers=3),
        ActionBundle(
            2,
            _lineup((3, 16)),
            (_defender_transfer(),),
            ChipType.WILDCARD,
        ),
        _rules(),
    )

    assert outcome.gameweek.points_cost == 0
    assert outcome.next_manager is not None
    assert outcome.next_manager.free_transfers == 3
    assert 16 in {player.player_id for player in outcome.next_manager.squad}


def test_free_hit_restores_squad_and_bank_but_consumes_chip() -> None:
    state = _state(event=2, free_transfers=4)
    outcome = apply_action(
        state,
        ActionBundle(
            2,
            _lineup((3, 16)),
            (_defender_transfer(),),
            ChipType.FREE_HIT,
        ),
        _rules(),
    )

    assert outcome.gameweek.bank == 240
    assert outcome.next_manager is not None
    assert outcome.next_manager.squad == state.squad
    assert outcome.next_manager.bank == state.bank
    assert outcome.next_manager.free_transfers == 4
    assert (
        next(
            slot
            for slot in outcome.next_manager.chips
            if slot.half == 1 and slot.chip == ChipType.FREE_HIT
        ).status
        == ChipStatus.PLAYED
    )


def test_free_hit_and_wildcard_are_unavailable_in_gw1() -> None:
    for chip in (ChipType.FREE_HIT, ChipType.WILDCARD):
        with pytest.raises(ValueError, match="Gameweek 1"):
            apply_action(_state(event=1), ActionBundle(1, _lineup(), chip=chip), _rules())


def test_free_hit_cannot_be_played_in_consecutive_gw19_and_gw20() -> None:
    state = replace(
        _state(event=20),
        previous_chip=ChipType.FREE_HIT,
        previous_chip_event=19,
    )

    with pytest.raises(ValueError, match="consecutive"):
        apply_action(state, ActionBundle(20, _lineup(), chip=ChipType.FREE_HIT), _rules())


def test_unused_first_half_chips_expire_and_second_set_unlocks() -> None:
    outcome = apply_action(_state(event=19), ActionBundle(19, _lineup()), _rules())

    assert outcome.next_manager is not None and outcome.next_manager.event == 20
    assert all(
        slot.status == ChipStatus.EXPIRED for slot in outcome.next_manager.chips if slot.half == 1
    )
    assert all(
        slot.status == ChipStatus.AVAILABLE for slot in outcome.next_manager.chips if slot.half == 2
    )


def test_transfer_result_must_still_have_a_legal_lineup() -> None:
    with pytest.raises(ValueError, match="partition"):
        apply_action(
            _state(),
            ActionBundle(2, _lineup(), (_defender_transfer(),)),
            _rules(),
        )


def test_gameweek_finality_cannot_skip_or_move_backwards() -> None:
    gameweek = apply_action(_state(), ActionBundle(2, _lineup()), _rules()).gameweek
    live = advance_gameweek_status(gameweek, EventStatus.LIVE)
    provisional = advance_gameweek_status(live, EventStatus.PROVISIONAL)
    final = advance_gameweek_status(provisional, EventStatus.FINAL)

    assert final.status == EventStatus.FINAL
    with pytest.raises(ValueError, match="exactly one"):
        advance_gameweek_status(gameweek, EventStatus.PROVISIONAL)
    with pytest.raises(ValueError, match="exactly one"):
        advance_gameweek_status(final, EventStatus.PROVISIONAL)
