from itertools import permutations

import numpy as np
import pytest
from test_engine_weekly_simulation import _rules

from fplagent_engine.acceleration import cuda_available
from fplagent_engine.current_squad_audit import _bench_orders, enumerate_legal_xis
from fplagent_engine.exact_configuration import (
    configuration_frontier,
    fused_score_candidates,
    pareto_indices,
)
from fplagent_engine.season_state import ChipType
from fplagent_engine.tournament import _score_candidates_cpu


def _meta():
    return {
        i: {"position": p}
        for i, p in enumerate(["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3)
    }


def _candidate(xi, order, captain, vice, event=4):
    return {
        "selected": list(range(15)),
        "lineups": {
            str(event): {
                "starters": xi,
                "bench_order": order,
                "captain": captain,
                "vice_captain": vice,
            }
        },
    }


def test_frontier_matches_bruteforce_dominance_with_duplicates():
    rng = np.random.default_rng(19)
    values = rng.integers(-10, 11, (180, 3)).astype(float)
    values = np.vstack([values, values[:10]])
    expected = {
        tuple(v)
        for v in values
        if not any(np.all(other >= v) and np.any(other > v) for other in values)
    }
    actual = values[pareto_indices(values)]
    assert {tuple(v) for v in actual} == expected
    assert len(actual) == len(expected)


def test_fused_scorer_matches_every_appearance_mask_and_multiple_formations():
    if not cuda_available():
        pytest.skip("CUDA not available")
    meta = _meta()
    all_xis = enumerate_legal_xis(list(meta), meta, _rules())
    candidates = []
    for xi in (all_xis[0], all_xis[90], all_xis[250], all_xis[-1]):
        for order in _bench_orders(list(meta), xi, meta):
            candidates.append(_candidate(xi, order, xi[-1], xi[0]))
    masks = np.arange(1 << 15, dtype=np.uint32)
    played = ((masks[:, None] >> np.arange(15)) & 1).astype(bool)[:, None, :]
    points = np.random.default_rng(73).integers(-3, 30, played.shape, dtype=np.int8)
    gpu = fused_score_candidates(candidates, list(meta), (4,), points, played, meta)
    cpu = _score_candidates_cpu(candidates, list(meta), (4,), points, played, meta)
    np.testing.assert_array_equal(gpu, cpu)


@pytest.mark.parametrize("backend", ["cpu", "cuda"])
@pytest.mark.parametrize("chip", [None, ChipType.TRIPLE_CAPTAIN, ChipType.BENCH_BOOST])
def test_configuration_means_match_reference_and_enumerate_all_choices(monkeypatch, backend, chip):
    if backend == "cuda" and not cuda_available():
        pytest.skip("CUDA not available")
    import fplagent_engine.exact_configuration as module

    if backend == "cpu":
        monkeypatch.setattr(module, "cupy_module", lambda: None)

    meta = _meta()
    selected = list(meta)
    # Exhaustive Cartesian comparison on two XIs: no shortlist/pruning oracle.
    xis = enumerate_legal_xis(selected, meta, _rules())[30:32]
    monkeypatch.setattr(module, "enumerate_legal_xis", lambda *a: xis)
    rng = np.random.default_rng(74)
    worlds = {
        name: {
            "player_ids": selected,
            "events": (4,),
            "player_meta": meta,
            "points": rng.integers(-3, 16, (samples, 1, 15), dtype=np.int8),
            "played": rng.random((samples, 1, 15)) < 0.74,
        }
        for name, samples in zip(
            ("residual", "component_anchored", "component_raw"), (61, 83, 101), strict=True
        )
    }
    candidates = [
        _candidate(xi, order, c, v)
        for xi in xis
        for order in _bench_orders(selected, xi, meta)
        for c, v in permutations(xi, 2)
    ]
    actual = configuration_frontier(selected, 4, worlds, _rules(), chip=chip)

    def score_with_chip(candidates, world):
        scores = _score_candidates_cpu(
            candidates, selected, (4,), world["points"], world["played"], meta
        ).astype(float)
        for i, candidate in enumerate(candidates):
            lineup = candidate["lineups"]["4"]
            c, v = lineup["captain"], lineup["vice_captain"]
            bonus = np.where(world["played"][:, 0, c], world["points"][:, 0, c],
                             np.where(world["played"][:, 0, v], world["points"][:, 0, v], 0))
            if chip == ChipType.TRIPLE_CAPTAIN:
                scores[:, i, 0] += bonus
            elif chip == ChipType.BENCH_BOOST:
                scores[:, i, 0] = (world["points"] * world["played"]).sum(axis=(1, 2)) + bonus
        return scores

    means = np.column_stack(
        [
            score_with_chip(candidates, w).mean(axis=(0, 2))
            for w in worlds.values()
        ]
    )
    expected = means[pareto_indices(means)]
    # Exact integer score means, floating summation order only differs.
    for vector in expected:
        assert np.any(np.all(np.isclose(actual["means"], vector, atol=1e-10, rtol=0), axis=1))
    for vector in actual["means"]:
        assert np.any(np.all(np.isclose(expected, vector, atol=1e-10, rtol=0), axis=1))
    assert actual["possible_configurations"] == 2 * 6 * 110
    for cfg, vector in zip(actual["configurations"], actual["means"], strict=True):
        for i, w in enumerate(worlds.values()):
            reference = score_with_chip([_candidate(*cfg)], w)
            assert reference.mean() == pytest.approx(vector[i], abs=1e-10)


def test_fused_scores_handle_future_squads_and_different_player_order():
    if not cuda_available():
        pytest.skip("CUDA not available")
    meta = {**_meta(), 15: {"position": "DEF"}}
    xi = enumerate_legal_xis(list(range(15)), meta, _rules())[100]
    bench = _bench_orders(list(range(15)), xi, meta)[2]
    candidate = _candidate(xi, bench, xi[0], xi[-1])
    outgoing = 2
    replacement = lambda ps: [15 if p == outgoing else p for p in ps]
    candidate["planned_squads"] = {"5": replacement(list(range(15)))}
    candidate["lineups"]["5"] = {
        "starters": replacement(xi),
        "bench_order": replacement(bench),
        "captain": 15 if xi[0] == outgoing else xi[0],
        "vice_captain": 15 if xi[-1] == outgoing else xi[-1],
    }
    rng = np.random.default_rng(13)
    ids = list(reversed(range(16)))
    points = rng.integers(-3, 30, (301, 2, 16), dtype=np.int8)
    played = rng.random(points.shape) < 0.7
    actual = fused_score_candidates([candidate], ids, (4, 5), points, played, meta)
    expected = _score_candidates_cpu([candidate], ids, (4, 5), points, played, meta)
    np.testing.assert_array_equal(actual, expected)
