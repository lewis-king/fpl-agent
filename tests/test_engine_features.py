import pytest

from fplagent_engine.features import (
    MODEL_FEATURES,
    _current_query,
    assert_independent_forecast_features,
)


def test_model_features_are_deadline_safe() -> None:
    forbidden = {
        "target_points",
        "target_minutes",
        "minutes_class",
        "xP",
        "ep_this",
        "ep_next",
        "event_points",
        "current_points",
    }
    assert forbidden.isdisjoint(MODEL_FEATURES)


@pytest.mark.parametrize("feature", ["xP", "ep_this", "ep_next"])
def test_official_expected_points_fail_the_runtime_contract(feature: str) -> None:
    with pytest.raises(RuntimeError, match="forbidden"):
        assert_independent_forecast_features((*MODEL_FEATURES, feature))


def test_model_has_participation_and_fixture_context() -> None:
    assert {"appearance_rate5", "availability_chance", "fixture_count"}.issubset(
        MODEL_FEATURES
    )


def test_current_feature_horizon_rolls_forward_and_includes_live_history() -> None:
    query = _current_query(5, start_event=7)
    assert "current_player_events" in query
    assert "all_player_events" in query
    assert "generate_series(7, 11)" in query
    assert query.count("BETWEEN 7 AND 11") == 2
    assert "form10_xg" in query
    assert "form38_xa" in query
    assert "form38_minutes" in query


def test_current_features_keep_owned_sale_only_players_at_zero_availability() -> None:
    query = _current_query(5, start_event=3)

    assert "WHEN NOT coalesce(p.can_select, true) THEN 0.0" in query
    assert "OR coalesce(p.can_transact, false)" in query
    assert "p.can_transact" in query
