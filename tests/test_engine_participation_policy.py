from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine.participation_policy import apply_current_participation_policy


def _write_evidence(tmp_path, rows, *, single_source_override: bool = False):
    consensus = tmp_path / "consensus.parquet"
    receipt = tmp_path / "receipt.json"
    pq.write_table(pa.Table.from_pylist(rows), consensus)
    receipt.write_text(
        json.dumps(
            {
                "decision_eligible": True,
                "event": 1,
                "observed_at": "2026-08-16T09:00:00+00:00",
                "deadline_time": "2026-08-21T17:30:00+00:00",
                "sources": (
                    {
                        "fantasy_football_scout": {
                            "status": "captured",
                            "decision_eligible": False,
                        },
                        "rotowire": {"status": "captured", "decision_eligible": True},
                    }
                    if single_source_override
                    else {
                        "fantasy_football_scout": {
                            "status": "captured",
                            "decision_eligible": True,
                        },
                        "rotowire": {"status": "captured", "decision_eligible": True},
                    }
                ),
                "authority": (
                    {
                        "operator_override_active": True,
                        "predicted_lineup_consensus": ("bounded_production_operator_override"),
                    }
                    if single_source_override
                    else {}
                ),
                "outputs": {"consensus_sha256": hashlib.sha256(consensus.read_bytes()).hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    return receipt, consensus


def _forecast(element: int, *, position: str = "FWD") -> dict:
    return {
        "season": "2026-27",
        "event_number": 1,
        "element": element,
        "position": position,
        "p_dnp": 0.36956644,
        "p_1_59": 0.16952533,
        "p_60_89": 0.19219106,
        "p_90_or_more": 0.26871717,
        "p_play": 0.63043356,
        "conditional_points_if_playing": 4.59103584,
        "expected_points": 2.90010428,
        "robust_points": 2.84557056,
        "epistemic_uncertainty": 0.36355782,
    }


def test_two_source_start_updates_play_odds_without_inventing_duration(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 411,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_start_consensus",
                "predicted_start_sources": ["fantasy_football_scout", "rotowire"],
                "predicted_not_start_sources": [],
            }
        ],
    )

    rows, diagnostics = apply_current_participation_policy(
        [_forecast(411)],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    row = rows[0]
    assert diagnostics["decision_authority"] is True
    assert row["p_play"] == pytest.approx(0.94462513)
    assert row["live_participation_expected_minutes"] == pytest.approx(64.9479)
    assert row["live_participation_conditional_minutes"] == pytest.approx(68.7552)
    assert 4.0 < row["expected_points"] < 5.0
    assert row["incumbent_expected_points_before_live_participation"] == pytest.approx(2.90010428)
    assert sum(
        row[field] for field in ("p_dnp", "p_1_59", "p_60_89", "p_90_or_more")
    ) == pytest.approx(1.0)


def test_two_source_bench_reduces_role_without_special_casing_player(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 99,
                "position": "MID",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_bench_consensus",
                "predicted_start_sources": [],
                "predicted_not_start_sources": [
                    "fantasy_football_scout",
                    "rotowire",
                ],
            }
        ],
    )
    forecast = _forecast(99, position="MID")
    forecast.update(
        {
            "p_dnp": 0.03,
            "p_1_59": 0.03,
            "p_60_89": 0.20,
            "p_90_or_more": 0.74,
            "p_play": 0.97,
            "expected_points": 6.0,
            "robust_points": 5.9,
        }
    )

    rows, _ = apply_current_participation_policy(
        [forecast],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert rows[0]["live_participation_expected_minutes"] < 50.0
    assert rows[0]["expected_points"] < 4.0
    assert rows[0]["live_participation_reason"] == "two_source_bench"


def test_official_unavailable_bypasses_predicted_bench_floor(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 99,
                "position": "FWD",
                "official_status": "unavailable",
                "official_chance": 0,
                "consensus": "single_source_bench",
                "predicted_start_sources": [],
                "predicted_not_start_sources": ["rotowire"],
                "production_adjustment_authorized": True,
            }
        ],
        single_source_override=True,
    )

    rows, _ = apply_current_participation_policy(
        [_forecast(99)],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    row = rows[0]
    assert row["p_play"] == 0.0
    assert row["live_participation_expected_minutes"] == 0.0
    assert row["live_role_minutes_ratio"] == 0.0
    assert row["expected_points"] == 0.0
    assert row["robust_points"] == 0.0


def test_bounded_single_source_bench_survives_a_stale_second_source(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 99,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "single_source_bench",
                "predicted_start_sources": [],
                "predicted_not_start_sources": ["rotowire"],
                "production_adjustment_authorized": True,
            }
        ],
        single_source_override=True,
    )
    forecast = _forecast(99)
    forecast.update(
        {
            "last_minutes": 0.0,
            "p_dnp": 0.42,
            "p_1_59": 0.35,
            "p_60_89": 0.12,
            "p_90_or_more": 0.11,
            "p_play": 0.58,
            "expected_points": 2.0,
            "robust_points": 1.95,
        }
    )

    rows, diagnostics = apply_current_participation_policy(
        [forecast],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert diagnostics["decision_authority"] is True
    assert diagnostics["eligible_source_count"] == 1
    assert diagnostics["policy"] == "bounded_official_single_source_operator_v1"
    assert rows[0]["live_participation_applied"] is True
    assert rows[0]["live_participation_consensus"] == "single_source_bench"
    assert rows[0]["p_play"] < forecast["p_play"]
    assert rows[0]["live_participation_expected_minutes"] < 25.0


def test_single_source_without_explicit_operator_policy_remains_inactive(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 99,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "single_source_bench",
                "predicted_start_sources": [],
                "predicted_not_start_sources": ["rotowire"],
                "production_adjustment_authorized": True,
            }
        ],
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["sources"]["fantasy_football_scout"]["decision_eligible"] = False
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    rows, diagnostics = apply_current_participation_policy(
        [_forecast(99)],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert diagnostics["decision_authority"] is False
    assert "bounded single-source operator policy" in diagnostics["reason"]
    assert rows[0]["live_participation_applied"] is False


def test_two_source_bench_role_decays_across_next_two_events(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 99,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_bench_consensus",
                "predicted_start_sources": [],
                "predicted_not_start_sources": ["fantasy_football_scout", "rotowire"],
            }
        ],
    )
    forecasts = []
    for event in (1, 2, 3, 4):
        row = _forecast(99)
        row.update(
            {
                "event_number": event,
                "p_dnp": 0.03,
                "p_1_59": 0.03,
                "p_60_89": 0.20,
                "p_90_or_more": 0.74,
                "p_play": 0.97,
                "expected_points": 6.0,
                "robust_points": 5.9,
            }
        )
        forecasts.append(row)

    rows, diagnostics = apply_current_participation_policy(
        forecasts,
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    minutes = [row.get("live_participation_expected_minutes") for row in rows]
    assert minutes[0] < minutes[1] < minutes[2]
    assert minutes[2] < 80.0
    assert minutes[3] is None
    assert rows[1]["live_participation_persistence_offset"] == 1
    assert rows[2]["live_participation_persistence_offset"] == 2
    assert diagnostics["persistence_applied_rows"] == 2


def test_two_source_start_activates_history_backed_future_role_prior(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 411,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_start_consensus",
                "predicted_start_sources": ["fantasy_football_scout", "rotowire"],
                "predicted_not_start_sources": [],
            }
        ],
    )
    current = _forecast(411)
    future = {**_forecast(411), "event_number": 2}
    for row in (current, future):
        row.update(
            {
                "appearance_rate5": 0.8,
                "start_rate5": 0.8,
                "form5_minutes": 90.0,
                "form10_minutes": 81.0,
                "form38_minutes": 82.0,
                "availability_chance": 100.0,
            }
        )

    rows, diagnostics = apply_current_participation_policy(
        [current, future],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert rows[1]["live_participation_reason"] == "durable_role_prior"
    assert rows[1]["live_participation_role_prior_applied"] is True
    assert rows[1]["live_participation_role_prior_probability"] == pytest.approx(0.9)
    assert rows[1]["p_play"] == pytest.approx(0.9)
    assert rows[1]["live_participation_expected_minutes"] > 70.0
    assert rows[1]["expected_points"] > future["expected_points"]
    assert diagnostics["durable_role_prior_applied_rows"] == 1


def test_future_role_prior_requires_established_start_history(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 12,
                "position": "MID",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_start_consensus",
                "predicted_start_sources": ["fantasy_football_scout", "rotowire"],
                "predicted_not_start_sources": [],
            }
        ],
    )
    future = {**_forecast(12, position="MID"), "event_number": 2}
    future.update(
        {
            "appearance_rate5": 0.6,
            "start_rate5": 0.4,
            "form5_minutes": 35.0,
            "form10_minutes": 48.0,
            "form38_minutes": 55.0,
            "availability_chance": 100.0,
        }
    )

    rows, diagnostics = apply_current_participation_policy(
        [future],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert rows[0]["live_participation_applied"] is False
    assert rows[0]["p_play"] == pytest.approx(future["p_play"])
    assert diagnostics["durable_role_prior_applied_rows"] == 0


def test_two_source_starters_retain_bounded_player_specific_usage(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": element,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_start_consensus",
                "predicted_start_sources": ["fantasy_football_scout", "rotowire"],
                "predicted_not_start_sources": [],
            }
            for element in (1, 2)
        ],
    )
    talisman = _forecast(1)
    talisman.update({"form5_minutes": 90.0, "form10_minutes": 86.0, "form38_minutes": 84.0})
    rotation_risk = _forecast(2)
    rotation_risk.update({"form5_minutes": 52.0, "form10_minutes": 48.0, "form38_minutes": 55.0})

    rows, _ = apply_current_participation_policy(
        [talisman, rotation_risk],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    by_element = {row["element"]: row for row in rows}
    assert by_element[1]["live_participation_expected_minutes"] > 70.0
    assert by_element[2]["live_participation_expected_minutes"] < 60.0
    assert by_element[1]["expected_points"] > by_element[2]["expected_points"]


def test_two_source_start_uplift_is_bounded_for_extreme_low_prior(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 3,
                "position": "MID",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "predicted_start_consensus",
                "predicted_start_sources": ["fantasy_football_scout", "rotowire"],
                "predicted_not_start_sources": [],
            }
        ],
    )
    player = _forecast(3, position="MID")
    player.update(
        {
            "p_dnp": 0.90,
            "p_1_59": 0.05,
            "p_60_89": 0.04,
            "p_90_or_more": 0.01,
            "p_play": 0.10,
            "form5_minutes": 90.0,
            "appearance_rate5": 1.0,
            "form10_minutes": 90.0,
            "form38_minutes": 90.0,
        }
    )
    rows, _ = apply_current_participation_policy(
        [player],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert (
        rows[0]["live_participation_expected_minutes"]
        - rows[0]["incumbent_expected_minutes_before_live_participation"]
        <= 36.0 + 1e-9
    )


def test_source_disagreement_uncertainty_is_current_event_only(tmp_path) -> None:
    receipt, consensus = _write_evidence(
        tmp_path,
        [
            {
                "event": 1,
                "element": 4,
                "position": "FWD",
                "official_status": "clear",
                "official_chance": 100,
                "consensus": "source_disagreement",
                "predicted_start_sources": ["rotowire"],
                "predicted_not_start_sources": ["fantasy_football_scout"],
            }
        ],
    )
    current = _forecast(4)
    future = {**_forecast(4), "event_number": 2}
    rows, _ = apply_current_participation_policy(
        [current, future],
        receipt_path=receipt,
        consensus_path=consensus,
        as_of=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    assert rows[0]["epistemic_uncertainty"] == pytest.approx(0.71355782)
    assert rows[1]["epistemic_uncertainty"] == pytest.approx(0.36355782)
