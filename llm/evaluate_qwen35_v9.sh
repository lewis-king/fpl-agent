#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
python="$repository_root/llm/.venv/bin/python"
adapter="$repository_root/llm/outputs/qwen35-4b-fpl-lora-v9/adapter"
evaluation_dir="$repository_root/llm/evaluations/qwen35-4b-fpl-lora-v9"

if [[ ! -f "$adapter/adapter_model.safetensors" ]]; then
  printf 'V9 adapter is incomplete: %s\n' "$adapter" >&2
  exit 1
fi

cd "$repository_root"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

"$python" llm/evaluate_text.py \
  --local-files-only \
  --profile app \
  --benchmarks config/llm/benchmarks/appchatbench_v1.jsonl \
  --output "$evaluation_dir/base-app.json"

"$python" llm/evaluate_text.py \
  --local-files-only \
  --adapter "$adapter" \
  --profile app \
  --benchmarks config/llm/benchmarks/appchatbench_v1.jsonl \
  --output "$evaluation_dir/candidate-app.json"

"$python" llm/evaluate_text.py \
  --local-files-only \
  --adapter "$adapter" \
  --profile legacy \
  --benchmarks config/llm/benchmarks/fplbench_v1.jsonl \
  --output "$evaluation_dir/candidate-legacy.json"

"$python" llm/evaluate_screenshot_suite.py \
  --local-files-only \
  --real-image-root /home/lewis/Downloads \
  --output "$evaluation_dir/base-screenshots.json"

"$python" llm/evaluate_screenshot_suite.py \
  --local-files-only \
  --adapter "$adapter" \
  --real-image-root /home/lewis/Downloads \
  --output "$evaluation_dir/candidate-screenshots.json"

"$python" llm/prepare_qualitative_ab.py \
  --base "$evaluation_dir/base-app.json" \
  --candidate "$evaluation_dir/candidate-app.json" \
  --output "$evaluation_dir/qualitative-blind-review.json" \
  --key-output "$evaluation_dir/qualitative-blind-key.json"

printf '\nAutomatic evaluation complete. Score this file without opening the key:\n%s\n' \
  "$evaluation_dir/qualitative-blind-review.json"
