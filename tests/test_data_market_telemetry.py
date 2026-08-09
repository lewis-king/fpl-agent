from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from fplagent_data.cli import parser
from fplagent_data.market_telemetry import (
    build_market_features,
    build_price_change_outcomes,
    collect_market_observation,
)


def _bootstrap(
    *,
    transfers_in: int = 120,
    transfers_out: int = 20,
    selected_by: str = "12.4",
    status: str = "a",
    now_cost: int = 75,
    price_change_percent: float = 83.5,
) -> bytes:
    player = {
        "id": 101,
        "code": 9001,
        "web_name": "Test",
        "team": 7,
        "element_type": 3,
        "now_cost": now_cost,
        "selected_by_percent": selected_by,
        "transfers_in_event": transfers_in,
        "transfers_out_event": transfers_out,
        "transfers_in": 300,
        "transfers_out": 40,
        "cost_change_event": 1,
        "cost_change_start": 2,
        "price_change_percent": price_change_percent,
        "status": status,
        "chance_of_playing_this_round": 75,
        "chance_of_playing_next_round": None,
        "news": "Test note",
        "news_added": "2026-08-08T09:00:00Z",
        "can_select": True,
        "removed": False,
    }
    return json.dumps(
        {
            "elements": [player],
            "teams": [{"id": 7, "short_name": "TST"}],
            "element_types": [{"id": 3, "singular_name_short": "MID"}],
        }
    ).encode()


def _kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "observed_at": "2026-08-08T10:15:00+00:00",
        "raw_root": tmp_path / "raw",
        "observation_root": tmp_path / "observations",
        "receipt_root": tmp_path / "receipts",
        "pointer_path": tmp_path / "current.json",
    }


def test_market_observation_is_append_only_typed_and_idempotent(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path)

    first = collect_market_observation(fetcher=lambda _: _bootstrap(), **kwargs)
    second = collect_market_observation(fetcher=lambda _: _bootstrap(), **kwargs)
    row = pq.read_table(first["parquet_path"]).to_pylist()[0]

    assert first["rows"] == 1
    assert first["price_change_nonzero"] == 1
    assert second["reused"] is True
    assert row["net_transfers_event"] == 100
    assert row["price_change_percent"] == 83.5
    assert row["chance_this_round"] == 75
    assert Path(first["raw_path"]).is_file()
    assert Path(kwargs["pointer_path"]).is_file()


def test_same_observation_timestamp_cannot_be_rewritten(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path)
    collect_market_observation(fetcher=lambda _: _bootstrap(), **kwargs)

    with pytest.raises(ValueError, match="immutable market raw collision"):
        collect_market_observation(
            fetcher=lambda _: _bootstrap(transfers_in=121), **kwargs
        )


def test_cli_exposes_market_observation_collection() -> None:
    args = parser().parse_args(
        ["collect-market-observation", "--observed-at", "2026-08-08T10:15:00+00:00"]
    )

    assert args.command == "collect-market-observation"
    assert args.observed_at == "2026-08-08T10:15:00+00:00"


def test_market_features_derive_point_in_time_velocity_without_policy_authority(
    tmp_path: Path,
) -> None:
    roots = {
        "raw_root": tmp_path / "raw",
        "observation_root": tmp_path / "observations",
        "receipt_root": tmp_path / "receipts",
        "pointer_path": tmp_path / "current.json",
    }
    collect_market_observation(
        observed_at="2026-08-08T10:00:00+00:00",
        fetcher=lambda _: _bootstrap(),
        **roots,
    )
    collect_market_observation(
        observed_at="2026-08-08T10:15:00+00:00",
        fetcher=lambda _: _bootstrap(
            transfers_in=145, transfers_out=25, selected_by="12.5"
        ),
        **roots,
    )

    result = build_market_features(
        observation_root=roots["observation_root"],
        output_path=tmp_path / "features.parquet",
        receipt_path=tmp_path / "feature-receipt.json",
        as_of="2026-08-08T10:16:00+00:00",
    )
    row = pq.read_table(result["output_path"]).to_pylist()[0]

    assert result["status"] == "ready"
    assert "cannot authorize" in result["authority"]
    assert row["net_transfers_interval"] == 20
    assert row["net_transfer_velocity_per_hour"] == pytest.approx(80.0)
    assert row["ownership_delta_pp_per_hour"] == pytest.approx(0.4)
    assert row["hours_to_uk_midnight"] == pytest.approx(12.75)
    assert row["net_transfer_acceleration_per_hour2"] is None


def test_market_features_fail_closed_until_two_observations_exist(
    tmp_path: Path,
) -> None:
    roots = {
        "raw_root": tmp_path / "raw",
        "observation_root": tmp_path / "observations",
        "receipt_root": tmp_path / "receipts",
        "pointer_path": tmp_path / "current.json",
    }
    collect_market_observation(
        observed_at="2026-08-08T10:00:00+00:00",
        fetcher=lambda _: _bootstrap(),
        **roots,
    )

    result = build_market_features(
        observation_root=roots["observation_root"],
        output_path=tmp_path / "features.parquet",
        receipt_path=tmp_path / "feature-receipt.json",
        as_of="2026-08-08T10:01:00+00:00",
    )

    assert result["status"] == "not_ready"
    assert not (tmp_path / "features.parquet").exists()


def test_cli_exposes_market_feature_build() -> None:
    args = parser().parse_args(["build-market-features"])

    assert args.command == "build-market-features"


def test_price_outcomes_score_tight_uk_midnight_observation_pair(tmp_path: Path) -> None:
    roots = {
        "raw_root": tmp_path / "raw",
        "observation_root": tmp_path / "observations",
        "receipt_root": tmp_path / "receipts",
        "pointer_path": tmp_path / "current.json",
    }
    collect_market_observation(
        observed_at="2026-08-21T22:30:00+00:00",
        fetcher=lambda _: _bootstrap(transfers_in=100, price_change_percent=80.0),
        **roots,
    )
    collect_market_observation(
        observed_at="2026-08-21T22:55:00+00:00",
        fetcher=lambda _: _bootstrap(transfers_in=140, price_change_percent=105.0),
        **roots,
    )
    collect_market_observation(
        observed_at="2026-08-21T23:05:00+00:00",
        fetcher=lambda _: _bootstrap(
            transfers_in=140,
            now_cost=76,
            price_change_percent=0.0,
        ),
        **roots,
    )

    receipt = build_price_change_outcomes(
        observation_root=tmp_path / "observations",
        output_path=tmp_path / "outcomes.parquet",
        receipt_path=tmp_path / "outcomes.json",
        as_of="2026-08-21T23:10:00+00:00",
    )
    row = pq.read_table(receipt["output_path"]).to_pylist()[0]

    assert receipt["status"] == "ready"
    assert receipt["outcome_nights"] == 1
    assert receipt["calibration_gate"]["passed"] is False
    assert row["actual_direction"] == "rise"
    assert row["threshold_direction"] == "rise"
    assert row["threshold_crossed"] is True
    assert row["net_transfer_velocity_per_hour"] == pytest.approx(96.0)


def test_cli_exposes_price_outcome_build() -> None:
    args = parser().parse_args(["build-price-change-outcomes"])

    assert args.command == "build-price-change-outcomes"
