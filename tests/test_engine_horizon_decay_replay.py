from __future__ import annotations

import pytest

from fplagent_engine.horizon_decay_replay import (
    PolicyConfig,
    _fixture_multiplier,
    _promotion_gate,
    _schedule_at_origin,
    _select_configuration,
    _selection_neighbour_stability,
    build_deadline_horizon_rows,
    policy_grid,
)


def _coefficients() -> dict[str, dict[str, float | int]]:
    return {
        position: {
            "rows": 100,
            "player_seasons": 10,
            "home_coefficient": 0.1,
            "easier_fixture_coefficient": 0.2,
        }
        for position in ("GK", "DEF", "MID", "FWD")
    }


def test_policy_grid_deduplicates_one_week_decay() -> None:
    configs = policy_grid()

    assert len(configs) == 16
    assert configs[0] == PolicyConfig(1, 1.0)
    assert len({config.config_id for config in configs}) == len(configs)
    assert PolicyConfig(8, 0.88) in configs


def test_fixture_multiplier_rewards_easier_home_fixture_and_handles_blank() -> None:
    coefficients = _coefficients()

    easy_home = _fixture_multiplier("DEF", 1.0, 1.0, 2.0, coefficients)
    hard_away = _fixture_multiplier("DEF", 1.0, 0.0, 4.0, coefficients)

    assert easy_home > hard_away
    assert _fixture_multiplier("DEF", 0.0, 0.0, None, coefficients) == 0.0
    assert _fixture_multiplier("DEF", 2.0, 0.5, 3.0, coefficients) == pytest.approx(2.0)


def test_schedule_never_uses_a_future_snapshot() -> None:
    snapshots = {
        ("2024-25", 1): [
            {
                "event": 3,
                "team_h": 1,
                "team_a": 2,
                "team_h_difficulty": 2,
                "team_a_difficulty": 4,
            }
        ],
        ("2024-25", 4): [
            {
                "event": 3,
                "team_h": 1,
                "team_a": 2,
                "team_h_difficulty": 5,
                "team_a_difficulty": 1,
            }
        ],
    }

    schedule, selected = _schedule_at_origin(
        season="2024-25",
        origin_event=3,
        fixture_by_snapshot=snapshots,
        available_snapshots={"2024-25": [1, 4]},
    )

    assert selected == 1
    assert schedule[(3, 1)]["fixture_difficulty"] == 2.0


def test_future_horizon_rows_freeze_origin_player_information_and_hide_outcomes() -> None:
    forecast = {
        ("2024-25", 1): [
            {
                "season": "2024-25",
                "event_number": 1,
                "element": 10,
                "player_name": "Player",
                "position": "MID",
                "team_id": 1,
                "market_price": 75.0,
                "expected_points": 5.0,
                "target_points": 12.0,
                "p_play": 0.9,
            }
        ]
    }
    features = {
        ("2024-25", 1, 10): {
            "fixture_count": 1.0,
            "home_fraction": 1.0,
            "fixture_difficulty": 3.0,
            "target_minutes": 90.0,
        }
    }
    fixtures = {
        ("2024-25", 1): [
            {
                "event": 1,
                "team_h": 1,
                "team_a": 2,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
            },
            {
                "event": 2,
                "team_h": 2,
                "team_a": 1,
                "team_h_difficulty": 4,
                "team_a_difficulty": 2,
            },
        ]
    }

    rows, lineage = build_deadline_horizon_rows(
        season="2024-25",
        origin_event=1,
        horizon=2,
        end_event=8,
        forecast_by_event=forecast,
        feature_by_key=features,
        fixture_by_snapshot=fixtures,
        available_snapshots={"2024-25": [1]},
        coefficients=_coefficients(),
    )

    current, future = rows
    assert current["expected_points"] == 5.0
    assert current["target_points"] == 12.0
    assert future["target_points"] == 0.0
    assert future["target_minutes"] == 0.0
    assert future["market_price"] == current["market_price"]
    assert future["p_play"] == current["p_play"]
    assert future["forecast_origin_event"] == 1
    assert future["forecast_lead"] == 1
    assert lineage["snapshot_event"] == 1


def _path(points: int, event_points: list[int] | None = None) -> dict:
    values = event_points or [points // 8] * 8
    return {
        "net_points": points,
        "events": [{"net_points": value} for value in values],
    }


def test_configuration_selection_uses_cross_season_regret_not_pooled_ceiling() -> None:
    stable = PolicyConfig(5, 0.88)
    volatile = PolicyConfig(8, 1.0)
    paths = {
        ("2023-24", stable.config_id): _path(100),
        ("2024-25", stable.config_id): _path(100),
        ("2025-26", stable.config_id): _path(100),
        ("2023-24", volatile.config_id): _path(120),
        ("2024-25", volatile.config_id): _path(70),
        ("2025-26", volatile.config_id): _path(100),
    }

    selected, ranking = _select_configuration(paths, (stable, volatile))

    assert selected == stable
    assert ranking[0]["worst_regret"] < ranking[1]["worst_regret"]


def test_promotion_gate_requires_untouched_test_improvement() -> None:
    incumbent = PolicyConfig(8, 0.88)
    selected = PolicyConfig(5, 0.88)
    paths = {
        ("2023-24", incumbent.config_id): _path(100),
        ("2024-25", incumbent.config_id): _path(100),
        ("2025-26", incumbent.config_id): _path(100, [10] * 8),
        ("2023-24", selected.config_id): _path(102),
        ("2024-25", selected.config_id): _path(103),
        ("2025-26", selected.config_id): _path(108, [11] * 8),
    }

    gate = _promotion_gate(
        selected=selected,
        incumbent=incumbent,
        paths=paths,
        selection_stability={"passed": True},
    )

    assert gate["passed"] is True
    assert gate["frozen_test_total_delta"] == 8


def test_selection_neighbour_stability_rejects_an_isolated_peak() -> None:
    selected = PolicyConfig(5, 0.88)
    ranking = [
        {
            "config_id": config.config_id,
            "selection_total_points": (
                200 if config == selected else 180
            ),
        }
        for config in policy_grid()
    ]

    stability = _selection_neighbour_stability(selected, ranking)

    assert stability["passed"] is False
    assert stability["supported_neighbours"] == 0
