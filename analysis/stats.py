"""Customer-clustered estimators for ratio metrics (delta method)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class RatioEstimate:
    """A ratio metric sum(num) / sum(den) with a customer-clustered variance."""

    rate: float
    variance: float
    n_clusters: int
    n_units: float


@dataclass(frozen=True)
class RatioDiff:
    """Difference in ratio metrics between two arms (b minus a)."""

    diff: float
    se: float
    z: float
    p_value: float


def clustered_ratio(num: np.ndarray, den: np.ndarray) -> RatioEstimate:
    """Delta-method estimate of sum(num) / sum(den) treating clusters (customers) as iid.

    `num` and `den` hold one value per cluster, e.g. successful sessions and sessions per customer.
    """
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    k = num.size
    rate = num.sum() / den.sum()
    variance = np.var(num - rate * den, ddof=1) * k / den.sum() ** 2
    return RatioEstimate(rate=rate, variance=variance, n_clusters=k, n_units=den.sum())


def diff_in_ratios(a: RatioEstimate, b: RatioEstimate) -> RatioDiff:
    """Two-sided z-test for b.rate - a.rate using the clustered variances."""
    diff = b.rate - a.rate
    se = float(np.sqrt(a.variance + b.variance))
    z = diff / se
    return RatioDiff(diff=diff, se=se, z=z, p_value=float(2 * stats.norm.sf(abs(z))))
