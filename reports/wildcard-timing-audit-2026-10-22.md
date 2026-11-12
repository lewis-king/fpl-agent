# GW8 Wildcard timing audit — 22 October 2026

## Decision

The published −4 recommendation is **not proven superior to Wildcard now**. The existing chip
authority gate had conflated "not approved" with a practical recommendation to retain. The app
and CLI now flag a positive but unvalidated chip alternative as an unresolved decision.

The new timing evaluator is implemented and tested, but **not promoted as an automatic policy**.
It finds an attractive live Wildcard, yet its two recent-season development comparisons do not
establish better actual results. No FPL account changes or LLM work were performed.

## Frozen live experiment

Source: published GW8 decision and 22 October 14:21 UTC official forecast snapshot. Exact
manager selling prices, £0.5m bank and one FT are retained. No extra budget, free transfer or chip
is invented. The published route is N. Williams → Gabriel and Semenyo → Le Fée, costing four
points. Comparison is through GW19, with fresh legal transfer searches at each simulated deadline.

88 candidate paths cover every later Wildcard date, the roll/free/paid/published roots and explicit
United alternatives. Initial timing decisions use 10,000 samples; 20,000 separately seeded
samples evaluate those frozen decisions. Future calendar selection is not repeated on validation.

| First decision | Best later WC date within this experiment | Net projected gain vs published −4 then WC9 |
|---|---:|---:|
| Published −4 | GW9 | 0.00 |
| Semenyo → Rogers, free | GW9 | +2.21 |
| Roll | GW9 | +0.56 |
| WC now, Bruno and Mbeumo included | GW8 | +7.22 |
| WC now, Bruno included / Mbeumo excluded | GW8 | +7.27 |
| WC now, Mbeumo included / Bruno excluded | GW8 | +3.77 |
| WC now, neither included | GW8 | +5.31 |

The both-included WC was selected before opening validation. The Bruno-only WC's tiny validation
edge is **not** a reason to reselect on the holdout. These inclusion constraints apply to the
current squad, not a requirement to keep or exclude those players forever.

Adding Bench Boost and Triple Captain date selection, conditional on each saved transfer path,
leaves the same selection: WC now +7.59 versus the published root; the free-transfer alternative
is +2.30. This comparison uses separate seeds from the no-team-chip ablation. It does not jointly
optimise transfers made to prepare for BB/TC, and does not optimise Free Hit timing.

The +7.59 estimate has Monte Carlo mean bounds +7.30 to +7.87 but an actual simulated outcome-
difference p10–p90 of **−19 to +34**. Those narrow mean bounds are NOT a guarantee of gaining
points and exclude model error. The probability of beating the reference within this model is
about 63%, not a calibrated real-world probability.

### Follow-up: first transfers anticipate the Wildcard

The original comparison kept each first move fixed while varying its later Wildcard date.
A follow-up regenerates ordinary first moves for the actual bridge to that Wildcard: WC9 means
buying for GW8, not assuming a five-week stay. The exact published route remains the comparator.
This uses fresh 10k/20k draw seeds and a separately saved `wc-aware-roots` receipt.

- Free Semenyo → Rogers then WC9: **+2.41** versus the published −4 then WC9.
- Best regenerated two-transfer bridge: **+1.06**, still behind the free route.
- Selected WC now, Bruno included and Mbeumo excluded: **+7.47** versus the published route,
  approximately **+5.06** versus the free-transfer route.

The two leading Wildcard structures are close; their selection changes between independently
seeded runs. Treat the case for considering WC now separately from certainty about Mbeumo's
inclusion. The broader first-move pool has not had its own matched historical promotion replay.
It remains research, not a replacement production recommendation.

## Historical challenge

Both arms share a common GW1–7 policy. At GW8, pick WC now or a later date from origin-only
forecasts and prefix-fitted residual calibration. Subsequently replan with the real forecast,
price and fixture information available at each deadline; score actual GW8–19 net points.

| Development season | WC now | Later WC | Now minus later | Later date selected before outcomes |
|---|---:|---:|---:|---:|
| 2024/25 | 695 | 695 | 0 | GW12 |
| 2025/26 | 680 | 714 | −34 | GW9 |

The frozen simulation preferred WC now by approximately 3.49 and 3.56 points respectively.
That advantage did not translate into better realised results. This exposes the limitation of
frozen-information rollouts: they can misvalue waiting for new information. Two paths do not
prove a universal benefit to waiting, nor validate a blanket "never Wildcard" policy.

These are reused development seasons, not untouched policy-validation data. Original-season
scoring is retained; current chip/FT rules are applied counterfactually. Six explicit blank-
holding repairs were required in 2024/25; none in 2025/26. They are recorded in the ledger.

## United and future-news sensitivity

Reducing all United players' point forecasts by 20% from GW8, with the same appearance
probabilities, changes the best tested Wildcard from both players included to **neither**.
That route is +8.99 model points versus the same published-root comparison in that stress case.
The both-included Wildcard's advantage falls to +1.00. This is a sensitivity test, not evidence
that United will underperform by 20%, and not a fitted probability of either scenario.

An additional news experiment introduces that reduction only at GW10. The original root actions
and WC dates must remain frozen before the news: choosing the best root retrospectively for
that particular future scenario would be clairvoyance. `audit_wildcard_news.py` verifies identical
pre-news actions and scores the origin-selected WC8 policy against the origin-selected published
root with WC9. Their difference under this one news path is +8.41 model points. This tests
non-anticipating execution, **not** the calibrated option value of all future news. Ignore the
scenario run's conditional/oracle `selected_group` as a live recommendation.

The initial auxiliary news summary mistakenly indexed a score-sorted metric list by input order.
Validation caught that reporting error; the corrected script matches by action ID. The invalid
zero-gain summary is retained under `origin-frozen-news-check-invalid-index.json`, not as evidence.
It did not affect the main baseline, stress or historical results, which use ordered score arrays.

## Interpretation and remaining work

1. Do not treat the published hit as a settled optimum while a credible chip route is unresolved.
2. Learn and validate the value of future forecast/role changes, instead of assuming frozen
   ability or adding a generic retained-chip constant. A hand-chosen stress is not calibration.
3. Add Free Hit and chip-preparation transfer interactions; test multiple origins and manager
   states, not just one origin per season. Preserve legal half expiry and future information limits.
4. Validate longer-range forecasts, availability recovery, price changes and fixture moves;
   GW13–19 currently extrapolates frozen ability from GW8–12. Future bookmaker lines are not known.
   That research-only extension fits venue/official fixture-difficulty response, not a fresh
   production team-strength model. It does not use `ep_next`.
5. Replicate across the production simulation families and preserve an independent forward
   evaluation before granting automatic WC/FH authority. Do not tune thresholds on these results.

## Reproducibility

- Implementation/run commands: `docs/chip-strategy-v2.md`, adaptive timing section.
- Baseline: `data/research/wildcard-timing-20261022-baseline/{inputs,paths,results}.json`.
- WC-aware first moves: `data/research/wildcard-timing-20261022-wc-aware-roots/{inputs,paths,results}.json`.
- Team chips: the same directory's `team-chips-results.json` and `team-chips-ledgers.json`.
- Historical: `data/research/wildcard-timing-20261022-historical/results.json`.
- United current-forecast stress: `data/research/wildcard-timing-20261022-united-down20/`.
- Future-news stress revealed only at GW10: `data/research/wildcard-timing-20261022-news-gw10/`.

Directories contain private frozen manager inputs and generated research artifacts; do not commit
them indiscriminately. Source code, tests and this report are the durable implementation record.

## Verification

136 targeted engine/API/CLI tests passed, plus six frontend state tests. TypeScript/Vite build
passed. Browser QA mocked every browser API request, tested compatibility with the running older
API, verified the unresolved warning is expanded and visible, and checked mobile overflow and
browser errors. The mobile screenshot was visually reviewed. No live browser refresh or account
write was triggered by the browser test. The published decision ID remains `A-ba2087c85b-2`.
