from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb
from scipy.stats import rankdata
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .models import require_cuda
from .paths import ARTIFACTS, MODEL_DATA, REPORTS, ensure_engine_layout

HISTORICAL_GAMEWEEKS = PROCESSED / "vaastav" / "player_gameweeks.parquet"
HISTORICAL_PLAYERS = PROCESSED / "vaastav" / "players.parquet"
CURRENT_PLAYERS = PROCESSED / "fpl" / "2026-27" / "preseason" / "players.parquet"
OUTPUT_DIR = MODEL_DATA / "bps_2026_27_v1"
MODEL_DIR = ARTIFACTS / "bps_2026_27_v1"
TACKLED_MODEL = MODEL_DIR / "tackled-event-model.joblib"
FIXTURE_RECONSTRUCTION = OUTPUT_DIR / "fixture-player-reconstruction.parquet"
CURRENT_PRIORS = OUTPUT_DIR / "current-player-bonus-priors.parquet"
METRICS_FILE = OUTPUT_DIR / "metrics.json"
REPORT = REPORTS / "2026-27-bps-reconstruction.md"

OFFICIAL_SOURCE = (
    "https://www.premierleague.com/en/news/4679946/"
    "whats-new-in-202627-fantasy-changes-to-bonus-points-system"
)

# These are published season totals, not scraped private data. They anchor the
# cross-era scale of the tackled-event proxy and are never treated as fixture labels.
OFFICIAL_TACKLED_TOTALS = {
    "Morgan Rogers": 156,
    "Jarrod Bowen": 143,
    "Antoine Semenyo": 137,
    "Brenden Aaronson": 127,
    "Iliman Ndiaye": 126,
    "Jérémy Doku": 113,
    "Jaidon Anthony": 106,
    "Elliot Anderson": 104,
    "Mohammed Kudus": 104,
    "Mohamed Salah": 103,
    "Michael Kayode": 83,
    "Hugo Bueno López": 78,
    "Jayden Bogle": 72,
    "Djed Spence": 72,
    "Nico O'Reilly": 69,
    "Lewis Hall": 69,
}

OFFICIAL_BIG_CHANCE_SAVE_TOTALS = {
    "Jordan Pickford": 28,
    "Caoimhín Kelleher": 27,
    "Dean Henderson": 26,
    "Martin Dúbravka": 23,
    "Bernd Leno": 22,
}

POSITIONS = ("GK", "DEF", "MID", "FWD")
MODEL_FEATURES = (
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "yellow_cards",
    "red_cards",
    "saves",
    "penalties_saved",
    "was_home",
    "team_h_score",
    "team_a_score",
    "influence",
    "creativity",
    "threat",
    "ict_index",
    "clearances_blocks_interceptions",
    "recoveries",
    "tackles",
)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _historical_rows(seasons: tuple[str, ...]) -> pa.Table:
    values = ", ".join(f"'{season}'" for season in seasons)
    connection = duckdb.connect()
    try:
        return connection.execute(
            f"""
            SELECT
                g.*,
                p.code AS player_code,
                CASE p.element_type
                    WHEN 1 THEN 'GK'
                    WHEN 2 THEN 'DEF'
                    WHEN 3 THEN 'MID'
                    WHEN 4 THEN 'FWD'
                END AS reconstructed_position
            FROM read_parquet('{_sql_path(HISTORICAL_GAMEWEEKS)}') g
            LEFT JOIN read_parquet('{_sql_path(HISTORICAL_PLAYERS)}') p
              ON g.season = p.season AND g.element = p.id
            WHERE g.season IN ({values})
            ORDER BY g.season, g.fixture, g.element
            """
        ).fetch_arrow_table()
    finally:
        connection.close()


def _values(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(
        [0.0 if value is None else float(value) for value in table[name].to_pylist()],
        dtype=np.float32,
    )


def _strings(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(table[name].to_pylist(), dtype=object)


def _positions(table: pa.Table) -> np.ndarray:
    stored = _strings(table, "position")
    reconstructed = _strings(table, "reconstructed_position")
    missing = np.fromiter((value is None for value in stored), dtype=bool)
    return np.where(missing, reconstructed, stored)


def _matrix(table: pa.Table) -> np.ndarray:
    positions = _positions(table)
    numeric = [_values(table, name) for name in MODEL_FEATURES]
    one_hot = [(positions == position).astype(np.float32) for position in POSITIONS]
    return np.column_stack([*numeric, *one_hot]).astype(np.float32, copy=False)


def _tackled_model(seed: int) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="count:poisson",
        eval_metric="poisson-nloglik",
        n_estimators=650,
        learning_rate=0.03,
        max_depth=4,
        min_child_weight=15.0,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.1,
        reg_lambda=8.0,
        tree_method="hist",
        device="cuda",
        random_state=seed,
        n_jobs=8,
    )


def _rank_correlation(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return float("nan")
    return float(
        np.corrcoef(rankdata(left, method="average"), rankdata(right, method="average"))[0, 1]
    )


def _baseline_tackled_rate(
    train: pa.Table, test: pa.Table, target: np.ndarray
) -> np.ndarray:
    train_positions = _positions(train)
    test_positions = _positions(test)
    train_minutes = _values(train, "minutes")
    test_minutes = _values(test, "minutes")
    output = np.zeros(test.num_rows, dtype=np.float32)
    for position in POSITIONS:
        selected = train_positions == position
        rate = float(target[selected].sum() / max(train_minutes[selected].sum(), 1.0))
        output[test_positions == position] = rate * test_minutes[test_positions == position]
    return output


def _aggregate_player_metrics(
    table: pa.Table, actual: np.ndarray, predicted: np.ndarray, baseline: np.ndarray
) -> dict[str, float | int]:
    names = _strings(table, "name")
    minutes = _values(table, "minutes")
    aggregates = []
    for name in np.unique(names):
        selected = names == name
        aggregates.append(
            (
                float(actual[selected].sum()),
                float(predicted[selected].sum()),
                float(baseline[selected].sum()),
                float(minutes[selected].sum()),
            )
        )
    values = np.asarray(aggregates)
    active = values[:, 3] >= 450.0
    return {
        "players_450_minutes": int(active.sum()),
        "model_mae": float(mean_absolute_error(values[active, 0], values[active, 1])),
        "baseline_mae": float(mean_absolute_error(values[active, 0], values[active, 2])),
        "model_spearman": _rank_correlation(values[active, 0], values[active, 1]),
        "baseline_spearman": _rank_correlation(values[active, 0], values[active, 2]),
    }


def _fit_tackled_proxy(seed: int) -> tuple[xgb.XGBRegressor, dict[str, Any], pa.Table, np.ndarray]:
    cuda = require_cuda()
    historical = _historical_rows(("2016-17", "2017-18", "2018-19"))
    seasons = _strings(historical, "season")
    target = _values(historical, "tackled")
    matrix = _matrix(historical)
    train_mask = np.isin(seasons, ["2016-17", "2017-18"])
    test_mask = seasons == "2018-19"
    holdout_model = _tackled_model(seed)
    holdout_model.fit(matrix[train_mask], target[train_mask], verbose=False)
    predicted = np.clip(holdout_model.predict(matrix[test_mask]), 0.001, None)
    train = historical.filter(pa.array(train_mask))
    test = historical.filter(pa.array(test_mask))
    baseline = _baseline_tackled_rate(train, test, target[train_mask])
    holdout = {
        "train_seasons": ["2016-17", "2017-18"],
        "test_season": "2018-19",
        "rows": int(test_mask.sum()),
        "row_model_mae": float(mean_absolute_error(target[test_mask], predicted)),
        "row_baseline_mae": float(mean_absolute_error(target[test_mask], baseline)),
        "row_model_poisson_deviance": float(
            mean_poisson_deviance(target[test_mask], predicted)
        ),
        "row_baseline_poisson_deviance": float(
            mean_poisson_deviance(target[test_mask], np.clip(baseline, 0.001, None))
        ),
        "player_season": _aggregate_player_metrics(
            test, target[test_mask], predicted, baseline
        ),
    }
    final_model = _tackled_model(seed)
    final_model.fit(matrix, target, verbose=False)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "version": 1,
            "features": [*MODEL_FEATURES, *(f"position_{p.lower()}" for p in POSITIONS)],
            "model": final_model,
            "trained_seasons": ["2016-17", "2017-18", "2018-19"],
            "cuda": cuda,
        },
        TACKLED_MODEL,
        compress=3,
    )
    return final_model, holdout, historical, matrix


def allocate_bonus(bps: np.ndarray, minutes: np.ndarray) -> np.ndarray:
    """Apply FPL's tie rules to a single match."""
    output = np.zeros(len(bps), dtype=np.int8)
    eligible = np.flatnonzero(minutes > 0)
    if not len(eligible):
        return output
    scores = sorted({int(bps[index]) for index in eligible}, reverse=True)
    groups = [eligible[bps[eligible] == score] for score in scores]
    output[groups[0]] = 3
    if len(groups[0]) == 1 and len(groups) > 1:
        output[groups[1]] = 2
        if len(groups[1]) == 1 and len(groups) > 2:
            output[groups[2]] = 1
    elif len(groups[0]) == 2 and len(groups) > 1:
        output[groups[1]] = 1
    return output


def cbi_bps_delta(cbi: np.ndarray) -> np.ndarray:
    values = np.asarray(cbi, dtype=np.int16)
    return (values // 3 - values // 2).astype(np.int8)


def _fixture_groups(fixtures: np.ndarray) -> list[np.ndarray]:
    return [np.flatnonzero(fixtures == fixture) for fixture in np.unique(fixtures)]


def _control_reconstruction(table: pa.Table) -> tuple[np.ndarray, dict[str, Any]]:
    bps = _values(table, "bps").astype(np.int16)
    minutes = _values(table, "minutes").astype(np.int16)
    actual = _values(table, "bonus").astype(np.int8)
    fixtures = _values(table, "fixture").astype(np.int32)
    reconstructed = np.zeros(table.num_rows, dtype=np.int8)
    exact_fixtures = 0
    for indices in _fixture_groups(fixtures):
        reconstructed[indices] = allocate_bonus(bps[indices], minutes[indices])
        exact_fixtures += int(np.array_equal(reconstructed[indices], actual[indices]))
    return reconstructed, {
        "fixtures": len(np.unique(fixtures)),
        "fixture_exact_rate": float(exact_fixtures / len(np.unique(fixtures))),
        "player_row_exact_rate": float(np.mean(reconstructed == actual)),
        "actual_bonus_points": int(actual.sum()),
        "reconstructed_bonus_points": int(reconstructed.sum()),
    }


def _scale_tackled_rates(
    table: pa.Table, raw_rates: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    names = _strings(table, "name")
    positions = _positions(table)
    minutes = _values(table, "minutes")
    comparisons = []
    ratios: dict[str, list[float]] = defaultdict(list)
    for name, actual in OFFICIAL_TACKLED_TOTALS.items():
        selected = names == name
        predicted = float(raw_rates[selected].sum())
        if not selected.any() or predicted <= 0:
            continue
        group = "DEF" if positions[selected][0] == "DEF" else "ATT"
        ratios[group].append(actual / predicted)
        comparisons.append(
            {
                "player": name,
                "position": str(positions[selected][0]),
                "official_total": actual,
                "raw_model_total": predicted,
                "raw_ratio": actual / predicted,
            }
        )
    scale = {
        "DEF": float(np.median(ratios["DEF"])),
        "ATT": float(np.median(ratios["ATT"])),
        "GK": 1.0,
    }
    calibrated = raw_rates.copy().astype(np.float64)
    for position in POSITIONS:
        group = "DEF" if position == "DEF" else "GK" if position == "GK" else "ATT"
        calibrated[positions == position] *= scale[group]
    # Published totals override only season aggregates. Fixture distribution still
    # comes entirely from the time-forward event model.
    for name, actual in OFFICIAL_TACKLED_TOTALS.items():
        selected = names == name
        total = calibrated[selected].sum()
        if selected.any() and total > 0:
            calibrated[selected] *= actual / total
    calibrated[minutes <= 0] = 0.0
    raw_official = np.asarray([row["raw_model_total"] for row in comparisons])
    official = np.asarray([row["official_total"] for row in comparisons])
    adjusted_official = np.asarray(
        [calibrated[names == row["player"]].sum() for row in comparisons]
    )
    metrics = {
        "published_players_found": len(comparisons),
        "published_players_expected": len(OFFICIAL_TACKLED_TOTALS),
        "position_scale_medians": scale,
        "raw_total_mae": float(mean_absolute_error(official, raw_official)),
        "raw_total_spearman": _rank_correlation(official, raw_official),
        "anchored_total_mae": float(mean_absolute_error(official, adjusted_official)),
        "comparisons": comparisons,
        "scope": (
            "Published totals calibrate the selectable-player scale; they do not reveal "
            "which fixtures contained the tackled events."
        ),
    }
    return calibrated, metrics


def _sample_tackled(
    table: pa.Table, rates: np.ndarray, simulations: int, rng: np.random.Generator
) -> np.ndarray:
    names = _strings(table, "name")
    samples = rng.poisson(rates[None, :], size=(simulations, table.num_rows)).astype(np.int16)
    for name, total in OFFICIAL_TACKLED_TOTALS.items():
        indices = np.flatnonzero(names == name)
        if not len(indices):
            continue
        probabilities = rates[indices]
        probabilities /= probabilities.sum()
        samples[:, indices] = rng.multinomial(total, probabilities, size=simulations)
    return samples


def _sample_known_big_chance_saves(
    table: pa.Table, simulations: int, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    names = _strings(table, "name")
    saves = _values(table, "saves").astype(np.int16)
    penalties = _values(table, "penalties_saved").astype(np.int16)
    samples = np.zeros((simulations, table.num_rows), dtype=np.int16)
    found = []
    for name, published_total in OFFICIAL_BIG_CHANCE_SAVE_TOTALS.items():
        indices = np.flatnonzero(names == name)
        if not len(indices):
            continue
        penalty_total = int(penalties[indices].sum())
        non_penalty_total = max(published_total - penalty_total, 0)
        available = np.maximum(saves[indices] - penalties[indices], 0)
        probability = min(non_penalty_total / max(int(available.sum()), 1), 1.0)
        samples[:, indices] = rng.binomial(available[None, :], probability)
        found.append(
            {
                "player": name,
                "published_big_chance_saves": published_total,
                "penalty_saves": penalty_total,
                "modelled_non_penalty_big_chance_saves": non_penalty_total,
            }
        )
    return samples, {
        "published_players_found": len(found),
        "published_players_expected": len(OFFICIAL_BIG_CHANCE_SAVE_TOTALS),
        "players": found,
        "limitation": (
            "The archive lacks save location and big-chance flags. Only the five official "
            "published season totals receive a goalkeeper uplift; other keepers remain neutral."
        ),
    }


def _counterfactual_bonus(
    table: pa.Table,
    tackled_rates: np.ndarray,
    simulations: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    rng = np.random.default_rng(seed)
    bps = _values(table, "bps").astype(np.int16)
    minutes = _values(table, "minutes").astype(np.int16)
    cbi = _values(table, "clearances_blocks_interceptions").astype(np.int16)
    fixtures = _values(table, "fixture").astype(np.int32)
    actual_bonus = _values(table, "bonus").astype(np.int8)
    cbi_delta = cbi_bps_delta(cbi)
    tackled = _sample_tackled(table, tackled_rates, simulations, rng)
    keeper_uplift, keeper_metrics = _sample_known_big_chance_saves(table, simulations, rng)
    bonus_samples = np.zeros((simulations, table.num_rows), dtype=np.int8)
    for indices in _fixture_groups(fixtures):
        for simulation in range(simulations):
            adjusted = (
                bps[indices]
                + cbi_delta[indices]
                + tackled[simulation, indices]
                + keeper_uplift[simulation, indices]
            )
            bonus_samples[simulation, indices] = allocate_bonus(adjusted, minutes[indices])
    mean_bonus = bonus_samples.mean(axis=0).astype(np.float32)
    mean_delta = (mean_bonus - actual_bonus).astype(np.float32)
    probability_change = np.mean(bonus_samples != actual_bonus[None, :], axis=0).astype(
        np.float32
    )
    return mean_bonus, mean_delta, probability_change, keeper_metrics


def _write_current_priors(table: pa.Table, mean_delta: np.ndarray) -> dict[str, Any]:
    names = _strings(table, "name")
    codes = _strings(table, "player_code")
    positions = _positions(table)
    minutes = _values(table, "minutes")
    aggregates: dict[int, dict[str, Any]] = {}
    position_values: dict[str, list[float]] = defaultdict(list)
    populated_codes = np.asarray([code for code in codes if code is not None], dtype=object)
    for code in np.unique(populated_codes):
        selected = codes == code
        appearances = int(np.sum(minutes[selected] > 0))
        if not appearances:
            continue
        delta = float(mean_delta[selected].sum() / appearances)
        position = str(positions[selected][0])
        aggregates[int(code)] = {
            "historical_name": str(names[selected][0]),
            "historical_position": position,
            "historical_appearances": appearances,
            "raw_bonus_delta_per_appearance": delta,
        }
        position_values[position].extend([delta] * appearances)
    position_priors = {
        position: float(np.mean(position_values[position])) if position_values[position] else 0.0
        for position in POSITIONS
    }
    current = pq.read_table(CURRENT_PLAYERS)
    output = []
    position_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    for row in current.to_pylist():
        position = position_map[int(row["element_type"])]
        historical = aggregates.get(int(row["code"]))
        if position == "GK":
            appearances = int(historical["historical_appearances"]) if historical else 0
            delta = 0.0
            source = "neutral_missing_full_save_context"
        elif historical:
            appearances = int(historical["historical_appearances"])
            weight = appearances / (appearances + 20.0)
            delta = (
                weight * float(historical["raw_bonus_delta_per_appearance"])
                + (1.0 - weight) * position_priors[position]
            )
            source = "player_shrunk_to_current_position"
        else:
            appearances = 0
            delta = position_priors[position]
            source = "position_prior"
        output.append(
            {
                "element": int(row["id"]),
                "player_code": int(row["code"]),
                "player_name": row["web_name"],
                "position": position,
                "historical_appearances": appearances,
                "bonus_delta_per_appearance": float(delta),
                "source": source,
                "promoted": position != "GK",
            }
        )
    output_table = pa.Table.from_pylist(output)
    pq.write_table(output_table, CURRENT_PRIORS, compression="zstd")
    return {
        "rows": len(output),
        "matched_current_players": sum(row["historical_appearances"] > 0 for row in output),
        "position_priors": position_priors,
        "sha256": sha256_file(CURRENT_PRIORS),
    }


def reconstruct_2026_27_bps(
    simulations: int = 400, seed: int = 20260803
) -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model, holdout, _, _ = _fit_tackled_proxy(seed)
    season = _historical_rows(("2025-26",))
    raw_rates = np.clip(model.predict(_matrix(season)), 0.001, None)
    tackled_rates, official_calibration = _scale_tackled_rates(season, raw_rates)
    control_bonus, control = _control_reconstruction(season)
    if control["fixture_exact_rate"] != 1.0:
        raise RuntimeError(f"Historical bonus control failed: {control}")
    mean_bonus, mean_delta, probability_change, keeper_metrics = _counterfactual_bonus(
        season, tackled_rates, simulations, seed
    )
    cbi = _values(season, "clearances_blocks_interceptions").astype(np.int16)
    positions = _positions(season)
    cbi_delta = cbi_bps_delta(cbi)
    rows = []
    for index, row in enumerate(season.to_pylist()):
        rows.append(
            {
                "season": row["season"],
                "fixture": int(row["fixture"]),
                "event_number": int(row["GW"]),
                "element": int(row["element"]),
                "player_code": row["player_code"],
                "player_name": row["name"],
                "position": str(positions[index]),
                "minutes": int(row["minutes"]),
                "original_bps": int(row["bps"]),
                "actual_bonus": int(row["bonus"]),
                "control_bonus": int(control_bonus[index]),
                "cbi": int(cbi[index]),
                "exact_cbi_bps_delta": int(cbi_delta[index]),
                "modelled_tackled_events": float(tackled_rates[index]),
                "mean_counterfactual_bonus": float(mean_bonus[index]),
                "mean_bonus_delta": float(mean_delta[index]),
                "probability_bonus_changes": float(probability_change[index]),
            }
        )
    fixture_table = pa.Table.from_pylist(rows)
    pq.write_table(fixture_table, FIXTURE_RECONSTRUCTION, compression="zstd")
    priors = _write_current_priors(season, mean_delta)
    played = _values(season, "minutes") > 0
    by_position = {}
    for position in POSITIONS:
        selected = played & (positions == position)
        by_position[position] = {
            "appearances": int(selected.sum()),
            "mean_bonus_delta_per_appearance": float(mean_delta[selected].mean()),
            "changed_bonus_row_rate": float((probability_change[selected] > 0.05).mean()),
        }
    gate = {
        "control_exact": control["fixture_exact_rate"] == 1.0,
        "tackled_proxy_beats_baseline_row_mae": (
            holdout["row_model_mae"] < holdout["row_baseline_mae"]
        ),
        "tackled_proxy_beats_baseline_player_mae": (
            holdout["player_season"]["model_mae"]
            < holdout["player_season"]["baseline_mae"]
        ),
        "tackled_proxy_player_spearman_above_0_80": (
            holdout["player_season"]["model_spearman"] > 0.80
        ),
        "official_tackled_tables_complete": (
            official_calibration["published_players_found"]
            == official_calibration["published_players_expected"]
        ),
        "official_keeper_table_complete": (
            keeper_metrics["published_players_found"]
            == keeper_metrics["published_players_expected"]
        ),
    }
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source": OFFICIAL_SOURCE,
        "simulations": simulations,
        "seed": seed,
        "cuda": require_cuda(),
        "control": control,
        "tackled_proxy_holdout": holdout,
        "official_tackled_calibration": official_calibration,
        "keeper_reconstruction": keeper_metrics,
        "counterfactual_by_position": by_position,
        "current_priors": priors,
        "promoted_positions": ["DEF", "MID", "FWD"],
        "gate": gate,
        "promoted": all(gate.values()),
        "scope": {
            "exact": [
                "historical bonus allocation and tie rules",
                "CBI denominator change for every 2025/26 player-fixture",
            ],
            "modelled": [
                "removed tackled penalty, season totals anchored for 16 published leaders",
                "non-penalty big-chance saves for five published goalkeepers",
            ],
            "unknown_and_left_neutral": [
                "fixture identity of published tackled and big-chance-save season totals",
                "save location and deflected-cross saves",
                "big-chance saves for goalkeepers outside the published top five",
            ],
        },
        "artifacts": {
            "model": str(TACKLED_MODEL),
            "model_sha256": sha256_file(TACKLED_MODEL),
            "fixture_reconstruction": str(FIXTURE_RECONSTRUCTION),
            "fixture_sha256": sha256_file(FIXTURE_RECONSTRUCTION),
            "current_priors": str(CURRENT_PRIORS),
        },
    }
    METRICS_FILE.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    holdout = result["tackled_proxy_holdout"]
    player = holdout["player_season"]
    lines = [
        "# 2026/27 Bonus Points System reconstruction",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Monte Carlo worlds:** {result['simulations']:,}  ",
        f"**Promotion gate:** {'PASS' if result['promoted'] else 'FAIL'}",
        "",
        "## What is proven",
        "",
        (
            f"The tie-aware control reproduces {result['control']['fixtures']} of "
            f"{result['control']['fixtures']} 2025/26 match allocations exactly and all "
            f"{result['control']['actual_bonus_points']:,} awarded bonus points."
        ),
        "",
        "The CBI change is exact at player-match level: `floor(CBI / 3) - floor(CBI / 2)`.",
        "",
        "## The missing tackled event",
        "",
        (
            "The public 2025/26 archive does not contain the tackled event. A GPU Poisson model "
            "was trained on 2016/17 and 2017/18 and tested strictly forward on 2018/19."
        ),
        "",
        f"- Row MAE: {holdout['row_model_mae']:.3f} vs {holdout['row_baseline_mae']:.3f} baseline.",
        (
            f"- Active-player season MAE: {player['model_mae']:.2f} vs "
            f"{player['baseline_mae']:.2f} baseline."
        ),
        f"- Active-player season rank correlation: {player['model_spearman']:.3f}.",
        "",
        (
            "The official 2025/26 top-ten and defender tables anchor the modern scale. Their "
            "published season totals are exact; match placement remains simulated from the model."
        ),
        "",
        "## Counterfactual effect",
        "",
        "| Position | Appearances | Mean bonus delta/appearance | Rows with >5% change chance |",
        "| --- | ---: | ---: | ---: |",
    ]
    for position, row in result["counterfactual_by_position"].items():
        lines.append(
            f"| {position} | {row['appearances']:,} | "
            f"{row['mean_bonus_delta_per_appearance']:+.3f} | "
            f"{row['changed_bonus_row_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Boundary of confidence",
            "",
            (
                "This is a promoted correction prior, not a claim that the complete Opta BPS feed "
                "has been recreated. Unknown goalkeeper save locations and unpublished big-chance "
                "saves make the displayed GK counterfactual a lower bound, so goalkeeper deltas are "
                "not promoted into live forecasts. The live simulator keeps match-level bonus "
                "conservation and applies the promoted outfield deltas only to bonus propensity."
            ),
            "",
            f"Official source: {result['source']}",
            "",
        ]
    )
    return "\n".join(lines)
