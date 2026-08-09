from __future__ import annotations

import json
from pathlib import Path

from fplagent_engine.challenger_registry import ChallengerSpec, build_challenger_registry


def test_registry_never_auto_promotes_historical_pass_without_prospective_sample(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "challenger.json"
    artifact.write_text(json.dumps({"gate": {"passed": True}, "verdict": "PASS_SHADOW"}))
    scoreboard = tmp_path / "scoreboard.json"
    scoreboard.write_text(
        json.dumps(
            {
                "version": "prospective_scoreboard_v1",
                "challenger_summaries": {
                    "test_policy": {
                        "events": 9,
                        "mean_delta_to_champion": 1.0,
                        "ci95_low": 0.1,
                    }
                },
            }
        )
    )
    output = tmp_path / "registry.json"
    report = tmp_path / "registry.md"

    result = build_challenger_registry(
        specs=(
            ChallengerSpec(
                "test",
                "Test challenger",
                "test scope",
                artifact,
                ("gate", "passed"),
                "test_policy",
            ),
        ),
        prospective_scoreboard=scoreboard,
        output_path=output,
        report_path=report,
    )

    assert result["production_changed"] is False
    assert result["challengers"][0]["registry_status"] == "awaiting_prospective_evidence"
    assert result["challengers"][0]["promotion_gate"]["passed"] is False
    assert output.is_file()

    output_bytes = output.read_bytes()
    repeated = build_challenger_registry(
        specs=(
            ChallengerSpec(
                "test",
                "Test challenger",
                "test scope",
                artifact,
                ("gate", "passed"),
                "test_policy",
            ),
        ),
        prospective_scoreboard=scoreboard,
        output_path=output,
        report_path=report,
    )
    assert repeated["reused"] is True
    assert output.read_bytes() == output_bytes
