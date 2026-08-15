from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS

from .audit import QUALITY_JSON, audit_features
from .availability_watch import RECEIPT as AVAILABILITY_RECEIPT
from .bench_allocation_audit import RESULTS_JSON as BENCH_RESULTS
from .deadline_evidence import DEADLINE_STATUS_RECEIPT
from .decision_synthesis import DECISION_JSON
from .horizon_audit import RESULTS_JSON as HORIZON_RESULTS
from .market_odds import CURRENT_MARKET_RECEIPT
from .models import CURRENT_FORECAST_MANIFEST
from .paths import REPORTS
from .preseason_pipeline import GW1_PIPELINE_RECEIPT
from .robust_search import RESULTS_JSON as ROBUST_RESULTS
from .structure_stress import RESULTS_JSON as STRUCTURE_RESULTS
from .synthesis_selector_replay import RESULTS_JSON as SELECTOR_RESULTS

VERSION = "gw1_deadline_pack_v1"
RECEIPT = MANIFESTS / "gw1-deadline-pack.json"
REPORT = REPORTS / "gw1-deadline-pack.md"


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Invalid {label}: expected object")
    return value


def _render(result: dict[str, Any]) -> str:
    decision = result["decision"]
    squad = decision["squad"]
    lines = [
        "# GW1 deadline pack",
        "",
        f"Built: {result['created_at']}",
        "",
        (
            f"**{result['verdict']}** — `{decision['candidate_id']}` · "
            f"{decision['formation']} · {decision['expected_points']:.2f} GW1 xP."
        ),
        "",
        "## Publication gates",
        "",
    ]
    for name, row in result["gates"].items():
        lines.append(
            f"- {'PASS' if row['passed'] else 'FAIL'} — {name.replace('_', ' ')}: "
            f"{row['detail']}"
        )
    lines.extend(
        [
            "",
            "## Starting XI",
            "",
            "| Pos | Player | Team | Captaincy |",
            "|---|---|---|---|",
        ]
    )
    for player in squad["starters"]:
        captaincy = "C" if player["captain"] else "V" if player["vice_captain"] else ""
        lines.append(
            f"| {player['position']} | {player['name']} | {player['team']} | {captaincy} |"
        )
    lines.extend(["", "## Bench", "", "| Order | Pos | Player | Team |", "|---:|---|---|---|"])
    for order, player in enumerate(squad["bench"], start=1):
        lines.append(
            f"| {order} | {player['position']} | {player['name']} | {player['team']} |"
        )
    lines.extend(["", "## Resolved GW1-only trade-offs", ""])
    alternatives = result.get("role_scenario_alternatives") or []
    if alternatives:
        for row in alternatives:
            lines.append(
                f"- `{row['challenger_squad_id']}` wins the {row['scenario']} GW1-only replay "
                f"by at least {float(row['minimum_family_gain']):.3f} points, but ranks "
                f"{row['challenger_synthesis_rank']} across the multiweek synthesis and carries "
                f"{float(row['synthesis_regret_delta']):.3f} additional synthesis regret. It is "
                "retained as the strongest short-term alternative, not silently discarded."
            )
    else:
        lines.append("- No supported baseline or moderate role-scenario reversal.")
    lines.extend(
        [
            "",
            "## Evidence receipt",
            "",
            f"- Official/forecast observed: {result['freshness']['official_snapshot_at']}",
            f"- Decision generated: {result['freshness']['decision_created_at']}",
            f"- Decision checked: {result['freshness']['checked_at']}",
            (
                f"- Betting fixtures: {result['market']['fixture_count']}/10 from "
                f"{result['market']['provider']}"
            ),
            (
                f"- Defender market feature: "
                f"{100 * float(result['market']['defender_feature']['weight']):.0f}% bounded "
                "preseason blend"
            ),
            (
                f"- Global discovery universe: {result['search']['combined_universe']:,} legal "
                "local/global candidates"
            ),
            f"- Deep five-week finalists: {result['search']['robust_finalists']}",
            f"- Deep eight-week finalists: {result['search']['horizon_finalists']}",
            (
                f"- Participation frontier: "
                f"{result['participation_frontier']['candidate_count']} candidates / "
                f"{result['participation_frontier']['player_count']} players"
            ),
            "",
            "## Deadline instruction",
            "",
            (
                "Use this as the current recommendation, not a permanent lock. Run one final "
                "refresh after the last manager press conferences and before the FPL deadline. "
                "Any official availability, price, fixture or forecast checksum change invalidates "
                "this receipt and requires the complete pipeline again."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def build_deadline_pack(
    *,
    receipt_path: Path = RECEIPT,
    report_path: Path = REPORT,
    created_at: str | None = None,
) -> dict[str, Any]:
    quality = audit_features()
    pipeline = _load(GW1_PIPELINE_RECEIPT, "GW1 pipeline receipt")
    deadline = _load(DEADLINE_STATUS_RECEIPT, "deadline evidence receipt")
    decision = _load(DECISION_JSON, "synthesized decision")
    availability = _load(AVAILABILITY_RECEIPT, "availability watch")
    structure = _load(STRUCTURE_RESULTS, "structure stress")
    bench = _load(BENCH_RESULTS, "bench allocation audit")
    selector = _load(SELECTOR_RESULTS, "synthesis-selector replay")
    robust = _load(ROBUST_RESULTS, "global robust search")
    horizon = _load(HORIZON_RESULTS, "horizon audit")
    market = _load(CURRENT_MARKET_RECEIPT, "current market receipt")
    forecast_manifest = _load(CURRENT_FORECAST_MANIFEST, "current forecast manifest")

    decision_sha = sha256_file(DECISION_JSON)
    published_decision = (pipeline.get("published_artifacts") or {}).get("decision") or {}
    frontier = availability.get("decision_frontier") or {}
    decision_impacts = list(availability.get("decision_impacts") or [])
    selector_production = selector.get("production_configuration") or {}
    method = decision.get("method") or {}
    market_feature = (forecast_manifest.get("result") or {}).get("market_feature_policy") or {}
    checks = {
        "data_quality": (
            quality.get("status") == "pass",
            (
                f"{len(quality.get('checks') or [])} checks; "
                f"{len(quality.get('failed_checks') or [])} failures"
            ),
        ),
        "transactional_pipeline": (
            pipeline.get("status") == "published"
            and pipeline.get("published") is True
            and published_decision.get("sha256") == decision_sha,
            str(pipeline.get("status")),
        ),
        "deadline_evidence": (
            deadline.get("publishable") is True,
            f"issues={len(deadline.get('issues') or [])}",
        ),
        "availability_and_frontier": (
            availability.get("current") is True
            and frontier.get("complete_official_forecast_role_coverage") is True
            and int(frontier.get("candidate_count") or 0)
            == int(frontier.get("requested_candidate_count") or -1),
            (
                f"{frontier.get('candidate_count', 0)} finalists / "
                f"{frontier.get('player_count', 0)} players"
            ),
        ),
        "role_scenario_tradeoff_reconciled": (
            all(
                int(row.get("challenger_synthesis_rank") or 0) > 1
                and float(row.get("synthesis_regret_delta") or 0.0) > 0.0
                for row in decision_impacts
            ),
            (
                f"{len(decision_impacts)} supported GW1-only alternatives; all carry positive "
                "multiweek synthesis regret"
                if decision_impacts
                else "no supported baseline/moderate alternative"
            ),
        ),
        "historical_selector": (
            float(selector_production.get("horizon_family_weight", -1))
            == float(method.get("horizon_family_weight", -2))
            and float(selector_production.get("family_worst_weight", -1))
            == float(method.get("family_worst_weight", -2)),
            (
                f"{selector.get('verdict')} at "
                f"{selector_production.get('horizon_family_weight')}/"
                f"{selector_production.get('family_worst_weight')}"
            ),
        ),
        "scoring_formation_autosubs": (
            structure.get("publishable") is True
            and (structure.get("lineage") or {}).get("decision_sha256") == decision_sha,
            f"{structure.get('verdict')} · leader {structure.get('stress_leader_id')}",
        ),
        "bench_allocation": (
            (bench.get("verdict") or {}).get("promotable") is True
            and (bench.get("lineage") or {}).get("synthesis_sha256") == decision_sha,
            str((bench.get("verdict") or {}).get("status")),
        ),
        "betting_market": (
            market.get("status") == "ready"
            and int(market.get("fixture_count") or 0) == 10
            and 1 in set(map(int, market.get("ready_events") or [])),
            f"{market.get('provider')} · {market.get('fixture_count')}/10",
        ),
        "defender_market_feature": (
            market_feature.get("status") == "applied"
            and market_feature.get("decision_authority") is True
            and float(market_feature.get("weight") or 0.0) == 0.20
            and int(market_feature.get("fixtures") or 0) == 10,
            (
                f"{100 * float(market_feature.get('weight') or 0.0):.0f}% DEF-only · "
                f"{market_feature.get('fixtures', 0)}/10 fixtures"
            ),
        ),
        "global_search": (
            int((robust.get("funnel") or {}).get("combined_universe") or 0) >= 100_000
            and int((robust.get("global_challenge") or {}).get("finalists") or 0) > 0,
            f"{(robust.get('funnel') or {}).get('combined_universe', 0)} candidates",
        ),
    }
    gates = {
        name: {"passed": bool(passed), "detail": detail}
        for name, (passed, detail) in checks.items()
    }
    selected = decision["decision"]
    expected = float(selected["candidate"]["lineups"]["1"]["expected_points"])
    result = {
        "version": VERSION,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "verdict": "DEADLINE_READY" if all(row["passed"] for row in gates.values()) else "BLOCKED",
        "publishable": all(row["passed"] for row in gates.values()),
        "gates": gates,
        "decision": {
            "candidate_id": selected["candidate_id"],
            "formation": selected["formation"],
            "expected_points": expected,
            "synthesis_regret": selected["synthesis_regret"],
            "squad": selected["squad"],
        },
        "freshness": {
            "official_snapshot_at": (deadline.get("official") or {}).get("observed_at"),
            "decision_created_at": decision.get("created_at"),
            "checked_at": deadline.get("checked_at"),
        },
        "market": {
            "provider": market.get("provider"),
            "fixture_count": market.get("fixture_count"),
            "created_at": market.get("created_at"),
            "semantic_fingerprint": market.get("semantic_fingerprint"),
            "defender_feature": market_feature,
        },
        "search": {
            "combined_universe": (robust.get("funnel") or {}).get("combined_universe"),
            "robust_finalists": (robust.get("funnel") or {}).get("finalists"),
            "horizon_finalists": (horizon.get("funnel") or {}).get("deep_finalists"),
        },
        "participation_frontier": {
            key: frontier.get(key)
            for key in (
                "candidate_count",
                "player_count",
                "attention_player_count",
                "predicted_lineup_coverage",
            )
        },
        "role_scenario_alternatives": decision_impacts,
        "lineage": {
            "decision_sha256": decision_sha,
            "pipeline_sha256": sha256_file(GW1_PIPELINE_RECEIPT),
            "deadline_evidence_sha256": sha256_file(DEADLINE_STATUS_RECEIPT),
            "availability_sha256": sha256_file(AVAILABILITY_RECEIPT),
            "structure_stress_sha256": sha256_file(STRUCTURE_RESULTS),
            "bench_allocation_sha256": sha256_file(BENCH_RESULTS),
            "selector_replay_sha256": sha256_file(SELECTOR_RESULTS),
            "data_quality_sha256": sha256_file(QUALITY_JSON),
            "forecast_manifest_sha256": sha256_file(CURRENT_FORECAST_MANIFEST),
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render(result), encoding="utf-8")
    return result
