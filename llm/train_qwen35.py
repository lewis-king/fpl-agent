from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Time-boxed FPLAgent Qwen3.5 LoRA training")
    root.add_argument(
        "--config", type=Path, default=Path("llm/configs/qwen35_4b_lora.json")
    )
    root.add_argument(
        "--train-data", type=Path, default=Path("data/llm/generated/fpl_sft_seed_v1.jsonl")
    )
    root.add_argument("--image-root", type=Path)
    root.add_argument("--max-steps", type=int)
    root.add_argument("--max-wall-minutes", type=float)
    root.add_argument("--allow-seed-data", action="store_true")
    root.add_argument("--dry-run", action="store_true")
    return root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_rows(path: Path, image_root: Path | None) -> list[dict[str, Any]]:
    from PIL import Image

    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            split = value.get("metadata", {}).get("split", "train")
            if split != "train":
                raise ValueError(
                    f"{path}:{line_number}: refusing to train on split {split!r}"
                )
            messages = value.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                raise ValueError(f"{path}:{line_number}: invalid messages")
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if part.get("type") != "image" or "image" in part:
                        continue
                    relative = part.get("path")
                    if not relative or image_root is None:
                        raise ValueError(
                            f"{path}:{line_number}: image row requires --image-root"
                        )
                    image_path = image_root / relative
                    part["image"] = Image.open(image_path).convert("RGB")
            rows.append({"messages": messages})
    return rows


def _gpu() -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; no CPU training fallback is permitted")
    properties = torch.cuda.get_device_properties(0)
    major, minor = torch.cuda.get_device_capability(0)
    return {
        "name": properties.name,
        "total_memory_bytes": properties.total_memory,
        "compute_capability": f"{major}.{minor}",
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "bf16": torch.cuda.is_bf16_supported(),
    }


def main() -> None:
    from fplagent_llm.training_context import build_app_training_formatter

    args = parser().parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    rows = _load_rows(args.train_data, args.image_root)
    minimum = int(config["minimum_training_rows"])
    if len(rows) < minimum and not args.allow_seed_data:
        raise RuntimeError(
            f"training corpus has only {len(rows)} rows; at least {minimum} are required. "
            "Pass --allow-seed-data only for a smoke/timing run."
        )
    gpu = _gpu()
    if not gpu["bf16"]:
        raise RuntimeError("Qwen3.5 BF16 LoRA requires a BF16-capable CUDA GPU")

    preflight = {
        "config": config,
        "config_sha256": _sha256(args.config),
        "train_data": str(args.train_data),
        "train_data_sha256": _sha256(args.train_data),
        "rows": len(rows),
        "gpu": gpu,
    }
    print(json.dumps(preflight, indent=2, sort_keys=True))
    if args.dry_run:
        return

    import torch
    import unsloth  # noqa: F401 - must patch Transformers before later imports
    from transformers import TrainerCallback
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastVisionModel
    from unsloth.trainer import UnslothVisionDataCollator

    class WallClockCallback(TrainerCallback):
        def __init__(self, seconds: float) -> None:
            self.deadline = time.monotonic() + seconds

        def on_step_end(self, args, state, control, **kwargs):
            if time.monotonic() >= self.deadline:
                control.should_training_stop = True
                control.should_save = True
            return control

    started_at = datetime.now(tz=UTC)
    model, processor = FastVisionModel.from_pretrained(
        config["model_name"],
        load_in_4bit=bool(config["load_in_4bit"]),
        use_gradient_checkpointing="unsloth",
        revision=config.get("model_revision", "main"),
    )
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=bool(config["finetune_vision_layers"]),
        finetune_language_layers=bool(config["finetune_language_layers"]),
        finetune_attention_modules=bool(config["finetune_attention_modules"]),
        finetune_mlp_modules=bool(config["finetune_mlp_modules"]),
        r=int(config["lora_rank"]),
        lora_alpha=int(config["lora_alpha"]),
        lora_dropout=float(config["lora_dropout"]),
        bias="none",
        random_state=int(config["seed"]),
        use_rslora=False,
        loftq_config=None,
    )
    FastVisionModel.for_training(model)

    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    max_wall_minutes = float(
        args.max_wall_minutes
        if args.max_wall_minutes is not None
        else config["max_wall_minutes"]
    )
    training_args = SFTConfig(
        per_device_train_batch_size=int(config["per_device_train_batch_size"]),
        gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
        warmup_ratio=float(config["warmup_ratio"]),
        max_steps=args.max_steps if args.max_steps is not None else -1,
        num_train_epochs=float(config["num_train_epochs"]),
        learning_rate=float(config["learning_rate"]),
        logging_steps=int(config["logging_steps"]),
        save_steps=int(config["save_steps"]),
        optim="adamw_8bit",
        weight_decay=float(config["weight_decay"]),
        lr_scheduler_type=config["lr_scheduler_type"],
        seed=int(config["seed"]),
        output_dir=str(output_dir),
        report_to="none",
        bf16=True,
        fp16=False,
        remove_unused_columns=False,
        dataset_text_field="",
        dataset_kwargs={"skip_prepare_dataset": True},
        max_length=int(config["max_length"]),
    )
    data_collator = UnslothVisionDataCollator(
        model,
        processor,
        formatting_func=(
            build_app_training_formatter(processor)
            if bool(config.get("include_app_tools_in_training", False))
            else None
        ),
        max_seq_length=int(config["max_length"]),
        train_on_responses_only=bool(config.get("train_on_responses_only", True)),
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=processor,
        data_collator=data_collator,
        train_dataset=rows,
        args=training_args,
        callbacks=[WallClockCallback(max_wall_minutes * 60.0)],
    )
    result = trainer.train()
    adapter_dir = output_dir / "adapter"
    model.save_pretrained(adapter_dir)
    processor.save_pretrained(adapter_dir)
    completed_at = datetime.now(tz=UTC)
    manifest = {
        **preflight,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_seconds": (completed_at - started_at).total_seconds(),
        "max_wall_minutes": max_wall_minutes,
        "global_step": trainer.state.global_step,
        "train_on_responses_only": bool(config.get("train_on_responses_only", True)),
        "train_metrics": result.metrics,
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "adapter_dir": str(adapter_dir),
    }
    (output_dir / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
