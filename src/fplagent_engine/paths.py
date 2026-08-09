from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MODEL_DATA = DATA / "model"
NORMALIZED = MODEL_DATA / "normalized"
FEATURES = MODEL_DATA / "features"
ARTIFACTS = MODEL_DATA / "artifacts"
FORECASTS = MODEL_DATA / "forecasts"
DECISIONS = DATA / "decisions"
REPORTS = ROOT / "reports"


def ensure_engine_layout() -> None:
    for path in (NORMALIZED, FEATURES, ARTIFACTS, FORECASTS, DECISIONS, REPORTS):
        path.mkdir(parents=True, exist_ok=True)
