"""Treatment effect estimators for customer-randomized ratio metrics.

Function names match the estimator names in config/prereg.yaml (dispatch with `estimator_fn(name)`).
Each takes a customer frame, a metric function, and the pre-registration, and returns an Effect for
treatment minus control. Ratio metrics use the customer-clustered delta method (Deng, Knoblich & Lu, 2018).
"""

from __future__ import annotations

import dataclasses
import functools
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from analysis.metrics import MetricFn, metric_fn
from analysis.stats import clustered_ratio
from generate.assignment import TREATMENT
from generate.settings import load_settings


@dataclass(frozen=True)
class Effect:
    """Treatment minus control for one metric, with absolute and relative uncertainty."""

    method: str
    control: float
    treatment: float
    diff: float
    se: float
    relative: float
    relative_se: float
    n_control: int
    n_treatment: int
    extra: dict[str, Any] = field(default_factory=dict)

    def z_ci(self, alpha: float) -> tuple[float, float]:
        """Two-sided (1 - alpha) CI for the absolute difference."""
        h = stats.norm.ppf(1 - alpha / 2) * self.se
        return self.diff - h, self.diff + h

    def relative_ci(self, alpha: float) -> tuple[float, float]:
        """Two-sided (1 - alpha) CI for the relative lift (delta method unless overridden)."""
        if "relative_ci" in self.extra:
            return tuple(self.extra["relative_ci"])
        h = stats.norm.ppf(1 - alpha / 2) * self.relative_se
        return self.relative - h, self.relative + h

    @property
    def p_value(self) -> float:
        """Two-sided p-value for a zero difference."""
        return float(2 * stats.norm.sf(abs(self.diff / self.se)))

    def as_dict(self, alpha: float) -> dict[str, Any]:
        """Serializable summary with CIs at the given alpha."""
        out = {k: v for k, v in asdict(self).items() if k != "extra"}
        lo, hi = self.z_ci(alpha)
        rlo, rhi = self.relative_ci(alpha)
        out |= {"ci_low": lo, "ci_high": hi, "relative_ci_low": rlo, "relative_ci_high": rhi, "p_value": self.p_value}
        return out | self.extra


def _named(fn: Callable[..., Effect]) -> Callable[..., Effect]:
    """Stamp each Effect with the estimator's function name (the name used in config/prereg.yaml)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Effect:
        return dataclasses.replace(fn(*args, **kwargs), method=fn.__name__)

    return wrapper


def _arms(frame: pd.DataFrame) -> np.ndarray:
    return (frame["variant"] == TREATMENT).to_numpy()


def _relative(rc: float, rt: float, var_c: float, var_t: float) -> tuple[float, float]:
    """Relative lift rt/rc - 1 and its delta-method SE (arms independent)."""
    return rt / rc - 1, float(np.sqrt(var_t / rc**2 + rt**2 * var_c / rc**4))


def _effect(method: str, rc: float, rt: float, var_c: float, var_t: float, nc: int, nt: int, **extra: Any) -> Effect:
    rel, rel_se = _relative(rc, rt, var_c, var_t)
    se = float(np.sqrt(var_c + var_t))
    return Effect(method, rc, rt, rt - rc, se, rel, rel_se, nc, nt, dict(extra))


@_named
def delta_method_diff(frame: pd.DataFrame, metric: MetricFn, prereg: dict[str, Any]) -> Effect:
    """Unadjusted difference in ratio metrics with customer-clustered delta-method variance."""
    num, den = metric(frame, prereg)
    t = _arms(frame)
    c_est, t_est = clustered_ratio(num[~t], den[~t]), clustered_ratio(num[t], den[t])
    return _effect("", c_est.rate, t_est.rate, c_est.variance, t_est.variance, int((~t).sum()), int(t.sum()))


@_named
def naive_two_proportion(frame: pd.DataFrame, metric: MetricFn, prereg: dict[str, Any]) -> Effect:
    """Treats every unit (session) as independent: the textbook test that ignores customer clustering."""
    num, den = metric(frame, prereg)
    t = _arms(frame)
    rc, rt = num[~t].sum() / den[~t].sum(), num[t].sum() / den[t].sum()
    var_c, var_t = rc * (1 - rc) / den[~t].sum(), rt * (1 - rt) / den[t].sum()
    return _effect("", rc, rt, var_c, var_t, int(den[~t].sum()), int(den[t].sum()))


def _linearize(num: np.ndarray, den: np.ndarray) -> tuple[float, np.ndarray]:
    """Ratio and per-customer linearized contribution (num - r * den) / mean(den)."""
    r = num.sum() / den.sum()
    return r, (num - r * den) / den.mean()


@_named
def cuped_delta_method(frame: pd.DataFrame, metric: MetricFn, prereg: dict[str, Any]) -> Effect:
    """CUPED on linearized ratios (Deng, Xu, Kohavi & Walker, 2013), covariate from prereg, theta pooled.

    Customers without pre-period sessions get a linearized covariate of 0.
    """
    covariate = metric_fn(prereg["secondary"]["cuped"]["covariate"])
    num, den = metric(frame, prereg)
    x_num, x_den = covariate(frame, prereg)
    t = _arms(frame)
    x_rate = x_num.sum() / x_den.sum()
    x = (x_num - x_rate * x_den) / x_den.mean()
    x = x - x.mean()

    lin = np.empty_like(num)
    rc, lin[~t] = _linearize(num[~t], den[~t])
    rt, lin[t] = _linearize(num[t], den[t])
    theta = float(np.dot(lin, x) / np.dot(x, x))
    adj = lin - theta * x
    rc_adj, rt_adj = rc - theta * x[~t].mean(), rt - theta * x[t].mean()
    var_c, var_t = adj[~t].var(ddof=1) / (~t).sum(), adj[t].var(ddof=1) / t.sum()
    raw_var = lin[~t].var(ddof=1) / (~t).sum() + lin[t].var(ddof=1) / t.sum()
    return _effect(
        "",
        rc_adj,
        rt_adj,
        var_c,
        var_t,
        int((~t).sum()),
        int(t.sum()),
        theta=theta,
        variance_reduction=1 - (var_c + var_t) / raw_var,
    )


@_named
def regression_adjusted_delta_method(frame: pd.DataFrame, metric: MetricFn, prereg: dict[str, Any]) -> Effect:
    """OLS of the linearized per-customer outcome on treatment plus prereg covariates (HC1 SEs)."""
    covariates = prereg["secondary"]["account_age_adjusted"]["covariates"]
    num, den = metric(frame, prereg)
    t = _arms(frame)
    y = np.empty_like(num)
    rates = {}
    for key, arm in (("c", ~t), ("t", t)):
        r, lin = _linearize(num[arm], den[arm])
        y[arm], rates[key] = r + lin, r
    design = pd.get_dummies(frame[covariates].astype(str), drop_first=True, dtype=float)
    design.insert(0, "treatment", t.astype(float))
    fit = sm.OLS(y, sm.add_constant(design.to_numpy()), hasconst=True).fit(cov_type="HC1")
    diff, se = float(fit.params[1]), float(fit.bse[1])
    rc = rates["c"]
    return Effect(
        "",
        rc,
        rc + diff,
        diff,
        se,
        diff / rc,
        se / rc,
        int((~t).sum()),
        int(t.sum()),
        {"covariates": covariates, "unadjusted_treatment": rates["t"]},
    )


@_named
def cluster_bootstrap(frame: pd.DataFrame, metric: MetricFn, prereg: dict[str, Any], reps: int) -> Effect:
    """Poisson bootstrap over customers (each customer weighted Poisson(1)) for the relative lift.

    Seeded from config/settings.yaml. Returns percentile CIs at the prereg alpha in `extra`.
    """
    num, den = metric(frame, prereg)
    t = _arms(frame)
    rng = np.random.default_rng(load_settings().seed)
    draws = {}
    chunk = max(1, reps // 16)
    for key, arm in (("c", ~t), ("t", t)):
        n_arm, d_arm, out = num[arm], den[arm], []
        for start in range(0, reps, chunk):
            w = rng.poisson(1.0, size=(min(chunk, reps - start), n_arm.size))
            out.append((w @ n_arm) / (w @ d_arm))
        draws[key] = np.concatenate(out)
    rel = draws["t"] / draws["c"] - 1
    diff = draws["t"] - draws["c"]
    alpha = prereg["alpha"]
    q = [alpha / 2, 1 - alpha / 2]
    rc, rt = num[~t].sum() / den[~t].sum(), num[t].sum() / den[t].sum()
    return Effect(
        "",
        rc,
        rt,
        rt - rc,
        float(diff.std(ddof=1)),
        rt / rc - 1,
        float(rel.std(ddof=1)),
        int((~t).sum()),
        int(t.sum()),
        {"relative_ci": [float(v) for v in np.quantile(rel, q)], "reps": reps},
    )


def estimator_fn(name: str) -> Callable[..., Effect]:
    """Look up an estimator function by its pre-registered name."""
    return getattr(sys.modules[__name__], name)


def estimate(name: str, frame: pd.DataFrame, metric: str, prereg: dict[str, Any], **kwargs: Any) -> Effect:
    """Run the named estimator on the named metric."""
    return estimator_fn(name)(frame, metric_fn(metric), prereg, **kwargs)
