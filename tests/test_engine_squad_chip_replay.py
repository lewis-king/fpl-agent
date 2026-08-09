from __future__ import annotations

from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.season_state import ChipType
from fplagent_engine.squad_chip_replay import _choose_action
from fplagent_engine.weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_weekly_actions,
)


def _actions():
    state = _state(bank=20)
    rows = _rows()
    ordinary = generate_weekly_actions(
        state,
        rows,
        _rules(),
        events=(2,),
        alternatives_per_transfer_count=1,
        max_total_transfers=3,
        max_paid_transfers=1,
    )
    chips = generate_squad_chip_shadow_actions(
        state,
        rows,
        _rules(),
        events=(2,),
        alternatives_per_chip=1,
    )
    return ordinary, chips


def test_squad_chip_policy_requires_declared_edge_and_confirmed_schedule() -> None:
    ordinary, chips = _actions()

    selected, context = _choose_action(
        ordinary,
        chips,
        threshold=10.0,
        minimum_wildcard_changes=3,
        schedule={"schedule_confirmed": True, "blank_team_count": 2, "double_team_count": 2},
    )

    assert selected.action.chip is None
    assert all(not row["eligible"] for row in context["chip_candidates"])


def test_free_hit_requires_exception_but_wildcard_can_address_structural_decay() -> None:
    ordinary, chips = _actions()

    selected, context = _choose_action(
        ordinary,
        chips,
        threshold=2.0,
        minimum_wildcard_changes=3,
        schedule={"schedule_confirmed": True, "blank_team_count": 0, "double_team_count": 0},
    )

    free_hit = next(
        row for row in context["chip_candidates"] if row["chip"] == ChipType.FREE_HIT.value
    )
    assert selected.action.chip == ChipType.WILDCARD
    assert free_hit["eligible"] is False
    assert free_hit["reason"] == "no confirmed blank/double opportunity"


def test_squad_chip_policy_can_be_disabled_for_no_chip_comparator() -> None:
    ordinary, chips = _actions()

    selected, context = _choose_action(
        ordinary,
        chips,
        threshold=None,
        minimum_wildcard_changes=3,
        schedule=None,
    )

    assert selected.action_id == ordinary[0].action_id
    assert context["chip_candidates"] == []
