"""Independent cash/FT/formation and exhaustive legal-substitution receipt check.

Read-only: does not use apply_action, the optimizer, or production autosub scoring.
Uses the same declared archived prices; cannot establish missing quote availability.
"""
import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import pyarrow.parquet as pq


def score(record, meta, minutes):
    starters, bench = record["starters"], record["bench_order"]
    def played(p):
        return minutes[p] > 0
    active = [p for p in starters if played(p)]
    keeper = next(p for p in starters if meta[p]["position"] == "GK")
    bench_keeper = next(p for p in bench if meta[p]["position"] == "GK")
    if not played(keeper) and played(bench_keeper):
        active.append(bench_keeper)
    missing = [p for p in starters if not played(p) and meta[p]["position"] != "GK"]
    reserves = [p for p in bench if played(p) and meta[p]["position"] != "GK"]
    # Enumerate every feasible set of substitutions. Max fill then bench priority.
    legal = []
    original = Counter(meta[p]["position"] for p in starters)
    for count in range(min(len(missing), len(reserves)) + 1):
        for incoming in combinations(reserves, count):
            for outgoing in combinations(missing, count):
                positions = original.copy()
                positions.subtract(meta[p]["position"] for p in outgoing)
                positions.update(meta[p]["position"] for p in incoming)
                if positions["DEF"] >= 3 and positions["MID"] >= 2 and positions["FWD"] >= 1:
                    legal.append(incoming)
                    break
    chosen = min(legal, key=lambda group: (-len(group), tuple(p not in group for p in reserves)))
    active.extend(chosen)
    captain = record["captain"] if played(record["captain"]) else record["vice_captain"]
    bonus = meta[captain]["target_points"] if played(captain) else 0
    return sum(meta[p]["target_points"] for p in active) + bonus


def verify(path):
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "completed" and receipt["hashes_stable"]
    forecasts = next(Path(p) for p in receipt["source_hashes"] if p.endswith("backtest.parquet"))
    features = next(Path(p) for p in receipt["source_hashes"] if p.endswith("player_deadlines.parquet"))
    seasons = [f["season"] for f in receipt["folds"]]
    base = pq.read_table(forecasts, columns=["season", "event_number", "element", "position",
                                            "team_id", "market_price", "target_points"],
                         filters=[("season", "in", seasons)]).to_pylist()
    minute_rows = pq.read_table(features, columns=["season", "event_number", "element", "target_minutes"],
                                filters=[("season", "in", seasons)]).to_pylist()
    catalog = {(r["season"], r["event_number"], r["element"]): r for r in base}
    minute_map = {(r["season"], r["event_number"], r["element"]): r["target_minutes"] for r in minute_rows}
    checked = 0
    for fold in receipt["folds"]:
        season = fold["season"]
        for name, arm in fold["paths"].items():
            bank, holdings, free = 1000, {}, 0
            for record in arm["events"]:
                event = record["event"]
                meta = {p: r for (s, e, p), r in catalog.items() if s == season and e == event}
                minutes = {p: minute_map[(season, event, p)] for p in record["selected"]}
                def price(p, meta=meta):
                    value = float(meta[p]["market_price"])
                    assert value > 0 and value == round(value)
                    return int(value)
                def sale(p, holdings=holdings, price=price):
                    return min(price(p), holdings[p]) + max(0, price(p) - holdings[p]) // 2
                if event == 1:
                    holdings.update({p: price(p) for p in record["selected"]})
                    bank -= sum(holdings.values())
                else:
                    outgoing = [t["out"] for t in record["transfers"]]
                    incoming = [t["in"] for t in record["transfers"]]
                    assert len(set(outgoing)) == len(outgoing) == len(set(incoming))
                    assert set(outgoing) <= holdings.keys() and not set(incoming) & holdings.keys()
                    bank += sum(sale(p) for p in outgoing) - sum(price(p) for p in incoming)
                    for p in outgoing:
                        del holdings[p]
                    holdings.update({p: price(p) for p in incoming})
                count = len(record["transfers"])
                assert record["free_transfers_before"] == free
                assert record["points_cost"] == max(0, count - free) * 4
                free = min(5, max(0, free - count) + 1)
                assert record["free_transfers_after"] == free
                assert bank == record["bank_after"] and bank >= 0
                assert sum(sale(p) for p in holdings) == record["sale_value_after"]
                assert set(holdings) == set(record["selected"]) and len(holdings) == 15
                assert Counter(meta[p]["position"] for p in holdings) == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
                assert max(Counter(meta[p]["team_id"] for p in holdings).values()) <= 3
                xi, bench = record["starters"], record["bench_order"]
                assert len(set(xi)) == 11 and len(set(bench)) == 4 and not set(xi) & set(bench)
                assert set(xi) | set(bench) == set(holdings)
                counts = Counter(meta[p]["position"] for p in xi)
                assert counts["GK"] == 1 and counts["DEF"] >= 3 and counts["MID"] >= 2 and counts["FWD"] >= 1
                assert record["captain"] in xi and record["vice_captain"] in xi
                assert record["captain"] != record["vice_captain"]
                assert score(record, meta, minutes) == record["gross_points"], (season, name, event)
                assert record["net_points"] == record["gross_points"] - record["points_cost"]
                checked += 1
            assert arm["net_points"] == sum(r["net_points"] for r in arm["events"])
    return {"verified_arm_events": checked, "receipt": str(path),
            "scope": "Independent arithmetic and legal substitutions under declared archived prices; not a check of quote availability or model accuracy."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    print(json.dumps(verify(parser.parse_args().receipt), indent=2))
