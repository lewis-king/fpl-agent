from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from fplagent_engine.robust_search import SHORTLIST_JSON, parallel_policy_variants
from fplagent_engine.tournament import DEFAULT_EVENTS, _load_rows


def _canonical(value: list[dict[str, Any]]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark deterministic serial and parallel FPL policy solves."
    )
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.candidates < 1 or args.workers < 1:
        parser.error("candidates and workers must be positive")

    rows, _ = _load_rows(DEFAULT_EVENTS)
    payload = json.loads(SHORTLIST_JSON.read_text(encoding="utf-8"))
    candidates = payload["candidates"][: args.candidates]

    os.environ["FPLAGENT_POLICY_WORKERS"] = "1"
    started = time.perf_counter()
    serial = parallel_policy_variants(
        candidates,
        rows,
        progress_label="Serial benchmark",
    )
    serial_seconds = time.perf_counter() - started

    os.environ["FPLAGENT_POLICY_WORKERS"] = str(args.workers)
    started = time.perf_counter()
    parallel = parallel_policy_variants(
        candidates,
        rows,
        progress_label="Parallel benchmark",
    )
    parallel_seconds = time.perf_counter() - started

    equivalent = _canonical(serial) == _canonical(parallel)
    result = {
        "candidates": len(candidates),
        "milp_policies": len(candidates) * 2,
        "workers": min(args.workers, len(candidates) * 2),
        "serial_seconds": round(serial_seconds, 3),
        "parallel_seconds": round(parallel_seconds, 3),
        "speedup": round(serial_seconds / parallel_seconds, 3),
        "exactly_equivalent": equivalent,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if not equivalent:
        raise SystemExit("Parallel policies differ from the serial reference")


if __name__ == "__main__":
    main()

