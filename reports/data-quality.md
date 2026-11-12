# Model data quality gate

Status: **PASS** · generated 2026-11-12T17:29:42.955333+00:00

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
| current_player_horizon_grid | PASS | `{"players": 672, "rows": 3360, "first_event": 11, "last_event": 15, "event_count": 5}` | players x 5 contiguous events |
| current_required_fields | PASS | `0` | 0 missing |
| current_selectable_universe_exact | PASS | `{"official_selectable": 566, "official_actionable": 672, "modelled_players": 672, "missing_player_ids": [], "invalid_extra_player_ids": []}` | every selectable player plus legitimate transactable sale-only player appears exactly once per horizon |
| sale_only_players_zero_availability | PASS | `0` | 0 sale-only player-horizons with non-zero availability |
| adjusted_rating_unique_keys | PASS | `0` | 0 |
| adjusted_ratings_precede_kickoff | PASS | `0` | 0 late ratings |
| one_information_set_per_event | PASS | `0` | 0 events with mixed information cutoffs |
| current_adjusted_rating_coverage | PASS | `0` | 0 missing player-horizon ratings |
| adjusted_rating_probability_bounds | PASS | `0` | 0 invalid expectations |
| promoted_and_returning_club_priors | PASS | `0` | 0 entrant fixture-sides without a promoted prior |
| official_difficulty_excluded_from_challenger | PASS | `false` | false |
| ownership_scale | PASS | `{"min": 0.0, "max": 1.0}` | within [0,1] for every season |
| feature_allowlist_has_no_targets | PASS | `0` | 0 |
| selectable_position_pool | PASS | `{"DEF": 219, "GK": 75, "MID": 299, "FWD": 79}` | at least 2/5/5/3 |

## Legacy raw-form gaps (diagnostic only)

- Coventry City: prior gap `None` days; the production challenger replaces this gap with the validated opponent-adjusted promoted/returning-club prior.
- Hull City: prior gap `None` days; the production challenger replaces this gap with the validated opponent-adjusted promoted/returning-club prior.
- Ipswich Town: prior gap `545.0` days; the production challenger replaces this gap with the validated opponent-adjusted promoted/returning-club prior.
