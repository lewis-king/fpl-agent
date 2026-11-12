# FPLAgent state-of-the-art readiness audit

**Built:** 2026-08-19T16:59:13.941554+00:00
**Verdict:** `DEADLINE_GRADE_RESEARCH_SYSTEM_NOT_SOTA_PROVEN`  
**Current candidate:** `R-01afc86b1b`

## Claim boundary

- **Defensible:** The best-supported GW1 squad produced by FPLAgent under its current, checksum-bound evidence and declared risk policy.
- **Not defensible:** The objectively best possible squad in the world, or a forecast proven state of the art against every strong external system.

## Evidence gates

| Gate | Scope | State | Evidence |
|---|---|---|---|
| Independent of FPL's own xP | production | **PASS** | Neither ep_this, ep_next nor xP can enter the production feature allowlist. |
| Point-in-time data and leakage controls | production | **PASS** | 22 checks; 0 failures. |
| Player forecast beats the declared form baseline | production | **PASS** | MAE wins 11/12; top-k wins 11/12; mean top-k lift +0.512. |
| Exact legal GW1 replay | production | **PASS** | 3 seasons; model 2 wins, 1 ties, 0 losses; +18.0 points. |
| Global and local roster challenge | production | **PASS** | 537,804 legal candidates; 518,272 local two-swap; 256 distant MILP and 19,249 evolutionary squads. |
| Correlated simulation and exact FPL mechanics | production | **PASS** | Exact formation-valid autosubs, captain fallback, scoring-rule ablations and independent holdout paths passed; any supported GW1-only alternative was explicitly reconciled against the declared multiweek selector. |
| Transfer-aware multi-horizon policy | production | **PASS** | 53 finalists across GW1–3/5/8, decay sensitivity, fixed/open/rolled-GW2 policies. |
| Bookmaker market is validated and bounded | production | **PASS** | Betfair 1X2/O2.5 covers 10/10 GW1 fixtures; 20% DEF blend and 5% FWD goal-environment blend over 64 forwards; MID and weekly authority remain zero. |
| Current decision is lineage-locked and publishable | production | **PASS** | Verdict DEADLINE_READY; 18 declared gates. |
| Human reports match machine artifacts | production | **PASS** | Canonical robust and horizon reports contain the active candidate IDs and timestamps. |
| Independent event-data enrichment | research frontier | **PARTIAL** | SofaScore, Understat is current and has time-forward replay, but the independent signals have not yet earned positive legal-policy lift. |
| Strong external forecast benchmark | research frontier | **PASS** | FPLAgent MAE 0.978 vs OpenFPL-method 0.993; OpenFPL legal-policy delta -69.0. |
| Untouched prospective 2026/27 evidence | research frontier | **NOT_READY** | 0 final events; six trigger diagnosis and 19 are required for the first SOTA evidence gate. |
| Predicted-lineup consensus is prospectively validated | research frontier | **NOT_READY** | 0 qualifying events; current consensus has bounded provisional rule-based authority, but has not earned a prospective calibration claim. |
| Forecast tails are time-forward calibrated | research frontier | **NOT_READY** | 0 events; CRPS, p10/p90, captain and bench tails remain shadow until every gate passes. |
| Price and affordability policy wins net points | research frontier | **NOT_READY** | 0 price nights; 0 prospective timing decisions. |

## Priority gaps

### 1. Independent player-event data

Reduces dependence on one event-data ontology and improves chance/role signals.

**Promotion rule:** Two live sources, stable player mapping, point-in-time folds, and legal-policy lift.

### 2. Matched external benchmark

Internal baselines cannot establish a state-of-the-art claim.

**Promotion rule:** Reproduce OpenFPL or another strong public model on identical folds and decisions.

### 3. Prospective 2026/27 scoring

New BPS/defensive-contribution rules and live behaviours need untouched outcomes.

**Promotion rule:** Six events for diagnosis; a materially larger sample before any SOTA claim.

### 4. Predicted-lineup calibration

Watkins-like role uncertainty is currently modelled conservatively but not source-authoritative.

**Promotion rule:** Two-source consensus must beat the champion prospectively on role and legal decisions.

### 5. Full distribution calibration

Mean xP and policy replay do not alone prove that p10/p90/CVaR tails are calibrated.

**Promotion rule:** Add time-forward CRPS, interval coverage and captain/bench tail calibration by position.

### 6. Future price and liquidity scenarios

The horizon models points and transfer hits, but not probabilistic price moves or forced affordability loss.

**Promotion rule:** Replay timestamp-safe price forecasts and promote only on net points, not team value alone.

## Interpretation

This audit intentionally has no blended readiness percentage. A high average can hide one fatal weakness. Production publication requires every production gate; a SOTA claim additionally requires every research-frontier gate.
