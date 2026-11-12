"""Bounded, private Scout benchmark. No forecast training or decision authority.

Uses the member page the account holder can normally view. No login bypass,
bulk history scraping, JavaScript evaluation, or proprietary model replication.
Only selected comparison rows are retained; cookies/HTML are never persisted.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import UTC, datetime

import httpx
import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .current_squad_audit import enumerate_legal_xis
from .paths import ROOT
from .rules import validate_lineup, validate_squad

URL = "https://www.fantasyfootballscout.co.uk/fpl/projected-points"
COOKIE = ROOT / ".local/ffscout-cookie.txt"
PRIVATE_ROOT = ROOT / ".local/scout-benchmarks"
MAX_PLAYERS = 40
MAX_HOURS = 6


def aware(value):
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("A benchmark timestamp must include its timezone")
    return parsed.astimezone(UTC)


def _island(body, name):
    match = re.search(r"window\." + re.escape(name) + r"\s*=\s*", body)
    if not match:
        raise ValueError("Scout projection schema unavailable")
    try:
        value, _ = json.JSONDecoder().raw_decode(body[match.end():])
    except json.JSONDecodeError:
        raise ValueError("Scout projection JSON is invalid") from None
    if not isinstance(value, dict):
        raise TypeError("Scout projection JSON has an unexpected type")
    return value


def parse_page(body):
    meta, payload = (_island(body, name) for name in ("FPL_PROJ_META", "FPL_PROJ_PLAYERS"))
    if (meta.get("isMember") is not True or meta.get("isLoggedIn") is not True
            or payload.get("isMember") is not True or payload.get("hasProjections") is not True):
        raise ValueError("Scout member projections require an active authorized session")
    players = payload.get("players")
    if not isinstance(players, list) or not players:
        raise ValueError("Scout returned no player projections")
    ids, codes = set(), set()
    for row in players:
        identity, code = int(row["e"]), int(row["c"])
        if identity <= 0 or code <= 0 or identity in ids or code in codes:
            raise ValueError("Scout player identity is invalid or ambiguous")
        ids.add(identity)
        codes.add(code)
    return meta, players


def fetch_page(cookie_path=COOKIE):
    # Never include credentials, response text, redirect targets or request
    # objects in exceptions. Do not forward the Cookie header to another host.
    mode = stat.S_IMODE(cookie_path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Scout cookie file must be owner-only (chmod 600)")
    cookie = cookie_path.read_text().strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    if not cookie or "\n" in cookie or "\r" in cookie:
        raise ValueError("Scout cookie file must contain one nonempty header value")
    try:
        response = httpx.get(URL, headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
                             timeout=20, follow_redirects=False)
    except httpx.HTTPError:
        raise ValueError("Scout request unavailable; credentials were not logged") from None
    if response.status_code != 200:
        raise ValueError(f"Scout returned HTTP {response.status_code}; no bypass attempted")
    return response.text


def number(value):
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite Scout projection")
    return result


def _simple_lineup(rows, field, rules):
    """Transparent scalar-mean control, NOT Scout's proprietary RMT optimizer.

    Both sources use precisely the same constraints and objective. We deliberately
    do not invent per-GW Scout availability from its aggregate minutes column.
    """
    validate_squad(rows, rules, enforce_budget=False)
    meta = {r["element"]: r for r in rows}
    if any(r[field] is None for r in rows):
        return None
    candidates = enumerate_legal_xis(sorted(meta), meta, rules)
    if not candidates:
        raise ValueError("No legal XI in matched squad")
    def score(xi):
        return sum(meta[p][field] for p in xi) + max(meta[p][field] for p in xi)
    xi = min(candidates, key=lambda x: (-score(x), x))
    captain, vice = sorted(xi, key=lambda p: (-meta[p][field], p))[:2]
    bench = sorted(set(meta) - set(xi),
                   key=lambda p: (meta[p]["position"] == "GK", -meta[p][field], p))
    validate_lineup(rows, xi, bench, captain, vice, rules)
    return {"starters": list(xi), "bench_order": bench, "captain": captain,
            "vice_captain": vice, "scalar_xp_including_captain": score(xi)}


def build_comparison(meta, players, rows, *, held_ids, events, observed_at, deadline, rules):
    observed, cutoff = aware(observed_at), aware(deadline)
    if not events or len(events) > 5 or tuple(events) != tuple(range(events[0], events[0] + len(events))):
        raise ValueError("Scout benchmark needs a contiguous horizon of one to five events")
    if len(set(held_ids)) != 15:
        raise ValueError("Scout benchmark requires exactly 15 distinct held players")
    if int(meta["currentGw"]) != events[0] or int(meta["projGw"]) != events[0]:
        raise ValueError("Scout and local actionable events differ")
    local = [r for r in rows if int(r["event_number"]) in events]
    if not local or {r["season"] for r in local} != {meta["season"]}:
        raise ValueError("Scout and local forecast seasons differ")
    grid = {(int(r["element"]), int(r["event_number"])): r for r in local}
    if len(grid) != len(local):
        raise ValueError("Duplicate local player-event forecasts")
    external = {int(r["e"]): r for r in players}
    current = {p: r for (p, e), r in grid.items() if e == events[0]}
    if not set(held_ids) <= set(current) & set(external):
        raise ValueError("Held player missing from one forecast source")
    # Fixed, declared cohort rule; do not cherry-pick post-result disagreements.
    selected = set(held_ids)
    for position in ("GK", "DEF", "MID", "FWD"):
        pool = [p for p, r in current.items() if r["position"] == position and p in external]
        for source in ("own", "scout"):
            def horizon(p, source=source):
                values = ([grid.get((p, e), {}).get("expected_points") for e in events]
                          if source == "own" else [external[p]["xp"][e - 1] for e in events])
                return sum(float(v) for v in values) if all(v is not None for v in values) else -math.inf
            selected.update(sorted(pool, key=lambda p: (-horizon(p), p))[:2])
    if len(selected) > MAX_PLAYERS:
        raise ValueError("Scout private comparison cohort exceeds its limit")
    result_rows, issues = [], []
    source_times, created_times = set(), set()
    for player in sorted(selected):
        source, own = external[player], current[player]
        position = "GK" if source["p"] in {"GK", "GKP"} else source["p"]
        if (int(source["c"]) != int(own["player_code"]) or position != own["position"]
                or int(source["tb"]) != int(own["team_code"])):
            raise ValueError(f"Scout identity/club/position mismatch for element {player}")
        xp = source.get("xp")
        if not isinstance(xp, list) or len(xp) < events[-1]:
            raise ValueError("Scout gameweek projection array is incomplete")
        for event in events:
            own = grid.get((player, event))
            if own is None:
                issues.append(f"local_missing:{player}:{event}")
                continue
            source_times.add(aware(own["snapshot_at"]))
            created_times.add(aware(own["forecast_created_at"]))
            price = number(source.get("pr"))
            if price is None or round(price * 10) != round(float(own["market_price"])):
                issues.append(f"price_mismatch:{player}:{event}")
            scout_xp = number(xp[event - 1])
            if scout_xp is None:
                issues.append(f"scout_missing:{player}:{event}")
            result_rows.append({"element": player, "player_code": int(source["c"]),
                                "name": own["player_name"], "position": position,
                                "team_id": own["team_id"], "team_code": own["team_code"],
                                "event": event, "market_price": own["market_price"],
                                "scout_price": price, "held": player in held_ids,
                                "own_xp": number(own["expected_points"]), "scout_xp": scout_xp,
                                "own_p_play": number(own["p_play"]),
                                "delta_scout_minus_own": None if scout_xp is None else scout_xp - float(own["expected_points"]),
                                # Source explicitly exposes aggregates, not per-GW minutes.
                                "scout_aggregate_minutes_unverified_window": number(source.get("mn")),
                                "scout_set_pieces": str(source.get("sp") or "")})
    for time in source_times | created_times:
        if time > observed or (observed - time).total_seconds() > MAX_HOURS * 3600:
            issues.append("local_forecast_not_contemporaneous")
    if len(source_times) != 1 or len(created_times) != 1:
        issues.append("mixed_local_forecast_generation")
    if observed >= cutoff:
        issues.append("capture_not_before_deadline")
    current_squad = [r for r in result_rows if r["held"] and r["event"] == events[0]]
    # Never label an unmatched cross-date comparison as a recommendation contest.
    lineups = None if issues else {
        source: _simple_lineup(current_squad, f"{source}_xp", rules) for source in ("own", "scout")}
    return {"version": "scout_private_benchmark_v1", "decision_authority": False,
            "source": URL, "season": meta["season"], "event": events[0], "events": list(events),
            "observed_at": observed.isoformat(), "deadline": cutoff.isoformat(),
            "source_published_at": None, "source_published_at_known": False,
            "local_snapshot_at": [t.isoformat() for t in sorted(source_times)],
            "local_forecast_created_at": [t.isoformat() for t in sorted(created_times)],
            "status": "unmatched" if issues else "contemporaneous_capture",
            "issues": sorted(set(issues)), "cohort_rule": "Held 15 plus top two per position/source by unweighted horizon xP; no outcome-based selection.",
            "rows": result_rows, "held_ids": sorted(held_ids), "lineup_controls": lineups,
            "limitations": ["Capture time is not the unknown Scout model build/publication time.",
                            "Legal scalar-XI controls isolate xP differences, not Scout's actual advice or full optimizer; no autosub expectation, transfers, chips or risk objective.",
                            "No historical or prospective superiority established by a disagreement.",
                            "Paid rows are private evaluation data, not a training set or redistributable feed."]}


def save_private(payload, root=PRIVATE_ROOT):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    path = root / f"gw{payload['event']:02d}-{digest[:20]}.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("Scout capture identity collision") from None
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    return path


def capture(*, forecast_path, held_ids, events, deadline, rules, cookie_path=COOKIE,
            root=PRIVATE_ROOT, fetcher=fetch_page, now=None, manager_contract_path=None):
    # Hash and read before network; refuse to join two changing generations.
    before = sha256_file(forecast_path)
    rows = pq.read_table(forecast_path).to_pylist()
    context = None
    if manager_contract_path is not None:
        contract_hash = sha256_file(manager_contract_path)
        contract = json.loads(manager_contract_path.read_text())
        if set(held_ids) != {int(p["player_id"]) for p in contract["manager_state"]["squad"]}:
            raise ValueError("Comparison cohort differs from the supplied manager contract")
        context = {"contract_sha256": contract_hash,
                   "contract_event": contract["manager_state"]["event"],
                   "manager_observed_at": contract.get("source_artifacts", {}).get("manager_snapshot_observed_at"),
                   "interpretation": "Fixed supplied roster; not a claim that this older contract is the current FPL account state."}
    body = fetcher(cookie_path)
    observed = now or datetime.now(UTC)
    meta, players = parse_page(body)
    result = build_comparison(meta, players, rows, held_ids=held_ids, events=events,
                              observed_at=observed.isoformat(), deadline=deadline, rules=rules)
    if sha256_file(forecast_path) != before:
        raise ValueError("Local forecast changed during Scout capture")
    if context is not None and sha256_file(manager_contract_path) != context["contract_sha256"]:
        raise ValueError("Manager contract changed during Scout capture")
    result["manager_context"] = context
    result["local_forecast_sha256"] = before
    path = save_private(result, root)
    return {"status": result["status"], "decision_authority": False, "path": str(path),
            "sha256": sha256_file(path), "event": events[0],
            "players": len({r["element"] for r in result["rows"]}), "issues": result["issues"]}


def optional_capture(*, forecast_path, contract_path, events, rules):
    """One optional read on each new weekly run. Failure cannot alter/pause advice."""
    try:
        previous_scores = score_available()
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        previous_scores = {"status": "unavailable", "error_type": type(exc).__name__}
    if not COOKIE.is_file():
        return {"status": "not_configured", "decision_authority": False,
                "previous_captures_scored": previous_scores}
    try:
        from fplagent_data.live_snapshots import latest_official_snapshot

        official_dir, _ = latest_official_snapshot()
        bootstrap = json.loads((official_dir / "bootstrap-static.json").read_text())
        deadline = next(e["deadline_time"] for e in bootstrap["events"] if int(e["id"]) == events[0])
        contract = json.loads(contract_path.read_text())
        held = [int(p["player_id"]) for p in contract["manager_state"]["squad"]]
        result = capture(forecast_path=forecast_path, held_ids=held, events=events[:5],
                         deadline=deadline, rules=rules, manager_contract_path=contract_path)
        result["previous_captures_scored"] = previous_scores
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration, ImportError) as exc:
        # Do not stringify a request exception or a malformed secret-containing file.
        return {"status": "unavailable", "decision_authority": False, "error_type": type(exc).__name__,
                "previous_captures_scored": previous_scores,
                "message": "Optional private Scout comparison unavailable; live policy unaffected."}


def score_comparison(payload, history, *, final_events):
    """Score frozen pre-deadline means and controls, only on finalized outcomes."""
    if payload["status"] != "contemporaneous_capture":
        return {"status": "ineligible_unmatched", "decision_authority": False}
    if aware(payload["observed_at"]) >= aware(payload["deadline"]):
        raise ValueError("Cannot score a post-deadline forecast as prospective")
    event = int(payload["event"])
    if event not in final_events:
        return {"status": "awaiting_final_outcomes", "decision_authority": False}
    actual = {int(r["element"]): r for r in history
              if r["season"] == payload["season"] and int(r["event"]) == event}
    rows = [r for r in payload["rows"] if int(r["event"]) == event]
    if any(r["element"] not in actual for r in rows):
        return {"status": "incomplete_outcomes", "decision_authority": False}
    if any(int(actual[r["element"]]["player_code"]) != r["player_code"] for r in rows):
        raise ValueError("Scout prospective outcome identity mismatch")
    from .tournament import _score_candidates_cpu

    ids = payload["held_ids"]
    meta = {r["element"]: r for r in rows}
    points = np.asarray([[[actual[p]["points"] for p in ids]]], dtype=np.float64)
    played = np.asarray([[[actual[p]["minutes"] > 0 for p in ids]]], dtype=bool)
    scores = {}
    for source in ("own", "scout"):
        errors = np.asarray([r[f"{source}_xp"] - actual[r["element"]]["points"] for r in rows])
        lineup = payload["lineup_controls"][source]
        candidate = {"candidate_id": source, "selected": ids, "lineups": {str(event): lineup}}
        scored = _score_candidates_cpu([candidate], ids, (event,), points, played, meta)
        scores[source] = {"mae": float(np.abs(errors).mean()), "bias": float(errors.mean()),
                          "rmse": float(np.sqrt((errors ** 2).mean())),
                          "legal_lineup_points_including_autosubs_captain_fallback": float(scored[0, 0, 0])}
    return {"status": "scored", "event": event, "decision_authority": False,
            "player_events": len(rows), "scores": scores,
            "interpretation": "Frozen same-squad scalar controls, NOT actual Scout advice or whole-season policy lift. Selected cohort, not an unbiased full-universe sample."}


def score_available(root=PRIVATE_ROOT):
    """Use the existing validated final-outcome archive; no new external requests."""
    from fplagent_data.event_outcomes import CURRENT_PLAYER_HISTORY, CURRENT_PLAYER_HISTORY_RECEIPT

    if not CURRENT_PLAYER_HISTORY_RECEIPT.is_file() or not CURRENT_PLAYER_HISTORY.is_file():
        return {"status": "no_final_archive"}
    receipt = json.loads(CURRENT_PLAYER_HISTORY_RECEIPT.read_text())
    if receipt.get("status") != "ready" or sha256_file(CURRENT_PLAYER_HISTORY) != receipt.get("output_sha256"):
        return {"status": "outcome_archive_unvalidated"}
    history = pq.read_table(CURRENT_PLAYER_HISTORY).to_pylist()
    statuses = {}
    for path in sorted(root.glob("gw*.json")):
        if not path.stem.endswith(sha256_file(path)[:20]):
            raise ValueError("Private Scout capture content changed after freezing")
        payload = json.loads(path.read_text())
        score = score_comparison(payload, history, final_events=set(receipt["events"]))
        statuses[score["status"]] = statuses.get(score["status"], 0) + 1
        if score["status"] == "scored":
            save_private({**score, "capture_sha256": sha256_file(path),
                          "outcomes_sha256": receipt["output_sha256"]}, root / "scores")
    return statuses
