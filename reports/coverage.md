# CI coverage simulation

Post-hoc method validation, added after the overall dispute CI missed its planted value (see
reports/deviations.md). Exploratory: not part of the pre-registration.

200 independent worlds (generator seeds), 50,000 customers each (a quarter of full scale), each built with dbt and analyzed with the pre-registered estimators. Each row is the share of seeds whose 95% CI contains the planted value, with a Clopper-Pearson 95% interval. Runtime 2.9 minutes. Seeds were not re-randomized by the A/A rule.

| Quantity | Covered | Coverage | 95% interval |
|---|---|---|---|
| conversion_full | 184/200 | 92.0% | [87.3%, 95.4%] |
| conversion_weeks_3_8 | 186/200 | 93.0% | [88.5%, 96.1%] |
| conversion_week_1 | 193/200 | 96.5% | [92.9%, 98.6%] |
| authorization_delta | 184/200 | 92.0% | [87.3%, 95.4%] |
| revenue_per_transaction | 188/200 | 94.0% | [89.8%, 96.9%] |
| dispute_rate | 192/200 | 96.0% | [92.3%, 98.3%] |
| conversion_full_naive (extra) | 148/200 | 74.0% | [67.3%, 79.9%] |
| conversion_full_cuped (extra) | 189/200 | 94.5% | [90.4%, 97.2%] |

Rows marked (extra) are not recovery checks: the naive binomial CI ignores customer clustering, and
CUPED is a secondary estimator.
