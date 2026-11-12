"""Frozen gate/search experiment. Does not publish advice or change live policy."""
import argparse
from pathlib import Path

from fplagent_engine.gate_search_replay import run_experiment
from fplagent_engine.sequential_policy_replay import SequentialConfig

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10000)
    parser.add_argument("--end-event", type=int, default=10)
    parser.add_argument("--seasons", nargs="+", default=["2024-25", "2025-26"])
    args = parser.parse_args()
    run_experiment(args.output, SequentialConfig(seasons=tuple(args.seasons), end_event=args.end_event,
                                                 samples=args.samples), lambda r: print(r, flush=True))
