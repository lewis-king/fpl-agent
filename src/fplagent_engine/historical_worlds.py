"""Explicit, prefix-fitted historical worlds for policy research, never publication.

Reuses the production samplers, not production-trained artifacts. Future match
strength uses the origin's ratings and dated schedule, not later forecast rows.
This is still an architecture replay: archived markets/lineup consensus and the
2025 defensive-contribution prior are unavailable before those seasons.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pyarrow.parquet as pq

from .acceleration import xgboost_infer
from .component_models import MODEL_DIR
from .component_simulator import (
    ComponentSimulationInputs,
    _goal_feature_vector,
    _goal_regressor,
    _historical_goal_rows,
    _paired_residual_correlation,
    calibrate_empirical_components,
    simulate_component_outcomes,
)
from .models import SEEDS, TRAINING_FEATURES, _classifier, _matrix, _season_weights
from .sequential_policy_replay import deadline_world, fit_prefix
from .team_strength import (
    DynamicTeamRatings,
    Fixture,
    RatingParameters,
)
from .transfer_value import ARTIFACT as TRANSFER_VALUE_ARTIFACT
from .weekly_actions import _forecast_grid

WEIGHTS = {"residual": 0.5, "component_anchored": 0.45, "component_raw": 0.05}
BINS = ("p_dnp", "p_1_59", "p_60_89", "p_90_or_more")
COMPONENT_OOF = MODEL_DIR / "rolling-backtest.parquet"
HISTORICAL_TEAMS = TRAINING_FEATURES.parents[2] / "processed/vaastav/teams.parquet"


def origin_cutoff(features, fixtures, origin):
    """Use observed archives; missing origin metadata is explicit, never future-filled."""
    observed = [datetime.fromisoformat(str(f["observed_at"]))
                for f in fixtures if f.get("observed_at")]
    deadlines = {f["deadline_at"] for f in features.values() if f.get("deadline_at")}
    if len(deadlines) > 1 or not observed:
        raise ValueError("Conflicting origin deadline or missing dated fixture evidence")
    missing = not deadlines
    if missing:
        kickoffs = [f["kickoff_time"] for f in fixtures
                    if f.get("event") == origin and f.get("kickoff_time")]
        if not kickoffs:
            raise ValueError("Missing origin deadline and scheduled fixture proxy")
        # Same labelled proxy as vaastav_deadlines, NOT an observed true deadline.
        # Team-rating updates stop earlier at the dated archive observation.
        deadline = min(kickoffs) - timedelta(minutes=90)
    else:
        deadline = next(iter(deadlines))
    if any(t >= deadline for t in observed):
        raise ValueError("Fixture archive is not strictly before the origin deadline")
    return min(observed), {
        "origin_deadline_metadata_missing": missing,
        "deadline_proxy": deadline.isoformat(),
        "same_event_player_snapshot_rows": sum(bool(f.get("deadline_proxy_available")) for f in features.values()),
        "player_rows": len(features),
        "price_caveat": "Uncovered features use earlier lagged prices, not verified deadline execution quotes; no full live-replication claim.",
    }


def prefix_transfer_curve(observations, season, maximum=5):
    """Fit only earlier-season opportunity values, never the final selected curve."""
    prior = [r for r in observations if r["season"] < season]
    if not prior:
        raise ValueError("No earlier free-transfer opportunity observations")
    values = np.asarray([[r["cumulative_value_by_bank"][str(i)]
                          for i in range(maximum + 1)] for r in prior], dtype=float)
    if not np.isfinite(values).all() or np.any(values[:, 0] != 0):
        raise ValueError("Invalid historical FT opportunity observation")
    curve = np.maximum.accumulate(np.maximum(values.mean(axis=0), 0))
    return {i: float(v) for i, v in enumerate(curve)}, {
        "training_seasons": sorted({r["season"] for r in prior}), "observations": len(prior),
        "method": "nonnegative monotone mean of earlier-season cumulative opportunity values",
        "production_promotion": False,
        "caveat": "Small historical sample; common comparator assumption, not a validated replacement FT model.",
    }


def anchor_bins(probability, p_play):
    """Retain conditional minute shape but exactly honour the archived p(play)."""
    probability = np.asarray(probability, dtype=float)
    if (probability.shape != (4,) or not np.isfinite(probability).all()
            or np.any(probability < 0) or not 0 <= p_play <= 1):
        raise ValueError("Invalid historical minute probability")
    total = probability[1:].sum()
    if p_play and not total:
        raise ValueError("Cannot invent a conditional minute shape")
    return np.r_[1 - p_play, probability[1:] * (p_play / total if total else 0)]


def ratings_at_origin(fixtures, season, cutoff, initial_rates):
    """Never update from an unfinished/current/future match, even if known now."""
    ratings = DynamicTeamRatings(RatingParameters(), *initial_rates)
    for year in sorted({f.season for f in fixtures if f.season <= season}):
        group = [f for f in fixtures if f.season == year]
        # Club membership and season opening dates are schedule facts, not scores.
        codes = {c for f in group for c in (f.home_code, f.away_code)}
        ratings.begin_season(year, codes, min(f.kickoff for f in group))
        eligible = [f for f in group if f.kickoff < cutoff]
        for kickoff in sorted({f.kickoff for f in eligible}):
            ratings.update([f for f in eligible if f.kickoff == kickoff])
    return ratings


@dataclass
class PrefixWorlds:
    season: str
    residual: object
    shapes: dict
    empirical: object
    minute_bins: dict
    components: dict
    goal_model: object
    goal_medians: np.ndarray
    score_correlation: float
    historical_fixtures: list
    initial_rates: tuple
    terminal_curve: dict
    provenance: dict

    @classmethod
    def fit(cls, inputs, season, residual_fixtures, progress=None):
        def report(message):
            if progress:
                progress({"season": season, "stage": message})

        report("fitting past-only empirical components and free-transfer value")
        residual, shapes = fit_prefix(inputs, season, residual_fixtures)
        empirical = calibrate_empirical_components(before_season=season)
        curve, curve_audit = prefix_transfer_curve(
            json.loads(TRANSFER_VALUE_ARTIFACT.read_text())["observations"], season)
        table = pq.read_table(TRAINING_FEATURES)
        seasons = np.array(table["season"].to_pylist())
        positions = np.array(table["position"].to_pylist())
        classes = np.array(table["minutes_class"].to_pylist())
        matrix = _matrix(table)
        previous = sorted(set(seasons[seasons < season]))
        if len(previous) < 2:
            raise ValueError("Minute classifier needs separate earlier training/validation seasons")
        ids = table["element"].to_pylist()
        events = table["event_number"].to_pylist()
        bins, minute_audit = {}, {}
        for position in ("GK", "DEF", "MID", "FWD"):
            train = (seasons < previous[-1]) & (positions == position)
            valid = (seasons == previous[-1]) & (positions == position)
            test = (seasons == season) & (positions == position)
            report(f"recreating existing {position} minute classifier on earlier seasons")
            model = _classifier(SEEDS[0], 900, early_stopping=True)
            model.fit(matrix[train], classes[train], sample_weight=_season_weights(seasons, train),
                      eval_set=[(matrix[valid], classes[valid])], verbose=False)
            predictions = xgboost_infer(model, matrix[test], method="predict_proba")
            for index, probabilities in zip(np.flatnonzero(test), predictions, strict=True):
                bins[(events[index], ids[index])] = probabilities
            minute_audit[position] = {"training_rows": int(train.sum()),
                                      "validation_rows": int(valid.sum()),
                                      "validation_season": str(previous[-1]),
                                      "best_iteration": int(model.best_iteration)}
        report("fitting earlier-season goal model and validation-only score correlation")
        metadata, gs, target, design = _historical_goal_rows()
        val_season = max(gs[gs < season])
        earlier, validation, train = gs < val_season, gs == val_season, gs < season

        def fit(mask):
            medians = np.nanmedian(design[mask], axis=0)
            model = _goal_regressor(20260802)
            model.fit(np.where(np.isnan(design[mask]), medians, design[mask]), target[mask])
            return model, medians

        validation_model, vm = fit(earlier)
        vp = xgboost_infer(validation_model,
                           np.where(np.isnan(design[validation]), vm, design[validation]))
        correlation = float(np.clip(_paired_residual_correlation(
            metadata, validation, target[validation] - vp), -0.15, 0.15))
        goal_model, medians = fit(train)
        components = defaultdict(dict)
        for row in pq.read_table(COMPONENT_OOF, filters=[("season", "=", season)]).to_pylist():
            components[(int(row["event_number"]), int(row["element"]))][row["component"]] = row["predicted"]
        teams = {(r["season"], int(r["id"])): int(r["code"])
                 for r in pq.read_table(HISTORICAL_TEAMS).to_pylist()}
        first_mapped_season = min(s for s, _ in teams)
        fixtures = [Fixture(str(f["season"]), int(f["event"]), int(f["id"]),
                            datetime.fromisoformat(str(f["kickoff_time"])), int(f["team_h"]), int(f["team_a"]),
                            teams[(f["season"], int(f["team_h"]))], teams[(f["season"], int(f["team_a"]))],
                            int(f["team_h_score"]), int(f["team_a_score"]))
                    for f in residual_fixtures if f.get("event") is not None and f.get("kickoff_time")
                    and first_mapped_season <= f["season"] <= season
                    and f.get("team_h_score") is not None and f.get("team_a_score") is not None]
        # 2018/19 supplies the long-run initial rate but has no archived club-code
        # table. Start rating updates at 2019/20, as the original inner join did.
        initial_rates = tuple(float(np.mean([f[name] for f in residual_fixtures
                                             if f["season"] == "2018-19" and f.get(name) is not None]))
                              for name in ("team_h_score", "team_a_score"))
        provenance = {"training_before": season, "minute_models": minute_audit,
                      "empirical_rows": empirical.rows, "goal_training_rows": int(train.sum()),
                      "goal_correlation_validation_season": str(val_season),
                      "goal_score_correlation": correlation, "terminal_curve_fit": curve_audit,
                      "component_models": "prefix-trained OOF predictions; fixed enabled components, no retrospective promotion flags",
                      "limitations": [
                          "Historical one-event xP is extrapolated at each origin; no future forecast rows.",
                          "Production markets and predicted-lineup consensus are not archived for these origins.",
                          "Unit residual scales are shared fixed research settings, not retrospectively tuned production scales.",
                          "No earlier defensive-contribution prior for 2025/26; raw component DC points are zero.",
                          "OOF models/features were developed after these seasons; prefix fitting is not a pristine prospective test.",
                      ]}
        return cls(season, residual, shapes, empirical, bins, components, goal_model, medians,
                   correlation, fixtures, initial_rates, curve, provenance)

    def prepare(self, inputs, rows, fixtures, origin):
        features = {p: inputs["feature_by_key"][(self.season, origin, p)]
                    for p in {int(r["element"]) for r in rows}}
        output, components = [], {}
        for row in rows:
            p, event = int(row["element"]), int(row["event_number"])
            source = features[p]
            probabilities = anchor_bins(self.minute_bins[(origin, p)], float(row["p_play"]))
            # Only known-at-origin features; explicitly discard outcome labels.
            known = {k: v for k, v in source.items()
                     if not k.startswith(("target_", "realized_")) and k != "minutes_class"}
            output.append({**known, **row, **dict(zip(BINS, probabilities, strict=True))})
            prediction = self.components.get((origin, p), {})
            expected_minutes = sum(probabilities[c] * float(self.empirical.minute_pools[(row["position"], c)].mean())
                                   for c in (1, 2, 3))
            components[(p, event)] = {"expected_minutes": expected_minutes,
                                      **{f"expected_{k}": v for k, v in prediction.items()},
                                      **{f"{k}_model_promoted": k in prediction for k in ("goals", "assists", "bonus")}}
        # Every future fixture is forecast from this same information set.
        cutoff, coverage = origin_cutoff(features, fixtures, origin)
        ratings = ratings_at_origin(self.historical_fixtures, self.season, cutoff, self.initial_rates)
        codes = {team: code for f in self.historical_fixtures if f.season == self.season
                 for team, code in ((f.home_id, f.home_code), (f.away_id, f.away_code))}
        relevant = [f for f in fixtures if f.get("event") in {r["event_number"] for r in rows}]
        design, keys = [], []
        for f in relevant:
            h, a, e = int(f["team_h"]), int(f["team_a"]), int(f["event"])
            fixture = Fixture(self.season, e, int(f["id"]), f["kickoff_time"], h, a,
                              codes[h], codes[a], None, None)
            home, away, _ = ratings.snapshot(fixture, cutoff)
            design.extend((_goal_feature_vector(home, True), _goal_feature_vector(away, False)))
            keys.append((e, h, a))
        design = np.asarray(design, dtype=np.float32)
        predicted = np.clip(xgboost_infer(self.goal_model, np.where(np.isnan(design), self.goal_medians, design)), 0.15, 4.5)
        goals = {key: tuple(map(float, predicted[2*i:2*i+2])) for i, key in enumerate(keys)}
        return output, components, goals, {**coverage, "observed_before": cutoff.isoformat(),
                                           "fixture_count": len(relevant), "origin_event": origin}

    def sample(self, rows, fixtures, components, goals, *, events, samples, seed):
        residual = deadline_world(rows, fixtures, self.residual, events=events, samples=samples, seed=seed)
        by_player, meta = _forecast_grid(rows, events)
        explicit = ComponentSimulationInputs(fixtures, self.residual, components,
                                             self.score_correlation, self.provenance)
        ids, raw, anchored, played, _means, diagnostic = simulate_component_outcomes(
            by_player, events, goals, self.empirical, samples, seed + 1,
            simulation_inputs=explicit, component_point_weights={"defensive_contribution_points": 0})
        if ids != residual["player_ids"]:
            raise ValueError("Historical world player alignment changed")
        base = {"player_ids": ids, "player_meta": meta, "played": played}
        worlds = {"residual": residual, "component_anchored": {**base, "points": anchored},
                  "component_raw": {**base, "points": raw}}
        return worlds, diagnostic
