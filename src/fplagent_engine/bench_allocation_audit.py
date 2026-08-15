from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    _blend_scenario_scores,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
    train_goal_model,
)
from .decision_synthesis import (
    RESULTS_JSON as SYNTHESIS_RESULTS,
)
from .decision_synthesis import synthesis_rows
from .horizon_audit import (
    CENTRAL_REGRET_CAP as HORIZON_CENTRAL_REGRET_CAP,
)
from .horizon_audit import (
    CENTRAL_SCENARIO as HORIZON_CENTRAL_SCENARIO,
)
from .horizon_audit import EVENTS as HORIZON_EVENTS
from .horizon_audit import RESULTS_JSON as HORIZON_RESULTS
from .horizon_audit import SCENARIO_WEIGHTS as HORIZON_SCENARIO_WEIGHTS
from .horizon_audit import _candidate_record, _scenario_totals
from .models import CURRENT_FORECAST, require_cuda
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import (
    CENTRAL_REGRET_CAP as ROBUST_CENTRAL_REGRET_CAP,
)
from .robust_search import (
    RESULTS_JSON as ROBUST_RESULTS,
)
from .robust_search import SCENARIO_WEIGHTS as ROBUST_SCENARIO_WEIGHTS
from .robust_search import (
    SELECTION_PARQUET as ROBUST_SELECTION,
)
from .robust_search import (
    SHORTLIST_JSON as ROBUST_SHORTLIST,
)
from .robust_search import _paired_comparison, _policy_variant, _weighted_regret
from .tournament import DEFAULT_EVENTS, _load_rows, _score_candidates

VERSION = "bench_allocation_audit_v2"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "current-season-bench-allocation-audit.md"

# The fresh holdout is a falsification run, not a second opportunity to crown a
# winner on an immaterial Monte Carlo/composite-score difference. This bound is
# derived from the already-declared central regret caps and is substantially
# stricter than either family gate.
PRACTICAL_EQUIVALENCE_REGRET = (
    min(ROBUST_CENTRAL_REGRET_CAP, HORIZON_CENTRAL_REGRET_CAP) / 4.0
)

RECENT_ELITE_CONTEXT = (
    {
        "season": "2019/20",
        "manager": "Joshua Bull",
        "observation": "exact GW1 bench",
        "price": 18.5,
        "source": "local reconstructed eventual-winner picks",
    },
    {
        "season": "2023/24",
        "manager": "Jonas Sand Labakk",
        "observation": "maximum possible GW1 bench from published XI",
        "price": 19.0,
        "source": "https://www.premierleague.com/en/news/4025901",
    },
    {
        "season": "2024/25",
        "manager": "Lovro Budisin",
        "observation": "exact GW1 bench from published squad",
        "price": 19.0,
        "source": (
            "https://www.fantasyfootballscout.co.uk/2025/06/03/"
            "fpl-2024-25-champion-lovro-budisin-speaks-to-ffscout"
        ),
    },
    {
        "season": "2025/26",
        "manager": "Erik Ibsen",
        "observation": "exact GW2 Wildcard bench; GW1 failed",
        "price": 21.0,
        "source": (
            "https://www.premierleague.com/en/news/4671982/"
            "fpl-champion-how-to-build-the-perfect-squad-and-make-the-best-transfers"
        ),
    },
)


def _price(row: dict[str, Any]) -> float:
    return float(row["market_price"]) / 10.0


def bench_profile(
    candidate: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    *,
    events: tuple[int, ...] = DEFAULT_EVENTS,
) -> dict[str, Any]:
    """Separate GW1 role assignment from persistent squad investment."""

    selected = list(map(int, candidate["selected"]))
    first = candidate["lineups"][str(events[0])]
    first_bench = list(map(int, first["bench_order"]))
    future_events = tuple(event for event in events if event != events[0])
    starts_by_player = {
        element: [
            event
            for event in events
            if element in set(map(int, candidate["lineups"][str(event)]["starters"]))
        ]
        for element in selected
    }
    cheapest = sorted(selected, key=lambda element: (_price(meta[element]), element))[:4]
    position_floors: dict[str, float] = {}
    for row in meta.values():
        if not bool(row.get("can_select", True)) or bool(row.get("removed", False)):
            continue
        position = str(row["position"])
        position_floors[position] = min(position_floors.get(position, math.inf), _price(row))

    bench_players = []
    for element in first_bench:
        future_starts = [event for event in starts_by_player[element] if event in future_events]
        position = str(meta[element]["position"])
        price = _price(meta[element])
        bench_players.append(
            {
                "element": element,
                "name": str(meta[element]["player_name"]),
                "position": position,
                "price": price,
                "future_starts": future_starts,
                "future_start_count": len(future_starts),
                "premium_above_position_floor": price - position_floors[position],
            }
        )

    nominal = sum(_price(meta[element]) for element in first_bench)
    four_cheapest = sum(_price(meta[element]) for element in cheapest)
    return {
        "nominal_gw1_bench_spend": nominal,
        "four_cheapest_squad_spend": four_cheapest,
        "gw1_role_assignment_premium": nominal - four_cheapest,
        "four_cheapest_players": [
            {
                "element": element,
                "name": str(meta[element]["player_name"]),
                "position": str(meta[element]["position"]),
                "price": _price(meta[element]),
                "starts": starts_by_player[element],
            }
            for element in cheapest
        ],
        "gw1_bench_players": bench_players,
        "gw1_bench_players_used_later": sum(
            player["future_start_count"] > 0 for player in bench_players
        ),
        "gw1_bench_future_start_events": sum(
            player["future_start_count"] for player in bench_players
        ),
        "squad_players_started": sum(bool(events_) for events_ in starts_by_player.values()),
        "squad_players_never_started": [
            str(meta[element]["player_name"])
            for element, starts in starts_by_player.items()
            if not starts
        ],
        "formations": sorted(
            {str(candidate["lineups"][str(event)]["formation"]) for event in events}
        ),
        "events": list(events),
    }


def _targeted_candidates(
    shortlist: list[dict[str, Any]],
    selection_rows: list[dict[str, Any]],
    synthesis: dict[str, Any],
    robust: dict[str, Any],
    horizon: dict[str, Any],
    *,
    top_historical_band: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_id = {str(candidate["candidate_id"]): candidate for candidate in shortlist}
    metrics = {str(row["candidate_id"]): row for row in selection_rows}
    lean = [candidate for candidate in shortlist if float(candidate["gw1_bench_spend"]) <= 20.0]
    lean_by_mean = sorted(
        lean,
        key=lambda candidate: float(metrics[str(candidate["candidate_id"])]["evidence_mean"]),
        reverse=True,
    )
    lean_by_cvar = sorted(
        lean,
        key=lambda candidate: float(metrics[str(candidate["candidate_id"])]["cvar10"]),
        reverse=True,
    )
    protected_ids = {
        str(synthesis["decision"]["candidate_id"]),
        str(robust["leader"]["candidate_id"]),
        str(horizon["leader"]["candidate_id"]),
    }
    for row in synthesis["ranking"]:
        spend = float(row["gw1_bench_spend"])
        if spend > 22.0:
            protected_ids.add(str(row["candidate_id"]))
            break
    exact_lean = [candidate for candidate in lean if float(candidate["gw1_bench_spend"]) <= 18.5]
    chosen_ids = {
        *(str(candidate["candidate_id"]) for candidate in exact_lean),
        *(str(candidate["candidate_id"]) for candidate in lean_by_mean[:top_historical_band]),
        *(str(candidate["candidate_id"]) for candidate in lean_by_cvar[:8]),
        *protected_ids,
    }
    missing = sorted(chosen_ids - set(by_id))
    if missing:
        raise RuntimeError(f"Targeted bench candidates missing from shortlist: {missing}")
    candidates = [by_id[candidate_id] for candidate_id in sorted(chosen_ids)]
    return candidates, {
        "shortlist_candidates": len(shortlist),
        "shortlist_at_or_below_20": len(lean),
        "all_at_or_below_18_5_protected": len(exact_lean),
        "top_historical_band_by_mean": min(top_historical_band, len(lean_by_mean)),
        "top_historical_band_by_cvar": min(8, len(lean_by_cvar)),
        "protected_control_ids": sorted(protected_ids),
        "targeted_unique_candidates": len(candidates),
    }


def _five_week_holdout(
    candidates: list[dict[str, Any]],
    *,
    simulations: int,
    seed: int,
    stress_goal_multiplier: float,
    raw_weight: float,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, np.ndarray]], dict[int, dict]]:
    rows, loaded = _load_rows(DEFAULT_EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    goal_rates, _ = predict_current_goal_rates(by_player, DEFAULT_EVENTS)
    empirical = calibrate_empirical_components()
    variants = []
    for index, candidate in enumerate(candidates, start=1):
        variants.extend(
            _policy_variant(candidate, rows, kind) for kind in ("fixed", "open", "roll-gw2")
        )
        if index % 8 == 0 or index == len(candidates):
            print(
                f"Bench allocation audit: solved five-week policies for {index}/"
                f"{len(candidates)} candidates",
                flush=True,
            )
    player_ids, raw, anchored, played, _, _ = simulate_component_outcomes(
        by_player,
        DEFAULT_EVENTS,
        goal_rates,
        empirical,
        simulations,
        seed,
    )
    raw_scores = _score_candidates(variants, player_ids, DEFAULT_EVENTS, raw, played, meta)
    anchored_scores = _score_candidates(
        variants, player_ids, DEFAULT_EVENTS, anchored, played, meta
    )
    evidence_scores = _blend_scenario_scores(raw_scores, anchored_scores, raw_weight)
    stress_rates = {
        key: (home * stress_goal_multiplier, away * stress_goal_multiplier)
        for key, (home, away) in goal_rates.items()
    }
    stress_ids, stress_raw, _, stress_played, _, _ = simulate_component_outcomes(
        by_player,
        DEFAULT_EVENTS,
        stress_rates,
        empirical,
        simulations,
        seed + 1,
    )
    stress_scores = _score_candidates(
        variants,
        stress_ids,
        DEFAULT_EVENTS,
        stress_raw,
        stress_played,
        meta,
    )
    variant_index = {
        (str(variant["root_candidate_id"]), str(variant["variant_kind"])): index
        for index, variant in enumerate(variants)
    }
    paths: dict[str, dict[str, np.ndarray]] = {}
    values: dict[str, dict[str, float]] = {}
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        fixed = variant_index[(candidate_id, "fixed")]
        opened = variant_index[(candidate_id, "open")]
        rolled = variant_index[(candidate_id, "roll-gw2")]
        paths[candidate_id] = {
            "base_evidence_open": evidence_scores[:, opened, :].sum(axis=1),
            "base_evidence_roll_gw2": evidence_scores[:, rolled, :].sum(axis=1),
            "base_evidence_fixed": evidence_scores[:, fixed, :].sum(axis=1),
            "base_raw_open": raw_scores[:, opened, :].sum(axis=1),
            "base_anchored_open": anchored_scores[:, opened, :].sum(axis=1),
            "high_goal_open": stress_scores[:, opened, :].sum(axis=1),
            "high_goal_roll_gw2": stress_scores[:, rolled, :].sum(axis=1),
            "high_goal_fixed": stress_scores[:, fixed, :].sum(axis=1),
        }
        values[candidate_id] = {
            name: float(path.mean()) for name, path in paths[candidate_id].items()
        }
    bests = {
        name: max(candidate_values[name] for candidate_values in values.values())
        for name in ROBUST_SCENARIO_WEIGHTS
    }
    candidate_by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    output = []
    for candidate_id, candidate_values in values.items():
        central = paths[candidate_id]["base_evidence_open"]
        output.append(
            {
                "candidate_id": candidate_id,
                "display_name": candidate_by_id[candidate_id]["display_name"],
                "origin_ids": candidate_by_id[candidate_id]["origin_ids"],
                "gw1_formation": candidate_by_id[candidate_id]["gw1_formation"],
                "gw1_bench_spend": candidate_by_id[candidate_id]["gw1_bench_spend"],
                "scenario_values": candidate_values,
                "base_p10": float(np.quantile(central, 0.10)),
                "base_p90": float(np.quantile(central, 0.90)),
                **_weighted_regret(candidate_values, bests),
            }
        )
    output.sort(
        key=lambda row: (
            row["scenario_regrets"]["base_evidence_open"] > ROBUST_CENTRAL_REGRET_CAP,
            row["robust_regret"],
            -row["scenario_values"]["base_evidence_open"],
        )
    )
    return output, paths, meta


def _eight_week_holdout(
    candidates: list[dict[str, Any]],
    *,
    simulations: int,
    seed: int,
    raw_weight: float,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, np.ndarray]]]:
    rows, loaded = _load_rows(HORIZON_EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    horizon_candidates = [
        _candidate_record(
            list(map(int, candidate["selected"])),
            by_player,
            meta,
            list(map(str, candidate["origin_ids"])),
        )
        for candidate in candidates
    ]
    variants = []
    for index, candidate in enumerate(horizon_candidates, start=1):
        variants.extend(
            _policy_variant(candidate, rows, kind, HORIZON_EVENTS)
            for kind in ("fixed", "open", "roll-gw2")
        )
        if index % 8 == 0 or index == len(horizon_candidates):
            print(
                f"Bench allocation audit: solved eight-week policies for {index}/"
                f"{len(horizon_candidates)} candidates",
                flush=True,
            )
    goal_rates, _ = predict_current_goal_rates(by_player, HORIZON_EVENTS)
    empirical = calibrate_empirical_components()
    player_ids, raw, anchored, played, _, _ = simulate_component_outcomes(
        by_player,
        HORIZON_EVENTS,
        goal_rates,
        empirical,
        simulations,
        seed,
    )
    raw_scores = _score_candidates(variants, player_ids, HORIZON_EVENTS, raw, played, meta)
    anchored_scores = _score_candidates(
        variants, player_ids, HORIZON_EVENTS, anchored, played, meta
    )
    evidence_scores = _blend_scenario_scores(raw_scores, anchored_scores, raw_weight)
    variant_index = {
        (str(variant["root_candidate_id"]), str(variant["variant_kind"])): index
        for index, variant in enumerate(variants)
    }
    paths: dict[str, dict[str, np.ndarray]] = {}
    values: dict[str, dict[str, float]] = {}
    for candidate in horizon_candidates:
        candidate_id = str(candidate["candidate_id"])
        scores_by_kind = {
            kind: evidence_scores[:, variant_index[(candidate_id, kind)], :]
            for kind in ("fixed", "open", "roll-gw2")
        }
        paths[candidate_id] = _scenario_totals(scores_by_kind)
        values[candidate_id] = {
            name: float(path.mean()) for name, path in paths[candidate_id].items()
        }
    bests = {
        name: max(candidate_values[name] for candidate_values in values.values())
        for name in HORIZON_SCENARIO_WEIGHTS
    }
    candidate_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in horizon_candidates
    }
    output = []
    for candidate_id, candidate_values in values.items():
        regrets = {
            name: float(bests[name] - candidate_values[name]) for name in HORIZON_SCENARIO_WEIGHTS
        }
        weighted = sum(
            HORIZON_SCENARIO_WEIGHTS[name] * regrets[name] for name in HORIZON_SCENARIO_WEIGHTS
        )
        worst = max(regrets.values())
        central = paths[candidate_id][HORIZON_CENTRAL_SCENARIO]
        candidate = candidate_by_id[candidate_id]
        output.append(
            {
                "candidate_id": candidate_id,
                "display_name": candidate["display_name"],
                "origin_ids": candidate["origin_ids"],
                "gw1_formation": candidate["gw1_formation"],
                "gw1_bench_spend": candidate["gw1_bench_spend"],
                "scenario_values": candidate_values,
                "scenario_regrets": regrets,
                "weighted_mean_regret": weighted,
                "worst_scenario_regret": worst,
                "robust_regret": 0.80 * weighted + 0.20 * worst,
                "central_p10": float(np.quantile(central, 0.10)),
                "central_p90": float(np.quantile(central, 0.90)),
            }
        )
    output.sort(
        key=lambda row: (
            row["scenario_regrets"][HORIZON_CENTRAL_SCENARIO] > HORIZON_CENTRAL_REGRET_CAP,
            row["robust_regret"],
            -row["scenario_values"][HORIZON_CENTRAL_SCENARIO],
        )
    )
    return output, paths


def _comparison(
    current_id: str,
    challenger_id: str,
    five_paths: dict[str, dict[str, np.ndarray]],
    eight_paths: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name in ROBUST_SCENARIO_WEIGHTS:
        output[name] = _paired_comparison(
            five_paths[current_id][name], five_paths[challenger_id][name]
        )
    for name in HORIZON_SCENARIO_WEIGHTS:
        output[name] = _paired_comparison(
            eight_paths[current_id][name], eight_paths[challenger_id][name]
        )
    return output


def _candidate_difference(
    current: dict[str, Any],
    challenger: dict[str, Any],
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    current_ids = set(map(int, current["selected"]))
    challenger_ids = set(map(int, challenger["selected"]))

    def named(elements: set[int]) -> list[dict[str, Any]]:
        return [
            {
                "element": element,
                "name": str(meta[element]["player_name"]),
                "position": str(meta[element]["position"]),
                "price": _price(meta[element]),
            }
            for element in sorted(elements)
        ]

    return {
        "shared_players": len(current_ids & challenger_ids),
        "current_only": named(current_ids - challenger_ids),
        "challenger_only": named(challenger_ids - current_ids),
    }


def targeted_retention_assessment(
    active: dict[str, Any],
    targeted_winner: dict[str, Any],
    *,
    active_won_original_selector: bool,
    equivalence_regret: float = PRACTICAL_EQUIVALENCE_REGRET,
) -> dict[str, Any]:
    """Decide whether a fresh holdout materially falsifies the active squad."""

    active_id = str(active["candidate_id"])
    winner_id = str(targeted_winner["candidate_id"])
    exact_winner = active_id == winner_id
    regret_gap = max(
        0.0,
        float(active["synthesis_regret"]) - float(targeted_winner["synthesis_regret"]),
    )
    active_worst = float(active["family_worst_regret"])
    winner_worst = float(targeted_winner["family_worst_regret"])
    practically_equivalent = bool(
        not exact_winner
        and active_won_original_selector
        and regret_gap <= equivalence_regret
        and active_worst <= winner_worst
    )
    survives = exact_winner or practically_equivalent
    if exact_winner:
        status = "exact_fresh_holdout_winner"
    elif practically_equivalent:
        status = "practically_equivalent_lower_worst_family_regret"
    else:
        status = "materially_falsified"
    return {
        "status": status,
        "survives": survives,
        "exact_fresh_holdout_winner": exact_winner,
        "practically_equivalent": practically_equivalent,
        "active_won_original_selector": active_won_original_selector,
        "active_synthesis_regret": float(active["synthesis_regret"]),
        "targeted_winner_synthesis_regret": float(targeted_winner["synthesis_regret"]),
        "active_minus_winner_regret": regret_gap,
        "practical_equivalence_regret": equivalence_regret,
        "active_family_worst_regret": active_worst,
        "targeted_winner_family_worst_regret": winner_worst,
    }


def _render_report(result: dict[str, Any]) -> str:
    current = result["current"]
    profile = current["profile"]
    challenger = result["best_historical_band_challenger"]
    comparison = result["current_minus_historical_band"]
    verdict = result["verdict"]
    retention = result["targeted_retention"]
    targeted = result["targeted_winner"]
    lines = [
        "# Current-season bench allocation audit",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Verdict:** {verdict['status']}  ",
        f"**Active decision:** {current['candidate_id']} · {current['display_name']}",
        "",
        "## Answer",
        "",
        verdict["explanation"],
        "",
        (
            f"The visible GW1 bench costs **£{profile['nominal_gw1_bench_spend']:.1f}m**, "
            f"but the four cheapest players in the 15 cost **£{profile['four_cheapest_squad_spend']:.1f}m**. "
            f"The remaining £{profile['gw1_role_assignment_premium']:.1f}m is caused by which "
            "owned players happen to sit out GW1, not by extra persistent reserve investment."
        ),
        "",
        (
            f"Of the four GW1 substitutes, **{profile['gw1_bench_players_used_later']}/4** "
            f"are planned to start later and they supply **{profile['gw1_bench_future_start_events']}** "
            "planned starts across GW2–5."
        ),
        "",
        "## Fresh-selector stability",
        "",
        (
            f"The fresh targeted winner was **{targeted['candidate_id']}** · "
            f"{targeted['display_name']}; the active squad ranked "
            f"**{current['targeted_rank']}**. The active-minus-winner composite-regret gap was "
            f"**{retention['active_minus_winner_regret']:+.3f} points**, against a predeclared "
            f"practical-equivalence bound of {retention['practical_equivalence_regret']:.3f}."
        ),
        "",
        (
            f"The active squad's worst family regret was "
            f"**{retention['active_family_worst_regret']:.3f}**, versus "
            f"**{retention['targeted_winner_family_worst_regret']:.3f}** for the fresh winner. "
            f"Classification: **{retention['status']}**. Equivalence can retain an original "
            "selector winner only when its fresh deficit is immaterial and its worst-family "
            "result is no worse; it cannot rescue a dominated squad."
        ),
        "",
        "## What the GW1 bench becomes",
        "",
        "| Player | Price | Planned starts after GW1 | Premium above position floor |",
        "|---|---:|---|---:|",
    ]
    for player in profile["gw1_bench_players"]:
        starts = ", ".join(f"GW{event}" for event in player["future_starts"]) or "None"
        lines.append(
            f"| {player['name']} | £{player['price']:.1f}m | {starts} | "
            f"£{player['premium_above_position_floor']:.1f}m |"
        )
    lines.extend(
        [
            "",
            "## Matched historical-band challenge",
            "",
            (
                f"The targeted holdout sent **{result['coverage']['targeted_unique_candidates']}** "
                "candidates through fresh five- and eight-week simulations, including "
                f"{result['coverage']['all_at_or_below_18_5_protected']} candidates at or below "
                "£18.5m and the strongest selection-screen candidates up to £20m."
            ),
            "",
            (
                f"The best ≤£20m challenger is **{challenger['candidate_id']}** · "
                f"{challenger['display_name']}. It shares "
                f"**{result['candidate_difference']['shared_players']}/15 players** with the "
                "active decision."
            ),
            "",
            "| Scenario | Active minus ≤£20m | 95% interval |",
            "|---|---:|---:|",
        ]
    )
    scenarios = (
        "base_evidence_open",
        "base_raw_open",
        "high_goal_open",
        "gw1_3_open_d088",
        "gw1_5_open_d088",
        "gw1_8_open_d088",
        "gw6_8_open_equal",
        "gw1_8_fixed_d088",
    )
    for name in scenarios:
        row = comparison[name]
        lines.append(
            f"| {name.replace('_', ' ')} | {row['mean_delta']:+.2f} | "
            f"{row['delta_95ci_low']:+.2f} to {row['delta_95ci_high']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Why the preferred spend changes",
            "",
            (
                "The cross-family result is not monotonic proof that more bench money is better. "
                "The preferred nominal bench rises as more trust is placed in today's long-horizon "
                "rotation forecast:"
            ),
            "",
            "| Horizon-family weight | Winner | Nominal GW1 bench |",
            "|---:|---|---:|",
        ]
    )
    for interval in result["horizon_weight_champion_intervals"]:
        lines.append(
            f"| {interval['lower']:.1%}–{interval['upper']:.1%} | "
            f"{interval['candidate_id']} | £{interval['gw1_bench_spend']:.1f}m |"
        )
    lines.extend(
        [
            "",
            "## Recent elite context",
            "",
            "| Season | Manager | Observation | Price |",
            "|---|---|---|---:|",
        ]
    )
    for row in result["recent_elite_context"]:
        lines.append(
            f"| {row['season']} | {row['manager']} | {row['observation']} | £{row['price']:.1f}m |"
        )
    lines.extend(
        [
            "",
            (
                "This context is descriptive and survivorship-selected. It supplies a prior, not "
                "a causal target. The four-cheapest-spend metric is also not identical to an "
                "observed GW1 bench; it is used because it is invariant to a one-week formation "
                "choice."
            ),
            "",
            "## Production gate",
            "",
            "| Check | Result |",
            "|---|---|",
        ]
    )
    for check, passed in verdict["checks"].items():
        lines.append(f"| {check.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            verdict["decision_rule"],
            "",
            "## Limitations",
            "",
            "- The same forecast family helps select and score candidates; paired holdouts remove Monte Carlo noise, not shared model bias.",
            "- The high-goal run is an adversarial sensitivity test, not an alternative calibrated forecast.",
            "- Planned rotations are valuable only if deadline availability and role forecasts remain current.",
            "- This audit tests the strongest available targeted lean field; it does not mathematically enumerate every legal 15-player squad.",
            "",
            (
                "Machine receipt: `data/model/bench_allocation_audit_v2/results.json`. "
                "Active decision: `data/model/gw1_decision_synthesis_v1/results.json`."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def run_bench_allocation_audit(
    *,
    simulations: int = 25_000,
    five_week_seed: int = 20260818,
    eight_week_seed: int = 20260820,
    top_historical_band: int = 24,
    stress_goal_multiplier: float = 1.15,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if simulations < 5_000:
        raise ValueError("bench allocation audit needs at least 5,000 holdout worlds")
    if top_historical_band < 8:
        raise ValueError("protect at least eight historical-band candidates")
    if five_week_seed == eight_week_seed:
        raise ValueError("five- and eight-week seeds must be distinct")
    if stress_goal_multiplier <= 1.0:
        raise ValueError("stress_goal_multiplier must be greater than one")
    ensure_engine_layout()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    synthesis = load_json_artifact(SYNTHESIS_RESULTS, "GW1 decision synthesis")
    robust = load_json_artifact(ROBUST_RESULTS, "global robust-search results")
    horizon = load_json_artifact(HORIZON_RESULTS, "horizon-audit results")
    shortlist_payload = load_json_artifact(ROBUST_SHORTLIST, "global robust shortlist")
    require_current_forecast(
        robust,
        CURRENT_FORECAST,
        "global robust-search results",
        fields=("artifacts", "forecast_sha256"),
    )
    require_current_forecast(
        horizon,
        CURRENT_FORECAST,
        "horizon-audit results",
        fields=("artifacts", "forecast_sha256"),
    )
    require_current_forecast(shortlist_payload, CURRENT_FORECAST, "global robust shortlist")
    require_recorded_file(
        synthesis,
        ("source_artifacts", "robust_results_sha256"),
        ROBUST_RESULTS,
        "decision synthesis robust input",
    )
    require_recorded_file(
        synthesis,
        ("source_artifacts", "horizon_results_sha256"),
        HORIZON_RESULTS,
        "decision synthesis horizon input",
    )
    require_recorded_file(
        synthesis,
        ("source_artifacts", "robust_shortlist_sha256"),
        ROBUST_SHORTLIST,
        "decision synthesis shortlist input",
    )
    require_recorded_file(
        horizon,
        ("artifacts", "robust_results_sha256"),
        ROBUST_RESULTS,
        "horizon-audit robust input",
    )

    selection_rows = pq.read_table(ROBUST_SELECTION).to_pylist()
    candidates, coverage = _targeted_candidates(
        shortlist_payload["candidates"],
        selection_rows,
        synthesis,
        robust,
        horizon,
        top_historical_band=top_historical_band,
    )
    candidate_by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    current_id = str(synthesis["decision"]["candidate_id"])
    if current_id not in candidate_by_id:
        raise RuntimeError("Active synthesized decision is missing from the targeted field")

    require_cuda()
    train_goal_model(force=False, seed=five_week_seed)
    backtest = load_json_artifact(COMPONENT_BACKTEST_METRICS, "component backtest metrics")
    raw_weight = float(backtest["blend_selection"]["selected_raw_weight"])
    print(
        f"Bench allocation audit: evaluating {len(candidates)} targeted candidates in "
        f"{simulations:,} fresh worlds",
        flush=True,
    )
    five_rows, five_paths, meta = _five_week_holdout(
        candidates,
        simulations=simulations,
        seed=five_week_seed,
        stress_goal_multiplier=stress_goal_multiplier,
        raw_weight=raw_weight,
    )
    eight_rows, eight_paths = _eight_week_holdout(
        candidates,
        simulations=simulations,
        seed=eight_week_seed,
        raw_weight=raw_weight,
    )
    ranking = synthesis_rows(
        five_rows,
        eight_rows,
        horizon_family_weight=float(synthesis["method"]["horizon_family_weight"]),
        family_worst_weight=float(synthesis["method"]["family_worst_weight"]),
    )
    targeted_winner_id = str(ranking[0]["candidate_id"])
    ranking_by_id = {str(row["candidate_id"]): row for row in ranking}
    original_synthesis_rank = next(
        int(row["rank"])
        for row in synthesis["ranking"]
        if str(row["candidate_id"]) == current_id
    )
    retention = targeted_retention_assessment(
        ranking_by_id[current_id],
        ranking_by_id[targeted_winner_id],
        active_won_original_selector=original_synthesis_rank == 1,
    )
    historical_band_rows = [row for row in ranking if float(row["gw1_bench_spend"]) <= 20.0]
    if not historical_band_rows:
        raise RuntimeError("Targeted field contains no candidate at or below £20m")
    challenger_id = str(historical_band_rows[0]["candidate_id"])
    comparison = _comparison(current_id, challenger_id, five_paths, eight_paths)
    profile = bench_profile(candidate_by_id[current_id], meta)
    challenger_profile = bench_profile(candidate_by_id[challenger_id], meta)

    interval_by_id = {
        str(row["candidate_id"]): row for row in synthesis["horizon_weight_champion_intervals"]
    }
    intervals = []
    shortlist_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in shortlist_payload["candidates"]
    }
    for row in synthesis["horizon_weight_champion_intervals"]:
        candidate_id = str(row["candidate_id"])
        intervals.append(
            {
                **row,
                "gw1_bench_spend": float(shortlist_by_id[candidate_id]["gw1_bench_spend"]),
            }
        )
    active_interval = interval_by_id.get(current_id)
    weight_stable = bool(
        active_interval
        and float(active_interval["lower"]) <= 0.5 <= float(active_interval["upper"])
        and float(active_interval["upper"]) - float(active_interval["lower"]) >= 0.20
    )
    checks = {
        "artifact_lineage_current": True,
        "active_decision_not_materially_falsified": bool(retention["survives"]),
        "four_cheapest_spend_within_recent_18_5_to_21_reference": (
            18.5 <= float(profile["four_cheapest_squad_spend"]) <= 21.0
        ),
        "at_least_two_gw1_substitutes_rotate_later": (
            int(profile["gw1_bench_players_used_later"]) >= 2
        ),
        "at_least_four_planned_future_starts_from_gw1_bench": (
            int(profile["gw1_bench_future_start_events"]) >= 4
        ),
        "balanced_family_weight_is_in_stable_champion_interval": weight_stable,
        "at_least_24_targeted_historical_band_candidates": (
            int(coverage["targeted_unique_candidates"]) >= 24
        ),
    }
    promotable = all(checks.values())
    if promotable:
        status = "SUPPORTED_AS_ROTATION_SQUAD_NOT_AS_A_DEEP_BENCH_RULE"
        explanation = (
            "The active squad survives the expanded targeted holdout, but the evidence supports "
            "a rotation structure rather than a general instruction to buy a high-priced bench. "
            "Its persistent four-cheapest allocation is inside the recent elite reference band, "
            "and most of its visible GW1 bench is scheduled to enter the XI."
        )
    else:
        status = "NOT_PROVEN_RETAIN_AS_CHALLENGER_ONLY"
        failed = ", ".join(
            check.replace("_", " ") for check, passed in checks.items() if not passed
        )
        explanation = (
            "The active squad has not cleared the falsification gate. The following checks failed: "
            f"{failed}. It must not be defended merely because the optimiser produced it."
        )
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": {
            "status": status,
            "promotable": promotable,
            "checks": checks,
            "explanation": explanation,
            "decision_rule": (
                "Publish the active squad only while this receipt remains checksum-current. If "
                "availability, price, role, fixture or forecast evidence changes, rebuild both "
                "audit families, regenerate the synthesis, and rerun this targeted gate. A high "
                "nominal GW1 bench price is never itself a positive feature."
            ),
        },
        "current": {
            "candidate_id": current_id,
            "display_name": candidate_by_id[current_id]["display_name"],
            "targeted_rank": next(
                int(row["rank"]) for row in ranking if row["candidate_id"] == current_id
            ),
            "profile": profile,
        },
        "targeted_winner": next(
            row for row in ranking if row["candidate_id"] == targeted_winner_id
        ),
        "targeted_retention": retention,
        "best_historical_band_challenger": {
            **next(row for row in ranking if row["candidate_id"] == challenger_id),
            "profile": challenger_profile,
        },
        "current_minus_historical_band": comparison,
        "candidate_difference": _candidate_difference(
            candidate_by_id[current_id], candidate_by_id[challenger_id], meta
        ),
        "targeted_ranking": ranking,
        "five_week_metrics": five_rows,
        "eight_week_metrics": eight_rows,
        "coverage": coverage,
        "horizon_weight_champion_intervals": intervals,
        "recent_elite_context": list(RECENT_ELITE_CONTEXT),
        "method": {
            "simulations_per_family": simulations,
            "five_week_seed": five_week_seed,
            "eight_week_seed": eight_week_seed,
            "stress_goal_multiplier": stress_goal_multiplier,
            "evidence_raw_weight": raw_weight,
            "selection": (
                "All shortlist candidates at or below £18.5m, the top historical-band candidates "
                "by the existing selection screen, the top eight by downside CVaR, and the active "
                "five-week/eight-week/synthesis controls."
            ),
        },
        "lineage": {
            "forecast_sha256": sha256_file(CURRENT_FORECAST),
            "synthesis_sha256": sha256_file(SYNTHESIS_RESULTS),
            "robust_results_sha256": sha256_file(ROBUST_RESULTS),
            "horizon_results_sha256": sha256_file(HORIZON_RESULTS),
            "robust_shortlist_sha256": sha256_file(ROBUST_SHORTLIST),
            "robust_selection_sha256": sha256_file(ROBUST_SELECTION),
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_report(result), encoding="utf-8")
    print(
        f"Bench allocation audit: complete; {status}; targeted winner {targeted_winner_id}",
        flush=True,
    )
    return result
