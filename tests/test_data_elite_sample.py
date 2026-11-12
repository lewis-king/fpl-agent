from __future__ import annotations

import json

import pytest

from fplagent_data.elite_sample import field_exposure, load_elite_sample, summarise_sample


def _manager(elements, captain, points, chips=()):
    return {
        "picks": {"active_chip": None, "picks": [
            {"element": e, "multiplier": 0 if i >= 2 else (2 if e == captain else 1),
             "is_captain": e == captain}
            for i, e in enumerate(elements)]},
        "history": {
            "current": [{"event": w + 1, "points": p, "event_transfers_cost": 4 if w == 1 else 0,
                         "total_points": sum(points[: w + 1])} for w, p in enumerate(points)],
            "chips": [{"name": name, "event": week} for name, week in chips],
        },
    }


def test_sample_summary_counts_ownership_captains_chips_and_net_scores():
    managers = {
        1: _manager([10, 20, 30], 10, [60, 70], chips=[("bboost", 1)]),
        2: _manager([10, 40, 30], 40, [50, 90], chips=[("bboost", 2), ("3xc", 3)]),
    }
    summary = summarise_sample(managers, event=2)
    assert summary["ownership"] == {"10": 1.0, "20": 0.5, "30": 1.0, "40": 0.5}
    assert "30" not in summary["started"]  # Third pick is on the bench.
    assert summary["captaincy"] == {"10": 0.5, "40": 0.5}
    # A chip played after the sampled week is not counted.
    assert summary["chips_played_to_date"] == {"bboost": 1.0}
    assert summary["median_net_points_by_event"] == {"1": 55.0, "2": 76.0}
    with pytest.raises(ValueError):
        summarise_sample({}, event=2)


def test_field_exposure_names_the_bets_against_the_field():
    sample = {"ownership": {"10": 1.0, "20": 0.6, "30": 0.05, "40": 0.3}}
    exposure = field_exposure([30, 40], sample, names={10: "Haaland", 20: "Konsa"})
    assert [row["name"] for row in exposure["against"]] == ["Haaland", "Konsa"]
    assert [row["element"] for row in exposure["differentials"]] == [30]
    assert exposure["expected_shared_players"] == pytest.approx(0.35)


def test_latest_saved_sample_is_loaded(tmp_path):
    assert load_elite_sample(directory=tmp_path) is None
    for week in (9, 10):
        (tmp_path / f"gw{week:02d}.json").write_text(json.dumps({"event": week}))
    assert load_elite_sample(directory=tmp_path)["event"] == 10
    assert load_elite_sample(9, directory=tmp_path)["event"] == 9
    assert load_elite_sample(8, directory=tmp_path) is None


def test_scoreboard_flags_a_review_only_after_a_sustained_gap():
    from fplagent_data.elite_sample import scoreboard

    sample = {
        "event": 6, "managers": 60, "sample_bands": ["top_1k"], "thresholds": {},
        "ownership": {"1": 0.9, "2": 0.4},
        "median_net_points_by_event": {str(e): 60 for e in range(1, 7)},
    }
    level = [{"event": e, "net_points": 58} for e in range(1, 7)]
    board = scoreboard(level, sample, squad=[2], names={1: "Template", 2: "Ours"})
    assert board["status"] == "on_pace"
    assert board["recent_gap"] == -10 and board["season_gap"] == -12
    assert [p["name"] for p in board["widely_owned_missing"]] == ["Template"]
    assert board["decision_authority"] is False

    poor = [{"event": e, "net_points": 49} for e in range(1, 7)]
    assert scoreboard(poor, sample)["status"] == "review"
    assert scoreboard(poor[:3], sample)["status"] == "too_early"
