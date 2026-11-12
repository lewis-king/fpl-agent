from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .artifact_lineage import load_json_artifact
from .deadline_contingencies import RESULTS_JSON as CONTINGENCY_RESULTS
from .deadline_pack import RECEIPT as DEADLINE_PACK
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .gw1_chip_decision import RESULTS_JSON as CHIP_RESULTS
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .preseason_pipeline import GW1_PIPELINE_RECEIPT

VERSION = "deadline_execution_receipt_v1"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "gw1-deadline-execution.md"
HTML_REPORT = REPORTS / "gw1-deadline-execution.html"


def build_complete_deadline_handoff(
    *,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    chip_simulations: int = 25_000,
) -> dict[str, Any]:
    """Build every checksum-bound artifact required for a human GW1 hand-off."""

    # Local imports avoid making the compact receipt renderer the dependency root
    # for the simulation modules it orchestrates.
    from .deadline_contingencies import build_deadline_contingencies
    from .deadline_pack import build_deadline_pack
    from .deadline_stability import run_deadline_stability_audit
    from .gw1_chip_decision import run_gw1_chip_decision
    from .participation_break_even import run_participation_break_even_audit

    stability = run_deadline_stability_audit()
    break_even = run_participation_break_even_audit(
        selection_simulations=selection_simulations,
        holdout_simulations=holdout_simulations,
    )
    contingencies = build_deadline_contingencies()
    chip = run_gw1_chip_decision(simulations=chip_simulations)
    pack = build_deadline_pack()
    execution = build_deadline_execution_receipt()
    return {
        "status": "published" if execution["ready_to_enter"] else "blocked",
        "published": bool(execution["ready_to_enter"]),
        "stability": {
            "verdict": stability["verdict"],
            "production_winner_counts": stability["gate"]["production_winner_counts"],
        },
        "break_even": {
            "decision_candidate_id": break_even["decision_candidate_id"],
            "players": [row["name"] for row in break_even["players"].values()],
        },
        "contingencies": contingencies["summary"],
        "chip": chip["recommendation"],
        "deadline_pack": pack["verdict"],
        "execution": execution,
    }


def _canonical_decision(decision: dict[str, Any]) -> dict[str, Any]:
    selected = decision["decision"]
    squad = selected["squad"]
    return {
        "candidate_id": str(selected["candidate_id"]),
        "formation": str(selected["formation"]),
        "starters": [
            {
                "element": int(player["element"]),
                "name": str(player["name"]),
                "position": str(player["position"]),
                "team": str(player["team"]),
                "price": float(player["price"]),
            }
            for player in squad["starters"]
        ],
        "bench": [
            {
                "element": int(player["element"]),
                "name": str(player["name"]),
                "position": str(player["position"]),
                "team": str(player["team"]),
                "price": float(player["price"]),
            }
            for player in squad["bench"]
        ],
        "captain": next(
            {
                "element": int(player["element"]),
                "name": str(player["name"]),
            }
            for player in squad["starters"]
            if player["captain"]
        ),
        "vice_captain": next(
            {
                "element": int(player["element"]),
                "name": str(player["name"]),
            }
            for player in squad["starters"]
            if player["vice_captain"]
        ),
        "budget_spent": float(squad["budget_spent"]),
        "bank": float(squad["bank"]),
    }


def _central_route_matches(canonical: dict[str, Any], contingency: dict[str, Any]) -> bool:
    central = next(
        (route for route in contingency.get("routes") or [] if route.get("route_id") == "central"),
        None,
    )
    if central is None:
        return False
    route = central["route"]
    return (
        str(route["squad_id"]) == canonical["candidate_id"]
        and list(map(int, route["starter_elements"]))
        == [player["element"] for player in canonical["starters"]]
        and list(map(int, route["bench_elements"]))
        == [player["element"] for player in canonical["bench"]]
        and int(route["captain_element"]) == canonical["captain"]["element"]
        and int(route["vice_captain_element"]) == canonical["vice_captain"]["element"]
    )


def build_deadline_execution_receipt(
    *,
    created_at: str | None = None,
    decision_path: Path = SYNTHESIZED_DECISION,
    pack_path: Path = DEADLINE_PACK,
    contingency_path: Path = CONTINGENCY_RESULTS,
    chip_path: Path = CHIP_RESULTS,
    pipeline_path: Path = GW1_PIPELINE_RECEIPT,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
    html_path: Path = HTML_REPORT,
) -> dict[str, Any]:
    ensure_engine_layout()
    decision = load_json_artifact(decision_path, "synthesized GW1 decision")
    pack = load_json_artifact(pack_path, "GW1 deadline pack")
    contingency = load_json_artifact(contingency_path, "deadline contingencies")
    chip = load_json_artifact(chip_path, "GW1 chip decision")
    pipeline = load_json_artifact(pipeline_path, "GW1 pipeline receipt")
    canonical = _canonical_decision(decision)
    decision_sha = sha256_file(decision_path)
    prospective = dict(pipeline.get("prospective_contract") or {})
    prospective_path = Path(str(prospective.get("path") or ""))
    prospective_receipt = (
        load_json_artifact(prospective_path, "GW1 prospective contract")
        if prospective_path.is_file()
        else {}
    )
    checks = {
        "deadline_pack_publishable": pack.get("publishable") is True,
        "deadline_pack_candidate_matches": str((pack.get("decision") or {}).get("candidate_id"))
        == canonical["candidate_id"],
        "deadline_pack_lineage_matches": (pack.get("lineage") or {}).get("decision_sha256")
        == decision_sha,
        "contingency_lineage_matches": (contingency.get("lineage") or {}).get("decision_sha256")
        == decision_sha,
        "contingencies_are_legal": (contingency.get("summary") or {}).get("all_legal") is True,
        "central_route_matches_byte_intent": _central_route_matches(canonical, contingency),
        "chip_candidate_matches": str(chip.get("candidate_id")) == canonical["candidate_id"],
        "chip_lineage_matches": (chip.get("lineage") or {}).get("decision_sha256") == decision_sha,
        "chip_is_actionable": (chip.get("recommendation") or {}).get("actionable") is True,
        "pipeline_published": pipeline.get("status") == "published"
        and pipeline.get("published") is True,
        "prospective_contract_current": (
            prospective_path.is_file()
            and prospective.get("sha256") == sha256_file(prospective_path)
            and str(prospective_receipt.get("selected_action_id")) == canonical["candidate_id"]
        ),
        "one_captain_and_vice": canonical["captain"]["element"]
        != canonical["vice_captain"]["element"],
        "exact_budget": abs(canonical["budget_spent"] + canonical["bank"] - 100.0) < 1e-6,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "version": VERSION,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "event": 1,
        "verdict": "READY_TO_ENTER" if not failed else "BLOCKED",
        "ready_to_enter": not failed,
        "checks": checks,
        "failed_checks": failed,
        "decision": canonical,
        "chip": chip["recommendation"],
        "contingencies": [
            {
                "route_id": route["route_id"],
                "call_name": route["call_name"],
                "status": route["status"],
                "trigger": route["trigger"],
                "candidate_id": route["route"]["squad_id"],
            }
            for route in contingency["routes"]
        ],
        "freshness": pack.get("freshness"),
        "prospective_contract": prospective,
        "lineage": {
            "decision_sha256": decision_sha,
            "deadline_pack_sha256": sha256_file(pack_path),
            "contingencies_sha256": sha256_file(contingency_path),
            "chip_decision_sha256": sha256_file(chip_path),
            "pipeline_sha256": sha256_file(pipeline_path),
        },
        "manual_confirmation": [
            "The 15 names and prices on the FPL transfer screen match this receipt.",
            "The starting XI and formation match this receipt.",
            "The bench order is entered left-to-right exactly as shown.",
            "Captain and vice-captain badges match this receipt.",
            "The chip state matches the explicit chip recommendation.",
            "No new official or attributable participation evidence arrived after this receipt.",
        ],
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_markdown(result), encoding="utf-8")
    html_path.write_text(_render_html(result), encoding="utf-8")
    return result


def _render_markdown(result: dict[str, Any]) -> str:
    decision = result["decision"]
    lines = [
        "# GW1 canonical execution receipt",
        "",
        f"**{result['verdict']}** · `{decision['candidate_id']}` · {result['created_at']}",
        "",
        (
            f"Budget £{decision['budget_spent']:.1f}m · bank £{decision['bank']:.1f}m · "
            f"{decision['formation']} · chip **{result['chip']['label']}**."
        ),
        "",
        "## Starting XI",
        "",
        "| Position | Player | Club | Price | Marker |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for player in decision["starters"]:
        marker = (
            "C"
            if player["element"] == decision["captain"]["element"]
            else "V"
            if player["element"] == decision["vice_captain"]["element"]
            else ""
        )
        lines.append(
            f"| {player['position']} | {player['name']} | {player['team']} | "
            f"£{player['price']:.1f}m | {marker} |"
        )
    lines.extend(["", "## Bench", ""])
    for index, player in enumerate(decision["bench"], start=1):
        lines.append(
            f"{index}. **{player['name']}** · {player['position']} · {player['team']} · "
            f"£{player['price']:.1f}m"
        )
    lines.extend(["", "## Publication checks", ""])
    for name, passed in result["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}")
    lines.extend(["", "## Manual confirmation", ""])
    lines.extend(f"- [ ] {item}" for item in result["manual_confirmation"])
    lines.append("")
    return "\n".join(lines)


def _render_html(result: dict[str, Any]) -> str:
    decision = result["decision"]
    player_cards = []
    for player in decision["starters"]:
        marker = (
            "C"
            if player["element"] == decision["captain"]["element"]
            else "V"
            if player["element"] == decision["vice_captain"]["element"]
            else ""
        )
        player_cards.append(
            "<article class='player'><span>"
            + html.escape(player["position"])
            + "</span><strong>"
            + html.escape(player["name"])
            + "</strong><small>"
            + html.escape(player["team"])
            + f" · £{player['price']:.1f}m</small>"
            + (f"<b>{marker}</b>" if marker else "")
            + "</article>"
        )
    bench = "".join(
        f"<li><i>{index}</i><span><strong>{html.escape(player['name'])}</strong>"
        f"<small>{html.escape(player['position'])} · {html.escape(player['team'])} · "
        f"£{player['price']:.1f}m</small></span></li>"
        for index, player in enumerate(decision["bench"], start=1)
    )
    checks = "".join(
        f"<li class='{'pass' if passed else 'fail'}'><span>{'✓' if passed else '×'}</span>"
        f"{html.escape(name.replace('_', ' '))}</li>"
        for name, passed in result["checks"].items()
    )
    manual = "".join(
        f"<li><span></span>{html.escape(item)}</li>" for item in result["manual_confirmation"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FPLAgent · GW1 execution receipt</title><style>
:root{{--ink:#15231c;--muted:#69756e;--paper:#f4f3eb;--card:#fffef8;--green:#164d37;--lime:#d8ef57;--line:#d8ddd5}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{width:min(1180px,calc(100% - 32px));margin:28px auto 60px}}header{{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end;padding:34px;border-radius:28px;background:var(--green);color:white}}
.eyebrow{{font:700 11px/1.2 ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--lime)}}h1{{max-width:720px;margin:10px 0 0;font-size:clamp(38px,6vw,76px);line-height:.92;letter-spacing:-.06em}}.status{{text-align:right}}.status strong{{display:block;font-size:20px;color:var(--lime)}}.status small{{opacity:.68}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin:18px 0;background:var(--line);border:1px solid var(--line);border-radius:18px;overflow:hidden}}.metrics div{{padding:18px;background:var(--card)}}.metrics span,.player span{{display:block;color:var(--muted);font-size:10px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}}.metrics strong{{display:block;margin-top:4px;font-size:22px}}
.layout{{display:grid;grid-template-columns:1.4fr .8fr;gap:18px}}section{{padding:24px;border:1px solid var(--line);border-radius:22px;background:var(--card)}}h2{{margin:0 0 18px;font-size:18px}}.xi{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.player{{position:relative;min-height:92px;padding:14px;border:1px solid var(--line);border-radius:14px}}.player strong{{display:block;margin-top:8px}}.player small{{display:block;color:var(--muted)}}.player b{{position:absolute;top:10px;right:10px;display:grid;place-items:center;width:25px;height:25px;border-radius:50%;background:var(--lime);color:var(--ink)}}
ol,ul{{list-style:none;margin:0;padding:0}}.bench li{{display:flex;gap:12px;padding:13px 0;border-top:1px solid var(--line)}}.bench i{{display:grid;place-items:center;width:25px;height:25px;border-radius:50%;background:var(--ink);color:white;font-style:normal;font-size:11px}}.bench small{{display:block;color:var(--muted)}}.checks{{margin-top:18px}}.checks li{{display:flex;gap:10px;padding:8px 0;color:var(--muted)}}.checks li span{{font-weight:900;color:var(--green)}}.checks .fail span{{color:#a33}}.manual{{margin-top:18px}}.manual li{{display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--line)}}.manual li span{{width:18px;height:18px;border:1px solid var(--ink);border-radius:4px;flex:0 0 auto}}
footer{{margin-top:18px;color:var(--muted);font:11px/1.5 ui-monospace,monospace}}@media(max-width:800px){{header,.layout{{grid-template-columns:1fr}}.status{{text-align:left}}.metrics{{grid-template-columns:repeat(2,1fr)}}.xi{{grid-template-columns:repeat(2,1fr)}}}}@media print{{body{{background:white}}main{{width:100%;margin:0}}}}
</style></head><body><main><header><div><span class="eyebrow">FPLAgent · canonical hand-off</span><h1>One squad.<br>One receipt.</h1></div><div class="status"><strong>{html.escape(result["verdict"])}</strong><small>{html.escape(result["created_at"])}<br>{html.escape(decision["candidate_id"])}</small></div></header>
<div class="metrics"><div><span>Formation</span><strong>{html.escape(decision["formation"])}</strong></div><div><span>Spend</span><strong>£{decision["budget_spent"]:.1f}m</strong></div><div><span>Bank</span><strong>£{decision["bank"]:.1f}m</strong></div><div><span>Chip</span><strong>{html.escape(result["chip"]["label"])}</strong></div></div>
<div class="layout"><section><h2>Starting XI</h2><div class="xi">{"".join(player_cards)}</div></section><aside><section><h2>Bench · left to right</h2><ol class="bench">{bench}</ol></section><section class="checks"><h2>Machine checks</h2><ul>{checks}</ul></section></aside></div>
<section class="manual"><h2>Confirm in the official game</h2><ul>{manual}</ul></section><footer>Decision SHA-256 · {html.escape(result["lineage"]["decision_sha256"])}<br>This receipt is invalidated by a material official, forecast, market or participation checksum change.</footer></main></body></html>"""
