from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .app_corpus import DEFAULT_BASE as APP_CORPUS_BASE
from .app_corpus import DEFAULT_OUTPUT as APP_CORPUS_OUTPUT
from .app_corpus import (
    QUALITY_BASE,
    QUALITY_OUTPUT,
    TOOL_AWARE_BASE,
    TOOL_AWARE_OUTPUT,
    build_app_corpus,
    build_quality_corpus,
    build_tool_aware_corpus,
)
from .benchmarks import ScreenshotBenchmarkCase, load_screenshot_benchmark, load_text_benchmark
from .contracts import ScreenshotTeamProposal, validate_resolved_team
from .conversation_corpus import DEFAULT_OUTPUT as CONVERSATION_OUTPUT
from .conversation_corpus import build_conversation_corpus
from .correction_corpus import DEFAULT_BASE as CORRECTION_BASE
from .correction_corpus import DEFAULT_OUTPUT as CORRECTION_OUTPUT
from .correction_corpus import build_correction_corpus
from .dataset import build_all
from .evaluation import score_screenshot_extraction
from .paths import BENCHMARKS, ROOT
from .precision_corpus import DEFAULT_BASE as PRECISION_CORPUS_BASE
from .precision_corpus import DEFAULT_OUTPUT as PRECISION_CORPUS_OUTPUT
from .precision_corpus import build_precision_corpus
from .runtime_tools import (
    DEFAULT_COMPONENTS,
    DEFAULT_DECISION,
    DEFAULT_FORECASTS,
    build_default_tool_registry,
)
from .screenshot_corpus import DEFAULT_OUTPUT as CORPUS_OUTPUT
from .screenshot_corpus import render_corpus
from .screenshot_import import load_current_catalog
from .source_policy import load_source_registry
from .synthetic_screenshots import DEFAULT_OUTPUT, render_dataset
from .tool_contracts import openai_tools


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="fplagent-llm")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("contracts")
    validate = commands.add_parser("validate-benchmarks")
    validate.add_argument("--image-root", type=Path)
    validate.add_argument(
        "--database", type=Path, default=ROOT / "data" / "fpl_history.duckdb"
    )
    commands.add_parser("build-data")
    commands.add_parser("source-policy")
    render = commands.add_parser("render-screenshots")
    render.add_argument(
        "--database", type=Path, default=ROOT / "data" / "fpl_history.duckdb"
    )
    render.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    render.add_argument("--squads", type=int, default=8)
    render.add_argument("--seed", type=int, default=20_260_804)
    corpus = commands.add_parser("render-screenshot-corpus")
    corpus.add_argument(
        "--database", type=Path, default=ROOT / "data" / "fpl_history.duckdb"
    )
    corpus.add_argument("--output", type=Path, default=CORPUS_OUTPUT)
    corpus.add_argument("--squads", type=int, default=240)
    corpus.add_argument("--seed", type=int, default=20_260_811)
    conversations = commands.add_parser("build-conversation-corpus")
    conversations.add_argument(
        "--database", type=Path, default=ROOT / "data" / "fpl_history.duckdb"
    )
    conversations.add_argument("--output", type=Path, default=CONVERSATION_OUTPUT)
    conversations.add_argument("--seed", type=int, default=20_260_812)
    corrections = commands.add_parser("build-correction-corpus")
    corrections.add_argument("--base", type=Path, default=CORRECTION_BASE)
    corrections.add_argument("--output", type=Path, default=CORRECTION_OUTPUT)
    corrections.add_argument("--seed", type=int, default=20_260_804)
    app_corpus = commands.add_parser("build-app-corpus")
    app_corpus.add_argument("--base", type=Path, default=APP_CORPUS_BASE)
    app_corpus.add_argument("--output", type=Path, default=APP_CORPUS_OUTPUT)
    app_corpus.add_argument("--seed", type=int, default=20_260_806)
    tool_aware_corpus = commands.add_parser("build-tool-aware-corpus")
    tool_aware_corpus.add_argument("--base", type=Path, default=TOOL_AWARE_BASE)
    tool_aware_corpus.add_argument("--output", type=Path, default=TOOL_AWARE_OUTPUT)
    tool_aware_corpus.add_argument("--seed", type=int, default=20_260_807)
    quality_corpus = commands.add_parser("build-quality-corpus")
    quality_corpus.add_argument("--base", type=Path, default=QUALITY_BASE)
    quality_corpus.add_argument("--output", type=Path, default=QUALITY_OUTPUT)
    quality_corpus.add_argument("--seed", type=int, default=20_260_808)
    precision_corpus = commands.add_parser("build-precision-corpus")
    precision_corpus.add_argument("--base", type=Path, default=PRECISION_CORPUS_BASE)
    precision_corpus.add_argument(
        "--output", type=Path, default=PRECISION_CORPUS_OUTPUT
    )
    precision_corpus.add_argument("--seed", type=int, default=20_260_809)
    score = commands.add_parser("score-screenshot")
    score.add_argument("--extraction", type=Path, required=True)
    score.add_argument("--case-id", required=True)
    score.add_argument(
        "--database", type=Path, default=ROOT / "data" / "fpl_history.duckdb"
    )
    synthetic_score = commands.add_parser("score-synthetic-screenshot")
    synthetic_score.add_argument("--extraction", type=Path, required=True)
    synthetic_score.add_argument("--truth", type=Path, required=True)
    synthetic_score.add_argument(
        "--database", type=Path, default=ROOT / "data" / "fpl_history.duckdb"
    )
    estimate = commands.add_parser("estimate-training")
    estimate.add_argument("--planned-tokens", type=int, required=True)
    estimate.add_argument("--calibration-tokens", type=int, required=True)
    estimate.add_argument("--calibration-seconds", type=float, required=True)
    estimate.add_argument("--overhead", type=float, default=1.15)
    runtime = commands.add_parser(
        "runtime-tools", description="Execute the local manager and captain tools without an LLM"
    )
    runtime.add_argument("--manager-id", type=int, default=1)
    runtime.add_argument("--event", type=int, default=1)
    runtime.add_argument(
        "--risk-policy",
        choices=("expected_points", "robust", "mini_league"),
        default="robust",
    )
    runtime.add_argument("--candidate-player-id", type=int, action="append", default=[])
    runtime.add_argument("--as-of")
    runtime.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    runtime.add_argument("--forecasts", type=Path, default=DEFAULT_FORECASTS)
    runtime.add_argument("--components", type=Path, default=DEFAULT_COMPONENTS)
    return root


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _validate_benchmarks(image_root: Path | None, database: Path) -> dict:
    text_cases = load_text_benchmark(BENCHMARKS / "fplbench_v1.jsonl")
    screenshot_cases = load_screenshot_benchmark(
        BENCHMARKS / "screenshotbench_v1.jsonl"
    )
    catalog_rows = load_current_catalog(database)
    catalog = {player.player_id: player for player in catalog_rows}
    screenshot_results = []
    for case in screenshot_cases:
        validation = validate_resolved_team(case.expected, catalog)
        image_status = None
        if image_root is not None:
            image_status = case.verify_image(image_root)
        screenshot_results.append(
            {
                "case_id": case.case_id,
                "team_valid": validation.valid,
                "issues": validation.issues,
                "formation": validation.inferred_formation,
                "image_status": image_status,
            }
        )
    return {
        "text_cases": len(text_cases),
        "text_categories": dict(sorted(Counter(case.category for case in text_cases).items())),
        "screenshot_cases": len(screenshot_cases),
        "screenshots": screenshot_results,
    }


def _estimate(
    planned_tokens: int,
    calibration_tokens: int,
    calibration_seconds: float,
    overhead: float,
) -> dict:
    if min(planned_tokens, calibration_tokens) <= 0 or calibration_seconds <= 0:
        raise ValueError("token counts and calibration time must be positive")
    if overhead < 1.0:
        raise ValueError("overhead must be at least one")
    tokens_per_second = calibration_tokens / calibration_seconds
    projected_seconds = planned_tokens / tokens_per_second * overhead
    return {
        "tokens_per_second": tokens_per_second,
        "planned_tokens": planned_tokens,
        "overhead_multiplier": overhead,
        "projected_seconds": projected_seconds,
        "projected_hours": projected_seconds / 3600.0,
    }


def main() -> None:
    args = parser().parse_args()
    if args.command == "contracts":
        _print(openai_tools())
    elif args.command == "validate-benchmarks":
        _print(_validate_benchmarks(args.image_root, args.database))
    elif args.command == "build-data":
        _print(build_all())
    elif args.command == "source-policy":
        _print(load_source_registry().summary())
    elif args.command == "render-screenshots":
        _print(
            render_dataset(
                database_path=args.database,
                output_dir=args.output,
                squad_count=args.squads,
                seed=args.seed,
            )
        )
    elif args.command == "render-screenshot-corpus":
        _print(
            render_corpus(
                database_path=args.database,
                output_dir=args.output,
                squad_count=args.squads,
                seed=args.seed,
            )
        )
    elif args.command == "build-conversation-corpus":
        _print(
            build_conversation_corpus(
                database_path=args.database,
                output_dir=args.output,
                seed=args.seed,
            )
        )
    elif args.command == "build-correction-corpus":
        _print(
            build_correction_corpus(
                base_path=args.base,
                output_dir=args.output,
                seed=args.seed,
            )
        )
    elif args.command == "build-app-corpus":
        _print(
            build_app_corpus(
                base_path=args.base,
                output_dir=args.output,
                seed=args.seed,
            )
        )
    elif args.command == "build-tool-aware-corpus":
        _print(
            build_tool_aware_corpus(
                base_path=args.base,
                output_dir=args.output,
                seed=args.seed,
            )
        )
    elif args.command == "build-quality-corpus":
        _print(
            build_quality_corpus(
                base_path=args.base,
                output_dir=args.output,
                seed=args.seed,
            )
        )
    elif args.command == "build-precision-corpus":
        _print(
            build_precision_corpus(
                base_path=args.base,
                output_dir=args.output,
                seed=args.seed,
            )
        )
    elif args.command == "score-screenshot":
        cases = load_screenshot_benchmark(BENCHMARKS / "screenshotbench_v1.jsonl")
        case_by_id = {case.case_id: case for case in cases}
        if args.case_id not in case_by_id:
            raise ValueError(f"unknown screenshot benchmark case: {args.case_id}")
        payload = json.loads(args.extraction.read_text(encoding="utf-8"))
        extraction = payload.get("extraction", payload)
        if not isinstance(extraction, dict):
            raise TypeError("extraction payload must be a JSON object")
        _print(
            score_screenshot_extraction(
                extraction,
                case_by_id[args.case_id],
                load_current_catalog(args.database),
            )
        )
    elif args.command == "score-synthetic-screenshot":
        payload = json.loads(args.extraction.read_text(encoding="utf-8"))
        extraction = payload.get("extraction", payload)
        if not isinstance(extraction, dict):
            raise TypeError("extraction payload must be a JSON object")
        truth = json.loads(args.truth.read_text(encoding="utf-8"))
        expected = ScreenshotTeamProposal.from_dict(truth["resolved_proposal"])
        benchmark = ScreenshotBenchmarkCase(
            case_id=str(truth["case_id"]),
            image_filename="synthetic.png",
            image_sha256="0" * 64,
            width=1,
            height=1,
            expected=expected,
            notes="Generated synthetic screenshot truth.",
        )
        _print(
            score_screenshot_extraction(
                extraction,
                benchmark,
                load_current_catalog(args.database),
            )
        )
    elif args.command == "estimate-training":
        _print(
            _estimate(
                args.planned_tokens,
                args.calibration_tokens,
                args.calibration_seconds,
                args.overhead,
            )
        )
    elif args.command == "runtime-tools":
        as_of = args.as_of or datetime.now(tz=UTC).isoformat()
        registry = build_default_tool_registry(
            decision_path=args.decision,
            forecast_path=args.forecasts,
            component_path=args.components,
            manager_id=args.manager_id,
        )
        state = registry.execute(
            "get_manager_state", {"manager_id": args.manager_id, "as_of": as_of}
        )
        captains = registry.execute(
            "compare_captains",
            {
                "manager_id": args.manager_id,
                "event": args.event,
                "candidate_player_ids": args.candidate_player_id,
                "risk_policy": args.risk_policy,
                "as_of": as_of,
            },
        )
        _print({"manager_state": state.model_payload(), "captain_comparison": captains.model_payload()})
