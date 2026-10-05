# Payments Experimentation Lab

A reproducible A/B test on synthetic, Stripe-shaped payments data: does removing the CVC field from checkout lift conversion enough to justify the extra fraud and dispute risk?

> Status: in progress. The data generator, dbt warehouse, and semantic layer are built. Pre-registration, analysis, and the decision memo follow. The full plan is in [PLAN.md](PLAN.md).

## The semantic layer, for a finance stakeholder

A semantic layer is a single, governed definition of each business metric that every report and analysis queries, so "conversion rate" means the same thing in a dashboard, a notebook, and a board deck. This project uses [MetricFlow](https://docs.getdbt.com/docs/build/about-metricflow) on top of the dbt marts.

If you know Power BI, you already know the idea. The concepts map almost one to one:

| Power BI semantic model | MetricFlow in this project |
|---|---|
| Fact and dimension tables joined by relationships (a star schema) | Semantic models joined by entities: `checkout_sessions` and `charges` facts, `customers` and `experiment_assignments` dimensions, all linked through `customer` |
| A DAX measure such as `DIVIDE([Successful sessions], [Sessions])` | A ratio metric (`checkout_conversion_rate`) |
| `CALCULATE([Disputes], Charges[IsMatured] = TRUE)` | A metric input filter (`dispute_rate` counts only matured charges) |
| A marked date table | The `metricflow_time_spine` model |
| Saved report pages or bookmarks | Saved queries |

The difference is that the definitions live in version-controlled YAML ([dbt/models/semantic/](dbt/models/semantic/)), are reviewed like code, and are validated against the warehouse on every build.

### Metrics

| Metric | Definition | Role in the experiment |
|---|---|---|
| `checkout_conversion_rate` | Successful (captured) sessions / checkout sessions | Primary metric |
| `authorization_rate` | Authorized charges / attempted charges | Guardrail: issuers may decline more without CVC |
| `revenue_per_transaction` | Captured USD volume / successful charges | Guardrail |
| `dispute_rate` | Disputed charges / successful charges, **matured charges only** | Guardrail: fraud risk |
| `total_payment_volume` | Sum of captured amounts in USD | Business context |
| `dispute_rate_observed_at_experiment_end` | Disputes opened before the experiment ended / successful charges | Illustration only: why early reads mislead |

Two definitions deserve a note:

- **Dispute rate only counts matured charges.** Cardholders can dispute for weeks after a payment. A charge is "matured" once its 60-day window has passed. Counting immature charges divides by payments whose disputes have not arrived yet, which makes the rate look better than it is. Pooled over the experiment window, the matured rate is 0.41% while the rate observable on the last day of the experiment is 0.18%.
- **Charges are dated by their checkout session.** `metric_time` is the session time for every metric, so a payment made a few minutes after midnight still lands in the same week and period as the session that produced it.

`is_exposed` is available as a filter dimension (`customer__is_exposed`); the experiment queries use exposed customers only.

### Querying it

```bash
cd dbt
uv run mf query --metrics checkout_conversion_rate,dispute_rate --group-by metric_time__week
uv run mf query --saved-query weekly_kpis --order metric_time__week
```

`scripts/mf_queries.sh` runs the five standard saved queries (by week, by variant, by country) and writes CSVs to `reports/mf/`. The three that compare treatment with control inside the experiment window are gated behind `analysis.unblinded` in `config/settings.yaml` and do not run until the analysis plan is pre-registered.

## Reconciliation

Every metric is tied out the way a finance team ties a report to the ledger. `tests/test_reconciliation.py` queries MetricFlow for the experiment window (pooled, no variant split) and compares each number with a hand-written SQL query on the dbt marts:

| Check | Tolerance |
|---|---|
| Counts (sessions, charges, disputes) | Exact |
| Payment volume (USD) | To the cent |
| Ratios (conversion, authorization, revenue per transaction, dispute rates) | 6 decimal places |

The hand-written SQL filters on raw timestamps rather than the dbt `period` column, so the check also covers the window logic. It runs in `make all` alongside `mf validate-configs`, which validates every semantic model, dimension, measure, and metric against the warehouse.

## Randomization and the pre-experiment A/A check

Customers are bucketed by a salted hash of their customer id. Before launch, the assignment was checked on historical (pre-period) data, the A/A check described by Kohavi, Tang & Xu in *Trustworthy Online Controlled Experiments*. The first salt failed: pre-period conversion differed between the arms by 4.2 customer-clustered standard errors. Diagnostics ruled out a code bug. Re-bucketing under 300 placebo salts gave z-scores with standard deviation 1.00, pre-period outcomes were bit-identical when everyone was forced into control, and observable covariates were balanced. So the assignment was re-salted using a rule fixed before looking at any candidate: take the first salt with pre-period |z| < 2 and every observable covariate balanced at p > 0.05. The second salt passed (z = +0.82). Choosing among assignments this way makes standard confidence intervals slightly conservative, never optimistic. A permanent test keeps the pre-period difference within 3 standard errors.

## How to run

```bash
make all   # generate data, dbt build, validate the semantic layer, run saved queries, lint, test
```

Requires [uv](https://docs.astral.sh/uv/). Everything rebuilds from a single seed in `config/settings.yaml`.
