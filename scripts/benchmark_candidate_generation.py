from __future__ import annotations

import argparse
import time

from fplagent_engine.rules import load_rules, validate_lineup, validate_squad
from fplagent_engine.tournament import DEFAULT_EVENTS, _load_rows, generate_candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=int, default=128)
    args = parser.parse_args()
    started = time.perf_counter()
    payload = generate_candidates(count=args.candidates)
    elapsed = time.perf_counter() - started
    _, loaded = _load_rows(DEFAULT_EVENTS)
    meta = loaded["meta"]
    rules = load_rules()
    for candidate in payload["candidates"]:
        squad_rows = [meta[int(element)] for element in candidate["selected"]]
        validate_squad(squad_rows, rules)
        for event in DEFAULT_EVENTS:
            lineup = candidate["lineups"][str(event)]
            validate_lineup(
                squad_rows,
                lineup["starters"],
                lineup["bench_order"],
                lineup["captain"],
                lineup["vice_captain"],
                rules,
            )
    fingerprints = {frozenset(candidate["selected"]) for candidate in payload["candidates"]}
    if len(fingerprints) != args.candidates:
        raise RuntimeError("candidate generation returned duplicate squads")
    print(f"candidates={args.candidates}")
    print(f"elapsed_seconds={elapsed:.3f}")
    print("all_unique=true")
    print("all_legal=true")


if __name__ == "__main__":
    main()
