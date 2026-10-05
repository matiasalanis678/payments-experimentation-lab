# Deviations from the pre-registration

Log of everything the analysis did beyond, or in more detail than, [config/prereg.yaml](../config/prereg.yaml). Written 2026-10-05 with the Phase 5 analysis. Outputs carry the matching label in `reports/results/`.

## Amendment A1 analyses (specified before unblinding)

Specified in [prereg_amendments.md](prereg_amendments.md), committed and tagged `prereg-amendment-1` before the unblinding commit. Labeled `amendment A1 (pre-unblinding)`.

1. Economic decision under the observed pre-period dispute loss rate (60.7%) alongside the frozen 70%.
2. Economic decision at every point of the pre-registered sensitivity grid. The grid is run full factorial (3 x 3 x 3 = 27 points), since prereg.yaml lists the values but not the design. The dispute non-inferiority margin stays at the frozen +0.215pp at every point; only net value, the band net value tests, and the decision vary.
3. The position of the frozen-assumption result within the grid (percentile of annual net value).

## Exploratory analyses (not in prereg.yaml)

Labeled `exploratory`.

1. **Dispute reason and lag mix by arm**, with a two-sample KS test on lags. preregistration.md section 7 describes this check for the early-read hypothesis, but prereg.yaml does not specify it.
2. **Segment tables.** prereg.yaml fixes the dimensions, metrics, Holm correction, and families. It does not fix the test for the descriptive segment table, so each level reports a two-sided test of zero difference, Holm-adjusted within its (dimension, metric) family. The decision-relevant risk band tests are the one-sided tests in `decision_rules`, unchanged.

## Implementation choices within the plan

Recorded for transparency; none changes a pre-registered parameter.

- `cluster_bootstrap`: Poisson bootstrap over customers (each customer weighted Poisson(1)), 2,000 replicates, seeded from config/settings.yaml. Percentile CI at the pre-registered alpha.
- Relative lift CIs: delta method on the ratio of arm means.
- `cuped_delta_method`: linearized ratio outcome and linearized pre-period conversion covariate, covariate centered at its pooled mean, theta pooled across arms. Customers with no pre-period sessions have covariate 0.
- `regression_adjusted_delta_method`: OLS of the linearized per-customer outcome on treatment plus `account_age_band` dummies, HC1 standard errors.
- Lag-adjusted early read: the arrival curve uses 610 pre-period disputes on captured charges created before 2026-05-28 (matured by experiment end).
- Net value: disputes counted on matured charges from weeks 3 to 8 sessions; every in-window charge is matured at the readout date.
- Weekly lifts: unadjusted, descriptive.
- Risk band dispute tests use the full window (the dispute guardrail window); band net value tests use weeks 3 to 8 (the economics window).

## Validation note (not an analysis deviation)

`tests/test_recovery.py` checks that 95% CIs contain the planted effects. Six checks pass. The overall dispute lift does not: the estimate is +30.3% [21.0%, 39.7%] against a planted +40%. The generator's calibration is exact (given each arm's realized hidden risk mix the expected lift is +39.9%), so the shortfall is chance in which charges were disputed (control 1.2 SD above expectation, treatment 1.7 SD below; about 2 SE combined). The check is kept as a strict expected failure with this diagnosis, next to a passing calibration check. No analysis choice was changed in response.
