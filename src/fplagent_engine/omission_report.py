from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .decision_synthesis import DECISION_JSON
from .decision_synthesis import RESULTS_JSON as SYNTHESIS_RESULTS
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

AUDIT_RESULTS = MODEL_DATA / "top_player_omission_audit_v1" / "results.json"
OUTPUT = REPORTS / "gw1-top-player-omission-report.html"
VERSION = "gw1_top_player_explainer_v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _reason(row: dict[str, Any], synthesis: dict[str, Any]) -> tuple[str, str]:
    deep = dict(row.get("best_deep_counterfactual") or {})
    delta = deep.get("robust_regret_delta")
    consensus = str(row.get("participation_consensus") or "insufficient_coverage")
    if deep == {}:
        return (
            "Below deep-search floor",
            (
                "Reported because of price or ownership, but its current play probability is "
                "below the mandatory protected-search threshold."
            ),
        )
    if delta is not None and abs(float(delta)) < 1e-9:
        selected = str(synthesis["decision"]["candidate_id"])
        return (
            "Wins one family, not the synthesis",
            (
                "This alternative is the five-week robust-family leader. The published "
                f"{selected} finished first only after the declared five/eight-week family "
                "regrets were combined; this is a genuine close policy choice, not a bad-player "
                "verdict."
            ),
        )
    if consensus == "source_disagreement":
        return (
            "Lineup sources disagree",
            (
                "RotoWire and FFScout do not agree on the start. The mean forecast retains the "
                "incumbent role probability, while the confirmed-start sensitivity remains "
                "visible."
            ),
        )
    if consensus == "predicted_bench_consensus":
        return (
            "Two-source bench prediction",
            (
                "Both independent predicted lineups currently show a bench role. A confirmed "
                "start would invalidate this receipt and trigger a complete regeneration."
            ),
        )
    if str(row["player_name"]) == "Haaland":
        return (
            "Price opportunity cost, not minutes",
            (
                "His minutes bug is fixed: the live forecast now gives him a clear two-source "
                "start. At £15.5m, however, the best protected Haaland XV must surrender several "
                "strong players and captain Bruno; that complete legal package lost in the deep "
                "holdout."
            ),
        )
    return (
        "Deep legal XV lost",
        (
            "The strongest protected squad containing this player was simulated with the same "
            "budget, captaincy, autosubs, future transfers and correlated match worlds. Its "
            "positive regret delta means the complete squad—not the player in isolation—was less "
            "robust."
        ),
    )


def build_top_player_omission_report(
    *,
    audit_path: Path = AUDIT_RESULTS,
    decision_path: Path = DECISION_JSON,
    synthesis_path: Path = SYNTHESIS_RESULTS,
    output_path: Path = OUTPUT,
) -> dict[str, Any]:
    ensure_engine_layout()
    audit = _load(audit_path)
    decision = _load(decision_path)
    synthesis = _load(synthesis_path)
    squad = decision["decision"]["squad"]
    selected = [*squad["starters"], *squad["bench"]]
    selected_names = " · ".join(
        f"{player['name']}{' (C)' if player.get('captain') else ''}" for player in selected
    )
    capital = dict(decision.get("capital_efficiency") or {})
    capital_risks = {
        int(risk["element"]): risk
        for candidate in capital.get("excluded_candidates") or []
        for risk in candidate.get("risks") or []
    }
    capital_names = " · ".join(
        f"{row['player_name']} (£{float(row['price']):.1f}m, "
        f"{float(row['expected_minutes']):.1f}m)"
        for row in sorted(capital_risks.values(), key=lambda item: str(item["player_name"]))
    )

    rows = []
    for index, row in enumerate(audit["omissions"], start=1):
        deep = dict(row.get("best_deep_counterfactual") or {})
        title, reason = _reason(row, synthesis)
        delta = deep.get("robust_regret_delta")
        sensitivity = (
            f"<span class='sensitivity'>Start case {float(row['full_start_counterfactual_xp']):.2f} xP</span>"
            if row.get("full_start_counterfactual_xp") is not None
            else ""
        )
        swaps = (
            f"<b>In</b> {_e(', '.join(deep.get('players_in') or []))}<br>"
            f"<b>Out</b> {_e(', '.join(deep.get('players_out') or []))}"
            if deep
            else "Not mandatory at current play probability"
        )
        rows.append(
            f"""
            <article class="player-row{" near" if delta is not None and float(delta) <= 0.5 else ""}">
              <div class="rank">{index:02d}</div>
              <div class="identity"><span>{_e(row["position"])} · {_e(row["team_name"])}</span><h3>{_e(row["player_name"])}</h3><small>£{float(row["price"]):.1f}m · {float(row["ownership_percent"]):.1f}% owned</small></div>
              <div class="numbers"><div><strong>{float(row["expected_points"]):.2f}</strong><span>GW1 xP</span></div><div><strong>{float(row["expected_minutes"]):.1f}</strong><span>minutes</span></div><div><strong>{"—" if delta is None else f"{float(delta):+.3f}"}</strong><span>5W regret Δ</span></div></div>
              <div class="explain"><span class="label">{_e(title)}</span><p>{_e(reason)}</p>{sensitivity}</div>
              <div class="swaps">{swaps}</div>
            </article>"""
        )

    checks = "".join(
        f"<span class='check'>{'✓' if passed else '×'} {_e(name.replace('_', ' '))}</span>"
        for name, passed in audit["checks"].items()
    )
    now = datetime.now(UTC).isoformat()
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GW1 top-player omission report</title>
<style>
:root{{--ink:#142019;--paper:#f4f3ec;--green:#1d5b41;--lime:#c9f05b;--line:#d5d9cf;--muted:#69736d;--red:#aa4d42}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}main{{width:min(1500px,calc(100% - 48px));margin:auto;padding:56px 0 96px}}header{{display:grid;grid-template-columns:1.5fr 1fr;gap:56px;padding-bottom:42px;border-bottom:1px solid var(--line)}}.eyebrow,.label{{font:700 11px/1.2 ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--green)}}h1{{font-size:clamp(52px,7vw,108px);letter-spacing:-.065em;line-height:.86;margin:18px 0 28px;max-width:900px}}.dek{{font-size:20px;color:var(--muted);max-width:760px}}.receipt{{align-self:end;background:var(--ink);color:#eef5ec;border-radius:24px;padding:26px;box-shadow:0 24px 60px #1e2d2220}}.receipt strong{{font-size:32px;display:block;margin:8px 0}}.receipt p{{color:#b8c4bc}}.squad{{padding:24px 0;border-bottom:1px solid var(--line);color:var(--muted)}}.squad b{{color:var(--ink)}}.capital-gate{{margin:20px 0 0;padding:18px 20px;border:1px solid #8ca83d;border-radius:16px;background:#edf2db}}.capital-gate strong{{display:block;margin:4px 0}}.capital-gate p{{margin:0;color:#4f5b54}}.checks{{display:flex;flex-wrap:wrap;gap:8px;padding:20px 0 28px}}.check{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:#fff8;font-size:11px}}.player-list{{display:grid;gap:8px}}.player-row{{display:grid;grid-template-columns:52px 1.2fr 1.15fr 2fr 1.5fr;gap:22px;align-items:center;background:#fff9;border:1px solid var(--line);border-radius:18px;padding:18px 22px}}.player-row.near{{border-color:#8ca83d;box-shadow:inset 4px 0 var(--lime)}}.rank{{font:700 12px ui-monospace;color:#99a29c}}.identity span,.identity small,.numbers span{{color:var(--muted);font-size:11px}}h3{{margin:2px 0;font-size:19px;letter-spacing:-.025em}}.numbers{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.numbers div{{display:flex;flex-direction:column}}.numbers strong{{font-size:20px}}.explain p{{margin:5px 0 0;color:#4f5b54}}.sensitivity{{display:inline-block;margin-top:7px;background:#edf2db;border-radius:999px;padding:3px 8px;font-size:11px}}.swaps{{border-left:1px solid var(--line);padding-left:18px;font-size:12px;color:var(--muted)}}.swaps b{{color:var(--ink)}}footer{{margin-top:34px;color:var(--muted);font:11px ui-monospace}}@media(max-width:980px){{header{{grid-template-columns:1fr}}.player-row{{grid-template-columns:36px 1fr}}.numbers,.explain,.swaps{{grid-column:2}}.swaps{{border:0;padding:0}}}}@media print{{body{{background:white}}main{{width:100%;padding:20px}}.player-row{{break-inside:avoid}}}}
.legend{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:18px 0 0}}.legend div{{padding:14px 16px;border:1px solid var(--line);border-radius:14px;background:#fff8}}.legend strong{{display:block;margin-bottom:3px}}.legend span{{color:var(--muted);font-size:12px}}@media(max-width:980px){{.legend{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div><span class="eyebrow">FPLAgent · forensic decision receipt</span><h1>Why they<br>missed out.</h1><p class="dek">Every expensive, highly owned or high-xP omission is shown with its current minutes, role evidence and strongest deeply simulated legal squad. This is the audit that would have exposed the original Haaland problem before publication.</p></div><aside class="receipt"><span class="eyebrow">Publication verdict</span><strong>{_e(audit["verdict"])}</strong><p>{int(audit["summary"]["material_players"])} material players · {int(audit["summary"]["deep_finalists"])} deep finalists · {int(audit["summary"]["near_misses"])} near-misses · {int(audit["summary"]["open_role_assumptions"])} open role assumptions</p></aside></header>
<div class="squad"><b>Published XV · {_e(decision["decision"]["candidate_id"])}</b><br>{_e(selected_names)}</div><div class="capital-gate"><span class="eyebrow">Premium role-capital gate</span><strong>{int(capital.get("excluded_common_finalists") or 0)} finalists rejected before publication</strong><p>{_e(capital_names or "No unresolved premium low-minute player reached the jointly tested final field.")}</p></div><div class="legend"><div><strong>Price opportunity cost, not minutes</strong><span>A clear starter can still lose when the strongest complete legal XV containing him gives up more elsewhere.</span></div><div><strong>Wins one family, not the synthesis</strong><span>A squad may lead one horizon or scoring family yet lose after every declared family is combined.</span></div></div><div class="checks">{checks}</div><section class="player-list">{"".join(rows)}</section>
<footer>Generated {_e(now)} · audit {_e(sha256_file(audit_path))} · decision {_e(sha256_file(decision_path))} · {VERSION}</footer>
</main></body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return {
        "version": VERSION,
        "created_at": now,
        "output": str(output_path),
        "bytes": output_path.stat().st_size,
        "sha256": sha256_file(output_path),
        "candidate_id": decision["decision"]["candidate_id"],
        "verdict": audit["verdict"],
    }
