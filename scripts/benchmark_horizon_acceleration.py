from __future__ import annotations

import argparse
import json
import os
import time

from fplagent_engine.horizon_audit import (
    EVENTS,
    _generate_horizon_candidates,
    _load_incumbent_candidates,
)
from fplagent_engine.rules import load_rules, validate_squad
from fplagent_engine.tournament import _load_rows


def _run(
    workers: int,
    count: int,
    by_player: dict,
    meta: dict,
    incumbents: list[dict],
) -> tuple[list[dict], float]:
    os.environ["FPLAGENT_POLICY_WORKERS"] = str(workers)
    started = time.perf_counter()
    values = _generate_horizon_candidates(
        by_player,
        meta,
        incumbents,
        count,
        20260807,
    )
    return values, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark serial and parallel horizon challenger generation."
    )
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.candidates < 1 or args.workers < 1:
        parser.error("candidates and workers must be positive")

    _, loaded = _load_rows(EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    incumbents, _ = _load_incumbent_candidates(by_player, meta)
    serial, serial_seconds = _run(1, args.candidates, by_player, meta, incumbents)
    parallel, parallel_seconds = _run(
        args.workers,
        args.candidates,
        by_player,
        meta,
        incumbents,
    )

    rules = load_rules()
    for candidate in [*serial, *parallel]:
        validate_squad([meta[element] for element in candidate["selected"]], rules)
    result = {
        "candidates": args.candidates,
        "workers": min(args.workers, args.candidates),
        "serial_seconds": round(serial_seconds, 3),
        "parallel_seconds": round(parallel_seconds, 3),
        "speedup": round(serial_seconds / parallel_seconds, 3),
        "serial_unique": len({value["candidate_id"] for value in serial}),
        "parallel_unique": len({value["candidate_id"] for value in parallel}),
        "all_squads_legal": True,
        "parallel_deterministic_seed": 20260807,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

