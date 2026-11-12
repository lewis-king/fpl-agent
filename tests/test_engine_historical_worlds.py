from dataclasses import asdict, replace
from datetime import UTC, datetime

import numpy as np
import pytest

from fplagent_engine.historical_worlds import (
    anchor_bins,
    origin_cutoff,
    prefix_transfer_curve,
    ratings_at_origin,
)
from fplagent_engine.team_strength import Fixture


@pytest.mark.parametrize("p", [0., .2, .99, 1.])
def test_minute_shape_preserves_exact_archived_appearance_probability(p):
    result = anchor_bins([.4, .1, .2, .3], p)
    assert result.sum() == pytest.approx(1.)
    assert result[0] == pytest.approx(1 - p)
    assert result[1:].sum() == pytest.approx(p)
    if p:
        np.testing.assert_allclose(result[1:] / p, [1/6, 2/6, 3/6])


@pytest.mark.parametrize("bins,p", [([1, 0, 0, 0], .5), ([1, 2], .5),
                                   ([float("nan"), 0, 0, 0], 0), ([0, -.1, .5, .6], 1)])
def test_invalid_bins_fail_closed(bins, p):
    with pytest.raises(ValueError):
        anchor_bins(bins, p)


def test_terminal_curve_excludes_heldout_and_future_values():
    rows = [{"season": s, "cumulative_value_by_bank": {str(i): i * scale for i in range(6)}}
            for s, scale in (("2023-24", 1.2), ("2024-25", 100.), ("2025-26", 999.))]
    curve, audit = prefix_transfer_curve(rows, "2024-25")
    assert curve == {i: i*1.2 for i in range(6)}
    assert audit["training_seasons"] == ["2023-24"]
    assert audit["observations"] == 1
    rows[-1]["cumulative_value_by_bank"] = {}
    assert prefix_transfer_curve(rows, "2024-25")[0] == curve


def test_future_results_cannot_change_origin_team_strength():
    cutoff = datetime(2024, 8, 25, tzinfo=UTC)
    fixtures = [Fixture("2024-25", 1, 1, datetime(2024, 8, 17, tzinfo=UTC), 1, 2, 10, 20, 2, 0),
                Fixture("2024-25", 2, 2, datetime(2024, 8, 26, tzinfo=UTC), 2, 1, 20, 10, 0, 8)]
    original = ratings_at_origin(fixtures, "2024-25", cutoff, (1.5, 1.1))
    changed = ratings_at_origin([fixtures[0], replace(fixtures[1], home_goals=30, away_goals=0)],
                                 "2024-25", cutoff, (1.5, 1.1))
    assert {k: asdict(v) for k, v in original.states.items()} == {k: asdict(v) for k, v in changed.states.items()}
    assert all(v.matches == 1 for v in original.states.values())


def test_missing_origin_metadata_uses_earlier_archive_and_reports_price_limitations():
    observed = datetime(2025, 9, 30, 20, tzinfo=UTC)
    fixtures = [{"event": 8, "observed_at": observed.isoformat(),
                 "kickoff_time": datetime(2025, 10, 18, 12, 30, tzinfo=UTC)}]
    cutoff, audit = origin_cutoff({1: {"deadline_at": None, "deadline_proxy_available": 0}}, fixtures, 8)
    assert cutoff == observed
    assert audit["origin_deadline_metadata_missing"]
    assert audit["same_event_player_snapshot_rows"] == 0
    assert "lagged prices" in audit["price_caveat"]
    # A future archive cannot be relabelled as pre-deadline evidence.
    fixtures[0]["observed_at"] = "2025-10-19T10:00:00+00:00"
    with pytest.raises(ValueError, match="strictly before"):
        origin_cutoff({1: {"deadline_at": None}}, fixtures, 8)
