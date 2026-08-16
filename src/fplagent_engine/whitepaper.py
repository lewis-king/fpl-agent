from __future__ import annotations

import base64
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS

from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .sota_readiness import RESULTS_JSON as READINESS_RESULTS
from .sota_readiness import build_sota_readiness_audit

VERSION = "gw1_whitepaper_v2"
OUTPUT = REPORTS / "fplagent-gw1-2026-27-whitepaper.html"
DEADLINE_PACK = MANIFESTS / "gw1-deadline-pack.json"
SYNTHESIS_RESULTS = MODEL_DATA / "gw1_decision_synthesis_v1" / "results.json"
ROBUST_RESULTS = MODEL_DATA / "robust_search_v2_global" / "results.json"
HORIZON_RESULTS = MODEL_DATA / "horizon_audit_v1" / "results.json"
FORECAST_METRICS = MODEL_DATA / "artifacts" / "forecast_v2" / "metrics.json"
PICKER_BACKTEST = MODEL_DATA / "artifacts" / "forecast_v2" / "picker-backtest.json"
DATA_QUALITY = MODEL_DATA / "normalized" / "data_quality.json"
AVAILABILITY = MANIFESTS / "fpl-availability-watch.json"
MARKET_POLICY = MODEL_DATA / "market_feature_v1" / "results.json"
STRUCTURE_RESULTS = MODEL_DATA / "gw1_structure_stress_v1" / "results.json"
UNDERSTAT_RESULTS = MODEL_DATA / "understat_preseason_v1" / "results.json"
BENCH_ALLOCATION_RESULTS = MODEL_DATA / "bench_allocation_audit_v2" / "results.json"
ROLE_SCENARIO_RESULTS = MODEL_DATA / "preseason_role_scenario_v1" / "results.json"
FONT_DIR = REPORTS / "assets"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def _font(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _player_card(player: dict[str, Any], role: dict[int, dict[str, Any]]) -> str:
    observed = role.get(int(player["element"]), {})
    forecast = dict(observed.get("forecast") or {})
    tags = []
    if player.get("captain"):
        tags.append('<span class="armband">C</span>')
    if player.get("vice_captain"):
        tags.append('<span class="armband vice">V</span>')
    attention = list(observed.get("attention") or [])
    if attention:
        tags.append('<span class="risk-dot" title="Role verification required"></span>')
    xp = forecast.get("expected_points")
    p_play = forecast.get("p_play")
    metrics = []
    if xp is not None:
        metrics.append(f"{float(xp):.2f} xP")
    if p_play is not None:
        metrics.append(f"{100 * float(p_play):.0f}% play")
    return f"""
      <article class="player-card">
        <div class="player-top"><span class="position">{_e(player['position'])}</span><span>{''.join(tags)}</span></div>
        <strong>{_e(player['name'])}</strong>
        <span>{_e(player['team'])} · £{float(player['price']):.1f}m</span>
        <small>{_e(' · '.join(metrics))}</small>
      </article>"""


def _gate_card(row: dict[str, Any]) -> str:
    state = str(row["state"])
    label = {"pass": "Passed", "partial": "Partial", "not_ready": "Not ready"}[state]
    return f"""
      <article class="gate-card {state}">
        <div class="gate-head"><span class="status-dot"></span><span>{_e(label)}</span><small>{_e(row['scope'].replace('_', ' '))}</small></div>
        <h3>{_e(row['label'])}</h3>
        <p>{_e(row['evidence'])}</p>
        <details><summary>Promotion standard</summary><p>{_e(row['requirement'])}</p></details>
      </article>"""


def build_algorithm_whitepaper(
    *,
    deadline_pack_path: Path = DEADLINE_PACK,
    synthesis_path: Path = SYNTHESIS_RESULTS,
    robust_path: Path = ROBUST_RESULTS,
    horizon_path: Path = HORIZON_RESULTS,
    forecast_metrics_path: Path = FORECAST_METRICS,
    picker_backtest_path: Path = PICKER_BACKTEST,
    data_quality_path: Path = DATA_QUALITY,
    availability_path: Path = AVAILABILITY,
    market_policy_path: Path = MARKET_POLICY,
    structure_path: Path = STRUCTURE_RESULTS,
    understat_path: Path = UNDERSTAT_RESULTS,
    bench_allocation_path: Path = BENCH_ALLOCATION_RESULTS,
    role_scenario_path: Path = ROLE_SCENARIO_RESULTS,
    readiness_path: Path = READINESS_RESULTS,
    output_path: Path = OUTPUT,
) -> dict[str, Any]:
    ensure_engine_layout()
    if not readiness_path.is_file():
        build_sota_readiness_audit()
    pack = _load(deadline_pack_path)
    synthesis = _load(synthesis_path)
    robust = _load(robust_path)
    horizon = _load(horizon_path)
    metrics = _load(forecast_metrics_path)
    picker = _load(picker_backtest_path)
    quality = _load(data_quality_path)
    availability = _load(availability_path)
    market = _load(market_policy_path)
    structure = _load(structure_path)
    understat = _load(understat_path) if understat_path.is_file() else {}
    bench_allocation = _load(bench_allocation_path)
    role_scenario = _load(role_scenario_path)
    readiness = _load(readiness_path)

    decision = dict(pack["decision"])
    squad = dict(decision["squad"])
    role = {int(row["element"]): row for row in availability.get("players") or []}
    starters = list(squad["starters"])
    bench = list(squad["bench"])
    groups = {
        position: [player for player in starters if player["position"] == position]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    funnel = dict(robust["funnel"])
    global_challenge = dict(robust["global_challenge"])
    backtest_gate = dict(metrics["backtest_gate"])
    picker_summary = dict(picker["summary"])
    market_policy = dict(market["production_policy"])
    understat_current = dict((understat.get("mapping") or {}).get("current") or {})
    understat_coverage = dict(
        (understat_current.get("coverage") or {}).get("2026-27") or {}
    )
    bench_targeted = dict(bench_allocation.get("targeted_winner") or {})
    bench_retention = dict(bench_allocation.get("targeted_retention") or {})
    baseline_role = dict((role_scenario.get("scenarios") or {}).get("baseline") or {})
    baseline_deep = dict(baseline_role.get("deep_squad_replay") or {})
    baseline_delta = dict(baseline_deep.get("holdout_delta_challenger_to_incumbent") or {})
    baseline_residual = dict(baseline_delta.get("residual") or {})
    baseline_component = dict(baseline_delta.get("component") or {})
    structure_holdout = dict(
        ((structure.get("holdout") or {}).get("challenger_minus_published") or {}).get(
            "central_rules"
        )
        or {}
    )
    structure_reconciliation = dict(structure.get("reconciliation") or {})
    long_horizon = dict(synthesis.get("long_horizon_challenger") or {})
    alternative = dict(long_horizon.get("eight_week_horizon") or {})
    alt_delta = dict(long_horizon.get("central_eight_week_delta") or {})
    selected_families = dict(synthesis.get("selected_family_metrics") or {})
    five = dict(selected_families.get("five_week_robust") or {})
    eight = dict(selected_families.get("eight_week_horizon") or {})
    role_summary = dict(availability.get("summary") or {})
    watkins = role.get(55, {})
    watkins_preseason = dict(watkins.get("preseason") or {})
    watkins_lineups = dict(watkins.get("predicted_lineups") or {})
    now = datetime.now(UTC).isoformat()

    font_css = f"""
    @font-face{{font-family:Manrope;src:url(data:font/ttf;base64,{_font(FONT_DIR / 'manrope-400.ttf')}) format('truetype');font-weight:400;font-display:swap}}
    @font-face{{font-family:Manrope;src:url(data:font/ttf;base64,{_font(FONT_DIR / 'manrope-600.ttf')}) format('truetype');font-weight:600;font-display:swap}}
    @font-face{{font-family:Newsreader;src:url(data:font/ttf;base64,{_font(FONT_DIR / 'newsreader-500.ttf')}) format('truetype');font-weight:500;font-display:swap}}
    """
    gate_cards = "".join(_gate_card(row) for row in readiness["checks"])
    pitch_rows = "".join(
        f'<div class="pitch-row {position.lower()}">{"".join(_player_card(player, role) for player in groups[position])}</div>'
        for position in ("GK", "DEF", "MID", "FWD")
    )
    bench_cards = "".join(_player_card(player, role) for player in bench)
    priority_rows = "".join(
        f"""
        <article class="priority"><span>0{gap['priority']}</span><div><h3>{_e(gap['name'])}</h3><p>{_e(gap['why'])}</p><small>{_e(gap['promotion_rule'])}</small></div></article>
        """
        for gap in readiness["priority_gaps"]
    )
    checksums = "".join(
        f"<tr><td>{_e(name.replace('_sha256', '').replace('_', ' '))}</td><td><code>{_e(value[:16])}…</code></td></tr>"
        for name, value in readiness["artifacts"].items()
    )

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="FPLAgent 2026/27 GW1 algorithm white paper and evidence audit.">
  <title>FPLAgent — The first fifteen</title>
  <style>
  {font_css}
  :root{{--ink:#132019;--forest:#173e2b;--moss:#39724f;--lime:#d9f45a;--paper:#f3f0e7;--cream:#fffdf7;--line:#c9cec5;--muted:#68736c;--amber:#b66923;--red:#a0443b;--shadow:0 22px 60px rgba(19,32,25,.10);--ease:cubic-bezier(.2,.75,.25,1)}}
  *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Manrope,sans-serif;font-size:16px;line-height:1.65}}a{{color:inherit;text-decoration-thickness:1px;text-underline-offset:4px}}button{{font:inherit}}h1,h2,.serif{{font-family:Newsreader,serif;font-weight:500;letter-spacing:-.035em}}h1{{font-size:clamp(3.6rem,8vw,7.7rem);line-height:.84;margin:.22em 0}}h2{{font-size:clamp(2.4rem,4.5vw,5rem);line-height:.96;margin:0 0 .45em}}h3{{font-size:1rem;line-height:1.3;margin:.55rem 0}}p{{margin:.45rem 0 1rem}}small{{color:var(--muted)}}code{{font-family:Manrope,sans-serif;font-size:.78rem}}
  .shell{{max-width:1460px;margin:auto;padding:0 34px}}.topbar{{height:74px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;background:rgba(243,240,231,.94);backdrop-filter:blur(16px)}}.brand{{display:flex;align-items:center;gap:12px;font-weight:600}}.mark{{width:30px;height:30px;background:var(--forest);border-radius:9px;display:grid;place-items:center;color:var(--lime);font-size:.72rem}}nav{{display:flex;gap:24px;font-size:.8rem}}.print{{border:1px solid var(--ink);border-radius:999px;padding:8px 14px;background:transparent;cursor:pointer}}
  .hero{{min-height:720px;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.55fr);gap:8vw;align-items:center;padding:8vh 0 9vh}}.eyebrow{{text-transform:uppercase;letter-spacing:.18em;font-size:.68rem;font-weight:600;color:var(--moss)}}.dek{{font-family:Newsreader,serif;font-size:clamp(1.35rem,2vw,2rem);line-height:1.25;max-width:760px;color:#35443b}}.hero-note{{border-left:2px solid var(--forest);padding-left:26px}}.verdict{{display:inline-flex;align-items:center;gap:9px;border:1px solid #a9b6ad;border-radius:999px;padding:8px 13px;font-size:.7rem;text-transform:uppercase;letter-spacing:.09em}}.verdict i{{width:8px;height:8px;border-radius:50%;background:var(--amber)}}.hero-meta{{display:grid;gap:22px;margin-top:36px}}.hero-meta div{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:10px}}.hero-meta strong{{font-size:1.35rem}}
  section{{padding:120px 0;border-top:1px solid var(--line)}}.section-head{{display:grid;grid-template-columns:.7fr 1.3fr;gap:8vw;margin-bottom:54px}}.section-head p{{font-size:1.1rem;max-width:680px;color:#49564e}}.chapter{{font-size:.7rem;letter-spacing:.17em;text-transform:uppercase;color:var(--moss)}}
  .bezel{{min-width:0;padding:8px;border:1px solid #b7beb7;border-radius:30px;background:rgba(255,255,255,.28)}}.panel{{min-width:0;border:1px solid #d0d4ce;border-radius:22px;background:var(--cream);box-shadow:var(--shadow)}}.claim-panel{{display:grid;grid-template-columns:1fr 1fr;gap:1px;overflow:hidden;background:var(--line)}}.claim{{background:var(--cream);padding:42px}}.claim b{{display:inline-block;text-transform:uppercase;font-size:.65rem;letter-spacing:.14em;margin-bottom:25px}}.claim.good b{{color:var(--moss)}}.claim.limit b{{color:var(--red)}}.claim p{{font-family:Newsreader,serif;font-size:1.55rem;line-height:1.25}}
  .score-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0 50px}}.metric{{padding:26px;border:1px solid var(--line);border-radius:18px;background:rgba(255,253,247,.55)}}.metric strong{{font-family:Newsreader,serif;font-size:2.3rem;display:block;line-height:1}}.metric span{{font-size:.7rem;text-transform:uppercase;letter-spacing:.11em;color:var(--muted)}}
  .pitch{{padding:7%;background:var(--forest);border-radius:22px;position:relative;overflow:hidden}}.pitch:before{{content:"";position:absolute;inset:5%;border:1px solid rgba(255,255,255,.35);border-radius:2px;pointer-events:none}}.pitch:after{{content:"";position:absolute;width:18%;aspect-ratio:1;border:1px solid rgba(255,255,255,.35);border-radius:50%;left:41%;top:41%;pointer-events:none}}.pitch-row{{display:flex;justify-content:center;gap:12px;position:relative;z-index:2;margin:30px 0}}.player-card{{background:var(--cream);border:1px solid rgba(19,32,25,.22);border-radius:12px;padding:11px 12px;width:150px;min-height:108px;box-shadow:0 8px 22px rgba(0,0,0,.13);display:flex;flex-direction:column;line-height:1.35}}.player-card strong{{font-size:.83rem;margin-top:8px}}.player-card>span,.player-card small{{font-size:.65rem}}.player-top{{display:flex;justify-content:space-between;align-items:center}}.position{{font-size:.57rem!important;letter-spacing:.12em;color:var(--moss);font-weight:600}}.armband{{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:var(--lime);font-size:.62rem;font-weight:600;margin-left:3px}}.armband.vice{{background:#dce6dd}}.risk-dot{{display:inline-block;width:8px;height:8px;background:var(--amber);border-radius:50%;margin-left:5px}}.bench-label{{display:flex;justify-content:space-between;margin:25px 2px 12px}}.bench{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.bench .player-card{{width:auto;min-height:112px}}
  .layers{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.layer{{padding:34px;min-height:300px}}.layer-number{{font-family:Newsreader,serif;font-size:4rem;color:#b8c1b9;line-height:1}}.layer ul{{padding-left:18px;font-size:.9rem;color:#47554c}}.plain-tech{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}}.explain{{padding:34px}}.explain.plain{{background:var(--lime);border-radius:22px}}.formula{{display:block;padding:20px;margin:18px 0;background:#15231b;color:#f3f0e7;border-radius:12px;font-size:.83rem;overflow:auto}}
  .funnel{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:18px;overflow:hidden}}.funnel div{{background:var(--cream);padding:28px 18px;min-height:150px}}.funnel strong{{font-family:Newsreader,serif;font-size:2rem;display:block}}.funnel span{{font-size:.68rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}}.evidence-strip{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}}.evidence-strip article{{padding:34px}}.evidence-strip strong{{font-family:Newsreader,serif;font-size:2.6rem;display:block}}
  .source-table,.receipt-table{{width:100%;border-collapse:collapse}}#data .panel,.receipt-grid>div{{min-width:0;overflow-x:auto}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:16px 10px;vertical-align:top}}th{{font-size:.65rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}td{{font-size:.85rem}}.pill{{display:inline-block;padding:4px 9px;border-radius:999px;font-size:.62rem;text-transform:uppercase;letter-spacing:.08em;background:#dce8de}}.pill.bounded{{background:#f1ddc5}}.pill.gap{{background:#ead0cc}}
  .gates{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.gate-card{{border:1px solid var(--line);border-radius:18px;padding:26px;background:var(--cream);min-height:250px}}.gate-head{{display:flex;align-items:center;gap:8px;font-size:.66rem;text-transform:uppercase;letter-spacing:.08em}}.gate-head small{{margin-left:auto;font-size:.58rem}}.status-dot{{width:8px;height:8px;border-radius:50%;background:var(--moss)}}.gate-card.not_ready .status-dot{{background:var(--red)}}.gate-card.partial .status-dot{{background:var(--amber)}}.gate-card p{{font-size:.82rem;color:#4e5a52}}details{{margin-top:16px;font-size:.76rem}}summary{{cursor:pointer;font-weight:600}}
  .risk-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.risk-box{{padding:38px}}.risk-box.warning{{background:#f2dfc7}}.risk-box h3{{font-family:Newsreader,serif;font-size:2rem}}.priority-list{{border-top:1px solid var(--line)}}.priority{{display:grid;grid-template-columns:100px 1fr;gap:26px;padding:28px 0;border-bottom:1px solid var(--line)}}.priority>span{{font-family:Newsreader,serif;font-size:2.8rem;color:#a8b1aa}}.priority p{{margin:.2rem 0}}.priority small{{display:block;max-width:780px}}
  .receipt-grid{{display:grid;grid-template-columns:1fr 1fr;gap:60px}}.footnote{{font-size:.72rem;color:var(--muted)}}footer{{padding:60px 0 80px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:30px;font-size:.72rem;color:var(--muted)}}
  [data-reveal]{{opacity:0;transform:translateY(18px);transition:opacity .7s var(--ease),transform .7s var(--ease)}}[data-reveal].visible{{opacity:1;transform:none}}
  @media(max-width:900px){{.shell{{padding:0 18px}}nav{{display:none}}.hero,.section-head,.claim-panel,.plain-tech,.risk-grid,.receipt-grid{{grid-template-columns:1fr}}.hero{{min-height:0;padding:100px 0}}section{{padding:80px 0}}.score-grid,.bench{{grid-template-columns:1fr 1fr}}.layers,.gates{{grid-template-columns:1fr}}.funnel{{grid-template-columns:1fr 1fr}}.pitch{{padding:5% 2%}}.pitch-row{{gap:5px;margin:18px 0}}.player-card{{width:110px;padding:8px;min-height:96px}}.player-card strong{{font-size:.68rem}}.mid .player-card{{width:92px}}.claim-panel{{gap:1px}}}}
  @media(max-width:560px){{h1{{font-size:3.5rem}}.score-grid{{grid-template-columns:1fr 1fr}}.pitch{{overflow-x:auto}}.pitch>div{{min-width:620px}}.funnel{{grid-template-columns:1fr}}.evidence-strip{{grid-template-columns:1fr}}.priority{{grid-template-columns:55px 1fr}}footer{{flex-direction:column}}}}
  @media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}[data-reveal]{{opacity:1;transform:none;transition:none}}}}
  @media print{{.topbar,.print{{display:none}}body{{background:white}}section{{break-inside:avoid;padding:45px 0}}[data-reveal]{{opacity:1;transform:none}}.pitch{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
  </style>
</head>
<body>
  <header class="topbar shell"><div class="brand"><span class="mark">FA</span> FPLAgent Research</div><nav><a href="#squad">The XV</a><a href="#method">Method</a><a href="#evidence">Evidence</a><a href="#limits">Limits</a></nav><button class="print" onclick="window.print()">Print paper</button></header>
  <main class="shell">
    <section class="hero" data-reveal>
      <div><div class="eyebrow">Technical white paper · 2026/27 · GW1</div><h1>The first<br>fifteen.</h1><p class="dek">How an independent FPL forecast, calibrated football markets, half a million legal squads and correlated match simulation produced one deadline-ready team.</p></div>
      <aside class="hero-note"><span class="verdict"><i></i>{_e(readiness['verdict'].replace('_',' '))}</span><div class="hero-meta"><div><span>Selected candidate</span><strong>{_e(decision['candidate_id'])}</strong></div><div><span>GW1 central xP</span><strong>{float(decision['expected_points']):.2f}</strong></div><div><span>Budget</span><strong>£{float(squad['budget_spent']):.1f}m</strong></div><div><span>Evidence frozen</span><strong>{_e(pack['freshness']['official_snapshot_at'][:10])}</strong></div></div></aside>
    </section>

    <section id="claim" data-reveal><div class="section-head"><div><span class="chapter">01 · The claim</span><h2>Confidence,<br>without theatre.</h2></div><p>The algorithm is strong enough to publish a coherent GW1 recommendation. It is not scientifically honest to call it universally state of the art before a matched external benchmark and untouched 2026/27 outcomes exist.</p></div><div class="bezel"><div class="panel claim-panel"><article class="claim good"><b>What the evidence supports</b><p>{_e(readiness['claim']['defensible'])}</p></article><article class="claim limit"><b>What it does not prove</b><p>{_e(readiness['claim']['not_defensible'])}</p></article></div></div></section>

    <section id="squad" data-reveal><div class="section-head"><div><span class="chapter">02 · The output</span><h2>The selected<br>GW1 squad.</h2></div><p>A {_e(squad['formation'])} built for this deadline and for inexpensive adaptation, not a fixed eight-week team. Bruno Fernandes is captain; Tarkowski is vice-captain. Every bench place is scored in exact autosub worlds after discovery.</p></div>
      <div class="score-grid"><div class="metric"><strong>{float(decision['expected_points']):.1f}</strong><span>Central GW1 xP</span></div><div class="metric"><strong>{_e(squad['formation'])}</strong><span>Starting shape</span></div><div class="metric"><strong>£{sum(float(x['price']) for x in bench):.1f}m</strong><span>GW1 bench</span></div><div class="metric"><strong>£{float(squad.get('bank',0)):.1f}m</strong><span>In the bank</span></div></div>
      <div class="bezel"><div class="pitch"><div>{pitch_rows}</div></div></div><div class="bench-label"><strong>Bench order</strong><small>Left to right · legal formation autosubs</small></div><div class="bench">{bench_cards}</div>
    </section>

    <section id="method" data-reveal><div class="section-head"><div><span class="chapter">03 · The engine</span><h2>Prediction is<br>only layer one.</h2></div><p>The useful object is not a list of player xP values. It is a decision policy: a legal 15, a legal XI, captaincy, bench order and plausible future transfers, evaluated together under the same uncertain match worlds.</p></div>
      <div class="layers"><div class="bezel"><article class="panel layer"><span class="layer-number">I</span><h3>Forecast</h3><ul><li>{int(metrics['training_rows']):,} deadline rows</li><li>{int(metrics['feature_count'])} point-in-time features</li><li>Position-specific XGBoost hurdle models</li><li>Appearance classes: DNP, 1–59, 60–89, 90+</li><li>FPL's own xP prohibited</li></ul></article></div><div class="bezel"><article class="panel layer"><span class="layer-number">II</span><h3>Simulate</h3><ul><li>Team goal and player component identities</li><li>Correlated match outcomes</li><li>Exact autosubs and captain fallback</li><li>Raw, anchored and high-goal worlds</li><li>Untouched selection/holdout seeds</li></ul></article></div><div class="bezel"><article class="panel layer"><span class="layer-number">III</span><h3>Decide</h3><ul><li>£100m, 2/5/5/3, max three per club</li><li>Open, fixed and rolled-GW2 policies</li><li>GW1–3, GW1–5 and GW1–8 views</li><li>Mean and downside-aware regret</li><li>Transactional evidence gate</li></ul></article></div></div>
      <div class="plain-tech"><article class="explain plain"><span class="eyebrow">In plain English</span><h3>We ask which team we would regret least.</h3><p>The model estimates who plays and what they score. The simulator then plays thousands of plausible versions of the fixtures. Squads that only look good under one fragile assumption fall away; legal teams that remain close to the best across several views survive.</p></article><article class="bezel"><div class="panel explain"><span class="eyebrow">Technical form</span><h3>A hurdle forecast feeding minimax-flavoured regret.</h3><code class="formula">xPᵢ = E[pointsᵢ | plays] × P(plays), with calibrated minute-class probabilities</code><code class="formula">R(c) = 0.75 Σₛ wₛ[max Vₛ − Vₛ(c)] + 0.25 maxₛ[max Vₛ − Vₛ(c)]</code><p><small>A central-regret cap prevents a stress-only winner from displacing a materially stronger base squad.</small></p></div></article></div>
    </section>

    <section id="search" data-reveal><div class="section-head"><div><span class="chapter">04 · Search</span><h2>From {int(funnel['combined_universe']):,}<br>to one.</h2></div><p>No single optimiser objective is trusted. Deterministic grids, local legal neighbours, distant MILP restarts and evolutionary squads create a diverse field before expensive exact simulation.</p></div>
      <div class="funnel"><div><strong>{int(funnel['combined_universe']):,}</strong><span>Legal combined universe</span></div><div><strong>{int(funnel['discovery_candidates']):,}</strong><span>Multi-objective discovery</span></div><div><strong>{int(funnel['shortlist']):,}</strong><span>Component screen</span></div><div><strong>{int(funnel['finalists']):,}</strong><span>Deep robust finalists</span></div><div><strong>{int(funnel['holdout_simulations']):,}</strong><span>Untouched worlds</span></div></div>
      <div class="evidence-strip"><div class="bezel"><article class="panel"><strong>{int(global_challenge['milp_generated']) + int(global_challenge['evolution_generated']):,}</strong><span>Distant MILP + evolutionary challengers</span><p>The best distant finalist still trailed the selected robust leader by {float((global_challenge.get('leader_minus_best_global') or {{}}).get('mean_delta') or 0):.2f} paired central points.</p></article></div><div class="bezel"><article class="panel"><strong>{int((horizon.get('funnel') or {{}})['deep_finalists'])}</strong><span>Eight-week policy finalists</span><p>The horizon audit solves legal future transfers, including a deliberate GW2 roll, rather than pretending the starting 15 is frozen.</p></article></div></div><p class="footnote">This is a broad adversarial search, not a mathematical certificate over every combinatorial roster under the nonlinear simulation objective. The distant search and protected alternatives reduce—without eliminating—search miss risk.</p>
    </section>

    <section id="data" data-reveal><div class="section-head"><div><span class="chapter">05 · Inputs</span><h2>What is signal.<br>What is opinion.</h2></div><p>Every source receives an authority level. More data is not automatically better: it must be timestamp-safe, mapped, replayable and improve legal decisions before it can change the squad.</p></div>
      <div class="bezel"><div class="panel" style="padding:24px 34px"><table class="source-table"><thead><tr><th>Source</th><th>What enters</th><th>Authority</th><th>Why</th></tr></thead><tbody>
        <tr><td>Official FPL</td><td>Rules, prices, positions, fixtures, status, realised points and lagged xG/xA/BPS/DC</td><td><span class="pill">Production</span></td><td>Canonical game state and labels. Its authored xP is explicitly excluded.</td></tr>
        <tr><td>Betfair Exchange</td><td>De-vigged 1X2 and over/under 2.5 → team goal/clean-sheet priors</td><td><span class="pill bounded">{100 * float(market_policy.get('preseason_weight') or 0):.0f}% DEF, preseason</span></td><td>10/10 GW1 fixtures; only the bounded policy passed the historical legal-decision gate.</td></tr>
        <tr><td>Team/player history</td><td>Lagged form, minutes, chance quality, set pieces, venue-adjusted team strength</td><td><span class="pill">Production</span></td><td>Strictly pre-deadline features; unavailable xG remains missing rather than backfilled from the future.</td></tr>
        <tr><td>FFScout + RotoWire</td><td>Predicted-start consensus</td><td><span class="pill bounded">Shadow</span></td><td>Visible for role review, zero forecast weight until prospective calibration passes.</td></tr>
        <tr><td>Understat</td><td>Prior-season npxG, xA, shots, key passes, xGChain and xGBuildup</td><td><span class="pill bounded">{_e(understat.get('verdict','Not run'))}</span></td><td>{int(understat_coverage.get('matched') or 0)}/{int(understat_coverage.get('players') or 0)} current players mapped. A time-forward legal replay selected {100 * float((understat.get('sequential_policy') or {{}}).get('selected_weight') or 0):.0f}% weight, so it remains independent shadow evidence rather than being forced into xP.</td></tr>
        <tr><td>SofaScore player-event feed</td><td>Independent chance, role and defensive event context</td><td><span class="pill shadow">Shadow replay</span></td><td>1,140 historical EPL matches are checksum-bound with 95–99% fail-closed identity mapping. The first frozen legal-policy challenger lost 15 points, so the feed has zero production weight pending a better validated feature model.</td></tr>
      </tbody></table></div></div>
    </section>

    <section id="evidence" data-reveal><div class="section-head"><div><span class="chapter">06 · Evidence</span><h2>The tests that<br>can say no.</h2></div><p>The strongest sign of a useful research system is not how often it says “promote,” but whether rejected challengers remain rejected and incomplete evidence fails closed.</p></div>
      <div class="score-grid"><div class="metric"><strong>{backtest_gate['mae_wins_vs_form5']}/{backtest_gate['slices']}</strong><span>MAE slices won</span></div><div class="metric"><strong>{backtest_gate['top_k_wins_vs_form5']}/{backtest_gate['slices']}</strong><span>Top-k slices won</span></div><div class="metric"><strong>+{float(picker_summary['total_actual_point_lift']):.0f}</strong><span>GW1 replay points</span></div><div class="metric"><strong>{len(quality.get('checks') or [])}/0</strong><span>Data checks / failures</span></div></div>
      <div class="gates">{gate_cards}</div>
    </section>

    <section id="tradeoff" data-reveal><div class="section-head"><div><span class="chapter">07 · The close call</span><h2>Why not the<br>GW1-only leader?</h2></div><p>The selected squad is not the maximum central GW1 projection. It is a declared season-opening robustness choice. That trade-off is visible so you can disagree with the risk policy rather than being handed a mysterious “optimal” team.</p></div>
      <div class="risk-grid"><div class="bezel"><article class="panel risk-box"><span class="eyebrow">Selected · {_e(decision['candidate_id'])}</span><h3>{_e(decision['formation'])} · {float(decision['expected_points']):.2f} published GW1 xP</h3><p>Five-week robust regret {float(five.get('robust_regret') or 0):.3f}; eight-week robust regret {float(eight.get('robust_regret') or 0):.3f}. It remains rank one in the historically gated five/eight-week synthesis.</p></article></div><article class="risk-box warning"><span class="eyebrow">GW1 structure leader · {_e(structure.get('stress_leader_id','—'))}</span><h3>+{float(structure_holdout.get('mean_delta') or 0):.2f} GW1 points in the independent holdout</h3><p>The 95% interval is {float(structure_holdout.get('delta_95ci_low') or 0):+.2f} to {float(structure_holdout.get('delta_95ci_high') or 0):+.2f}. It is a real alternative, but ranks {int(structure_reconciliation.get('challenger_synthesis_rank') or 0)} in the multiweek synthesis and carries {float(structure_reconciliation.get('challenger_synthesis_regret_delta') or 0):+.3f} more synthesis regret. A newly generated squad without that deep multiweek score would block publication.</p></article></div>
      <div class="bezel" style="margin-top:18px"><article class="panel risk-box"><span class="eyebrow">Eight-week challenger · {_e(alternative.get('candidate_id','—'))}</span><h3>{_e(alternative.get('gw1_formation','—'))} · {float(alt_delta.get('mean_delta') or 0):+.2f} weighted points over eight weeks</h3><p>It wins the central long-horizon view and a separate exhaustive baseline role/configuration replay ({float(baseline_residual.get('mean') or 0):+.2f} residual; {float(baseline_component.get('mean') or 0):+.2f} component). It has materially worse five-week high-goal/raw-component regret, however. The declared synthesis retains the lower combined-regret squad and marks the disagreement for live role verification rather than treating it as settled.</p></article></div>
      <div class="bezel" style="margin-top:18px"><article class="panel risk-box"><span class="eyebrow">Fresh bench/allocation selector · {_e(bench_targeted.get('candidate_id','—'))}</span><h3>A fresh rank-two result, not a material defeat.</h3><p>The targeted winner beat the active squad by only {float(bench_retention.get('active_minus_winner_regret') or 0):.3f} composite points, inside the {_e(bench_retention.get('practical_equivalence_regret','—'))} practical-equivalence bound. The active squad retained the lower worst-family regret ({float(bench_retention.get('active_family_worst_regret') or 0):.3f} vs {float(bench_retention.get('targeted_winner_family_worst_regret') or 0):.3f}) and won the original selector. The evidence therefore supports a practical tie resolved toward the less brittle squad—not a general rule to spend heavily on the bench.</p></article></div>
      <div class="bezel" style="margin-top:18px"><article class="panel risk-box"><span class="eyebrow">Immediate role watch · {int(role_summary.get('role_verification') or 0)} selected players flagged</span><h3>Ollie Watkins is the most important deadline verification.</h3><p>Official status is available and the model gives {100 * float((watkins.get('forecast') or {{}}).get('p_play') or 0):.0f}% play probability, but he appeared in {int(watkins_preseason.get('appearances') or 0)}/{int(watkins_preseason.get('eligible_team_matches') or 0)} eligible preseason lineups and {int(watkins_lineups.get('complete_source_count') or 0)} captured sources currently flag him as bench. Those sources have zero production weight; the scenario audit shows the counterfactual rather than silently overriding the model.</p></article></div>
    </section>

    <section id="limits" data-reveal><div class="section-head"><div><span class="chapter">08 · Frontier</span><h2>What would make<br>this genuinely SOTA.</h2></div><p>The gaps below are ordered by information value. None should be patched with an unvalidated scraper or an opinion-weight chosen because it changes the team.</p></div><div class="priority-list">{priority_rows}</div></section>

    <section id="receipts" data-reveal><div class="section-head"><div><span class="chapter">09 · Reproducibility</span><h2>The proof is<br>content-addressed.</h2></div><p>The paper is a readable index over machine artifacts. Hashes detect accidental mixing of forecasts, searches, reports and decisions from different generations.</p></div><div class="receipt-grid"><div><table class="receipt-table"><thead><tr><th>Artifact</th><th>SHA-256 prefix</th></tr></thead><tbody>{checksums}</tbody></table></div><div><h3>Primary references</h3><p><a href="https://fantasy.premierleague.com/help/" rel="noreferrer">Official FPL rules and help</a></p><p><a href="https://arxiv.org/abs/2508.09992" rel="noreferrer">OpenFPL: a public position-specific forecast benchmark</a></p><p><a href="https://github.com/daniegr/OpenFPL" rel="noreferrer">OpenFPL released implementation</a></p><p><a href="https://github.com/solioanalytics/open-fpl-solver" rel="noreferrer">Open FPL Solver: multi-period optimisation reference</a></p><p class="footnote">External references establish comparison targets and rule context. They do not contribute expected-points values to this squad.</p></div></div></section>
  </main>
  <footer class="shell"><span>FPLAgent · local research build · no FPL account writes</span><span>Generated {_e(now)} · {_e(VERSION)}</span></footer>
  <script>
  const io=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('visible');io.unobserve(e.target)}}}}),{{threshold:.08}});document.querySelectorAll('[data-reveal]').forEach(el=>io.observe(el));
  </script>
</body>
</html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return {
        "version": VERSION,
        "created_at": now,
        "output": str(output_path),
        "sha256": sha256_file(output_path),
        "bytes": output_path.stat().st_size,
        "candidate_id": decision["candidate_id"],
        "readiness_verdict": readiness["verdict"],
    }
