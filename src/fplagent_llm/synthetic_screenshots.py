from __future__ import annotations

import hashlib
import html
import json
import random
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from .benchmarks import load_screenshot_benchmark
from .contracts import CatalogPlayer, ImportedPlayer, ScreenshotTeamProposal, validate_resolved_team
from .dataset import SYSTEM_PROMPT, validate_sft_rows
from .paths import BENCHMARKS, GENERATED, ROOT
from .screenshot_import import load_current_catalog

GENERATOR_VERSION = "synthetic-screenshot-v1"
DEFAULT_OUTPUT = GENERATED / "screenshot_render_v1"
FORMATIONS = (
    "3-4-3",
    "3-5-2",
    "4-3-3",
    "4-4-2",
    "4-5-1",
    "5-2-3",
    "5-3-2",
    "5-4-1",
)
CHIP_KEYS = ("bench_boost", "triple_captain", "wildcard", "free_hit")
PALETTES = (
    ("#315f74", "#dce8ea"),
    ("#8f3f49", "#f0d9d2"),
    ("#b66a32", "#f4e4c9"),
    ("#3e6b55", "#d7e8dd"),
    ("#5b507b", "#e3def0"),
    ("#7b553d", "#eee0d5"),
    ("#256b69", "#d8ece9"),
    ("#6d465c", "#eadce4"),
)

EXTRACTION_INSTRUCTION = """Extract this FPL team screenshot into JSON only.
Return season, event, deadline, formation, players, chips and unresolved. For every player return
source_text, position, squad_role, order, is_captain and is_vice_captain. Preserve truncated names.
Number starters 1-11 and bench players 1-4 within their own role. Use null for hidden metadata or
chip states. Do not invent player IDs. The result remains provisional until validation and user
confirmation."""


@dataclass(frozen=True)
class RendererContext:
    season: str
    event: int
    deadline: str
    snapshot_at: str
    fixtures: dict[int, str]


@dataclass(frozen=True)
class SyntheticSquad:
    squad_id: str
    formation: str
    players: tuple[ImportedPlayer, ...]
    captain_player_id: int
    vice_captain_player_id: int

    @property
    def signature(self) -> str:
        player_ids = sorted(
            player.player_id for player in self.players if player.player_id is not None
        )
        payload = ",".join(str(player_id) for player_id in player_ids)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class RenderVariation:
    viewport: str
    width: int
    height: int
    show_metadata: bool
    show_chips: bool
    truncate_names: bool
    damage: str
    template: str = "canvas"


def load_renderer_context(database_path: Path, event: int = 1) -> RendererContext:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        teams = dict(
            connection.execute(
                "SELECT id, short_name FROM fpl_current_teams ORDER BY id"
            ).fetchall()
        )
        event_row = connection.execute(
            """
            SELECT season, id, deadline_time, snapshot_at
            FROM fpl_current_events
            WHERE id = ?
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            [event],
        ).fetchone()
        if event_row is None:
            raise ValueError(f"event {event} is absent from the current FPL snapshot")
        fixture_rows = connection.execute(
            """
            SELECT team_h, team_a
            FROM fpl_current_fixtures
            WHERE event = ?
            ORDER BY id
            """,
            [event],
        ).fetchall()
    finally:
        connection.close()

    fixtures: dict[int, str] = {}
    for home_id, away_id in fixture_rows:
        fixtures[int(home_id)] = f"{teams[int(away_id)]} (H)"
        fixtures[int(away_id)] = f"{teams[int(home_id)]} (A)"
    return RendererContext(
        season=str(event_row[0]),
        event=int(event_row[1]),
        deadline=str(event_row[2]),
        snapshot_at=str(event_row[3]),
        fixtures=fixtures,
    )


def _locked_signatures() -> set[frozenset[int]]:
    cases = load_screenshot_benchmark(BENCHMARKS / "screenshotbench_v1.jsonl")
    return {
        frozenset(
            player.player_id
            for player in case.expected.players
            if player.player_id is not None
        )
        for case in cases
    }


def _sample_position(
    rng: random.Random,
    candidates: list[CatalogPlayer],
    count: int,
    team_counts: Counter[int],
) -> list[CatalogPlayer] | None:
    shuffled = candidates.copy()
    rng.shuffle(shuffled)
    selected: list[CatalogPlayer] = []
    for player in shuffled:
        if team_counts[player.team_id] >= 3:
            continue
        selected.append(player)
        team_counts[player.team_id] += 1
        if len(selected) == count:
            return selected
    return None


def sample_legal_squad(
    catalog: tuple[CatalogPlayer, ...],
    seed: int,
    squad_id: str,
    forbidden_signatures: set[frozenset[int]] | None = None,
    formation: str | None = None,
) -> SyntheticSquad:
    available = tuple(player for player in catalog if player.can_select)
    by_position = {
        position: [player for player in available if player.position == position]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    forbidden = forbidden_signatures or set()

    for attempt in range(200):
        rng = random.Random(seed + attempt * 104_729)
        team_counts: Counter[int] = Counter()
        selected: dict[str, list[CatalogPlayer]] = {}
        for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
            rows = _sample_position(rng, by_position[position], count, team_counts)
            if rows is None:
                break
            selected[position] = rows
        if set(selected) != {"GK", "DEF", "MID", "FWD"}:
            continue
        signature = frozenset(player.player_id for rows in selected.values() for player in rows)
        if signature in forbidden:
            continue

        random_formation = rng.choice(FORMATIONS)
        selected_formation = formation or random_formation
        if selected_formation not in FORMATIONS:
            raise ValueError(f"unsupported formation: {selected_formation!r}")
        defenders, midfielders, forwards = (
            int(value) for value in selected_formation.split("-")
        )
        starter_rows = (
            [selected["GK"][0]]
            + selected["DEF"][:defenders]
            + selected["MID"][:midfielders]
            + selected["FWD"][:forwards]
        )
        bench_rows = [selected["GK"][1]] + [
            player
            for position in ("DEF", "MID", "FWD")
            for player in selected[position]
            if player not in starter_rows
        ]
        outfield_bench = bench_rows[1:]
        rng.shuffle(outfield_bench)
        bench_rows = [bench_rows[0], *outfield_bench]
        captain, vice = rng.sample(starter_rows, 2)
        players = tuple(
            ImportedPlayer(
                source_text=player.web_name,
                squad_role="starter",
                order=index,
                player_id=player.player_id,
                position=player.position,
                confidence=1.0,
            )
            for index, player in enumerate(starter_rows, start=1)
        ) + tuple(
            ImportedPlayer(
                source_text=player.web_name,
                squad_role="bench",
                order=index,
                player_id=player.player_id,
                position=player.position,
                confidence=1.0,
            )
            for index, player in enumerate(bench_rows, start=1)
        )
        return SyntheticSquad(
            squad_id=squad_id,
            formation=selected_formation,
            players=players,
            captain_player_id=captain.player_id,
            vice_captain_player_id=vice.player_id,
        )
    raise RuntimeError(f"could not sample a legal unique squad for {squad_id}")


def _truncate(value: str, limit: int, enabled: bool) -> str:
    if not enabled or len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip("- ") + "…"


def _jersey(player: ImportedPlayer, team_id: int, x: float, y: float, scale: float) -> str:
    primary, secondary = PALETTES[(team_id - 1) % len(PALETTES)]
    stripe = ""
    if team_id % 3 == 0:
        stripe = (
            f'<path d="M {-7 * scale} 0 L {7 * scale} 0 L {4 * scale} '
            f'{50 * scale} L {-4 * scale} {50 * scale} Z" fill="{secondary}" opacity=".9"/>'
        )
    elif team_id % 3 == 1:
        stripe = (
            f'<path d="M {-20 * scale} {21 * scale} H {20 * scale}" '
            f'stroke="{secondary}" stroke-width="{8 * scale}" opacity=".88"/>'
        )
    else:
        stripe = (
            f'<path d="M {-19 * scale} {8 * scale} L {19 * scale} '
            f'{43 * scale}" stroke="{secondary}" stroke-width="{6 * scale}" opacity=".82"/>'
        )
    return f"""
    <g transform="translate({x:.2f} {y:.2f})" filter="url(#softShadow)">
      <path d="M {-18 * scale} 0 L {-38 * scale} {13 * scale} L {-29 * scale} {31 * scale}
               L {-20 * scale} {25 * scale} L {-16 * scale} {55 * scale} L {16 * scale} {55 * scale}
               L {20 * scale} {25 * scale} L {29 * scale} {31 * scale} L {38 * scale} {13 * scale}
               L {18 * scale} 0 L {9 * scale} {7 * scale} L {-9 * scale} {7 * scale} Z"
            fill="{primary}" stroke="rgba(255,255,255,.42)" stroke-width="{1.2 * scale}"/>
      {stripe}
      <path d="M {-9 * scale} {7 * scale} Q 0 {17 * scale} {9 * scale} {7 * scale}"
            fill="none" stroke="{secondary}" stroke-width="{2.2 * scale}"/>
    </g>
    """


def _player_card(
    player: ImportedPlayer,
    catalog_by_id: dict[int, CatalogPlayer],
    context: RendererContext,
    variation: RenderVariation,
    x: float,
    y: float,
    card_width: float,
    compact: bool = False,
    bench_label: str | None = None,
    is_captain: bool = False,
    is_vice: bool = False,
) -> tuple[str, str]:
    if player.player_id is None:
        raise ValueError("synthetic renderer requires resolved player IDs")
    catalog_player = catalog_by_id[player.player_id]
    mobile = variation.viewport == "mobile"
    scale = 1.22 if mobile and not compact else 0.9 if compact else 1.0
    name_limit = 13 if compact else 14 if mobile else 16
    rendered_name = _truncate(player.source_text, name_limit, variation.truncate_names)
    fixture = context.fixtures.get(catalog_player.team_id, "TBD")
    jersey_y = y + (18 if compact else 14)
    jersey = _jersey(player, catalog_player.team_id, x, jersey_y, scale)
    label_height = 52 if mobile and not compact else 43
    label_y = jersey_y + 52 * scale
    font_size = 16 if mobile and not compact else 13.2 if compact else 14.5
    fixture_size = font_size - 1.5
    radius = 7
    badge = ""
    if is_captain or is_vice:
        badge_text = "C" if is_captain else "V"
        badge_x = x - 30 * scale
        badge_y = jersey_y + 4
        badge = f"""
        <circle cx="{badge_x:.2f}" cy="{badge_y:.2f}" r="10.5" fill="#1b2025"
                stroke="#f3f1e8" stroke-width="1.4"/>
        <text x="{badge_x:.2f}" y="{badge_y + 4.2:.2f}" text-anchor="middle"
              class="badge">{badge_text}</text>
        """
    order_label = ""
    if bench_label:
        order_label = f"""
        <text x="{x:.2f}" y="{y - 4:.2f}" text-anchor="middle" class="benchOrder">
          {html.escape(bench_label)}
        </text>
        """
    rendered = f"""
    <g data-player-id="{player.player_id}" data-role="{player.squad_role}"
       data-order="{player.order}">
      {order_label}
      {jersey}
      {badge}
      <rect x="{x - card_width / 2:.2f}" y="{label_y:.2f}" width="{card_width:.2f}"
            height="{label_height}" rx="{radius}" fill="#f5f2eb" stroke="#26363a"
            stroke-width="1.2"/>
      <text x="{x:.2f}" y="{label_y + font_size + 5:.2f}" text-anchor="middle"
            class="playerName" font-size="{font_size}">{html.escape(rendered_name)}</text>
      <text x="{x:.2f}" y="{label_y + label_height - 9:.2f}" text-anchor="middle"
            class="fixture" font-size="{fixture_size}">{html.escape(fixture)}</text>
    </g>
    """
    return rendered, rendered_name


def _row_positions(count: int, width: float, pitch_top: float, y: float) -> list[tuple[float, float]]:
    left = 105 + max(0.0, (y - pitch_top) * -0.02)
    right = width - left
    if count == 1:
        return [(width / 2, y)]
    return [
        (left + index * (right - left) / (count - 1), y) for index in range(count)
    ]


def _chip_states(seed: int, visible: bool) -> dict[str, str | None]:
    if not visible:
        return {key: None for key in CHIP_KEYS}
    states = ("available", "unavailable", "played")
    return {key: states[(seed + index) % len(states)] for index, key in enumerate(CHIP_KEYS)}


def render_svg(
    squad: SyntheticSquad,
    catalog: tuple[CatalogPlayer, ...],
    context: RendererContext,
    variation: RenderVariation,
    seed: int,
) -> tuple[str, dict[str, Any], ScreenshotTeamProposal]:
    catalog_by_id = {player.player_id: player for player in catalog}
    canvas_width = 1000.0
    canvas_height = canvas_width * variation.height / variation.width
    mobile = variation.viewport == "mobile"
    header_height = 290 if mobile and variation.show_chips else 148 if mobile else 82
    pitch_top = header_height + 24
    bench_height = 260 if mobile else 208
    pitch_bottom = canvas_height - bench_height - 26
    pitch_height = pitch_bottom - pitch_top
    card_width = 142 if mobile else 112
    chips = _chip_states(seed, variation.show_chips)

    starters = [player for player in squad.players if player.squad_role == "starter"]
    bench = sorted(
        (player for player in squad.players if player.squad_role == "bench"),
        key=lambda player: player.order,
    )
    starter_by_position = {
        position: [player for player in starters if player.position == position]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    row_y = {
        "GK": pitch_top + pitch_height * 0.09,
        "DEF": pitch_top + pitch_height * 0.31,
        "MID": pitch_top + pitch_height * 0.55,
        "FWD": pitch_top + pitch_height * 0.77,
    }

    player_markup: list[str] = []
    rendered_names: dict[tuple[str, int], str] = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = starter_by_position[position]
        for player, (x, y) in zip(
            rows,
            _row_positions(len(rows), canvas_width, pitch_top, row_y[position]),
            strict=True,
        ):
            markup, rendered_name = _player_card(
                player,
                catalog_by_id,
                context,
                variation,
                x,
                y,
                card_width,
                is_captain=player.player_id == squad.captain_player_id,
                is_vice=player.player_id == squad.vice_captain_player_id,
            )
            player_markup.append(markup)
            rendered_names[(player.squad_role, player.order)] = rendered_name

    bench_y = pitch_bottom + 58
    bench_card_width = 155 if mobile else 120
    bench_positions = _row_positions(4, canvas_width, pitch_top, bench_y)
    for player, (x, y) in zip(bench, bench_positions, strict=True):
        markup, rendered_name = _player_card(
            player,
            catalog_by_id,
            context,
            variation,
            x,
            y,
            bench_card_width,
            compact=not mobile,
            bench_label=f"{player.order}. {player.position}",
        )
        player_markup.append(markup)
        rendered_names[(player.squad_role, player.order)] = rendered_name

    metadata = ""
    if variation.show_metadata:
        metadata = f"""
        <text x="52" y="51" class="eyebrow">{html.escape(context.season)}</text>
        <text x="500" y="53" text-anchor="middle" class="title">Pick team</text>
        <text x="948" y="50" text-anchor="end" class="meta">GW {context.event}</text>
        <text x="948" y="72" text-anchor="end" class="meta small">
          Deadline {html.escape(context.deadline[:16].replace('T', ' '))}
        </text>
        """
    else:
        metadata = '<text x="52" y="54" class="title">Pick team</text>'

    chip_markup = ""
    if variation.show_chips:
        chip_labels = (
            ("Bench boost", chips["bench_boost"]),
            ("Triple captain", chips["triple_captain"]),
            ("Wildcard", chips["wildcard"]),
            ("Free hit", chips["free_hit"]),
        )
        items = []
        for index, (label, state) in enumerate(chip_labels):
            x = 44 + index * 239
            items.append(
                f"""
                <g>
                  <rect x="{x}" y="112" width="218" height="102" rx="13"
                        fill="#252b30" stroke="#48545a"/>
                  <text x="{x + 18}" y="146" class="chipLabel">{label}</text>
                  <text x="{x + 18}" y="181" class="chipState">{state}</text>
                </g>
                """
            )
        chip_markup = "".join(items)

    extraction_players = []
    proposal_players = []
    for player in squad.players:
        slot = (player.squad_role, player.order)
        rendered_name = rendered_names[slot]
        extraction_players.append(
            {
                "source_text": rendered_name,
                "position": player.position,
                "squad_role": player.squad_role,
                "order": player.order,
                "is_captain": player.player_id == squad.captain_player_id,
                "is_vice_captain": player.player_id == squad.vice_captain_player_id,
            }
        )
        proposal_players.append(
            ImportedPlayer(
                source_text=rendered_name,
                squad_role=player.squad_role,
                order=player.order,
                player_id=player.player_id,
                position=player.position,
                confidence=1.0,
            )
        )

    extraction = {
        "season": context.season if variation.show_metadata else None,
        "event": context.event if variation.show_metadata else None,
        "deadline": context.deadline if variation.show_metadata else None,
        "formation": squad.formation,
        "players": extraction_players,
        "chips": chips,
        "unresolved": [],
    }
    proposal = ScreenshotTeamProposal(
        schema_version="screenshot-team-v1",
        source_image_id=f"{squad.squad_id}-{variation.viewport}",
        season=context.season,
        event=context.event if variation.show_metadata else None,
        deadline=(
            datetime.fromisoformat(context.deadline)
            if variation.show_metadata
            else None
        ),
        formation=squad.formation,
        players=tuple(proposal_players),
        captain_player_id=squad.captain_player_id,
        vice_captain_player_id=squad.vice_captain_player_id,
        bench_order=tuple(player.player_id for player in bench if player.player_id is not None),
        chips={key: value if value is not None else "not_visible" for key, value in chips.items()},
        unresolved=(),
    )

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{variation.width}" height="{variation.height}"
     viewBox="0 0 {canvas_width:.0f} {canvas_height:.2f}" role="img"
     aria-label="Synthetic fantasy football team selection">
  <defs>
    <linearGradient id="pitch" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#176f55"/>
      <stop offset="1" stop-color="#0d6049"/>
    </linearGradient>
    <linearGradient id="bench" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#d6e8dd"/>
      <stop offset="1" stop-color="#b8d4c4"/>
    </linearGradient>
    <filter id="softShadow" x="-30%" y="-30%" width="160%" height="170%">
      <feDropShadow dx="0" dy="5" stdDeviation="5" flood-color="#102c28" flood-opacity=".28"/>
    </filter>
  </defs>
  <style>
    text {{ font-family: "Noto Sans", "DejaVu Sans", sans-serif; }}
    .title {{ fill: #f4f1e9; font-size: 24px; font-weight: 700; letter-spacing: -.4px; }}
    .eyebrow {{ fill: #9fb3ac; font-size: 15px; font-weight: 700; letter-spacing: 1.2px; }}
    .meta {{ fill: #f4f1e9; font-size: 15px; font-weight: 650; }}
    .meta.small {{ fill: #9fb3ac; font-size: 11.5px; font-weight: 500; }}
    .playerName {{ fill: #2d1b35; font-weight: 750; }}
    .fixture {{ fill: #334c4e; font-weight: 650; }}
    .badge {{ fill: #f3f1e8; font-size: 12px; font-weight: 800; }}
    .benchOrder {{ fill: #26343a; font-size: 13px; font-weight: 750; }}
    .chipLabel {{ fill: #f4f1e9; font-size: 15px; font-weight: 700; }}
    .chipState {{ fill: #abc7b7; font-size: 13px; font-weight: 600; text-transform: uppercase; }}
  </style>
  <rect width="1000" height="{canvas_height:.2f}" fill="#171c20"/>
  <rect x="0" y="0" width="1000" height="{header_height + 8}" fill="#1c2227"/>
  {metadata}
  {chip_markup}
  <path d="M 112 {pitch_top:.2f} H 888 L 982 {pitch_bottom:.2f} H 18 Z"
        fill="url(#pitch)" stroke="#5aa384" stroke-width="2"/>
  <path d="M 112 {pitch_top + pitch_height * .18:.2f} H 888
           M 65 {pitch_top + pitch_height * .5:.2f} H 935
           M 31 {pitch_top + pitch_height * .82:.2f} H 969"
        fill="none" stroke="#e4eee7" stroke-opacity=".72" stroke-width="2.4"/>
  <circle cx="500" cy="{pitch_top + pitch_height * .5:.2f}" r="{pitch_height * .095:.2f}"
          fill="none" stroke="#e4eee7" stroke-opacity=".72" stroke-width="2.4"/>
  <path d="M 372 {pitch_top:.2f} V {pitch_top + pitch_height * .12:.2f} H 628 V {pitch_top:.2f}
           M 323 {pitch_bottom:.2f} V {pitch_bottom - pitch_height * .13:.2f} H 677 V {pitch_bottom:.2f}"
        fill="none" stroke="#e4eee7" stroke-opacity=".72" stroke-width="2.4"/>
  <rect x="72" y="{pitch_bottom - 14:.2f}" width="856" height="{bench_height - 18:.2f}"
        rx="18" fill="url(#bench)" stroke="#d9eee2" stroke-opacity=".7"/>
  <text x="96" y="{pitch_bottom + 28:.2f}" class="benchOrder">Bench order</text>
  {''.join(player_markup)}
  <text x="926" y="{canvas_height - 18:.2f}" text-anchor="end"
        fill="#6e827a" font-size="10.5" font-weight="650">SYNTHETIC · {GENERATOR_VERSION}</text>
</svg>
"""
    return svg, extraction, proposal


def _sha256_bytes(payload: bytes) -> str:
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
    return _sha256_bytes(payload)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _rasterize(svg_path: Path, image_path: Path, damage: str) -> None:
    magick = shutil.which("magick")
    if magick is None:
        raise RuntimeError("ImageMagick `magick` is required to rasterize synthetic screenshots")
    with tempfile.TemporaryDirectory(prefix="fpl-render-") as temporary:
        base_png = Path(temporary) / "base.png"
        subprocess.run(
            [magick, "-background", "#171c20", str(svg_path), str(base_png)],
            check=True,
            capture_output=True,
            text=True,
        )
        rendered = base_png
        if damage == "clean":
            pass
        elif damage == "jpeg_roundtrip":
            jpeg = Path(temporary) / "compressed.jpg"
            subprocess.run(
                [magick, str(base_png), "-quality", "63", str(jpeg)],
                check=True,
                capture_output=True,
                text=True,
            )
            rendered = jpeg
        elif damage == "soft_blur":
            blurred = Path(temporary) / "blurred.png"
            subprocess.run(
                [magick, str(base_png), "-blur", "0x0.45", str(blurred)],
                check=True,
                capture_output=True,
                text=True,
            )
            rendered = blurred
        else:
            raise ValueError(f"unknown screenshot damage: {damage!r}")
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


def _split_for(index: int, squad_count: int) -> str:
    if squad_count == 1:
        return "train"
    if squad_count == 2:
        return "train" if index == 0 else "test"
    if index == squad_count - 1:
        return "test"
    if index == squad_count - 2:
        return "validation"
    return "train"


def _variations(index: int) -> tuple[RenderVariation, ...]:
    return (
        RenderVariation(
            viewport="mobile",
            width=1042,
            height=2048,
            show_metadata=True,
            show_chips=index % 2 == 0,
            truncate_names=index % 3 != 1,
            damage="jpeg_roundtrip" if index % 3 == 1 else "clean",
        ),
        RenderVariation(
            viewport="desktop",
            width=988,
            height=919,
            show_metadata=index % 3 != 2,
            show_chips=False,
            truncate_names=index % 2 == 0,
            damage="soft_blur" if index % 4 == 3 else "clean",
        ),
    )


def render_dataset(
    database_path: Path,
    output_dir: Path = DEFAULT_OUTPUT,
    squad_count: int = 8,
    seed: int = 20_260_804,
) -> dict[str, Any]:
    if squad_count < 1:
        raise ValueError("squad_count must be positive")
    catalog = load_current_catalog(database_path)
    catalog_by_id = {player.player_id: player for player in catalog}
    context = load_renderer_context(database_path)
    forbidden = _locked_signatures()
    image_dir = output_dir / "images"
    truth_dir = output_dir / "truth"
    svg_dir = output_dir / "svg"
    for path in (output_dir, image_dir, truth_dir, svg_dir):
        path.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    sft_by_split: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    seen_signatures = set(forbidden)
    for index in range(squad_count):
        squad_id = f"synthetic-squad-{index + 1:04d}"
        squad = sample_legal_squad(
            catalog,
            seed=seed + index * 10_007,
            squad_id=squad_id,
            forbidden_signatures=seen_signatures,
            formation=FORMATIONS[(index + 1) % len(FORMATIONS)],
        )
        signature_ids = frozenset(
            player.player_id for player in squad.players if player.player_id is not None
        )
        seen_signatures.add(signature_ids)
        split = _split_for(index, squad_count)
        for variation_index, variation in enumerate(_variations(index)):
            case_id = f"{squad_id}-{variation.viewport}"
            render_seed = seed + index * 10_007 + variation_index
            svg, extraction, proposal = render_svg(
                squad,
                catalog,
                context,
                variation,
                render_seed,
            )
            validation = validate_resolved_team(proposal, catalog_by_id)
            if not validation.valid:
                raise ValueError(f"generated invalid team {case_id}: {validation.issues}")

            svg_path = svg_dir / f"{case_id}.svg"
            image_path = image_dir / f"{case_id}.png"
            truth_path = truth_dir / f"{case_id}.json"
            svg_path.write_text(svg, encoding="utf-8")
            _rasterize(svg_path, image_path, variation.damage)
            truth = {
                "case_id": case_id,
                "extraction": extraction,
                "resolved_proposal": proposal.to_dict(),
                "validation": {
                    "valid": validation.valid,
                    "issues": list(validation.issues),
                    "inferred_formation": validation.inferred_formation,
                },
            }
            truth_payload = json.dumps(
                truth, indent=2, ensure_ascii=False, sort_keys=True, default=str
            ) + "\n"
            truth_path.write_text(truth_payload, encoding="utf-8")
            image_relative = image_path.relative_to(output_dir).as_posix()
            manifest_row = {
                "case_id": case_id,
                "split": split,
                "squad_id": squad.squad_id,
                "squad_signature": squad.signature,
                "formation": squad.formation,
                "viewport": variation.viewport,
                "width": variation.width,
                "height": variation.height,
                "template": variation.template,
                "show_metadata": variation.show_metadata,
                "show_chips": variation.show_chips,
                "truncate_names": variation.truncate_names,
                "damage": variation.damage,
                "image_path": image_relative,
                "image_sha256": _sha256_bytes(image_path.read_bytes()),
                "svg_path": svg_path.relative_to(output_dir).as_posix(),
                "svg_sha256": _sha256_bytes(svg.encode()),
                "truth_path": truth_path.relative_to(output_dir).as_posix(),
                "truth_sha256": _sha256_bytes(truth_payload.encode()),
                "source": "official-fpl-derived-synthetic",
                "rights": "structured_facts_with_original_project_expression",
                "synthetic": True,
                "generator_version": GENERATOR_VERSION,
                "generator_seed": render_seed,
                "upstream_snapshot_at": context.snapshot_at,
            }
            manifest_rows.append(manifest_row)
            sft_by_split[split].append(
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
                                extraction,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    "metadata": {
                        key: manifest_row[key]
                        for key in (
                            "split",
                            "squad_id",
                            "squad_signature",
                            "viewport",
                            "template",
                            "damage",
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

    manifest_sha256 = _write_jsonl(output_dir / "manifest.jsonl", manifest_rows)
    split_files = {}
    for split, rows in sft_by_split.items():
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
        "formations": dict(sorted(Counter(row["formation"] for row in manifest_rows).items())),
        "source_snapshot_at": context.snapshot_at,
        "manifest": {
            "path": _display_path(output_dir / "manifest.jsonl"),
            "sha256": manifest_sha256,
        },
        "splits": split_files,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
