import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_engine.cli import parser
from fplagent_engine.rules import SquadRules
from fplagent_engine.weekly_rehearsal import (
    build_synthetic_manager_snapshot,
    run_weekly_rehearsal,
)


def _rules() -> SquadRules:
    return SquadRules(
        budget=1000,
        squad_size=15,
        starting_size=11,
        club_limit=3,
        squad_positions={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        minimum_starters={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        maximum_starters={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_free_transfers=5,
        scoring={},
    )


def _rows() -> list[dict[str, Any]]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return [
        {
            "element": element,
            "event_number": event,
            "position": position,
            "team_id": ((element - 1) // 3) + 1,
            "team_name": f"Team {((element - 1) // 3) + 1}",
            "player_name": f"Player {element}",
            "market_price": 50,
        }
        for event in (2, 3)
        for element, position in enumerate(positions, start=1)
    ]


def _decision() -> dict[str, Any]:
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    return {
        "decision": {
            "candidate": {
                "selected": list(range(1, 16)),
                "lineups": {
                    "1": {
                        "starters": starters,
                        "bench_order": bench,
                        "captain": 13,
                        "vice_captain": 8,
                    }
                },
            }
        }
    }


def test_published_gw1_squad_becomes_explicit_zero_authority_state() -> None:
    snapshot = build_synthetic_manager_snapshot(
        _decision(),
        _rows(),
        event=2,
        observed_at="2026-08-25T12:00:00+00:00",
        rules=_rules(),
    )

    assert snapshot["status"] == "connected"
    assert snapshot["free_transfers"] == 1
    assert snapshot["bank"] == 250
    assert len(snapshot["picks"]) == 15
    assert [row["position"] for row in snapshot["picks"]] == list(range(1, 16))
    assert snapshot["rehearsal"]["decision_authority"] is False


def test_rehearsal_runs_weekly_runner_without_publishing_production(tmp_path: Path) -> None:
    forecast = tmp_path / "forecast.parquet"
    component = tmp_path / "component.parquet"
    decision = tmp_path / "gw1.json"
    schedule = tmp_path / "schedule.json"
    report = tmp_path / "report.md"
    pq.write_table(pa.Table.from_pylist(_rows()), forecast)
    pq.write_table(pa.Table.from_pylist(_rows()), component)
    decision.write_text(json.dumps(_decision()), encoding="utf-8")
    schedule.write_text("{}\n", encoding="utf-8")

    def runner(_rules: SquadRules, **kwargs: Any) -> dict[str, Any]:
        result = {
            "selected_action_id": "roll",
            "action_summaries": [
                {
                    "action_id": "roll",
                    "transfers": [],
                    "captain_player_id": 13,
                    "captain_name": "Player 13",
                    "vice_captain_player_id": 8,
                    "vice_captain_name": "Player 8",
                    "starter_player_ids": list(range(1, 12)),
                    "bench_player_ids": list(range(12, 16)),
                }
            ],
        }
        Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["output_path"]).write_text(json.dumps(result), encoding="utf-8")
        return result

    result = run_weekly_rehearsal(
        event=2,
        horizon=2,
        observed_at="2026-08-25T12:00:00+00:00",
        residual_simulations=5,
        component_simulations=7,
        forecast_path=forecast,
        component_forecast_path=component,
        gw1_decision_path=decision,
        schedule_receipt_path=schedule,
        output_root=tmp_path / "rehearsal",
        report_path=report,
        rules_loader=_rules,
        decision_runner=runner,
    )

    assert result["status"] == "complete"
    assert result["decision_authority"] is False
    assert result["selected_action_id"] == "roll"
    assert result["simulation_config"]["residual_simulations"] == 5
    assert result["simulation_config"]["component_simulations"] == 7
    assert Path(result["receipt_path"]).is_file()
    assert "zero — synthetic QA only" in report.read_text(encoding="utf-8")


def test_weekly_rehearsal_command_is_exposed() -> None:
    args = parser().parse_args(
        [
            "rehearse-weekly-decision",
            "--event",
            "2",
            "--horizon",
            "4",
            "--residual-simulations",
            "100",
        ]
    )
    assert args.command == "rehearse-weekly-decision"
    assert args.event == 2
    assert args.horizon == 4
    assert args.residual_simulations == 100
