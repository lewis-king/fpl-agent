"""Deep current-week audit on hash-checked inputs; never publishes or writes FPL."""

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_engine.component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    GOAL_METRICS_FILE,
    GOAL_MODEL_FILE,
)
from fplagent_engine.deadline_pipeline import weekly_pipeline_implementation_sha256
from fplagent_engine.market_odds import CURRENT_MARKET_RATES, CURRENT_MARKET_RECEIPT
from fplagent_engine.rules import POSITIONS_PATH, RULES_PATH, load_rules
from fplagent_engine.tournament import (
    BACKTEST_FORECAST,
    CURRENT_FIXTURES,
    HISTORICAL_FIXTURES,
    PLAYER_GAMEWEEKS,
    TRAINING_FEATURES,
)
from fplagent_engine.transfer_value import load_terminal_free_transfer_curve
from fplagent_engine.weekly_decision import (
    load_weekly_manager_state,
    require_weekly_forecast_lineage,
)
from fplagent_engine.weekly_deep_search import run_deep_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt", type=Path, default=Path("data/decisions/2026-27-weekly-current.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose a fresh research receipt; preserve previous results")
    receipt = json.loads(args.receipt.read_text())
    sources = receipt["source_artifacts"]
    forecast, components = Path(sources["forecast"]), Path(sources["component_forecast"])
    for name in ("forecast", "component_forecast", "manager_state_contract"):
        if sha256_file(Path(sources[name])) != sources[name + "_sha256"]:
            raise ValueError(f"{name} no longer matches the active receipt; refresh first")
    events = tuple(int(l["event"]) for l in receipt["action_summaries"][0]["event_lineups"])
    require_weekly_forecast_lineage(
        forecast,
        components,
        events=events,
        component_model_path=Path(sources["component_event_model"]),
    )
    paths = {
        str(Path(v))
        for k, v in sources.items()
        if isinstance(v, str) and not k.endswith("sha256") and len(v) < 250 and Path(v).is_file()
    }
    paths.update(
        map(
            str,
            (
                GOAL_MODEL_FILE,
                GOAL_METRICS_FILE,
                COMPONENT_BACKTEST_METRICS,
                CURRENT_MARKET_RATES,
                CURRENT_MARKET_RECEIPT,
                BACKTEST_FORECAST,
                TRAINING_FEATURES,
                PLAYER_GAMEWEEKS,
                HISTORICAL_FIXTURES,
                CURRENT_FIXTURES,
                RULES_PATH,
                POSITIONS_PATH,
            ),
        )
    )
    hashes = {p: sha256_file(Path(p)) for p in sorted(paths) if Path(p).is_file()}
    code_sha = weekly_pipeline_implementation_sha256()
    source_sha = sha256_file(args.receipt)
    rules = load_rules()
    rows = pq.read_table(forecast).to_pylist()
    state, _ = load_weekly_manager_state(
        Path(sources["manager_state_contract"]),
        forecast_path=forecast,
        event=events[0],
        rules=rules,
        forecast_rows=rows,
    )
    curve, _ = load_terminal_free_transfer_curve(maximum=rules.max_free_transfers, rules=rules)
    try:
        result, _, _, _ = run_deep_search(
            state,
            rows,
            rules,
            events,
            curve,
            incumbent_id=receipt["selected_action_id"],
            component_forecast_path=components,
            progress=lambda message: print(message, flush=True),
            output=args.output,
        )
    except (Exception, KeyboardInterrupt) as error:
        result = json.loads(args.output.read_text()) if args.output.exists() else {}
        result.update(
            status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            error=str(error) or type(error).__name__,
            promotion_ready=False,
            decision="retain_incumbent",
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
        raise
    stable = all(
        Path(p).is_file() and sha256_file(Path(p)) == digest for p, digest in hashes.items()
    )
    stable = stable and code_sha == weekly_pipeline_implementation_sha256()
    stable = stable and args.receipt.is_file() and source_sha == sha256_file(args.receipt)
    result["input_lineage"] = {
        "source_receipt": str(args.receipt),
        "source_sha256": source_sha,
        "artifacts": hashes,
        "implementation_sha256": code_sha,
        "unchanged_through_audit": stable,
    }
    if not stable:
        result.update(status="input_changed", promotion_ready=False, decision="retain_incumbent")
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {k: result[k] for k in ("status", "decision", "promotion_ready", "elapsed_seconds")}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
