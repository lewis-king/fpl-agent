"""Fixed three-season availability ablation. Never trains or publishes a live model.

Compares frozen OOF xP, explicit dated next-round-zero enforcement, and lagged form5.
Runs complete 38-event legal transfer ledgers, without current-season outcomes in selection.
This tests an isolated hard-zero policy, NOT refitting the incorrectly indexed input feature.
"""

import argparse
import time
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_engine.features import TRAINING_FEATURES
from fplagent_engine.forecast_diagnosis import error_summary, historical_next_chance, save_diagnosis
from fplagent_engine.market_transfer_replay import moving_block_mean_interval, run_policy_season
from fplagent_engine.models import BACKTEST_FORECAST, _atomic_json
from fplagent_engine.rules import load_rules


def run(output):
    if output.exists():
        raise FileExistsError("Preserve previous experiment receipts")
    snapshots = Path("data/processed/vaastav_deadlines/player_snapshots.parquet")
    source_paths = [
        TRAINING_FEATURES,
        BACKTEST_FORECAST,
        snapshots,
        Path(__file__),
        *Path("src/fplagent_engine").glob("*.py"),
        Path("src/fplagent_data/availability.py"),
    ]
    hashes = {str(p): sha256_file(p) for p in source_paths}
    started = time.monotonic()
    result = {
        "version": "round_availability_ablation_v1",
        "status": "running",
        "decision_authority": False,
        "source_hashes": hashes,
        "definition": {
            "seasons": ["2023-24", "2024-25", "2025-26"],
            "events": [1, 38],
            "arms": ["incumbent", "explicit_next_zero", "form5_control"],
            "rule": "Zero only for an explicit 0 next-round chance, dated before deadline and at most seven days old; missing coverage retains incumbent.",
            "policy": "Same one-event legal optimizer, own rolling squad/cash/FT/hits, one candidate per transfer count, max5 transfers/two paid, zero terminal FT value for all arms, no chips.",
            "interpretation": "Mechanistic correctness can be released independently of empirical gain; do not change thresholds or select a season after seeing results. No learned-model or SOTA promotion from this run.",
        },
        "limitations": [
            "Deadline proxies use Git observation and fixture kickoff minus90minutes; no exact intraday FPL field rollover archived.",
            "Historical availability coverage is incomplete, especially2025/26. Old forecasts themselves were trained with this-round metadata; this is not corrected-feature retraining.",
            "Current scoring/transfer rules are held identical across arms, not a reproduction of each past season’s chip/FT rules.",
            "Historical prices may be lagged and fixture assignments are not a complete point-in-time forward grid. One-event replay, not the production multi-world five-event optimizer.",
            "Historical folds have been examined previously; not a pristine holdout. No retrospective Scout projections are used.",
        ],
        "folds": [],
    }

    def save(stage):
        result["stage"] = stage
        result["elapsed_seconds"] = time.monotonic() - started
        _atomic_json(output, result)
        print(stage, flush=True)

    save("registered before reading historical outcome scores")
    try:
        result["season_diagnosis"] = save_diagnosis()
        features = {
            (r["season"], int(r["event_number"]), int(r["element"])): r
            for r in pq.read_table(
                TRAINING_FEATURES, columns=["season", "event_number", "element", "target_minutes"]
            ).to_pylist()
        }
        official = {}
        for r in pq.read_table(
            snapshots,
            columns=[
                "season",
                "decision_event",
                "id",
                "observed_at",
                "deadline_at",
                "chance_of_playing_next_round",
            ],
        ).to_pylist():
            key = (r["season"], int(r["decision_event"]), int(r["id"]))
            if key in official:
                raise ValueError("Ambiguous historical player deadline")
            official[key] = historical_next_chance(r)
        grouped = {}
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist():
            key = (row["season"], int(row["event_number"]), int(row["element"]))
            if row.get("market_price") is None:
                continue
            chance = official.get(key)
            xp = float(row["expected_points"])
            r = {
                **row,
                "target_minutes": features[key]["target_minutes"],
                "market_price": round(float(row["market_price"])),
                "xp_expected_points": xp,
                "incumbent": xp,
                "explicit_next_zero": 0.0 if chance == 0 else xp,
                "form5_control": float(row["form5_expected_points"]),
                "official_next_chance": chance,
                "can_select": True,
                "removed": False,
            }
            grouped.setdefault((row["season"], int(row["event_number"])), []).append(r)
        rules = load_rules()
        for season in result["definition"]["seasons"]:
            rows = [r for (s, _), rs in grouped.items() if s == season for r in rs]
            changed = [r for r in rows if r["official_next_chance"] == 0]
            fold = {
                "season": season,
                "players": len(rows),
                "explicit_chance_rows": sum(r["official_next_chance"] is not None for r in rows),
                "zero_chance_rows": len(changed),
                "zero_chance_but_appeared": sum(r["target_minutes"] > 0 for r in changed),
                "forecast_metrics": {},
                "paths": {},
            }
            result["folds"].append(fold)
            for name in result["definition"]["arms"]:
                for cohort, subset in [("all", rows), ("zero_flag", changed)]:
                    fold["forecast_metrics"][f"{name}_{cohort}"] = error_summary(
                        [
                            dict(
                                r,
                                expected_points=r[name],
                                actual_points=r["target_points"],
                                actual_minutes=r["target_minutes"],
                                p_play=0.0
                                if name == "explicit_next_zero" and r["official_next_chance"] == 0
                                else (1.0 if name == "form5_control" else r["p_play"]),
                            )
                            for r in subset
                        ]
                    )
                save(f"{season}: replaying {name}, all38events")
                fold["paths"][name] = run_policy_season(
                    season=season,
                    policy=name,
                    grouped=grouped,
                    market_weight=1,
                    rules=rules,
                    terminal_curve={bank: 0.0 for bank in range(rules.max_free_transfers + 1)},
                    score_field=name,
                )
                save(f"{season}: {name} net={fold['paths'][name]['net_points']}")
            base = fold["paths"]["incumbent"]
            fold["paired_delta"] = {}
            for name in ("explicit_next_zero", "form5_control"):
                values = [
                    r["net_points"] - b["net_points"]
                    for r, b in zip(fold["paths"][name]["events"], base["events"], strict=True)
                ]
                fold["paired_delta"][name] = dict(
                    total=sum(values), **moving_block_mean_interval(values)
                )
        result["hashes_stable"] = all(sha256_file(Path(p)) == h for p, h in hashes.items())
        if not result["hashes_stable"]:
            raise ValueError("Experiment code or data changed during evaluation")
        result["status"] = "completed"
        save("completed; no advice published")
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        save("failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
