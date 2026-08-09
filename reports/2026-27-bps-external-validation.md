# 2026/27 BPS external validation

**Built:** 2026-08-07T13:40:38.335480+00:00  
**Authority:** third_party_advisory  
**Evidence gate:** PASS  
**Production change:** none_advisory_validation_only

## Result

All 537 published player rows and 440 unique changed player-fixtures map to the local 2025/26 reconstruction.

The current proxy has player-season MAE **0.535**, versus **0.693** for no rules correction and **0.752** for a position-only correction. Its rank correlation with the external deltas is **0.625**.

| Position | External delta | Deduplicated delta | Model mean delta |
| --- | ---: | ---: | ---: |
| GK | +1 | +1 | -34.98 |
| DEF | -77 | -77 | -41.85 |
| MID | +53 | +53 | +56.89 |
| FWD | +15 | +14 | +9.62 |

## Source integrity finding

The page contains 441 movement rows but only 440 unique player-fixtures. The duplicate is the Junior Kroupi GW9 fixture, so the source is valuable corroborating evidence but is not accepted as an exact production label set.

## Decision

Retain the current shrunk outfield correction prior. It is independently directionally corroborated and beats simpler reconstruction baselines, but this audit does not promote the third-party table or claim an exact live Opta BPS engine. Goalkeeper correction remains neutral in production until complete, reliable save-context evidence is available.

## Limitations

- The benchmark is third-party research rather than an official Opta event feed.
- Its big-chance-save labels are reconstructed and calibrated, not complete Opta labels.
- The current source contains a duplicated Junior Kroupi player-fixture movement.
- Same-season reconstruction agreement is not a forward test of 2026/27 bonus outcomes.

Source: https://fpl.red/bonus
