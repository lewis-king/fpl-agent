from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from fplagent_llm.paths import ROOT
from fplagent_llm.precision_corpus import (
    DIRECT_VARIANTS,
    IMAGE_REPLAY_ROWS,
    MULTI_TURN_ROWS,
    MULTILINGUAL_REPLAY_ROWS,
    TOOL_VARIANTS,
    build_precision_corpus,
)
from fplagent_llm.training_context import APP_TOOL_NAMES


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_precision_corpus_has_deliberate_balanced_shape(tmp_path: Path) -> None:
    output = tmp_path / "v9"
    summary = build_precision_corpus(
        ROOT / "data/llm/generated/fpl_app_corpus_v6/combined_train.jsonl",
        output,
    )

    assert summary["rows"] == 3_668
    assert summary["quality_scenarios"] == 134
    assert summary["variants_per_scenario"] == DIRECT_VARIANTS == 12
    assert summary["tool_rows"] == 7 * TOOL_VARIANTS == 700
    assert summary["multi_turn_rows"] == MULTI_TURN_ROWS == 200
    assert summary["image_rows"] == IMAGE_REPLAY_ROWS == 960
    assert summary["direct_text_rows"] == (
        134 * DIRECT_VARIANTS + MULTI_TURN_ROWS + MULTILINGUAL_REPLAY_ROWS
    )
    assert summary["near_eval_max_similarity"] < 0.95

    rows = _rows(output / "combined_train.jsonl")
    assert Counter(row["metadata"]["family"] for row in rows) == {
        "precision_direct": 1_608,
        "precision_multi_turn": 200,
        "precision_replay_multilingual": 200,
        "precision_replay_multimodal": 960,
        "precision_tool_routing": 700,
    }
    assert all(
        row["metadata"]["tool_context"]
        in {"exact_app_runtime_v1", "none_for_screenshot"}
        for row in rows
    )
    prompts = [
        row["messages"][1]["content"]
        for row in rows
        if isinstance(row["messages"][1].get("content"), str)
    ]
    assert len(prompts) == len({prompt.casefold() for prompt in prompts})
    assert not any(prompt.strip().casefold() == "what do you do?" for prompt in prompts)


def test_precision_tool_routes_are_faithful_and_use_only_app_tools(
    tmp_path: Path,
) -> None:
    output = tmp_path / "v9"
    build_precision_corpus(
        ROOT / "data/llm/generated/fpl_app_corpus_v6/combined_train.jsonl",
        output,
    )
    rows = _rows(output / "combined_train.jsonl")
    tool_rows = [
        row
        for row in rows
        if any(message.get("tool_calls") for message in row["messages"])
    ]

    observed_tools: set[str] = set()
    manager_results = 0
    optimize_results = 0
    for row in tool_rows:
        pending_calls: dict[str, tuple[str, dict[str, Any]]] = {}
        for message in row["messages"]:
            for call in message.get("tool_calls", []):
                function = call["function"]
                observed_tools.add(function["name"])
                pending_calls[call["id"]] = (function["name"], function["arguments"])
            if message.get("role") != "tool":
                continue
            name, arguments = pending_calls[message["tool_call_id"]]
            result = json.loads(message["content"])
            assert message["name"] == name
            if name == "get_manager_state":
                assert result["squad_size"] == len(result["squad"]) == 15
                manager_results += 1
            if name == "optimize_squad":
                assert result["legal"] is True
                assert len(result["roster"]) == 15
                assert result["applied_constraints"] == arguments["constraints"]
                optimize_results += 1

    assert observed_tools == APP_TOOL_NAMES
    assert manager_results == 700
    assert optimize_results == 400


def test_precision_direct_targets_do_not_reintroduce_generic_closers(
    tmp_path: Path,
) -> None:
    output = tmp_path / "v9"
    build_precision_corpus(
        ROOT / "data/llm/generated/fpl_app_corpus_v6/combined_train.jsonl",
        output,
    )
    rows = _rows(output / "combined_train.jsonl")
    direct_answers = [
        row["messages"][-1]["content"]
        for row in rows
        if row["metadata"]["family"] == "precision_direct"
    ]

    assert len(set(direct_answers)) == 134
    banned = (
        "the important distinction",
        "a good fpl conversation should",
        "practical point:",
    )
    assert not any(phrase in answer.casefold() for phrase in banned for answer in direct_answers)
