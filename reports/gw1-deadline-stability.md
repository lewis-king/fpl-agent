# GW1 multi-seed decision stability

Verdict: **STABLE**.

The leading 5 legal squads were rerun on 3 independent seeds with 25,000 worlds per seed.

## Production policy

| Seed | Winner | Selected rank | Selected regret to winner |
| ---: | --- | ---: | ---: |
| 20260911 | `R-01afc86b1b` | 1 | 0.000 |
| 20260912 | `R-01afc86b1b` | 1 | 0.000 |
| 20260913 | `R-01afc86b1b` | 1 | 0.000 |

## Gate

- PASS — at least three independent seeds
- PASS — candidate pool at least five
- PASS — selected candidate wins every production seed
- PASS — selected candidate within every weight grid tolerance

Maximum selected regret across the bounded weight grid: 0.000.

The published squad must win the production objective on every independent seed. Across the bounded objective-weight grid it may lose only while remaining within 0.25 synthesis-regret points of the seed-specific leader.
