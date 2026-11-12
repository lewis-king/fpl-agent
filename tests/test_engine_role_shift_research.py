from copy import deepcopy

import pytest

from fplagent_engine.role_shift_research import FEATURE_NAMES, design, lagged_role_signal


def _history():
    return [
        {"season": "2025-26", "event": event, "element": 1, "minutes": minutes, "fixture_count": 1}
        for event, minutes in enumerate([90, 90, 90, 90, 90, 0, 0, 90], 1)
    ]


def test_role_loss_uses_disjoint_blocks_and_not_current_or_future_outcomes():
    history = _history()
    before = lagged_role_signal(history, season="2025-26", event=8, element=1)
    assert before["loss_of_regular_role"]
    assert before["recent_appearance"] == 0
    assert before["older_full_minutes"] == 1
    assert before["observed_events"] == list(range(1, 8))
    history[-1]["minutes"] = 0
    history.append(dict(history[-1], event=9, minutes=90))
    assert lagged_role_signal(history, season="2025-26", event=8, element=1) == before
    assert len(design(0.9, before)) == len(FEATURE_NAMES)


def test_blanks_doubles_other_players_and_previous_seasons_are_not_role_losses():
    history = _history()[:5]
    original = lagged_role_signal(history, season="2025-26", event=8, element=1)
    history += [
        dict(history[0], event=6, minutes=0, fixture_count=0),
        dict(history[0], event=7, minutes=0, fixture_count=2),
        dict(history[0], event=6, minutes=0, season="2024-25"),
        dict(history[0], event=7, minutes=0, element=2),
    ]
    assert lagged_role_signal(history, season="2025-26", event=8, element=1) == original
    assert not original["loss_of_regular_role"]


def test_finishing_variance_does_not_change_role_signal():
    history = _history()[:5]
    before = lagged_role_signal(history, season="2025-26", event=6, element=1)
    after = deepcopy(history)
    for r in after:
        r.update(points=20, xg=3, goals=5)
    assert lagged_role_signal(after, season="2025-26", event=6, element=1) == before


def test_early_season_history_is_not_claimed_as_established_role_change():
    signal = lagged_role_signal(_history(), season="2025-26", event=3, element=1)
    assert signal["status"] == "insufficient_prior"
    assert not signal["loss_of_regular_role"]


def test_unknown_minutes_and_duplicates_fail():
    history = _history()
    history[0]["minutes"] = float("nan")
    with pytest.raises(ValueError, match="Unknown minutes"):
        lagged_role_signal(history, season="2025-26", event=8, element=1)
    history = _history()
    history.append(dict(history[0]))
    with pytest.raises(ValueError, match="Duplicate"):
        lagged_role_signal(history, season="2025-26", event=8, element=1)
