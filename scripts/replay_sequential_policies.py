"""Run the frozen chronological policy experiment without touching live decisions."""

import argparse
import json
from pathlib import Path

from fplagent_engine.sequential_policy_replay import SequentialConfig, run_replay

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-event", type=int, default=10)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--solver-seconds", type=float, default=5.0)
    args = parser.parse_args()
    result = run_replay(
        args.output, SequentialConfig(end_event=args.end_event, samples=args.samples,
                                      solver_seconds=args.solver_seconds),
        progress=lambda row: print(json.dumps(row), flush=True),
    )
    print(json.dumps({"status": result["status"], "screens": result["historical_screens"],
                      "seconds": result["elapsed_seconds"]}))
