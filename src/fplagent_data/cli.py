from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from . import (
    fpl_current,
    fpl_genius,
    solio,
    supporting,
    vaastav,
    vaastav_deadlines,
    veterans,
)
from .analysis import run as run_analysis
from .database import build_catalog
from .event_outcomes import collect_event_outcome
from .http import sha256_file
from .live_snapshots import latest_official_status, record_refresh_receipt
from .market_telemetry import (
    build_market_features,
    build_price_change_outcomes,
    collect_market_observation,
)
from .paths import ensure_layout
from .preseason_lineups import collect_preseason_lineups, upgrade_role_receipt_mapping
from .validate import validate

SOURCES = {
    "solio": solio,
    "fpl_genius": fpl_genius,
    "veterans": veterans,
    "vaastav": vaastav,
    "vaastav_deadlines": vaastav_deadlines,
    "supporting": supporting,
    "fpl_current": fpl_current,
}
ORDER = tuple(SOURCES)


def _selected(value: str) -> list[str]:
    return list(ORDER) if value == "all" else [value]


def _fetch(names: list[str], force: bool) -> None:
    for name in names:
        print(f"\n== fetch: {name} ==")
        SOURCES[name].fetch(force=force)


def _preprocess(names: list[str]) -> dict:
    report = {}
    for name in names:
        print(f"\n== preprocess: {name} ==")
        report[name] = SOURCES[name].preprocess()
        print(json.dumps(report[name], indent=2, sort_keys=True))
    return report


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="fpl-data")
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("fetch", "preprocess", "build"):
        item = commands.add_parser(command)
        item.add_argument("--source", choices=("all", *ORDER), default="all")
        if command in {"fetch", "build"}:
            item.add_argument("--force", action="store_true")
    commands.add_parser("validate")
    commands.add_parser("catalog")
    commands.add_parser("analyse")
    refresh_current = commands.add_parser("refresh-current")
    refresh_current.add_argument("--no-catalog", action="store_true")
    refresh_current.add_argument(
        "--reuse-latest",
        action="store_true",
        help="reprocess the latest validated immutable snapshot without fetching a new one",
    )
    snapshot_status = commands.add_parser("snapshot-status")
    snapshot_status.add_argument("--as-of")
    event_outcome = commands.add_parser("collect-event-outcome")
    event_outcome.add_argument("--event", type=int, required=True)
    event_outcome.add_argument("--observed-at")
    event_outcome.add_argument("--reuse-latest-official", action="store_true")
    commands.add_parser("collect-preseason-lineups")
    commands.add_parser("upgrade-preseason-role-lineage")
    market_observation = commands.add_parser("collect-market-observation")
    market_observation.add_argument("--observed-at")
    commands.add_parser("build-market-features")
    commands.add_parser("build-price-change-outcomes")
    return root


def main() -> None:
    args = parser().parse_args()
    ensure_layout()
    if args.command == "validate":
        print(json.dumps(validate(), indent=2, sort_keys=True))
        return
    if args.command == "catalog":
        print(json.dumps(build_catalog(), indent=2, sort_keys=True))
        return
    if args.command == "analyse":
        print(json.dumps(run_analysis(), indent=2, sort_keys=True))
        return
    if args.command == "snapshot-status":
        print(
            json.dumps(
                latest_official_status(as_of=args.as_of),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command == "collect-event-outcome":
        fpl_current.fetch(force=not args.reuse_latest_official)
        print(
            json.dumps(
                collect_event_outcome(args.event, observed_at=args.observed_at),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command == "collect-preseason-lineups":
        print(json.dumps(collect_preseason_lineups(), indent=2, sort_keys=True))
        return
    if args.command == "upgrade-preseason-role-lineage":
        print(json.dumps(upgrade_role_receipt_mapping(), indent=2, sort_keys=True))
        return
    if args.command == "collect-market-observation":
        print(
            json.dumps(
                collect_market_observation(observed_at=args.observed_at),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command == "build-market-features":
        print(json.dumps(build_market_features(), indent=2, sort_keys=True))
        return
    if args.command == "build-price-change-outcomes":
        print(json.dumps(build_price_change_outcomes(), indent=2, sort_keys=True))
        return
    if args.command == "refresh-current":
        snapshot = fpl_current.fetch(force=not args.reuse_latest)
        status = latest_official_status()
        if not status["publishable"]:
            raise RuntimeError(f"current snapshot cannot be published: {status['issues']}")
        processed = fpl_current.preprocess()
        catalog = None if args.no_catalog else build_catalog()
        receipt = {
            "receipt_version": 1,
            "completed_at": datetime.now(tz=UTC).isoformat(),
            "snapshot_id": status["snapshot_id"],
            "status": status,
            "processed": processed,
            "processed_sha256": {
                path.name: sha256_file(path)
                for path in sorted(fpl_current.OUT_DIR.glob("*.parquet"))
            },
            "catalog": catalog,
        }
        record_refresh_receipt(receipt)
        print(
            json.dumps(
                {"snapshot": snapshot, "receipt": receipt},
                indent=2,
                sort_keys=True,
            )
        )
        return
    names = _selected(args.source)
    if args.command in {"fetch", "build"}:
        _fetch(names, args.force)
    if args.command in {"preprocess", "build"}:
        _preprocess(names)
    if args.command == "build" and args.source == "all":
        print(json.dumps(build_catalog(), indent=2, sort_keys=True))
        print(json.dumps(validate(), indent=2, sort_keys=True))
