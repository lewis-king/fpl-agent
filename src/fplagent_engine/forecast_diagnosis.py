"""Outcome-led forecast diagnosis, separate from model/policy promotion."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from fplagent_data.http import sha256_file

from .paths import MODEL_DATA


def error_summary(rows: list[dict]) -> dict:
    """Exact appearance/performance identity, not a causal or recoverable-points claim.

    y - x = (x/p)*(I_play-p) + (y - (x/p)*I_play).
    Missing minutes remain missing. The linear minutes bridge is a diagnostic only:
    FPL appearance, clean-sheet and defensive-contribution points are not linear in minutes.
    """
    if not rows:
        return {"rows": 0}
    actual = np.array([float(r["actual_points"]) for r in rows])
    expected = np.array([float(r["expected_points"]) for r in rows])
    probability = np.array([float(r["p_play"]) for r in rows])
    played = np.array([float(r["actual_minutes"] > 0) for r in rows])
    if not np.isfinite(np.r_[actual, expected, probability]).all() or np.any(
        (probability < 0) | (probability > 1)
    ):
        raise ValueError("Nonfinite outcome/projection or invalid play probability")
    conditional = np.divide(
        expected, probability, out=np.zeros_like(expected), where=probability > 0
    )
    if np.any((probability == 0) & (np.abs(expected) > 1e-9)):
        raise ValueError("Nonzero expected points at zero play probability")
    appearance = conditional * (played - probability)
    performance = actual - conditional * played
    assert np.allclose(actual - expected, appearance + performance)
    minute_rows = [r for r in rows if r.get("expected_minutes") is not None]
    minutes = {
        "rows": len(minute_rows),
        "mae": float(
            np.mean([abs(r["actual_minutes"] - r["expected_minutes"]) for r in minute_rows])
        )
        if minute_rows
        else None,
        "bias_actual_minus_expected": float(
            np.mean([r["actual_minutes"] - r["expected_minutes"] for r in minute_rows])
        )
        if minute_rows
        else None,
    }
    return {
        "rows": len(rows),
        "expected_mean": float(expected.mean()),
        "actual_mean": float(actual.mean()),
        "mae": float(np.abs(actual - expected).mean()),
        "rmse": float(np.sqrt(np.square(actual - expected).mean())),
        "bias_actual_minus_expected": float((actual - expected).mean()),
        "appearance_error_sum": float(appearance.sum()),
        "conditional_performance_error_sum": float(performance.sum()),
        "appearance_brier": float(np.square(played - probability).mean()),
        "minutes": minutes,
    }


def frozen_season_diagnosis(root: Path | None = None) -> dict:
    from .prospective_scoring import RESULT_ROOT

    root = root or RESULT_ROOT
    by_event = {}
    for path in sorted(root.glob("event-*/*.json")):
        payload = json.loads(path.read_text())
        frozen = payload["frozen_evidence"]
        created = datetime.fromisoformat(frozen["decision_created_at"])
        deadline = datetime.fromisoformat(frozen["official_deadline_time"])
        if created > deadline:
            raise ValueError("Post-deadline forecast cannot enter diagnosis")
        for kind in ("decision", "outcome"):
            if sha256_file(Path(frozen[f"{kind}_path"])) != frozen[f"{kind}_sha256"]:
                raise ValueError("Frozen diagnosis evidence changed")
        event = int(payload["event"])
        identity = (created, datetime.fromisoformat(frozen['outcome_observed_at']))
        if event not in by_event or identity > by_event[event][0]:
            by_event[event] = (identity, path, payload)
    universe, selected, events, lineage = [], [], [], []
    by_player = defaultdict(list)
    for event, (_, path, payload) in sorted(by_event.items()):
        rows = payload.get("forecast_universe", {}).get("player_outcomes", [])
        squad = payload["selected_squad_player_outcomes"]
        for row in rows:
            universe.append({**row, "event": event})
            if row["expected_points"] >= 2:
                by_player[row["player_name"]].append(row)
        selected.extend({**r, "event": event} for r in squad)
        events.append(
            {"event": event, "universe": error_summary(rows), "squad": error_summary(squad)}
        )
        lineage.append({"path": str(path), "sha256": sha256_file(path)})
    players = [dict(name=name, **error_summary(rs)) for name, rs in by_player.items()]
    players.sort(key=lambda r: (r["actual_mean"] - r["expected_mean"]) * r["rows"])
    return {
        "version": "forecast_diagnosis_v1",
        "decision_authority": False,
        "events": events,
        "source_receipts": lineage,
        "all_frozen": error_summary(universe),
        "selected_squads": error_summary(selected),
        "by_position": {
            pos: error_summary([r for r in universe if r["position"] == pos])
            for pos in ("GK", "DEF", "MID", "FWD")
        },
        "by_position_xp_at_least_3": {
            pos: error_summary(
                [r for r in universe if r["position"] == pos and r["expected_points"] >= 3]
            )
            for pos in ("GK", "DEF", "MID", "FWD")
        },
        "captains": error_summary([r for r in selected if r.get("decision_role") == "captain"]),
        "largest_negative_player_errors": players[:10],
        "largest_positive_player_errors": players[-10:][::-1],
        "limitations": [
            "GW1–3 frozen universes are selected subsets; GW4 onward includes the full pool. Do not compare aggregate counts as stationary samples.",
            "Appearance versus conditional-return attribution is algebraic, not causal. Missing expected minutes are not zero.",
            "Historical per-component predictions were not frozen consistently: cannot assign point error precisely to attacking/clean-sheet/DC forecasts.",
            "Player rankings select observed errors after outcomes; diagnostic only, not a training target or a recoverable-points estimate.",
            "Repeated players, shared matches and only seven events limit inferential strength.",
        ],
    }


def save_diagnosis() -> dict:
    from .models import _atomic_json

    result = frozen_season_diagnosis()
    path = MODEL_DATA / "forecast_diagnosis_v1/current.json"
    _atomic_json(path, result)
    return {
        "status": "ready",
        "path": str(path),
        "sha256": sha256_file(path),
        "events": len(result["events"]),
        "decision_authority": False,
    }


def historical_next_chance(row: dict) -> float | None:
    """Strict dated-proxy screen; no current metadata may backfill an old decision."""
    observed, deadline = row.get("observed_at"), row.get("deadline_at")
    if not observed or not deadline:
        return None
    observed = datetime.fromisoformat(str(observed))
    deadline = datetime.fromisoformat(str(deadline))
    if observed.tzinfo is None or deadline.tzinfo is None or observed >= deadline:
        return None
    if (deadline - observed).total_seconds() > 7 * 86400:
        return None
    # Only explicit, round-specific observations are authoritative in this experiment.
    raw = row.get("chance_of_playing_next_round")
    if raw is None or str(raw).strip().lower() in {"", "none", "null"}:
        return None
    value = float(raw)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Invalid historical next-round availability")
    return value
