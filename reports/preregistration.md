# Pre-registration: removing the CVC field from checkout

Experiment `exp_remove_cvc`. Frozen at git tag `prereg-v1` together with the machine-readable version, [config/prereg.yaml](../config/prereg.yaml), which is what the analysis code reads. Power calculations are reproduced in [power_analysis.md](power_analysis.md). Any deviation from this plan will be logged, with its reason, in `reports/deviations.md`. This file will not be edited after the tag (a test enforces that).

## 1. Read this first: what this pre-registration can and cannot show

The author designed the simulation that produced the data and wrote the effects planted in it. Blindness to the true effects is therefore impossible. This document demonstrates process discipline: a primary metric, estimators, margins, and decision rules fixed in writing before any treatment versus control comparison is run on the final assignment, with every earlier look disclosed below. It does not demonstrate that the analyst was ignorant of the answer. In a real experiment, the same document would be written before launch.

It is also written after the data exist (the generator produces the whole experiment at once), so "pre" means before the analysis of outcomes by arm, not before data collection.

### Disclosed looks at the data

| When | What was seen | Assignment |
|---|---|---|
| Phase 1, generator calibration | In-window rates by arm: conversion 0.5116 control vs 0.5250 treatment (+2.6% relative), attempt rate, authorization 0.9189 vs 0.9141 (-0.48pp), dispute rate 0.00339 vs 0.00487 (+44% relative). The generator log also prints its calibrated dispute lift by hidden risk tier. | Salt v1, later discarded |
| Phase 1, A/A diagnosis | Pre-period conversion by arm under v1 and many placebo salts. Hidden-trait balance under v1 and v2. | v1 and v2 (pre-period only) |
| Phase 3, semantic layer | Pooled (both arms) weekly KPIs; pooled in-window dispute rate 0.41% matured vs 0.18% observable at experiment end; pre-period metrics by arm under v2. | v2, pooled or pre-period only |
| Phase 4, this document | Pre-period outcomes pooled across arms; in-window session counts (traffic, not outcomes). | v2, no arm split |

The Phase 1 numbers came from an assignment that no longer exists, but they were close to the planted effects, so they are disclosed. The MDE, margins, and thresholds below are set from pre-period baselines and business assumptions only, never from those numbers. No in-window treatment versus control comparison has been run on the v2 assignment.

## 2. Hypothesis

Removing the CVC field reduces checkout friction, so more sessions end in a successful payment. Without CVC, fraudsters with stolen card numbers face one fewer barrier and some issuers decline more card-not-present charges, so disputes may rise and authorization may fall.

- H1 (primary): checkout conversion (session to captured charge) is higher in treatment.
- Guardrails: the dispute rate does not rise by more than the break-even margin; authorization and revenue per transaction do not fall by more than their margins.

## 3. Design

| Item | Value |
|---|---|
| Randomization | Customer level, sha256 hash of salt and customer id, 50/50 |
| Analysis population | Exposed customers only (at least one in-window checkout session, `dim_experiment.is_exposed`) |
| Experiment window | 2026-06-01 to 2026-07-26 (8 weeks) |
| Readout date | 2026-09-25: experiment end plus the 60-day dispute maturity window |
| SRM check | Chi-square on exposed customers per arm; p < 0.001 stops the analysis |
| Alpha | 0.05 two-sided for the primary; 0.025 one-sided for every non-inferiority and segment value test |

### Re-randomization before launch

The first salt (`exp_remove_cvc_v1`) failed a pre-experiment A/A check on historical data: pre-period conversion differed between arms by -0.77pp, a customer-clustered z of -4.18. Three checks ruled out a bug:

1. **The standard error is right.** Re-bucketing the same customers under 300 placebo salts gave clustered z-scores with mean +0.02 and standard deviation 1.00, none beyond 3.
2. **No leak.** Regenerating with every customer forced into control produced bit-identical pre-period outcomes, so pre-period data cannot depend on assignment.
3. **No systematic hash correlation.** Across 200 generator seeds, the balance z of hidden customer traits under the same salt had mean about 0 and standard deviation about 1. Salt v1 had simply drawn two hidden traits about 2.5 standard errors apart in the same direction.

The assignment was re-salted with a rule fixed before any candidate was evaluated: take the first of `v2, v3, ...` whose pre-period conversion |z| is below 2 and whose observable covariates all have chi-square p above 0.05. `exp_remove_cvc_v2` was the first to pass (z = +0.82). This follows the practice of running A/A checks on historical data to choose a balanced hash seed (Kohavi, Tang & Xu, *Trustworthy Online Controlled Experiments*, 2020). Selecting among assignments by a balance criterion makes standard confidence intervals slightly conservative (Morgan & Rubin, 2012), never anti-conservative, so the analysis below does not adjust for it.

**Account age disclosure.** The rule was applied with account age measured at experiment start (Phase 1 definition). The dbt marts later defined it at first exposure, which is more correct. Under the dbt definition the v2 account-age balance test gives p = 0.012 (0 to 90 day accounts: 3.26% of control, 3.52% of treatment), which would fail the 0.05 threshold. With five covariates, a minimum p-value at or below 0.012 occurs about 6% of the time by chance, and re-salting after seeing more balance statistics would be a forking-paths choice, so v2 is kept. Regression adjustment for account age band is pre-registered below as a robustness analysis.

## 4. Metrics and estimators

All metrics are ratios of sums over sessions or charges, while randomization is by customer, so every estimator aggregates to the customer and uses the delta method (Deng, Knoblich & Lu, 2018). Lifts are reported as absolute differences and as relative lifts with delta-method confidence intervals.

| Role | Metric | Estimator | Window |
|---|---|---|---|
| **Primary** | Checkout conversion | Unadjusted delta-method difference, two-sided | Full (weeks 1 to 8) |
| Secondary: variance reduction | Checkout conversion | CUPED on the linearized ratio, covariate = pre-period conversion (Deng, Xu, Kohavi & Walker, 2013) | Full |
| Secondary: robustness | Checkout conversion | Regression adjustment for account age band on the linearized ratio | Full |
| Secondary: novelty sensitivity | Checkout conversion | Delta-method difference | Weeks 3 to 8 |
| Diagnostic | Checkout conversion | Naive two-proportion test, to show how much it understates the CI width | Full |
| Descriptive | Checkout conversion | Delta-method lift by experiment week | Each week |

Secondary analyses are reported next to the primary and cannot replace it. CUPED is framed as variance reduction: the v2 pre-period gap is small (+0.15pp, z = +0.82), so it is not correcting an imbalance. New customers have no pre-period history; their covariate is zero after linearization.

## 5. Power and duration

Inputs: pre-period outcomes pooled across both arms and in-window session counts. Baseline conversion is 0.5259. The MDE is a 1.0% relative lift (0.526pp): the smallest lift worth a rollout given the fixed cost of engineering and a risk review, worth about $0.93M a year under the assumptions in section 6.

Clustering inflates the variance by a design effect DE = 1 + rho(m_eff - 1), where m_eff = sum(n_i^2) / sum(n_i) is the session-weighted number of sessions per customer. The pre-period gives DE = 1.78 at m_eff = 9.3, so rho = 0.093. m_eff for each candidate duration comes from the actual in-window traffic.

| | Naive binomial | Clustered (delta method) |
|---|---|---|
| Required sessions per arm | 141,504 | 208,528 |
| Days to 80% power | 13 | 18 |
| MDE at 8 weeks | 0.43% | 0.67% |

The naive calculation understates the required sample by a factor of 1.47 and the duration by 5 days. Because customers accumulate sessions over time, the design effect keeps growing: 2.42 at 8 weeks, where naive standard errors would be 1.56 times too narrow.

**Eight weeks is overpowered for conversion** (power 0.986 at the MDE; 18 days would suffice). The timeline is driven by the dispute guardrail, not conversion:

- Disputes arrive up to 60 days after a charge, so the guardrail can only be read on matured charges, at 2026-09-25.
- The business case uses weeks 3 to 8, after novelty fades; that window alone has a clustered MDE of 0.71%.
- Segment-level dispute evidence needs volume. The high-risk band is the binding constraint (below).

| Risk band (exploratory) | Session share | Conversion MDE (unadjusted / Holm worst case) | Pre-period dispute rate | Dispute NI power at true difference 0 (unadjusted / Holm worst case) |
|---|---|---|---|---|
| Low | 60.8% | 0.86% / 1.00% | 0.20% | 100% / 100% |
| Medium | 34.6% | 1.20% / 1.38% | 0.49% | 100% / 100% |
| **High** | **4.6%** | **4.04% / 4.67%** | **1.14%** | **37% / 22%** |

The high-risk band (6% of customers, 4.6% of sessions) is underpowered: even if removing CVC had no effect on its disputes, the test would establish non-inferiority only 22% to 37% of the time, and its conversion MDE is about 4%. Its baseline dispute rate rests on only 2,274 matured pre-period charges. A high-band result will usually be "inconclusive" unless the effect is large, which is why the decision rules treat inconclusive bands differently from harmful ones.

Overall dispute non-inferiority has power near 100% at a true difference of 0 (794,063 expected matured charges, SE of the difference 0.011pp).

Caveat: the pre-period contains returning customers only, so in-window baselines (with new customers) will differ, especially the dispute rate. The absolute margin below is insensitive to the baseline dispute rate.

## 6. Economic model and the dispute margin

Implemented in [analysis/economics.py](../analysis/economics.py). Every input below is an **assumption**, not a fact, except the two baselines measured on pre-period data.

| Input | Value | Type |
|---|---|---|
| Contribution margin on order value, before payment costs | 30% | Assumption |
| Processing fee | 2.9% + $0.30 | Assumption (Stripe standard US list price) |
| Dispute fee | $15.00 | Assumption (Stripe US list price) |
| Ops cost per dispute (review and response) | $20.00 | Assumption |
| Share of disputes lost | 70% | Assumption (pre-period observed 61%; rounded up because fraud disputes without CVC evidence are harder to win) |
| Revenue per transaction A | $68.13 | Pre-period baseline |
| Dispute rate d | 0.258% | Pre-period baseline |

Per successful sale the merchant keeps M = (0.30 - 0.029)A - 0.30 = **$18.16**. Each dispute costs K = 15 + 20 + 0.70A = **$82.69** in expectation.

**Derivation.** Let c be control conversion, L the relative conversion lift, and dd the absolute increase in disputes per successful charge. Per session, treatment minus control is worth

    V = c(1+L)M - c(1+L)(d + dd)K - (cM - cdK) = c[L*M - K(L*d + (1+L)*dd)]

The term L*d is the baseline dispute cost carried by the extra sales; (1+L)dd is the extra dispute rate on every treatment sale. Setting V = 0:

    dd* = L(M/K - d) / (1+L)

At L equal to the MDE (1%): dd* = 0.01 x (18.16/82.69 - 0.00258) / 1.01 = **0.215pp**, 83% of the pre-period dispute rate. This is the non-inferiority margin. It is evaluated at the MDE on purpose: if conversion rises by only the smallest lift worth acting on, a dispute increase of 0.215pp erases its value. A larger observed lift tolerates more disputes, which the net value rule below captures directly.

**Authorization.** Conversion is measured end to end (session to captured charge), so revenue lost to a lower authorization rate is already inside L and is not subtracted again. It is reported separately for attribution: an authorization drop at its guardrail limit (-1pp) would cost $0.103 per session, more than an MDE-sized lift earns ($0.094). The authorization guardrail exists for operational reasons (issuer decline monitoring); the economics already price its revenue effect.

**Sensitivity of the margin** (one assumption varied at a time):

| Assumption | Low | Base | High |
|---|---|---|---|
| Contribution margin 20% / 30% / 40% | 0.133pp | 0.215pp | 0.297pp |
| Dispute loss rate 50% / 70% / 90% | 0.258pp | 0.215pp | 0.184pp |
| Ops cost $10 / $20 / $40 | 0.245pp | 0.215pp | 0.173pp |

The analysis will report net value under every point of this grid.

**Business case window.** Net value is estimated on weeks 3 to 8, while the statistical primary uses the full window. The primary answers "did treatment change conversion during the experiment" with all the pre-specified data, so it is not tuned after the fact. The business case forecasts the run rate after launch, and a novelty-inflated early lift would overstate it. Both windows are fixed here, so neither is a post hoc choice.

**Net value estimator.** Per customer, v_i = (0.30 - 0.029) x captured USD - 0.30 x captured charges - (15 + 20) x matured disputes - 0.70 x disputed USD, using actual amounts. Net value per session is sum(v_i) / sum(sessions_i) per arm (steady-state sessions and the charges they produced, matured at the readout date). The arm difference uses the same customer-clustered delta method, and is annualized by multiplying by 26,962 sessions a day x 365.

## 7. Guardrails

| Guardrail | Test | Margin | Pass condition |
|---|---|---|---|
| Dispute rate (matured captured charges only) | One-sided non-inferiority, alpha 0.025 | +0.215pp absolute (derived above) | Upper bound of the 95% CI of the difference < +0.215pp |
| Authorization rate | One-sided non-inferiority, alpha 0.025 | -1.0pp absolute (assumption: operational limit on issuer decline rate) | Lower bound > -1.0pp |
| Revenue per transaction | One-sided non-inferiority, alpha 0.025; customer-clustered bootstrap (2,000 reps) as robustness | -2% relative (assumption) | Lower bound of the relative lift > -2% |

### Early dispute read

At experiment end no in-window charge has matured. Three reads of the dispute difference will be compared:

1. **Naive observed:** disputes opened before experiment end divided by all successful charges.
2. **Lag-adjusted:** the dispute arrival curve F(t), the share of eventual disputes opened within t days of the charge, is fit as an empirical CDF on pre-period charges that had matured by experiment end (charges created on or before 2026-05-28). Each arm's estimate is observed disputes divided by the sum of F(age) over its charges, where age is days from charge to experiment end.
3. **Matured final:** dispute rate on matured charges at the readout date.

**Pre-registered hypothesis:** the lag-adjusted read understates the treatment increase. If removing CVC adds mainly fraud disputes, and fraud disputes arrive later than the pre-period mix the curve was fit on, then F overstates how complete treatment's disputes are at experiment end. This will be checked by comparing the three reads and the dispute reason and lag distribution by arm at the readout date.

## 8. Segments (exploratory)

| Item | Value |
|---|---|
| Dimensions | Risk score band (low, medium, high), country (9), card brand (4) |
| Metrics | Conversion, dispute rate, net value per session |
| Correction | Holm, within each family of one dimension and one metric |
| Targetable dimension | Risk score band only; a ship-to-segment decision can use no other |

The risk score is a transparent points rule on observable, pre-treatment features (account age at first exposure, card funding, country), defined in `dim_customers`. On pre-period data its bands have dispute rates of 0.20%, 0.49%, and 1.14%. Segment results are exploratory: they can motivate a decision to roll out to a segment, but that rollout carries its own confirmatory test.

## 9. Decision rules

Applied in order, using only the tests above.

1. **Validity.** If the SRM test gives p < 0.001, stop: no decision until the cause is found.
2. **Primary.** If conversion lift is not significantly positive (two-sided p ≥ 0.05, or the lift is negative): **don't ship**.
3. **Operational guardrails.** If authorization or revenue per transaction fails non-inferiority: **don't ship**.
4. **Risk bands.** For each band, with Holm adjustment across the three bands and one-sided alpha 0.025:
   - *Qualifies*: dispute non-inferiority holds and net value per session (weeks 3 to 8) is significantly above zero.
   - *Harmful*: net value per session (weeks 3 to 8) is significantly below zero, or the dispute increase is significantly above the margin.
   - *Inconclusive*: neither.
5. **Decision.**
   - **Ship globally** if overall dispute non-inferiority holds, the 95% CI of annualized net value (weeks 3 to 8) is above zero, and no band is harmful.
   - **Ship to segment** otherwise, if at least one band qualifies: roll out to the qualifying bands only, as a staged rollout with its own pre-registered confirmatory test, because segment evidence is exploratory.
   - **Don't ship** otherwise.

## References

- Kohavi, R., Tang, D., & Xu, Y. (2020). *Trustworthy Online Controlled Experiments: A Practical Guide to A/B Testing*. Cambridge University Press.
- Deng, A., Xu, Y., Kohavi, R., & Walker, T. (2013). Improving the sensitivity of online controlled experiments by utilizing pre-experiment data. *WSDM*.
- Deng, A., Knoblich, U., & Lu, J. (2018). Applying the delta method in metric analytics. *KDD*.
- Morgan, K. L., & Rubin, D. B. (2012). Rerandomization to improve covariate balance in experiments. *Annals of Statistics*.
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics*.
