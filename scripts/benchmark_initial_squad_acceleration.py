from __future__ import annotations

import os
import time

from fplagent_engine.optimizer import _player_rows, _solve, _stability


def _run(rows: list[dict], events: list[int], primary: dict, workers: int) -> tuple[dict, float]:
    os.environ["FPLAGENT_POLICY_WORKERS"] = str(workers)
    started = time.perf_counter()
    result = _stability(rows, events, primary, samples=20)
    return result, time.perf_counter() - started


def main() -> None:
    rows, events = _player_rows()
    primary = _solve(rows, events)
    serial, serial_seconds = _run(rows, events, primary, 1)
    parallel, parallel_seconds = _run(rows, events, primary, 12)
    if serial != parallel:
        raise RuntimeError("parallel stability output differs from the serial reference")
    print(f"serial_seconds={serial_seconds:.3f}")
    print(f"parallel_seconds={parallel_seconds:.3f}")
    print(f"speedup={serial_seconds / parallel_seconds:.3f}x")
    print("outputs_equal=true")


if __name__ == "__main__":
    main()
