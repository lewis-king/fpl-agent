from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from itertools import combinations, permutations, product
from pathlib import Path
from typing import Any

import numpy as np

from fplagent_data.http import sha256_file

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)
from .component_models import CURRENT_COMPONENT_FORECAST
from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
)
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .decision_synthesis import REPORT as SYNTHESIZED_REPORT
from .decision_synthesis import RESULTS_JSON as SYNTHESIZED_RESULTS
from .decision_synthesis import _named_squad
from .decision_synthesis import _render_report as _render_synthesis_report
from .horizon_audit import RESULTS_JSON as HORIZON_RESULTS
from .models import CURRENT_FORECAST
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .robust_search import RESULTS_JSON as ROBUST_RESULTS
from .rules import SquadRules, load_rules, validate_lineup
from .tournament import (
    _load_rows,
    _score_candidates,
    _simulate_player_outcomes,
    calibrate_residuals,
)

VERSION = "current_squad_adversarial_v2"
RESULT_DIR = MODEL_DATA / VERSION
RESULTS_JSON = RESULT_DIR / "results.json"
REPORT = REPORTS / "current-squad-xi-captain-bench-audit.md"
EVENT = 1
MINIMUM_HOLDOUT_ROBUST_GAIN = 0.01
# With 25,000 worlds per independent sample, a hard 0.010 boundary proved brittle for an
# otherwise identical one-player starter/bench decision (observed cross-sample gap: 0.010776).
# Keep this deliberately narrow: both leaders must still be top-three, agree on the selected 15,
# captain and vice, and differ by exactly one starter/bench exchange.
PRACTICAL_CONFIGURATION_REGRET = 0.0125
PRACTICAL_CONFIGURATION_MAX_RANK = 3


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def enumerate_legal_xis(
    selected: list[int],
    meta: dict[int, dict[str, Any]],
    rules: SquadRules | None = None,
) -> list[tuple[int, ...]]:
    """Enumerate every legal starting XI for one valid 15-player squad."""
    rules = rules or load_rules()
    by_position = {
        position: sorted(element for element in selected if meta[element]["position"] == position)
        for position in rules.squad_positions
    }
    lineups: list[tuple[int, ...]] = []
    for goalkeeper in combinations(by_position["GK"], 1):
        for defenders in range(rules.minimum_starters["DEF"], rules.maximum_starters["DEF"] + 1):
            for midfielders in range(
                rules.minimum_starters["MID"], rules.maximum_starters["MID"] + 1
            ):
                forwards = rules.starting_size - 1 - defenders - midfielders
                if not (rules.minimum_starters["FWD"] <= forwards <= rules.maximum_starters["FWD"]):
                    continue
                for groups in product(
                    combinations(by_position["DEF"], defenders),
                    combinations(by_position["MID"], midfielders),
                    combinations(by_position["FWD"], forwards),
                ):
                    lineups.append((*goalkeeper, *groups[0], *groups[1], *groups[2]))
    return lineups


def _formation(starters: tuple[int, ...], meta: dict[int, dict[str, Any]]) -> str:
    return "-".join(
        str(sum(meta[element]["position"] == position for element in starters))
        for position in ("DEF", "MID", "FWD")
    )


def _candidate(
    selected: list[int],
    starters: tuple[int, ...],
    bench_order: tuple[int, ...],
    captain: int,
    vice: int,
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    identity = {
        "starters": sorted(starters),
        "bench_order": list(bench_order),
        "captain": captain,
        "vice_captain": vice,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return {
        "candidate_id": f"XI-{digest}",
        "selected": list(selected),
        "lineups": {
            str(EVENT): {
                **identity,
                "formation": _formation(starters, meta),
            }
        },
    }


def _bench_orders(
    selected: list[int], starters: tuple[int, ...], meta: dict[int, dict[str, Any]]
) -> list[tuple[int, ...]]:
    bench = set(selected) - set(starters)
    outfield = sorted(element for element in bench if meta[element]["position"] != "GK")
    reserve_goalkeepers = sorted(element for element in bench if meta[element]["position"] == "GK")
    if len(outfield) != 3 or len(reserve_goalkeepers) != 1:
        raise ValueError("A legal FPL XI must leave three outfield substitutes and one goalkeeper")
    return [(*order, reserve_goalkeepers[0]) for order in permutations(outfield)]


def _captain_bonus(
    points: np.ndarray,
    played: np.ndarray,
    player_index: dict[int, int],
    captain: int,
    vice: int,
) -> np.ndarray:
    captain_index = player_index[captain]
    vice_index = player_index[vice]
    return np.where(
        played[:, 0, captain_index],
        points[:, 0, captain_index],
        np.where(played[:, 0, vice_index], points[:, 0, vice_index], 0),
    )


def _choice_leaders(family_means: np.ndarray, limit: int = 3) -> list[int]:
    """Return the minimax-balanced choice plus each family-specific leader."""
    leaders = family_means.max(axis=0)
    regrets = leaders[None, :] - family_means
    scores = 0.8 * regrets.mean(axis=1) + 0.2 * regrets.max(axis=1)
    ordered = list(np.argsort(scores, kind="stable"))
    family_leaders = [int(np.argmax(family_means[:, index])) for index in range(2)]
    output: list[int] = []
    for index in [*ordered, *family_leaders]:
        value = int(index)
        if value not in output:
            output.append(value)
        if len(output) == limit:
            break
    return output


def _rank_candidates(
    candidates: list[dict[str, Any]], residual_scores: np.ndarray, component_scores: np.ndarray
) -> list[dict[str, Any]]:
    means = np.column_stack(
        (residual_scores[:, :, 0].mean(axis=0), component_scores[:, :, 0].mean(axis=0))
    )
    leaders = means.max(axis=0)
    regrets = leaders[None, :] - means
    robust = 0.8 * regrets.mean(axis=1) + 0.2 * regrets.max(axis=1)
    rows = []
    for index, candidate in enumerate(candidates):
        lineup = candidate["lineups"][str(EVENT)]
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "formation": lineup["formation"],
                "starters": list(map(int, lineup["starters"])),
                "bench_order": list(map(int, lineup["bench_order"])),
                "captain": int(lineup["captain"]),
                "vice_captain": int(lineup["vice_captain"]),
                "residual_mean": float(means[index, 0]),
                "component_mean": float(means[index, 1]),
                "residual_regret": float(regrets[index, 0]),
                "component_regret": float(regrets[index, 1]),
                "robust_regret": float(robust[index]),
            }
        )
    rows.sort(key=lambda row: (row["robust_regret"], row["candidate_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def resolve_configuration_stability(
    selection_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    *,
    selection_simulations: int,
    holdout_simulations: int,
    practical_regret: float = PRACTICAL_CONFIGURATION_REGRET,
    maximum_rank: int = PRACTICAL_CONFIGURATION_MAX_RANK,
) -> dict[str, Any]:
    """Resolve narrowly defined practical ties across independent samples.

    Captain choices must agree exactly. Vice-captain choices can be statistically indistinguishable
    because their returns are observed only when the captain misses out. The ordering of the same
    outfield bench can likewise be noisy when two substitutes have virtually identical conditional
    value. A single starter/bench swap can also straddle the sample boundary while every other
    decision agrees. For one of these narrowly defined *single-action* disagreements, require both
    leaders to be top-three and within 0.0125 robust-regret points in both samples, then use all
    simulated worlds to choose between them. Captain or multi-player XI disagreement still fails
    closed.
    """

    if not selection_rows or not holdout_rows:
        raise ValueError("configuration stability needs selection and holdout rankings")
    selection_by_id = {str(row["candidate_id"]): row for row in selection_rows}
    holdout_by_id = {str(row["candidate_id"]): row for row in holdout_rows}
    selection_leader = selection_rows[0]
    holdout_leader = holdout_rows[0]
    selection_id = str(selection_leader["candidate_id"])
    holdout_id = str(holdout_leader["candidate_id"])
    if selection_id == holdout_id:
        return {
            "stable": True,
            "exact": True,
            "vice_only_practical_equivalence": False,
            "bench_order_only_practical_equivalence": False,
            "single_starter_bench_swap_practical_equivalence": False,
            "practical_equivalence_type": None,
            "resolved_candidate_id": selection_id,
            "eligible_candidate_ids": [selection_id],
            "selection_leader_regret_gap": 0.0,
            "holdout_leader_regret_gap": 0.0,
        }

    def vice_equivalence_core(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            tuple(sorted(map(int, row["starters"]))),
            tuple(map(int, row["bench_order"])),
            int(row["captain"]),
        )

    def bench_equivalence_core(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            tuple(sorted(map(int, row["starters"]))),
            tuple(sorted(map(int, row["bench_order"]))),
            int(row["captain"]),
            int(row["vice_captain"]),
        )

    def is_single_starter_bench_swap(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_starters = set(map(int, left["starters"]))
        right_starters = set(map(int, right["starters"]))
        left_bench = list(map(int, left["bench_order"]))
        right_bench = list(map(int, right["bench_order"]))
        starter_out = left_starters - right_starters
        starter_in = right_starters - left_starters
        if len(starter_out) != 1 or len(starter_in) != 1:
            return False
        outgoing = next(iter(starter_out))
        incoming = next(iter(starter_in))
        return bool(
            int(left["captain"]) == int(right["captain"])
            and int(left["vice_captain"]) == int(right["vice_captain"])
            and left_starters | set(left_bench) == right_starters | set(right_bench)
            and incoming in left_bench
            and outgoing in right_bench
            and [player for player in left_bench if player != incoming]
            == [player for player in right_bench if player != outgoing]
        )

    leaders_are_common = holdout_id in selection_by_id and selection_id in holdout_by_id
    if not leaders_are_common:
        return {
            "stable": False,
            "exact": False,
            "vice_only_practical_equivalence": False,
            "bench_order_only_practical_equivalence": False,
            "single_starter_bench_swap_practical_equivalence": False,
            "practical_equivalence_type": None,
            "resolved_candidate_id": selection_id,
            "eligible_candidate_ids": [],
            "selection_leader_regret_gap": None,
            "holdout_leader_regret_gap": None,
        }

    selection_gap = abs(
        float(selection_by_id[holdout_id]["robust_regret"])
        - float(selection_leader["robust_regret"])
    )
    holdout_gap = abs(
        float(holdout_by_id[selection_id]["robust_regret"]) - float(holdout_leader["robust_regret"])
    )
    vice_only_equivalent = bool(
        vice_equivalence_core(selection_leader) == vice_equivalence_core(holdout_leader)
        and int(selection_leader["vice_captain"]) != int(holdout_leader["vice_captain"])
        and int(selection_by_id[holdout_id]["rank"]) <= maximum_rank
        and int(holdout_by_id[selection_id]["rank"]) <= maximum_rank
        and selection_gap <= practical_regret
        and holdout_gap <= practical_regret
    )
    bench_order_only_equivalent = bool(
        bench_equivalence_core(selection_leader) == bench_equivalence_core(holdout_leader)
        and tuple(map(int, selection_leader["bench_order"]))
        != tuple(map(int, holdout_leader["bench_order"]))
        and int(selection_by_id[holdout_id]["rank"]) <= maximum_rank
        and int(holdout_by_id[selection_id]["rank"]) <= maximum_rank
        and selection_gap <= practical_regret
        and holdout_gap <= practical_regret
    )
    single_starter_bench_swap_equivalent = bool(
        is_single_starter_bench_swap(selection_leader, holdout_leader)
        and int(selection_by_id[holdout_id]["rank"]) <= maximum_rank
        and int(holdout_by_id[selection_id]["rank"]) <= maximum_rank
        and selection_gap <= practical_regret
        and holdout_gap <= practical_regret
    )
    if not (
        vice_only_equivalent
        or bench_order_only_equivalent
        or single_starter_bench_swap_equivalent
    ):
        return {
            "stable": False,
            "exact": False,
            "vice_only_practical_equivalence": False,
            "bench_order_only_practical_equivalence": False,
            "single_starter_bench_swap_practical_equivalence": False,
            "practical_equivalence_type": None,
            "resolved_candidate_id": selection_id,
            "eligible_candidate_ids": [],
            "selection_leader_regret_gap": selection_gap,
            "holdout_leader_regret_gap": holdout_gap,
        }

    equivalence_type = (
        "vice_captain"
        if vice_only_equivalent
        else "bench_order"
        if bench_order_only_equivalent
        else "single_starter_bench_swap"
    )

    def is_same_equivalence_class(row: dict[str, Any]) -> bool:
        if equivalence_type == "vice_captain":
            return vice_equivalence_core(row) == vice_equivalence_core(selection_leader)
        if equivalence_type == "single_starter_bench_swap":
            return str(row["candidate_id"]) in {selection_id, holdout_id}
        return bench_equivalence_core(row) == bench_equivalence_core(selection_leader)

    common = set(selection_by_id) & set(holdout_by_id)
    eligible = [
        candidate_id
        for candidate_id in common
        if is_same_equivalence_class(selection_by_id[candidate_id])
        and int(selection_by_id[candidate_id]["rank"]) <= maximum_rank
        and int(holdout_by_id[candidate_id]["rank"]) <= maximum_rank
        and float(selection_by_id[candidate_id]["robust_regret"])
        - float(selection_leader["robust_regret"])
        <= practical_regret
        and float(holdout_by_id[candidate_id]["robust_regret"])
        - float(holdout_leader["robust_regret"])
        <= practical_regret
    ]
    total = selection_simulations + holdout_simulations
    combined = {
        candidate_id: (
            selection_simulations * float(selection_by_id[candidate_id]["robust_regret"])
            + holdout_simulations * float(holdout_by_id[candidate_id]["robust_regret"])
        )
        / total
        for candidate_id in eligible
    }
    resolved = min(eligible, key=lambda candidate_id: (combined[candidate_id], candidate_id))
    return {
        "stable": True,
        "exact": False,
        "vice_only_practical_equivalence": vice_only_equivalent,
        "bench_order_only_practical_equivalence": bench_order_only_equivalent,
        "single_starter_bench_swap_practical_equivalence": (
            single_starter_bench_swap_equivalent
        ),
        "practical_equivalence_type": equivalence_type,
        "resolved_candidate_id": resolved,
        "eligible_candidate_ids": sorted(eligible),
        "combined_robust_regret": combined,
        "selection_leader_regret_gap": selection_gap,
        "holdout_leader_regret_gap": holdout_gap,
        "practical_regret": practical_regret,
        "maximum_rank": maximum_rank,
    }


def _paired_delta(challenger: np.ndarray, incumbent: np.ndarray) -> dict[str, float]:
    delta = challenger.astype(np.float64) - incumbent.astype(np.float64)
    mean = float(delta.mean())
    standard_error = float(delta.std(ddof=1) / math.sqrt(len(delta)))
    return {
        "mean": mean,
        "ci95_low": mean - 1.96 * standard_error,
        "ci95_high": mean + 1.96 * standard_error,
        "beat_probability": float(np.mean(delta > 0)),
        "tie_probability": float(np.mean(delta == 0)),
    }


def _player_labels(elements: list[int], meta: dict[int, dict[str, Any]]) -> list[str]:
    return [str(meta[element]["player_name"]) for element in elements]


def _simulate_families(
    by_player: dict[int, dict[int, dict[str, Any]]],
    simulations: int,
    seed: int,
    raw_weight: float,
) -> tuple[list[int], np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    events = (EVENT,)
    player_ids = sorted(by_player)
    residual_points, residual_played = _simulate_player_outcomes(
        player_ids,
        events,
        by_player,
        calibrate_residuals(),
        simulations,
        seed,
    )
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, events)
    (
        component_player_ids,
        component_raw,
        component_anchored,
        component_played,
        _,
        component_diagnostics,
    ) = simulate_component_outcomes(
        by_player,
        events,
        goal_rates,
        calibrate_empirical_components(),
        simulations,
        seed + 10_000,
    )
    if component_player_ids != player_ids:
        raise RuntimeError("Residual and component simulation player order differs")
    component_evidence = component_anchored + raw_weight * (component_raw - component_anchored)
    diagnostics = {
        "goal_rates": goal_diagnostics,
        "component": component_diagnostics,
    }
    return (
        player_ids,
        residual_points,
        residual_played,
        component_evidence,
        {**diagnostics, "component_played": component_played},
    )


def _verify_lineage(
    *, decision_path: Path = SYNTHESIZED_DECISION
) -> tuple[dict[str, Any], dict[str, str]]:
    decision = load_json_artifact(decision_path, "synthesized GW1 decision")
    robust_sha = require_recorded_file(
        decision,
        ("source_artifacts", "robust_results_sha256"),
        ROBUST_RESULTS,
        "synthesized decision robust input",
    )
    horizon_sha = require_recorded_file(
        decision,
        ("source_artifacts", "horizon_results_sha256"),
        HORIZON_RESULTS,
        "synthesized decision horizon input",
    )
    robust = load_json_artifact(ROBUST_RESULTS, "global robust-search results")
    horizon = load_json_artifact(HORIZON_RESULTS, "horizon-audit results")
    forecast_sha = require_current_forecast(
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
    return decision, {
        "decision_sha256": sha256_file(decision_path),
        "forecast_sha256": forecast_sha,
        "component_forecast_sha256": sha256_file(CURRENT_COMPONENT_FORECAST),
        "robust_results_sha256": robust_sha,
        "horizon_results_sha256": horizon_sha,
    }


def _configuration_changes(
    before: dict[str, Any],
    after: dict[str, Any],
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    before_starters = set(map(int, before["starters"]))
    after_starters = set(map(int, after["starters"]))

    def names(elements: list[int] | set[int]) -> list[str]:
        return [str(meta[element]["player_name"]) for element in elements]

    return {
        "starters_in": names(sorted(after_starters - before_starters)),
        "starters_out": names(sorted(before_starters - after_starters)),
        "bench_order_before": names(list(map(int, before["bench_order"]))),
        "bench_order_after": names(list(map(int, after["bench_order"]))),
        "captain_before": str(meta[int(before["captain"])]["player_name"]),
        "captain_after": str(meta[int(after["captain"])]["player_name"]),
        "vice_captain_before": str(meta[int(before["vice_captain"])]["player_name"]),
        "vice_captain_after": str(meta[int(after["vice_captain"])]["player_name"]),
        "formation_before": str(before["formation"]),
        "formation_after": str(after["formation"]),
    }


def _apply_simulation_configuration(
    decision: dict[str, Any],
    champion: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    by_player: dict[int, dict[int, dict[str, Any]]],
    evidence: dict[str, Any],
    rules: SquadRules | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace only the actionable GW1 configuration, never the selected 15.

    Squad identity and future planning lineups stay intact.  The next deadline run will solve
    future events again; only the current event is allowed to become simulation-authoritative.
    """

    promoted = deepcopy(decision)
    current = promoted["decision"]["candidate"]
    if set(map(int, current["selected"])) != set(map(int, champion["selected"])):
        raise ValueError("A configuration promotion cannot change the selected 15")
    before = dict(current["lineups"][str(EVENT)])
    after = dict(champion["lineups"][str(EVENT)])
    selected_rows = [meta[int(element)] for element in current["selected"]]
    validate_lineup(
        selected_rows,
        after["starters"],
        after["bench_order"],
        int(after["captain"]),
        int(after["vice_captain"]),
        rules or load_rules(),
    )
    after["expected_points"] = sum(
        float(by_player[int(element)][EVENT]["expected_points"]) for element in after["starters"]
    ) + float(by_player[int(after["captain"])][EVENT]["expected_points"])
    current["lineups"][str(EVENT)] = after
    current["gw1_formation"] = str(after["formation"])
    bench = list(map(int, after["bench_order"]))
    current["gw1_bench_spend"] = (
        sum(float(meta[element]["market_price"]) for element in bench) / 10.0
    )
    current["gw1_outfield_bench_spend"] = (
        sum(
            float(meta[element]["market_price"])
            for element in bench
            if str(meta[element]["position"]) != "GK"
        )
        / 10.0
    )
    captain_name = str(meta[int(after["captain"])]["player_name"])
    current["display_name"] = (
        f"{after['formation']} · {captain_name} captain · £{current['gw1_bench_spend']:.1f}m bench"
    )
    promoted["decision"]["display_name"] = current["display_name"]
    promoted["decision"]["formation"] = str(after["formation"])
    promoted["decision"]["squad"] = _named_squad(current, meta)
    changes = _configuration_changes(before, after, meta)
    promoted["decision"]["configuration_evidence"] = {
        **evidence,
        "authority": "independent_residual_and_component_simulation",
        "raw_xp_role": "forecast_input_and_display_metric_not_final_configuration_selector",
        "changes": changes,
    }
    selected_id = str(promoted["decision"]["candidate_id"])
    for row in promoted.get("ranking") or []:
        if str(row.get("candidate_id")) == selected_id:
            row["gw1_formation"] = str(after["formation"])
            row["display_name"] = current["display_name"]
    return promoted, changes


def run_current_squad_audit(
    *,
    selection_simulations: int = 25_000,
    holdout_simulations: int = 25_000,
    finalists: int = 64,
    selection_seed: int = 20260810,
    holdout_seed: int = 20260811,
    promote: bool = False,
    decision_path: Path = SYNTHESIZED_DECISION,
    decision_results_path: Path = SYNTHESIZED_RESULTS,
    decision_report_path: Path = SYNTHESIZED_REPORT,
    results_path: Path = RESULTS_JSON,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    if selection_simulations < 2_000 or holdout_simulations < 5_000:
        raise ValueError("Current-squad audit simulation counts are too small")
    ensure_engine_layout()
    decision, lineage = _verify_lineage(decision_path=decision_path)
    current = decision["decision"]["candidate"]
    selected = list(map(int, current["selected"]))
    current_lineup = current["lineups"][str(EVENT)]
    _, loaded = _load_rows((EVENT,))
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    if not set(selected) <= set(by_player):
        raise ValueError("Published squad contains a player missing from the current forecast")

    component_backtest = load_json_artifact(
        COMPONENT_BACKTEST_METRICS, "component backtest metrics"
    )
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    print("Current-squad audit: simulating selection worlds", flush=True)
    (
        player_ids,
        residual_points,
        residual_played,
        component_points,
        selection_diagnostics,
    ) = _simulate_families(by_player, selection_simulations, selection_seed, raw_weight)
    component_played = selection_diagnostics.pop("component_played")
    player_index = {element: index for index, element in enumerate(player_ids)}

    xis = enumerate_legal_xis(selected, meta)
    bench_candidates: list[dict[str, Any]] = []
    bench_ranges: list[tuple[int, int]] = []
    for starters in xis:
        start = len(bench_candidates)
        arbitrary_captain, arbitrary_vice = starters[:2]
        for order in _bench_orders(selected, starters, meta):
            bench_candidates.append(
                _candidate(
                    selected,
                    starters,
                    order,
                    arbitrary_captain,
                    arbitrary_vice,
                    meta,
                )
            )
        bench_ranges.append((start, len(bench_candidates)))
    residual_bench_scores = _score_candidates(
        bench_candidates,
        player_ids,
        (EVENT,),
        residual_points,
        residual_played,
        meta,
    )
    component_bench_scores = _score_candidates(
        bench_candidates,
        player_ids,
        (EVENT,),
        component_points,
        component_played,
        meta,
    )

    candidates_by_id: dict[str, dict[str, Any]] = {}
    for starters, (start, end) in zip(xis, bench_ranges, strict=True):
        bench_means = np.column_stack(
            (
                residual_bench_scores[:, start:end, 0].mean(axis=0),
                component_bench_scores[:, start:end, 0].mean(axis=0),
            )
        )
        bench_choices = [
            tuple(bench_candidates[start + index]["lineups"][str(EVENT)]["bench_order"])
            for index in _choice_leaders(bench_means)
        ]
        captain_pairs = list(permutations(starters, 2))
        captain_means = []
        for captain, vice in captain_pairs:
            residual_bonus = _captain_bonus(
                residual_points, residual_played, player_index, captain, vice
            )
            component_bonus = _captain_bonus(
                component_points, component_played, player_index, captain, vice
            )
            captain_means.append((float(residual_bonus.mean()), float(component_bonus.mean())))
        captain_choices = [
            captain_pairs[index] for index in _choice_leaders(np.asarray(captain_means))
        ]
        for bench_order, (captain, vice) in product(bench_choices, captain_choices):
            candidate = _candidate(selected, starters, bench_order, captain, vice, meta)
            candidates_by_id[candidate["candidate_id"]] = candidate

    published = _candidate(
        selected,
        tuple(map(int, current_lineup["starters"])),
        tuple(map(int, current_lineup["bench_order"])),
        int(current_lineup["captain"]),
        int(current_lineup["vice_captain"]),
        meta,
    )
    candidates_by_id[published["candidate_id"]] = published
    candidates = list(candidates_by_id.values())
    residual_selection_scores = _score_candidates(
        candidates, player_ids, (EVENT,), residual_points, residual_played, meta
    )
    component_selection_scores = _score_candidates(
        candidates, player_ids, (EVENT,), component_points, component_played, meta
    )
    selection_rows = _rank_candidates(
        candidates, residual_selection_scores, component_selection_scores
    )
    selection_champion_id = selection_rows[0]["candidate_id"]
    finalist_ids = [row["candidate_id"] for row in selection_rows[:finalists]]
    if published["candidate_id"] not in finalist_ids:
        finalist_ids.append(published["candidate_id"])
    finalists_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    finalist_candidates = [finalists_by_id[candidate_id] for candidate_id in finalist_ids]

    del residual_bench_scores, component_bench_scores
    del residual_selection_scores, component_selection_scores
    print("Current-squad audit: simulating independent holdout worlds", flush=True)
    (
        holdout_player_ids,
        residual_holdout_points,
        residual_holdout_played,
        component_holdout_points,
        holdout_diagnostics,
    ) = _simulate_families(by_player, holdout_simulations, holdout_seed, raw_weight)
    component_holdout_played = holdout_diagnostics.pop("component_played")
    if holdout_player_ids != player_ids:
        raise RuntimeError("Selection and holdout simulation player order differs")
    residual_holdout_scores = _score_candidates(
        finalist_candidates,
        player_ids,
        (EVENT,),
        residual_holdout_points,
        residual_holdout_played,
        meta,
    )
    component_holdout_scores = _score_candidates(
        finalist_candidates,
        player_ids,
        (EVENT,),
        component_holdout_points,
        component_holdout_played,
        meta,
    )
    holdout_rows = _rank_candidates(
        finalist_candidates, residual_holdout_scores, component_holdout_scores
    )
    finalist_index = {
        candidate["candidate_id"]: index for index, candidate in enumerate(finalist_candidates)
    }
    published_index = finalist_index[published["candidate_id"]]
    holdout_champion_id = str(holdout_rows[0]["candidate_id"])
    stability = resolve_configuration_stability(
        selection_rows,
        holdout_rows,
        selection_simulations=selection_simulations,
        holdout_simulations=holdout_simulations,
    )
    resolved_champion_id = str(stability["resolved_candidate_id"])
    champion_index = finalist_index[resolved_champion_id]
    residual_delta = _paired_delta(
        residual_holdout_scores[:, champion_index, 0],
        residual_holdout_scores[:, published_index, 0],
    )
    component_delta = _paired_delta(
        component_holdout_scores[:, champion_index, 0],
        component_holdout_scores[:, published_index, 0],
    )
    champion = finalists_by_id[resolved_champion_id]
    champion_lineup = champion["lineups"][str(EVENT)]
    exact_match = resolved_champion_id == published["candidate_id"]
    holdout_by_id = {str(row["candidate_id"]): row for row in holdout_rows}
    holdout_stable = bool(stability["stable"])
    holdout_robust_gain = float(
        holdout_by_id[str(published["candidate_id"])]["robust_regret"]
        - holdout_by_id[resolved_champion_id]["robust_regret"]
    )
    promotion_ready = (
        not exact_match and holdout_stable and holdout_robust_gain >= MINIMUM_HOLDOUT_ROBUST_GAIN
    )
    publishable = holdout_stable
    if not holdout_stable:
        verdict = "configuration_selection_and_holdout_disagree_publication_blocked"
    elif stability["vice_only_practical_equivalence"]:
        verdict = "vice_captain_equivalence_resolved_by_combined_worlds"
    elif stability["bench_order_only_practical_equivalence"]:
        verdict = "bench_order_equivalence_resolved_by_combined_worlds"
    elif stability["single_starter_bench_swap_practical_equivalence"]:
        verdict = "single_starter_bench_swap_equivalence_resolved_by_combined_worlds"
    elif exact_match:
        verdict = "published_configuration_is_selection_champion"
    elif promotion_ready:
        verdict = "simulation_champion_promoted_after_independent_holdout"
    else:
        verdict = "published_configuration_retained_below_material_gain_floor"

    names = {str(element): str(meta[element]["player_name"]) for element in selected}
    result = {
        "version": VERSION,
        "event": EVENT,
        "verdict": verdict,
        "read_only": not promote,
        "production_changed": bool(promote and promotion_ready),
        "promotion_ready": promotion_ready,
        "publishable": publishable,
        "input_lineage": lineage,
        "search": {
            "legal_xis": len(xis),
            "bench_orders_scored": len(bench_candidates),
            "joint_configurations_scored": len(candidates),
            "holdout_finalists": len(finalist_candidates),
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "component_raw_weight": raw_weight,
            "selector": (
                "minimax regret across residual and explicit football-component simulation families"
            ),
            "minimum_holdout_robust_gain": MINIMUM_HOLDOUT_ROBUST_GAIN,
            "practical_configuration_regret": PRACTICAL_CONFIGURATION_REGRET,
            "practical_configuration_max_rank": PRACTICAL_CONFIGURATION_MAX_RANK,
        },
        "published": {
            "source_candidate_id": str(current["candidate_id"]),
            "audit_candidate_id": published["candidate_id"],
            "formation": str(current_lineup["formation"]),
            "starters": _player_labels(list(map(int, current_lineup["starters"])), meta),
            "bench_order": _player_labels(list(map(int, current_lineup["bench_order"])), meta),
            "captain": names[str(current_lineup["captain"])],
            "vice_captain": names[str(current_lineup["vice_captain"])],
        },
        "selection_champion": {
            "candidate_id": selection_champion_id,
            "resolved_candidate_id": resolved_champion_id,
            "formation": champion_lineup["formation"],
            "starters": _player_labels(list(champion_lineup["starters"]), meta),
            "bench_order": _player_labels(list(champion_lineup["bench_order"]), meta),
            "captain": names[str(champion_lineup["captain"])],
            "vice_captain": names[str(champion_lineup["vice_captain"])],
            "holdout_delta_to_published": {
                "residual": residual_delta,
                "component": component_delta,
            },
            "holdout_champion_id": holdout_champion_id,
            "holdout_stable": holdout_stable,
            "holdout_robust_gain": holdout_robust_gain,
        },
        "configuration_stability": stability,
        "resolved_champion": {
            "candidate_id": resolved_champion_id,
            "formation": champion_lineup["formation"],
            "starters": _player_labels(list(champion_lineup["starters"]), meta),
            "bench_order": _player_labels(list(champion_lineup["bench_order"]), meta),
            "captain": names[str(champion_lineup["captain"])],
            "vice_captain": names[str(champion_lineup["vice_captain"])],
            "holdout_delta_to_published": {
                "residual": residual_delta,
                "component": component_delta,
            },
            "holdout_robust_gain": holdout_robust_gain,
        },
        "selection_top": selection_rows[:20],
        "holdout_top": holdout_rows[:20],
        "player_names": names,
        "diagnostics": {
            "selection": selection_diagnostics,
            "holdout": holdout_diagnostics,
        },
        "decision_rule": (
            "Never alter the selected 15 here. Select XI, bench priority, captain and vice by "
            "minimax regret across residual and explicit football-component simulations. Promote "
            "only when the preselected champion remains the independent holdout champion, or when "
            "both samples agree on captain and differ only between top-three vice-captains, "
            "orderings of the same bench, or one starter/bench swap within 0.0125 regret in both "
            "samples. Resolve that narrow single-action equivalence class using all simulated "
            "worlds. Every captain or multi-player XI disagreement fails closed."
        ),
    }
    if promote and promotion_ready:
        evidence = {
            "audit_version": VERSION,
            "selection_champion_id": selection_champion_id,
            "resolved_champion_id": resolved_champion_id,
            "holdout_champion_id": holdout_champion_id,
            "holdout_robust_gain": holdout_robust_gain,
            "selection_simulations_per_family": selection_simulations,
            "holdout_simulations_per_family": holdout_simulations,
            "selection_seed": selection_seed,
            "holdout_seed": holdout_seed,
            "component_raw_weight": raw_weight,
        }
        decision, changes = _apply_simulation_configuration(
            decision,
            champion,
            meta,
            by_player,
            evidence,
        )
        result["changes"] = changes
        rendered_decision = json.dumps(decision, indent=2, sort_keys=True) + "\n"
        _atomic_text(decision_path, rendered_decision)
        _atomic_text(decision_results_path, rendered_decision)
        _atomic_text(decision_report_path, _render_synthesis_report(decision))
    else:
        result["changes"] = None
    result["lineage"] = {
        **lineage,
        "input_decision_sha256": lineage["decision_sha256"],
        "decision_sha256": sha256_file(decision_path),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_text(results_path, json.dumps(result, indent=2, sort_keys=True) + "\n")
    _atomic_text(report_path, _render_report(result))
    return result


def _render_report(result: dict[str, Any]) -> str:
    published = result["published"]
    champion = result.get("resolved_champion") or result["selection_champion"]
    residual = champion["holdout_delta_to_published"]["residual"]
    component = champion["holdout_delta_to_published"]["component"]
    return "\n".join(
        [
            "# Simulation-authoritative XI, captain and bench audit",
            "",
            f"Verdict: **{result['verdict']}**.",
            f"Production changed: **{result['production_changed']}**.",
            f"Publishable: **{result['publishable']}**.",
            "",
            (
                "This checksum-bound audit never replaces the selected 15. It exhaustively "
                "selects the actionable XI, all three outfield substitute positions, captain and "
                "vice-captain using residual and explicit football-component simulations."
            ),
            "",
            "## Published configuration",
            "",
            f"- Formation: {published['formation']}",
            f"- Captain / vice: {published['captain']} / {published['vice_captain']}",
            f"- XI: {', '.join(published['starters'])}",
            f"- Bench order: {', '.join(published['bench_order'])}",
            "",
            "## Resolved configuration champion",
            "",
            f"- Formation: {champion['formation']}",
            f"- Captain / vice: {champion['captain']} / {champion['vice_captain']}",
            f"- XI: {', '.join(champion['starters'])}",
            f"- Bench order: {', '.join(champion['bench_order'])}",
            "",
            "## Independent holdout difference versus published",
            "",
            "| Family | Mean | 95% CI | Beat probability |",
            "| --- | ---: | ---: | ---: |",
            (
                f"| Residual | {residual['mean']:+.3f} | "
                f"[{residual['ci95_low']:+.3f}, {residual['ci95_high']:+.3f}] | "
                f"{residual['beat_probability']:.1%} |"
            ),
            (
                f"| Component | {component['mean']:+.3f} | "
                f"[{component['ci95_low']:+.3f}, {component['ci95_high']:+.3f}] | "
                f"{component['beat_probability']:.1%} |"
            ),
            "",
            "## Coverage",
            "",
            f"- Legal XIs: {result['search']['legal_xis']}",
            f"- Bench orders scored: {result['search']['bench_orders_scored']}",
            f"- Joint configurations scored: {result['search']['joint_configurations_scored']}",
            f"- Holdout finalists: {result['search']['holdout_finalists']}",
            (
                "- Independent holdout champion: "
                f"{result['selection_champion']['holdout_champion_id']} "
                f"(stable: {result['selection_champion']['holdout_stable']})"
            ),
            f"- Holdout robust gain: {champion['holdout_robust_gain']:+.3f}",
            "",
            result["decision_rule"],
            "",
        ]
    )
