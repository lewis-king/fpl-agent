from fplagent_data.database import _view_name


def test_view_names_are_stable_and_source_prefixed() -> None:
    assert _view_name("vaastav/player_gameweeks.parquet") == "vaastav_player_gameweeks"
    assert _view_name("fpl/2026-27/preseason/players.parquet") == "fpl_current_players"
