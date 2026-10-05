"""Pre-registered tests and decision rules (config/prereg.yaml: guardrails, decision_rules)."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analysis.estimators import Effect

SHIP_GLOBALLY = "SHIP GLOBALLY"
SHIP_TO_SEGMENT = "SHIP TO SEGMENT"
DONT_SHIP = "DON'T SHIP"
NO_DECISION = "NO DECISION (SRM)"


def non_inferiority(effect: Effect, margin: float, alpha_one_sided: float, relative: bool = False) -> dict[str, Any]:
    """One-sided non-inferiority test. A positive margin caps an increase; a negative margin caps a decrease."""
    est, se = (effect.relative, effect.relative_se) if relative else (effect.diff, effect.se)
    z = stats.norm.ppf(1 - alpha_one_sided)
    if margin > 0:
        bound, p = est + z * se, stats.norm.cdf((est - margin) / se)
        passed = bound < margin
    else:
        bound, p = est - z * se, stats.norm.sf((est - margin) / se)
        passed = bound > margin
    return {
        "estimate": est,
        "bound": float(bound),
        "margin": margin,
        "scale": "relative" if relative else "absolute",
        "p_value": float(p),
        "passed": bool(passed),
    }


def srm_test(counts: dict[str, int], expected_treatment_share: float, treatment: str) -> dict[str, Any]:
    """Chi-square goodness of fit of exposed customers per arm against the designed split."""
    n = sum(counts.values())
    observed = [counts[treatment], n - counts[treatment]]
    expected = [n * expected_treatment_share, n * (1 - expected_treatment_share)]
    chi = stats.chisquare(observed, expected)
    return {
        "counts": counts,
        "treatment_share": counts[treatment] / n,
        "chi2": float(chi.statistic),
        "p_value": float(chi.pvalue),
    }


def _holm(p_values: dict[str, float], alpha: float, method: str) -> dict[str, float]:
    keys = list(p_values)
    adjusted = multipletests([p_values[k] for k in keys], alpha=alpha, method=method)[1]
    return dict(zip(keys, (float(a) for a in adjusted), strict=True))


def band_status(
    dispute: dict[str, Effect], value: dict[str, Effect], margin: float, alpha: float, method: str
) -> dict[str, dict[str, Any]]:
    """Qualifies / harmful / inconclusive per band, each one-sided test Holm-adjusted across bands."""
    families = {
        "dispute_non_inferior": {b: stats.norm.cdf((e.diff - margin) / e.se) for b, e in dispute.items()},
        "dispute_above_margin": {b: stats.norm.sf((e.diff - margin) / e.se) for b, e in dispute.items()},
        "value_above_zero": {b: stats.norm.sf(e.diff / e.se) for b, e in value.items()},
        "value_below_zero": {b: stats.norm.cdf(e.diff / e.se) for b, e in value.items()},
    }
    adjusted = {name: _holm(ps, alpha, method) for name, ps in families.items()}
    out = {}
    for b in dispute:
        sig = {name: adjusted[name][b] < alpha for name in adjusted}
        if sig["value_below_zero"] or sig["dispute_above_margin"]:
            status = "harmful"
        elif sig["dispute_non_inferior"] and sig["value_above_zero"]:
            status = "qualifies"
        else:
            status = "inconclusive"
        reasons = [name for name, flag in sig.items() if flag]
        out[b] = {"status": status, "significant": reasons, "holm_adjusted_p": {n: adjusted[n][b] for n in adjusted}}
    return out


def annualize(effect: Effect, annual_sessions: float, alpha: float) -> dict[str, float]:
    """Scale a per-session value difference to a year, with its two-sided CI."""
    lo, hi = effect.z_ci(alpha)
    return {
        "per_session": effect.diff,
        "per_session_ci": [lo, hi],
        "annual": effect.diff * annual_sessions,
        "annual_ci": [lo * annual_sessions, hi * annual_sessions],
    }


def decide(
    srm_ok: bool,
    primary: Effect,
    alpha: float,
    operational: dict[str, dict[str, Any]],
    dispute_ni: dict[str, Any],
    net_value: dict[str, float],
    bands: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Apply the pre-registered decision rules in order; return the decision and the trail."""
    trail: list[str] = []
    if not srm_ok:
        return {"decision": NO_DECISION, "trail": ["SRM failed"]}
    primary_ok = primary.p_value < alpha and primary.diff > 0
    trail.append(f"primary significant positive: {primary_ok} (p={primary.p_value:.2e}, diff={primary.diff:+.5f})")
    if not primary_ok:
        return {"decision": DONT_SHIP, "trail": trail}
    for name, res in operational.items():
        trail.append(f"{name} non-inferior: {res['passed']} (bound {res['bound']:+.5f} vs margin {res['margin']:+.4f})")
    if not all(r["passed"] for r in operational.values()):
        return {"decision": DONT_SHIP, "trail": trail}
    value_ok = net_value["annual_ci"][0] > 0
    trail.append(f"dispute non-inferior overall: {dispute_ni['passed']} (bound {dispute_ni['bound']:+.5f})")
    trail.append(f"annual net value CI above zero: {value_ok} (CI {np.round(net_value['annual_ci'], 0).tolist()})")
    statuses = {b: r["status"] for b, r in bands.items()}
    trail.append(f"risk bands: {statuses}")
    harmful = [b for b, s in statuses.items() if s == "harmful"]
    qualifying = [b for b, s in statuses.items() if s == "qualifies"]
    if dispute_ni["passed"] and value_ok and not harmful:
        return {"decision": SHIP_GLOBALLY, "trail": trail, "bands": statuses}
    if qualifying:
        return {"decision": SHIP_TO_SEGMENT, "qualifying_segments": qualifying, "trail": trail, "bands": statuses}
    return {"decision": DONT_SHIP, "trail": trail, "bands": statuses}
