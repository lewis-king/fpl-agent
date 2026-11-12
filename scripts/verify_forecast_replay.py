"""Independent accounting / legal-substitution check for forecast-ablation receipts."""

import argparse
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from verify_policy_ledger import score


def verify(path):
    result = json.loads(path.read_text())
    assert result["status"] == "completed" and result["hashes_stable"]
    features = next(
        Path(p) for p in result["source_hashes"] if p.endswith("player_deadlines.parquet")
    )
    minutes = {
        (r["season"], int(r["event_number"]), int(r["element"])): r["target_minutes"]
        for r in pq.read_table(
            features, columns=["season", "event_number", "element", "target_minutes"]
        ).to_pylist()
    }
    if "folds" in result:
        forecast = next(Path(p) for p in result["source_hashes"] if p.endswith("backtest.parquet"))
        jobs = [
            (fold["season"], name, arm, forecast)
            for fold in result["folds"]
            for name, arm in fold["paths"].items()
        ]
    else:
        jobs = [
            (season, name, policy, Path(arm["forecast_path"]))
            for name, arm in result["arms"].items()
            for season, policy in arm["policies"].items()
        ]
    tables, checked, missing = {}, 0, 0
    for season, name, arm, forecast in jobs:
        if forecast not in tables:
            tables[forecast] = {
                (r["season"], int(r["event_number"]), int(r["element"])): r
                for r in pq.read_table(forecast).to_pylist()
            }
        catalog = tables[forecast]
        bank, free, holdings, previous = 1000, 1, {}, {}
        for r in arm["events"]:
            event = r["event"]
            meta = {p: row for (s, e, p), row in catalog.items() if s == season and e == event}
            for p in holdings:
                if p not in meta:
                    meta[p] = {**previous[p], "target_points": 0}
                    missing += 1

            def price(p, meta=meta):
                return round(float(meta[p]["market_price"]))

            def selling(p, price=price, holdings=holdings):
                return min(price(p), holdings[p]) + max(0, price(p) - holdings[p]) // 2

            if event == 1:
                holdings = {p: price(p) for p in r["selected"]}
                bank -= sum(holdings.values())
            else:
                outs, ins = [t["out"] for t in r["transfers"]], [t["in"] for t in r["transfers"]]
                assert len(set(outs)) == len(outs) == len(set(ins))
                assert set(outs) <= holdings.keys() and not set(ins) & holdings.keys()
                bank += sum(selling(p) for p in outs) - sum(price(p) for p in ins)
                for p in outs:
                    del holdings[p]
                holdings.update({p: price(p) for p in ins})
            count = len(r["transfers"])
            assert r["free_transfers_before"] == free
            assert r["points_cost"] == max(0, count - free) * 4
            free = min(5, max(0, free - count) + 1)
            assert r["free_transfers_after"] == (None if event == 38 else free)
            assert bank == r["bank_after"] and bank >= 0, (season, name, event, bank, r['bank_after'])
            assert set(holdings) == set(r["selected"]) and len(holdings) == 15
            assert Counter(meta[p]["position"] for p in holdings) == {
                "GK": 2,
                "DEF": 5,
                "MID": 5,
                "FWD": 3,
            }
            if event == 1 or count:
                assert max(Counter(meta[p]["team_id"] for p in holdings).values()) <= 3
            xi, bench = r["starters"], r["bench_order"]
            assert len(set(xi)) == 11 and len(set(bench)) == 4 and not set(xi) & set(bench)
            assert set(xi) | set(bench) == set(holdings)
            formation = Counter(meta[p]["position"] for p in xi)
            assert (
                formation["GK"] == 1
                and formation["DEF"] >= 3
                and formation["MID"] >= 2
                and formation["FWD"] >= 1
            )
            assert (
                r["captain"] in xi and r["vice_captain"] in xi and r["captain"] != r["vice_captain"]
            )
            minute_map = {p: minutes.get((season, event, p), 0) for p in holdings}
            assert score(r, meta, minute_map) == r["gross_points"], (season, name, event)
            assert r["net_points"] == r["gross_points"] - r["points_cost"]
            previous = meta
            checked += 1
        assert arm["net_points"] == sum(r["net_points"] for r in arm["events"])
    return {
        "verified_arm_events": checked,
        "missing_holding_event_fallbacks": missing,
        "scope": "Independent cash, FT, hits, legal XI/bench/CVC and score arithmetic. Uses declared lagged-price / missing-row assumptions, not proof of archived quote freshness.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    print(json.dumps(verify(parser.parse_args().receipt), indent=2))
