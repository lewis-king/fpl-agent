"""Real squads of managers at fixed overall ranks, from the public FPL API.

Usage: PYTHONPATH=src .venv/bin/python scripts/season_review/rival_sample.py --event 10
Writes data/analysis/rivals/gwNN.json: rank, total and picks for each manager.
Public endpoints only. Research input for wildcard_challenge.py.
"""

import argparse
import json
from pathlib import Path

import httpx

from fplagent_data.elite_sample import OVERALL_LEAGUE, _public_get

# Standings pages hold 50 managers: page 20000 starts near rank 1,000,000.
BANDS = (("10k", 200), ("100k", 2000), ("500k", 10000), ("1m", 20000),
         ("2m", 40000), ("3m", 60000), ("3.6m", 72000))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=int, required=True)
    parser.add_argument("--per-band", type=int, default=30)
    args = parser.parse_args()
    managers = []
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
        for band, page in BANDS:
            rows = _public_get(
                client, f"leagues-classic/{OVERALL_LEAGUE}/standings/?page_standings={page}"
            )["standings"]["results"][: args.per_band]
            for row in rows:
                picks = _public_get(client, f"entry/{row['entry']}/event/{args.event}/picks/")
                managers.append({
                    "band": band, "rank": int(row["rank"]), "total": int(row["total"]),
                    "active_chip": picks.get("active_chip"),
                    "picks": [[int(p["element"]), int(p["multiplier"])] for p in picks["picks"]],
                })
            print(f"{band}: {len(rows)} managers, rank {rows[0]['rank']}, total {rows[0]['total']}",
                  flush=True)
    path = Path(f"data/analysis/rivals/gw{args.event:02d}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"event": args.event, "managers": managers}) + "\n")


if __name__ == "__main__":
    main()
