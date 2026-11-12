from dataclasses import replace

import numpy as np
import pytest
from test_engine_weekly_configuration import EVENTS, WEIGHTS, _setup

from fplagent_engine.chip_opportunity_audit import exact_opportunities
from fplagent_engine.season_state import ChipType


def test_bb_is_all_fifteen_minus_normal_autosubs_not_bench_percentage():
    _, _, _, actions, _, worlds = _setup()
    for w in worlds.values():
        w["points"][:] = 2
    rows = exact_opportunities(actions[0], worlds, WEIGHTS, EVENTS)
    for row in rows:
        assert row["projected_uplift"] == pytest.approx(8 if row["chip"] == "bench_boost" else 2)
        assert row["sampling_standard_error"] == 0


def test_bb_does_not_double_count_an_automatic_substitute():
    _, _, _, actions, _, worlds = _setup()
    for w in worlds.values():
        w["points"][:] = 2
        # A missing starting GK is automatically replaced by the reserve GK.
        for e, lineup in enumerate(actions[0].lineups):
            keeper = next(p for p in lineup.lineup.starters if w["player_meta"][p]["position"] == "GK")
            idx = w["player_ids"].index(keeper)
            w["points"][:, e, idx] = 0
            w["played"][:, e, idx] = False
    result = exact_opportunities(actions[0], worlds, WEIGHTS, EVENTS)
    assert all(r["projected_uplift"] == pytest.approx(6) for r in result if r["chip"] == "bench_boost")


def test_triple_captain_uses_vice_when_captain_absent_and_zero_when_both_absent():
    _, _, _, actions, _, worlds = _setup()
    for w in worlds.values():
        w["points"][:] = 2
        for e, item in enumerate(actions[0].lineups):
            c, v = (w["player_ids"].index(p) for p in (item.lineup.captain, item.lineup.vice_captain))
            w["points"][:, e, c] = 0
            w["played"][:, e, c] = False
            w["points"][:, e, v] = 9 if e == 0 else 0
            w["played"][:, e, v] = e == 0
    result = exact_opportunities(actions[0], worlds, WEIGHTS, EVENTS)
    assert [r["projected_uplift"] for r in result if r["chip"] == "triple_captain"] == [9., 0.]


def test_explicit_chip_or_incoherent_nonappearance_is_rejected():
    _, _, _, actions, _, worlds = _setup()
    chip = replace(actions[0], action=replace(actions[0].action, chip=ChipType.BENCH_BOOST))
    with pytest.raises(ValueError, match="unchipped"):
        exact_opportunities(chip, worlds, WEIGHTS, EVENTS)
    worlds["residual"]["played"][:] = False
    with pytest.raises(ValueError, match="Nonappearance"):
        exact_opportunities(actions[0], worlds, WEIGHTS, EVENTS)


def test_component_covariance_is_preserved_in_sampling_error():
    _, _, _, actions, _, worlds = _setup()
    for n, w in worlds.items():
        w["points"][:] = 0
        for e, item in enumerate(actions[0].lineups):
            c = w["player_ids"].index(item.lineup.captain)
            w["points"][:, e, c] = 0 if n == "residual" else np.tile([0, 10], len(w["points"]) // 2)
    result = exact_opportunities(actions[0], worlds, WEIGHTS, EVENTS)
    expected = np.tile([0., 5.], 50).std(ddof=1) / 10
    assert all(r["sampling_standard_error"] == pytest.approx(expected)
               for r in result if r["chip"] == "triple_captain")
