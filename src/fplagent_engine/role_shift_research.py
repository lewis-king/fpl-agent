"""Forward-tested change-of-role diagnostic; never changes production forecasts.

Two non-overlapping blocks of SINGLE-fixture opportunities distinguish a new
selection pattern from a long-run regular's isolated rest. These are derived
FPL signals, not an independent lineup source or tactical-position observation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from scipy.special import betaln, expit, logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from fplagent_data.event_outcomes import CURRENT_PLAYER_HISTORY
from fplagent_data.http import sha256_file

from .features import TRAINING_FEATURES
from .models import BACKTEST_FORECAST
from .paths import MODEL_DATA

ARTIFACT = MODEL_DATA / "role_shift_research_v1" / "calibration-v2.json"
FEATURE_NAMES = (
    "champion_logit",
    "recent_appearance",
    "older_appearance",
    "recent_full_minutes",
    "older_full_minutes",
    "appearance_change",
    "full_minutes_change",
    "log_bayes_factor",
    "recent_opportunities",
    "older_opportunities",
    "recent_dnp_streak",
    "loss_of_regular_role",
)


def lagged_role_signal(history: list[dict], *, season: str, event: int, element: int) -> dict:
    eligible = sorted(
        (
            r
            for r in history
            if str(r["season"]) == season
            and int(r.get("event", r.get("event_number"))) < event
            and int(r["element"]) == element
            and float(r.get("fixture_count") or 0) == 1
        ),
        key=lambda r: int(r.get("event", r.get("event_number"))),
    )[-10:]
    keys = [int(r.get("event", r.get("event_number"))) for r in eligible]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate historical opportunity")
    minutes = [float(r.get("minutes", r.get("target_minutes"))) for r in eligible]
    if any(not math.isfinite(m) or m < 0 for m in minutes):
        raise ValueError("Unknown minutes are not a missed appearance")
    recent, older = minutes[-2:], minutes[:-2]
    rate = lambda values, cutoff: sum(v >= cutoff for v in values) / len(values) if values else 0.0
    ra, oa = rate(recent, 1), rate(older, 1)
    rf, of = rate(recent, 60), rate(older, 60)
    # Uniform-prior evidence for two Bernoulli rates versus one common rate.
    # A feature only, not a calibrated posterior probability of tactical change.
    successes = [sum(m >= 60 for m in block) for block in (older, recent)]
    ns = [len(older), len(recent)]
    bf = (
        (
            sum(betaln(s + 1, n - s + 1) for s, n in zip(successes, ns, strict=True))
            - betaln(sum(successes) + 1, sum(ns) - sum(successes) + 1)
        )
        if older and recent
        else 0.0
    )
    streak = 0
    for m in reversed(minutes):
        if m > 0:
            break
        streak += 1
    lost = len(older) >= 3 and len(recent) == 2 and of >= 0.6 and rf <= 0.5
    return {
        "recent_appearance": ra,
        "older_appearance": oa,
        "recent_full_minutes": rf,
        "older_full_minutes": of,
        "appearance_change": ra - oa if older else 0.0,
        "full_minutes_change": rf - of if older else 0.0,
        "log_bayes_factor": float(bf),
        "recent_opportunities": len(recent),
        "older_opportunities": len(older),
        "recent_dnp_streak": streak,
        "loss_of_regular_role": int(lost),
        "observed_events": keys,
        "status": "role_loss_watch"
        if lost
        else "insufficient_prior"
        if len(older) < 3
        else "monitored",
    }


def design(p_play: float, signal: dict) -> list[float]:
    return [
        float(logit(np.clip(p_play, 1e-5, 1 - 1e-5))),
        *(float(signal[name]) for name in FEATURE_NAMES[1:]),
    ]


def _model():
    return make_pipeline(
        StandardScaler(), LogisticRegression(C=0.1, max_iter=1000, random_state=49)
    )


def _metrics(y, probability):
    if not len(y):
        return {"rows": 0, "brier": None, "log_loss": None}
    return {
        "rows": len(y),
        "brier": float(brier_score_loss(y, probability)),
        "log_loss": float(log_loss(y, probability, labels=[0, 1])),
    }


def calibrate_role_shift(output: Path = ARTIFACT) -> dict:
    if output.exists():
        raise FileExistsError("Use a new artifact path; do not overwrite role experiments")
    columns = ["season", "event_number", "element", "fixture_count", "target_minutes"]
    history = pq.read_table(TRAINING_FEATURES, columns=columns).to_pylist()
    grouped = defaultdict(list)
    targets = {}
    for r in history:
        if str(r["season"]) not in ("2023-24", "2024-25", "2025-26"):
            continue
        grouped[(str(r["season"]), int(r["element"]))].append(r)
        targets[(str(r["season"]), int(r["event_number"]), int(r["element"]))] = r
    rows, x = [], []
    for r in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season, event, element = str(r["season"]), int(r["event_number"]), int(r["element"])
        target = targets.get((season, event, element))
        # A blank is not selection loss; aggregate double minutes do not reveal
        # which fixture a player started. Restrict the test and expose coverage.
        if target is None or float(target.get("fixture_count") or 0) != 1:
            continue
        signal = lagged_role_signal(
            grouped[(season, element)], season=season, event=event, element=element
        )
        x.append(design(float(r["p_play"]), signal))
        rows.append(
            {
                **r,
                "target_played": float(target["target_minutes"]) > 0,
                "role_loss_watch": bool(signal["loss_of_regular_role"]),
                "focus": float(r["expected_points"]) >= 2.5 or float(r["p_play"]) >= 0.75,
            }
        )
    matrix = np.asarray(x)
    seasons = np.asarray([r["season"] for r in rows])
    actual = np.asarray([r["target_played"] for r in rows])
    incumbent = np.asarray([r["p_play"] for r in rows])
    folds = []
    for test in ("2024-25", "2025-26"):
        train, holdout = seasons < test, seasons == test
        baseline = _model().fit(matrix[train, :1], actual[train])
        challenger = _model().fit(matrix[train], actual[train])
        predictions = {
            "champion": incumbent[holdout],
            "calibration_only": baseline.predict_proba(matrix[holdout, :1])[:, 1],
            "role_shift": challenger.predict_proba(matrix[holdout])[:, 1],
        }
        cohorts = {}
        for name, mask in {
            "all_single_fixture": np.ones(sum(holdout), dtype=bool),
            "decision_focus": np.asarray([r["focus"] for r in rows])[holdout],
            "role_loss_watch": np.asarray([r["role_loss_watch"] for r in rows])[holdout],
        }.items():
            cohorts[name] = {
                model: _metrics(actual[holdout][mask], values[mask])
                for model, values in predictions.items()
            }
        focus = cohorts["decision_focus"]
        folds.append(
            {
                "test_season": test,
                "training_seasons": sorted(set(seasons[train])),
                "cohorts": cohorts,
                "statistical_screen_passed": all(
                    focus["role_shift"]["brier"] < focus[control]["brier"]
                    and focus["role_shift"]["log_loss"] < focus[control]["log_loss"]
                    for control in ("champion", "calibration_only")
                ),
            }
        )
    fitted = _model().fit(matrix, actual)
    scale, logistic = fitted.steps[0][1], fitted.steps[1][1]
    result = {
        "version": "role_shift_research_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "decision_authority": False,
        "feature_names": FEATURE_NAMES,
        "model": {
            "mean": scale.mean_.tolist(),
            "scale": scale.scale_.tolist(),
            "coefficients": logistic.coef_[0].tolist(),
            "intercept": float(logistic.intercept_[0]),
        },
        "training_seasons": sorted(set(seasons)),
        "folds": folds,
        "rows": len(rows),
        "statistical_screen_passed": all(f["statistical_screen_passed"] for f in folds),
        "promotion_gate": {
            "passed": False,
            "missing": [
                "Matched continuous legal-policy net-points replay",
                "Prospective 2026/27 evidence",
            ],
        },
        "definition": "Two recent non-overlapping single-fixture opportunities versus up to eight older same-season opportunities; no cross-season carryover.",
        "limitations": [
            "Derived official evidence, not an independent tactical/lineup source.",
            "60-minute gameweeks are not literal starts; doubles/blanks excluded.",
            "Current season has little within-season role history; confidence must remain limited.",
            "Historical folds have been inspected in other experiments; not globally untouched.",
        ],
        "sources": {
            "forecast_sha256": sha256_file(BACKTEST_FORECAST),
            "consumed_rows_sha256": hashlib.sha256(
                json.dumps(rows, sort_keys=True).encode()
            ).hexdigest(),
            "implementation_sha256": sha256_file(Path(__file__)),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def current_role_diagnostic(
    rows: list[dict],
    *,
    event: int,
    path: Path = ARTIFACT,
    history_path: Path = CURRENT_PLAYER_HISTORY,
) -> dict:
    artifact = json.loads(path.read_text())
    if artifact.get("version") != "role_shift_research_v1" or artifact["sources"][
        "implementation_sha256"
    ] != sha256_file(Path(__file__)):
        raise ValueError("Role diagnostic model/code lineage mismatch")
    model = artifact["model"]
    grouped = defaultdict(list)
    for r in pq.read_table(history_path).to_pylist():
        grouped[(str(r["season"]), int(r["element"]))].append(r)
    result = []
    for r in rows:
        if int(r["event_number"]) != event:
            continue
        season, element = str(r["season"]), int(r["element"])
        signal = lagged_role_signal(
            grouped[(season, element)], season=season, event=event, element=element
        )
        vector = (np.asarray(design(float(r["p_play"]), signal)) - model["mean"]) / model["scale"]
        probability = float(expit(np.dot(vector, model["coefficients"]) + model["intercept"]))
        supported = float(r.get("fixture_count") or 0) == 1
        result.append(
            {
                "player_id": element,
                "name": str(r["player_name"]),
                "position": r["position"],
                "champion_p_play": float(r["p_play"]),
                "challenger_p_play": probability if supported else None,
                "forecast_status": "scorable_single_fixture"
                if supported
                else "unsupported_fixture_count",
                "signal": signal,
                "fixture_count": r.get("fixture_count"),
                "projection_delta": probability - float(r["p_play"]) if supported else None,
            }
        )
    return {
        "version": "role_shift_research_v1",
        "status": "ready_diagnostic",
        "decision_authority": False,
        "model_sha256": sha256_file(path),
        "history_sha256": sha256_file(history_path),
        "statistical_screen_passed": artifact["statistical_screen_passed"],
        "players": result,
        "interpretation": "Unpromoted appearance diagnostic, not a change to minutes/xP or proof of tactical role.",
        "independent_lineup_sources_added": 0,
    }
