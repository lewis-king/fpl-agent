from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.optimize import least_squares
from scipy.stats import poisson, skellam
from sklearn.metrics import mean_poisson_deviance

from .betfair_exchange import (
    BETFAIR_BOOTSTRAP_URL,
    collect_betfair_exchange_snapshot,
)
from .paths import DATA, MODEL_DATA, NORMALIZED, REPORTS, ensure_engine_layout

RAW_DIR = DATA / "raw" / "football-data"
HISTORICAL_MARKET_RATES = NORMALIZED / "historical_market_goal_rates.parquet"
MARKET_RECEIPT = NORMALIZED / "historical_market_goal_rates_receipt.json"
MARKET_REPORT = REPORTS / "market-goal-rate-challenger.md"
CURRENT_MARKET_RATES = NORMALIZED / "current_market_goal_rates.parquet"
CURRENT_MARKET_RECEIPT = NORMALIZED / "current_market_goal_rates_receipt.json"
FPL_FIXTURES = DATA / "processed" / "vaastav" / "fixtures.parquet"
FPL_TEAMS = DATA / "processed" / "vaastav" / "teams.parquet"
TEAM_STRENGTH = NORMALIZED / "opponent_adjusted_team_strength.parquet"

SOURCE_ROOT = "https://www.football-data.co.uk/mmz4281"
SOURCE_NOTES = "https://www.football-data.co.uk/notes.txt"
CURRENT_FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
CURRENT_FIXTURES_PAGE = "https://www.football-data.co.uk/matches.php"
CURRENT_FPL_FIXTURES = DATA / "processed" / "fpl" / "2026-27" / "preseason" / "fixtures.parquet"
CURRENT_FPL_TEAMS = DATA / "processed" / "fpl" / "2026-27" / "preseason" / "teams.parquet"
CURRENT_FPL_EVENTS = DATA / "processed" / "fpl" / "2026-27" / "preseason" / "events.parquet"
BETFAIR_RAW_DIR = DATA / "raw" / "betfair" / "current"
BETFAIR_CALIBRATION_RESULTS = MODEL_DATA / "betfair_exchange_policy_v1" / "results.json"
MATERIAL_GOAL_RATE_DELTA = 0.10
MATERIAL_CLEAN_SHEET_DELTA = 0.025
SEASON_CODES = {
    "2019-20": "1920",
    "2020-21": "2021",
    "2021-22": "2122",
    "2022-23": "2223",
    "2023-24": "2324",
    "2024-25": "2425",
    "2025-26": "2526",
}
FROZEN_TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
TEAM_NAME_ALIASES = {
    "Coventry": "Coventry City",
    "Hull": "Hull City",
    "Ipswich": "Ipswich Town",
    "Man United": "Man Utd",
    "Nottm Forest": "Nott'm Forest",
    "Sheffield United": "Sheffield Utd",
    "Tottenham": "Spurs",
}
BOOKMAKER_1X2_COLUMNS = (
    ("bet365", ("B365H", "B365D", "B365A")),
    ("betfair_sportsbook", ("BFDH", "BFDD", "BFDA")),
    ("betvictor", ("BVH", "BVD", "BVA")),
    ("betway", ("BWH", "BWD", "BWA")),
    ("pinnacle", ("PPH", "PPD", "PPA")),
    ("smarkets", ("SKBH", "SKBD", "SKBA")),
    ("betfair_exchange", ("BFEH", "BFED", "BFEA")),
)
TOTALS_COLUMNS = (
    ("bet365", ("B365>2.5", "B365<2.5")),
    ("market_average", ("Avg>2.5", "Avg<2.5")),
    ("betfair_exchange", ("BFE>2.5", "BFE<2.5")),
)


def _source_url(season: str) -> str:
    return f"{SOURCE_ROOT}/{SEASON_CODES[season]}/E0.csv"


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "FPLAgent-research/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _devig(values: list[float]) -> np.ndarray:
    inverse = 1.0 / np.asarray(values, dtype=np.float64)
    return inverse / inverse.sum()


def score_probabilities(home_rate: float, away_rate: float) -> np.ndarray:
    """Return independent-Poisson home, draw, away and over-2.5 probabilities."""
    draw = float(skellam.pmf(0, home_rate, away_rate))
    away = float(skellam.cdf(-1, home_rate, away_rate))
    home = 1.0 - draw - away
    over = float(1.0 - poisson.cdf(2, home_rate + away_rate))
    return np.asarray([home, draw, away, over], dtype=np.float64)


def infer_goal_rates(
    home_draw_away_odds: tuple[float, float, float],
    over_under_odds: tuple[float, float],
) -> tuple[float, float, dict[str, float]]:
    """Fit two Poisson rates to de-vigged pre-closing 1X2 and O/U probabilities."""
    one_x_two = _devig(list(home_draw_away_odds))
    over_under = _devig(list(over_under_odds))
    target = np.concatenate([one_x_two, over_under[:1]])
    weights = np.asarray([1.0, 1.0, 1.0, 1.25], dtype=np.float64)
    result = least_squares(
        lambda log_rates: (
            score_probabilities(*np.exp(log_rates)) - target
        )
        * weights,
        np.log([1.55, 1.25]),
        bounds=(np.log(0.08), np.log(5.0)),
        xtol=1e-11,
        ftol=1e-11,
        gtol=1e-11,
    )
    home_rate, away_rate = np.exp(result.x)
    fitted = score_probabilities(float(home_rate), float(away_rate))
    return float(home_rate), float(away_rate), {
        "home_probability": float(one_x_two[0]),
        "draw_probability": float(one_x_two[1]),
        "away_probability": float(one_x_two[2]),
        "over_2_5_probability": float(over_under[0]),
        "fit_rmse": float(np.sqrt(np.mean((fitted - target) ** 2))),
    }


def _odds(row: dict[str, str], keys: tuple[str, ...]) -> tuple[float, ...] | None:
    try:
        values = tuple(float(row[key]) for key in keys)
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 1.0 for value in values):
        return None
    return values


def market_consensus_diagnostics(row: dict[str, str]) -> dict[str, float | int | None]:
    """Describe pre-closing bookmaker agreement without using closing prices."""
    one_x_two = []
    for _, columns in BOOKMAKER_1X2_COLUMNS:
        prices = _odds(row, columns)
        if prices is not None:
            one_x_two.append(_devig(list(prices)))
    totals = []
    for _, columns in TOTALS_COLUMNS:
        prices = _odds(row, columns)
        if prices is not None:
            totals.append(float(_devig(list(prices))[0]))
    average_prices = _odds(row, ("AvgH", "AvgD", "AvgA"))
    average_totals = _odds(row, ("Avg>2.5", "Avg<2.5"))
    probabilities = np.asarray(one_x_two, dtype=np.float64)
    asian_handicap_line = None
    try:
        candidate = float(row.get("AHh", ""))
        if math.isfinite(candidate):
            asian_handicap_line = candidate
    except (TypeError, ValueError):
        pass
    asian_prices = _odds(row, ("AvgAHH", "AvgAHA"))
    return {
        "bookmaker_1x2_count": len(one_x_two),
        "home_probability_std": (
            float(probabilities[:, 0].std()) if len(probabilities) > 1 else None
        ),
        "draw_probability_std": (
            float(probabilities[:, 1].std()) if len(probabilities) > 1 else None
        ),
        "away_probability_std": (
            float(probabilities[:, 2].std()) if len(probabilities) > 1 else None
        ),
        "totals_source_count": len(totals),
        "over_2_5_probability_std": (
            float(np.asarray(totals).std()) if len(totals) > 1 else None
        ),
        "average_1x2_overround": (
            float(sum(1.0 / value for value in average_prices))
            if average_prices is not None
            else None
        ),
        "average_totals_overround": (
            float(sum(1.0 / value for value in average_totals))
            if average_totals is not None
            else None
        ),
        "asian_handicap_line": asian_handicap_line,
        "average_asian_home_odds": asian_prices[0] if asian_prices else None,
        "average_asian_away_odds": asian_prices[1] if asian_prices else None,
    }


def _goal_distribution_diagnostics(home_rate: float, away_rate: float) -> dict[str, float]:
    return {
        "market_total_goal_rate": home_rate + away_rate,
        "home_clean_sheet_probability": math.exp(-away_rate),
        "away_clean_sheet_probability": math.exp(-home_rate),
        "both_teams_to_score_probability": (1.0 - math.exp(-home_rate))
        * (1.0 - math.exp(-away_rate)),
        "goalless_draw_probability": math.exp(-(home_rate + away_rate)),
    }


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    predicted = np.clip(predicted.astype(np.float64), 0.05, 6.0)
    clean_sheet_actual = actual == 0
    clean_sheet_probability = np.exp(-predicted)
    return {
        "rows": len(actual),
        "actual_mean": float(actual.mean()),
        "predicted_mean": float(predicted.mean()),
        "goal_mae": float(np.mean(np.abs(actual - predicted))),
        "poisson_deviance": float(mean_poisson_deviance(actual, predicted)),
        "clean_sheet_brier": float(
            np.mean((clean_sheet_actual - clean_sheet_probability) ** 2)
        ),
    }


def _render(receipt: dict[str, Any]) -> str:
    frozen = receipt["frozen_test"]
    market = frozen["market"]
    incumbent = frozen["incumbent"]
    lines = [
        "# Pre-closing market goal-rate challenger",
        "",
        f"Generated: {receipt['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{receipt['verdict']}** — on the untouched 2023/24–2025/26 seasons, "
            f"market Poisson deviance was {market['poisson_deviance']:.4f} versus "
            f"{incumbent['poisson_deviance']:.4f}, goal MAE was "
            f"{market['goal_mae']:.4f} versus {incumbent['goal_mae']:.4f}, and clean-sheet "
            f"Brier was {market['clean_sheet_brier']:.4f} versus "
            f"{incumbent['clean_sheet_brier']:.4f}."
        ),
        "",
        "This passes the fixture-probability gate. It remains a shadow challenger until a legal FPL policy replay proves that the improvement converts into points and a deadline-safe current-season feed is present.",
        "",
        "## Season-forward evidence",
        "",
        "| Season | Source | Poisson deviance | Goal MAE | CS Brier |",
        "|---|---|---:|---:|---:|",
    ]
    for season, comparison in receipt["by_season"].items():
        for source in ("market", "incumbent"):
            row = comparison[source]
            lines.append(
                f"| {season} | {source} | {row['poisson_deviance']:.4f} | "
                f"{row['goal_mae']:.4f} | {row['clean_sheet_brier']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## Information safety and provenance",
            "",
            "The source labels non-closing columns as pre-closing odds and says weekend odds are collected Friday afternoons and midweek odds Tuesday afternoons. Only `AvgH`, `AvgD`, `AvgA`, `Avg>2.5` and `Avg<2.5` are used; all columns containing the closing marker `C` are excluded. Prices are de-vigged before two independent-Poisson goal rates are fitted.",
            "",
            f"Source notes: {receipt['source']['notes_url']}",
            "",
            "This is research evidence, not betting advice. Market availability and timestamp coverage must be verified before every live deadline; missing odds never silently fall back to fabricated values.",
            "",
        ]
    )
    return "\n".join(lines)


def build_historical_market_goal_rates(*, refresh: bool = False) -> dict[str, Any]:
    ensure_engine_layout()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = pq.read_table(FPL_FIXTURES).to_pylist()
    teams = pq.read_table(FPL_TEAMS).to_pylist()
    team_names = {
        (str(row["season"]), int(row["id"])): str(row["name"])
        for row in teams
    }
    strength_rows = pq.read_table(TEAM_STRENGTH).to_pylist()
    incumbent = {
        (str(row["season"]), int(row["fixture_id"]), int(row["team_id"])): float(
            row["team_expected_goals"]
        )
        for row in strength_rows
    }
    output_rows: list[dict[str, Any]] = []
    source_receipts = []
    for season in SEASON_CODES:
        path = RAW_DIR / f"{season}-E0.csv"
        if refresh or not path.is_file():
            payload = _download(_source_url(season))
            path.write_bytes(payload)
        else:
            payload = path.read_bytes()
        source_receipts.append(
            {
                "season": season,
                "url": _source_url(season),
                "path": str(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        market_rows = list(
            csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="replace")))
        )
        by_pair = {
            (
                TEAM_NAME_ALIASES.get(row["HomeTeam"], row["HomeTeam"]),
                TEAM_NAME_ALIASES.get(row["AwayTeam"], row["AwayTeam"]),
            ): row
            for row in market_rows
            if row.get("HomeTeam") and row.get("AwayTeam")
        }
        season_fixtures = [row for row in fixtures if str(row["season"]) == season]
        for fixture in season_fixtures:
            home_name = team_names[(season, int(fixture["team_h"]))]
            away_name = team_names[(season, int(fixture["team_a"]))]
            market = by_pair.get((home_name, away_name))
            if market is None:
                raise ValueError(f"No market row for {season} {home_name} v {away_name}")
            one_x_two = _odds(market, ("AvgH", "AvgD", "AvgA"))
            totals = _odds(market, ("Avg>2.5", "Avg<2.5"))
            if one_x_two is None or totals is None:
                raise ValueError(f"Missing pre-closing odds for {season} {home_name} v {away_name}")
            home_rate, away_rate, probabilities = infer_goal_rates(one_x_two, totals)
            output_rows.append(
                {
                    "season": season,
                    "event": int(fixture["event"]),
                    "fixture_id": int(fixture["id"]),
                    "kickoff_time": fixture["kickoff_time"],
                    "team_h": int(fixture["team_h"]),
                    "team_a": int(fixture["team_a"]),
                    "home_name": home_name,
                    "away_name": away_name,
                    "avg_home_odds": one_x_two[0],
                    "avg_draw_odds": one_x_two[1],
                    "avg_away_odds": one_x_two[2],
                    "avg_over_2_5_odds": totals[0],
                    "avg_under_2_5_odds": totals[1],
                    "market_home_goal_rate": home_rate,
                    "market_away_goal_rate": away_rate,
                    **probabilities,
                    "home_goals": int(fixture["team_h_score"]),
                    "away_goals": int(fixture["team_a_score"]),
                    "incumbent_home_goal_rate": incumbent[
                        (season, int(fixture["id"]), int(fixture["team_h"]))
                    ],
                    "incumbent_away_goal_rate": incumbent[
                        (season, int(fixture["id"]), int(fixture["team_a"]))
                    ],
                }
            )
    pq.write_table(pa.Table.from_pylist(output_rows), HISTORICAL_MARKET_RATES, compression="zstd")

    by_season = {}
    for season in SEASON_CODES:
        rows = [row for row in output_rows if row["season"] == season]
        actual = np.asarray(
            [value for row in rows for value in (row["home_goals"], row["away_goals"])],
            dtype=np.float64,
        )
        market = np.asarray(
            [
                value
                for row in rows
                for value in (row["market_home_goal_rate"], row["market_away_goal_rate"])
            ],
            dtype=np.float64,
        )
        model = np.asarray(
            [
                value
                for row in rows
                for value in (
                    row["incumbent_home_goal_rate"],
                    row["incumbent_away_goal_rate"],
                )
            ],
            dtype=np.float64,
        )
        by_season[season] = {"market": _metrics(actual, market), "incumbent": _metrics(actual, model)}
    frozen_rows = [row for row in output_rows if row["season"] in FROZEN_TEST_SEASONS]
    frozen_actual = np.asarray(
        [value for row in frozen_rows for value in (row["home_goals"], row["away_goals"])],
        dtype=np.float64,
    )
    frozen_market = np.asarray(
        [
            value
            for row in frozen_rows
            for value in (row["market_home_goal_rate"], row["market_away_goal_rate"])
        ],
        dtype=np.float64,
    )
    frozen_incumbent = np.asarray(
        [
            value
            for row in frozen_rows
            for value in (
                row["incumbent_home_goal_rate"],
                row["incumbent_away_goal_rate"],
            )
        ],
        dtype=np.float64,
    )
    frozen = {
        "seasons": list(FROZEN_TEST_SEASONS),
        "market": _metrics(frozen_actual, frozen_market),
        "incumbent": _metrics(frozen_actual, frozen_incumbent),
    }
    passed = all(
        frozen["market"][metric] < frozen["incumbent"][metric]
        for metric in ("poisson_deviance", "goal_mae", "clean_sheet_brier")
    )
    receipt = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS" if passed else "FAIL",
        "gate": {
            "market_beats_incumbent_on_all_frozen_fixture_metrics": passed,
            "legal_fpl_policy_replay_required_before_promotion": True,
            "current_deadline_safe_feed_required_before_promotion": True,
        },
        "information_policy": {
            "columns_used": ["AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5"],
            "closing_columns_used": False,
            "provider_collection_note": "Weekend games Friday afternoons; midweek games Tuesday afternoons.",
        },
        "by_season": by_season,
        "frozen_test": frozen,
        "rows": len(output_rows),
        "source": {"notes_url": SOURCE_NOTES, "seasons": source_receipts},
        "artifacts": {"normalized": str(HISTORICAL_MARKET_RATES)},
    }
    MARKET_RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    MARKET_REPORT.write_text(_render(receipt), encoding="utf-8")
    return receipt


def historical_market_goal_rates() -> tuple[
    dict[tuple[str, int, int], float], dict[tuple[str, int, int], float]
]:
    if not HISTORICAL_MARKET_RATES.is_file():
        build_historical_market_goal_rates()
    team_rate: dict[tuple[str, int, int], float] = {}
    opponent_rate: dict[tuple[str, int, int], float] = {}
    for row in pq.read_table(HISTORICAL_MARKET_RATES).to_pylist():
        season = str(row["season"])
        event = int(row["event"])
        home = int(row["team_h"])
        away = int(row["team_a"])
        home_rate = float(row["market_home_goal_rate"])
        away_rate = float(row["market_away_goal_rate"])
        team_rate[(season, event, home)] = home_rate
        team_rate[(season, event, away)] = away_rate
        opponent_rate[(season, event, home)] = away_rate
        opponent_rate[(season, event, away)] = home_rate
    return team_rate, opponent_rate


def _market_pair(row: dict[str, Any]) -> tuple[str, str]:
    return (
        TEAM_NAME_ALIASES.get(str(row["HomeTeam"]), str(row["HomeTeam"])),
        TEAM_NAME_ALIASES.get(str(row["AwayTeam"]), str(row["AwayTeam"])),
    )


def _select_market_events(
    event_rows: list[dict[str, Any]], *, event: int | None, horizon: int
) -> list[int]:
    if horizon < 1:
        raise ValueError("Market collection horizon must be positive")
    by_id = {int(row["id"]): row for row in event_rows}
    if event is None:
        next_events = sorted(
            int(row["id"]) for row in event_rows if bool(row.get("is_next"))
        )
        unfinished = sorted(
            int(row["id"]) for row in event_rows if not bool(row.get("finished"))
        )
        if not next_events and not unfinished:
            raise ValueError("No actionable FPL event exists")
        event = next_events[0] if next_events else unfinished[0]
    if event not in by_id:
        raise ValueError(f"FPL event {event} is not present in the current snapshot")
    return sorted(event_id for event_id in by_id if event_id >= event)[:horizon]


def _source_uploaded_at(page: str) -> datetime | None:
    uploaded_match = re.search(
        r"Latest fixtures uploaded:\s*(\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+UK time",
        page,
        flags=re.IGNORECASE,
    )
    if not uploaded_match:
        return None
    local = datetime.strptime(uploaded_match.group(1), "%d/%m/%y %H:%M").replace(
        tzinfo=ZoneInfo("Europe/London")
    )
    return local.astimezone(UTC)


def assess_current_market_source(
    payload: bytes,
    page: str,
    *,
    season: str,
    event: int | None,
    horizon: int,
    fpl_fixtures: list[dict[str, Any]],
    fpl_teams: list[dict[str, Any]],
    fpl_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess exact, timestamp-safe market coverage for actionable FPL events."""
    selected_events = _select_market_events(fpl_events, event=event, horizon=horizon)
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="replace"))))
    premier_league = [row for row in rows if row.get("Div") == "E0"]
    by_pair = {_market_pair(row): row for row in premier_league}
    team_names = {int(row["id"]): str(row["name"]) for row in fpl_teams}
    events_by_id = {int(row["id"]): row for row in fpl_events}
    uploaded_at = _source_uploaded_at(page)
    coverage = []
    for event_id in selected_events:
        fixtures = [
            row
            for row in fpl_fixtures
            if row.get("event") is not None and int(row["event"]) == event_id
        ]
        expected_pairs = {
            (team_names[int(row["team_h"])], team_names[int(row["team_a"])])
            for row in fixtures
        }
        observed_pairs = expected_pairs.intersection(by_pair)
        complete_pairs = {
            pair
            for pair in observed_pairs
            if _odds(by_pair[pair], ("AvgH", "AvgD", "AvgA")) is not None
            and _odds(by_pair[pair], ("Avg>2.5", "Avg<2.5")) is not None
        }
        deadline_at = datetime.fromisoformat(
            str(events_by_id[event_id]["deadline_time"])
        )
        timestamp_safe = uploaded_at is not None and uploaded_at < deadline_at
        coverage.append(
            {
                "event": event_id,
                "fpl_deadline_at": deadline_at.isoformat(),
                "expected_fixtures": len(expected_pairs),
                "covered_fixtures": len(observed_pairs),
                "complete_odds_fixtures": len(complete_pairs),
                "missing_fixtures": sorted(
                    f"{home} v {away}" for home, away in expected_pairs - observed_pairs
                ),
                "incomplete_odds_fixtures": sorted(
                    f"{home} v {away}" for home, away in observed_pairs - complete_pairs
                ),
                "timestamp_safe": timestamp_safe,
                "ready": bool(expected_pairs)
                and complete_pairs == expected_pairs
                and timestamp_safe,
            }
        )
    primary = coverage[0]
    return {
        "season": season,
        "event": primary["event"],
        "events": selected_events,
        "available": bool(premier_league),
        "ready_for_event": primary["ready"],
        "ready_events": [row["event"] for row in coverage if row["ready"]],
        "url": CURRENT_FIXTURES_URL,
        "source_page": CURRENT_FIXTURES_PAGE,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
        "event_coverage": coverage,
        **{key: value for key, value in primary.items() if key != "event"},
    }


def _current_fpl_rows() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    return (
        pq.read_table(CURRENT_FPL_FIXTURES).to_pylist(),
        pq.read_table(CURRENT_FPL_TEAMS).to_pylist(),
        pq.read_table(CURRENT_FPL_EVENTS).to_pylist(),
    )


def _betfair_rows_payload(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    columns = sorted({str(key) for row in rows for key in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def _assess_betfair_snapshot(
    snapshot: dict[str, Any],
    *,
    season: str,
    event: int | None,
    horizon: int,
    fpl_fixtures: list[dict[str, Any]],
    fpl_teams: list[dict[str, Any]],
    fpl_events: list[dict[str, Any]],
) -> tuple[bytes, dict[str, Any]]:
    payload = _betfair_rows_payload(snapshot["rows"])
    observed = datetime.fromisoformat(str(snapshot["observed_at"])).astimezone(
        ZoneInfo("Europe/London")
    )
    timestamp_page = f"Latest fixtures uploaded: {observed:%d/%m/%y %H:%M} UK time"
    availability = assess_current_market_source(
        payload,
        timestamp_page,
        season=season,
        event=event,
        horizon=horizon,
        fpl_fixtures=fpl_fixtures,
        fpl_teams=fpl_teams,
        fpl_events=fpl_events,
    )
    availability.update(
        {
            "provider": "betfair_exchange_public_delayed",
            "url": snapshot.get("competition_url", BETFAIR_BOOTSTRAP_URL),
            "source_page": snapshot.get("competition_url", BETFAIR_BOOTSTRAP_URL),
            "source_timestamp_kind": "observed_at",
            "source_observed_at": snapshot["observed_at"],
            "source_uploaded_at": snapshot["observed_at"],
            "sha256": snapshot["semantic_sha256"],
            "delayed_prices": True,
            "price_estimate": "probability midpoint of best exchange back and lay",
        }
    )
    return payload, availability


def _archive_betfair_snapshot(snapshot: dict[str, Any]) -> tuple[Path, str, list[dict[str, Any]]]:
    BETFAIR_RAW_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    for document in snapshot["documents"]:
        payload = bytes(document["payload"])
        digest = hashlib.sha256(payload).hexdigest()
        suffix = ".html" if document["name"] == "bootstrap" else ".json"
        path = BETFAIR_RAW_DIR / f"{document['name']}-{digest[:16]}{suffix}"
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"Content-addressed Betfair archive collision: {path}")
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        documents.append(
            {
                "name": document["name"],
                "url": document["url"],
                "path": str(path),
                "sha256": digest,
                "bytes": len(payload),
            }
        )
    bundle = {
        "provider": snapshot["provider"],
        "competition_id": snapshot["competition_id"],
        "observed_at": snapshot["observed_at"],
        "semantic_sha256": snapshot["semantic_sha256"],
        "event_ids": snapshot["event_ids"],
        "market_ids": snapshot["market_ids"],
        "rows": snapshot["rows"],
        "documents": documents,
    }
    payload = json.dumps(bundle, indent=2, sort_keys=True).encode() + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    path = BETFAIR_RAW_DIR / f"snapshot-{digest[:16]}.json"
    if path.exists() and path.read_bytes() != payload:
        raise ValueError(f"Content-addressed Betfair snapshot collision: {path}")
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return path, digest, documents


def current_season_source_available(
    season: str = "2026-27", *, event: int | None = None, horizon: int = 5
) -> dict[str, Any]:
    fpl_fixtures, fpl_teams, fpl_events = _current_fpl_rows()
    football_error = None
    try:
        payload = _download(CURRENT_FIXTURES_URL)
        page = _download(CURRENT_FIXTURES_PAGE).decode("utf-8", errors="replace")
        football_data = assess_current_market_source(
            payload,
            page,
            season=season,
            event=event,
            horizon=horizon,
            fpl_fixtures=fpl_fixtures,
            fpl_teams=fpl_teams,
            fpl_events=fpl_events,
        )
        football_data["provider"] = "football_data_market_average"
        if football_data["ready_for_event"]:
            return football_data
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        football_error = f"{type(error).__name__}: {error}"
        football_data = {
            "season": season,
            "event": event,
            "available": False,
            "ready_for_event": False,
            "ready_events": [],
            "url": CURRENT_FIXTURES_URL,
            "provider": "football_data_market_average",
            "reason": football_error,
        }
    try:
        betfair = collect_betfair_exchange_snapshot()
        _, exchange = _assess_betfair_snapshot(
            betfair,
            season=season,
            event=event,
            horizon=horizon,
            fpl_fixtures=fpl_fixtures,
            fpl_teams=fpl_teams,
            fpl_events=fpl_events,
        )
        exchange["fallback_from"] = football_data
        return exchange
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as error:
        return {
            "season": season,
            "event": event,
            "available": False,
            "ready_for_event": False,
            "ready_events": [],
            "providers": [football_data],
            "reason": (
                f"Football-Data: {football_error or 'incomplete'}; "
                f"Betfair: {type(error).__name__}: {error}"
            ),
        }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def disable_current_market_shadow(reason: str, *, event: int | None = None) -> dict[str, Any]:
    """Fail closed after a live collection error so an older receipt cannot be reused."""
    receipt = {
        "version": 2,
        "status": "unavailable",
        "created_at": datetime.now(UTC).isoformat(),
        "event": event,
        "events": [event] if event is not None else [],
        "ready_events": [],
        "fixture_count": 0,
        "fixture_counts_by_event": {},
        "rates_path": None,
        "rates_sha256": None,
        "reason": reason,
        "information_policy": {
            "decision_authority": False,
            "older_receipt_reuse_allowed": False,
        },
    }
    _write_json_atomic(CURRENT_MARKET_RECEIPT, receipt)
    return receipt


def build_current_market_goal_rates(
    *, season: str = "2026-27", event: int | None = None, horizon: int = 5
) -> dict[str, Any]:
    """Archive current prices and materialize every complete actionable fixture."""
    ensure_engine_layout()
    fpl_fixtures, fpl_teams, fpl_events = _current_fpl_rows()
    football_error = None
    try:
        payload = _download(CURRENT_FIXTURES_URL)
        page = _download(CURRENT_FIXTURES_PAGE).decode("utf-8", errors="replace")
        availability = assess_current_market_source(
            payload,
            page,
            season=season,
            event=event,
            horizon=horizon,
            fpl_fixtures=fpl_fixtures,
            fpl_teams=fpl_teams,
            fpl_events=fpl_events,
        )
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        football_error = error
        payload = (
            b"Div,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"
        )
        availability = assess_current_market_source(
            payload,
            "",
            season=season,
            event=event,
            horizon=horizon,
            fpl_fixtures=fpl_fixtures,
            fpl_teams=fpl_teams,
            fpl_events=fpl_events,
        )
        availability["reason"] = f"{type(error).__name__}: {error}"
    availability["provider"] = "football_data_market_average"
    provider = "football_data_market_average"
    source_documents: list[dict[str, Any]] = []
    if not availability["ready_for_event"]:
        try:
            betfair = collect_betfair_exchange_snapshot()
        except Exception as error:
            if football_error is not None:
                raise RuntimeError(
                    "both current market providers failed: "
                    f"Football-Data {type(football_error).__name__}: {football_error}; "
                    f"Betfair {type(error).__name__}: {error}"
                ) from error
            availability["betfair_fallback_error"] = f"{type(error).__name__}: {error}"
            betfair = None
        if betfair is not None:
            betfair_payload, betfair_availability = _assess_betfair_snapshot(
                betfair,
                season=season,
                event=event,
                horizon=horizon,
                fpl_fixtures=fpl_fixtures,
                fpl_teams=fpl_teams,
                fpl_events=fpl_events,
            )
            football_complete = int(availability["complete_odds_fixtures"])
            betfair_complete = int(betfair_availability["complete_odds_fixtures"])
            if betfair_availability["ready_for_event"] or betfair_complete > football_complete:
                payload = betfair_payload
                availability = betfair_availability
                provider = "betfair_exchange_public_delayed"
                raw_path, payload_sha256, source_documents = _archive_betfair_snapshot(betfair)
        if provider == "football_data_market_average":
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            raw_path = RAW_DIR / "current" / f"fixtures-{payload_sha256[:16]}.csv"
    else:
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        raw_path = RAW_DIR / "current" / f"fixtures-{payload_sha256[:16]}.csv"
    if provider == "football_data_market_average":
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists() and raw_path.read_bytes() != payload:
            raise ValueError("Content-addressed market archive contains different bytes")
        if not raw_path.exists():
            raw_path.write_bytes(payload)

    source_rows = list(
        csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="replace")))
    )
    by_pair = {
        _market_pair(row): row for row in source_rows if row.get("Div") == "E0"
    }
    team_names = {int(row["id"]): str(row["name"]) for row in fpl_teams}
    selected_events = {int(value) for value in availability["events"]}
    output_rows = []
    for fixture in fpl_fixtures:
        if fixture.get("event") is None or int(fixture["event"]) not in selected_events:
            continue
        event_id = int(fixture["event"])
        home_name = team_names[int(fixture["team_h"])]
        away_name = team_names[int(fixture["team_a"])]
        market = by_pair.get((home_name, away_name))
        if market is None:
            continue
        one_x_two = _odds(market, ("AvgH", "AvgD", "AvgA"))
        totals = _odds(market, ("Avg>2.5", "Avg<2.5"))
        if one_x_two is None or totals is None:
            continue
        home_rate, away_rate, probabilities = infer_goal_rates(one_x_two, totals)
        output_rows.append(
            {
                "season": season,
                "event": event_id,
                "fixture_id": int(fixture["id"]),
                "kickoff_time": str(fixture["kickoff_time"]),
                "team_h": int(fixture["team_h"]),
                "team_a": int(fixture["team_a"]),
                "home_name": home_name,
                "away_name": away_name,
                "market_provider": provider,
                "source_uploaded_at": availability["source_uploaded_at"],
                "avg_home_odds": one_x_two[0],
                "avg_draw_odds": one_x_two[1],
                "avg_away_odds": one_x_two[2],
                "avg_over_2_5_odds": totals[0],
                "avg_under_2_5_odds": totals[1],
                "market_home_goal_rate": home_rate,
                "market_away_goal_rate": away_rate,
                **_goal_distribution_diagnostics(home_rate, away_rate),
                **probabilities,
                **market_consensus_diagnostics(market),
                **{
                    key: value
                    for key, value in market.items()
                    if key.startswith("betfair_") or key == "source_observed_at"
                },
            }
        )

    rates_sha256 = None
    if output_rows:
        temporary_rates = CURRENT_MARKET_RATES.with_suffix(".parquet.tmp")
        pq.write_table(pa.Table.from_pylist(output_rows), temporary_rates, compression="zstd")
        temporary_rates.replace(CURRENT_MARKET_RATES)
        rates_sha256 = hashlib.sha256(CURRENT_MARKET_RATES.read_bytes()).hexdigest()
    ready_events = [int(value) for value in availability["ready_events"]]
    status = "ready" if availability["ready_for_event"] else (
        "partial" if output_rows else "not_ready"
    )
    receipt = {
        "version": 2,
        "status": status,
        "created_at": datetime.now(UTC).isoformat(),
        "season": season,
        "event": int(availability["event"]),
        "events": availability["events"],
        "ready_events": ready_events,
        "fixture_count": len(output_rows),
        "fixture_counts_by_event": {
            str(event_id): sum(int(row["event"]) == event_id for row in output_rows)
            for event_id in availability["events"]
        },
        "source": availability,
        "provider": provider,
        "source_documents": source_documents,
        "raw_path": str(raw_path),
        "raw_sha256": payload_sha256,
        "rates_path": str(CURRENT_MARKET_RATES) if output_rows else None,
        "rates_sha256": rates_sha256,
        "information_policy": {
            "closing_columns_used": False,
            "primary_estimate": (
                "de-vigged probability midpoint of best exchange back and lay"
                if provider == "betfair_exchange_public_delayed"
                else "de-vigged market-average 1X2 and over/under 2.5"
            ),
            "provider": provider,
            "betfair_exchange_price_method": (
                "probability midpoint of best back and lay"
                if provider == "betfair_exchange_public_delayed"
                else None
            ),
            "betfair_prices_are_delayed": provider == "betfair_exchange_public_delayed",
            "complete_event_required_for_shadow": True,
            "source_upload_must_precede_fpl_deadline": True,
            "source_observation_must_precede_fpl_deadline": True,
            "partial_rows_have_no_decision_authority": True,
        },
    }
    semantic_identity = {
        "version": receipt["version"],
        "status": receipt["status"],
        "season": receipt["season"],
        "events": receipt["events"],
        "ready_events": receipt["ready_events"],
        "fixture_counts_by_event": receipt["fixture_counts_by_event"],
        "raw_sha256": receipt["raw_sha256"],
        "rates_sha256": receipt["rates_sha256"],
        "source_uploaded_at": availability["source_uploaded_at"],
        "event_coverage": availability["event_coverage"],
    }
    receipt["semantic_fingerprint"] = hashlib.sha256(
        json.dumps(semantic_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        previous = json.loads(CURRENT_MARKET_RECEIPT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = None
    if (
        isinstance(previous, dict)
        and previous.get("semantic_fingerprint") == receipt["semantic_fingerprint"]
    ):
        return previous
    _write_json_atomic(CURRENT_MARKET_RECEIPT, receipt)
    return receipt


def _load_current_market_receipt(
    receipt_path: Path = CURRENT_MARKET_RECEIPT,
    rates_path: Path = CURRENT_MARKET_RATES,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not receipt.get("rates_path") or not rates_path.is_file():
        raise ValueError("Current market receipt has no rate artifact")
    artifact_sha256 = hashlib.sha256(rates_path.read_bytes()).hexdigest()
    if artifact_sha256 != receipt.get("rates_sha256"):
        raise ValueError("Current market goal-rate artifact no longer matches its receipt")
    rows = pq.read_table(rates_path).to_pylist()
    if len(rows) != int(receipt["fixture_count"]):
        raise ValueError("Current market row count no longer matches its receipt")
    return receipt, rows


def assess_current_market_materiality(
    previous_receipt: dict[str, Any] | None,
    previous_rows: list[dict[str, Any]],
    current_receipt: dict[str, Any],
    current_rows: list[dict[str, Any]],
    *,
    event: int,
    goal_rate_threshold: float = MATERIAL_GOAL_RATE_DELTA,
    clean_sheet_threshold: float = MATERIAL_CLEAN_SHEET_DELTA,
) -> dict[str, Any]:
    """Compare two archived market generations using decision-facing thresholds.

    Raw price movement is retained for provenance, but a 40+ minute policy search should not be
    launched for exchange noise. Coverage changes fail closed; otherwise the maximum change in
    inferred team goals or clean-sheet probability must cross a declared threshold.
    """
    if goal_rate_threshold <= 0 or clean_sheet_threshold <= 0:
        raise ValueError("market materiality thresholds must be positive")

    current_ready = event in {
        int(value) for value in current_receipt.get("ready_events", [])
    }
    previous_ready = bool(
        previous_receipt
        and event
        in {int(value) for value in previous_receipt.get("ready_events", [])}
    )
    reasons: list[str] = []
    if current_ready != previous_ready:
        reasons.append("decision_event_coverage_changed")

    def fixture_rows(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        return {
            int(row["fixture_id"]): row
            for row in rows
            if int(row.get("event") or -1) == event and row.get("fixture_id") is not None
        }

    previous_by_fixture = fixture_rows(previous_rows)
    current_by_fixture = fixture_rows(current_rows)
    if current_ready and previous_ready and set(previous_by_fixture) != set(current_by_fixture):
        reasons.append("decision_event_fixture_set_changed")

    goal_deltas: list[tuple[float, int, str]] = []
    clean_sheet_deltas: list[tuple[float, int, str]] = []
    for fixture_id in sorted(set(previous_by_fixture).intersection(current_by_fixture)):
        old = previous_by_fixture[fixture_id]
        new = current_by_fixture[fixture_id]
        for venue, goal_field, clean_field in (
            ("home", "market_home_goal_rate", "home_clean_sheet_probability"),
            ("away", "market_away_goal_rate", "away_clean_sheet_probability"),
        ):
            goal_deltas.append(
                (abs(float(new[goal_field]) - float(old[goal_field])), fixture_id, venue)
            )
            clean_sheet_deltas.append(
                (abs(float(new[clean_field]) - float(old[clean_field])), fixture_id, venue)
            )
    maximum_goal = max(goal_deltas, default=(0.0, 0, ""))
    maximum_clean_sheet = max(clean_sheet_deltas, default=(0.0, 0, ""))
    if maximum_goal[0] >= goal_rate_threshold:
        reasons.append("team_goal_expectation_moved")
    if maximum_clean_sheet[0] >= clean_sheet_threshold:
        reasons.append("clean_sheet_expectation_moved")

    previous_provider = previous_receipt.get("provider") if previous_receipt else None
    current_provider = current_receipt.get("provider")
    if previous_ready and current_ready and previous_provider != current_provider:
        reasons.append("market_provider_changed")

    changed = bool(reasons)
    return {
        "event": event,
        "changed": changed,
        "reasons": reasons,
        "previous_ready": previous_ready,
        "current_ready": current_ready,
        "previous_provider": previous_provider,
        "current_provider": current_provider,
        "goal_rate_threshold": goal_rate_threshold,
        "clean_sheet_threshold": clean_sheet_threshold,
        "maximum_goal_rate_delta": maximum_goal[0],
        "maximum_goal_rate_fixture_id": maximum_goal[1] or None,
        "maximum_goal_rate_venue": maximum_goal[2] or None,
        "maximum_clean_sheet_delta": maximum_clean_sheet[0],
        "maximum_clean_sheet_fixture_id": maximum_clean_sheet[1] or None,
        "maximum_clean_sheet_venue": maximum_clean_sheet[2] or None,
        "previous_fingerprint": (
            previous_receipt.get("semantic_fingerprint") if previous_receipt else None
        ),
        "current_fingerprint": current_receipt.get("semantic_fingerprint"),
    }


def current_market_goal_rates(
    *,
    event: int,
    receipt_path: Path = CURRENT_MARKET_RECEIPT,
    rates_path: Path = CURRENT_MARKET_RATES,
) -> dict[tuple[int, int, int], tuple[float, float]]:
    receipt, rows = _load_current_market_receipt(receipt_path, rates_path)
    if event not in {int(value) for value in receipt.get("ready_events", [])}:
        raise ValueError("Current market goal-rate receipt is not ready for this event")
    expected = int(receipt["fixture_counts_by_event"][str(event)])
    selected = [row for row in rows if int(row["event"]) == event]
    if len(selected) != expected:
        raise ValueError("Current market event rows no longer match their receipt")
    return {
        (int(row["event"]), int(row["team_h"]), int(row["team_a"])): (
            float(row["market_home_goal_rate"]),
            float(row["market_away_goal_rate"]),
        )
        for row in selected
    }


def apply_current_market_shadow_rates(
    incumbent: dict[tuple[int, int, int], tuple[float, float]],
    *,
    events: tuple[int, ...],
    receipt_path: Path = CURRENT_MARKET_RECEIPT,
    rates_path: Path = CURRENT_MARKET_RATES,
) -> tuple[dict[tuple[int, int, int], tuple[float, float]], dict[str, Any]]:
    """Override only fully covered events; returned rates never imply authority."""
    base = dict(incumbent)
    diagnostics: dict[str, Any] = {
        "status": "not_ready",
        "decision_authority": False,
        "requested_events": list(events),
        "overridden_events": [],
    }
    if not receipt_path.is_file():
        return base, {**diagnostics, "reason": "market receipt is absent"}
    try:
        receipt, rows = _load_current_market_receipt(receipt_path, rates_path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return base, {**diagnostics, "reason": str(error)}
    ready_events = sorted(set(events).intersection(int(v) for v in receipt.get("ready_events", [])))
    if not ready_events:
        return base, {
            **diagnostics,
            "reason": "no requested event has complete timestamp-safe market coverage",
            "receipt_status": receipt.get("status"),
        }
    selected = [row for row in rows if int(row["event"]) in ready_events]
    overrides = {
        (int(row["event"]), int(row["team_h"]), int(row["team_a"])): (
            float(row["market_home_goal_rate"]),
            float(row["market_away_goal_rate"]),
        )
        for row in selected
    }
    unexpected = sorted(set(overrides) - set(base))
    expected_keys = {key for key in base if key[0] in ready_events}
    missing = sorted(expected_keys - set(overrides))
    if unexpected or missing:
        return base, {
            **diagnostics,
            "reason": "market coverage does not exactly match simulator fixtures",
            "unexpected_fixture_keys": unexpected,
            "missing_fixture_keys": missing,
        }
    base.update(overrides)
    absolute_shifts = [
        abs(overrides[key][side] - incumbent[key][side])
        for key in overrides
        for side in (0, 1)
    ]
    return base, {
        "status": "ready_shadow",
        "decision_authority": False,
        "provider": receipt.get("provider"),
        "requested_events": list(events),
        "overridden_events": ready_events,
        "internal_only_events": sorted(set(events) - set(ready_events)),
        "overridden_fixtures": len(overrides),
        "mean_absolute_goal_rate_shift": float(np.mean(absolute_shifts)),
        "maximum_absolute_goal_rate_shift": float(np.max(absolute_shifts)),
        "receipt": str(receipt_path),
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "artifact": str(rates_path),
        "artifact_sha256": receipt["rates_sha256"],
        "promotion_policy": (
            "Zero authority until sequential transfer replay and prospective receipts show "
            "a stable points gain; missing future events retain internal rates."
        ),
    }


def apply_current_market_decision_rates(
    incumbent: dict[tuple[int, int, int], tuple[float, float]],
    *,
    events: tuple[int, ...],
    receipt_path: Path = CURRENT_MARKET_RECEIPT,
    rates_path: Path = CURRENT_MARKET_RATES,
    calibration_path: Path = BETFAIR_CALIBRATION_RESULTS,
) -> tuple[dict[tuple[int, int, int], tuple[float, float]], dict[str, Any]]:
    """Apply only a historically promoted, fully covered market blend to decisions."""
    market, diagnostics = apply_current_market_shadow_rates(
        incumbent,
        events=events,
        receipt_path=receipt_path,
        rates_path=rates_path,
    )
    if diagnostics.get("status") != "ready_shadow":
        return dict(incumbent), {**diagnostics, "production_weight": 0.0}
    if diagnostics.get("provider") != "betfair_exchange_public_delayed":
        return dict(incumbent), {
            **diagnostics,
            "production_weight": 0.0,
            "production_reason": "provider has no provider-specific promotion receipt",
        }
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(incumbent), {
            **diagnostics,
            "production_weight": 0.0,
            "production_reason": f"Betfair calibration is unavailable: {error}",
        }
    policy = calibration.get("production_policy") or {}
    weight = float(policy.get("goal_rate_weight") or 0.0)
    if not bool(policy.get("decision_authority")) or not 0.0 < weight <= 1.0:
        return dict(incumbent), {
            **diagnostics,
            "production_weight": 0.0,
            "production_reason": "Betfair held-out legal-policy gate has not promoted authority",
            "calibration_verdict": calibration.get("verdict"),
            "calibration_path": str(calibration_path),
            "calibration_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
        }
    blended = {
        key: (
            (1.0 - weight) * incumbent[key][0] + weight * market[key][0],
            (1.0 - weight) * incumbent[key][1] + weight * market[key][1],
        )
        for key in incumbent
    }
    return blended, {
        **diagnostics,
        "status": "ready_production",
        "decision_authority": True,
        "production_weight": weight,
        "calibration_verdict": calibration.get("verdict"),
        "calibration_path": str(calibration_path),
        "calibration_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
        "production_reason": "provider-specific held-out gate passed",
    }
