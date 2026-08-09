from fplagent_engine.features import MODEL_FEATURES, _current_query


def test_model_features_are_deadline_safe() -> None:
    forbidden = {
        "target_points",
        "target_minutes",
        "minutes_class",
        "xP",
        "event_points",
        "current_points",
    }
    assert forbidden.isdisjoint(MODEL_FEATURES)


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
