from __future__ import annotations

import json
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fplagent_llm.contracts import validate_resolved_team
from fplagent_llm.paths import ROOT
from fplagent_llm.screenshot_import import load_current_catalog
from fplagent_llm.synthetic_screenshots import (
    RenderVariation,
    _locked_signatures,
    load_renderer_context,
    render_dataset,
    render_svg,
    sample_legal_squad,
)

DATABASE = ROOT / "data" / "fpl_history.duckdb"


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", payload[16:24])


def test_legal_squad_sampling_is_deterministic_and_avoids_locked_teams() -> None:
    catalog = load_current_catalog(DATABASE)
    first = sample_legal_squad(
        catalog,
        seed=8142,
        squad_id="test-squad",
        forbidden_signatures=_locked_signatures(),
    )
    second = sample_legal_squad(
        catalog,
        seed=8142,
        squad_id="test-squad",
        forbidden_signatures=_locked_signatures(),
    )
    assert first == second
    assert frozenset(player.player_id for player in first.players) not in _locked_signatures()
    proposal = render_svg(
        first,
        catalog,
        load_renderer_context(DATABASE),
        RenderVariation(
            viewport="desktop",
            width=988,
            height=919,
            show_metadata=True,
            show_chips=False,
            truncate_names=True,
            damage="clean",
        ),
        seed=8142,
    )[2]
    result = validate_resolved_team(
        proposal, {player.player_id: player for player in catalog}
    )
    assert result.valid, result.issues


def test_svg_and_extraction_share_visible_truth() -> None:
    catalog = load_current_catalog(DATABASE)
    context = load_renderer_context(DATABASE)
    squad = sample_legal_squad(catalog, seed=44, squad_id="visual-contract")
    variation = RenderVariation(
        viewport="mobile",
        width=1042,
        height=2048,
        show_metadata=False,
        show_chips=False,
        truncate_names=True,
        damage="clean",
    )
    svg, extraction, _ = render_svg(squad, catalog, context, variation, seed=44)
    root = ET.fromstring(svg)
    assert root.attrib["width"] == "1042"
    assert root.attrib["height"] == "2048"
    assert extraction["season"] is None
    assert extraction["event"] is None
    assert extraction["deadline"] is None
    assert all(value is None for value in extraction["chips"].values())
    assert len(extraction["players"]) == 15
    assert sum(player["is_captain"] for player in extraction["players"]) == 1
    assert sum(player["is_vice_captain"] for player in extraction["players"]) == 1
    for player in extraction["players"]:
        assert player["source_text"] in svg


@pytest.mark.skipif(shutil.which("magick") is None, reason="ImageMagick is unavailable")
def test_renderer_writes_raster_truth_manifest_and_split_sft(tmp_path: Path) -> None:
    output = tmp_path / "render"
    summary = render_dataset(DATABASE, output_dir=output, squad_count=3, seed=73)
    assert summary["squads"] == 3
    assert summary["images"] == 6
    assert summary["splits"]["train"]["rows"] == 2
    assert summary["splits"]["validation"]["rows"] == 2
    assert summary["splits"]["test"]["rows"] == 2

    manifest = [
        json.loads(line)
        for line in (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(manifest) == 6
    assert len({row["case_id"] for row in manifest}) == 6
    assert len({row["squad_signature"] for row in manifest}) == 3
    assert all(row["source"] == "official-fpl-derived-synthetic" for row in manifest)
    for row in manifest:
        image_path = output / row["image_path"]
        assert _png_dimensions(image_path) == (row["width"], row["height"])
        truth = json.loads((output / row["truth_path"]).read_text(encoding="utf-8"))
        assert truth["validation"]["valid"] is True

    train_rows = [
        json.loads(line)
        for line in (output / "sft_train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["metadata"]["split"] == "train" for row in train_rows)
    assert all(row["messages"][1]["content"][0]["type"] == "image" for row in train_rows)
