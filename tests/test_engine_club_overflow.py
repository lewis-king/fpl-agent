from dataclasses import replace

import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.manager_state_store import _state_from_payload, _state_payload
from fplagent_engine.season_state import (
    ActionBundle,
    ChipType,
    MarketPlayer,
    Transfer,
    apply_action,
    validate_manager_state,
)
from fplagent_engine.weekly_actions import generate_weekly_actions
from fplagent_engine.weekly_continuation_replay import reprice_state


def overflow_state():
    state = _state()
    return replace(
        state, squad=tuple(replace(h, team_id=1) if h.player_id == 4 else h for h in state.squad)
    )


def test_only_proven_existing_overflow_is_allowed_and_serializes():
    state = overflow_state()
    with pytest.raises(ValueError, match="club limit"):
        validate_manager_state(state, _rules())
    state = replace(state, club_overflow_allowed=True)
    validate_manager_state(state, _rules())
    assert _state_from_payload(_state_payload(state)) == state
    outcome = apply_action(state, ActionBundle(2, state.lineup), _rules())
    assert outcome.next_manager.club_overflow_allowed


def test_next_fantasy_transfer_must_repair_overflow():
    state = replace(overflow_state(), club_overflow_allowed=True)
    wrong = Transfer(5, MarketPlayer(16, "DEF", 6, 50))
    lineup = replace(
        state.lineup, starters=tuple(16 if p == 5 else p for p in state.lineup.starters)
    )
    with pytest.raises(ValueError, match="club limit"):
        apply_action(state, ActionBundle(2, lineup, (wrong,)), _rules())
    correct = Transfer(4, MarketPlayer(16, "DEF", 6, 50))
    lineup = replace(
        state.lineup, starters=tuple(16 if p == 4 else p for p in state.lineup.starters)
    )
    outcome = apply_action(state, ActionBundle(2, lineup, (correct,)), _rules())
    assert not outcome.next_manager.club_overflow_allowed
    fh = apply_action(state, ActionBundle(2, lineup, (correct,), ChipType.FREE_HIT), _rules())
    assert fh.next_manager.squad == state.squad
    assert fh.next_manager.club_overflow_allowed


def test_milp_keeps_legal_roll_and_only_generates_repaired_transfers():
    state = replace(overflow_state(), club_overflow_allowed=True)
    rows = [dict(r, team_id=1) if r["element"] == 4 else r for r in _rows()]
    actions = generate_weekly_actions(state, rows, _rules(), events=(2, 3), max_total_transfers=1)
    assert any(a.route_type == "roll" for a in actions)
    assert any(a.action.transfers for a in actions)
    for a in actions:
        if a.action.transfers:
            assert sum(h.team_id == 1 for h in a.outcome.gameweek.squad) <= 3


def test_observed_real_club_move_does_not_spend_a_fantasy_transfer():
    state = replace(_state(), season="2025-26")
    rows = [
        dict(r, team_id=1) if r["element"] == 4 else r for r in _rows() if r["event_number"] == 2
    ]
    updated = reprice_state(state, rows)
    assert updated.club_overflow_allowed
    assert updated.bank == state.bank and updated.free_transfers == state.free_transfers
    assert updated.squad[3].purchase_price == state.squad[3].purchase_price
