from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_data.http import sha256_file
from fplagent_engine.availability_watch import (
    _decision_frontier,
    _decision_impacts,
    audit_availability_watch,
)
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
    assert result["decision_frontier"]["candidate_count"] == 1
    assert result["decision_frontier"]["player_count"] == 15


def test_frontier_covers_every_ranked_candidate_and_weights_exposure() -> None:
    decision = {
        "ranking": [{"candidate_id": "A"}, {"candidate_id": "B"}],
        "decision": {
            "candidate": {
                "candidate_id": "A",
                "selected": [1, 2],
                "lineups": {"1": {"starters": [1], "captain": 1}},
            }
        },
    }
    # With no external shortlist, candidate B is deliberately a hard lineage issue.
    issues: list[str] = []
    players = {
        element: {
            "id": element,
            "web_name": f"P{element}",
            "status": "a",
            "can_select": True,
            "removed": False,
            "news": "",
        }
        for element in (1, 2)
    }
    forecasts = {
        element: {
            "element": element,
            "player_name": f"P{element}",
            "team_name": "Club",
            "position": "MID",
            "p_play": 0.9,
            "expected_points": 4.0,
        }
        for element in (1, 2)
    }
    roles = {element: _role_row(element) for element in (1, 2)}

    result = _decision_frontier(
        decision,
        player_by_id=players,
        forecast_by_id=forecasts,
        role_by_id=roles,
        participation_by_id={},
        issues=issues,
    )

    assert result["requested_candidate_count"] == 2
    assert result["candidate_count"] == 1
    assert result["players"][0]["squad_exposure"] == 1.0
    assert any("candidate" in issue and "B" in issue for issue in issues)


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


def test_aligned_predicted_lineups_are_exposed_with_zero_authority(
    tmp_path: Path,
) -> None:
    kwargs = _artifacts(tmp_path)
    receipt_path = tmp_path / "participation-receipt.json"
    consensus_path = tmp_path / "participation.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event": 1,
                    "element": element,
                    "consensus": "single_source_start",
                    "predicted_start_sources": ["rotowire"],
                    "predicted_not_start_sources": [],
                    "complete_source_count": 1,
                    "attention": [],
                }
                for element in range(1, 16)
            ]
        ),
        consensus_path,
    )
    _write_json(
        receipt_path,
        {
            "event": 1,
            "observed_at": kwargs["as_of"].isoformat(),
            "status": "shadow_consensus_partial",
            "inputs": {
                "official_players_sha256": sha256_file(Path(kwargs["players_path"])),
                "forecast_sha256": sha256_file(Path(kwargs["forecast_path"])),
            },
            "outputs": {"consensus_sha256": sha256_file(consensus_path)},
            "sources": {
                "rotowire": {"status": "captured", "decision_eligible": True},
                "stale_source": {"status": "captured", "decision_eligible": False},
            },
            "summary": {"predicted_start_consensus": 0},
            "promotion_gate": {"passed": False},
        },
    )
    kwargs["participation_receipt_path"] = receipt_path
    kwargs["participation_consensus_path"] = consensus_path

    result = audit_availability_watch(**kwargs)

    predicted = result["predicted_lineup_consensus"]
    assert predicted["current"] is True
    assert predicted["eligible_source_count"] == 1
    assert predicted["captured_source_count"] == 2
    assert predicted["production_adjustment_authorized"] is False
    assert result["players"][0]["predicted_lineups"]["consensus"] == (
        "single_source_start"
    )


def test_supported_role_alternative_is_current_attention_not_stale_evidence(
    tmp_path: Path,
) -> None:
    kwargs = _artifacts(tmp_path)
    scenario_path = Path(kwargs["scenario_results_path"])
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["scenarios"]["moderate_role_stress"]["deep_squad_replay"] = {
        "cross_family_holdout_support": True,
        "challenger_squad_id": "R-safer",
        "incumbent_configuration": {
            "starters": ["Player 1"],
            "bench_order": ["Player 2"],
        },
        "challenger_configuration": {
            "starters": ["Player 2"],
            "bench_order": ["Player 1"],
            "formation": "4-4-2",
            "captain": "Player 2",
            "vice_captain": "Player 3",
        },
        "holdout_delta_challenger_to_incumbent": {
            "residual": {"mean": 0.3},
            "component": {"mean": 0.2},
        },
    }
    scenario["supported_deep_squad_scenarios"] = ["moderate_role_stress"]
    _write_json(scenario_path, scenario)
    threshold_path = Path(kwargs["threshold_results_path"])
    threshold = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold["lineage"]["preseason_role_scenario_sha256"] = sha256_file(scenario_path)
    _write_json(threshold_path, threshold)

    result = audit_availability_watch(**kwargs)

    assert result["current"] is True
    assert result["status"] == "scenario_attention"
    assert result["decision_change_authorized"] is False
    assert result["decision_action"] == "retain_decision_and_review_supported_alternatives"
    assert result["issues"] == []
    assert result["decision_impacts"][0]["challenger_squad_id"] == "R-safer"
    assert any("counterfactuals require review" in value for value in result["warnings"])


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


def test_supported_scenario_reversal_is_projected_for_decision_consumers() -> None:
    result = _decision_impacts(
        {
            "scenarios": {
                "moderate_role_stress": {
                    "description": "Retain fewer uncertain appearances.",
                    "deep_squad_replay": {
                        "cross_family_holdout_support": True,
                        "challenger_squad_id": "R-safer",
                        "incumbent_configuration": {
                            "starters": ["Risky Starter", "Captain"],
                            "bench_order": ["Bench Hold"],
                        },
                        "challenger_configuration": {
                            "starters": ["Safer Starter", "Captain"],
                            "bench_order": ["Bench Hold"],
                            "formation": "4-4-2",
                            "captain": "Captain",
                            "vice_captain": "Safer Starter",
                        },
                        "holdout_delta_challenger_to_incumbent": {
                            "residual": {"mean": 0.8},
                            "component": {"mean": 0.6},
                        },
                    },
                }
            }
        }
    )

    assert result == [
        {
            "scenario": "moderate_role_stress",
            "description": "Retain fewer uncertain appearances.",
            "challenger_squad_id": "R-safer",
            "incoming": ["Safer Starter"],
            "outgoing": ["Risky Starter"],
            "formation": "4-4-2",
            "captain": "Captain",
            "vice_captain": "Safer Starter",
            "minimum_family_gain": 0.6,
            "counterfactual_not_probability": True,
        }
    ]


def test_scenario_reversal_explains_why_synthesis_rejected_it() -> None:
    scenario = {
        "scenarios": {
            "baseline": {
                "description": "Production appearance worlds unchanged.",
                "deep_squad_replay": {
                    "cross_family_holdout_support": True,
                    "challenger_squad_id": "R-challenger",
                    "incumbent_configuration": {"starters": ["Current"]},
                    "challenger_configuration": {
                        "starters": ["Alternative"],
                        "formation": "4-4-2",
                        "captain": "Alternative",
                        "vice_captain": "Current",
                    },
                    "holdout_delta_challenger_to_incumbent": {
                        "residual": {"mean": 0.8},
                        "component": {"mean": 0.6},
                    },
                },
            }
        }
    }
    decision = {
        "decision": {"candidate_id": "R-selected"},
        "ranking": [
            {
                "candidate_id": "R-selected",
                "rank": 1,
                "synthesis_regret": 1.0,
                "robust_family_regret": 1.2,
                "horizon_family_regret": 0.6,
            },
            {
                "candidate_id": "R-challenger",
                "rank": 9,
                "synthesis_regret": 1.17,
                "robust_family_regret": 1.8,
                "horizon_family_regret": 0.2,
            },
        ],
    }

    result = _decision_impacts(scenario, decision)

    assert result[0]["challenger_synthesis_rank"] == 9
    assert result[0]["synthesis_regret_delta"] == pytest.approx(0.17)
    assert result[0]["five_week_regret_delta"] == pytest.approx(0.6)
    assert result[0]["eight_week_regret_delta"] == pytest.approx(-0.4)
    assert "0.170 more synthesis regret" in result[0]["why_not_selected"]
