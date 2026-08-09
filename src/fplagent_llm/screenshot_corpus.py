from __future__ import annotations

import hashlib
import html
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import CatalogPlayer, ImportedPlayer, ScreenshotTeamProposal, validate_resolved_team
from .dataset import SYSTEM_PROMPT, validate_sft_rows
from .paths import GENERATED, ROOT
from .screenshot_import import load_current_catalog
from .synthetic_screenshots import (
    EXTRACTION_INSTRUCTION,
    FORMATIONS,
    PALETTES,
    RendererContext,
    SyntheticSquad,
    _chip_states,
    _locked_signatures,
    _player_card,
    _row_positions,
    load_renderer_context,
    sample_legal_squad,
)

GENERATOR_VERSION = "synthetic-screenshot-v2"
DEFAULT_OUTPUT = GENERATED / "screenshot_corpus_v2"


@dataclass(frozen=True)
class Theme:
    background: str
    header: str
    field_top: str
    field_bottom: str
    field_line: str
    field_border: str
    bench: str
    primary_text: str
    secondary_text: str
    accent: str


THEMES = {
    "canvas": Theme(
        "#171c20",
        "#1c2227",
        "#176f55",
        "#0d6049",
        "#e4eee7",
        "#5aa384",
        "#c8dfd2",
        "#f4f1e9",
        "#9fb3ac",
        "#abc7b7",
    ),
    "compact": Theme(
        "#e8ebe6",
        "#25322f",
        "#40725d",
        "#315e4d",
        "#edf3ef",
        "#799987",
        "#dde5dd",
        "#f5f2eb",
        "#b8c5be",
        "#d0a768",
    ),
    "roster": Theme(
        "#182023",
        "#20292d",
        "#2c383b",
        "#232e31",
        "#5f7275",
        "#39484b",
        "#252f32",
        "#f2efe8",
        "#9eadae",
        "#8fbda8",
    ),
    "ledger": Theme(
        "#efeee8",
        "#deded6",
        "#f7f5ef",
        "#ebe9e2",
        "#9aa7a0",
        "#c2c6be",
        "#e4e4dc",
        "#27312f",
        "#68736f",
        "#9b754b",
    ),
    "broadcast": Theme(
        "#172126",
        "#243039",
        "#47746c",
        "#345c57",
        "#f0e9d9",
        "#8ca69f",
        "#d7d1c2",
        "#f4eddf",
        "#b9c2bf",
        "#c4945d",
    ),
    "paper": Theme(
        "#f2efe6",
        "#e1ded4",
        "#faf7ef",
        "#eae6dc",
        "#909b95",
        "#c9c7bc",
        "#dfddd3",
        "#27302e",
        "#6f7874",
        "#ad754c",
    ),
}


@dataclass(frozen=True)
class CorpusVariation:
    key: str
    viewport: str
    width: int
    height: int
    view: str
    template: str
    show_metadata: bool
    show_chips: bool
    truncate_names: bool
    damage: str
    evaluation_axis: str
    occluded_slots: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class RenderedCase:
    svg: str
    extraction: dict[str, Any]
    visible_proposal: ScreenshotTeamProposal
    full_proposal: ScreenshotTeamProposal
    expected_valid: bool


def _split_for(index: int, squad_count: int) -> str:
    if squad_count < 10:
        if squad_count == 1:
            return "train"
        if squad_count == 2:
            return "train" if index == 0 else "test"
        if index == squad_count - 1:
            return "test"
        if index == squad_count - 2:
            return "validation"
        return "train"
    fraction = index / squad_count
    if fraction < 0.8:
        return "train"
    if fraction < 0.9:
        return "validation"
    return "test"


def _variant(
    key: str,
    viewport: str,
    view: str,
    template: str,
    show_metadata: bool,
    show_chips: bool,
    truncate_names: bool,
    damage: str,
    axis: str,
    occluded: bool = False,
) -> CorpusVariation:
    dimensions = {"mobile": (1042, 2048), "desktop": (988, 919)}
    width, height = dimensions[viewport]
    return CorpusVariation(
        key=key,
        viewport=viewport,
        width=width,
        height=height,
        view=view,
        template=template,
        show_metadata=show_metadata,
        show_chips=show_chips,
        truncate_names=truncate_names,
        damage=damage,
        evaluation_axis=axis,
        occluded_slots=(("bench", 3),) if occluded else (),
    )


def variations_for(split: str, index: int) -> tuple[CorpusVariation, ...]:
    partial = index % 4 == 0
    if split == "test":
        return (
            _variant(
                "mobile-pitch-broadcast",
                "mobile",
                "pitch",
                "broadcast",
                True,
                True,
                index % 2 == 0,
                "clean",
                "template_holdout",
            ),
            _variant(
                "desktop-pitch-broadcast-crop",
                "desktop",
                "pitch",
                "broadcast",
                False,
                False,
                True,
                "edge_crop",
                "template_holdout",
            ),
            _variant(
                "mobile-list-paper",
                "mobile",
                "list",
                "paper",
                True,
                False,
                False,
                "scaled_roundtrip",
                "template_holdout",
            ),
            _variant(
                "desktop-list-paper-partial",
                "desktop",
                "list",
                "paper",
                True,
                False,
                True,
                "clean",
                "template_holdout",
                occluded=partial,
            ),
            _variant(
                "mobile-pitch-broadcast-photo",
                "mobile",
                "pitch",
                "broadcast",
                True,
                False,
                True,
                "screen_photo",
                "template_holdout",
            ),
        )

    axis = "in_distribution"
    return (
        _variant(
            "mobile-pitch-canvas",
            "mobile",
            "pitch",
            "canvas",
            True,
            index % 2 == 0,
            index % 3 != 1,
            "jpeg_roundtrip" if index % 5 == 1 else "clean",
            axis,
        ),
        _variant(
            "desktop-pitch-compact",
            "desktop",
            "pitch",
            "compact",
            index % 3 != 2,
            False,
            index % 2 == 0,
            "soft_blur" if index % 5 == 2 else "clean",
            axis,
        ),
        _variant(
            "mobile-list-roster",
            "mobile",
            "list",
            "roster",
            True,
            False,
            index % 4 != 1,
            "scaled_roundtrip",
            axis,
        ),
        _variant(
            "desktop-list-ledger",
            "desktop",
            "list",
            "ledger",
            index % 4 != 3,
            False,
            False,
            "edge_crop" if index % 6 == 3 else "clean",
            axis,
        ),
        _variant(
            "mobile-pitch-compact-partial",
            "mobile",
            "pitch",
            "compact",
            False,
            False,
            True,
            "screen_photo" if index % 5 == 4 else "clean",
            axis,
            occluded=partial,
        ),
    )


def _rendered_name(player: ImportedPlayer, variation: CorpusVariation, compact: bool) -> str:
    limit = 13 if compact else 14 if variation.viewport == "mobile" else 17
    if not variation.truncate_names or len(player.source_text) <= limit:
        return player.source_text
    return player.source_text[: limit - 1].rstrip("- ") + "…"


def _build_proposal(
    case_id: str,
    squad: SyntheticSquad,
    context: RendererContext,
    variation: CorpusVariation,
    rendered_names: dict[tuple[str, int], str],
    visible_slots: set[tuple[str, int]],
    chips: dict[str, str | None],
    *,
    include_unresolved: bool,
) -> ScreenshotTeamProposal:
    players = tuple(
        ImportedPlayer(
            source_text=rendered_names[(player.squad_role, player.order)],
            squad_role=player.squad_role,
            order=player.order,
            player_id=player.player_id,
            position=player.position,
            confidence=1.0,
        )
        for player in squad.players
        if (player.squad_role, player.order) in visible_slots
    )
    bench_order = tuple(
        player.player_id
        for player in sorted(
            (player for player in players if player.squad_role == "bench"),
            key=lambda player: player.order,
        )
        if player.player_id is not None
    )
    return ScreenshotTeamProposal(
        schema_version="screenshot-team-v1",
        source_image_id=case_id,
        season=context.season,
        event=context.event if variation.show_metadata else None,
        deadline=(
            datetime.fromisoformat(context.deadline) if variation.show_metadata else None
        ),
        formation=squad.formation,
        players=players,
        captain_player_id=squad.captain_player_id,
        vice_captain_player_id=squad.vice_captain_player_id,
        bench_order=bench_order,
        chips={key: value if value is not None else "not_visible" for key, value in chips.items()},
        unresolved=("bench slot 3 is obscured",) if include_unresolved else (),
    )


def _build_truth(
    case_id: str,
    squad: SyntheticSquad,
    context: RendererContext,
    variation: CorpusVariation,
    rendered_names: dict[tuple[str, int], str],
    chips: dict[str, str | None],
) -> tuple[dict[str, Any], ScreenshotTeamProposal, ScreenshotTeamProposal]:
    all_slots = {(player.squad_role, player.order) for player in squad.players}
    visible_slots = all_slots - set(variation.occluded_slots)
    extraction_players = [
        {
            "source_text": rendered_names[(player.squad_role, player.order)],
            "position": player.position,
            "squad_role": player.squad_role,
            "order": player.order,
            "is_captain": player.player_id == squad.captain_player_id,
            "is_vice_captain": player.player_id == squad.vice_captain_player_id,
        }
        for player in squad.players
        if (player.squad_role, player.order) in visible_slots
    ]
    extraction = {
        "season": context.season if variation.show_metadata else None,
        "event": context.event if variation.show_metadata else None,
        "deadline": context.deadline if variation.show_metadata else None,
        "formation": squad.formation,
        "players": extraction_players,
        "chips": chips,
        "unresolved": ["bench slot 3 is obscured"] if variation.occluded_slots else [],
    }
    visible = _build_proposal(
        case_id,
        squad,
        context,
        variation,
        rendered_names,
        visible_slots,
        chips,
        include_unresolved=bool(variation.occluded_slots),
    )
    full = _build_proposal(
        case_id,
        squad,
        context,
        variation,
        rendered_names,
        all_slots,
        chips,
        include_unresolved=False,
    )
    return extraction, visible, full


def _metadata_markup(
    context: RendererContext,
    variation: CorpusVariation,
    theme: Theme,
    title: str,
) -> str:
    if variation.show_metadata:
        return f"""
        <text x="52" y="50" class="eyebrow">{html.escape(context.season)}</text>
        <text x="52" y="82" class="title">{title}</text>
        <text x="948" y="48" text-anchor="end" class="meta">GW {context.event}</text>
        <text x="948" y="72" text-anchor="end" class="meta small">
          {html.escape(context.deadline[:16].replace('T', ' '))}
        </text>
        """
    return f'<text x="52" y="58" class="title">{title}</text>'


def _chip_markup(
    chips: dict[str, str | None],
    variation: CorpusVariation,
    theme: Theme,
) -> str:
    if not variation.show_chips:
        return ""
    labels = (
        ("Bench boost", chips["bench_boost"]),
        ("Triple captain", chips["triple_captain"]),
        ("Wildcard", chips["wildcard"]),
        ("Free hit", chips["free_hit"]),
    )
    rows = []
    for index, (label, state) in enumerate(labels):
        x = 44 + index * 239
        rows.append(
            f"""
            <g><rect x="{x}" y="112" width="218" height="96" rx="12"
              fill="{theme.header}" stroke="{theme.field_border}"/>
            <text x="{x + 17}" y="145" class="chipLabel">{label}</text>
            <text x="{x + 17}" y="178" class="chipState">{state}</text></g>
            """
        )
    return "".join(rows)


def _style(theme: Theme) -> str:
    return f"""
    text {{ font-family: "Noto Sans", "DejaVu Sans", sans-serif; }}
    .title {{ fill: {theme.primary_text}; font-size: 25px; font-weight: 750; }}
    .eyebrow {{ fill: {theme.secondary_text}; font-size: 14px; font-weight: 700;
                letter-spacing: 1.1px; }}
    .meta {{ fill: {theme.primary_text}; font-size: 14px; font-weight: 700; }}
    .meta.small {{ fill: {theme.secondary_text}; font-size: 11.5px; font-weight: 500; }}
    .playerName {{ fill: #2d2430; font-weight: 750; }}
    .fixture {{ fill: #385052; font-weight: 650; }}
    .badge {{ fill: #f3f1e8; font-size: 12px; font-weight: 800; }}
    .benchOrder {{ fill: #263633; font-size: 13px; font-weight: 750; }}
    .chipLabel {{ fill: {theme.primary_text}; font-size: 14px; font-weight: 700; }}
    .chipState {{ fill: {theme.accent}; font-size: 12.5px; font-weight: 650; }}
    .listName {{ fill: {theme.primary_text}; font-size: 16px; font-weight: 750; }}
    .listMeta {{ fill: {theme.secondary_text}; font-size: 12.5px; font-weight: 600; }}
    .position {{ fill: {theme.accent}; font-size: 11px; font-weight: 800; }}
    """


def _defs(theme: Theme) -> str:
    return f"""
    <defs>
      <linearGradient id="pitch" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="{theme.field_top}"/>
        <stop offset="1" stop-color="{theme.field_bottom}"/>
      </linearGradient>
      <filter id="softShadow" x="-30%" y="-30%" width="160%" height="170%">
        <feDropShadow dx="0" dy="5" stdDeviation="5" flood-color="#17221f"
                      flood-opacity=".24"/>
      </filter>
    </defs>
    """


def _occlusion_markup(
    boxes: dict[tuple[str, int], tuple[float, float, float, float]],
    variation: CorpusVariation,
    theme: Theme,
) -> str:
    rows = []
    for slot in variation.occluded_slots:
        x, y, width, height = boxes[slot]
        rows.append(
            f"""
            <g data-occludes="{slot[0]}:{slot[1]}">
              <rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}"
                    rx="12" fill="{theme.header}" stroke="{theme.accent}" stroke-width="1.3"/>
              <path d="M {x + 18:.2f} {y + height / 2:.2f} H {x + 35:.2f}"
                    stroke="{theme.accent}" stroke-width="3"/>
              <text x="{x + 44:.2f}" y="{y + height / 2 + 4:.2f}"
                    fill="{theme.primary_text}" font-size="11.5" font-weight="700">
                Preview unavailable
              </text>
            </g>
            """
        )
    return "".join(rows)


def _render_pitch(
    case_id: str,
    squad: SyntheticSquad,
    catalog: tuple[CatalogPlayer, ...],
    context: RendererContext,
    variation: CorpusVariation,
    seed: int,
) -> RenderedCase:
    theme = THEMES[variation.template]
    catalog_by_id = {player.player_id: player for player in catalog}
    canvas_width = 1000.0
    canvas_height = canvas_width * variation.height / variation.width
    mobile = variation.viewport == "mobile"
    header_height = 280 if mobile and variation.show_chips else 132 if mobile else 92
    pitch_top = header_height + 22
    bench_height = 260 if mobile else 205
    pitch_bottom = canvas_height - bench_height - 24
    pitch_height = pitch_bottom - pitch_top
    compact = variation.template == "compact"
    card_width = 138 if mobile else 110
    chips = _chip_states(seed, variation.show_chips)
    starters = [player for player in squad.players if player.squad_role == "starter"]
    bench = sorted(
        (player for player in squad.players if player.squad_role == "bench"),
        key=lambda player: player.order,
    )
    by_position = {
        position: [player for player in starters if player.position == position]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    row_y = {
        "GK": pitch_top + pitch_height * 0.08,
        "DEF": pitch_top + pitch_height * 0.30,
        "MID": pitch_top + pitch_height * 0.54,
        "FWD": pitch_top + pitch_height * 0.77,
    }
    player_markup: list[str] = []
    rendered_names: dict[tuple[str, int], str] = {}
    boxes: dict[tuple[str, int], tuple[float, float, float, float]] = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = by_position[position]
        positions = _row_positions(len(rows), canvas_width, pitch_top, row_y[position])
        for player, (x, y) in zip(rows, positions, strict=True):
            markup, rendered_name = _player_card(
                player,
                catalog_by_id,
                context,
                variation,  # type: ignore[arg-type]
                x,
                y,
                card_width,
                compact=compact and not mobile,
                is_captain=player.player_id == squad.captain_player_id,
                is_vice=player.player_id == squad.vice_captain_player_id,
            )
            slot = (player.squad_role, player.order)
            player_markup.append(markup)
            rendered_names[slot] = rendered_name
            boxes[slot] = (x - card_width / 2 - 8, y - 4, card_width + 16, 145)

    bench_y = pitch_bottom + 56
    bench_width = 150 if mobile else 118
    for player, (x, y) in zip(
        bench,
        _row_positions(4, canvas_width, pitch_top, bench_y),
        strict=True,
    ):
        markup, rendered_name = _player_card(
            player,
            catalog_by_id,
            context,
            variation,  # type: ignore[arg-type]
            x,
            y,
            bench_width,
            compact=not mobile,
            bench_label=f"{player.order}. {player.position}",
        )
        slot = (player.squad_role, player.order)
        player_markup.append(markup)
        rendered_names[slot] = rendered_name
        boxes[slot] = (x - bench_width / 2 - 8, y - 14, bench_width + 16, 142)

    extraction, visible, full = _build_truth(
        case_id, squad, context, variation, rendered_names, chips
    )
    shape = (
        f'<rect x="24" y="{pitch_top:.2f}" width="952" '
        f'height="{pitch_height:.2f}" rx="8" fill="url(#pitch)" '
        f'stroke="{theme.field_border}" stroke-width="2"/>'
        if compact
        else (
            f'<path d="M 112 {pitch_top:.2f} H 888 L 982 {pitch_bottom:.2f} '
            f'H 18 Z" fill="url(#pitch)" stroke="{theme.field_border}" stroke-width="2"/>'
        )
    )
    line_left = 28 if compact else 65
    line_right = 972 if compact else 935
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{variation.width}" height="{variation.height}"
     viewBox="0 0 1000 {canvas_height:.2f}" role="img"
     aria-label="Synthetic fantasy football pitch team">
  {_defs(theme)}
  <style>{_style(theme)}</style>
  <rect width="1000" height="{canvas_height:.2f}" fill="{theme.background}"/>
  <rect width="1000" height="{header_height + 8}" fill="{theme.header}"/>
  {_metadata_markup(context, variation, theme, 'Squad canvas')}
  {_chip_markup(chips, variation, theme)}
  {shape}
  <path d="M {line_left} {pitch_top + pitch_height * .5:.2f} H {line_right}
           M {line_left} {pitch_top + pitch_height * .82:.2f} H {line_right}"
        fill="none" stroke="{theme.field_line}" stroke-opacity=".72" stroke-width="2.3"/>
  <circle cx="500" cy="{pitch_top + pitch_height * .5:.2f}" r="{pitch_height * .095:.2f}"
          fill="none" stroke="{theme.field_line}" stroke-opacity=".72" stroke-width="2.3"/>
  <path d="M 372 {pitch_top:.2f} V {pitch_top + pitch_height * .12:.2f} H 628 V {pitch_top:.2f}
           M 323 {pitch_bottom:.2f} V {pitch_bottom - pitch_height * .13:.2f} H 677 V {pitch_bottom:.2f}"
        fill="none" stroke="{theme.field_line}" stroke-opacity=".72" stroke-width="2.3"/>
  <rect x="70" y="{pitch_bottom - 12:.2f}" width="860" height="{bench_height - 18:.2f}"
        rx="18" fill="{theme.bench}" stroke="{theme.field_border}"/>
  <text x="94" y="{pitch_bottom + 28:.2f}" class="benchOrder">Bench order</text>
  {''.join(player_markup)}
  {_occlusion_markup(boxes, variation, theme)}
  <text x="930" y="{canvas_height - 16:.2f}" text-anchor="end"
        fill="{theme.secondary_text}" font-size="10.5" font-weight="650">
    SYNTHETIC · {GENERATOR_VERSION}
  </text>
</svg>
"""
    return RenderedCase(svg, extraction, visible, full, not variation.occluded_slots)


def _list_row(
    player: ImportedPlayer,
    catalog_by_id: dict[int, CatalogPlayer],
    context: RendererContext,
    variation: CorpusVariation,
    theme: Theme,
    x: float,
    y: float,
    width: float,
    height: float,
    is_captain: bool,
    is_vice: bool,
) -> tuple[str, str]:
    if player.player_id is None:
        raise ValueError("list renderer requires resolved player IDs")
    catalog_player = catalog_by_id[player.player_id]
    rendered_name = _rendered_name(player, variation, compact=True)
    fixture = context.fixtures.get(catalog_player.team_id, "TBD")
    primary, secondary = PALETTES[(catalog_player.team_id - 1) % len(PALETTES)]
    badge = ""
    if is_captain or is_vice:
        badge_text = "C" if is_captain else "V"
        badge = f"""
        <circle cx="{x + width - 30:.2f}" cy="{y + height / 2:.2f}" r="11"
                fill="{theme.header}" stroke="{theme.accent}"/>
        <text x="{x + width - 30:.2f}" y="{y + height / 2 + 4:.2f}"
              text-anchor="middle" fill="{theme.primary_text}" font-size="12"
              font-weight="800">{badge_text}</text>
        """
    return (
        f"""
        <g data-player-id="{player.player_id}" data-role="{player.squad_role}"
           data-order="{player.order}">
          <rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}"
                rx="9" fill="{theme.field_top}" stroke="{theme.field_border}"/>
          <rect x="{x:.2f}" y="{y:.2f}" width="9" height="{height:.2f}" rx="4"
                fill="{primary}"/>
          <rect x="{x + 20:.2f}" y="{y + 17:.2f}" width="47" height="24" rx="12"
                fill="{secondary}" opacity=".96"/>
          <text x="{x + 43.5:.2f}" y="{y + 33.5:.2f}" text-anchor="middle"
                fill="#27312f" font-size="10.5" font-weight="850">{player.position}</text>
          <text x="{x + 82:.2f}" y="{y + 27:.2f}" class="listName">
            {html.escape(rendered_name)}
          </text>
          <text x="{x + 82:.2f}" y="{y + 49:.2f}" class="listMeta">
            {html.escape(fixture)} · {player.squad_role} {player.order}
          </text>
          {badge}
        </g>
        """,
        rendered_name,
    )


def _render_list(
    case_id: str,
    squad: SyntheticSquad,
    catalog: tuple[CatalogPlayer, ...],
    context: RendererContext,
    variation: CorpusVariation,
    seed: int,
) -> RenderedCase:
    theme = THEMES[variation.template]
    catalog_by_id = {player.player_id: player for player in catalog}
    canvas_height = 1000 * variation.height / variation.width
    mobile = variation.viewport == "mobile"
    chips = _chip_states(seed, variation.show_chips)
    header_height = 116
    rendered_names: dict[tuple[str, int], str] = {}
    boxes: dict[tuple[str, int], tuple[float, float, float, float]] = {}
    rows: list[str] = []
    if mobile:
        row_height = 82
        gap = 12
        start_y = header_height + 38
        for index, player in enumerate(squad.players):
            x = 45
            y = start_y + index * (row_height + gap)
            markup, rendered_name = _list_row(
                player,
                catalog_by_id,
                context,
                variation,
                theme,
                x,
                y,
                910,
                row_height,
                player.player_id == squad.captain_player_id,
                player.player_id == squad.vice_captain_player_id,
            )
            slot = (player.squad_role, player.order)
            rows.append(markup)
            rendered_names[slot] = rendered_name
            boxes[slot] = (x - 2, y - 2, 914, row_height + 4)
    else:
        starters = [player for player in squad.players if player.squad_role == "starter"]
        bench = [player for player in squad.players if player.squad_role == "bench"]
        for group_index, group in enumerate((starters, bench)):
            x = 42 if group_index == 0 else 665
            width = 585 if group_index == 0 else 293
            row_height = 55 if group_index == 0 else 83
            gap = 8
            start_y = 150
            for index, player in enumerate(group):
                y = start_y + index * (row_height + gap)
                markup, rendered_name = _list_row(
                    player,
                    catalog_by_id,
                    context,
                    variation,
                    theme,
                    x,
                    y,
                    width,
                    row_height,
                    player.player_id == squad.captain_player_id,
                    player.player_id == squad.vice_captain_player_id,
                )
                slot = (player.squad_role, player.order)
                rows.append(markup)
                rendered_names[slot] = rendered_name
                boxes[slot] = (x - 2, y - 2, width + 4, row_height + 4)

    extraction, visible, full = _build_truth(
        case_id, squad, context, variation, rendered_names, chips
    )
    section_labels = (
        """
        <text x="46" y="136" class="eyebrow">STARTING XI</text>
        <text x="669" y="136" class="eyebrow">BENCH ORDER</text>
        """
        if not mobile
        else ""
    )
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{variation.width}" height="{variation.height}"
     viewBox="0 0 1000 {canvas_height:.2f}" role="img"
     aria-label="Synthetic fantasy football team list">
  {_defs(theme)}
  <style>{_style(theme)}</style>
  <rect width="1000" height="{canvas_height:.2f}" fill="{theme.background}"/>
  <rect width="1000" height="{header_height}" fill="{theme.header}"/>
  {_metadata_markup(context, variation, theme, 'Squad list')}
  <text x="500" y="76" text-anchor="middle" fill="{theme.accent}" font-size="15"
        font-weight="800">FORMATION {squad.formation}</text>
  {section_labels}
  {''.join(rows)}
  {_occlusion_markup(boxes, variation, theme)}
  <text x="948" y="{canvas_height - 18:.2f}" text-anchor="end"
        fill="{theme.secondary_text}" font-size="10.5" font-weight="650">
    SYNTHETIC · {GENERATOR_VERSION}
  </text>
</svg>
"""
    return RenderedCase(svg, extraction, visible, full, not variation.occluded_slots)


def render_case_svg(
    case_id: str,
    squad: SyntheticSquad,
    catalog: tuple[CatalogPlayer, ...],
    context: RendererContext,
    variation: CorpusVariation,
    seed: int,
) -> RenderedCase:
    if variation.template not in THEMES:
        raise ValueError(f"unknown template: {variation.template!r}")
    if variation.view == "pitch":
        return _render_pitch(case_id, squad, catalog, context, variation, seed)
    if variation.view == "list":
        return _render_list(case_id, squad, catalog, context, variation, seed)
    raise ValueError(f"unknown screenshot view: {variation.view!r}")


def _rasterize(
    svg_path: Path,
    image_path: Path,
    variation: CorpusVariation,
    seed: int,
) -> None:
    magick = shutil.which("magick")
    if magick is None:
        raise RuntimeError("ImageMagick `magick` is required to rasterize the corpus")
    with tempfile.TemporaryDirectory(prefix="fpl-corpus-") as temporary:
        temporary_path = Path(temporary)
        base = temporary_path / "base.png"
        subprocess.run(
            [magick, "-background", THEMES[variation.template].background, str(svg_path), str(base)],
            check=True,
            capture_output=True,
            text=True,
        )
        rendered = base
        if variation.damage == "clean":
            pass
        elif variation.damage == "jpeg_roundtrip":
            rendered = temporary_path / "compressed.jpg"
            subprocess.run(
                [magick, str(base), "-quality", "61", str(rendered)],
                check=True,
                capture_output=True,
                text=True,
            )
        elif variation.damage == "soft_blur":
            rendered = temporary_path / "blurred.png"
            subprocess.run(
                [magick, str(base), "-blur", "0x0.52", str(rendered)],
                check=True,
                capture_output=True,
                text=True,
            )
        elif variation.damage == "scaled_roundtrip":
            rendered = temporary_path / "scaled.png"
            subprocess.run(
                [
                    magick,
                    str(base),
                    "-resize",
                    "64%",
                    "-resize",
                    f"{variation.width}x{variation.height}!",
                    str(rendered),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        elif variation.damage == "edge_crop":
            rendered = temporary_path / "cropped.png"
            crop_width = round(variation.width * 0.94)
            crop_height = round(variation.height * 0.96)
            offset_x = (variation.width - crop_width) // 2
            offset_y = (variation.height - crop_height) // 2
            subprocess.run(
                [
                    magick,
                    str(base),
                    "-crop",
                    f"{crop_width}x{crop_height}+{offset_x}+{offset_y}",
                    "+repage",
                    "-resize",
                    f"{variation.width}x{variation.height}!",
                    str(rendered),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        elif variation.damage == "screen_photo":
            rendered = temporary_path / "photo.png"
            subprocess.run(
                [
                    magick,
                    str(base),
                    "-seed",
                    str(seed),
                    "-attenuate",
                    "0.025",
                    "+noise",
                    "Gaussian",
                    str(rendered),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            raise ValueError(f"unknown damage transform: {variation.damage!r}")
        subprocess.run(
            [
                magick,
                str(rendered),
                "-strip",
                "-define",
                "png:exclude-chunks=date,time",
                str(image_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    payload = b"".join(_json_bytes(row) + b"\n" for row in rows)
    path.write_bytes(payload)
    return _sha256(payload)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def render_corpus(
    database_path: Path,
    output_dir: Path = DEFAULT_OUTPUT,
    squad_count: int = 240,
    seed: int = 20_260_811,
) -> dict[str, Any]:
    if squad_count < 1:
        raise ValueError("squad_count must be positive")
    catalog = load_current_catalog(database_path)
    catalog_by_id = {player.player_id: player for player in catalog}
    context = load_renderer_context(database_path)
    image_dir = output_dir / "images"
    svg_dir = output_dir / "svg"
    truth_dir = output_dir / "truth"
    for path in (output_dir, image_dir, svg_dir, truth_dir):
        path.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    split_rows: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    seen_signatures = set(_locked_signatures())
    for index in range(squad_count):
        split = _split_for(index, squad_count)
        squad_id = f"corpus-v2-squad-{index + 1:04d}"
        squad = sample_legal_squad(
            catalog,
            seed=seed + index * 10_007,
            squad_id=squad_id,
            forbidden_signatures=seen_signatures,
            formation=FORMATIONS[index % len(FORMATIONS)],
        )
        seen_signatures.add(
            frozenset(
                player.player_id for player in squad.players if player.player_id is not None
            )
        )
        for variation_index, variation in enumerate(variations_for(split, index)):
            case_id = f"{squad_id}-{variation.key}"
            render_seed = seed + index * 10_007 + variation_index
            rendered = render_case_svg(
                case_id,
                squad,
                catalog,
                context,
                variation,
                render_seed,
            )
            full_validation = validate_resolved_team(rendered.full_proposal, catalog_by_id)
            visible_validation = validate_resolved_team(
                rendered.visible_proposal, catalog_by_id
            )
            if not full_validation.valid:
                raise ValueError(f"invalid private squad {case_id}: {full_validation.issues}")
            if visible_validation.valid != rendered.expected_valid:
                raise ValueError(
                    f"visible validity mismatch for {case_id}: {visible_validation.issues}"
                )

            svg_path = svg_dir / f"{case_id}.svg"
            image_path = image_dir / f"{case_id}.png"
            truth_path = truth_dir / f"{case_id}.json"
            svg_path.write_text(rendered.svg, encoding="utf-8")
            _rasterize(svg_path, image_path, variation, render_seed)
            truth = {
                "case_id": case_id,
                "extraction": rendered.extraction,
                "resolved_proposal": rendered.visible_proposal.to_dict(),
                "full_resolved_proposal": rendered.full_proposal.to_dict(),
                "expected_valid": rendered.expected_valid,
                "visible_validation": {
                    "valid": visible_validation.valid,
                    "issues": list(visible_validation.issues),
                    "inferred_formation": visible_validation.inferred_formation,
                },
                "full_validation": {
                    "valid": full_validation.valid,
                    "issues": list(full_validation.issues),
                    "inferred_formation": full_validation.inferred_formation,
                },
            }
            truth_payload = json.dumps(
                truth, indent=2, sort_keys=True, ensure_ascii=False, default=str
            ) + "\n"
            truth_path.write_text(truth_payload, encoding="utf-8")
            image_relative = image_path.relative_to(output_dir).as_posix()
            manifest = {
                "case_id": case_id,
                "split": split,
                "evaluation_axis": variation.evaluation_axis,
                "squad_id": squad.squad_id,
                "squad_signature": squad.signature,
                "formation": squad.formation,
                "viewport": variation.viewport,
                "width": variation.width,
                "height": variation.height,
                "view": variation.view,
                "template": variation.template,
                "template_holdout": variation.evaluation_axis == "template_holdout",
                "show_metadata": variation.show_metadata,
                "show_chips": variation.show_chips,
                "truncate_names": variation.truncate_names,
                "damage": variation.damage,
                "occluded_slots": [list(slot) for slot in variation.occluded_slots],
                "expected_valid": rendered.expected_valid,
                "image_path": image_relative,
                "image_sha256": _sha256(image_path.read_bytes()),
                "svg_path": svg_path.relative_to(output_dir).as_posix(),
                "svg_sha256": _sha256(rendered.svg.encode()),
                "truth_path": truth_path.relative_to(output_dir).as_posix(),
                "truth_sha256": _sha256(truth_payload.encode()),
                "source": "official-fpl-derived-synthetic",
                "rights": "structured_facts_with_original_project_expression",
                "synthetic": True,
                "generator_version": GENERATOR_VERSION,
                "generator_seed": render_seed,
                "upstream_snapshot_at": context.snapshot_at,
            }
            manifest_rows.append(manifest)
            split_rows[split].append(
                {
                    "id": case_id,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "path": image_relative},
                                {"type": "text", "text": EXTRACTION_INSTRUCTION},
                            ],
                        },
                        {
                            "role": "assistant",
                            "content": json.dumps(
                                rendered.extraction,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    "metadata": {
                        key: manifest[key]
                        for key in (
                            "split",
                            "evaluation_axis",
                            "squad_id",
                            "squad_signature",
                            "formation",
                            "viewport",
                            "view",
                            "template",
                            "template_holdout",
                            "damage",
                            "occluded_slots",
                            "expected_valid",
                            "source",
                            "rights",
                            "synthetic",
                            "generator_version",
                            "generator_seed",
                            "image_sha256",
                            "truth_sha256",
                            "upstream_snapshot_at",
                        )
                    },
                }
            )

    manifest_sha = _write_jsonl(output_dir / "manifest.jsonl", manifest_rows)
    split_files = {}
    for split, rows in split_rows.items():
        validate_sft_rows(rows)
        path = output_dir / f"sft_{split}.jsonl"
        split_files[split] = {
            "path": _display_path(path),
            "rows": len(rows),
            "sha256": _write_jsonl(path, rows),
        }
    summary = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "squads": squad_count,
        "images": len(manifest_rows),
        "source_snapshot_at": context.snapshot_at,
        "formations": dict(sorted(Counter(row["formation"] for row in manifest_rows).items())),
        "views": dict(sorted(Counter(row["view"] for row in manifest_rows).items())),
        "templates": dict(sorted(Counter(row["template"] for row in manifest_rows).items())),
        "damage": dict(sorted(Counter(row["damage"] for row in manifest_rows).items())),
        "expected_valid": dict(
            sorted(Counter(str(row["expected_valid"]).lower() for row in manifest_rows).items())
        ),
        "evaluation_axes": dict(
            sorted(Counter(row["evaluation_axis"] for row in manifest_rows).items())
        ),
        "manifest": {
            "path": _display_path(output_dir / "manifest.jsonl"),
            "sha256": manifest_sha,
        },
        "splits": split_files,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
