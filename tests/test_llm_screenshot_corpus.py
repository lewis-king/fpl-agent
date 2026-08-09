from __future__ import annotations

import json
import shutil
import struct
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from fplagent_llm.contracts import validate_resolved_team
from fplagent_llm.paths import ROOT
from fplagent_llm.screenshot_corpus import (
    _split_for,
    render_case_svg,
    render_corpus,
    variations_for,
)
from fplagent_llm.screenshot_import import load_current_catalog
from fplagent_llm.synthetic_screenshots import load_renderer_context, sample_legal_squad

DATABASE = ROOT / "data" / "fpl_history.duckdb"


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", payload[16:24])


def test_large_split_is_balanced_and_test_templates_are_held_out() -> None:
    split_counts = Counter(_split_for(index, 240) for index in range(240))
    assert split_counts == {"train": 192, "validation": 24, "test": 24}

    templates: dict[str, set[str]] = defaultdict(set)
    variation_counts = Counter()
    for index in range(240):
        split = _split_for(index, 240)
        variations = variations_for(split, index)
        assert len(variations) == 5
        variation_counts[split] += len(variations)
        templates[split].update(variation.template for variation in variations)

    assert variation_counts == {"train": 960, "validation": 120, "test": 120}
    assert templates["train"] == templates["validation"]
    assert templates["train"].isdisjoint(templates["test"])
    assert templates["test"] == {"broadcast", "paper"}


def test_partial_render_has_adjusted_visible_truth_and_legal_private_truth() -> None:
    catalog = load_current_catalog(DATABASE)
    catalog_by_id = {player.player_id: player for player in catalog}
    squad = sample_legal_squad(catalog, seed=91, squad_id="partial-contract")
    variation = variations_for("train", 0)[4]
    assert variation.occluded_slots == (("bench", 3),)

    rendered = render_case_svg(
        "partial-contract-mobile",
        squad,
        catalog,
        load_renderer_context(DATABASE),
        variation,
        seed=91,
    )
    assert len(rendered.extraction["players"]) == 14
    assert rendered.extraction["unresolved"] == ["bench slot 3 is obscured"]
    assert len(rendered.visible_proposal.players) == 14
    assert len(rendered.full_proposal.players) == 15
    assert "Preview unavailable" in rendered.svg
    assert not validate_resolved_team(rendered.visible_proposal, catalog_by_id).valid
    assert validate_resolved_team(rendered.full_proposal, catalog_by_id).valid
    assert rendered.expected_valid is False


def test_list_render_preserves_all_visible_players() -> None:
    catalog = load_current_catalog(DATABASE)
    squad = sample_legal_squad(catalog, seed=107, squad_id="list-contract")
    variation = variations_for("train", 1)[2]
    rendered = render_case_svg(
        "list-contract-mobile",
        squad,
        catalog,
        load_renderer_context(DATABASE),
        variation,
        seed=107,
    )
    root = ET.fromstring(rendered.svg)
    assert root.attrib["width"] == "1042"
    assert root.attrib["height"] == "2048"
    assert len(rendered.extraction["players"]) == 15
    assert len(rendered.visible_proposal.players) == 15
    assert rendered.expected_valid is True
    assert rendered.extraction["formation"] == squad.formation


@pytest.mark.skipif(shutil.which("magick") is None, reason="ImageMagick is unavailable")
def test_corpus_writes_rasters_truth_and_split_sft(tmp_path: Path) -> None:
    output = tmp_path / "corpus"
    summary = render_corpus(DATABASE, output_dir=output, squad_count=3, seed=113)
    assert summary["squads"] == 3
    assert summary["images"] == 15
    assert {key: value["rows"] for key, value in summary["splits"].items()} == {
        "train": 5,
        "validation": 5,
        "test": 5,
    }

    manifest = [
        json.loads(line)
        for line in (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len({row["case_id"] for row in manifest}) == 15
    assert len({row["squad_signature"] for row in manifest}) == 3
    assert all(row["source"] == "official-fpl-derived-synthetic" for row in manifest)
    train_templates = {row["template"] for row in manifest if row["split"] == "train"}
    test_templates = {row["template"] for row in manifest if row["split"] == "test"}
    assert train_templates.isdisjoint(test_templates)

    partial_rows = [row for row in manifest if row["occluded_slots"]]
    assert len(partial_rows) == 1
    for row in manifest:
        assert _png_dimensions(output / row["image_path"]) == (row["width"], row["height"])
        truth = json.loads((output / row["truth_path"]).read_text(encoding="utf-8"))
        assert truth["full_validation"]["valid"] is True
        assert truth["visible_validation"]["valid"] is row["expected_valid"]

    train_rows = [
        json.loads(line)
        for line in (output / "sft_train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["metadata"]["split"] == "train" for row in train_rows)
    assert all(row["messages"][1]["content"][0]["type"] == "image" for row in train_rows)
