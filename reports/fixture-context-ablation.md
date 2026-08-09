# Fixture-context champion/challenger

All variants use the same rolling seasons, position models, targets and CUDA training. Only the feature contract changes. The full challenger does not consume FPL's official team-strength ratings.

| Variant | Features | MAE | Rank | Top-k actual | GW1 top-k | Legal GW1 total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| player_only | 28 | 0.9780 | 0.6964 | 3.984 | 3.955 | 111.0 |
| legacy_official_raw | 41 | 0.9452 | 0.6968 | 4.098 | 3.748 | 138.0 |
| opponent_adjusted | 40 | 0.9457 | 0.6974 | 4.158 | 3.891 | 121.0 |
| opponent_adjusted_home_away | 47 | 0.9467 | 0.6974 | 4.200 | 3.816 | 137.0 |

## Preregistered promotion gate

Result: **PASS**

- PASS — mae not worse by more than 0 01
- PASS — rank not worse by more than 0 002
- PASS — mean top k improves
- PASS — top k slice wins at least half
- PASS — passed

The three-season legal GW1 replay is reported as a high-variance diagnostic and is deliberately not a promotion condition.
