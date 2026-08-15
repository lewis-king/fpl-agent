from __future__ import annotations

from fplagent_engine.deadline_pack import _render


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
