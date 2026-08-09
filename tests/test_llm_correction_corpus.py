from __future__ import annotations

import json
from pathlib import Path

from fplagent_llm.correction_corpus import build_correction_corpus
from fplagent_llm.paths import ROOT


def test_correction_corpus_keeps_broad_replay_and_validates_rows(tmp_path: Path) -> None:
    summary = build_correction_corpus(
        ROOT / "data/llm/generated/fpl_corpus_v3/combined_train.jsonl",
        tmp_path / "correction",
    )

    assert summary["rows"] == 13_600
    assert summary["replay_rows"] == 9_600
    assert summary["correction_rows"] == 4_000
    assert 0.70 < summary["replay_fraction"] < 0.71
    assert summary["tool_rows"] > 7_000
    assert summary["image_rows"] == 1_360
    assert summary["near_eval_max_similarity"] < 0.94

    output = tmp_path / "correction/combined_train.jsonl"
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 13_600
    image_paths = [
        part["path"]
        for row in rows
        for message in row["messages"]
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if part.get("type") == "image"
    ]
    assert image_paths
    assert all((output.parent / path).resolve().exists() for path in image_paths)
