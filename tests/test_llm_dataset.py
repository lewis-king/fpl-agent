from __future__ import annotations

from fplagent_llm.dataset import (
    _assert_no_eval_prompt_contamination,
    _language_rows,
    _tool_rows,
    validate_sft_rows,
)
from fplagent_llm.knowledge import chunk_markdown
from fplagent_llm.paths import ROOT
from fplagent_llm.source_policy import load_source_registry


def test_seed_sft_rows_are_valid_and_evaluation_safe() -> None:
    rows = _language_rows() + _tool_rows()
    counts = validate_sft_rows(rows)
    _assert_no_eval_prompt_contamination(rows)
    assert counts["rows"] >= 50
    assert counts["tool_rows"] >= 5
    assert counts["image_rows"] == 0


def test_seed_tool_rows_use_structured_calls_and_grounded_final_answers() -> None:
    rows = _tool_rows()
    for row in rows:
        assert row["metadata"]["synthetic"] is True
        assert row["messages"][-1]["role"] == "assistant"
        assert row["messages"][-1]["content"]
        calls = [
            call
            for message in row["messages"]
            for call in message.get("tool_calls", [])
        ]
        assert calls
        for call in calls:
            assert isinstance(call["function"]["arguments"], dict)


def test_markdown_chunking_is_deterministic_and_provenanced() -> None:
    path = ROOT / "reports" / "decision-engine-blueprint.md"
    first = chunk_markdown(path, ROOT, target_words=200, overlap_words=30)
    second = chunk_markdown(path, ROOT, target_words=200, overlap_words=30)
    assert first
    assert first == second
    assert all(chunk.source_sha256 for chunk in first)
    assert all(chunk.rights == "owned" for chunk in first)
    assert all(chunk.source_path == "reports/decision-engine-blueprint.md" for chunk in first)


def test_markdown_chunker_rejects_nonadvancing_windows() -> None:
    path = ROOT / "reports" / "data-quality.md"
    try:
        chunk_markdown(path, ROOT, target_words=100, overlap_words=100)
    except ValueError as exc:
        assert "exceed" in str(exc)
    else:
        raise AssertionError("expected target/overlap validation to fail")


def test_source_registry_defaults_unknown_sources_to_deny() -> None:
    registry = load_source_registry()
    assert registry.decision_for("unknown-source", "sft") == "deny"
    assert registry.decision_for("owned-training-seed", "sft") == "allow"


def test_restricted_public_sources_cannot_enter_sft() -> None:
    registry = load_source_registry()
    for source_id in (
        "official-fpl-game",
        "reddit-user-content",
        "user-supplied-screenshots",
    ):
        try:
            registry.require_allowed(source_id, "sft")
        except ValueError as exc:
            assert "not allowed" in str(exc)
        else:
            raise AssertionError(f"expected {source_id} to be rejected for SFT")


def test_official_fpl_research_extracts_are_available_to_runtime_layers() -> None:
    registry = load_source_registry()
    for use in ("rag", "evaluation", "automated_fetch", "live_tool"):
        registry.require_allowed("official-fpl-game", use)
    registry.require_allowed("official-fpl-derived-synthetic", "sft")
