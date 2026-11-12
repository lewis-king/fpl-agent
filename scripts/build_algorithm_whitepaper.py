"""Build the canonical FPLAgent algorithm whitepaper as one self-contained HTML file.

The Markdown document remains the source of truth. This builder adds editorial styling,
artifact-backed diagrams and embedded fonts without introducing a runtime dependency on a
Markdown package or the network.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
SOURCE = REPORTS / "fplagent-algorithm-technical-whitepaper.md"
OUTPUT = REPORTS / "fplagent-algorithm-technical-whitepaper-standalone.html"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def font_data(name: str) -> str:
    encoded = base64.b64encode((REPORTS / "assets" / name).read_bytes()).decode("ascii")
    return f"data:font/ttf;base64,{encoded}"


def slugify(value: str) -> str:
    clean = re.sub(r"[`*_]", "", value.lower())
    clean = re.sub(r"[^a-z0-9]+", "-", clean).strip("-")
    return clean or "section"


def inline(value: str) -> str:
    """Render the intentionally small inline-Markdown subset used by the paper."""

    code_tokens: list[str] = []

    def save_code(match: re.Match[str]) -> str:
        code_tokens.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00CODE{len(code_tokens) - 1}\x00"

    rendered = re.sub(r"`([^`]+)`", save_code, value)
    rendered = html.escape(rendered)
    rendered = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: (
            f'<a href="{html.escape(match.group(2), quote=True)}">{match.group(1)}</a>'
        ),
        rendered,
    )
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered)
    for index, token in enumerate(code_tokens):
        rendered = rendered.replace(f"\x00CODE{index}\x00", token)
    return rendered


@dataclass
class RenderedMarkdown:
    body: str
    headings: list[tuple[int, str, str]]


def render_markdown(source: str, visuals: dict[str, str]) -> RenderedMarkdown:
    """Render the paper's constrained block-level Markdown into semantic HTML."""

    lines = source.splitlines()
    output: list[str] = []
    headings: list[tuple[int, str, str]] = []
    used_ids: set[str] = set()
    index = 0
    in_section = False

    def unique_id(title: str) -> str:
        base = slugify(title)
        candidate = base
        suffix = 2
        while candidate in used_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used_ids.add(candidate)
        return candidate

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            index += 1
            continue

        visual_match = re.fullmatch(r"<!-- VISUAL:([a-z-]+) -->", stripped)
        if visual_match:
            output.append(visuals[visual_match.group(1)])
            index += 1
            continue

        fence = re.match(r"^```([^`]*)$", stripped)
        if fence:
            language = fence.group(1).strip()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != "```":
                code_lines.append(lines[index])
                index += 1
            index += 1
            formula_class = " formula" if language == "math" else ""
            label = "MODEL EQUATION" if language == "math" else (language.upper() or "CODE")
            output.append(
                f'<figure class="code-panel{formula_class}"><figcaption>{label}</figcaption>'
                f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre></figure>"
            )
            continue

        heading = re.match(r"^(#{2,4})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            section_id = unique_id(title)
            if level == 2:
                if in_section:
                    output.append("</section>")
                output.append(f'<section class="paper-section" id="{section_id}">')
                in_section = True
            heading_id = f"{section_id}-title" if level == 2 else section_id
            output.append(
                f'<h{level} id="{heading_id}"><a class="heading-link" '
                f'href="#{section_id}">{inline(title)}</a></h{level}>'
            )
            headings.append((level, title, section_id))
            index += 1
            continue

        if stripped.startswith(">"):
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip()[1:].strip())
                index += 1
            output.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
            continue

        if (
            index + 1 < len(lines)
            and "|" in stripped
            and re.fullmatch(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*", lines[index + 1])
        ):
            headers = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            head = "".join(f"<th>{inline(cell)}</th>" for cell in headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            output.append(
                '<div class="table-scroll"><table><thead><tr>'
                + head
                + "</tr></thead><tbody>"
                + body
                + "</tbody></table></div>"
            )
            continue

        list_match = re.match(r"^\s*(-|\d+\.)\s+(.+)$", raw)
        if list_match:
            ordered = list_match.group(1) != "-"
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while index < len(lines):
                item_match = re.match(r"^\s*(-|\d+\.)\s+(.+)$", lines[index])
                if not item_match or (item_match.group(1) != "-") != ordered:
                    break
                item_parts = [item_match.group(2).strip()]
                index += 1
                while (
                    index < len(lines)
                    and lines[index].strip()
                    and not re.match(r"^\s*(-|\d+\.)\s+", lines[index])
                    and not re.match(r"^#{2,4}\s+", lines[index])
                    and "<!-- VISUAL:" not in lines[index]
                ):
                    item_parts.append(lines[index].strip())
                    index += 1
                items.append(" ".join(item_parts))
            output.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>")
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines) and lines[index].strip():
            next_line = lines[index].strip()
            if (
                re.match(r"^(#{2,4})\s+", next_line)
                or next_line.startswith(("```", ">"))
                or re.match(r"^\s*(-|\d+\.)\s+", lines[index])
                or "<!-- VISUAL:" in next_line
                or (
                    index + 1 < len(lines)
                    and "|" in next_line
                    and re.fullmatch(
                        r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*",
                        lines[index + 1],
                    )
                )
            ):
                break
            paragraph.append(next_line)
            index += 1
        output.append(f"<p>{inline(' '.join(paragraph))}</p>")

    if in_section:
        output.append("</section>")
    return RenderedMarkdown(body="\n".join(output), headings=headings)


def captain_name(synthesis: dict) -> str:
    return next(
        player["name"]
        for player in synthesis["decision"]["squad"]["starters"]
        if player["captain"]
    )


def pipeline_visual(robust: dict, horizon: dict, synthesis: dict, forecast: dict) -> str:
    funnel = robust["funnel"]
    player_count = horizon["holdout_diagnostics"]["players"]
    event_count = len(horizon["events"])
    decision = synthesis["decision"]
    captain = captain_name(synthesis)
    stages = [
        ("01", "Historical rows", f"{forecast['training_rows']:,}", "deadline-safe player-GWs"),
        ("02", "Forecast grid", f"{player_count} × {event_count}", "players across events"),
        ("03", "Search universe", f"{funnel['combined_universe']:,}", "legal squads"),
        ("04", "Robust holdout", f"{funnel['finalists']}", "five-week finalists"),
        ("05", "Horizon holdout", f"{horizon['funnel']['deep_finalists']}", "eight-week finalists"),
        (
            "06",
            "Joint synthesis",
            str(synthesis["candidate_coverage"]["common_finalists"]),
            "shared finalists",
        ),
        ("07", "Decision", decision["formation"].replace("-", "–"), f"{captain} captain"),
    ]
    cards = "".join(
        f'<div class="flow-card"><span>{number}</span><div><small>{label}</small>'
        f"<strong>{value}</strong><em>{note}</em></div></div>"
        for number, label, value, note in stages
    )
    return (
        '<figure class="major-visual pipeline-visual"><div class="visual-kicker">DECISION PIPELINE</div>'
        '<div class="flow-line" aria-hidden="true"></div><div class="flow-grid">'
        + cards
        + '</div><figcaption>Seven independently auditable stages turn public observations into one '
        "versioned squad receipt.</figcaption></figure>"
    )


def funnel_visual(robust: dict, synthesis: dict) -> str:
    funnel = robust["funnel"]
    stages = [
        ("Generated", funnel["combined_universe"], "Local, MILP and evolution"),
        ("Proxy field", funnel["discovery_candidates"], "40 deterministic views"),
        ("Residual", funnel["discovery_candidates"], "2,000 worlds"),
        ("Component", funnel["shortlist"], "5,000 worlds"),
        ("Deep holdout", funnel["finalists"], "25k base + 25k stress"),
        (
            "Synthesized",
            synthesis["candidate_coverage"]["common_finalists"],
            "Both audit families",
        ),
        ("Selected", 1, "Decision receipt"),
    ]
    maximum = stages[0][1]
    rows = []
    for rank, (label, value, note) in enumerate(stages):
        width = max(7.0, 100 * (1 - rank * 0.13))
        rows.append(
            f'<div class="funnel-row" style="--funnel-width:{width:.1f}%">'
            f'<div class="funnel-bar"><span>{label}</span><strong>{value:,}</strong></div>'
            f"<small>{note}</small></div>"
        )
    return (
        '<figure class="major-visual funnel-visual"><div class="visual-kicker">PROGRESSIVE COMPUTE</div>'
        '<div class="funnel-grid">'
        + "".join(rows)
        + f'</div><figcaption>Only {funnel["finalists"] / maximum:.4%} of the generated universe '
        "reaches the untouched deep five-week holdout.</figcaption></figure>"
    )


def synthesis_visual(synthesis: dict) -> str:
    selected = synthesis["selected_family_metrics"]
    five = selected["five_week_robust"]["robust_regret"]
    eight = selected["eight_week_horizon"]["robust_regret"]
    final = synthesis["decision"]["synthesis_regret"]
    challenger = synthesis["long_horizon_challenger"]
    challenger_ranking = next(
        row
        for row in synthesis["ranking"]
        if row["candidate_id"] == challenger["candidate_id"]
    )
    boundary = next(
        interval
        for interval in synthesis["horizon_weight_champion_intervals"]
        if interval["candidate_id"] == synthesis["decision"]["candidate_id"]
    )
    return f"""
<figure class="major-visual synthesis-visual">
  <div class="visual-kicker">TWO-FAMILY CHECK AND BALANCE</div>
  <div class="synthesis-grid">
    <article class="family-card family-five"><span>FIVE-WEEK FAMILY</span><strong>{five:.3f}</strong>
      <p>Scoring calibration, components, transfers and high-goal stress.</p></article>
    <div class="synthesis-node"><span>80% family mean</span><i>+</i><span>20% worst family</span>
      <strong>{final:.3f}</strong><em>lower regret wins</em></div>
    <article class="family-card family-eight"><span>EIGHT-WEEK FAMILY</span><strong>{eight:.3f}</strong>
      <p>Decay, late fixtures, transfer timing, fixed and banked paths.</p></article>
  </div>
  <div class="boundary-track"><span style="width:{boundary['upper'] * 100:.1f}%"></span>
    <b>Current squad remains champion through {boundary['upper'] * 100:.1f}% horizon weight</b>
  </div>
  <div class="comparison-strip"><span>Selected <b>{synthesis['decision']['candidate_id']} · {final:.3f}</b></span>
    <span>Horizon challenger <b>{challenger['candidate_id']} · {challenger_ranking['synthesis_regret']:.3f}</b></span></div>
  <figcaption>The winner is the squad least brittle across model families—not the leader of a
  single preferred forecast.</figcaption>
</figure>"""


def team_visual(synthesis: dict) -> str:
    decision_id = synthesis["decision"]["candidate_id"]
    squad = synthesis["decision"]["squad"]
    starters = squad["starters"]
    groups = {position: [] for position in ("GK", "DEF", "MID", "FWD")}
    for player in starters:
        badge = " C" if player["captain"] else " V" if player["vice_captain"] else ""
        groups[player["position"]].append(
            f'<div class="shirt"><span>{html.escape(player["name"])}{badge}</span>'
            f'<small>{html.escape(player["team"])} · £{player["price"]:.1f}m</small></div>'
        )
    rows = "".join(
        f'<div class="pitch-row row-{position.lower()}">{"".join(groups[position])}</div>'
        for position in ("GK", "DEF", "MID", "FWD")
    )
    bench = "".join(
        f'<div><b>{order}</b><span>{html.escape(player["name"])}</span>'
        f'<small>{player["position"]} · £{player["price"]:.1f}m</small></div>'
        for order, player in enumerate(squad["bench"], 1)
    )
    return f"""
<figure class="major-visual team-visual">
  <div class="visual-kicker">CURRENT GW1 RECEIPT · {decision_id}</div>
  <div class="pitch"><div class="centre-circle"></div>{rows}</div>
  <div class="bench"><strong>BENCH ORDER</strong>{bench}</div>
  <div class="team-meta"><span>£{squad['budget_spent']:.1f}m spent</span><span>£{squad['bank']:.1f}m bank</span>
    <span>{squad['formation']}</span><span>Watkins role watch</span></div>
  <figcaption>The current 15 passed the atomic publication gate. It remains conditional on a final
  attributable role check and a checksum-coherent refresh before the deadline.</figcaption>
</figure>"""


def validation_visual(
    forecast: dict,
    component: dict,
    bps: dict,
    appearance: dict,
    robust: dict,
    readiness: dict,
) -> str:
    gate = forecast["backtest_gate"]
    blend = component["blend_selection"]
    cards = [
        ("DATA", "22 / 22", "leakage & integrity contracts"),
        ("XGBOOST", f"{gate['mae_wins_vs_form5']} / {gate['slices']}", "MAE slices beat form5"),
        ("SHORTLIST", f"+{gate['mean_top_k_lift']:.3f}", "actual-point lift per player-GW"),
        ("COMPONENTS", f"{blend['selected_raw_weight']:.0%}", "raw-model weight after freeze"),
        ("BONUS", f"{bps['control']['fixtures']} / {bps['control']['fixtures']}", "historical control fixtures exact"),
        ("APPEARANCE", ", ".join(appearance["promoted_positions"]), "only position clearing both slices"),
        (
            "ROBUSTNESS",
            f"{len(robust['decision_sensitivity']['leave_one_scenario_out'])} / 8",
            "leave-one-scenario-out wins",
        ),
        (
            "READINESS",
            f"{readiness['summary']['production_pass']} / {readiness['summary']['production_total']}",
            "production gates; SOTA remains unproven",
        ),
    ]
    body = "".join(
        f'<article><span>{label}</span><strong>{value}</strong><p>{note}</p></article>'
        for label, value, note in cards
    )
    return (
        '<figure class="major-visual validation-visual"><div class="visual-kicker">EVIDENCE GATES</div>'
        f'<div class="validation-grid">{body}</div><figcaption>Complexity enters production only '
        "after it beats the frozen baseline on a declared, time-forward acceptance gate.</figcaption></figure>"
    )


def episode_visual(candidate_universe: int) -> str:
    """Embed the film poster while keeping the MP4 as an offline sibling artifact."""

    poster_path = REPORTS / "fplagent-decision-episode-poster.png"
    video_path = REPORTS / "fplagent-decision-episode.mp4"
    if not poster_path.exists() or not video_path.exists():
        raise RuntimeError("Build the decision episode and poster before publishing the whitepaper")
    poster = base64.b64encode(poster_path.read_bytes()).decode("ascii")
    return (
        '<figure class="major-visual episode-visual">'
        '<div class="visual-kicker">COMPANION DECISION FILM · 02:20</div>'
        '<div class="episode-layout"><div class="episode-copy">'
        f'<span class="episode-number">{candidate_universe:,} → 1</span>'
        '<h3>The squad knockout.</h3>'
        f'<p>Watch real named squads enter a visible tournament: {candidate_universe:,} legal builds become 10,000, '
        'then 512, then 64. Survivors face 25,000 correlated worlds, horizon challengers, an eight-squad '
        'bracket and three publication vetoes. Composition-derived call signs make each contender '
        'recognisable; checksum IDs remain underneath as the audit receipt.</p>'
        '<a class="episode-link" href="fplagent-decision-episode.mp4">Play the 1080p film <span>↗</span></a>'
        '</div><video controls preload="none" '
        f'poster="data:image/png;base64,{poster}" aria-label="FPLAgent squad knockout film">'
        '<source src="fplagent-decision-episode.mp4" type="video/mp4">'
        '<a href="fplagent-decision-episode.mp4">Download the decision film.</a>'
        '</video></div><figcaption>The film is generated from the same current machine artifacts '
        'as this paper. Its original 128 BPM tournament score changes by round and synchronises '
        'elimination impacts, finals tension and the champion payoff without third-party media.</figcaption></figure>'
    )


def build() -> str:
    markdown = SOURCE.read_text(encoding="utf-8")
    robust = read_json(DATA / "model" / "robust_search_v2_global" / "results.json")
    horizon = read_json(DATA / "model" / "horizon_audit_v1" / "results.json")
    synthesis = read_json(DATA / "model" / "gw1_decision_synthesis_v1" / "results.json")
    forecast = read_json(DATA / "model" / "artifacts" / "forecast_v2" / "metrics.json")
    component = read_json(DATA / "model" / "component_backtest_v1" / "metrics.json")
    bps = read_json(DATA / "model" / "bps_2026_27_v1" / "metrics.json")
    appearance = read_json(DATA / "model" / "appearance_audit_v1" / "metrics.json")
    readiness = read_json(DATA / "model" / "sota_readiness_v1" / "results.json")
    pipeline = read_json(DATA / "manifests" / "fpl-gw1-deadline-pipeline.json")
    bench = read_json(DATA / "model" / "bench_allocation_audit_v2" / "results.json")
    market = read_json(DATA / "model" / "market_feature_v1" / "results.json")
    external = read_json(DATA / "model" / "external_forecast_benchmark_v1" / "results.json")
    structure = read_json(DATA / "model" / "gw1_structure_stress_v1" / "results.json")
    role = read_json(DATA / "model" / "preseason_role_scenario_v1" / "results.json")

    expected_leader = synthesis["decision"]["candidate_id"]
    expected_universe = robust["funnel"]["combined_universe"]
    expected_common = synthesis["candidate_coverage"]["common_finalists"]
    robust_finalists = {row["candidate_id"] for row in robust["finalist_metrics"]}
    horizon_finalists = {row["candidate_id"] for row in horizon["finalist_metrics"]}
    if expected_leader not in robust_finalists or expected_leader not in horizon_finalists:
        raise RuntimeError(
            "The synthesized decision was not deeply evaluated by both audit families"
        )
    if not pipeline["published"] or pipeline["status"] != "published":
        raise RuntimeError("The deadline pipeline is not published; do not publish the whitepaper")
    if readiness["selected_candidate_id"] != expected_leader:
        raise RuntimeError("The readiness audit does not describe the published candidate")
    if bench["current"]["candidate_id"] != expected_leader:
        raise RuntimeError("The bench audit does not describe the published candidate")
    if structure["published_candidate_id"] != expected_leader or not structure["publishable"]:
        raise RuntimeError("The structure audit does not authorize the published candidate")
    if role["production_changed"]:
        raise RuntimeError("The role audit changed production; rebuild the canonical decision first")
    if len(pipeline["stages"]) != 15 or any(
        stage["status"] != "completed" for stage in pipeline["stages"]
    ):
        raise RuntimeError("The canonical deadline pipeline is incomplete")
    market_policy = pipeline["refresh"]["direct_forecast"]["market_feature_policy"]
    if market_policy["weight"] != market["production_policy"]["preseason_weight"]:
        raise RuntimeError("The current forecast and promoted market policy disagree")
    external_test_rows = sum(fold["test_rows"] for fold in external["build"]["folds"])
    external_events = len(external["legal_policy"]["events"])
    for required in (
        expected_leader,
        f"{expected_universe:,}",
        f"{expected_common}",
        pipeline["input_fingerprint"],
        f"{forecast['backtest_gate']['mean_top_k_lift']:+.3f}",
        f"{synthesis['decision']['synthesis_regret']:.3f}",
        f"{synthesis['selected_family_metrics']['five_week_robust']['robust_regret']:.3f}",
        f"{synthesis['selected_family_metrics']['eight_week_horizon']['robust_regret']:.3f}",
        f"{market_policy['weight']:.0%}",
        f"{external_test_rows:,}",
        f"{external_events}",
        str(bench["coverage"]["targeted_unique_candidates"]),
        structure["stress_leader_id"],
        role["verdict"],
    ):
        if required not in markdown:
            raise RuntimeError(f"Canonical Markdown is missing expected snapshot marker: {required}")

    # The custom masthead owns title/version metadata; render from the Abstract onward.
    abstract_offset = markdown.index("## Abstract")
    article_source = markdown[abstract_offset:]
    visuals = {
        "episode": episode_visual(expected_universe),
        "funnel": funnel_visual(robust, synthesis),
        "synthesis": synthesis_visual(synthesis),
        "team": team_visual(synthesis),
        "validation": validation_visual(
            forecast, component, bps, appearance, robust, readiness
        ),
    }
    rendered = render_markdown(article_source, visuals)
    overview = pipeline_visual(robust, horizon, synthesis, forecast)
    word_count = len(re.findall(r"\b[\w’'-]+\b", markdown))
    read_minutes = max(1, round(word_count / 230))
    source_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    robust_sha = hashlib.sha256(
        (DATA / "model" / "robust_search_v2_global" / "results.json").read_bytes()
    ).hexdigest()
    horizon_sha = hashlib.sha256(
        (DATA / "model" / "horizon_audit_v1" / "results.json").read_bytes()
    ).hexdigest()
    toc = "".join(
        f'<a class="toc-level-{level}" href="#{section_id}"><span>{html.escape(title)}</span></a>'
        for level, title, section_id in rendered.headings
        if level <= 3
    )
    return document(
        article=rendered.body,
        overview=overview,
        toc=toc,
        word_count=word_count,
        read_minutes=read_minutes,
        source_sha=source_sha,
        robust_sha=robust_sha,
        horizon_sha=horizon_sha,
        section_count=sum(level == 2 for level, _, _ in rendered.headings),
        decision_id=expected_leader,
        formation=synthesis["decision"]["formation"],
        captain=captain_name(synthesis),
        snapshot_at=pipeline["checked_at"],
        evidence_fingerprint=pipeline["input_fingerprint"],
    )


def document(
    *,
    article: str,
    overview: str,
    toc: str,
    word_count: int,
    read_minutes: int,
    source_sha: str,
    robust_sha: str,
    horizon_sha: str,
    section_count: int,
    decision_id: str,
    formation: str,
    captain: str,
    snapshot_at: str,
    evidence_fingerprint: str,
) -> str:
    snapshot_label = datetime.fromisoformat(snapshot_at).strftime("%d %b %Y · %H:%M UTC")
    fonts = {
        "manrope400": font_data("manrope-400.ttf"),
        "manrope500": font_data("manrope-500.ttf"),
        "manrope600": font_data("manrope-600.ttf"),
        "manrope700": font_data("manrope-700.ttf"),
        "news400": font_data("newsreader-400.ttf"),
        "news500": font_data("newsreader-500.ttf"),
        "news600": font_data("newsreader-600.ttf"),
    }
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="description" content="Technical whitepaper for the current FPLAgent 2026/27 initial-squad decision engine.">
<title>FPLAgent · Algorithm Technical Whitepaper</title>
<style>
@font-face{{font-family:Manrope;src:url('{fonts['manrope400']}') format('truetype');font-weight:400}}
@font-face{{font-family:Manrope;src:url('{fonts['manrope500']}') format('truetype');font-weight:500}}
@font-face{{font-family:Manrope;src:url('{fonts['manrope600']}') format('truetype');font-weight:600}}
@font-face{{font-family:Manrope;src:url('{fonts['manrope700']}') format('truetype');font-weight:700}}
@font-face{{font-family:Newsreader;src:url('{fonts['news400']}') format('truetype');font-weight:400}}
@font-face{{font-family:Newsreader;src:url('{fonts['news500']}') format('truetype');font-weight:500}}
@font-face{{font-family:Newsreader;src:url('{fonts['news600']}') format('truetype');font-weight:600}}
:root{{--paper:#f1f0e9;--surface:#fbfaf5;--ink:#14231c;--muted:#667169;--line:#c8c9be;
 --blue:#2d6449;--blue-soft:#dce9df;--coral:#2d6449;--green:#244f3b;--pitch:#295f43;
 --serif:Newsreader,Georgia,serif;--sans:Manrope,"Trebuchet MS",sans-serif}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth;background:var(--paper)}}
body{{margin:0;color:var(--ink);background:var(--paper);font-family:var(--sans);font-size:16px;line-height:1.72}}
a{{color:inherit}}
::selection{{background:#ffcf74;color:var(--ink)}}
.reading-progress{{position:fixed;z-index:100;left:0;top:0;width:100%;height:3px;background:transparent}}
.reading-progress span{{display:block;width:100%;height:100%;background:var(--coral);transform:scaleX(0);transform-origin:left}}
.topbar{{position:fixed;z-index:90;top:18px;left:50%;transform:translateX(-50%);width:min(1180px,calc(100% - 32px));
 display:flex;align-items:center;justify-content:space-between;padding:9px 10px 9px 18px;border:1px solid rgba(18,33,38,.14);
 border-radius:999px;background:rgba(251,248,241,.91);backdrop-filter:blur(18px);box-shadow:0 14px 50px rgba(35,42,40,.1)}}
.brand{{display:flex;align-items:center;gap:10px;font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}}
.brand-mark{{display:grid;place-items:center;width:26px;height:26px;border-radius:50%;color:white;background:var(--blue);letter-spacing:0}}
.top-meta{{display:flex;align-items:center;gap:20px;color:var(--muted);font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase}}
.print-button{{border:0;border-radius:999px;padding:10px 16px;color:white;background:var(--ink);font:600 11px var(--sans);letter-spacing:.06em;text-transform:uppercase;cursor:pointer}}
.hero{{position:relative;min-height:830px;padding:150px max(24px,calc((100vw - 1180px)/2)) 70px;overflow:hidden;background:var(--surface)}}
.hero:before{{content:"";position:absolute;right:-10vw;top:-20vw;width:62vw;height:62vw;border:1px solid #ded8ca;border-radius:50%}}
.hero:after{{content:"";position:absolute;right:8vw;top:16vw;width:24vw;height:24vw;border:1px solid #ded8ca;border-radius:50%}}
.hero-grid{{position:relative;z-index:2;display:grid;grid-template-columns:minmax(0,1.5fr) minmax(260px,.5fr);gap:90px;align-items:end}}
.eyebrow,.visual-kicker{{font-size:11px;font-weight:700;letter-spacing:.18em;text-transform:uppercase}}
.eyebrow{{display:flex;align-items:center;gap:12px;color:var(--blue)}}
.eyebrow:before{{content:"";width:42px;height:2px;background:var(--blue)}}
h1{{max-width:840px;margin:26px 0 28px;font:500 clamp(58px,7vw,108px)/.91 var(--serif);letter-spacing:-.055em}}
.hero-copy{{max-width:700px;margin:0;font:400 clamp(20px,2vw,28px)/1.35 var(--serif);color:#44504f}}
.hero-side{{padding:24px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
.hero-side dl{{display:grid;grid-template-columns:1fr auto;gap:12px 20px;margin:0;font-size:12px}}
.hero-side dt{{color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
.hero-side dd{{margin:0;text-align:right;font-weight:700}}
.decision-banner{{position:relative;z-index:2;display:grid;grid-template-columns:1fr auto auto;gap:30px;align-items:center;margin-top:90px;padding:24px 0 0;border-top:1px solid var(--ink)}}
.decision-banner small{{display:block;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}}
.decision-banner strong{{display:block;margin-top:4px;font:500 28px var(--serif)}}
.status{{padding:8px 12px;border-radius:999px;background:#e4eee8;color:var(--green);font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase}}
.overview-wrap{{padding:0 max(24px,calc((100vw - 1180px)/2));background:var(--ink)}}
.major-visual{{position:relative;margin:70px 0;padding:32px;border:1px solid rgba(18,33,38,.22);background:var(--surface);box-shadow:8px 8px 0 rgba(18,33,38,.08)}}
.major-visual:before{{content:"";position:absolute;inset:7px;pointer-events:none;border:1px solid rgba(18,33,38,.08)}}
.major-visual figcaption{{position:relative;margin-top:24px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}}
.episode-visual{{padding:0;overflow:hidden;background:var(--ink);color:var(--surface);box-shadow:10px 10px 0 var(--blue)}}
.episode-visual:before{{display:none}}.episode-visual>.visual-kicker{{padding:22px 26px;border-bottom:1px solid #405054;color:#aeb9b7}}
.episode-layout{{display:grid;grid-template-columns:minmax(250px,.64fr) minmax(0,1.36fr);align-items:stretch}}
.episode-copy{{display:flex;min-height:390px;flex-direction:column;padding:34px 30px}}
.episode-number{{color:var(--blue-soft);font:500 42px var(--serif);letter-spacing:-.04em}}
.episode-copy h3{{margin:46px 0 14px;color:white;font:500 36px/1 var(--serif)}}
.episode-copy p{{margin:0;color:#aeb9b7;font-size:12px;line-height:1.65}}
.episode-link{{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:18px;border-top:1px solid #405054;color:white;font-size:11px;font-weight:700;letter-spacing:.06em;text-decoration:none;text-transform:uppercase}}
.episode-link span{{font-size:18px}}.episode-visual video{{display:block;width:100%;height:100%;min-height:390px;object-fit:cover;background:#0f1813}}
.episode-visual figcaption{{margin:0;padding:17px 26px;border-top:1px solid #405054;color:#aeb9b7}}
.overview-wrap .major-visual{{top:60px;margin:0;color:var(--surface);background:var(--ink);border-color:#405054;box-shadow:10px 10px 0 var(--blue)}}
.overview-wrap .major-visual:before{{border-color:#405054}}
.overview-wrap .major-visual figcaption{{border-color:#405054;color:#aeb9b7}}
.flow-grid{{position:relative;display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-top:28px}}
.flow-line{{position:absolute;left:6%;right:6%;top:105px;height:1px;background:#516064}}
.flow-card{{position:relative;min-height:174px;padding:16px 12px;background:#192b31;border-top:2px solid var(--blue)}}
.flow-card>span{{display:grid;place-items:center;width:28px;height:28px;margin-bottom:26px;border:1px solid #718083;border-radius:50%;font-size:10px}}
.flow-card small,.flow-card em{{display:block;color:#9fadaa;font-size:9px;font-style:normal;text-transform:uppercase;letter-spacing:.06em}}
.flow-card strong{{display:block;margin:5px 0;font:500 clamp(21px,2vw,31px) var(--serif);white-space:nowrap}}
.paper-layout{{display:grid;grid-template-columns:250px minmax(0,770px);gap:100px;max-width:1180px;margin:0 auto;padding:150px 24px 120px}}
.toc{{position:sticky;top:98px;max-height:calc(100vh - 125px);align-self:start;overflow:auto;padding-right:20px;scrollbar-width:thin}}
.toc-title{{display:block;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid var(--line);font-size:10px;font-weight:700;letter-spacing:.15em;text-transform:uppercase}}
.toc a{{display:block;padding:6px 0;color:#71807d;text-decoration:none;font-size:10px;line-height:1.35;transition:color .2s ease}}
.toc a.active{{color:var(--blue);font-weight:700}}
.toc .toc-level-3{{padding-left:14px;font-size:9px}}
.paper{{min-width:0}}
.paper-section{{scroll-margin-top:110px;padding:88px 0 10px;border-top:1px solid var(--line)}}
.paper-section:first-child{{padding-top:0;border-top:0}}
.paper h2{{max-width:680px;margin:0 0 32px;font:500 clamp(38px,5vw,64px)/1 var(--serif);letter-spacing:-.035em}}
.paper h3{{margin:52px 0 16px;font:600 25px/1.15 var(--serif);letter-spacing:-.015em}}
.paper h4{{margin:38px 0 12px;font:700 12px var(--sans);letter-spacing:.09em;text-transform:uppercase}}
.heading-link{{text-decoration:none}}
.paper p{{margin:0 0 22px}}
.paper h2+p{{font:400 20px/1.58 var(--serif);color:#394644}}
.paper strong{{font-weight:700}}
.paper code{{padding:.14em .35em;border-radius:4px;background:#e8e3d8;font:500 .88em ui-monospace,"Cascadia Mono","Courier New",monospace;overflow-wrap:anywhere;word-break:break-word}}
.paper blockquote{{margin:36px 0;padding:8px 0 8px 28px;border-left:3px solid var(--coral)}}
.paper blockquote p{{margin:0;font:500 23px/1.45 var(--serif)}}
.paper ul,.paper ol{{margin:18px 0 28px;padding-left:24px}}
.paper li{{padding:3px 0 3px 5px}}
.paper li::marker{{color:var(--coral);font-weight:700}}
.code-panel{{margin:32px 0;border:1px solid #38494d;background:var(--ink);color:#e8efed;overflow:hidden}}
.code-panel figcaption{{margin:0;padding:10px 16px;border:0;border-bottom:1px solid #38494d;color:#8ea19e;font-size:9px;font-weight:700;letter-spacing:.13em}}
.code-panel pre{{margin:0;padding:22px;overflow:auto;font:500 12px/1.7 ui-monospace,"Cascadia Mono","Courier New",monospace}}
.code-panel code{{padding:0;background:transparent;color:inherit;overflow-wrap:normal;word-break:normal}}
.code-panel.formula{{background:#1e3e37;border-color:#376157}}
.table-scroll{{max-width:100%;margin:30px 0;overflow:auto;border-top:2px solid var(--ink);border-bottom:1px solid var(--line)}}
table{{width:100%;border-collapse:collapse;font-size:12px;line-height:1.5}}
th{{padding:14px 12px;text-align:left;background:#eae5da;font-size:9px;letter-spacing:.08em;text-transform:uppercase}}
td{{padding:12px;border-top:1px solid #d9d3c7;vertical-align:top}}
th:last-child,td:last-child{{text-align:right}}
.funnel-grid{{display:grid;gap:8px;margin-top:26px}}
.funnel-row{{display:grid;grid-template-columns:1fr 150px;align-items:center;gap:18px}}
.funnel-row small{{color:var(--muted);font-size:10px}}
.funnel-bar{{display:flex;width:var(--funnel-width);min-width:190px;justify-content:space-between;align-items:center;margin:auto;padding:10px 14px;color:white;background:var(--ink)}}
.funnel-bar span{{font-size:10px;text-transform:uppercase;letter-spacing:.07em}}
.funnel-bar strong{{font:500 20px var(--serif)}}
.synthesis-grid{{display:grid;grid-template-columns:1fr .8fr 1fr;gap:12px;align-items:stretch;margin-top:26px}}
.family-card,.synthesis-node{{padding:24px}}
.family-card{{color:white;background:var(--ink)}}
.family-card span,.synthesis-node span{{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}}
.family-card strong{{display:block;margin:25px 0 6px;font:500 54px var(--serif)}}
.family-card p{{margin:0;color:#b9c4c1;font-size:11px;line-height:1.5}}
.family-eight{{background:var(--blue)}}
.family-eight p{{color:#d9e0ff}}
.synthesis-node{{display:flex;flex-direction:column;justify-content:center;text-align:center;background:#eae5da}}
.synthesis-node i{{font:400 22px var(--serif)}}
.synthesis-node strong{{display:block;margin-top:20px;font:600 45px var(--serif)}}
.synthesis-node em{{color:var(--muted);font-size:9px;font-style:normal;text-transform:uppercase}}
.boundary-track{{position:relative;height:52px;margin-top:14px;background:#eae5da;overflow:hidden}}
.boundary-track span{{position:absolute;inset:0 auto 0 0;background:#cbd5fb}}
.boundary-track b{{position:relative;display:flex;height:100%;align-items:center;padding:0 18px;font-size:10px}}
.comparison-strip{{display:flex;justify-content:space-between;gap:20px;margin-top:12px;padding:13px 16px;border:1px solid var(--line);font-size:10px}}
.pitch{{position:relative;min-height:560px;margin-top:26px;padding:24px 20px;display:grid;grid-template-rows:repeat(4,1fr);overflow:hidden;color:white;background:var(--pitch);border:2px solid white;outline:12px solid var(--pitch)}}
.pitch:before{{content:"";position:absolute;inset:50% 0 auto;height:1px;background:rgba(255,255,255,.42)}}
.centre-circle{{position:absolute;z-index:0;left:50%;top:50%;width:100px;height:100px;transform:translate(-50%,-50%);border:1px solid rgba(255,255,255,.42);border-radius:50%}}
.pitch-row{{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-around;gap:8px}}
.shirt{{max-width:126px;text-align:center}}
.shirt:before{{content:"";display:block;width:32px;height:38px;margin:0 auto 7px;background:var(--surface);clip-path:polygon(20% 0,37% 0,43% 8%,57% 8%,63% 0,80% 0,100% 18%,84% 36%,81% 100%,19% 100%,16% 36%,0 18%)}}
.shirt span{{display:block;font-size:10px;font-weight:700;line-height:1.15}}
.shirt small{{display:block;margin-top:3px;color:#c9ddd6;font-size:8px}}
.row-mid .shirt:before{{background:#ffce69}}.row-fwd .shirt:before{{background:#f49a7e}}.row-gk .shirt:before{{background:#93b7ff}}
.bench{{display:grid;grid-template-columns:auto repeat(4,1fr);gap:1px;margin:24px 0 0;background:var(--line)}}
.bench>strong,.bench>div{{padding:13px;background:#eae5da}}
.bench>strong{{display:flex;align-items:center;font-size:9px;letter-spacing:.1em;writing-mode:vertical-rl}}
.bench div b{{display:block;color:var(--coral);font-size:9px}}.bench div span{{display:block;font-size:10px;font-weight:700}}.bench div small{{font-size:8px;color:var(--muted)}}
.team-meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}.team-meta span{{padding:7px 10px;border-radius:999px;background:#eae5da;font-size:9px;font-weight:700;text-transform:uppercase}}
.validation-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin-top:26px;background:var(--line)}}
.validation-grid article{{min-height:155px;padding:18px;background:var(--surface)}}
.validation-grid span{{font-size:8px;font-weight:700;letter-spacing:.1em;color:var(--blue)}}
.validation-grid strong{{display:block;margin:19px 0 8px;font:500 28px var(--serif)}}
.validation-grid p{{margin:0;color:var(--muted);font-size:9px;line-height:1.45}}
.reveal{{opacity:1;transform:none}}
.reveal.visible{{opacity:1;transform:none}}
.footer{{padding:70px max(24px,calc((100vw - 1180px)/2));color:#b5c0bd;background:var(--ink)}}
.footer-grid{{display:grid;grid-template-columns:1fr 1fr;gap:80px}}
.footer h2{{margin:0;color:white;font:500 43px var(--serif)}}
.footer p{{max-width:560px;font-size:12px}}
.hashes{{font:500 9px/1.9 ui-monospace,"Cascadia Mono","Courier New",monospace;overflow-wrap:anywhere}}
@media(max-width:900px){{.flow-grid{{grid-template-columns:repeat(4,1fr)}}.flow-line{{display:none}}.paper-layout{{grid-template-columns:190px minmax(0,1fr);gap:45px}}.validation-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:720px){{body{{font-size:15px}}.top-meta span{{display:none}}.hero{{min-height:760px;padding-top:130px}}.hero-grid{{grid-template-columns:1fr;gap:45px}}h1{{font-size:62px}}.decision-banner{{grid-template-columns:1fr 1fr;margin-top:55px}}.status{{grid-column:1/-1;width:max-content}}.flow-grid{{grid-template-columns:repeat(2,1fr)}}.paper-layout{{display:block;padding-top:120px}}.toc{{display:none}}.paper h2{{font-size:42px}}.major-visual{{margin-left:-12px;margin-right:-12px;padding:22px}}.episode-visual{{padding:0}}.episode-layout{{grid-template-columns:1fr}}.episode-copy{{min-height:330px}}.episode-visual video{{min-height:0;aspect-ratio:16/9}}.synthesis-grid{{grid-template-columns:1fr}}.comparison-strip{{display:grid}}.funnel-row{{grid-template-columns:1fr}}.funnel-row small{{display:none}}.funnel-bar{{margin:0}}.pitch{{min-height:520px;padding-left:5px;padding-right:5px}}.shirt span{{font-size:8px}}.shirt small{{display:none}}.bench{{grid-template-columns:1fr 1fr}}.bench>strong{{grid-column:1/-1;writing-mode:initial}}.footer-grid{{grid-template-columns:1fr;gap:30px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}.reveal{{opacity:1;transform:none;transition:none}}}}
@media print{{@page{{margin:16mm}}body{{background:white;font-size:10pt}}.topbar,.reading-progress,.toc{{display:none!important}}.hero{{min-height:0;padding:20mm 0 15mm;background:white}}.hero:before,.hero:after{{display:none}}.paper-layout{{display:block;max-width:none;padding:20mm 0}}.paper-section{{break-before:page;padding-top:12mm}}.paper-section:first-child{{break-before:auto}}.major-visual,.code-panel,.table-scroll{{break-inside:avoid;box-shadow:none}}.reveal{{opacity:1;transform:none}}.footer{{padding:15mm 0;color:#333;background:white}}}}
</style>
</head>
<body>
<div class="reading-progress" aria-hidden="true"><span></span></div>
<nav class="topbar" aria-label="Whitepaper controls"><div class="brand"><span class="brand-mark">F</span>FPLAgent</div>
  <div class="top-meta"><span>{section_count} sections · {read_minutes} min read</span><button class="print-button" type="button" onclick="window.print()">Print / PDF</button></div></nav>
<header class="hero">
  <div class="hero-grid"><div><div class="eyebrow">Technical whitepaper · Version 2.1</div>
    <h1>Evidence before instinct.</h1>
    <p class="hero-copy">How point-in-time data, independent forecasting, bookmaker calibration,
    exact FPL mechanics and adversarial decision audits produced the current 2026/27 squad.</p></div>
    <aside class="hero-side"><dl><dt>Prepared</dt><dd>19 Aug 2026</dd><dt>Snapshot</dt><dd>{snapshot_label}</dd>
      <dt>Words</dt><dd>{word_count:,}</dd><dt>Reading time</dt><dd>{read_minutes} minutes</dd><dt>Format</dt><dd>Self-contained HTML</dd></dl></aside></div>
  <div class="decision-banner"><div><small>Current decision</small><strong>{decision_id}</strong></div>
    <div><small>Shape & captain</small><strong>{formation} · {captain}</strong></div><span class="status">Published · role verification open</span></div>
</header>
<div class="overview-wrap">{overview}</div>
<main class="paper-layout"><aside class="toc" aria-label="Contents"><span class="toc-title">Contents</span>{toc}</aside>
  <article class="paper">{article}</article></main>
<footer class="footer"><div class="footer-grid"><div><h2>A receipt, not a prophecy.</h2><p>This document describes the algorithm at one versioned preseason snapshot. The engine must ingest
new information, rerun its gates and issue a new receipt before the Gameweek 1 lock.</p></div>
<div class="hashes">EVIDENCE FINGERPRINT · {evidence_fingerprint}<br>MARKDOWN SHA-256 · {source_sha}<br>ROBUST AUDIT SHA-256 · {robust_sha}<br>HORIZON AUDIT SHA-256 · {horizon_sha}<br><br>Fonts, CSS, diagrams and interactions are embedded. No network connection is required.</div></div></footer>
<script>
document.fonts.ready.then(()=>{{
  if(location.hash){{
    const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if(target) target.scrollIntoView();
  }}
}});
const sections=[...document.querySelectorAll('.paper-section')];
sections.forEach(section=>section.classList.add('reveal'));
document.querySelectorAll('.paper .major-visual').forEach(visual=>visual.classList.add('reveal'));
const revealObserver=new IntersectionObserver(entries=>{{entries.forEach(entry=>{{if(entry.isIntersecting)entry.target.classList.add('visible')}})}},{{rootMargin:'0px 0px -8% 0px',threshold:.05}});
document.querySelectorAll('.reveal').forEach(element=>revealObserver.observe(element));
const tocLinks=[...document.querySelectorAll('.toc a')];
const activeObserver=new IntersectionObserver(entries=>{{entries.forEach(entry=>{{if(entry.isIntersecting){{tocLinks.forEach(link=>link.classList.toggle('active',link.getAttribute('href')==='#'+entry.target.id))}}}})}},{{rootMargin:'-18% 0px -72% 0px'}});
sections.forEach(section=>activeObserver.observe(section));
const progress=document.querySelector('.reading-progress span');
const progressObserver=new IntersectionObserver(()=>{{const rect=document.documentElement.getBoundingClientRect();const max=document.documentElement.scrollHeight-document.documentElement.clientHeight;const ratio=max?Math.min(1,Math.max(0,-rect.top/max)):0;progress.style.transform=`scaleX(${{ratio}})`}},{{threshold:[0,.25,.5,.75,1]}});
sections.forEach(section=>progressObserver.observe(section));
</script>
</body>
</html>"""


def main() -> None:
    output = build()
    OUTPUT.write_text(output, encoding="utf-8")
    print(f"Built {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
