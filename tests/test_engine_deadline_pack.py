from __future__ import annotations

import json
from pathlib import Path

from fplagent_data.http import sha256_file
from fplagent_engine.deadline_pack import _render, deadline_pack_currentness


def test_deadline_pack_report_names_failed_gate_and_squad() -> None:
    result = {
        "created_at": "2026-08-15T12:00:00+00:00",
        "verdict": "BLOCKED",
        "gates": {"market": {"passed": False, "detail": "0/10"}},
        "decision": {
            "candidate_id": "R-test",
            "formation": "3-4-3",
            "expected_points": 60.0,
            "squad": {
                "starters": [
                    {
                        "position": "MID",
                        "name": "Example",
                        "team": "Club",
                        "captain": True,
                        "vice_captain": False,
                    }
                ],
                "bench": [
                    {
                        "position": "DEF",
                        "name": "Reserve",
                        "team": "Club",
                        "captain": False,
                        "vice_captain": False,
                    }
                ],
            },
        },
        "freshness": {
            "official_snapshot_at": "now",
            "decision_created_at": "now",
            "checked_at": "now",
        },
        "market": {
            "fixture_count": 0,
            "provider": "none",
            "defender_feature": {"weight": 0.2},
        },
        "search": {
            "combined_universe": 100,
            "robust_finalists": 2,
            "horizon_finalists": 2,
        },
        "participation_frontier": {"candidate_count": 2, "player_count": 16},
    }

    report = _render(result)

    assert "FAIL — market" in report
    assert "Example" in report
    assert "Reserve" in report


def test_deadline_pack_currentness_rejects_a_superseded_decision(tmp_path: Path) -> None:
    decision = tmp_path / "decision.json"
    pipeline = tmp_path / "pipeline.json"
    pack = tmp_path / "pack.json"
    decision.write_text('{"decision":{"candidate_id":"new"}}\n', encoding="utf-8")
    pipeline.write_text('{"status":"published"}\n', encoding="utf-8")
    pack.write_text(
        json.dumps(
            {
                "verdict": "DEADLINE_READY",
                "publishable": True,
                "lineage": {
                    "decision_sha256": "old-decision",
                    "pipeline_sha256": sha256_file(pipeline),
                },
            }
        ),
        encoding="utf-8",
    )

    result = deadline_pack_currentness(
        pack_path=pack,
        decision_path=decision,
        pipeline_path=pipeline,
    )

    assert result["current"] is False
    assert result["reasons"] == ["The deadline pack belongs to a superseded decision."]


def test_deadline_pack_currentness_accepts_exact_transaction(tmp_path: Path) -> None:
    decision = tmp_path / "decision.json"
    pipeline = tmp_path / "pipeline.json"
    pack = tmp_path / "pack.json"
    decision.write_text('{"decision":{"candidate_id":"current"}}\n', encoding="utf-8")
    pipeline.write_text('{"status":"published"}\n', encoding="utf-8")
    pack.write_text(
        json.dumps(
            {
                "verdict": "DEADLINE_READY",
                "publishable": True,
                "lineage": {
                    "decision_sha256": sha256_file(decision),
                    "pipeline_sha256": sha256_file(pipeline),
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        deadline_pack_currentness(
            pack_path=pack,
            decision_path=decision,
            pipeline_path=pipeline,
        )["current"]
        is True
    )
