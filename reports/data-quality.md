# Model data quality gate

Status: **PASS** · generated 2026-08-15T16:53:46.193403+00:00

| Check | Result | Value | Expectation |
| --- | --- | --- | --- |
| historical_row_volume | PASS | `244425` | >=200000 |
| historical_unique_keys | PASS | `0` | 0 |
| historical_player_identity | PASS | `0` | 0 null codes |
| last_points_strictly_lagged | PASS | `0` | 0 mismatches |
| form5_excludes_target_event | PASS | `0` | 0 mismatches |
| snapshots_precede_deadlines | PASS | `0` | 0 late snapshots |
| attacking_history_live_parity | PASS | `[]` | all long-horizon attacking columns in historical and current matrices |
| unavailable_xg_remains_missing | PASS | `0` | 0 synthetic pre-2022/23 values |
| current_unique_keys | PASS | `0` | 0 |
| current_player_horizon_grid | PASS | `{"players": 568, "rows": 4544, "horizon": 8}` | players x 8 |
| current_required_fields | PASS | `0` | 0 missing |
| current_selectable_universe_exact | PASS | `{"official_selectable": 568, "modelled_players": 568, "missing_player_ids": [], "extra_player_ids": []}` | every currently selectable official player appears exactly once per horizon |
| adjusted_rating_unique_keys | PASS | `0` | 0 |
| adjusted_ratings_precede_kickoff | PASS | `0` | 0 late ratings |
| one_information_set_per_event | PASS | `0` | 0 events with mixed information cutoffs |
| current_adjusted_rating_coverage | PASS | `0` | 0 missing player-horizon ratings |
| adjusted_rating_probability_bounds | PASS | `0` | 0 invalid expectations |
| promoted_and_returning_club_priors | PASS | `0` | 0 entrant fixture-sides without a promoted prior |
| official_difficulty_excluded_from_challenger | PASS | `false` | false |
| ownership_scale | PASS | `{"min": 0.0, "max": 1.0}` | within [0,1] for every season |
| feature_allowlist_has_no_targets | PASS | `0` | 0 |
| selectable_position_pool | PASS | `{"MID": 254, "GK": 61, "DEF": 187, "FWD": 66}` | at least 2/5/5/3 |

## Legacy raw-form gaps (diagnostic only)

- Coventry City: prior gap `None` days; the production challenger replaces this gap with the validated opponent-adjusted promoted/returning-club prior.
- Hull City: prior gap `None` days; the production challenger replaces this gap with the validated opponent-adjusted promoted/returning-club prior.
- Ipswich Town: prior gap `454.0` days; the production challenger replaces this gap with the validated opponent-adjusted promoted/returning-club prior.
