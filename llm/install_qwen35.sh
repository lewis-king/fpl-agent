#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TRAINING_PYTHON="$SCRIPT_DIR/.venv/bin/python"

uv venv "$SCRIPT_DIR/.venv" --python 3.12
uv pip install --python "$TRAINING_PYTHON" \
  "torch==2.8.0" \
  "triton>=3.3.0" \
  pillow \
  "duckdb>=1.3.0" \
  "highspy>=1.11.0" \
  "pyarrow>=19.0.0" \
  "fastapi>=0.116.0" \
  "uvicorn>=0.35.0" \
  torchvision \
  bitsandbytes \
  "xformers==0.0.32.post2"
uv pip install --python "$TRAINING_PYTHON" \
  "unsloth_zoo[base] @ git+https://github.com/unslothai/unsloth-zoo" \
  "unsloth[base] @ git+https://github.com/unslothai/unsloth"
uv pip install --python "$TRAINING_PYTHON" --no-deps "torchcodec==0.7.0"
uv pip install --python "$TRAINING_PYTHON" --upgrade --no-deps \
  "tokenizers>=0.22.0,<=0.23.0" \
  "trl==0.22.2" \
  unsloth \
  unsloth_zoo
uv pip install --python "$TRAINING_PYTHON" "transformers==5.2.0"
uv pip install --python "$TRAINING_PYTHON" --no-build-isolation \
  flash-linear-attention \
  "causal_conv1d==1.6.0"
uv pip install --python "$TRAINING_PYTHON" --no-deps \
  "apache-tvm-ffi==0.1.9" \
  "tilelang==0.1.8" \
  "torchao==0.16.0"

"$TRAINING_PYTHON" -c \
  'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0), "capability": torch.cuda.get_device_capability(0), "bf16": torch.cuda.is_bf16_supported()})'
