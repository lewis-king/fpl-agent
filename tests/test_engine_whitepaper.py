from __future__ import annotations

from pathlib import Path

from fplagent_engine.cli import parser
from fplagent_engine.whitepaper import build_algorithm_whitepaper


def test_whitepaper_is_self_contained_and_bound_to_current_decision(tmp_path: Path) -> None:
    output = tmp_path / "whitepaper.html"

    result = build_algorithm_whitepaper(output_path=output)
    text = output.read_text(encoding="utf-8")

    assert result["candidate_id"] in text
    assert result["sha256"]
    assert "data:font/ttf;base64," in text
    assert "<link rel=\"stylesheet\"" not in text
    assert "authored xP is explicitly excluded" in text
    assert "Fresh bench/allocation selector" in text
    assert "Neither ep_this, ep_next nor xP can enter" in text
    assert "What it does not prove" in text
    assert "OpenFPL" in text


def test_whitepaper_is_exposed_as_one_engine_command() -> None:
    args = parser().parse_args(["build-algorithm-whitepaper"])
    assert args.command == "build-algorithm-whitepaper"
