"""Paired chronological refit of the availability input; no live weights are changed.

Same XGBoost hyperparameters/seeds/early-stopping folds in both arms. Only dated
next-round availability replaces this-round metadata. Three full seasons, fixed
before evaluation. Research artifacts are never loaded by normal forecasts.
"""

import argparse
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_engine.features import TRAINING_FEATURES
from fplagent_engine.forecast_diagnosis import historical_next_chance
from fplagent_engine.market_transfer_replay import moving_block_mean_interval, run_policy_season
from fplagent_engine.models import (
    _atomic_json,
    _backtest,
    _matrix,
    _numeric,
    _strings,
    require_cuda,
)
from fplagent_engine.rules import load_rules


def run(output):
    if output.exists():
        raise FileExistsError("Keep prior research receipts")
    snapshots = Path("data/processed/vaastav_deadlines/player_snapshots.parquet")
    files = [
        TRAINING_FEATURES,
        snapshots,
        Path(__file__),
        *Path("src/fplagent_engine").glob("*.py"),
    ]
    hashes = {str(p): sha256_file(p) for p in files}
    start = time.monotonic()
    result = {
        "version": "availability_refit_v1",
        "status": "running",
        "decision_authority": False,
        "source_hashes": hashes,
        "arms": {},
        "definition": {
            "arms": ["recreated_incumbent", "next_round_refit"],
            "test_seasons": ["2023-24", "2024-25", "2025-26"],
            "training": "For each test season: train on seasons earlier than the immediately preceding validation season; identical early stopping and seeds. No current-season outcomes.",
            "change": "Replace only explicitly observed next-round availability on dated snapshots <=7days before target deadline. Missing coverage retains incumbent features. No hard-zero gate in this refit ablation.",
            "selection": "No blend or parameter search. Paired complete-season legal one-event transfer replay; identical zero terminal FT value; no chips.",
            "promotion_screen": "Pooled net points positive, aggregate MAE/RMSE improved, and positive lower95% four-event-block mean delta in each held-out season. This is a cautious release screen, not a claim rejected models are worthless.",
        },
        "limitations": [
            "Development seasons have been examined before; not an untouched SOTA test.",
            "Archive availability field rollover is inferred from next future fixture deadline; exact API event flags were not archived.",
            "Missing dated snapshots and lagged price/fixture data limit production equivalence. No fresh historical Scout data invented.",
            "This isolates a training-input correction, not new role features or an LLM/minutes architecture overhaul.",
        ],
    }

    def save(stage):
        result["stage"] = stage
        result["elapsed_seconds"] = time.monotonic() - start
        _atomic_json(output, result)
        print(stage, flush=True)

    save("registered paired refit")
    try:
        result["gpu"] = require_cuda()
        table = pq.read_table(TRAINING_FEATURES)
        keys = [
            (r["season"], int(r["event_number"]), int(r["element"]))
            for r in table.select(["season", "event_number", "element"]).to_pylist()
        ]
        availability = _numeric(table, "availability_chance").copy()
        observed = {}
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
            observed[(r["season"], int(r["decision_event"]), int(r["id"]))] = (
                historical_next_chance(r)
            )
        changed = 0
        for i, key in enumerate(keys):
            chance = observed.get(key)
            if chance is not None:
                changed += int(chance != availability[i])
                availability[i] = chance
        fixed = table.set_column(
            table.schema.get_field_index("availability_chance"),
            "availability_chance",
            pa.array(availability),
        )
        result["changed_feature_rows"] = changed
        metadata = table.select(
            [
                "season",
                "event_number",
                "element",
                "player_name",
                "position",
                "team_id",
                "market_price",
                "target_points",
                "target_minutes",
            ]
        ).to_pylist()
        rules = load_rules()
        for name, features in [("recreated_incumbent", table), ("next_round_refit", fixed)]:
            save(f"{name}: training12time-forward position folds on RTX5090")
            metrics, predictions = _backtest(
                _matrix(features),
                _strings(features, "season"),
                _strings(features, "position"),
                _numeric(features, "event_number").astype(np.int16),
                _numeric(features, "target_points"),
                _numeric(features, "target_minutes"),
                _numeric(features, "minutes_class").astype(np.int32),
                _numeric(features, "form5_points"),
                _numeric(features, "availability_chance"),
            )
            rows = [
                {**metadata[p["row_index"]], **{k: v for k, v in p.items() if k != "row_index"}}
                for p in predictions
            ]
            path = output.with_name(output.stem + "-" + name + ".parquet")
            if path.exists():
                raise FileExistsError(path)
            pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
            result["arms"][name] = {
                "metrics": metrics,
                "forecast_path": str(path),
                "forecast_sha256": sha256_file(path),
                "policies": {},
            }
            grouped = {}
            for r in rows:
                if r.get("market_price") is None:
                    continue
                r = {
                    **r,
                    "market_price": round(float(r["market_price"])),
                    "xp_expected_points": r["expected_points"],
                    "can_select": True,
                    "removed": False,
                }
                grouped.setdefault((r["season"], int(r["event_number"])), []).append(r)
            for season in result["definition"]["test_seasons"]:
                save(f"{name}: {season} full38event legal replay")
                result["arms"][name]["policies"][season] = run_policy_season(
                    season=season,
                    policy="incumbent_xp",
                    grouped=grouped,
                    market_weight=0,
                    rules=rules,
                    terminal_curve={b: 0.0 for b in range(rules.max_free_transfers + 1)},
                )
        old, new = [result["arms"][n] for n in result["definition"]["arms"]]
        differences = {}
        for season in result["definition"]["test_seasons"]:
            delta = [
                a["net_points"] - b["net_points"]
                for a, b in zip(
                    new["policies"][season]["events"],
                    old["policies"][season]["events"],
                    strict=True,
                )
            ]
            differences[season] = dict(total=sum(delta), **moving_block_mean_interval(delta))
        result["paired_net_deltas"] = differences

        def aggregate(arm, key):
            return sum(r[key] * r["rows"] for r in arm["metrics"]) / sum(
                r["rows"] for r in arm["metrics"]
            )

        result["promotion_screen_passed"] = (
            sum(d["total"] for d in differences.values()) > 0
            and all(d["p025"] > 0 for d in differences.values())
            and all(aggregate(new, key) < aggregate(old, key) for key in ["mae", "rmse"])
        )
        result["hashes_stable"] = all(sha256_file(Path(p)) == h for p, h in hashes.items())
        if not result["hashes_stable"]:
            raise ValueError("Source data or code changed during refit")
        result["status"] = "completed"
        save("completed; learned weights remain research-only pending review")
    except Exception as e:
        result["status"] = "failed"
        result["error"] = f"{type(e).__name__}: {e}"
        save("failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
