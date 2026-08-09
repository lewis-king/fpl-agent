from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
MANIFESTS = DATA / "manifests"


def ensure_layout() -> None:
    for path in (RAW, PROCESSED, MANIFESTS):
        path.mkdir(parents=True, exist_ok=True)

