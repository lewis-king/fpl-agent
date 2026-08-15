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
