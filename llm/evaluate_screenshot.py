from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

EXTRACTION_INSTRUCTION = """Extract this FPL team screenshot into JSON only.
Use exactly this object shape:
{
  "season": string | null,
  "event": integer | null,
  "deadline": string | null,
  "formation": string | null,
  "players": [{"source_text": string, "position": "GK"|"DEF"|"MID"|"FWD", "squad_role": "starter"|"bench", "order": integer, "is_captain": boolean, "is_vice_captain": boolean}],
  "chips": {"bench_boost": string | null, "triple_captain": string | null, "wildcard": string | null, "free_hit": string | null},
  "unresolved": [string]
}
Do not infer a player or state hidden outside the image. Use null when season, event, deadline or a chip state is not visible. Preserve truncated visible names. Number starters 1-11 and bench players 1-4 within their own role. Derive formation by counting the positions of the 11 starters: five DEF, three MID and two FWD is 5-3-2. Do not infer formation from row width or spacing. The import is provisional and must not include invented player IDs."""


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Run a VLM-only screenshot extraction baseline")
    root.add_argument("--image", type=Path, required=True)
    root.add_argument("--model", default="unsloth/Qwen3.5-4B")
    root.add_argument("--adapter", type=Path)
    root.add_argument("--max-new-tokens", type=int, default=2048)
    root.add_argument("--output", type=Path)
    return root


def _extract_json(text: str) -> dict:
    without_thinking = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    decoder = json.JSONDecoder()
    for index, character in enumerate(without_thinking):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(without_thinking[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model output did not contain a JSON object")


def main() -> None:
    args = parser().parse_args()
    import unsloth  # noqa: F401 - must patch Transformers before later imports
    from PIL import Image
    from unsloth import FastVisionModel

    model, processor = FastVisionModel.from_pretrained(
        args.model,
        load_in_4bit=False,
        use_gradient_checkpointing=False,
    )
    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.adapter)
    FastVisionModel.for_inference(model)
    tokenizer = getattr(processor, "tokenizer", processor)
    end_of_turn_token_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if not isinstance(end_of_turn_token_id, int) or end_of_turn_token_id < 0:
        raise RuntimeError("Qwen tokenizer does not expose an <|im_end|> token ID")
    image = Image.open(args.image).convert("RGB")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": EXTRACTION_INSTRUCTION},
            ],
        }
    ]
    text = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = processor(
        image,
        text,
        add_special_tokens=False,
        return_tensors="pt",
    ).to("cuda")
    output = model.generate(
        **inputs,
        max_new_tokens=args.max_new_tokens,
        do_sample=False,
        use_cache=True,
        eos_token_id=end_of_turn_token_id,
    )
    generated = processor.decode(
        output[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True
    )
    try:
        extraction = _extract_json(generated)
        parse_error = None
    except ValueError as exc:
        extraction = None
        parse_error = str(exc)
    result = {
        "image_path": str(args.image),
        "image_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        "model": args.model,
        "adapter": str(args.adapter) if args.adapter else None,
        "raw_output": generated,
        "extraction": extraction,
        "parse_valid": parse_error is None,
        "parse_error": parse_error,
    }
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
