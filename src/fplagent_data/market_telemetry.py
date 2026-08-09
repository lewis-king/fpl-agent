from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from .arrow import write_table
from .catalog import sources
from .http import USER_AGENT, sha256_file
from .paths import MANIFESTS, PROCESSED, RAW

SEASON = "2026-27"
RAW_ROOT = RAW / "fpl" / SEASON / "market-telemetry"
OBSERVATION_ROOT = PROCESSED / "fpl" / SEASON / "market-observations"
RECEIPT_ROOT = MANIFESTS / "fpl-market-observations"
CURRENT_POINTER = MANIFESTS / "fpl-market-observation-current.json"
CURRENT_FEATURES = PROCESSED / "fpl" / SEASON / "market-features-current.parquet"
CURRENT_FEATURE_RECEIPT = MANIFESTS / "fpl-market-features-current.json"
PRICE_OUTCOMES = PROCESSED / "fpl" / SEASON / "price-change-outcomes.parquet"
PRICE_OUTCOME_RECEIPT = MANIFESTS / "fpl-price-change-outcomes.json"
MARKET_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("observed_at", pa.string()),
        ("element", pa.int64()),
        ("player_code", pa.int64()),
        ("player_name", pa.string()),
        ("team_id", pa.int64()),
        ("team", pa.string()),
        ("position", pa.string()),
        ("now_cost", pa.int64()),
        ("selected_by_percent", pa.float64()),
        ("transfers_in_event", pa.int64()),
        ("transfers_out_event", pa.int64()),
        ("net_transfers_event", pa.int64()),
        ("transfers_in_total", pa.int64()),
        ("transfers_out_total", pa.int64()),
        ("cost_change_event", pa.int64()),
        ("cost_change_start", pa.int64()),
        ("price_change_percent", pa.float64()),
        ("status", pa.string()),
        ("chance_this_round", pa.int64()),
        ("chance_next_round", pa.int64()),
        ("news", pa.string()),
        ("news_added", pa.string()),
        ("can_select", pa.bool_()),
        ("removed", pa.bool_()),
    ]
)
FEATURE_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("feature_at", pa.string()),
        ("element", pa.int64()),
        ("player_name", pa.string()),
        ("team", pa.string()),
        ("position", pa.string()),
        ("data_points", pa.int64()),
        ("span_hours", pa.float64()),
        ("interval_hours", pa.float64()),
        ("now_cost", pa.int64()),
        ("cost_change_event", pa.int64()),
        ("price_change_percent", pa.float64()),
        ("selected_by_percent", pa.float64()),
        ("ownership_delta_pp_per_hour", pa.float64()),
        ("transfers_in_interval", pa.int64()),
        ("transfers_out_interval", pa.int64()),
        ("net_transfers_interval", pa.int64()),
        ("net_transfer_velocity_per_hour", pa.float64()),
        ("gross_transfer_velocity_per_hour", pa.float64()),
        ("net_velocity_per_ownership_point", pa.float64()),
        ("net_transfer_acceleration_per_hour2", pa.float64()),
        ("hours_to_uk_midnight", pa.float64()),
        ("status", pa.string()),
        ("chance_this_round", pa.int64()),
        ("news", pa.string()),
    ]
)
PRICE_OUTCOME_SCHEMA = pa.schema(
    [
        ("season", pa.string()),
        ("boundary_at", pa.string()),
        ("before_observed_at", pa.string()),
        ("after_observed_at", pa.string()),
        ("boundary_gap_minutes", pa.float64()),
        ("element", pa.int64()),
        ("player_name", pa.string()),
        ("position", pa.string()),
        ("price_before", pa.int64()),
        ("price_after", pa.int64()),
        ("price_delta", pa.int64()),
        ("actual_direction", pa.string()),
        ("price_change_percent", pa.float64()),
        ("threshold_direction", pa.string()),
        ("threshold_crossed", pa.bool_()),
        ("selected_by_percent", pa.float64()),
        ("net_transfer_velocity_per_hour", pa.float64()),
        ("status", pa.string()),
        ("chance_this_round", pa.int64()),
        ("news", pa.string()),
    ]
)


def _aware(value: str | datetime | None) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value)
        if value
        else datetime.now(tz=UTC)
    )
    if parsed.tzinfo is None:
        raise ValueError("market observation time must include a timezone")
    return parsed.astimezone(UTC)


def _timestamp_id(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    rendered = json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise ValueError(f"immutable market observation collision: {path}")
    if not path.exists():
        _atomic_bytes(path, rendered.encode("utf-8"))


def _download_bytes(url: str, *, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _integer(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"market player {row.get('id')} has invalid {field}")
    return int(value)


def _optional_integer(row: Mapping[str, Any], field: str) -> int | None:
    value = row.get(field)
    return None if value is None else int(value)


def _rows(payload: Mapping[str, Any], *, observed_at: str) -> list[dict[str, Any]]:
    elements = payload.get("elements")
    teams = payload.get("teams")
    positions = payload.get("element_types")
    if not isinstance(elements, list) or not elements:
        raise ValueError("market bootstrap has no player elements")
    if not isinstance(teams, list) or not isinstance(positions, list):
        raise TypeError("market bootstrap is missing teams or positions")
    team_by_id = {
        int(row["id"]): str(row.get("short_name") or row.get("name") or row["id"])
        for row in teams
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    position_by_id = {
        int(row["id"]): str(row.get("singular_name_short") or row["id"])
        for row in positions
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    output: list[dict[str, Any]] = []
    for raw in elements:
        if not isinstance(raw, Mapping):
            raise TypeError("market bootstrap player rows must be objects")
        team = _integer(raw, "team")
        position = _integer(raw, "element_type")
        output.append(
            {
                "season": SEASON,
                "observed_at": observed_at,
                "element": _integer(raw, "id"),
                "player_code": _integer(raw, "code"),
                "player_name": str(raw.get("web_name") or ""),
                "team_id": team,
                "team": team_by_id.get(team, str(team)),
                "position": position_by_id.get(position, str(position)),
                "now_cost": _integer(raw, "now_cost"),
                "selected_by_percent": float(raw.get("selected_by_percent") or 0.0),
                "transfers_in_event": _integer(raw, "transfers_in_event"),
                "transfers_out_event": _integer(raw, "transfers_out_event"),
                "net_transfers_event": (
                    _integer(raw, "transfers_in_event")
                    - _integer(raw, "transfers_out_event")
                ),
                "transfers_in_total": _integer(raw, "transfers_in"),
                "transfers_out_total": _integer(raw, "transfers_out"),
                "cost_change_event": _integer(raw, "cost_change_event"),
                "cost_change_start": _integer(raw, "cost_change_start"),
                "price_change_percent": float(raw.get("price_change_percent") or 0.0),
                "status": str(raw.get("status") or ""),
                "chance_this_round": _optional_integer(
                    raw, "chance_of_playing_this_round"
                ),
                "chance_next_round": _optional_integer(
                    raw, "chance_of_playing_next_round"
                ),
                "news": str(raw.get("news") or ""),
                "news_added": (
                    str(raw["news_added"]) if raw.get("news_added") is not None else None
                ),
                "can_select": bool(raw.get("can_select", True)),
                "removed": bool(raw.get("removed", False)),
            }
        )
    output.sort(key=lambda row: row["element"])
    if len({row["element"] for row in output}) != len(output):
        raise ValueError("market bootstrap contains duplicate player IDs")
    return output


def collect_market_observation(
    *,
    observed_at: str | datetime | None = None,
    fetcher: Callable[[str], bytes] = _download_bytes,
    raw_root: Path = RAW_ROOT,
    observation_root: Path = OBSERVATION_ROOT,
    receipt_root: Path = RECEIPT_ROOT,
    pointer_path: Path = CURRENT_POINTER,
) -> dict[str, Any]:
    observed = _aware(observed_at)
    observed_text = observed.isoformat()
    observation_id = _timestamp_id(observed)
    url = str(sources()["fpl_current"]["files"]["bootstrap-static.json"])
    payload_bytes = fetcher(url)
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("market bootstrap is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("market bootstrap must be an object")
    rows = _rows(payload, observed_at=observed_text)

    raw_path = raw_root / observation_id / "bootstrap-static.json"
    parquet_path = observation_root / f"{observation_id}.parquet"
    receipt_path = receipt_root / f"{observation_id}.json"
    if raw_path.exists() or parquet_path.exists() or receipt_path.exists():
        if not (raw_path.is_file() and parquet_path.is_file() and receipt_path.is_file()):
            raise ValueError(f"incomplete immutable market observation: {observation_id}")
        if raw_path.read_bytes() != payload_bytes:
            raise ValueError(f"immutable market raw collision: {raw_path}")
        prior = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            prior.get("raw_sha256") != sha256_file(raw_path)
            or prior.get("parquet_sha256") != sha256_file(parquet_path)
        ):
            raise ValueError(f"market observation checksums changed: {observation_id}")
        return {**prior, "reused": True}
    if raw_path.exists() and raw_path.read_bytes() != payload_bytes:
        raise ValueError(f"immutable market raw collision: {raw_path}")
    if not raw_path.exists():
        _atomic_bytes(raw_path, payload_bytes)
    write_table(pa.Table.from_pylist(rows, schema=MARKET_SCHEMA), parquet_path)

    row_fingerprint = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt = {
        "receipt_version": 1,
        "season": SEASON,
        "observation_id": observation_id,
        "observed_at": observed_text,
        "source": url,
        "rows": len(rows),
        "raw_path": str(raw_path),
        "raw_sha256": sha256_file(raw_path),
        "parquet_path": str(parquet_path),
        "parquet_sha256": sha256_file(parquet_path),
        "receipt_path": str(receipt_path),
        "row_fingerprint": row_fingerprint,
        "price_change_nonzero": sum(
            float(row["price_change_percent"]) != 0.0 for row in rows
        ),
    }
    _atomic_json(receipt_path, receipt)
    pointer = {
        "pointer_version": 1,
        "observation_id": observation_id,
        "observed_at": observed_text,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
    }
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer_path.with_suffix(pointer_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(pointer_path)
    return receipt


def _market_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("market row observation time must include a timezone")
    return parsed.astimezone(UTC)


def _interval_velocity(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> tuple[float, float]:
    hours = (
        _market_time(str(right["observed_at"]))
        - _market_time(str(left["observed_at"]))
    ).total_seconds() / 3600.0
    if hours <= 0:
        raise ValueError("market observations must be strictly increasing")
    net_left = int(left["transfers_in_event"]) - int(left["transfers_out_event"])
    net_right = int(right["transfers_in_event"]) - int(right["transfers_out_event"])
    return (net_right - net_left) / hours, hours


def build_market_features(
    *,
    observation_root: Path = OBSERVATION_ROOT,
    output_path: Path = CURRENT_FEATURES,
    receipt_path: Path = CURRENT_FEATURE_RECEIPT,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    checked = _aware(as_of)
    paths = sorted(observation_root.glob("*.parquet"))
    if len(paths) < 2:
        result = {
            "receipt_version": 1,
            "status": "not_ready",
            "checked_at": checked.isoformat(),
            "observation_files": len(paths),
            "minimum_observation_files": 2,
            "message": "At least two immutable market observations are required.",
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(receipt_path)
        return result

    by_element: dict[int, list[dict[str, Any]]] = {}
    for path in paths:
        for row in pq.read_table(path).to_pylist():
            by_element.setdefault(int(row["element"]), []).append(row)
    feature_rows: list[dict[str, Any]] = []
    for element, observations in sorted(by_element.items()):
        observations.sort(key=lambda row: _market_time(str(row["observed_at"])))
        if len(observations) < 2:
            continue
        previous, current = observations[-2:]
        velocity, interval_hours = _interval_velocity(previous, current)
        transfers_in = int(current["transfers_in_event"]) - int(
            previous["transfers_in_event"]
        )
        transfers_out = int(current["transfers_out_event"]) - int(
            previous["transfers_out_event"]
        )
        if transfers_in < 0 or transfers_out < 0:
            # Event counters can reset after a deadline. The first post-reset interval is not a
            # within-event velocity observation and must not masquerade as a mass reversal.
            continue
        current_time = _market_time(str(current["observed_at"]))
        first_time = _market_time(str(observations[0]["observed_at"]))
        ownership = float(current["selected_by_percent"])
        acceleration = None
        if len(observations) >= 3:
            prior_velocity, prior_hours = _interval_velocity(
                observations[-3], observations[-2]
            )
            midpoint_gap = max((interval_hours + prior_hours) / 2.0, 1 / 60)
            acceleration = (velocity - prior_velocity) / midpoint_gap
        london = current_time.astimezone(ZoneInfo("Europe/London"))
        next_midnight = (london + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        feature_rows.append(
            {
                "season": SEASON,
                "feature_at": current_time.isoformat(),
                "element": element,
                "player_name": str(current["player_name"]),
                "team": str(current["team"]),
                "position": str(current["position"]),
                "data_points": len(observations),
                "span_hours": (current_time - first_time).total_seconds() / 3600.0,
                "interval_hours": interval_hours,
                "now_cost": int(current["now_cost"]),
                "cost_change_event": int(current["cost_change_event"]),
                "price_change_percent": float(current["price_change_percent"]),
                "selected_by_percent": ownership,
                "ownership_delta_pp_per_hour": (
                    ownership - float(previous["selected_by_percent"])
                )
                / interval_hours,
                "transfers_in_interval": transfers_in,
                "transfers_out_interval": transfers_out,
                "net_transfers_interval": transfers_in - transfers_out,
                "net_transfer_velocity_per_hour": velocity,
                "gross_transfer_velocity_per_hour": (
                    transfers_in + transfers_out
                )
                / interval_hours,
                "net_velocity_per_ownership_point": velocity / max(ownership, 0.1),
                "net_transfer_acceleration_per_hour2": acceleration,
                "hours_to_uk_midnight": (
                    next_midnight - london
                ).total_seconds()
                / 3600.0,
                "status": str(current["status"]),
                "chance_this_round": current["chance_this_round"],
                "news": str(current["news"]),
            }
        )
    if not feature_rows:
        raise ValueError("no players have two valid within-event market observations")
    write_table(pa.Table.from_pylist(feature_rows, schema=FEATURE_SCHEMA), output_path)
    receipt = {
        "receipt_version": 1,
        "status": "ready",
        "checked_at": checked.isoformat(),
        "feature_at": max(row["feature_at"] for row in feature_rows),
        "rows": len(feature_rows),
        "observation_files": len(paths),
        "inputs": [
            {"path": str(path), "sha256": sha256_file(path)} for path in paths
        ],
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "authority": (
            "Telemetry features are evidence only. They cannot authorize an early transfer "
            "without a separately validated net-points policy."
        ),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(receipt_path)
    return receipt


def _price_direction(value: float) -> str:
    return "rise" if value > 0 else "fall" if value < 0 else "none"


def _threshold_metrics(rows: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    predicted = [row for row in rows if row["threshold_direction"] == direction]
    actual = [row for row in rows if row["actual_direction"] == direction]
    correct = [row for row in predicted if row["actual_direction"] == direction]
    return {
        "predicted": len(predicted),
        "actual": len(actual),
        "correct": len(correct),
        "precision": len(correct) / len(predicted) if predicted else None,
        "recall": len(correct) / len(actual) if actual else None,
    }


def build_price_change_outcomes(
    *,
    observation_root: Path = OBSERVATION_ROOT,
    output_path: Path = PRICE_OUTCOMES,
    receipt_path: Path = PRICE_OUTCOME_RECEIPT,
    as_of: str | datetime | None = None,
    maximum_boundary_gap: timedelta = timedelta(hours=4),
) -> dict[str, Any]:
    """Pair observations around UK midnight to score the official price indicator."""
    checked = _aware(as_of)
    if maximum_boundary_gap <= timedelta(0):
        raise ValueError("price outcome boundary gap must be positive")
    snapshots = []
    for path in sorted(observation_root.glob("*.parquet")):
        rows = pq.read_table(path).to_pylist()
        if not rows:
            continue
        observed_times = {str(row["observed_at"]) for row in rows}
        if len(observed_times) != 1:
            raise ValueError(f"market observation mixes timestamps: {path}")
        snapshots.append(
            (
                _market_time(next(iter(observed_times))),
                path,
                {int(row["element"]): row for row in rows},
            )
        )
    snapshots.sort(key=lambda item: item[0])
    london = ZoneInfo("Europe/London")
    output_rows: list[dict[str, Any]] = []
    nights: set[str] = set()
    for index in range(len(snapshots) - 1):
        before_at, _, before = snapshots[index]
        after_at, _, after = snapshots[index + 1]
        before_local = before_at.astimezone(london)
        after_local = after_at.astimezone(london)
        if after_local.date() == before_local.date():
            continue
        if (after_local.date() - before_local.date()).days != 1:
            continue
        boundary_local = after_local.replace(hour=0, minute=0, second=0, microsecond=0)
        boundary = boundary_local.astimezone(UTC)
        if not before_at <= boundary < after_at:
            continue
        gap = after_at - before_at
        if gap > maximum_boundary_gap:
            continue
        prior = snapshots[index - 1] if index > 0 else None
        prior_rows = prior[2] if prior is not None else {}
        prior_at = prior[0] if prior is not None else None
        if prior_at is not None and prior_at.astimezone(london).date() != before_local.date():
            prior_rows = {}
            prior_at = None
        common = sorted(set(before).intersection(after))
        nights.add(boundary.isoformat())
        for element in common:
            left = before[element]
            right = after[element]
            price_delta = int(right["now_cost"]) - int(left["now_cost"])
            progress = float(left["price_change_percent"])
            velocity = None
            earlier = prior_rows.get(element)
            if earlier is not None and prior_at is not None:
                transfers_in = int(left["transfers_in_event"]) - int(
                    earlier["transfers_in_event"]
                )
                transfers_out = int(left["transfers_out_event"]) - int(
                    earlier["transfers_out_event"]
                )
                hours = (before_at - prior_at).total_seconds() / 3600.0
                if transfers_in >= 0 and transfers_out >= 0 and hours > 0:
                    velocity = (transfers_in - transfers_out) / hours
            output_rows.append(
                {
                    "season": SEASON,
                    "boundary_at": boundary.isoformat(),
                    "before_observed_at": before_at.isoformat(),
                    "after_observed_at": after_at.isoformat(),
                    "boundary_gap_minutes": gap.total_seconds() / 60.0,
                    "element": element,
                    "player_name": str(left["player_name"]),
                    "position": str(left["position"]),
                    "price_before": int(left["now_cost"]),
                    "price_after": int(right["now_cost"]),
                    "price_delta": price_delta,
                    "actual_direction": _price_direction(price_delta),
                    "price_change_percent": progress,
                    "threshold_direction": (
                        _price_direction(progress) if abs(progress) >= 100.0 else "none"
                    ),
                    "threshold_crossed": abs(progress) >= 100.0,
                    "selected_by_percent": float(left["selected_by_percent"]),
                    "net_transfer_velocity_per_hour": velocity,
                    "status": str(left["status"]),
                    "chance_this_round": left["chance_this_round"],
                    "news": str(left["news"]),
                }
            )
    if not output_rows:
        result = {
            "receipt_version": 1,
            "status": "not_ready",
            "checked_at": checked.isoformat(),
            "observation_files": len(snapshots),
            "outcome_nights": 0,
            "message": (
                "No sufficiently tight before/after UK-midnight observation pair exists yet."
            ),
            "authority": False,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(receipt_path)
        return result
    output_rows.sort(key=lambda row: (row["boundary_at"], row["element"]))
    write_table(pa.Table.from_pylist(output_rows, schema=PRICE_OUTCOME_SCHEMA), output_path)
    metrics = {
        direction: _threshold_metrics(output_rows, direction)
        for direction in ("rise", "fall")
    }
    minimum_nights = 14
    minimum_predictions = 30
    precision_floor = 0.75
    calibration_ready = (
        len(nights) >= minimum_nights
        and all(metrics[direction]["predicted"] >= minimum_predictions for direction in metrics)
        and all(
            metrics[direction]["precision"] is not None
            and metrics[direction]["precision"] >= precision_floor
            for direction in metrics
        )
    )
    receipt = {
        "receipt_version": 1,
        "status": "ready",
        "checked_at": checked.isoformat(),
        "observation_files": len(snapshots),
        "outcome_nights": len(nights),
        "rows": len(output_rows),
        "actual_changes": sum(row["actual_direction"] != "none" for row in output_rows),
        "threshold_metrics": metrics,
        "calibration_gate": {
            "passed": calibration_ready,
            "minimum_nights": minimum_nights,
            "minimum_predictions_per_direction": minimum_predictions,
            "precision_floor": precision_floor,
        },
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "inputs": [
            {"path": str(path), "sha256": sha256_file(path)}
            for _, path, _ in snapshots
        ],
        "authority": False,
        "information_policy": (
            "Only observation pairs bracketing UK midnight by at most four hours are scored. "
            "The official percentage is progress toward a threshold, not a probability."
        ),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(receipt_path)
    return receipt


def build_market_evidence(
    *,
    observation_root: Path = OBSERVATION_ROOT,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    """Build both current velocity features and cumulative nightly calibration evidence."""
    features = build_market_features(observation_root=observation_root, as_of=as_of)
    outcomes = build_price_change_outcomes(observation_root=observation_root, as_of=as_of)
    return {**features, "price_outcomes": outcomes}
