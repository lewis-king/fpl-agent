from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from fplagent_llm.conversation_corpus import (
    FAMILY_TARGETS,
    _split_for_group,
    build_conversation_corpus,
)
from fplagent_llm.paths import ROOT
from fplagent_llm.tool_contracts import validate_tool_arguments

DATABASE = ROOT / "data" / "fpl_history.duckdb"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_scenario_group_split_is_exactly_eighty_ten_ten() -> None:
    assert Counter(_split_for_group(index) for index in range(100)) == {
        "train": 80,
        "validation": 10,
        "test": 10,
    }


def test_tool_arguments_are_checked_against_runtime_contracts() -> None:
    validate_tool_arguments(
        "get_player_forecasts",
        {
            "player_ids": [73],
            "start_event": 1,
            "horizon": 12,
            "as_of": "2026-08-02T10:02:54+00:00",
        },
    )
    with pytest.raises(ValueError, match="at most 12"):
        validate_tool_arguments(
            "get_player_forecasts",
            {
                "player_ids": [73],
                "start_event": 1,
                "horizon": 13,
                "as_of": "2026-08-02T10:02:54+00:00",
            },
        )
    with pytest.raises(ValueError, match="unknown fields"):
        validate_tool_arguments(
            "get_manager_state",
            {
                "manager_id": 1,
                "as_of": "2026-08-02T10:02:54+00:00",
                "invented": True,
            },
        )


def test_full_conversation_corpus_is_balanced_grounded_and_reproducible(
    tmp_path: Path,
) -> None:
    output = tmp_path / "corpus"
    first = build_conversation_corpus(DATABASE, output_dir=output, seed=20_260_812)
    second = build_conversation_corpus(DATABASE, output_dir=output, seed=20_260_812)

    assert first["combined_rows"] == 12_000
    assert first["combined_splits"] == {
        "train": 9_600,
        "validation": 1_200,
        "test": 1_200,
    }
    assert first["text"]["families"] == FAMILY_TARGETS
    assert first["text"]["tool_rows"] == 6_720
    assert first["text"]["estimated_tokens"] > 4_000_000
    assert first["text"]["unique_assistant_targets"] >= 9_000
    assert first["text"]["maximum_repeated_assistant_target"] <= 10
    assert first["text"]["near_eval_max_similarity"] < 0.94
    assert first["community_content_copied_into_targets"] is False
    assert first["text_files"] == second["text_files"]
    assert first["combined_files"] == second["combined_files"]
    assert first["manifest"] == second["manifest"]

    manifest = _rows(output / "text_manifest.jsonl")
    assert len(manifest) == 10_800
    group_splits: dict[str, set[str]] = defaultdict(set)
    for row in manifest:
        group_splits[row["scenario_group"]].add(row["split"])
    assert len(group_splits) == 1_080
    assert all(len(splits) == 1 for splits in group_splits.values())

    train_rows = _rows(output / "combined_train.jsonl")
    assert len(train_rows) == 9_600
    assert Counter(row["metadata"]["family"] for row in train_rows)["multimodal"] == 960
    image_rows = [
        row
        for row in train_rows
        if any(
            isinstance(message.get("content"), list)
            for message in row["messages"]
        )
    ]
    assert len(image_rows) == 960
    for row in image_rows[:10]:
        image_part = row["messages"][1]["content"][0]
        assert image_part["type"] == "image"
        assert (output / image_part["path"]).resolve().exists()

    for name, details in first["combined_files"].items():
        payload = (output / f"combined_{name}.jsonl").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == details["sha256"]
