from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "llm"
BENCHMARKS = CONFIG / "benchmarks"
TRAINING_SEEDS = CONFIG / "training_seeds"
DATA = ROOT / "data" / "llm"
GENERATED = DATA / "generated"
MANIFESTS = DATA / "manifests"


def ensure_llm_layout() -> None:
    for path in (BENCHMARKS, TRAINING_SEEDS, GENERATED, MANIFESTS):
        path.mkdir(parents=True, exist_ok=True)
