"""Outcome review: public actual picks versus immutable pre-deadline advice.

No forecasts are retrained here, no recommendation is regenerated and no FPL
account is written. Hindsight differences are diagnostics, not attainable gains.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fplagent_data.elite_sample import load_elite_sample, scoreboard
from fplagent_data.event_outcomes import archive_event_outcome, latest_event_outcome
from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import archive_official_payloads

from .paths import MODEL_DATA
from .policy_evidence import summarize_policy_evidence
from .prospective_scoring import ProspectiveScoringError, score_weekly_event

ROOT = MODEL_DATA / "gameweek_review_v1"


def _write(path: Path, payload: dict, *, immutable: bool = False) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_text() != text:
            raise ValueError("Immutable gameweek review source changed")
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def sync_finalized_decision_scores(events: list[int]) -> dict[str, Any]:
    """Close the feedback loop on every normal refresh, without auto-promoting models."""
    from .prospective_dashboard import build_prospective_scoreboard

    rows, scored = [], []
    for event in sorted(set(events)):
        try:
            result = score_weekly_event(event)
            scored.append(result)
            rows.append(
                {"event": event, "status": "scored", "receipt_path": result["receipt_path"]}
            )
        except (ProspectiveScoringError, OSError, ValueError, KeyError) as exc:
            rows.append({"event": event, "status": "needs_review", "reason": str(exc)})
    try:
        board = build_prospective_scoreboard()
        scoreboard = {"status": board["status"], "completed_events": board["completed_events"]}
    except (ValueError, OSError, KeyError) as exc:
        scoreboard = {"status": "needs_review", "reason": str(exc)}
    try:
        policy_evidence = summarize_policy_evidence(scored)
    except (ValueError, TypeError, KeyError) as exc:
        policy_evidence = {"status": "unavailable", "reason": str(exc),
                           "decision_authority": False}
    try:
        from .forecast_diagnosis import save_diagnosis
        diagnosis = save_diagnosis()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        diagnosis = {"status": "unavailable", "reason": str(exc), "decision_authority": False}
    return {"events": rows, "scoreboard": scoreboard, "decision_authority": False,
            "policy_evidence": policy_evidence, "forecast_diagnosis": diagnosis}


def reconcile_event(
    *,
    history: dict,
    picks: dict,
    live: dict,
    bootstrap: dict,
    score: dict | None,
    score_error: str | None = None,
) -> dict:
    event = int(history["event"])
    event_info = next(e for e in bootstrap["events"] if e["id"] == event)
    if event_info.get("finished") is not True or event_info.get("data_checked") is not True:
        raise ValueError("Review requires final and data-checked official outcomes")
    locked = picks["picks"]
    ids = [int(p["element"]) for p in locked]
    if len(ids) != 15 or len(set(ids)) != 15 or picks["entry_history"]["event"] != event:
        raise ValueError("Official picks do not contain one complete squad for this event")
    stats = {int(p["id"]): p["stats"] for p in live["elements"]}
    if set(ids) - set(stats):
        raise ValueError("Official result is missing a selected player's outcome")
    gross = sum(int(stats[p["element"]]["total_points"]) * int(p["multiplier"]) for p in locked)
    if gross != int(history["points"]) or gross != int(picks["entry_history"]["points"]):
        raise ValueError("Official player points do not reconcile with manager history")
    hit = int(history["event_transfers_cost"])
    if hit < 0 or hit % 4 or hit != int(picks["entry_history"]["event_transfers_cost"]):
        raise ValueError("Official transfer hit is inconsistent")
    names = {int(p["id"]): p["web_name"] for p in bootstrap["elements"]}
    forecasts = {p["element"]: p for p in (score or {}).get("selected_squad_player_outcomes", [])}
    players = []
    for pick in sorted(locked, key=lambda p: p["position"]):
        element = int(pick["element"])
        actual = stats[element]
        forecast = forecasts.get(element, {})
        players.append(
            {
                "element": element,
                "name": names.get(element, forecast.get("player_name", str(element))),
                "slot": int(pick["position"]),
                "multiplier": int(pick["multiplier"]),
                "captain": bool(pick["is_captain"]),
                "vice_captain": bool(pick["is_vice_captain"]),
                "actual_points": int(actual["total_points"]),
                "actual_minutes": int(actual["minutes"]),
                "contribution": int(actual["total_points"]) * int(pick["multiplier"]),
                "expected_points": forecast.get("expected_points"),
                "expected_minutes": forecast.get("expected_minutes"),
                "recommended_role": forecast.get("decision_role"),
            }
        )
    comparison = (score or {}).get("selected_comparison") or {}
    chip_score = (score or {}).get("chip_strategy_score") or {}
    chip = chip_score.get("frozen_recommendation") or "no_chip"
    recommendation_net = comparison.get("realized_manager_net_points")
    if chip != "no_chip":
        # Never label the separate ordinary winner as the executable chip route.
        decision = json.loads(Path(score["frozen_evidence"]["decision_path"]).read_text())
        chip_id = (decision.get("chip_strategy") or {}).get("recommended_action_id")
        candidate = next(
            (c for c in chip_score.get("candidates", []) if c["action_id"] == chip_id), None
        )
        recommendation_net = (
            candidate["realized_gross_points"] - candidate["total_points_cost"]
            if candidate and candidate.get("realized_gross_points") is not None
            else None
        )
    configuration = (score or {}).get("decision_attribution", {}).get("configuration", {})
    return {
        "event": event,
        "actual_points": gross,
        "hit_cost": hit,
        "net_points": gross - hit,
        "average_points": event_info["average_entry_score"],
        "average_comparison_basis": "FPL's reported event average; manager score shown after hits",
        "overall_rank": history["overall_rank"],
        "total_points": history["total_points"],
        "bench_points": history["points_on_bench"],
        "chip": picks.get("active_chip"),
        "recommendation_net_points": recommendation_net,
        "ordinary_projection": comparison.get("projected_event_gross_points"),
        "recommendation_chip": chip if score else None,
        "difference_to_recommendation": gross - hit - recommendation_net
        if recommendation_net is not None
        else None,
        "hindsight_configuration_gap": configuration.get("configuration_regret"),
        "hindsight_captain_gap": configuration.get("captaincy_regret_within_frozen_xi"),
        "review_status": "scored" if score else "missing_frozen_evidence",
        "review_error": score_error,
        "decision_created_at": (score or {}).get("frozen_evidence", {}).get("decision_created_at"),
        "decision_sha256": (score or {}).get("frozen_evidence", {}).get("decision_sha256"),
        "players": players,
    }


def read_gameweek_review(entry_id: int, *, root: Path = ROOT) -> dict:
    path = root / str(entry_id) / "current.json"
    if not path.is_file():
        return {"status": "not_collected", "entry_id": entry_id, "events": [], "observed_at": None}
    result = json.loads(path.read_text())
    if result.get("entry_id") != entry_id:
        raise ValueError("Saved review belongs to a different FPL entry")
    for evidence in result.get("evidence", []):
        if sha256_file(Path(evidence["path"])) != evidence["sha256"]:
            raise ValueError("Saved review evidence changed; refresh results")
    return result


def refresh_gameweek_review(
    entry_id: int, *, root: Path = ROOT, client: httpx.Client | None = None
) -> dict:
    if entry_id <= 0:
        raise ValueError("A positive FPL entry ID is required")
    if client is None:
        with httpx.Client(timeout=30, follow_redirects=False) as owned:
            return refresh_gameweek_review(entry_id, root=root, client=owned)

    def get(path: str) -> dict:
        response = client.get("https://fantasy.premierleague.com/api/" + path)
        response.raise_for_status()
        return response.json()

    observed = datetime.now(UTC).isoformat()
    bootstrap = get("bootstrap-static/")
    fixtures = get("fixtures/")
    # A results-only capture must carry complete feature lineage without advancing
    # the production official pointer or invalidating the active decision.
    official = archive_official_payloads(
        {"bootstrap-static.json": bootstrap, "fixtures.json": fixtures},
        observed_at=observed,
        snapshot_root=root / str(entry_id) / "official",
        pointer_path=root / str(entry_id) / "official-current.json",
    )
    bootstrap_path = (
        root / str(entry_id) / "official" / official["snapshot_id"] / "bootstrap-static.json"
    )
    history = get(f"entry/{entry_id}/history/")
    final_events = {
        e["id"] for e in bootstrap["events"] if e.get("finished") and e.get("data_checked")
    }
    rows, evidence, distribution_rows = [], [], []
    source = {"observed_at": observed, "bootstrap": bootstrap, "history": history, "picks": {}}
    for item in sorted(history["current"], key=lambda row: row["event"]):
        event = item["event"]
        if event not in final_events:
            continue
        live = get(f"event/{event}/live/")
        try:
            _, archived_manifest, archived_live = latest_event_outcome(event)
        except ValueError:
            archived_live = None
            archived_manifest = {}
        if archived_live != live or not archived_manifest.get("bootstrap_path"):
            archive_event_outcome(
                live,
                bootstrap,
                event=event,
                observed_at=observed,
                bootstrap_path=bootstrap_path,
                source_url=f"https://fantasy.premierleague.com/api/event/{event}/live/",
            )
        picks = get(f"entry/{entry_id}/event/{event}/picks/")
        source["picks"][str(event)] = picks
        score, error = None, None
        try:
            score = score_weekly_event(event)
            distribution_rows.extend(score.get("selected_squad_player_outcomes", []))
            evidence.append(
                {"path": score["receipt_path"], "sha256": sha256_file(Path(score["receipt_path"]))}
            )
            for kind in ("decision", "outcome"):
                frozen = score["frozen_evidence"]
                evidence.append(
                    {"path": frozen[f"{kind}_path"], "sha256": frozen[f"{kind}_sha256"]}
                )
        except (ProspectiveScoringError, ValueError, OSError, KeyError) as exc:
            error = str(exc)
        rows.append(
            reconcile_event(
                history=item,
                picks=picks,
                live=live,
                bootstrap=bootstrap,
                score=score,
                score_error=error,
            )
        )
    source_id = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    source_path = root / str(entry_id) / "sources" / f"{source_id}.json"
    _write(source_path, source, immutable=True)
    evidence.append({"path": str(source_path), "sha256": sha256_file(source_path)})
    from .distribution_calibration import score_distribution_rows

    calibration = score_distribution_rows(distribution_rows)
    benchmark = None
    sample = load_elite_sample(rows[-1]["event"]) if rows else None
    if sample:
        latest = source["picks"][str(rows[-1]["event"])]["picks"]
        benchmark = scoreboard(
            rows, sample,
            squad=[int(p["element"]) for p in latest],
            names={int(e["id"]): e["web_name"] for e in bootstrap["elements"]},
        )
    result = {
        "version": "gameweek_review_v1",
        "status": "ready" if rows else "awaiting_final_event",
        "entry_id": entry_id,
        "observed_at": observed,
        "events": rows,
        "evidence": evidence,
        "forecast_health": {
            "scope": "frozen recommended squads; repeated players and shared matches are correlated",
            "player_outcomes": calibration["overall"].get("rows", 0),
            "interval_80_coverage": calibration["overall"].get("interval_80_coverage"),
            "captain_outcomes": calibration["by_decision_role"]["captain"].get("rows", 0),
            "captain_interval_80_coverage": calibration["by_decision_role"]["captain"].get(
                "interval_80_coverage"
            ),
            "decision_authority": False,
        },
        "benchmark": benchmark,
        "total_points": rows[-1]["total_points"] if rows else 0,
        "overall_rank": rows[-1]["overall_rank"] if rows else None,
        "total_net_points_minus_event_averages": sum(
            r["net_points"] - r["average_points"] for r in rows
        ),
        "limitations": [
            "The official team is not assumed to match the app recommendation.",
            "Hindsight captain and lineup gaps overlap; do not add them or treat them as recoverable points.",
            "Forecasts are frozen before kickoff. One gameweek cannot establish model quality.",
            "Ordinary projections are risk-adjusted scores, not calibrated predictive intervals.",
        ],
    }
    _write(root / str(entry_id) / "current.json", result)
    return result
