"""Capture a bounded private Scout comparison; no live advice is changed."""
import argparse
import json
from pathlib import Path

from fplagent_data.live_snapshots import latest_official_snapshot
from fplagent_engine.models import CURRENT_FORECAST
from fplagent_engine.rules import load_rules
from fplagent_engine.scout_benchmark import capture

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-contract", type=Path, required=True)
    parser.add_argument("--forecast", type=Path, default=CURRENT_FORECAST)
    parser.add_argument("--event", type=int, required=True)
    parser.add_argument("--horizon", type=int, default=4)
    args = parser.parse_args()
    state = json.loads(args.manager_contract.read_text())
    official_dir, _ = latest_official_snapshot()
    bootstrap = json.loads((official_dir / "bootstrap-static.json").read_text())
    deadline = next(e["deadline_time"] for e in bootstrap["events"] if int(e["id"]) == args.event)
    result = capture(forecast_path=args.forecast, held_ids=[int(p["player_id"]) for p in state["manager_state"]["squad"]],
                     events=tuple(range(args.event, args.event + args.horizon)),
                     deadline=deadline, rules=load_rules(), manager_contract_path=args.manager_contract)
    print(json.dumps(result, indent=2))
