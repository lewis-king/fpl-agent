from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from fplagent_llm.benchmarks import (
    ScreenshotBenchmarkCase,
    load_screenshot_benchmark,
)
from fplagent_llm.contracts import ScreenshotTeamProposal
from fplagent_llm.evaluation import score_screenshot_extraction
from fplagent_llm.screenshot_import import load_current_catalog
from llm.evaluate_screenshot import EXTRACTION_INSTRUCTION, _extract_json

DEFAULT_CORPUS = ROOT / "data/llm/generated/screenshot_corpus_v2"
DEFAULT_BENCHMARK = ROOT / "config/llm/benchmarks/screenshotbench_v1.jsonl"
DEFAULT_DATABASE = ROOT / "data/fpl_history.duckdb"

# This set is deliberately small enough to rerun before every promotion, but broad enough to
# cover every legal FPL formation, mobile/desktop, pitch/list and three degradation modes. None of
# these image IDs is present in the training or validation split.
LOCKED_SYNTHETIC_CASE_IDS = (
    "corpus-v2-squad-0217-mobile-pitch-broadcast",
    "corpus-v2-squad-0218-desktop-pitch-broadcast-crop",
    "corpus-v2-squad-0219-mobile-list-paper",
    "corpus-v2-squad-0220-mobile-pitch-broadcast-photo",
    "corpus-v2-squad-0221-mobile-pitch-broadcast",
    "corpus-v2-squad-0222-desktop-pitch-broadcast-crop",
    "corpus-v2-squad-0223-mobile-list-paper",
    "corpus-v2-squad-0224-mobile-pitch-broadcast-photo",
    "corpus-v2-squad-0225-desktop-list-paper-partial",
    "corpus-v2-squad-0229-desktop-list-paper-partial",
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Evaluate one Qwen model load on real and held-out FPL screenshots"
    )
    root.add_argument("--model", default="unsloth/Qwen3.5-4B")
    root.add_argument("--adapter", type=Path)
    root.add_argument(
        "--local-files-only",
        action="store_true",
        help="Load the already-cached model without network or token validation.",
    )
    root.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    root.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    root.add_argument("--real-image-root", type=Path, default=Path("/home/lewis/Downloads"))
    root.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    root.add_argument("--max-new-tokens", type=int, default=2048)
    root.add_argument("--skip-real", action="store_true")
    root.add_argument("--case-id", action="append", default=[])
    root.add_argument("--output", type=Path)
    return root


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError(f"{path} must contain JSON objects")
                rows.append(value)
    return rows


def _synthetic_case(corpus: Path, case_id: str) -> tuple[Path, ScreenshotBenchmarkCase, bool]:
    truth_path = corpus / "truth" / f"{case_id}.json"
    image_path = corpus / "images" / f"{case_id}.png"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    expected = ScreenshotTeamProposal.from_dict(truth["resolved_proposal"])
    from PIL import Image

    with Image.open(image_path) as image:
        width, height = image.size
    benchmark = ScreenshotBenchmarkCase(
        case_id=case_id,
        image_filename=image_path.name,
        image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
        width=width,
        height=height,
        expected=expected,
        notes="Locked held-out synthetic screenshot.",
    )
    return image_path, benchmark, bool(truth["expected_valid"])


def _verify_synthetic_split(corpus: Path, case_ids: tuple[str, ...]) -> None:
    rows = {str(row["id"]): row for row in _read_jsonl(corpus / "sft_test.jsonl")}
    missing = set(case_ids) - set(rows)
    if missing:
        raise ValueError(f"synthetic cases are absent from the held-out test split: {sorted(missing)}")
    leaked = [case_id for case_id in case_ids if rows[case_id]["metadata"].get("split") != "test"]
    if leaked:
        raise ValueError(f"synthetic cases are not held out: {leaked}")


def _run_extraction(
    *,
    model: Any,
    processor: Any,
    image_path: Path,
    max_new_tokens: int,
    eos_token_id: int,
) -> dict[str, Any]:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": EXTRACTION_INSTRUCTION},
            ],
        }
    ]
    rendered = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = processor(
        image,
        rendered,
        add_special_tokens=False,
        return_tensors="pt",
    ).to("cuda")
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            use_cache=True,
            eos_token_id=eos_token_id,
        )
    raw = processor.decode(
        output[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True
    ).strip()
    try:
        extraction = _extract_json(raw)
        parse_error = None
    except ValueError as exc:
        extraction = None
        parse_error = str(exc)
    return {
        "raw_output": re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip(),
        "extraction": extraction,
        "parse_valid": parse_error is None,
        "parse_error": parse_error,
    }


def _synthetic_pass(score: dict[str, Any], *, expected_valid: bool) -> bool:
    if expected_valid:
        return all(
            bool(score.get(field))
            for field in ("core_team_exact", "team_valid", "chips_exact")
        )
    # A partially hidden squad must preserve every visible slot and explicitly remain invalid.
    # This catches the dangerous failure mode where a VLM silently invents the obscured player.
    return (
        bool(score.get("core_team_exact"))
        and not bool(score.get("team_valid"))
        and bool(score.get("chips_exact"))
        and bool(score.get("unresolved"))
    )


def main() -> None:
    args = parser().parse_args()
    selected = tuple(args.case_id) if args.case_id else LOCKED_SYNTHETIC_CASE_IDS
    _verify_synthetic_split(args.corpus, selected)

    import unsloth  # noqa: F401 - patches Transformers before later imports
    from peft import PeftModel
    from unsloth import FastVisionModel

    load_options: dict[str, Any] = {
        "load_in_4bit": False,
        "use_gradient_checkpointing": False,
    }
    if args.local_files_only:
        load_options.update(local_files_only=True, token=False)
    model, processor = FastVisionModel.from_pretrained(args.model, **load_options)
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    FastVisionModel.for_inference(model)
    tokenizer = getattr(processor, "tokenizer", processor)
    eos_token_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if not isinstance(eos_token_id, int) or eos_token_id < 0:
        raise RuntimeError("Qwen tokenizer does not expose an <|im_end|> token ID")
    catalog = load_current_catalog(args.database)

    real_results: list[dict[str, Any]] = []
    if not args.skip_real:
        for benchmark in load_screenshot_benchmark(args.benchmark):
            image_path = args.real_image_root / benchmark.image_filename
            if not image_path.exists():
                raise FileNotFoundError(image_path)
            run = _run_extraction(
                model=model,
                processor=processor,
                image_path=image_path,
                max_new_tokens=args.max_new_tokens,
                eos_token_id=eos_token_id,
            )
            score = (
                score_screenshot_extraction(run["extraction"], benchmark, catalog)
                if run["extraction"] is not None
                else {"case_id": benchmark.case_id}
            )
            real_results.append({**score, **run, "image_path": str(image_path)})
            print(
                f"{benchmark.case_id}: parse={run['parse_valid']} "
                f"core={score.get('core_team_exact', False)} "
                f"valid={score.get('team_valid', False)} chips={score.get('chips_exact', False)}",
                flush=True,
            )

    synthetic_results: list[dict[str, Any]] = []
    for case_id in selected:
        image_path, benchmark, expected_valid = _synthetic_case(args.corpus, case_id)
        run = _run_extraction(
            model=model,
            processor=processor,
            image_path=image_path,
            max_new_tokens=args.max_new_tokens,
            eos_token_id=eos_token_id,
        )
        score = (
            score_screenshot_extraction(run["extraction"], benchmark, catalog)
            if run["extraction"] is not None
            else {"case_id": case_id}
        )
        passed = run["parse_valid"] and _synthetic_pass(score, expected_valid=expected_valid)
        synthetic_results.append(
            {
                **score,
                **run,
                "image_path": str(image_path),
                "expected_valid": expected_valid,
                "case_pass": passed,
            }
        )
        print(
            f"{case_id}: expected_valid={expected_valid} parse={run['parse_valid']} "
            f"core={score.get('core_team_exact', False)} "
            f"safe={passed}",
            flush=True,
        )

    valid_rows = [row for row in synthetic_results if row["expected_valid"]]
    invalid_rows = [row for row in synthetic_results if not row["expected_valid"]]
    summary = {
        "cases": len(synthetic_results),
        "valid_cases": len(valid_rows),
        "invalid_cases": len(invalid_rows),
        "case_passes": sum(bool(row["case_pass"]) for row in synthetic_results),
        "valid_exact": sum(bool(row["case_pass"]) for row in valid_rows),
        "invalid_safe_rejections": sum(bool(row["case_pass"]) for row in invalid_rows),
        "formations": sorted(
            {
                str(row.get("raw_extracted_formation"))
                for row in valid_rows
                if row.get("raw_extracted_formation")
            }
        ),
    }
    payload = {
        "evaluator_version": "fpl-screenshot-suite-v1",
        "evaluated_at": datetime.now(tz=UTC).isoformat(),
        "model": args.model,
        "adapter": str(args.adapter) if args.adapter else None,
        "corpus_test_sha256": hashlib.sha256(
            (args.corpus / "sft_test.jsonl").read_bytes()
        ).hexdigest(),
        "locked_case_ids": list(selected),
        "summary": summary,
        "passed": summary["case_passes"] == summary["cases"],
        "real_results": real_results,
        "results": synthetic_results,
    }
    rendered_payload = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered_payload, encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
