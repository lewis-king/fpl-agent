# Points-first deployment decisions — 9 September 2026

This review **concludes** the go/no-go decision for each current experiment. It supersedes the
deployment-status wording in the [round-two report](points-first-validation-round2-2026-09-09.md),
not that report's preserved experimental evidence. Rejected versions are not in a queue to become
live automatically. They can collect frozen measurements without changing a recommendation.

The objective remains season-long **net points**, not price appreciation, an exciting transfer,
or the number of new algorithms enabled. Tests establish software behaviour; simulated estimates
and small historical comparisons do not establish a world-leading FPL policy.

## Release decisions

| Item | Decision for this release | Evidence and reasoning |
| --- | --- | --- |
| Strongest admissible selection | **Promote** | Retain the safe-runner-up correction and fix the additional inadmissible-reference defect below. These are testable selection-contract corrections, not fitted player preferences. |
| Held-squad club overflow | **Promote** | Existing authenticated/witnessed overflow can be held, must be repaired on the next fantasy transfer, and returns after FH. Regression tests and the 76-event state audit pass. New squad limits stay strict. |
| Existing calibrated Bench Boost / Triple Captain policy | **Keep live** | `chip_strategy_v2` passes its expanding-window gate. Actual chip uplift is 34/17 in the two forward seasons versus 17/21 for the forecast-selected comparators. This is limited evidence, not proof of globally optimal chip timing. |
| Full-pool prospective capture and scoring | **Promote** | Preserve every current player forecast and exact alternative; score only verified outcomes, with missingness explicit. Capture is necessary to measure future improvement honestly. |
| Deterministic next-deadline continuation v1 | **Reject** | Its paired ten-event paths gained 58 points in 2024/25 but lost 2 in 2025/26. That fails the predeclared positive-both-folds screen. The zero-terminal-FT screening ablation is not a full production-policy replay. |
| Shared-world two-deadline continuation v1 | **Reject** | This is a different variant, not directly tested by the +58/−2 result. It has no matched sequential net-points evidence, only a restricted first-action set, and unvalidated future-hit and price/news assumptions. Its current preference for rolling does not justify activation. |
| New joint Wildcard / Free Hit timing | **Reject** | Playing all 16 chips across two full historical seasons verifies legal state/scoring transitions. An imposed test calendar without a matched control does not validate timing or retained chip value. |
| Role-change challenger v1 | **Reject** | 83,243 player-events, forward fits and fixed comparisons. Latest decision-focus log loss is 0.300656 versus champion 0.300581. The fixed screen fails despite slightly better Brier score; no post-hoc relaxation. |
| Seven-family allocation/candidate-access package v1 | **Reject** | Current selection simulations are reused to propose and compare candidates; no independent or matched historical policy lift. More candidates and a changed minimax winner are not evidence of a better points-producing policy. No compulsory cheap/expensive bench rule ships. |
| Retune risk weight | **Reject** | Weights 0/0.10/0.25/0.50 all produce 133 net points in the frozen GW2/GW3 selector audit. Two previously examined events cannot identify a season-optimal coefficient. Retain 0.25, without claiming it is proven optimal. |

BB/TC authority comes from **`data/model/chip_strategy_v2/retained-value.json`**, not the older
`team_chip_replay_v1/results.json`, which still reports a failed shadow policy. These are different
experiments. Keeping the eligible BB/TC policy does not grant authority to the older failed one.

The new `policy_release.py` module records these decisions in each published receipt. Rejected
diagnostics must explicitly have `decision_authority: false`; an attempt to self-promote fails
closed. This release also refuses operational WC/FH timing recommendations. Existing per-event
chip gates still decide whether an eligible BB/TC should actually be played. Measurement-ready and
deployment-approved are separate concepts.

## Additional defect found and fixed: the risk benchmark

Previously we checked every action's safety gates, but ranked the passing actions using regret
benchmarks set by **all** candidates, including those we would refuse to play. An extreme forecast
in one failed candidate could therefore reverse the choice between two unchanged safe transfers.

The regression reproduces this without using any real player's identity:

| Candidate | World 1 gain | World 2 gain | Gate |
| --- | ---: | ---: | --- |
| Roll | 0 | 0 | Pass |
| Safe A | 7 | 1 | Pass |
| Safe B | 3 | 4 | Pass |
| Rejected C | 1 | 100 | Fail: central uncertainty |

At equal world weights and the unchanged 0.25 risk coefficient, A wins without C, but B used to
win merely when rejected C was added. The test failed before the change and passes after it.

The corrected selector evaluates the existing gates first, computes each world's best mean among
**admissible** actions, and ranks that admissible set. No xP forecast, risk coefficient, incoming
role threshold or hit threshold changes. `ranking` retains the original unfiltered diagnostic
ordering for compatibility; `admissible_ranking` is the authoritative selection ordering.
`selection_audit` states which reference is used and whether it changed the selection.

This does **not** eliminate legitimate minimax dependence on additional *admissible* alternatives.
In particular, the earlier expanded-pool Gonzalo result must not be automatically blamed on this
bug: the excluded-reference defect and ordinary candidate-set sensitivity are distinct issues.

Synthesis receipts now use `weekly_decision_synthesis_v4`. Prospective scoring and mini-league
diagnostics accept both v3 and v4; old archives are neither rewritten nor backfilled.

## Merit checks and limits

- Fail-before/pass-after invariance test for adding an inadmissible candidate.
- Existing paid-hit, incoming-role, roll, runner-up, chip, manager-state and publication tests.
- Frozen GW2/GW3 candidates, exact legal reconstructed actions and verified final outcomes:
  **90 + 43 = 133 net points**, unchanged from the preceding corrected selector at all four risk
  weights. These are selector counterfactuals, not an assertion that the user played those actions.
- The saved pre-release GW4 receipt still selects **Richarlison → Evanilson** after re-selection.
- New release-authority tests reject true, missing and malformed authority on rejected experiments,
  retain measurement payloads, and do not disable the eligible BB/TC policy.

No measured points gain is attributed to the additional benchmark fix. Its merit is removal of a
demonstrable contract defect, with no change to the checked real-data decisions. Regression tests
cannot establish future football performance, and a narrow Monte Carlo confidence interval is not
a range of possible actual scores.

Reproduction:

```bash
.venv/bin/pytest -q tests --ignore-glob='tests/test_llm*' \
  --ignore=tests/test_web_chat.py --ignore=tests/test_web_uploads.py

# Choose a new output directory; existing evidence must not be overwritten.
.venv/bin/python scripts/replay_risk_weights.py --output data/research/policy-review-new
```

The completed post-fix replay is in
`data/research/policy-release-20260909-selector/results.json`. Its source receipt hashes identify
the frozen GW2/GW3 evidence. Original chronological research receipts remain at the paths documented
in the round-two report.

## Next iteration, in impact order

1. Build a genuinely matched sequential test for a **new** adaptive-policy version, including
   prefix-trained simulation/FT calibration, equally treated candidate bounds, actual deadline
   affordability and a fixed comparison protocol. Do not pass today's all-history calibrations
   into an old deadline. Do not tune until the old two folds happen to win.
2. Extend that validated stateful comparator to WC permanence/FH restoration and retained chip
   inventory. A positive raw chip uplift is not a reason to spend an option worth more later.
3. Score the already frozen 2026/27 forecasts and alternatives as games finish, separating role,
   forecast and action errors. Reconsider a rejected version only through a fresh explicit review.

The current versions above have a completed deployment decision. These successor research tasks
are not silently advertised as finished, and nothing here establishes SOTA or guarantees league wins.

## Live refresh and browser handoff

The normal app-triggered refresh **published at 14:22:21 BST**, completing all five stages in
**166.48 seconds**. The authenticated manager was synced immediately before it. Nothing was written
to the user's FPL account, and no LLM training or inference was involved.

- Move: **Richarlison → Evanilson**, one free transfer, no hit, £0.0m bank after the move.
- Captain: **Bruno Fernandes**. Vice-captain: **Szoboszlai**. Chip: **no chip**.
- Projected GW4 score: **53.87**, including captaincy. Weighted GW4–8 gain over optimized rolling:
  **+2.1759**; weakest model-world gain **+1.0225**.
- The current FPL setup displays 51.24, so the UI's **+2.63 current-event** difference includes
  lineup/captain changes as well as the transfer. It is not the five-week +2.1759 comparison.
- XI: Verbruggen; Truffert, Tarkowski, António Silva; Bruno, Szoboszlai, Semenyo, Gibbs-White;
  Evanilson, Igor Thiago, Calvert-Lewin. Outfield bench: Mbeumo, N. Williams, Maguire. Reserve GK:
  Donnarumma. One free transfer is available next deadline on this route.
- The new receipt contains all concluded release decisions. All four research diagnostics are
  measurement-ready but explicitly deployment-rejected with zero authority.
- The fresh expanded candidate pool now also selects Evanilson at risk weights 0.25 and 0.50;
  lower weights still prefer Maguire → Muharemović. Shared-world continuation still prefers rolling.
  Market inputs changed too, so the previous Gonzalo disagreement disappearing is **not** attributed
  solely to the selector fix without a same-input expanded-pool ablation.
- Ready market events on this capture are **GW4 only**; later events use the existing internal
  fallback. Do not carry forward the earlier report's GW4/GW5 market-coverage claim. Execution-time
  price advice remains unavailable when its telemetry postdates the frozen decision timestamp;
  this does not authorize an immediate transfer or block the ordinary weekly recommendation.

Validation: **653 non-LLM Python tests**, six frontend tests, targeted Python lint, frontend
build/lint, and both browser scripts pass. Browser scripts read the live workspace and mock API
mutations; the separate real sync/refresh above completed successfully. The live API's recommended
squad/action ID and 53.87 score match the immutable published receipt. The build retains its existing
large-JavaScript-chunk warning; Python reports the existing Starlette/httpx deprecation warning.

Persistence/provenance:

| Field | Value |
| --- | --- |
| Refresh | `refresh-v1-a2d9195f205c649d` |
| Selected action | `A-5329ac8f23-1` |
| Input fingerprint | `b3185e1e146a86ed53d5aaf09879ff652ebc6a2fdc28506c6f4b4b4b91543ec0` |
| Active/archive SHA256 | `34304a28c407c39826a476bcd740223ba336772402851624fd4b20e614a4d2b2` |
| Engine implementation SHA256 | `c7b9593b8f9652e488211864c50e8d201f7d594e67867c635a98d428228fbd96` |
| Pipeline manifest SHA256 | `a8ef595b74e4c114899a8d542017a1b3af7738a726fca3919ae16a5f0769ed54` |

Active: `data/decisions/2026-27-weekly-current.json`.
Archive: `data/decisions/weekly/event-4/b3185e1e146a86ed53d5aaf09879ff652ebc6a2fdc28506c6f4b4b4b91543ec0.json`.
The files were verified byte-identical, and the recorded engine hash matches the current code.

Services: frontend **http://localhost:5173**, API **127.0.0.1:8000** (PID 493127, execution session
55531), authenticated MCP **8021**, MCP login service **8020**. Select **Recommended squad**;
“Your FPL squad” remains your actual synced team. Next routine refresh is 20:22 BST, unless material
evidence or a manual request triggers an earlier one. No commits or pushes were made.
