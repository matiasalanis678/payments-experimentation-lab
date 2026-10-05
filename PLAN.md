# Project Plan: Payments Experimentation Lab

Portfolio project for a Stripe Data Analyst Intern application. Author: Matias, a finance BI developer (SQL, Power BI semantic models, DAX). The posting emphasizes SQL, A/B testing, extending a metrics semantic layer, data pipelines, and AI-assisted analysis. Goal: a reproducible payments experimentation project that proves all of those, shippable in 7 days on a MacBook Pro M2 Pro with 16GB RAM.

Process: execute phase by phase. Each phase ends with a review checkpoint (what was built, key decisions, anything to review, test results) before the next begins.

## The story
A merchant tests removing the CVC field from checkout (variant B). Hypothesis: conversion rises. Risks: fraud and disputes rise, and some issuers decline more without CVC. The final recommendation must weigh the conversion win against guardrails, including by risk segment.

## Stack
- Python 3.12 managed with uv
- DuckDB warehouse (single file: data/warehouse.duckdb)
- dbt-core + dbt-duckdb
- MetricFlow via dbt-metricflow with its DuckDB extra (check PyPI for the current extra name; if versions conflict, use the dbt-core version dbt-metricflow pins)
- Analysis: pandas, numpy, scipy, statsmodels
- Charts: matplotlib, static PNGs, clean minimal style
- Makefile where `make all` rebuilds everything from scratch
- ruff + pytest

## Phase 1: Synthetic data generator (src/generate/)
- 8-week experiment, ~200k customers, ~1.5M checkout sessions. Fully seeded and deterministic.
- Tables mirror Stripe API objects where sensible: customers, checkout_sessions, charges (amount in minor units, currency, status, flattened outcome type/reason, card brand, country), disputes (charge_id, reason, amount, created, status), experiment_assignments (customer_id, variant, assigned_at).
- Randomize at the CUSTOMER level via hash of customer_id, 50/50.
- Each customer has a hidden risk_tier (low/medium/high) plus observable features (country, card brand, new vs returning, account age).
- Funnel: session -> payment attempt -> authorization -> success. Disputes arrive 7 to 60 days after the charge.
- Generate dispute data through experiment end + 60 days so all charges can mature.
- Plant effects in config/truth.yaml (analysis code must NEVER read this file):
  - Conversion (session -> successful charge): +2.5% relative in B
  - Authorization rate: -0.5pp in B
  - Dispute rate: +40% relative in B overall, concentrated in high risk, ~0 change in low risk
  - Novelty effect: B's conversion lift larger in week 1, decaying after
- Write parquet to data/raw/ and load into DuckDB.
- Tests: row counts, referential integrity, assignment balance, baseline rates within expected bands.

## Phase 2: dbt models (dbt/)
- staging: stg_customers, stg_checkout_sessions, stg_charges, stg_disputes, stg_assignments
- intermediate: int_session_outcomes (one row per session with attempted/authorized/succeeded flags), int_charge_disputes (dispute lag + is_matured flag relative to a configurable analysis_date)
- marts: fct_checkout_sessions, fct_charges, dim_customers, dim_experiment
- dbt tests: unique, not_null, relationships, accepted_values on variant/status, plus a custom test that every customer has exactly one variant.
- Document every model and column in schema.yml.

## Phase 3: Semantic layer (MetricFlow)
- Semantic models on fct_checkout_sessions and fct_charges with entities, dimensions (variant, country, card_brand, is_returning, risk_score_band, metric_time), and measures. Include a time spine model.
- Metrics:
  - checkout_conversion_rate = successful sessions / sessions (ratio)
  - authorization_rate = authorized charges / attempted charges (ratio)
  - revenue_per_transaction = successful charge volume / successful charges (ratio)
  - dispute_rate = disputes / successful charges, matured charges only (ratio with filter)
  - total_payment_volume (simple)
- scripts/mf_queries.sh with 5 example `mf query` commands (by variant, by week, by country) saving outputs to reports/mf/.
- README section explaining the semantic layer for a finance stakeholder, briefly drawing the parallel to Power BI semantic models.

## Phase 4: Pre-registration and power (analysis/)
- Write reports/preregistration.md BEFORE computing any treatment effects: hypothesis, primary metric (checkout conversion), guardrails (dispute rate with an explicit non-inferiority margin, authorization rate, revenue per transaction), alpha 0.05, power 0.8, MDE, and decision rules for ship / don't ship / ship to segment.
- Power calculation: required sample per arm for the conversion MDE and the implied duration given daily traffic. Note that the dispute guardrail needs matured cohorts, so it reads out later.
- git commit with message "pre-registration" before Phase 5 starts.

## Phase 5: Experiment analysis (analysis/)
- Sample ratio mismatch check (chi-square) first. If it fails, stop and report.
- Primary metric: difference in proportions with 95% CI. Randomization is per customer but metrics are per session/charge, so use the delta method for ratio metrics. Also run the naive test and show how much it understates the CI width.
- Guardrails: authorization rate, revenue per transaction (Welch t-test or bootstrap), dispute rate as a one-sided non-inferiority test on matured charges.
- Early vs final readout: run the dispute guardrail at experiment end (immature) and at analysis_date (matured). Show how the early read understates risk.
- Segments: build a simple risk score from OBSERVABLE features only (a real company never sees the true tier), then estimate effects by risk band, country, and card brand with Holm correction.
- Novelty: lift by week.
- Stretch if time allows: CUPED using pre-period conversion.
- tests/test_recovery.py is the ONLY code allowed to read truth.yaml. Assert the 95% CIs contain the planted effects.

## Phase 6: Decision memo and charts (reports/)
- reports/experiment_readout.md, one page, written for a product manager. Order: recommendation first, results table (metric, control, treatment, lift, CI, p-value, verdict), guardrail outcome, segment finding, risks, next step.
- Let the data drive conclusions; do not hardcode them. If the dispute guardrail breaches overall but not in low risk, recommend a follow-up test shipping B to low risk only.
- Charts: funnel by variant, forest plot of lifts with CIs, lift by week, dispute rate by risk band, dispute maturation curve (early vs matured).

## Phase 7: Polish
- README: 3-sentence summary and headline results table at the top, Mermaid architecture diagram, how to run (`make all`), project structure, limitations of synthetic data, and what I'd do next with real data.
- GitHub Actions: ruff, pytest, dbt build on push.
- Clean, meaningful commit history.

## Conventions (CONVENTIONS.md)
- Analysis code never reads config/truth.yaml; only tests/test_recovery.py may.
- All randomness seeded from config/settings.yaml.
- Transformations in dbt SQL; Python only for generation and statistics.
- No em dashes in any written docs or comments.
- Small typed functions, docstrings on public functions.
- Each phase ends with a review checkpoint before the next begins.

## Amendments after Phase 1 (binding for later phases)
1. Novelty: the planted +2.5% is the long-run (steady-state) lift with decaying novelty on top. Phase 4 pre-registers the full 8-week window as the primary analysis and "excluding weeks 1-2" as a sensitivity analysis. The pooled vs long-run gap is a memo finding.
2. Pre-experiment A/A: salt exp_remove_cvc_v1 failed the pre-period A/A check (clustered z = -4.18). Diagnosis found no code leak: pre-period outcomes are bit-identical under any assignment, observables were balanced, and across 200 seeds the hidden-trait balance z has mean 0 and SD 1. It was an unlucky draw of hidden customer propensity and risk tier. Fix: re-salted with a rule fixed in advance (first of v2, v3, ... with |z| < 2 and every observable covariate chi-square p > 0.05), which selected v2. Permanent tests: tests/test_balance.py (pre-period A/A within 3 clustered SEs, observable balance) and tests/test_hidden_balance.py (hidden tier balance, truth exception in CONVENTIONS.md). Phase 4 discloses the re-salt as rerandomization.
3. Peek disclosure: during Phase 1 calibration, treatment vs control in-window rates were viewed once (conversion, attempt, authorization, dispute rate) under salt v1, an assignment that was later discarded. preregistration.md must disclose what was seen and when, and state that the MDE and thresholds are set from control baselines only. No treatment vs control comparisons until the "pre-registration" commit.
4. Exposure: Phase 2 adds first_exposure_at and is_exposed (at least one in-window session) to dim_experiment. SRM and all analysis use exposed customers only.
5. README limitations must include: dispute lag capped at 60 days (real disputes can arrive later, so the matured rate is a floor), no payment retries (at most one charge per session), one card per customer, fixed FX rates.
6. Push to the private GitHub repo after every phase.
7. Pre-registration (Phase 4) documents the v1 A/A failure (clustered z = -4.18), the three checks that ruled out a bug (300 placebo salts give z SD 1.00; pre-period outcomes bit-identical under forced-control regeneration; hidden-trait balance z has mean 0 and SD 1 across 200 seeds), the pre-specified re-randomization rule, and that v2 was the first salt to pass. It notes that re-randomization makes standard CIs slightly conservative and cites Kohavi, Tang & Xu, "Trustworthy Online Controlled Experiments" (A/A checks on historical data to choose a balanced hash seed). The README gets a short paragraph on this.
8. Phase 5 frames CUPED as variance reduction, not imbalance correction (the v2 pre-period gap is small).
9. Account age balance: keep salt v2, no re-run. preregistration.md discloses that the rule was fixed and applied under the Phase 1 definition (age at experiment start), that the dbt definition (age at first exposure) gives p = 0.012, that the minimum p across 5 covariates is below that about 6% of the time by chance, and that re-salting now would be forking paths. Phase 4 pre-registers regression adjustment for account_age_band as a robustness analysis.
10. Exposure filter coverage: fixture-based tests (dbt unit tests plus a mini DuckDB warehouse) with never-exposed customers, asserting they are excluded from SRM and analysis inputs.
11. Lag-adjusted early dispute read (Phases 4 and 5): fit the dispute arrival curve on pre-period charges only, scale each arm's observed-at-experiment-end disputes by it, and compare naive early read vs lag-adjusted early read vs matured final read. Pre-register the hypothesis that the adjusted read may still understate treatment risk if the fraud mix shifts lag.
12. Limitations also include: the dim_customers risk score features were chosen with knowledge of the generator; a real team would choose them from domain knowledge and validate them on pre-period data.
13. Blindness (Phase 3 until the "pre-registration" commit): MetricFlow queries grouped by variant run on the pre-period only. In-window variant splits are written but gated behind analysis.unblinded in config/settings.yaml, which Phase 5 turns on.
14. Phase 7 CI: GitHub Actions checkout uses fetch-depth: 0 (with tags) so the prereg-v1 and prereg-amendment-1 freeze checks run.
