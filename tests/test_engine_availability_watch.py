from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_engine.availability_watch import audit_availability_watch
from fplagent_engine.cli import parser


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _role_row(element: int) -> dict[str, Any]:
    if element == 1:
        status = "not_listed_in_eligible_lineups"
        eligible, listings, starts, recent, latest = 3, 0, 0, 0.0, None
    elif element == 2:
        status = "observed_in_lineup"
        eligible, listings, starts, recent, latest = 2, 2, 0, 0.2, False
    elif element == 3:
        status = "no_confirmed_team_lineups"
        eligible, listings, starts, recent, latest = 0, 0, 0, None, None
    else:
        status = "observed_in_lineup"
        eligible, listings, starts, recent, latest = 1, 1, 1, 1.0, True
    return {
        "fpl_element": element,
        "evidence_status": status,
        "eligible_team_matches": eligible,
        "squad_listings": listings,
        "starts": starts,
        "appearances": listings,
        "recency_weighted_start_share": recent,
        "last_match_listed": latest is not None,
        "last_match_started": latest,
        "minutes_data_complete": element != 2,
    }


def _artifacts(
    tmp_path: Path,
    *,
    player_status: str = "a",
    chance: int | None = None,
) -> dict[str, Any]:
    observed = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
    collected = observed + timedelta(hours=1)
    decision_path = tmp_path / "decision.json"
    forecast_path = tmp_path / "forecast.parquet"
    players_path = tmp_path / "players.parquet"
    role_path = tmp_path / "role.parquet"
    role_receipt_path = tmp_path / "role-receipt.json"
    scenario_path = tmp_path / "scenario.json"
    threshold_path = tmp_path / "threshold.json"
    output_path = tmp_path / "watch.json"

    _write_json(
        decision_path,
        {"decision": {"candidate": {"candidate_id": "R-current", "selected": list(range(1, 16))}}},
    )
    forecast_rows = [
        {
            "snapshot_at": observed.isoformat(),
            "event_number": 1,
            "element": element,
            "player_name": f"Player {element}",
            "team_name": "Test",
            "position": "MID",
            "p_play": 0.9,
            "expected_points": 4.0,
            "robust_points": 3.9,
        }
        for element in range(1, 16)
    ]
    pq.write_table(pa.Table.from_pylist(forecast_rows), forecast_path)
    player_rows = [
        {
            "snapshot_at": observed.isoformat(),
            "id": element,
            "web_name": f"Player {element}",
            "team": 1,
            "status": player_status if element == 1 else "a",
            "chance_of_playing_this_round": chance if element == 1 else None,
            "chance_of_playing_next_round": None,
            "news": "Knock" if element == 1 and player_status != "a" else "",
            "news_added": collected.isoformat() if element == 1 and player_status != "a" else None,
            "can_select": True,
            "removed": False,
        }
        for element in range(1, 16)
    ]
    pq.write_table(pa.Table.from_pylist(player_rows), players_path)
    pq.write_table(
        pa.Table.from_pylist([_role_row(element) for element in range(1, 16)]),
        role_path,
    )
    _write_json(
        role_receipt_path,
        {
            "created_at": collected.isoformat(),
            "inputs": {"players_sha256": sha256_file(players_path)},
            "outputs": {"role_evidence_sha256": sha256_file(role_path)},
        },
    )
    scenario = {
        "lineage": {
            "decision_sha256": sha256_file(decision_path),
            "preseason_receipt_sha256": sha256_file(role_receipt_path),
            "preseason_role_evidence_sha256": sha256_file(role_path),
        },
        "scenarios": {
            name: {
                "configuration": {"cross_family_holdout_support": False},
                "squad": {"cross_family_holdout_support": False},
                "deep_squad_replay": None,
            }
            for name in ("baseline", "moderate_role_stress")
        },
        "supported_deep_squad_scenarios": ["severe_role_stress"],
    }
    _write_json(scenario_path, scenario)
    _write_json(
        threshold_path,
        {
            "production_changed": False,
            "promotion_ready": False,
            "lineage": {
                "decision_sha256": sha256_file(decision_path),
                "forecast_sha256": sha256_file(forecast_path),
                "preseason_role_evidence_sha256": sha256_file(role_path),
                "preseason_role_scenario_sha256": sha256_file(scenario_path),
            },
            "boundary": {
                "classification": "supported_boundary_bracketed",
                "highest_supported_retention": 0.51,
                "highest_supported_role_watch_retention": 0.756,
                "next_tested_unsupported_retention": 0.515,
            },
            "threshold_points": [
                {
                    "not_listed_retention": 0.51,
                    "mechanical_appearance_rates": {
                        "1": {
                            "retention_factor": 0.51,
                            "mechanically_retained_p_play": 0.459,
                        },
                        "2": {
                            "retention_factor": 0.756,
                            "mechanically_retained_p_play": 0.6804,
                        },
                    },
                }
            ],
        },
    )
    return {
        "as_of": collected + timedelta(hours=1),
        "players_path": players_path,
        "forecast_path": forecast_path,
        "decision_path": decision_path,
        "role_receipt_path": role_receipt_path,
        "role_evidence_path": role_path,
        "scenario_results_path": scenario_path,
        "threshold_results_path": threshold_path,
        "output_path": output_path,
    }


def test_current_watch_retains_decision_and_names_verification_gaps(
    tmp_path: Path,
) -> None:
    kwargs = _artifacts(tmp_path)

    result = audit_availability_watch(**kwargs)

    assert result["status"] == "verification_required"
    assert result["current"] is True
    assert result["decision_change_authorized"] is False
    assert result["decision_action"] == "retain_decision_and_verify_flagged_players"
    assert result["summary"] == {
        "selected_players": 15,
        "official_attention": 0,
        "role_verification": 2,
        "uncovered_club_feed": 1,
        "no_attention": 12,
    }
    assert result["players"][0]["supported_edge_sensitivity"] == {
        "retention_factor": 0.51,
        "mechanically_retained_p_play": 0.459,
    }
    assert Path(kwargs["output_path"]).is_file()


def test_official_doubt_is_surfaced_but_not_an_automatic_squad_change(
    tmp_path: Path,
) -> None:
    kwargs = _artifacts(tmp_path, player_status="d", chance=50)

    result = audit_availability_watch(**kwargs)

    assert result["status"] == "official_attention"
    assert result["summary"]["official_attention"] == 1
    assert result["decision_change_authorized"] is False
    assert result["players"][0]["official"]["chance"] == 50
    assert "official_doubt_or_news" in result["players"][0]["attention"]


def test_stale_advisory_receipt_requires_refresh(tmp_path: Path) -> None:
    kwargs = _artifacts(tmp_path)
    kwargs["advisory_max_age"] = timedelta(minutes=30)

    result = audit_availability_watch(**kwargs)

    assert result["status"] == "refresh_required"
    assert result["current"] is False
    assert any("role receipt is stale" in issue for issue in result["issues"])


def test_threshold_lineage_mismatch_requires_replay(tmp_path: Path) -> None:
    kwargs = _artifacts(tmp_path)
    threshold_path = Path(kwargs["threshold_results_path"])
    threshold = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold["lineage"]["decision_sha256"] = "wrong"
    _write_json(threshold_path, threshold)

    result = audit_availability_watch(**kwargs)

    assert result["status"] == "refresh_required"
    assert any("current decision" in issue for issue in result["issues"])


def test_missing_advisory_artifact_returns_structured_refresh_status(
    tmp_path: Path,
) -> None:
    kwargs = _artifacts(tmp_path)
    Path(kwargs["role_evidence_path"]).unlink()

    result = audit_availability_watch(**kwargs)

    assert result["status"] == "refresh_required"
    assert result["players"] == []
    assert any("missing preseason role evidence" in issue for issue in result["issues"])


def test_cli_exposes_availability_status() -> None:
    args = parser().parse_args(
        ["availability-status", "--as-of", "2026-08-07T15:00:00+00:00"]
    )

    assert args.command == "availability-status"
    assert args.as_of == "2026-08-07T15:00:00+00:00"
