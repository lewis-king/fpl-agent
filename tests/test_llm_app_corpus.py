from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fplagent_llm.app_corpus import (
    NEW_FAMILY_TARGETS,
    QUALITY_IMAGE_REPLAY,
    QUALITY_MULTI_TURN_ROWS,
    QUALITY_TOOL_ROWS,
    QUALITY_VARIANTS_PER_SCENARIO,
    REPLAY_TARGETS,
    TOOL_AWARE_DROPPED_FAMILIES,
    build_app_corpus,
    build_quality_corpus,
    build_tool_aware_corpus,
)
from fplagent_llm.paths import ROOT


def test_app_corpus_is_direct_answer_heavy_and_replay_balanced(tmp_path: Path) -> None:
    output = tmp_path / "v5"
    summary = build_app_corpus(
        ROOT / "data/llm/generated/fpl_corpus_v3/combined_train.jsonl",
        output,
    )

    assert summary["rows"] == 24_000
    assert summary["new_rows"] == sum(NEW_FAMILY_TARGETS.values()) == 17_200
    assert summary["replay_rows"] == sum(REPLAY_TARGETS.values()) == 6_800
    assert summary["direct_answer_fraction"] > 0.75
    assert summary["tool_rows"] < 6_000
    assert summary["image_rows"] == 960
    assert summary["multi_turn_rows"] == 1_600
    assert summary["near_eval_max_similarity"] < 0.95

    rows = [
        json.loads(line)
        for line in (output / "combined_train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    families = Counter(row["metadata"]["family"] for row in rows)
    for family, count in NEW_FAMILY_TARGETS.items():
        assert families[family] == count
    for family, count in REPLAY_TARGETS.items():
        assert families[f"replay_{family}"] == count

    prompts = [
        row["messages"][1]["content"]
        for row in rows
        if isinstance(row["messages"][1]["content"], str)
    ]
    assert len(prompts) == len({prompt.casefold() for prompt in prompts})
    assert not any(prompt.strip().casefold() == "what do you do?" for prompt in prompts)

    image_paths = [
        part["path"]
        for row in rows
        for message in row["messages"]
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if part.get("type") == "image"
    ]
    assert len(image_paths) == 960
    assert all((output / path).resolve().exists() for path in image_paths[:20])


def test_tool_aware_corpus_removes_legacy_tool_routes(tmp_path: Path) -> None:
    v5_output = tmp_path / "v5"
    build_app_corpus(
        ROOT / "data/llm/generated/fpl_corpus_v3/combined_train.jsonl",
        v5_output,
    )
    v6_output = tmp_path / "v6"
    summary = build_tool_aware_corpus(
        v5_output / "combined_train.jsonl",
        v6_output,
    )

    assert summary["rows"] == 20_554
    assert summary["dropped_rows"] == 3_446
    assert summary["dropped_unsupported_tool_rows"] == 446
    assert summary["tool_rows"] == 2_000
    assert summary["direct_answer_fraction"] > 0.90
    assert summary["image_rows"] == 960
    assert set(summary["dropped_families"]) == TOOL_AWARE_DROPPED_FAMILIES

    rows = [
        json.loads(line)
        for line in (v6_output / "combined_train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    families = {row["metadata"]["family"] for row in rows}
    assert not (families & TOOL_AWARE_DROPPED_FAMILIES)
    assert all(
        row["metadata"]["tool_context"]
        in {"qwen_app_tools_v1", "none_for_screenshot"}
        for row in rows
    )


def test_quality_corpus_is_diverse_and_keeps_runtime_alignment(tmp_path: Path) -> None:
    output = tmp_path / "v7"
    summary = build_quality_corpus(
        ROOT / "data/llm/generated/fpl_app_corpus_v6/combined_train.jsonl",
        output,
    )

    assert summary["rows"] == 5_476
    assert summary["quality_scenarios"] == 134
    assert summary["variants_per_scenario"] == QUALITY_VARIANTS_PER_SCENARIO
    assert summary["tool_rows"] == QUALITY_TOOL_ROWS
    assert summary["image_rows"] == QUALITY_IMAGE_REPLAY
    assert summary["multi_turn_rows"] == QUALITY_MULTI_TURN_ROWS
    assert summary["near_eval_max_similarity"] < 0.95

    rows = [
        json.loads(line)
        for line in (output / "combined_train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assistant_texts = [
        message["content"]
        for row in rows
        for message in row["messages"]
        if message.get("role") == "assistant"
        and isinstance(message.get("content"), str)
        and not message.get("tool_calls")
    ]
    assert len(set(assistant_texts)) > 1_900
    assert not any(
        text.endswith("A good FPL conversation should make the next decision clearer, not merely longer.")
        for text in assistant_texts
    )
    assert all(
        row["metadata"]["tool_context"]
        in {"qwen_app_tools_v1", "none_for_screenshot"}
        for row in rows
    )
