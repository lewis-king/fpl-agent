from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_engine.schedule_rearrangement import (
    build_rearrangement_model,
    evaluate_rearrangement_shadow,
)


def _historical_rows() -> list[dict]:
    rows = []
    for decision_event in (2, 3, 4):
        deadline = datetime(2024, 8, 20, 18, 30, tzinfo=UTC) + timedelta(
            days=7 * (decision_event - 2)
        )
        common = {
            "season": "2024-25",
            "snapshot_sha": f"snapshot-{decision_event}",
            "decision_event": float(decision_event),
            "deadline_at": deadline,
            "observed_at": (deadline - timedelta(days=1)).isoformat(),
        }
        rows.append(
            {
                **common,
                "id": 10,
                "event": None if decision_event < 4 else 6.0,
                "team_h": 1,
                "team_a": 2,
            }
        )
        rows.append(
            {
                **common,
                "id": 11,
                "event": 6.0,
                "team_h": 1,
                "team_a": 3,
            }
        )
    return rows


def test_builds_one_weighted_unassigned_resolution_episode(tmp_path) -> None:
    fixture_path = tmp_path / "fixtures.parquet"
    episode_path = tmp_path / "episodes.parquet"
    model_path = tmp_path / "model.json"
    pq.write_table(pa.Table.from_pylist(_historical_rows()), fixture_path)

    model = build_rearrangement_model(
        fixture_path=fixture_path,
        episode_path=episode_path,
        model_path=model_path,
    )
    episode = pq.read_table(episode_path).to_pylist()[0]

    assert model["episodes"] == 1
    assert model["resolved_episodes"] == 1
    assert model["independent_resolution_batches"] == 1
    assert model["promotion_gate"]["passed"] is False
    assert episode["episode_start_event"] == 2
    assert episode["resolved_at_decision_event"] == 4
    assert episode["assigned_event"] == 6
    assert episode["resolution_delay_events"] == 2
    assert episode["assignment_lead_events"] == 2


def test_rearrangement_shadow_changes_probabilities_without_assigning_official_fixture() -> None:
    schedule = {
        "fixtures": [
            {"fixture_id": 10, "event": None, "team_h": 1, "team_a": 2},
            {"fixture_id": 11, "event": 6, "team_h": 1, "team_a": 3},
        ]
    }
    model = {
        "support": [
            {
                "resolution_delay_events": 2,
                "assignment_lead_events": 2,
                "probability": 1.0,
            }
        ],
        "promotion_gate": {"passed": False},
        "authority": False,
    }

    result = evaluate_rearrangement_shadow(
        schedule,
        current_event=2,
        events=(2, 3, 4, 5, 6),
        model=model,
        simulations=500,
    )
    team_one_event_six = next(
        row
        for row in result["team_event_probabilities"]
        if row["team_id"] == 1 and row["event"] == 6
    )

    assert result["status"] == "ready_shadow"
    assert result["official_schedule_unchanged"] is True
    assert result["decision_authority"] is False
    assert result["fixture_scenarios"][0]["event_probabilities"]["6"] == 1.0
    assert team_one_event_six["probability_double"] == 1.0
    assert schedule["fixtures"][0]["event"] is None


def test_rearrangement_shadow_is_not_needed_for_fully_assigned_schedule() -> None:
    result = evaluate_rearrangement_shadow(
        {"fixtures": [{"fixture_id": 1, "event": 2, "team_h": 1, "team_a": 2}]},
        current_event=2,
        events=(2, 3),
        model={"support": []},
        simulations=500,
    )

    assert result["status"] == "not_applicable"
    assert result["official_schedule_unchanged"] is True
