"""Independent player-comparison evidence from official, attributable FPL inputs.

No Scout projections, official ep_next, inferred transfer recommendation or account
write. Historical facts and existing model forecasts have separate freshness labels.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pyarrow.parquet as pq

from fplagent_data.event_outcomes import latest_event_outcome
from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import SNAPSHOT_ROOT

from .distribution_calibration import pmf_quantile
from .models import CURRENT_FORECAST
from .paths import MODEL_DATA
from .score_shape import ARTIFACT as SCORE_SHAPE_ARTIFACT
from .score_shape import frozen_score_distribution

ROOT = MODEL_DATA / "scouting_v1"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _number(value):
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def summarize_matches(rows: list[dict]) -> dict:
    """Missing values stay missing; denominators follow the metric's coverage."""
    minutes = sum(r["minutes"] for r in rows)
    complete_xg = [r for r in rows if r["xg"] is not None and r["xa"] is not None]
    xgi_minutes = sum(r["minutes"] for r in complete_xg)
    xg = sum(r["xg"] for r in complete_xg)
    xa = sum(r["xa"] for r in complete_xg)
    defcon = [r for r in rows if r["defcon_hits"] is not None]
    played_fixtures = sum(r["played_fixtures"] for r in defcon)
    starts_known = all(r["starts"] is not None for r in rows)
    eligible = sum(r["fixtures"] for r in rows)
    return {
        "events": len(rows),
        "fixtures": eligible,
        "minutes": minutes,
        "minutes_per_fixture": minutes / eligible if eligible else None,
        "starts": sum(r["starts"] for r in rows) if starts_known else None,
        "start_rate": sum(r["starts"] for r in rows) / eligible
        if eligible and starts_known
        else None,
        "points": sum(r["points"] for r in rows),
        "goals": sum(r["goals"] for r in rows),
        "assists": sum(r["assists"] for r in rows),
        "xg": xg if complete_xg else None,
        "xa": xa if complete_xg else None,
        "xgi_per90": 90 * (xg + xa) / xgi_minutes if xgi_minutes > 0 else None,
        "xgi_minutes": xgi_minutes,
        "xgi_events": len(complete_xg),
        "goals_minus_xg": sum(r["goals"] for r in complete_xg) - xg if complete_xg else None,
        "defcon_hits": sum(r["defcon_hits"] for r in defcon) if defcon else None,
        "defcon_played_fixtures": played_fixtures,
        "defcon_hit_rate": sum(r["defcon_hits"] for r in defcon) / played_fixtures
        if played_fixtures
        else None,
        "defcon_points": sum(r["defcon_points"] for r in defcon) if defcon else None,
    }


def event_record(event: int, player: dict, fixture_count: int) -> dict:
    stats = player["stats"]
    explained = player.get("explain")
    dc_hits, dc_points, played = 0, 0, 0
    valid = isinstance(explained, list) and len({r["fixture"] for r in explained}) == fixture_count
    if valid:
        for fixture in explained:
            identifiers = {s["identifier"]: s for s in fixture["stats"]}
            appearance = identifiers.get("minutes")
            if appearance is None:
                valid = False
                break
            if appearance["value"] > 0:
                played += 1
            awarded = identifiers.get("defensive_contribution", {}).get("points", 0)
            dc_hits += int(awarded > 0)
            dc_points += awarded
    return {
        "event": event,
        "fixtures": fixture_count,
        "minutes": int(stats["minutes"]),
        "points": int(stats["total_points"]),
        "starts": _number(stats.get("starts")),
        "goals": int(stats["goals_scored"]),
        "assists": int(stats["assists"]),
        "xg": _number(stats.get("expected_goals")),
        "xa": _number(stats.get("expected_assists")),
        "played_fixtures": played if valid else 0,
        "defcon_hits": dc_hits if valid else None,
        "defcon_points": dc_points if valid else None,
    }


def build_board(
    bootstrap: dict,
    fixtures: list[dict],
    history: dict[int, list[dict]],
    forecasts: list[dict],
    *,
    observed_at: str,
    now: datetime,
) -> dict:
    future = [e for e in bootstrap["events"] if datetime.fromisoformat(e["deadline_time"]) > now]
    event = min((e["id"] for e in future), default=None)
    if event is None:
        raise ValueError("No future deadline in this season")
    teams = {r["id"]: r["short_name"] for r in bootstrap["teams"]}
    index = {(int(r["element"]), int(r["event_number"])): r for r in forecasts}
    completed = sorted(
        e["id"] for e in bootstrap["events"] if e.get("finished") and e.get("data_checked")
    )
    recent_events = set(completed[-3:])
    players = []
    for p in bootstrap["elements"]:
        rows = sorted(history.get(p["id"], []), key=lambda r: r["event"])
        recent = summarize_matches([r for r in rows if r["event"] in recent_events])
        earlier = summarize_matches([r for r in rows if r["event"] not in recent_events])
        total = summarize_matches(rows)
        horizon = []
        for gw in range(event, min(event + 6, 39)):
            forecast = index.get((p["id"], gw), {})
            matches = [
                f
                for f in fixtures
                if f.get("event") == gw and p["team"] in (f["team_h"], f["team_a"])
            ]
            horizon.append(
                {
                    "event": gw,
                    "fixtures": [
                        {
                            "opponent": teams.get(
                                f["team_a"] if f["team_h"] == p["team"] else f["team_h"], "?"
                            ),
                            "venue": "H" if f["team_h"] == p["team"] else "A",
                            "kickoff": f.get("kickoff_time"),
                        }
                        for f in matches
                    ],
                    "xp": _number(forecast.get("expected_points")),
                    "p_play": _number(forecast.get("p_play")),
                    "p_short": _number(forecast.get("p_1_59")),
                    "p60": (float(forecast["p_60_89"]) + float(forecast["p_90_or_more"]))
                    if all(forecast.get(k) is not None for k in ("p_60_89", "p_90_or_more"))
                    else None,
                    "forecast_at": forecast.get("forecast_created_at"),
                    "team_goals": _number(forecast.get("team_expected_goals")),
                    "clean_sheet_probability": _number(
                        forecast.get("team_clean_sheet_probability")
                    ),
                }
            )
        warnings = []
        if p.get("status") != "a":
            warnings.append("Official availability needs checking.")
        if total["minutes"] < 300:
            warnings.append("Small minutes sample: per-90 figures are unstable.")
        if total["events"] < len(completed):
            warnings.append("Some completed events have no player record; not treated as zero.")
        first = horizon[0]
        score_risk = None
        first_row = index.get((p["id"], event))
        if first_row and first_row.get("fixture_count") == 1:
            distribution = frozen_score_distribution(first_row)
            if distribution.get("distribution_version") == "mean_preserving_score_atoms_v1":
                pmf = distribution["points_pmf"]
                score_risk = {
                    "blank_probability": sum(v for s, v in pmf.items() if int(s) <= 2),
                    "haul_probability": sum(v for s, v in pmf.items() if int(s) >= 10),
                    "p10": pmf_quantile(pmf, 0.1),
                    "p90": pmf_quantile(pmf, 0.9),
                    "source": distribution["distribution_source"],
                    "calibration_sha256": distribution["distribution_calibration_sha256"],
                }
        if (
            first["forecast_at"] is None
            or (now - datetime.fromisoformat(first["forecast_at"])).total_seconds() > 21600
        ):
            warnings.append(
                "Forecast is missing or older than six hours: refresh decisions before acting."
            )
        if (
            recent["start_rate"] is not None
            and first["p60"] is not None
            and first["p60"] - recent["start_rate"] >= 0.25
        ):
            warnings.append(
                "Model 60+ probability exceeds recent start rate by 25+ percentage points; inspect role evidence."
            )
        players.append(
            {
                "id": p["id"],
                "name": p["web_name"],
                "position": POSITIONS[p["element_type"]],
                "team": teams[p["team"]],
                "price": p["now_cost"] / 10,
                "status": p.get("status"),
                "news": p.get("news", ""),
                "news_at": p.get("news_added"),
                "penalty_order": p.get("penalties_order"),
                "corner_order": p.get("corners_and_indirect_freekicks_order"),
                "season": total,
                "recent": recent,
                "earlier": earlier,
                "history": rows,
                "horizon": horizon,
                "score_risk": score_risk,
                "warnings": warnings,
            }
        )
    return {
        "version": "scouting_v1",
        "status": "ready",
        "observed_at": observed_at,
        "decision_event": event,
        "completed_events": completed,
        "players": players,
        "decision_authority": False,
        "notes": [
            "Official FPL xG/xA include penalties; not labelled non-penalty or Understat.",
            "Last three finalized events are compared with the earlier non-overlapping season.",
            "DEFCON counts actual per-fixture awards, including doubles, not a threshold on summed GW actions.",
            "Per-90 and price comparisons are scouting evidence, not legal transfer recommendations.",
            "Upcoming fixtures are observed schedule, not a promise against postponement. Forecasts are separately dated.",
        ],
    }


def refresh_scouting(
    *, root: Path = ROOT, forecast_path: Path = CURRENT_FORECAST, client: httpx.Client | None = None
) -> dict:
    if client is None:
        with httpx.Client(timeout=30, follow_redirects=False) as owned:
            return refresh_scouting(root=root, forecast_path=forecast_path, client=owned)
    now = datetime.now(UTC)
    responses = []
    for route in ("bootstrap-static/", "fixtures/"):
        response = client.get("https://fantasy.premierleague.com/api/" + route)
        response.raise_for_status()
        responses.append(response.json())
    bootstrap, fixtures = responses
    return _save_scouting(
        bootstrap,
        fixtures,
        root=root,
        forecast_path=forecast_path,
        observed_at=now.isoformat(),
        now=now,
    )


def refresh_scouting_from_generation(
    official: dict,
    *,
    root: Path = ROOT,
    forecast_path: Path = CURRENT_FORECAST,
    snapshot_root: Path = SNAPSHOT_ROOT,
    now: datetime | None = None,
) -> dict:
    """Build explanations from the exact decision generation, without network I/O.

    Called by the normal weekly refresh, not dependent on anyone opening the
    comparison screen. The caller decides how an optional diagnostic failure is
    recorded; this function never changes forecasts or publishes a decision.
    """
    if not official.get("publishable"):
        raise ValueError("Scouting requires a validated official generation")
    directory = snapshot_root / official["snapshot_id"]
    payloads, evidence = [], []
    for filename in ("bootstrap-static.json", "fixtures.json"):
        path = directory / filename
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        if checksum != official["files"][filename]["sha256"]:
            raise ValueError("Scouting inputs differ from the decision generation")
        payloads.append(json.loads(raw))
        evidence.append({"path": str(path), "sha256": checksum})
    return _save_scouting(
        *payloads,
        root=root,
        forecast_path=forecast_path,
        observed_at=official["observed_at"],
        now=now or datetime.now(UTC),
        generation_evidence=evidence,
        generation_id=official["snapshot_id"],
    )


def _save_scouting(
    bootstrap: dict,
    fixtures: list[dict],
    *,
    root: Path,
    forecast_path: Path,
    observed_at: str,
    now: datetime,
    generation_evidence: list[dict] | None = None,
    generation_id: str | None = None,
) -> dict:
    history = defaultdict(list)
    evidence = list(generation_evidence or [])
    for e in bootstrap["events"]:
        if not (e.get("finished") and e.get("data_checked")):
            continue
        directory, manifest, live = latest_event_outcome(e["id"])
        # Historical team membership comes from that event's archived catalogue.
        source = Path(manifest["bootstrap_path"])
        if sha256_file(source) != manifest["bootstrap_sha256"]:
            raise ValueError("Historical player catalogue checksum differs")
        catalog = {p["id"]: p for p in json.loads(source.read_text())["elements"]}
        fixture_path = source.with_name("fixtures.json")
        source_manifest = json.loads(source.with_name("manifest.json").read_text())
        if sha256_file(fixture_path) != source_manifest["files"]["fixtures.json"]["sha256"]:
            raise ValueError("Historical fixture catalogue checksum differs")
        historical_fixtures = json.loads(fixture_path.read_text())
        fixture_counts = defaultdict(int)
        for f in historical_fixtures:
            if f.get("event") == e["id"]:
                fixture_counts[f["team_h"]] += 1
                fixture_counts[f["team_a"]] += 1
        for p in live["elements"]:
            if p["id"] in catalog:
                history[p["id"]].append(
                    event_record(e["id"], p, fixture_counts[catalog[p["id"]]["team"]])
                )
        for path in (directory / "event-live.json", source, source.with_name("fixtures.json")):
            evidence.append({"path": str(path), "sha256": sha256_file(path)})
    forecast_hash = sha256_file(forecast_path) if forecast_path.is_file() else None
    rows = pq.read_table(forecast_path).to_pylist() if forecast_hash else []
    board = build_board(bootstrap, fixtures, history, rows, observed_at=observed_at, now=now)
    board["built_at"] = now.isoformat()
    board["official_snapshot_id"] = generation_id
    board["refresh_mode"] = "weekly_pipeline" if generation_id else "standalone"
    capture = {"observed_at": observed_at, "bootstrap": bootstrap, "fixtures": fixtures}
    raw = json.dumps(capture, sort_keys=True).encode()
    source_path = root / "sources" / (hashlib.sha256(raw).hexdigest() + ".json")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    if not source_path.exists():
        source_path.write_bytes(raw)
    evidence.append({"path": str(source_path), "sha256": sha256_file(source_path)})
    if rows:
        # Freeze the forecast bytes so a normal refresh does not invalidate this saved board.
        forecast_bytes = forecast_path.read_bytes()
        checksum = hashlib.sha256(forecast_bytes).hexdigest()
        if checksum != forecast_hash:
            raise ValueError("Forecast changed while building scouting evidence")
        frozen = root / "sources" / (checksum + ".parquet")
        if not frozen.exists():
            frozen.write_bytes(forecast_bytes)
        evidence.append({"path": str(frozen), "sha256": checksum})
    if SCORE_SHAPE_ARTIFACT.is_file():
        checksum = sha256_file(SCORE_SHAPE_ARTIFACT)
        frozen = root / "sources" / (checksum + ".json")
        if not frozen.exists():
            frozen.write_bytes(SCORE_SHAPE_ARTIFACT.read_bytes())
        evidence.append({"path": str(frozen), "sha256": checksum})
    board["evidence"] = evidence
    path = root / "current.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(board, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)
    return board


def read_scouting(*, root: Path = ROOT) -> dict:
    path = root / "current.json"
    if not path.exists():
        return {"status": "not_collected", "players": [], "observed_at": None}
    board = json.loads(path.read_text())
    for evidence in board["evidence"]:
        if sha256_file(Path(evidence["path"])) != evidence["sha256"]:
            raise ValueError("Scouting evidence changed; refresh it")
    return board
