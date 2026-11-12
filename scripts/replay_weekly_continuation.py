"""Run the read-only, early-season adaptive-transfer experiment."""

import argparse
import json
from pathlib import Path

from fplagent_engine.weekly_continuation_replay import ReplayConfig, run_replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New research receipt; never the live decision"
    )
    parser.add_argument("--end-event", type=int, default=10)
    parser.add_argument("--solver-seconds", type=float, default=2.0)
    args = parser.parse_args()
    result = run_replay(
        args.output,
        ReplayConfig(end_event=args.end_event, solver_seconds=args.solver_seconds),
        progress=lambda item: print(json.dumps(item), flush=True),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "historical_screen_passed": result["historical_screen_passed"],
                "folds": [
                    {"season": f["season"], "net_points_delta": f["net_points_delta"]}
                    for f in result["folds"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
