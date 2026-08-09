# GW1 one-swap adversarial audit

**Verdict:** `supported_one_swap_requires_full_pipeline_replay`  
**Production changed:** no

Every legal one-player replacement is proxy-scored. The proxy shortlist receives direct-, robust- and component-optimized event lineups with exact simulated autosubs and captain fallback. This is an adversarial membership audit, not a replacement for the complete global squad-search funnel.

**Follow-up complete:** the Mukiele → Senesi challenger was forced through equal five-week robust,
eight-week horizon and synthesis fields. It ranked 2nd on the horizon but 27th on five-week
robustness; synthesis rejected it 1.498 to 0.906. Production remains unchanged. See the
[full-pipeline replay](gw1-one-swap-full-pipeline-replay.md).

## Preselected champion

- Change: Mukiele → Senesi
- Residual holdout: +2.396 [+2.347, +2.446]
- Component holdout: +2.283 [+2.156, +2.410]
- Cross-family support: True

## Search coverage

- Legal one-player replacements enumerated: 2,259
- Proxy shortlist squads: 516
- Selection configurations: 1,015
- Independent holdout finalists: 64

## Selection finalists

| Selection rank | Swap | Position | Bank | Residual delta | Component delta |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | Mukiele → Senesi | DEF | £0.5m | +2.396 [+2.347, +2.446] | +2.283 [+2.156, +2.410] |
| 2 | Mukiele → Guéhi | DEF | £0.5m | +1.702 [+1.649, +1.754] | +1.614 [+1.497, +1.732] |
| 3 | Collins → Senesi | DEF | £0.5m | +1.383 [+1.333, +1.432] | +1.333 [+1.211, +1.456] |
| 4 | Mukiele → Hill | DEF | £1.0m | +1.365 [+1.316, +1.414] | +1.277 [+1.152, +1.402] |
| 5 | Gibbs-White → Semenyo | MID | £0.5m | +1.294 [+1.245, +1.342] | +1.212 [+1.073, +1.350] |
| 6 | Maguire → Senesi | DEF | £0.0m | +1.149 [+1.098, +1.200] | +1.030 [+0.906, +1.154] |
| 7 | Mukiele → Virgil | DEF | £0.0m | +0.730 [+0.685, +0.776] | +0.759 [+0.639, +0.878] |
| 8 | Mukiele → Milenković | DEF | £1.0m | +0.744 [+0.698, +0.790] | +0.759 [+0.642, +0.875] |
| 9 | McAteer → Moisés Caicedo | MID | £0.0m | +0.742 [+0.716, +0.767] | +0.671 [+0.620, +0.722] |
| 10 | McAteer → Xhaka | MID | £0.0m | +0.640 [+0.620, +0.660] | +0.592 [+0.552, +0.631] |
| 11 | McAteer → Groß | MID | £0.0m | +0.505 [+0.488, +0.521] | +0.499 [+0.461, +0.536] |
| 12 | McAteer → Mac Allister | MID | £0.0m | +0.455 [+0.440, +0.470] | +0.477 [+0.448, +0.506] |
| 13 | McAteer → Tanaka | MID | £0.5m | +0.453 [+0.437, +0.468] | +0.423 [+0.397, +0.448] |
| 14 | McAteer → Lewis-Potter | MID | £0.0m | +0.442 [+0.427, +0.457] | +0.454 [+0.426, +0.482] |
| 15 | McAteer → Jensen | MID | £0.0m | +0.461 [+0.446, +0.477] | +0.444 [+0.417, +0.471] |
| 16 | McAteer → Bentancur | MID | £0.0m | +0.427 [+0.411, +0.442] | +0.407 [+0.380, +0.433] |
| 17 | McAteer → Ampadu | MID | £0.0m | +0.434 [+0.410, +0.458] | +0.396 [+0.342, +0.449] |
| 18 | Maguire → Guéhi | DEF | £0.0m | +0.420 [+0.368, +0.472] | +0.352 [+0.242, +0.462] |
| 19 | Collins → Hill | DEF | £1.0m | +0.346 [+0.298, +0.395] | +0.333 [+0.213, +0.453] |
| 20 | McAteer → Gallagher | MID | £0.0m | +0.359 [+0.344, +0.374] | +0.353 [+0.326, +0.380] |

## Replacement pressure by selected player

This is the best deterministic proxy replacement for each incumbent player, not a recommendation.

| Selected player | Best proxy replacement | Position | Global proxy rank |
| --- | --- | --- | ---: |
| Mukiele | Senesi | DEF | 1 |
| Maguire | Senesi | DEF | 2 |
| Collins | Senesi | DEF | 3 |
| Gibbs-White | Semenyo | MID | 10 |
| McAteer | Moisés Caicedo | MID | 11 |
| Truffert | Senesi | DEF | 14 |
| Calvert-Lewin | Richarlison | FWD | 183 |
| Verbruggen | Rushworth | GK | 189 |
| Tarkowski | Senesi | DEF | 254 |
| Mbeumo | Semenyo | MID | 255 |
| Szoboszlai | Enzo | MID | 496 |
| Igor Thiago | Richarlison | FWD | 713 |
| Donnarumma | Raya | GK | 721 |
| Watkins | Richarlison | FWD | 744 |
| Bruno Fernandes | Semenyo | MID | 2016 |

## Decision rule

This read-only audit cannot promote a swap. A non-incumbent must be preselected on the selection worlds and clear a paired 95% interval above zero in both independent holdout families. Even then, rerun the complete robust-search, horizon and synthesis pipeline with refreshed deadline evidence before changing production.
