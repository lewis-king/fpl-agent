from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.arrow import write_table
from fplagent_data.http import sha256_file

from .features import MODEL_FEATURES, POSITIONS, TRAINING_FEATURES
from .models import (
    BACKTEST_FORECAST,
    SEEDS,
    _classifier,
    _matrix,
    _predict_hurdle,
    _regressor,
    _season_weights,
    _strings,
    require_cuda,
)
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .rules import SquadRules, load_rules
from .tournament import _autosub_weights, _score_candidates

OUTPUT_DIR = MODEL_DATA / "bench_history_v1"
FORECASTS = OUTPUT_DIR / "rolling-forecasts.parquet"
RESULTS = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "historical-bench-depth-audit.md"

TEST_SEASONS = (
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
    "2025-26",
)
EARLY_TEST_SEASONS = TEST_SEASONS[:4]
HORIZON = 5
REGULAR_WINDOW_STARTS = (1, 6, 11, 16, 21, 26, 31)
# The compressed 2020/21 pandemic calendar is deliberately not treated as an
# analogue for an ordinary current-season five-Gameweek planning horizon.
EXTRAORDINARY_CONTEXT_SEASONS = {"2020-21"}
BENCH_BANDS = (
    ("lean", None, 185.0),
    ("lower_middle", 186.0, 200.0),
    ("upper_middle", 201.0, 220.0),
    ("deep", 221.0, None),
)


def _numeric(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(
        [np.nan if value is None else float(value) for value in table[name].to_pylist()],
        dtype=np.float32,
    )


def _rolling_forecasts(*, refresh: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if FORECASTS.is_file() and not refresh:
        rows = pq.read_table(FORECASTS).to_pylist()
        if {str(row["season"]) for row in rows} == set(TEST_SEASONS):
            return rows, {"reused": True, "path": str(FORECASTS)}

    require_cuda()
    table = pq.read_table(TRAINING_FEATURES)
    matrix = _matrix(table, MODEL_FEATURES)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    target_points = _numeric(table, "target_points")
    target_minutes = _numeric(table, "target_minutes")
    minute_classes = _numeric(table, "minutes_class").astype(np.int32)
    metadata = table.select(
        [
            "season",
            "event_number",
            "element",
            "player_name",
            "position",
            "team_id",
            "market_price",
            "target_points",
            "target_minutes",
        ]
    ).to_pylist()
    season_order = sorted(set(seasons.tolist()))
    predicted_by_index: dict[int, tuple[float, float]] = {}
    fits = []

    for test_season in EARLY_TEST_SEASONS:
        prior = [season for season in season_order if season < test_season]
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        if not training_seasons:
            raise RuntimeError(f"No season-forward training data for {test_season}")
        for position in POSITIONS:
            train = np.isin(seasons, training_seasons) & (positions == position)
            validation = (seasons == validation_season) & (positions == position)
            test = (seasons == test_season) & (positions == position)
            train_played = train & (target_minutes > 0)
            validation_played = validation & (target_minutes > 0)
            if train_played.sum() < 500 or test.sum() < 100:
                raise RuntimeError(
                    f"Insufficient {position} rows for historical fold {test_season}"
                )

            points_model = _regressor(SEEDS[0], 1200, early_stopping=True)
            points_model.fit(
                matrix[train_played],
                target_points[train_played],
                sample_weight=_season_weights(seasons, train_played),
                eval_set=[(matrix[validation_played], target_points[validation_played])],
                verbose=False,
            )
            minutes_model = _classifier(SEEDS[0], 900, early_stopping=True)
            minutes_model.fit(
                matrix[train],
                minute_classes[train],
                sample_weight=_season_weights(seasons, train),
                eval_set=[(matrix[validation], minute_classes[validation])],
                verbose=False,
            )
            probability, _, expected = _predict_hurdle(
                points_model,
                minutes_model,
                matrix[test],
            )
            global_indices = np.flatnonzero(test)
            for index, forecast, p_play in zip(
                global_indices,
                expected,
                probability[:, 1:].sum(axis=1),
                strict=True,
            ):
                predicted_by_index[int(index)] = (float(forecast), float(p_play))
            fits.append(
                {
                    "season": test_season,
                    "position": position,
                    "training_seasons": training_seasons,
                    "validation_season": validation_season,
                    "points_best_iteration": int(points_model.best_iteration),
                    "minutes_best_iteration": int(minutes_model.best_iteration),
                }
            )

    existing = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
        if str(row["season"]) in TEST_SEASONS
    }
    rows = []
    for index, row in enumerate(metadata):
        season = str(row["season"])
        if season not in TEST_SEASONS:
            continue
        key = (season, int(row["event_number"]), int(row["element"]))
        if season in EARLY_TEST_SEASONS:
            prediction = predicted_by_index.get(index)
            if prediction is None:
                continue
            expected_points, p_play = prediction
        else:
            prediction_row = existing.get(key)
            if prediction_row is None:
                continue
            expected_points = float(prediction_row["expected_points"])
            p_play = float(prediction_row["p_play"])
        rows.append(
            {
                **row,
                "expected_points": expected_points,
                "p_play": p_play,
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_table(pa.Table.from_pylist(rows), FORECASTS)
    return rows, {
        "reused": False,
        "path": str(FORECASTS),
        "fits": fits,
    }


def _window_rows(
    rows: list[dict[str, Any]],
    season: str,
    events: tuple[int, ...],
) -> list[dict[str, Any]]:
    season_rows = [row for row in rows if str(row["season"]) == season]
    selected = [
        row
        for row in season_rows
        if int(row["event_number"]) in events
        and row.get("market_price") is not None
        and float(row["market_price"]) > 0.0
    ]
    by_player: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in selected:
        by_player[int(row["element"])][int(row["event_number"])] = row

    season_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in season_rows:
        if row.get("market_price") is not None and float(row["market_price"]) > 0.0:
            season_by_player[int(row["element"])].append(row)

    normalized = []
    first_event = events[0]
    last_event = events[-1]
    for element, history in season_by_player.items():
        player_events = by_player.get(element, {})
        observed_before = [
            row for row in history if int(row["event_number"]) <= first_event
        ]
        observed_during_or_after = [
            row
            for row in history
            if first_event <= int(row["event_number"]) <= last_event
        ]
        if not observed_during_or_after:
            continue
        template = (
            max(observed_before, key=lambda row: int(row["event_number"]))
            if observed_before
            else min(observed_during_or_after, key=lambda row: int(row["event_number"]))
        )
        price = template.get("market_price")
        if price is None or float(price) <= 0.0:
            continue
        for event in events:
            row = player_events.get(event)
            normalized.append(
                {
                    **(row or template),
                    "event_number": event,
                    "market_price": float(price),
                    "expected_points": float(row["expected_points"]) if row else 0.0,
                    "p_play": float(row["p_play"]) if row else 0.0,
                    "target_points": float(row["target_points"]) if row else 0.0,
                    "target_minutes": float(row["target_minutes"]) if row else 0.0,
                }
            )
    return normalized


def _regular_single_fixture_events() -> dict[str, set[int]]:
    table = pq.read_table(
        TRAINING_FEATURES,
        columns=["season", "event_number", "team_id", "fixture_count"],
    )
    teams_by_event: dict[tuple[str, int], dict[int, float]] = defaultdict(dict)
    for row in table.to_pylist():
        key = (str(row["season"]), int(row["event_number"]))
        teams_by_event[key][int(row["team_id"])] = float(row["fixture_count"])
    regular: dict[str, set[int]] = defaultdict(set)
    for (season, event), teams in teams_by_event.items():
        if len(teams) == 20 and all(count == 1.0 for count in teams.values()):
            regular[season].add(event)
    return regular


def _candidate(solution: dict[str, Any], events: tuple[int, ...], label: str) -> dict[str, Any]:
    return {
        "candidate_id": label,
        "selected": list(solution["selected"]),
        "planned_squads": {
            str(event): list(solution["planned_squads"][event]) for event in events
        },
        "lineups": {
            str(event): {
                "starters": list(solution["lineups"][event]["starters"]),
                "bench_order": list(solution["lineups"][event]["bench_order"]),
                "captain": int(solution["lineups"][event]["captain"]),
                "vice_captain": int(solution["lineups"][event]["vice_captain"]),
            }
            for event in events
        },
    }


def _deadline_safe_fixed_squad_policy(
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
    *,
    minimum_bench_spend: float | None,
    maximum_bench_spend: float | None,
    rules: SquadRules,
) -> dict[str, Any]:
    """Pick once at the window origin, then set each lineup at its own deadline.

    Forecast rows for later events contain information observed before those later
    deadlines. They may be used to set the later XI, but never to choose the
    original 15-player squad. This prevents horizon-origin leakage while still
    measuring the realised value of owning substitutes who rotate into the XI.
    """
    first_event = events[0]
    first_event_rows = [
        row for row in rows if int(row["event_number"]) == first_event
    ]
    origin = _solve(
        first_event_rows,
        [first_event],
        bench_autosub_weight=0.0,
        gw1_bench_spend=(minimum_bench_spend, maximum_bench_spend),
        rules=rules,
    )
    selected = set(map(int, origin["selected"]))
    planned_squads: dict[int, list[int]] = {}
    lineups: dict[int, dict[str, Any]] = {}
    deadline_objectives: dict[int, float] = {}
    for event in events:
        if event == first_event:
            deadline_solution = origin
        else:
            event_rows = [
                row for row in rows if int(row["event_number"]) == event
            ]
            deadline_solution = _solve(
                event_rows,
                [event],
                initial_squad=selected,
                bench_autosub_weight=0.0,
                rules=rules,
            )
        planned_squads[event] = list(deadline_solution["planned_squads"][event])
        lineups[event] = dict(deadline_solution["lineups"][event])
        deadline_objectives[event] = float(deadline_solution["objective"])
    return {
        "selected": list(origin["selected"]),
        "planned_squads": planned_squads,
        "lineups": lineups,
        "deadline_objectives": deadline_objectives,
    }


def _score_window(
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
    events: tuple[int, ...],
) -> dict[str, Any]:
    actual = {
        (int(row["event_number"]), int(row["element"])): row for row in rows
    }
    player_ids = sorted({int(row["element"]) for row in rows})
    player_index = {element: index for index, element in enumerate(player_ids)}
    meta = {int(row["element"]): row for row in rows}
    points = np.asarray(
        [
            [
                [round(float(actual[(event, element)]["target_points"])) for element in player_ids]
                for event in events
            ]
        ],
        dtype=np.int16,
    )
    played = np.asarray(
        [
            [
                [float(actual[(event, element)]["target_minutes"]) > 0 for element in player_ids]
                for event in events
            ]
        ],
        dtype=bool,
    )
    scores = _score_candidates(
        [candidate],
        player_ids,
        events,
        points,
        played,
        meta,
    )[0, 0]

    autosub_points = 0
    stranded_points = 0
    for offset, event in enumerate(events):
        squad = [int(element) for element in candidate["planned_squads"][str(event)]]
        pattern = 0
        for squad_index, element in enumerate(squad):
            if played[0, offset, player_index[element]]:
                pattern |= 1 << squad_index
        weights = _autosub_weights(candidate, event, pattern, meta)
        lineup = candidate["lineups"][str(event)]
        starters = {int(element) for element in lineup["starters"]}
        captain = int(lineup["captain"])
        vice = int(lineup["vice_captain"])
        no_sub_weights = np.zeros(len(squad), dtype=np.int8)
        for squad_index, element in enumerate(squad):
            if element in starters and played[0, offset, player_index[element]]:
                no_sub_weights[squad_index] = 1
        if played[0, offset, player_index[captain]]:
            no_sub_weights[squad.index(captain)] += 1
        elif played[0, offset, player_index[vice]]:
            no_sub_weights[squad.index(vice)] += 1
        squad_points = np.asarray(
            [points[0, offset, player_index[element]] for element in squad], dtype=np.int16
        )
        autosub_points += int(np.sum(squad_points * (weights - no_sub_weights)))
        stranded_points += int(
            sum(
                points[0, offset, player_index[element]]
                for element in squad
                if weights[squad.index(element)] == 0
            )
        )

    first_event = events[0]
    first_lineup = candidate["lineups"][str(first_event)]
    first_bench = {int(element) for element in first_lineup["bench_order"]}
    first_prices = {
        int(row["element"]): float(row["market_price"])
        for row in rows
        if int(row["event_number"]) == first_event
    }
    later_rotation_slots = sum(
        element in first_bench
        for event in events[1:]
        for element in map(int, candidate["lineups"][str(event)]["starters"])
    )
    return {
        "actual_points": int(scores.sum()),
        "event_points": [int(value) for value in scores],
        "autosub_points": autosub_points,
        "stranded_bench_points": stranded_points,
        "bench_spend": sum(first_prices[element] for element in first_bench) / 10.0,
        "outfield_bench_spend": sum(
            first_prices[element]
            for element in first_bench
            if meta[element]["position"] != "GK"
        )
        / 10.0,
        "later_rotation_slots": int(later_rotation_slots),
        "unique_gw1_bench_players_started_later": len(
            first_bench
            & {
                int(element)
                for event in events[1:]
                for element in candidate["lineups"][str(event)]["starters"]
            }
        ),
        "gw1_bench": [meta[element]["player_name"] for element in first_bench],
    }


def _paired_summary(
    windows: list[dict[str, Any]],
    challenger: str,
    incumbent: str = "lean",
) -> dict[str, Any]:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in windows:
        grouped[(row["season"], int(row["start_event"]))][row["band"]] = row
    deltas = []
    by_season: dict[str, list[float]] = defaultdict(list)
    for key, bands in grouped.items():
        if challenger not in bands or incumbent not in bands:
            continue
        delta = float(bands[challenger]["actual_points"] - bands[incumbent]["actual_points"])
        deltas.append(delta)
        by_season[key[0]].append(delta)
    values = np.asarray(deltas, dtype=float)
    season_means = np.asarray(
        [np.mean(season_values) for season_values in by_season.values()], dtype=float
    )
    standard_error = (
        float(season_means.std(ddof=1) / math.sqrt(len(season_means)))
        if len(season_means) > 1
        else 0.0
    )
    mean = float(values.mean())
    return {
        "challenger": challenger,
        "incumbent": incumbent,
        "windows": len(values),
        "seasons": len(season_means),
        "mean_delta_per_five_events": mean,
        "median_delta_per_five_events": float(np.median(values)),
        "win_rate": float(np.mean(values > 0.0)),
        "tie_rate": float(np.mean(values == 0.0)),
        "season_clustered_95ci_low": mean - 1.96 * standard_error,
        "season_clustered_95ci_high": mean + 1.96 * standard_error,
        "season_mean_deltas": {
            season: float(np.mean(season_values))
            for season, season_values in sorted(by_season.items())
        },
    }


def _historical_manager_evidence() -> dict[str, Any]:
    from .tournament import _historical_bench_evidence

    return _historical_bench_evidence()


def _render(result: dict[str, Any]) -> str:
    opening = result["opening_windows"]
    rolling = result["rolling_windows"]
    deep = rolling["paired_vs_lean"]["deep"]
    exact = result["exact_manager_evidence"]["gameweeks"][0]
    lines = [
        "# Historical bench-depth audit",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        f"**{result['verdict']}**",
        "",
        (
            "The existing £18.45m benchmark is exact but narrow: it is the GW1 mean for ten "
            "eventual 2019/20 top-ten managers. It is not a multi-season target. The broader "
            "test below asks a different and more actionable question: when the same "
            "season-forward forecast and legal optimiser are forced into each bench-spend band, "
            "which policy subsequently scores most actual points?"
        ),
        "",
        "## Opening five-Gameweek replay",
        "",
        "Each squad is selected at that season's GW1 deadline using only the GW1 forecast. It is held for five events; at each later deadline the XI, bench order, captain and vice are reset using only the forecast available for that event. Actual points, minutes, formation-valid autosubs and captain fallback determine the score. A season is omitted here unless GW1–5 are five ordinary single-fixture rounds with all 20 clubs playing exactly once in each round.",
        "",
        "| Season | Lean ≤£18.5m | £18.6–20m | £20.1–22m | Deep >£22m | Deep − lean | Best band |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for season, bands in opening["by_season"].items():
        lines.append(
            f"| {season} | {bands['lean']['actual_points']} | "
            f"{bands['lower_middle']['actual_points']} | "
            f"{bands['upper_middle']['actual_points']} | {bands['deep']['actual_points']} | "
            f"{bands['deep']['actual_points'] - bands['lean']['actual_points']:+d} | "
            f"{bands['best_band']} |"
        )
    lines.extend(
        [
            "",
            "## Rolling five-event fixed-squad windows",
            "",
            (
                f"Across {deep['windows']} non-overlapping five-event windows in "
                f"{deep['seasons']} seasons, deep benches changed realised points by "
                f"**{deep['mean_delta_per_five_events']:+.2f} per window versus lean** "
                f"(season-clustered 95% interval {deep['season_clustered_95ci_low']:+.2f} to "
                f"{deep['season_clustered_95ci_high']:+.2f}; win rate {deep['win_rate']:.1%})."
            ),
            "",
            "| Band | Mean actual points | Mean bench spend | Mean autosub points | Mean rotation slots | Mean stranded bench points |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for band, row in rolling["by_band"].items():
        lines.append(
            f"| {band} | {row['mean_actual_points']:.2f} | £{row['mean_bench_spend']:.2f}m | "
            f"{row['mean_autosub_points']:.2f} | {row['mean_later_rotation_slots']:.2f} | "
            f"{row['mean_stranded_bench_points']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Exact manager evidence",
            "",
            (
                f"The exact 2019/20 eventual top-ten cohort averaged £{exact['mean_bench_spend']:.2f}m "
                f"on its GW1 bench (range £{exact['minimum_bench_spend']:.1f}m–"
                f"£{exact['maximum_bench_spend']:.1f}m). Exact manager-level bench positions and "
                "purchase prices are not present for every season in the archive, so aggregate "
                "veteran ownership tables are not mislabelled as bench-spend observations."
            ),
            "",
            "## Decision consequence",
            "",
            result["decision_consequence"],
            "",
            "## Method and limitations",
            "",
            "- Forecast folds are strictly season-forward; the test season is never used to train its model.",
            "- The last three folds reuse the frozen production rolling forecasts; earlier folds use the same feature and model contract.",
            "- The primary benchmark contains only five consecutive, ordinary single-fixture rounds. Blanks, doubles and extraordinary disruption are excluded rather than treated as representative of the current horizon.",
            "- The compressed 2020/21 pandemic season is excluded from primary windows even when a particular block happened to contain one fixture per club.",
            "- The 15-player squad is chosen using only the start-event forecast. Later-event forecasts may reset that event's XI, bench order and armband only after their own deadline information becomes available.",
            "- International breaks require no special fixture treatment: no Premier League round is scheduled during the break. Post-break availability uncertainty belongs in the player forecast.",
            "- Each replay is a fixed-squad experiment. It does not claim managers knew future injuries or price changes, and it intentionally gives the initial squad no future-fixture planning advantage.",
            "- Bench spend is constrained, never rewarded in the objective. The optimiser maximises forecast starters and captain with zero proxy credit for unused substitutes.",
            "- The rolling windows increase sample size but remain correlated within seasons; confidence intervals are therefore clustered by season.",
            "- This is policy evidence, not evidence that historical champions themselves used the simulated squads.",
            "",
        ]
    )
    return "\n".join(lines)


def run_historical_bench_depth_audit(*, refresh_forecasts: bool = False) -> dict[str, Any]:
    rows, forecast_receipt = _rolling_forecasts(refresh=refresh_forecasts)
    rules = load_rules()
    window_results = []
    regular_events = _regular_single_fixture_events()
    excluded_windows = []
    for season in TEST_SEASONS:
        for start_event in REGULAR_WINDOW_STARTS:
            events = tuple(range(start_event, start_event + HORIZON))
            if season in EXTRAORDINARY_CONTEXT_SEASONS:
                excluded_windows.append(
                    {
                        "season": season,
                        "start_event": start_event,
                        "events": list(events),
                        "reason": "extraordinary_schedule_context",
                    }
                )
                continue
            if not set(events) <= regular_events.get(season, set()):
                excluded_windows.append(
                    {
                        "season": season,
                        "start_event": start_event,
                        "events": list(events),
                        "reason": "not_five_regular_single_fixture_rounds",
                    }
                )
                continue
            event_rows = _window_rows(rows, season, events)
            if not event_rows:
                continue
            print(
                f"Bench history: solving {season} events {events[0]}-{events[-1]}",
                file=sys.stderr,
                flush=True,
            )
            for label, minimum, maximum in BENCH_BANDS:
                try:
                    solution = _deadline_safe_fixed_squad_policy(
                        event_rows,
                        events,
                        minimum_bench_spend=minimum,
                        maximum_bench_spend=maximum,
                        rules=rules,
                    )
                except RuntimeError as error:
                    raise RuntimeError(
                        f"Historical bench solve failed for {season} events "
                        f"{events[0]}-{events[-1]} band={label}: {error}"
                    ) from error
                candidate = _candidate(solution, events, label)
                scored = _score_window(candidate, event_rows, events)
                window_results.append(
                    {
                        "season": season,
                        "start_event": start_event,
                        "events": list(events),
                        "band": label,
                        **scored,
                    }
                )

    opening_rows = [row for row in window_results if int(row["start_event"]) == 1]
    opening_by_season: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in opening_rows:
        opening_by_season[row["season"]][row["band"]] = row
    for bands in opening_by_season.values():
        bands["best_band"] = max(
            (label for label, _, _ in BENCH_BANDS),
            key=lambda label: bands[label]["actual_points"],
        )

    by_band = {}
    for label, _, _ in BENCH_BANDS:
        band_rows = [row for row in window_results if row["band"] == label]
        by_band[label] = {
            "windows": len(band_rows),
            "mean_actual_points": float(np.mean([row["actual_points"] for row in band_rows])),
            "mean_bench_spend": float(np.mean([row["bench_spend"] for row in band_rows])),
            "mean_autosub_points": float(np.mean([row["autosub_points"] for row in band_rows])),
            "mean_later_rotation_slots": float(
                np.mean([row["later_rotation_slots"] for row in band_rows])
            ),
            "mean_stranded_bench_points": float(
                np.mean([row["stranded_bench_points"] for row in band_rows])
            ),
        }
    paired = {
        label: _paired_summary(window_results, label)
        for label, _, _ in BENCH_BANDS
        if label != "lean"
    }
    deep = paired["deep"]
    opening_deep_deltas = [
        bands["deep"]["actual_points"] - bands["lean"]["actual_points"]
        for bands in opening_by_season.values()
    ]
    supports_deep = (
        deep["mean_delta_per_five_events"] > 0.0
        and deep["season_clustered_95ci_low"] > 0.0
        and np.mean(opening_deep_deltas) > 0.0
    )
    verdict = (
        "DEEP BENCH HISTORICALLY SUPPORTED"
        if supports_deep
        else "DO NOT ASSUME A DEEP BENCH"
    )
    consequence = (
        "The multi-season replay supports retaining the £22m+ structure, subject to a fresh deadline rerun."
        if supports_deep
        else (
            "A £22m+ bench has not cleared the multi-season generalisation gate. The current "
            "£23.0m proposal may still win under 2026/27-specific forecasts, but it must be treated "
            "as a close, season-specific challenger. Production selection should require a positive "
            "paired holdout against the best ≤£20m alternative after the final data refresh; otherwise "
            "promote the leaner squad and move the money into the XI or bank."
        )
    )
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "test_seasons": list(TEST_SEASONS),
        "primary_excluded_seasons": sorted(EXTRAORDINARY_CONTEXT_SEASONS),
        "forecast_receipt": forecast_receipt,
        "forecast_sha256": sha256_file(FORECASTS),
        "information_policy": {
            "forecast": "strict season-forward",
            "selection": (
                "legal fixed squad selected from start-event forecast only; "
                "XI/bench/captain reset from each event's deadline forecast"
            ),
            "bench_objective_weight": 0.0,
            "future_information_used_to_select_initial_squad": False,
        },
        "opening_windows": {
            "by_season": dict(sorted(opening_by_season.items())),
            "deep_minus_lean_mean": float(np.mean(opening_deep_deltas)),
            "deep_minus_lean_median": float(np.median(opening_deep_deltas)),
            "deep_win_rate": float(np.mean(np.asarray(opening_deep_deltas) > 0.0)),
        },
        "rolling_windows": {
            "by_band": by_band,
            "paired_vs_lean": paired,
            "windows": window_results,
            "excluded_windows": excluded_windows,
        },
        "exact_manager_evidence": _historical_manager_evidence(),
        "decision_consequence": consequence,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
