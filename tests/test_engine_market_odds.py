import csv
import hashlib
import io
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_engine.market_odds import (
    apply_current_market_shadow_rates,
    assess_current_market_source,
    infer_goal_rates,
    market_consensus_diagnostics,
    score_probabilities,
)
from fplagent_engine.market_policy_replay import paired_policy_gate
from fplagent_engine.market_transfer_replay import (
    _policy_rows,
    blend_score_rows,
    moving_block_mean_interval,
)


def test_score_probabilities_are_coherent() -> None:
    probabilities = score_probabilities(1.8, 0.9)
    assert np.isclose(probabilities[:3].sum(), 1.0)
    assert np.all((probabilities > 0.0) & (probabilities < 1.0))


def test_infer_goal_rates_recovers_poisson_market() -> None:
    expected_home = 1.72
    expected_away = 1.08
    probabilities = score_probabilities(expected_home, expected_away)
    one_x_two_odds = tuple(float(1.0 / probability) for probability in probabilities[:3])
    total_odds = (float(1.0 / probabilities[3]), float(1.0 / (1.0 - probabilities[3])))
    home, away, diagnostics = infer_goal_rates(one_x_two_odds, total_odds)
    assert np.isclose(home, expected_home, atol=1e-5)
    assert np.isclose(away, expected_away, atol=1e-5)
    assert diagnostics["fit_rmse"] < 1e-7


def test_policy_gate_uses_only_frozen_test_season() -> None:
    rows = [
        {"season": "2024-25", "challenger_minus_incumbent": -20},
        *[
            {"season": "2025-26", "challenger_minus_incumbent": delta}
            for delta in (1, 1, 1, 1)
        ],
    ]
    gate = paired_policy_gate(rows, "2025-26")
    assert gate["passed"] is True
    assert gate["mean_delta"] == 1.0
    assert gate["events"] == 4


def test_moving_block_interval_is_deterministic_and_positive() -> None:
    first = moving_block_mean_interval([1.0, 2.0, 3.0, 4.0] * 3, samples=500, seed=9)
    second = moving_block_mean_interval([1.0, 2.0, 3.0, 4.0] * 3, samples=500, seed=9)
    assert first == second
    assert first["mean"] == 2.5
    assert first["p025"] > 0.0


def test_market_policy_blend_uses_direct_xp_fallback_values() -> None:
    row = {
        "xp_expected_points": 4.0,
        "internal_component_expected_points": 5.0,
        "market_component_expected_points": 7.0,
    }
    assert _policy_rows([row], "incumbent_xp", 0.75)[0]["expected_points"] == 4.0
    assert (
        _policy_rows([row], "internal_component_control", 0.75)[0]["expected_points"]
        == 4.75
    )
    assert _policy_rows([row], "market_challenger", 0.75)[0]["expected_points"] == 6.25


def test_generic_challenger_blend_reuses_sequential_replay() -> None:
    row = {"xp_expected_points": 4.0, "return_distribution_expected_points": 6.0}
    scored = blend_score_rows([row], "return_distribution_expected_points", 0.25)[0]
    assert scored["expected_points"] == 4.5
    assert scored["robust_points"] == 4.5


def _current_source_payload(rows: list[dict[str, str]]) -> bytes:
    columns = [
        "Div",
        "HomeTeam",
        "AwayTeam",
        "AvgH",
        "AvgD",
        "AvgA",
        "Avg>2.5",
        "Avg<2.5",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def test_current_market_coverage_selects_next_event_and_reports_partial_horizon() -> None:
    payload = _current_source_payload(
        [
            {
                "Div": "E0",
                "HomeTeam": "Arsenal",
                "AwayTeam": "Chelsea",
                "AvgH": "1.80",
                "AvgD": "3.80",
                "AvgA": "4.50",
                "Avg>2.5": "1.85",
                "Avg<2.5": "2.00",
            },
            {
                "Div": "E0",
                "HomeTeam": "Chelsea",
                "AwayTeam": "Arsenal",
                "AvgH": "",
                "AvgD": "",
                "AvgA": "",
                "Avg>2.5": "",
                "Avg<2.5": "",
            },
        ]
    )
    result = assess_current_market_source(
        payload,
        "Latest fixtures uploaded: 08/08/26 12:00 UK time",
        season="2026-27",
        event=None,
        horizon=2,
        fpl_fixtures=[
            {"event": 1, "team_h": 1, "team_a": 2},
            {"event": 2, "team_h": 2, "team_a": 1},
        ],
        fpl_teams=[{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Chelsea"}],
        fpl_events=[
            {
                "id": 1,
                "is_next": True,
                "finished": False,
                "deadline_time": "2026-08-21T17:30:00+00:00",
            },
            {
                "id": 2,
                "is_next": False,
                "finished": False,
                "deadline_time": "2026-08-28T17:30:00+00:00",
            },
        ],
    )
    assert result["event"] == 1
    assert result["events"] == [1, 2]
    assert result["ready_for_event"] is True
    assert result["ready_events"] == [1]
    assert result["event_coverage"][1]["covered_fixtures"] == 1
    assert result["event_coverage"][1]["complete_odds_fixtures"] == 0
    assert result["event_coverage"][1]["ready"] is False


def test_market_consensus_records_book_disagreement_and_never_needs_closing_prices() -> None:
    diagnostics = market_consensus_diagnostics(
        {
            "AvgH": "2.10",
            "AvgD": "3.40",
            "AvgA": "3.50",
            "Avg>2.5": "1.90",
            "Avg<2.5": "1.95",
            "B365H": "2.00",
            "B365D": "3.50",
            "B365A": "3.80",
            "B365>2.5": "1.85",
            "B365<2.5": "2.00",
            "BFEH": "2.16",
            "BFED": "3.55",
            "BFEA": "3.70",
            "BFE>2.5": "1.96",
            "BFE<2.5": "2.02",
            "AHh": "-0.25",
            "AvgAHH": "1.91",
            "AvgAHA": "1.96",
        }
    )
    assert diagnostics["bookmaker_1x2_count"] == 2
    assert diagnostics["totals_source_count"] == 3
    assert diagnostics["home_probability_std"] > 0
    assert diagnostics["over_2_5_probability_std"] > 0
    assert diagnostics["asian_handicap_line"] == -0.25


def test_market_shadow_overrides_only_receipted_complete_events(tmp_path) -> None:
    rates_path = tmp_path / "rates.parquet"
    receipt_path = tmp_path / "receipt.json"
    rows = [
        {
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "market_home_goal_rate": 2.0,
            "market_away_goal_rate": 0.8,
        }
    ]
    pq.write_table(pa.Table.from_pylist(rows), rates_path)
    rates_sha256 = hashlib.sha256(rates_path.read_bytes()).hexdigest()
    receipt_path.write_text(
        json.dumps(
            {
                "status": "ready",
                "ready_events": [1],
                "fixture_count": 1,
                "fixture_counts_by_event": {"1": 1},
                "rates_path": str(rates_path),
                "rates_sha256": rates_sha256,
            }
        )
    )
    incumbent = {(1, 1, 2): (1.5, 1.1), (2, 2, 1): (1.2, 1.4)}
    shadow, diagnostics = apply_current_market_shadow_rates(
        incumbent,
        events=(1, 2),
        receipt_path=receipt_path,
        rates_path=rates_path,
    )
    assert shadow[(1, 1, 2)] == (2.0, 0.8)
    assert shadow[(2, 2, 1)] == incumbent[(2, 2, 1)]
    assert diagnostics["status"] == "ready_shadow"
    assert diagnostics["decision_authority"] is False
    assert diagnostics["overridden_events"] == [1]
    assert diagnostics["internal_only_events"] == [2]


def test_market_shadow_fails_closed_when_fixture_keys_do_not_match(tmp_path) -> None:
    rates_path = tmp_path / "rates.parquet"
    receipt_path = tmp_path / "receipt.json"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "event": 1,
                    "team_h": 1,
                    "team_a": 3,
                    "market_home_goal_rate": 2.0,
                    "market_away_goal_rate": 0.8,
                }
            ]
        ),
        rates_path,
    )
    receipt_path.write_text(
        json.dumps(
            {
                "status": "ready",
                "ready_events": [1],
                "fixture_count": 1,
                "fixture_counts_by_event": {"1": 1},
                "rates_path": str(rates_path),
                "rates_sha256": hashlib.sha256(rates_path.read_bytes()).hexdigest(),
            }
        )
    )
    incumbent = {(1, 1, 2): (1.5, 1.1)}
    shadow, diagnostics = apply_current_market_shadow_rates(
        incumbent,
        events=(1,),
        receipt_path=receipt_path,
        rates_path=rates_path,
    )
    assert shadow == incumbent
    assert diagnostics["status"] == "not_ready"
    assert "exactly match" in diagnostics["reason"]
