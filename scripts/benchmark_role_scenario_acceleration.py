from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from fplagent_engine.preseason_role_scenario import (
    RESULTS_JSON,
    consume_role_scenario_worker_cpu_seconds,
    run_preseason_role_scenario_audit,
)


def main() -> None:
    reference = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="fplagent-role-benchmark-") as directory:
        output = Path(directory)
        started = time.perf_counter()
        accelerated = run_preseason_role_scenario_audit(
            results_path=output / "results.json",
            report_path=output / "report.md",
        )
        elapsed = time.perf_counter() - started
        worker_cpu_seconds = consume_role_scenario_worker_cpu_seconds()
    if accelerated != reference:
        raise RuntimeError("accelerated role-scenario result differs from published reference")
    print(f"elapsed_seconds={elapsed:.3f}")
    print(f"worker_cpu_seconds={worker_cpu_seconds:.3f}")
    print(f"worker_average_cores={worker_cpu_seconds / elapsed:.3f}")
    print("outputs_equal=true")
    print(f"scenarios={len(accelerated['scenarios'])}")


if __name__ == "__main__":
    main()
