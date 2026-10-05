# Experiment results: remove CVC field

Machine-readable outputs: `results.json`, `segments.csv` (exploratory), `weekly_lift.csv`,
`sensitivity_grid.csv`. Status labels: pre-registered (config/prereg.yaml), amendment A1
(reports/prereg_amendments.md, committed before unblinding), exploratory (reports/deviations.md).

**Decision under the pre-registered rules: SHIP TO SEGMENT (low risk band)**

- primary significant positive: True (p=5.97e-34, diff=+0.01571)
- authorization_rate non-inferior: True (bound -0.00643 vs margin -0.0100)
- revenue_per_transaction non-inferior: True (bound -0.00091 vs margin -0.0200)
- dispute non-inferior overall: True (bound +0.00138)
- annual net value CI above zero: True (CI [1596056.0, 2929174.0])
- risk bands: {'high': 'harmful', 'low': 'qualifies', 'medium': 'inconclusive'}
- Observed loss rate (60.7%, amendment A1): SHIP TO SEGMENT (low risk band)
- Sensitivity grid (27 points, amendment A1): {'SHIP TO SEGMENT': 27}; the frozen-assumption net value sits at the 56th percentile of the grid.

| Step | Metric | Control | Treatment | Difference [95% CI] | Relative lift [95% CI] | p | Verdict | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | SRM (exposed customers) | 99,738 | 100,262 | | share 0.5013 | 0.24 | Pass | pre-registered |
| 2 | Checkout conversion (primary, full window) | 51.049% | 52.620% | +1.571pp [+1.317pp, +1.824pp] | +3.08% [+2.57%, +3.58%] | 6e-34 | Significant lift | pre-registered |
| 3 | Checkout conversion, naive binomial | 51.049% | 52.620% | +1.571pp [+1.411pp, +1.730pp] | +3.08% [+2.76%, +3.39%] | 3.9e-83 | CI 37% too narrow | pre-registered |
| 4 | Authorization rate | 91.901% | 91.396% | -0.505pp [-0.643pp, -0.366pp] | -0.55% [-0.70%, -0.40%] | 9.5e-13 | Pass (bound -0.643pp vs -1.000pp) | pre-registered |
| 4 | Revenue per transaction (USD) | 68.15 | 68.37 | +0.221 [-0.061, +0.504] | +0.32% [-0.09%, +0.74%] | 0.12 | Pass (bound -0.09% vs -2.00%); bootstrap pass | pre-registered |
| 4 | Dispute rate (matured) | 0.358% | 0.466% | +0.109pp [+0.079pp, +0.138pp] | +30.34% [+21.00%, +39.69%] | 4.1e-13 | Pass (bound +0.138pp vs +0.215pp) | pre-registered |
| 5 | Net value, weeks 3-8, loss rate 70% | | | $2,262,615/yr [$1,596,056, $2,929,174] | $0.230/session | | CI above 0 | pre-registered |
| 5 | Net value, weeks 3-8, loss rate 60.7% | | | $2,302,069/yr [$1,637,857, $2,966,281] | $0.234/session | | CI above 0 | amendment A1 (pre-unblinding) |
| 6 | Dispute rate, high risk | 1.481% | 2.534% | +1.053pp [+0.713pp, +1.393pp] | +71.12% [+41.18%, +101.05%] | 1.3e-09 | harmful (dispute above margin) | pre-registered |
| 6 | Dispute rate, low risk | 0.199% | 0.201% | +0.002pp [-0.023pp, +0.027pp] | +0.88% [-11.69%, +13.45%] | 0.89 | qualifies (dispute non inferior, value above zero) | pre-registered |
| 6 | Dispute rate, medium risk | 0.558% | 0.775% | +0.217pp [+0.151pp, +0.283pp] | +38.87% [+25.03%, +52.70%] | 9.6e-11 | inconclusive (value above zero) | pre-registered |
| 6 | Net value per session, high risk | | | $-0.013 [$-0.245, $+0.219] | | 0.91 | harmful (dispute above margin) | pre-registered |
| 6 | Net value per session, low risk | | | $+0.266 [$+0.177, $+0.354] | | 3.9e-09 | qualifies (dispute non inferior, value above zero) | pre-registered |
| 6 | Net value per session, medium risk | | | $+0.218 [$+0.112, $+0.324] | | 5.3e-05 | inconclusive (value above zero) | pre-registered |
| 7 | Conversion, weeks 3-8 (novelty sensitivity) | 50.790% | 52.179% | +1.388pp [+1.123pp, +1.653pp] | +2.73% [+2.20%, +3.26%] | 9.7e-25 |  | pre-registered |
| 7 | Conversion, week 1 | 52.038% | 54.939% | +2.901pp [+2.360pp, +3.442pp] | +5.57% [+4.51%, +6.64%] | 8.1e-26 | Novelty | pre-registered |
| 8 | Conversion, CUPED | 51.074% | 52.596% | +1.522pp [+1.297pp, +1.747pp] | +2.98% [+2.53%, +3.43%] | 4.6e-40 | Variance -21% | pre-registered |
| 9 | Conversion, account-age adjusted | 51.049% | 52.624% | +1.575pp [+1.323pp, +1.827pp] | +3.08% [+2.59%, +3.58%] | 2e-34 | Robust | pre-registered |
| 10 | Dispute rate, naive observed | 0.164% | 0.201% | +0.037pp [+0.018pp, +0.056pp] | +22.43% [+9.54%, +35.33%] | 0.00016 | Pass (bound +0.056pp vs +0.215pp) | pre-registered |
| 10 | Dispute rate, lag adjusted | 0.337% | 0.411% | +0.073pp [+0.034pp, +0.113pp] | +21.77% [+8.94%, +34.59%] | 0.00024 | Pass (bound +0.113pp vs +0.215pp) | pre-registered |
| 10 | Dispute rate, matured final | 0.358% | 0.466% | +0.109pp [+0.079pp, +0.138pp] | +30.34% [+21.00%, +39.69%] | 4.1e-13 | Pass (bound +0.138pp vs +0.215pp) | pre-registered |
| 10 | Fraud share of disputes (matured) | 49.7% | 63.3% | | | 0.027 (lag KS) | Median lag 25.5d vs 26.5d | exploratory |
