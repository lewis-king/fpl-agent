from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from test_engine_weekly_simulation import _rows, _rules, _state

from fplagent_engine.season_state import ChipType, apply_action
from fplagent_engine.weekly_actions import (
    generate_squad_chip_shadow_actions,
    generate_team_chip_shadow_actions,
    generate_weekly_actions,
)
from fplagent_engine.weekly_configuration import (
    VALIDATION_SEEDS,
    configuration_identity,
    execution_plan,
    optimise_configurations,
    paired_validation,
    score_configurations,
    select_validated_configurations,
    validate_configurations,
)

WEIGHTS = {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05}
EVENTS = (2, 3)


def _worlds(rows, boosted, boost=20):
    meta = {r["element"]: r for r in rows}
    ids = sorted(meta)
    points = np.full((100, 2, len(ids)), 2, dtype=np.int8)
    points[:, :, ids.index(boosted)] = boost
    return {
        name: {
            "player_ids": ids,
            "player_meta": meta,
            "events": EVENTS,
            "points": points.copy(),
            "played": np.ones_like(points, dtype=bool),
        }
        for name in WEIGHTS
    }


def _setup():
    state, rows, rules = _state(), _rows(), _rules()
    actions = generate_weekly_actions(state, rows, rules, events=EVENTS, max_total_transfers=0)
    boosted = next(p for p in actions[0].action.lineup.bench_order if p > 2)
    worlds = _worlds(rows, boosted)
    return state, rows, rules, actions, boosted, worlds


def test_live_refinement_can_start_and_captain_a_bench_player_without_changing_forecasts():
    state, rows, rules, actions, boosted, worlds = _setup()
    original = configuration_identity(actions)
    configured, audit = optimise_configurations(
        actions, state, rows, rules, worlds, WEIGHTS, events=EVENTS
    )
    assert configuration_identity(actions) == original
    assert configured[0].action_id == actions[0].action_id
    assert configured[0].route_type == "roll"
    for item in configured[0].lineups:
        assert boosted in item.lineup.starters
        assert item.lineup.captain == boosted
    assert configured[0].outcome == apply_action(state, configured[0].action, rules)
    assert configured[0].outcome.gameweek.bank == actions[0].outcome.gameweek.bank
    assert configured[0].selected_player_ids == actions[0].selected_player_ids
    assert rows == _rows()
    assert audit["possible_configurations"] == 2 * 363_000
    assert audit["roster_search_expanded"] is False


def test_reused_frontier_cache_cannot_reuse_a_different_worlds_lineup():
    state, rows, rules, actions, first, worlds = _setup()
    cache = {}
    configured, _ = optimise_configurations(
        actions, state, rows, rules, worlds, WEIGHTS, events=EVENTS, frontier_cache=cache)
    assert configured[0].action.lineup.captain == first
    second = next(p for p in actions[0].selected_player_ids if p > 2 and p != first)
    changed = _worlds(rows, second)
    configured, _ = optimise_configurations(
        actions, state, rows, rules, changed, WEIGHTS, events=EVENTS, frontier_cache=cache)
    assert configured[0].action.lineup.captain == second


def test_chip_routes_keep_links_and_free_hit_restores_exact_event_roster():
    state, rows, rules, ordinary, _boosted, worlds = _setup()
    teams = generate_team_chip_shadow_actions(state, ordinary, rows, rules, events=EVENTS)
    squads = generate_squad_chip_shadow_actions(
        state, rows, rules, events=EVENTS, alternatives_per_chip=1
    )
    actions = ordinary + teams + squads
    configured, audit = optimise_configurations(
        actions, state, rows, rules, worlds, WEIGHTS, events=EVENTS
    )
    assert len(configured) == len(actions)
    for old, new in zip(actions, configured, strict=True):
        assert old.action_id == new.action_id
        assert old.parent_action_id == new.parent_action_id
        assert old.action.transfers == new.action.transfers
        assert old.action.chip == new.action.chip
        assert old.event_squads == new.event_squads
        assert new.outcome == apply_action(state, new.action, rules)
        for item in new.lineups:
            assert set(item.lineup.starters + item.lineup.bench_order) == set(
                dict(new.event_squads).get(item.event, new.selected_player_ids)
            )
    fh = next(a for a in configured if a.action.chip == ChipType.FREE_HIT)
    assert set(fh.lineups[1].lineup.starters + fh.lineups[1].lineup.bench_order) == {
        p.player_id for p in state.squad
    }
    metrics, _ = score_configurations(configured, worlds, events=EVENTS)
    assert set(metrics) == set(WEIGHTS)
    assert audit["unique_frontiers"] < len(actions) * len(EVENTS)


@pytest.mark.parametrize("holdout_boost,accepted", [(20, True), (-20, False)])
def test_independent_validation_can_reject_but_never_reselect(holdout_boost, accepted):
    state, rows, rules, actions, boosted, worlds = _setup()
    configured, _ = optimise_configurations(
        actions, state, rows, rules, worlds, WEIGHTS, events=EVENTS
    )
    frozen = configuration_identity(configured)
    calls = []

    def sampler(*args, **kwargs):
        calls.append(kwargs)
        return _worlds(rows, boosted, holdout_boost), WEIGHTS, {}

    result = validate_configurations(
        actions,
        configured,
        rows,
        events=EVENTS,
        weights=WEIGHTS,
        selected_ids=[configured[0].action_id],
        component_forecast_path=Path("unused"),
        selection_seeds=(11, 12),
        sampler=sampler,
    )
    assert result["passed"] is accepted
    assert calls[0]["seeds"] == VALIDATION_SEEDS
    assert result["holdout_reselection"] is False
    assert configuration_identity(configured) == frozen


def test_validation_preserves_covariance_between_component_worlds():
    signal = np.array([-2, 2] * 50, dtype=float)
    zero = np.zeros((100, 1))
    old = {n: zero.copy() for n in WEIGHTS}
    new = {n: zero.copy() for n in WEIGHTS}
    new["component_anchored"][:, 0] = signal
    new["component_raw"][:, 0] = signal
    actual = paired_validation(old, new, WEIGHTS, 0)
    assert actual["monte_carlo_standard_error"] == pytest.approx(
        0.5 * signal.std(ddof=1) / np.sqrt(len(signal))
    )


def test_validation_rejects_selection_seed_reuse():
    _state_value, rows, _rules_value, actions, _boosted, _worlds_value = _setup()
    with pytest.raises(ValueError, match="seeds overlap"):
        validate_configurations(
            actions,
            actions,
            rows,
            events=EVENTS,
            weights=WEIGHTS,
            selected_ids=[actions[0].action_id],
            component_forecast_path=Path("unused"),
            selection_seeds=VALIDATION_SEEDS,
        )


@pytest.mark.parametrize("passed", [True, False])
@pytest.mark.parametrize("play_chip", [True, False])
def test_production_selects_before_holdout_and_falls_back_atomically(
    monkeypatch, passed, play_chip
):
    import fplagent_engine.weekly_configuration as module

    state, rows, rules, actions, _boosted, worlds = _setup()
    if play_chip:
        actions += generate_team_chip_shadow_actions(state, actions, rows, rules, events=EVENTS)[:1]
    original_hash = configuration_identity(actions)
    metrics, totals = score_configurations(actions, worlds, events=EVENTS)
    order = []

    def selector(candidates, candidate_metrics, candidate_totals):
        order.append("select")
        return {
            "selected_action_id": candidates[0].action_id,
            "marker": len(order),
            "chip_strategy": {
                "operational_recommendation": "bench_boost" if play_chip else "no_chip",
                "recommended_action_id": candidates[1].action_id if play_chip else None,
            },
        }, candidate_metrics

    def validate(originals, configured, *_args, **kwargs):
        assert order == ["select", "select"]
        order.append("validate")
        assert kwargs["selected_ids"] == [a.action_id for a in configured]
        assert configuration_identity(originals) == original_hash
        assert configuration_identity(configured) != original_hash
        return {"passed": passed}

    monkeypatch.setattr(module, "validate_configurations", validate)
    output, _metrics, _totals, result, _base, audit = select_validated_configurations(
        actions,
        state,
        rows,
        rules,
        worlds,
        WEIGHTS,
        metrics,
        totals,
        events=EVENTS,
        selector=selector,
        component_forecast_path=Path("unused"),
        selection_seeds=(11, 12),
    )
    assert order == ["select", "select", "validate"]
    assert result["marker"] == (2 if passed else 1)
    assert (configuration_identity(output) == original_hash) is not passed
    assert audit["status"] == ("validated" if passed else "retained_original")
    assert audit["published_configuration_sha256"] == configuration_identity(output)


def test_execution_plan_uses_chip_specific_captain_and_projection():
    state, rows, rules, ordinary, _boosted, _worlds_value = _setup()
    chip = next(
        a
        for a in generate_team_chip_shadow_actions(state, ordinary, rows, rules, events=EVENTS)
        if a.action.chip == ChipType.TRIPLE_CAPTAIN
    )
    first = chip.lineups[0]
    swapped = replace(
        first.lineup, captain=first.lineup.vice_captain, vice_captain=first.lineup.captain
    )
    changed = replace(
        chip,
        action=replace(chip.action, lineup=swapped),
        lineups=(replace(first, lineup=swapped, projected_points=30.0), *chip.lineups[1:]),
    )
    summary = {"action_id": ordinary[0].action_id, "transfers": [], "event_lineups": []}
    result = {
        "chip_strategy": {
            "operational_recommendation": "triple_captain",
            "recommended_action_id": changed.action_id,
        },
        "action_summaries": [summary],
    }
    plan = execution_plan(result, ordinary + [changed], rows)
    assert plan["action_id"] == ordinary[0].action_id
    assert plan["configuration_action_id"] == changed.action_id
    assert plan["captain_player_id"] == swapped.captain
    assert plan["vice_captain_player_id"] == swapped.vice_captain
    bonus = next(
        r["robust_points"]
        for r in rows
        if r["event_number"] == 2 and r["element"] == swapped.captain
    )
    assert plan["event_lineups"][0]["projected_points"] == 30.0 + bonus
