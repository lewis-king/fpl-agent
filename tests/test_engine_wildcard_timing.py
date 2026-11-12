from dataclasses import replace

import numpy as np
import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.season_state import ChipType
from fplagent_engine.wildcard_timing import (
    InformationShock,
    TimingConfig,
    compare_frozen,
    extend_origin_forecast,
    ordinary_actions,
    reprice,
    revealed_rows,
    rollout,
    wildcard_action,
)


def setup():
    rows = [dict(r, fixture_count=1, home_fraction=0.5, fixture_difficulty=3) for r in _rows()]
    rows += [dict(r, event_number=4) for r in rows if r["event_number"] == 3]
    cfg = TimingConfig(planning_horizon=2, solver_seconds=10)
    roots = ordinary_actions(_state(), rows, _rules(), events=(2, 3), config=cfg)
    root = next(r for r in roots if not r.action.transfers)
    return rows, cfg, root


def test_no_future_information_or_outcome_leakage():
    rows, cfg, root = setup()
    shock = InformationShock(4, (12,), 0.1, -5)
    assert revealed_rows(rows, deadline=3, shocks=(shock,)) == revealed_rows(rows, deadline=3)
    _, plain = rollout(_state(), root, rows, _rules(), end_event=4, config=cfg)
    _, shocked = rollout(_state(), root, rows, _rules(), end_event=4, config=cfg, shocks=(shock,))
    assert plain[:2] == shocked[:2]
    with pytest.raises(ValueError, match="Outcomes"):
        revealed_rows([dict(r, target_points=100) for r in rows], deadline=2)
    assert revealed_rows(rows, deadline=4, shocks=(shock,))[11]["market_price"] == 45


def test_wc_later_preserves_ft_and_half_expiry_no_terminal_credit():
    rows, cfg, root = setup()
    plan, ledger = rollout(
        _state(), root, rows, _rules(), end_event=4, wildcard_event=3, config=cfg
    )
    assert [x["chip"] for x in ledger] == [None, "wildcard", None]
    assert ledger[1]["free_transfers_before"] == ledger[1]["free_transfers_after"] == 2
    assert plan.terminal_transfer_value == 0
    assert len(plan.event_squads) == len(plan.lineups) == 3
    with pytest.raises(ValueError, match="half"):
        rollout(_state(), root, rows, _rules(), end_event=20, config=cfg)


def test_wc_united_style_constraints_and_exact_money():
    rows, cfg, _ = setup()
    wc = wildcard_action(
        _state(bank=0), rows, _rules(), events=(2, 3), config=cfg, required=(12,), sold=(8,)
    )
    assert 12 in wc.selected_player_ids and 8 not in wc.selected_player_ids
    assert wc.outcome.gameweek.bank >= 0
    assert wc.incremental_points_cost == 0
    assert wc.next_free_transfers == _state().free_transfers


def test_auth_selling_price_preserved_and_actual_drop_applied():
    rows, _, _ = setup()
    state = _state()
    h = replace(state.squad[0], purchase_price=45, current_price=50, selling_price=46)
    state = replace(state, squad=(h, *state.squad[1:]))
    assert reprice(state, rows).squad[0].selling_price == 46
    changed = [dict(r, market_price=44) if r["element"] == 1 else r for r in rows]
    assert reprice(state, changed).squad[0].selling_price == 44


def test_forecast_extension_has_no_future_player_data_and_zero_blank():
    rows, _, _ = setup()
    coeffs = {
        p: {"home_coefficient": 0.0, "easier_fixture_coefficient": 0.0}
        for p in ["GK", "DEF", "MID", "FWD"]
    }
    extended = extend_origin_forecast(rows, [], end_event=5, coefficients=coeffs)
    assert len(extended) == len(rows) + 18
    assert all(r["expected_points"] == r["p_play"] == 0 for r in extended if r["event_number"] == 5)
    assert [r for r in extended if r["event_number"] < 5] == rows


def test_chips_cannot_collide_or_be_used_twice():
    rows, cfg, root = setup()
    with pytest.raises(ValueError, match="collides"):
        rollout(
            _state(),
            root,
            rows,
            _rules(),
            end_event=4,
            wildcard_event=3,
            chip_calendar=((3, ChipType.BENCH_BOOST),),
            config=cfg,
        )
    with pytest.raises(ValueError):
        rollout(
            _state(),
            root,
            rows,
            _rules(),
            end_event=4,
            chip_calendar=((3, ChipType.BENCH_BOOST), (4, ChipType.BENCH_BOOST)),
            config=cfg,
        )


def test_paired_holdout_scoring_and_reject_shared_samples():
    rows, cfg, root = setup()
    plan, _ = rollout(_state(), root, rows, _rules(), end_event=4, config=cfg)
    charged = replace(plan, action_id="charged", future_points_costs=((3, 4), (4, 4)))
    ids = sorted({r["element"] for r in rows})
    world = {
        "player_ids": ids,
        "player_meta": {r["element"]: r for r in rows},
        "points": np.full((30, 3, len(ids)), 2),
        "played": np.ones((30, 3, len(ids)), dtype=bool),
    }
    with pytest.raises(ValueError, match="independent"):
        compare_frozen(
            [plan, charged], ["hold", "hit"], world, world, events=(2, 3, 4), reference_group="hold"
        )
    validation = {**world, "points": world["points"].copy()}
    result = compare_frozen(
        [plan, charged],
        ["hold", "hit"],
        world,
        validation,
        events=(2, 3, 4),
        reference_group="hold",
    )
    assert result["selected_group"] == "hold"
    assert result["groups"][1]["paired_gain"] == -8
    assert not result["decision_authority"]


def test_team_chip_calendar_replays_legally_and_has_no_overlap():
    from fplagent_engine.wildcard_timing import plan_from_ledger, select_team_chip_calendar

    rows, cfg, _ = setup()
    wc = wildcard_action(_state(), rows, _rules(), events=(2, 3), config=cfg)
    plan, ledger = rollout(_state(), wc, rows, _rules(), end_event=4, wildcard_event=2, config=cfg)
    ids = sorted({r["element"] for r in rows})
    world = {
        "player_ids": ids,
        "player_meta": {r["element"]: r for r in rows},
        "points": np.full((30, 3, len(ids)), 2),
        "played": np.ones((30, 3, len(ids)), dtype=bool),
    }
    calendar = select_team_chip_calendar(plan, world, events=(2, 3, 4), state=_state())
    assert set(calendar) == {3, 4}
    assert set(calendar.values()) == {"bench_boost", "triple_captain"}
    updated = [dict(r, chip=calendar.get(r["event"], r["chip"])) for r in ledger]
    rescored = plan_from_ledger(_state(), updated, rows, _rules(), identity="chipped")
    result = compare_frozen(
        [plan, rescored],
        ["wc", "wc_team_chips"],
        world,
        {**world, "points": world["points"].copy()},
        events=(2, 3, 4),
        reference_group="wc",
    )
    assert result["groups"][1]["paired_gain"] == 10  # Four bench players + extra captain.
    tampered = [dict(r, bank_after=999) for r in updated]
    with pytest.raises(ValueError, match="ledger"):
        plan_from_ledger(_state(), tampered, rows, _rules(), identity="tampered")
