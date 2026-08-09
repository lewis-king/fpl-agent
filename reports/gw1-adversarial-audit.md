# 2026/27 GW1 picker adversarial audit

**Run:** 2 August 2026  
**Status:** accepted as the first shadow recommendation; must be refreshed before the 21 August
deadline.

## Evidence that passed

- The model-data gate passes all 13 checks over 244,425 historical rows and 4,472 live
  player/horizon rows. Lag reconstruction has zero mismatches and all 61,870 deadline-proxy player
  observations precede their inferred deadline.
- XGBoost 3.3.0 trained on `cuda:0` using the RTX 5090. The model artifact records the GPU, driver,
  feature contract and SHA-256 hash; no CPU fallback exists.
- Across 12 strict rolling position-season slices, `forecast_v2` beats five-match form on MAE in
  10, on top-shortlist return in all 12, and adds 0.428 actual points per shortlisted
  player/gameweek on average.
- The GW1-only shortlist wins 8/12 slices and adds 0.461 points per shortlisted player.
- Legal end-to-end historical GW1 squad replays score +0, +16 and +2 points versus form in
  2023/24–2025/26: +18 total, with no losing season in the three-season sample.
- The live squad retains 92% of its players across 20 model-error perturbations; Bruno Fernandes
  remains captain in 85% of them.
- The initial 15 is identical under 0.80, 0.88 and 0.95 per-week horizon decay. The best alternative
  changes only Verbruggen to Leno and trails by 0.026 objective points.

## Premium-recovery attack

The live model gives lower appearance probabilities to Saka and Haaland because both ended
2025/26 on zero minutes. A generic scenario—not a name-based override—was applied to available,
90th-percentile-owned midfielders/forwards priced at £9m or above after a 60+ day break. It raised:

- Saka from 3.496 to 3.879 GW1 xP;
- Isak from 1.745 to 2.810; and
- Haaland from 3.409 to 4.667.

The selected 15 and Bruno captaincy remained unchanged. Haaland's absence is therefore driven by
£15.5m opportunity cost as well as appearance probability; it is not a single fragile DNP
assumption.

## Behaviour to watch

The optimized GW1 XI is a 5-2-3. This is unusual historically but explainable: the only directly
comparable defensive-contribution season strongly rewards high-volume defenders, and 2026/27
retains two defensive-contribution points. It is an evidence-led hypothesis, not yet a proven
season-long edge.

The current squad is still a shadow pick because three important uncertainties remain:

1. defensive-contribution and 2026/27 BPS evidence is shallow;
2. Coventry City and Hull City have no Premier League prior in the ten-season corpus, while
   Ipswich Town's is stale; and
3. transfers, injuries, starting roles and prices can change materially before the deadline.

The collector, feature build, CUDA forecast and optimizer should be rerun at each material update
and at the planned T-72h, T-24h, T-6h, T-60m and T-10m checkpoints. The final deadline receipt must
supersede this one rather than relying on memory or manual hindsight.

## Correlated squad tournament

The follow-up [GW1–5 squad survival tournament](gw1-squad-tournament.md) generated 128 unique
legal constructions spanning premium and four bench-spend regimes. It ran 5,000 discovery paths
and independent 25,000-path holdouts with exact captain fallback and formation-valid autosubs.
Residual dispersion was selected on 2024/25 and checked forward on 2025/26; the nominal 80%
player-return interval covered 79.7% of 36,442 season-forward observations.

The current squad finished second in the fixed-squad holdout, 0.28 points behind the £21.0m-bench
static leader over five gameweeks, while retaining the better P10 and knockout-champion rate. When
all finalists received the same free-transfer planning envelope, the current squad led by 2.83
points over the fixed-squad leader and by at least 4.66 points over every tested Saka construction.
It therefore remains the shadow recommendation. This is evidence for the construction, not a
license to lock the four preseason transfer placeholders when new deadline information arrives.
