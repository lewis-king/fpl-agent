"""Exact, simulation-mean configuration frontiers for a legal FPL squad.

Collapse samples by appearance mask, keeping conditional *point sums*, not
independent player means. This preserves correlations, negative points, legal
autosubs and captain fallback. CPU reference and CUDA kernels share the same
scoring contract. No future observation is used to pick a lineup per sample.
"""

from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
from itertools import permutations

import numpy as np

from .acceleration import cupy_module
from .current_squad_audit import _bench_orders, enumerate_legal_xis
from .season_state import ChipType

CUDA_SOURCE = r"""
__device__ void multipliers(unsigned int mask, const int* pos, const int* xi,
                           const int* bench, int captain, int vice, int* weights) {
    int counts[4] = {0,0,0,0}, missing[11], nmissing=0, keeper=-1;
    for (int p=0; p<15; ++p) weights[p]=0;
    for (int j=0; j<11; ++j) {
        int p=xi[j]; counts[pos[p]]++;
        if (mask & (1u<<p)) weights[p]=1;
        else if (pos[p]!=0) missing[nmissing++]=p;
        if (pos[p]==0) keeper=p;
    }
    for (int j=0; j<4; ++j) {
        int p=bench[j];
        if (pos[p]==0) {
            if (!(mask & (1u<<keeper)) && (mask & (1u<<p))) weights[p]=1;
        } else if (mask & (1u<<p)) {
            for (int k=0; k<nmissing; ++k) {
                int old=missing[k]; if (old<0) continue;
                int d=counts[1]-(pos[old]==1)+(pos[p]==1);
                int m=counts[2]-(pos[old]==2)+(pos[p]==2);
                int f=counts[3]-(pos[old]==3)+(pos[p]==3);
                if (d>=3 && m>=2 && f>=1) {
                    counts[pos[old]]--; counts[pos[p]]++; missing[k]=-1;
                    weights[p]=1; break;
                }
            }
        }
    }
    if (captain>=0) {
        if (mask & (1u<<captain)) weights[captain]++;
        else if (mask & (1u<<vice)) weights[vice]++;
    }
}
extern "C" __global__ void exact_scores(
 const int* points, const unsigned char* played, const int* indices, const int* pos,
 const int* xi, const int* bench, const int* captains, const int* vices,
 int samples, int candidates, int events, int universe, int* scores) {
    long t=(long)blockIdx.x*blockDim.x+threadIdx.x;
    long total=(long)samples*candidates*events; if (t>=total) return;
    int e=t%events, c=(t/events)%candidates, s=t/(events*candidates), ce=c*events+e;
    unsigned int mask=0; long row=((long)s*events+e)*universe;
    for (int p=0;p<15;++p) if (played[row+indices[ce*15+p]]) mask|=(1u<<p);
    int w[15]; multipliers(mask,pos+ce*15,xi+ce*11,bench+ce*4,captains[ce],vices[ce],w);
    int score=0; for (int p=0;p<15;++p) score+=w[p]*points[row+indices[ce*15+p]];
    scores[t]=score;
}
extern "C" __global__ void configuration_means(
 const unsigned int* masks, const double* sums, const int* pos, const int* xi,
 const int* bench, int patterns, int candidates, int worlds, double* output) {
    int c=blockIdx.x*blockDim.x+threadIdx.x; if(c>=candidates) return;
    for (int world=0;world<worlds;++world) {
        double value=0;
        for (int k=0;k<patterns;++k) {
            int w[15]; multipliers(masks[k],pos,xi+c*11,bench+c*4,-1,-1,w);
            for(int p=0;p<15;++p) value+=w[p]*sums[(world*patterns+k)*15+p];
        }
        output[c*worlds+world]=value;
    }
}
"""


@lru_cache(maxsize=1)
def _kernels():
    cp = cupy_module()
    if cp is None:
        return None
    return cp.RawModule(code=CUDA_SOURCE)


def fused_score_candidates(candidates, player_ids, events, points, played, meta):
    """Exact per-path scores; GPU computes autosubs as well as point arithmetic."""
    from .tournament import _score_candidates_cpu

    cp = cupy_module()
    if cp is None:
        return _score_candidates_cpu(candidates, player_ids, events, points, played, meta)
    lookup = {p: i for i, p in enumerate(player_ids)}
    positions = {p: i for i, p in enumerate(("GK", "DEF", "MID", "FWD"))}
    indices, pos, xis, benches, captains, vices = [], [], [], [], [], []
    for candidate in candidates:
        for event in events:
            squad = list(candidate.get("planned_squads", {}).get(str(event), candidate["selected"]))
            local = {p: i for i, p in enumerate(squad)}
            lineup = candidate["lineups"][str(event)]
            indices.append([lookup[p] for p in squad])
            pos.append([positions[meta[p]["position"]] for p in squad])
            xis.append([local[p] for p in lineup["starters"]])
            benches.append([local[p] for p in lineup["bench_order"]])
            captains.append(local[lineup["captain"]])
            vices.append(local[lineup["vice_captain"]])
    shape = (len(points), len(candidates), len(events))
    out = cp.empty(shape, dtype=cp.int32)
    arrays = [cp.asarray(a, dtype=cp.int32) for a in (indices, pos, xis, benches, captains, vices)]
    _kernels().get_function("exact_scores")(
        ((out.size + 127) // 128,),
        (128,),
        (
            cp.asarray(points, dtype=cp.int32),
            cp.asarray(played, dtype=cp.uint8),
            *arrays,
            np.int32(shape[0]),
            np.int32(shape[1]),
            np.int32(shape[2]),
            np.int32(len(player_ids)),
            out,
        ),
    )
    result = cp.asnumpy(out)
    if result.min() < -32768 or result.max() > 32767:
        raise ValueError("Exact squad scores exceed int16 storage")
    return result.astype(np.int16)


def pareto_indices(values):
    """Exact 3-world non-dominated set, retaining one deterministic exact tie."""
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise ValueError("Configuration frontier requires three finite world means")
    order = np.lexsort((-values[:, 2], -values[:, 1], -values[:, 0]))
    keys, maxima, kept = [], [], []
    for i in order:
        _, second, third = values[i]
        at = bisect_right(keys, -second)
        if at and maxima[at - 1] >= third:
            continue
        kept.append(int(i))
        while at < len(keys) and maxima[at] <= third:
            del keys[at], maxima[at]
        keys.insert(at, -second)
        maxima.insert(at, third)
    return np.asarray(kept, dtype=np.int32)


def configuration_frontier(selected, event, worlds, rules, *, chip=None):
    """All legal configurations, pruned only by componentwise mean dominance.

    A discarded bench order or captain pair is no better in any model world;
    replacing it while holding the other choice fixed cannot worsen a monotone
    mean/regret objective. This pruning is NOT appropriate for CVaR objectives.
    """
    if len(worlds) != 3:
        raise ValueError("Configuration search requires three model worlds")
    selected = list(selected)
    if len(selected) != 15 or len(set(selected)) != 15:
        raise ValueError("Configuration search requires 15 distinct players")
    chip = ChipType(chip) if chip is not None else None
    captain_multiplier = 2 if chip == ChipType.TRIPLE_CAPTAIN else 1
    names = list(worlds)
    meta = worlds[names[0]]["player_meta"]
    local = {p: i for i, p in enumerate(selected)}
    positions = {p: i for i, p in enumerate(("GK", "DEF", "MID", "FWD"))}
    pos = np.asarray([positions[meta[p]["position"]] for p in selected], dtype=np.int32)
    xis = enumerate_legal_xis(selected, meta, rules)
    benches = [order for xi in xis for order in _bench_orders(selected, xi, meta)]
    xi_matrix = np.asarray([[local[p] for p in xi] for xi in xis for _ in range(6)], dtype=np.int32)
    bench_matrix = np.asarray([[local[p] for p in order] for order in benches], dtype=np.int32)
    pairs = list(permutations(selected, 2))
    pair_lookup = {pair: i for i, pair in enumerate(pairs)}
    bonuses = np.zeros((len(pairs), 3), dtype=np.float64)
    sampled, mask_arrays = [], []
    for w, name in enumerate(names):
        world = worlds[name]
        indices = {p: i for i, p in enumerate(world["player_ids"])}
        offset = world["events"].index(event)
        scores = world["points"][:, offset, [indices[p] for p in selected]].astype(np.float64)
        plays = world["played"][:, offset, [indices[p] for p in selected]]
        masks = plays.astype(np.uint32) @ (1 << np.arange(15, dtype=np.uint32))
        sampled.append((scores, plays))
        mask_arrays.append(masks)
        for i, (captain, vice) in enumerate(pairs):
            c, v = local[captain], local[vice]
            bonuses[i, w] = np.where(
                plays[:, c], scores[:, c], np.where(plays[:, v], scores[:, v], 0)
            ).sum()
    masks = np.unique(np.concatenate(mask_arrays))
    sums = np.zeros((3, len(masks), 15), dtype=np.float64)
    for w, (scores, _) in enumerate(sampled):
        # Integer totals are exactly representable here. Divide only AFTER
        # dominance pruning so summation noise cannot break mathematically tied
        # coordinates and manufacture a spurious frontier.
        np.add.at(sums[w], np.searchsorted(masks, mask_arrays[w]), scores)
    cp = cupy_module()
    if chip == ChipType.BENCH_BOOST:
        # Every appearing player scores, including negative returns. XI and
        # bench order still have to be legal; only the C/VC pair affects points.
        all_points = np.asarray([(scores * plays).sum() for scores, plays in sampled])
        means = np.tile(all_points, (len(benches), 1))
    elif cp is not None:
        gpu_means = cp.empty((len(benches), 3), dtype=cp.float64)
        _kernels().get_function("configuration_means")(
            ((len(benches) + 127) // 128,),
            (128,),
            (
                cp.asarray(masks),
                cp.asarray(sums),
                cp.asarray(pos),
                cp.asarray(xi_matrix),
                cp.asarray(bench_matrix),
                np.int32(len(masks)),
                np.int32(len(benches)),
                np.int32(3),
                gpu_means,
            ),
        )
        means = cp.asnumpy(gpu_means)
    else:
        from .tournament import _autosub_weights

        means = np.empty((len(benches), 3))
        for j, order in enumerate(benches):
            xi = xis[j // 6]
            candidate = {
                "selected": selected,
                "lineups": {
                    str(event): {
                        "starters": xi,
                        "bench_order": order,
                        "captain": xi[0],
                        "vice_captain": xi[1],
                    }
                },
            }
            weights = np.vstack([_autosub_weights(candidate, event, int(m), meta) for m in masks])
            c, v = local[xi[0]], local[xi[1]]
            weights[:, c] -= (masks & (1 << c)) != 0
            weights[:, v] -= ((masks & (1 << c)) == 0) & ((masks & (1 << v)) != 0)
            means[j] = np.einsum("wpj,pj->w", sums, weights)
    vectors, configurations = [], []
    for i, xi in enumerate(xis):
        bench_ids = pareto_indices(means[i * 6 : (i + 1) * 6]) + i * 6
        pair_ids = np.asarray([pair_lookup[p] for p in permutations(xi, 2)])
        pair_ids = pair_ids[pareto_indices(bonuses[pair_ids])]
        for bench_id in bench_ids:
            for pair_id in pair_ids:
                vectors.append(means[bench_id] + captain_multiplier * bonuses[pair_id])
                configurations.append((xi, benches[bench_id], *pairs[pair_id]))
    vectors = np.asarray(vectors)
    keep = pareto_indices(vectors)
    return {
        "means": vectors[keep] / np.asarray([len(scores) for scores, _ in sampled]),
        "configurations": [configurations[i] for i in keep],
        "world_names": names,
        "legal_xis": len(xis),
        "possible_configurations": len(xis) * 6 * 110,
        "bench_orders_scored": len(benches),
        "joint_after_factor_dominance": len(vectors),
        "frontier_size": len(keep),
        "appearance_patterns": len(masks),
        "backend": "cuda_exact_mask_sums" if cp is not None else "cpu_exact_mask_sums",
        "chip": chip.value if chip else None,
    }
