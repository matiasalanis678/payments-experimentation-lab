# Pre-registration amendments

Amendments to the plan frozen at tag `prereg-v1`. [config/prereg.yaml](../config/prereg.yaml) and [preregistration.md](preregistration.md) are not edited; this file adds to them. It is committed and tagged `prereg-amendment-1` before the commit that sets `analysis.unblinded` to true, and is frozen from then on (tests/test_prereg.py checks both).

## Amendment 1 (2026-10-05, before unblinding)

At the time of writing, no treatment versus control comparison has been run on the experiment window under the v2 assignment.

### A1.1 Disclosure: the dispute loss rate assumption

The frozen economic model assumes 70% of disputes are lost (`economics.assumptions.dispute_loss_rate: 0.7`). The pre-period data show 60.7% (`baselines.preperiod.observed_dispute_loss_rate: 0.607143`). The pre-registration justifies rounding up because fraud disputes on charges without CVC evidence are harder to win.

That choice was made by an author who knew the planted effects, including that the generator concentrates the treatment's extra disputes in the hidden high-risk tier. The author knew a higher loss rate raises the expected cost of each dispute and therefore makes a dispute-heavy segment look worse. The choice is likely to affect the high-risk band verdict.

| Loss rate | Expected cost per dispute | Break-even dispute margin at the 1% MDE |
|---|---|---|
| 70% (frozen) | $82.69 | +0.215pp (83% of the pre-period rate) |
| 60.7% (observed) | $76.36 | +0.233pp (90% of the pre-period rate) |

A finance reviewer checked the derivation and assumptions before unblinding and kept the frozen values. The guardrail margin stays at +0.215pp.

### A1.2 Added sensitivity reporting

The economic decision (net value per session for weeks 3 to 8, annualized, with its 95% CI, and the decision it implies) is reported:

1. under the frozen 70% loss rate: **primary**;
2. under the observed 60.7% loss rate: **sensitivity**;
3. at every point of the pre-registered sensitivity grid, with the primary result's position in it.

### A1.3 Analyses outside prereg.yaml

Any analysis not specified in config/prereg.yaml is logged with its reason in `reports/deviations.md` and labeled exploratory in every output.
