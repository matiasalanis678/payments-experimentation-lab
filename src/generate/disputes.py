"""Disputes on captured charges, arriving 7 to 60 days after the charge."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from generate.customers import RISK_TIERS
from generate.ids import make_ids
from generate.settings import SECONDS_PER_DAY, Settings, to_epoch


def solve_dispute_lifts(
    funnel: pd.DataFrame, world: dict[str, Any], dispute_effects: dict[str, Any]
) -> dict[str, float]:
    """Return relative dispute lift per risk tier, solving the high tier so the overall lift hits target.

    Uses expected successful charges per tier among treated sessions, so the calibration is exact
    in expectation and does not depend on the random draws.
    """
    treated = funnel["_treated"].to_numpy()
    expected = funnel.loc[treated].groupby("_risk_tier")["_p_success"].sum()
    base = world["disputes"]["base_rate_by_tier"]
    weight = {t: expected.get(t, 0.0) * base[t] for t in RISK_TIERS}
    lifts = dict(dispute_effects["relative_lift_by_risk_tier"])
    target = (1 + dispute_effects["overall_relative_lift"]) * sum(weight.values())
    fixed = sum(weight[t] * (1 + lifts[t]) for t in RISK_TIERS if t != "high")
    lifts["high"] = (target - fixed) / weight["high"] - 1
    return {t: float(lifts[t]) for t in RISK_TIERS}


def _truncated_gamma(rng: np.random.Generator, n: int, shape: float, scale: float, upper: float) -> np.ndarray:
    """Gamma draws truncated to [0, upper] by inverse CDF."""
    dist = stats.gamma(shape, scale=scale)
    return dist.ppf(rng.random(n) * dist.cdf(upper))


def _reasons_by_tier(rng: np.random.Generator, tier: np.ndarray, mix: dict[str, dict[str, float]]) -> np.ndarray:
    """Draw a dispute reason per row from the tier-specific mix."""
    out = np.empty(tier.size, dtype=object)
    for t, reasons in mix.items():
        mask = tier == t
        keys = np.array(list(reasons), dtype=object)
        probs = np.array(list(reasons.values()), dtype=float)
        out[mask] = rng.choice(keys, size=int(mask.sum()), p=probs / probs.sum())
    return out


def _statuses(
    rng: np.random.Generator, created: np.ndarray, reason: np.ndarray, snapshot: int, cfg: dict[str, Any]
) -> np.ndarray:
    """Dispute status as of the snapshot: recent ones are open, older ones are won or lost."""
    age_days = (snapshot - created) / SECONDS_PER_DAY
    windows = cfg["status_windows_days"]
    p_lost = np.where(reason == "fraudulent", cfg["lost_rate"]["fraudulent"], cfg["lost_rate"]["other"])
    closed = np.where(rng.random(created.size) < p_lost, "lost", "won")
    return np.select(
        [age_days < windows["needs_response"], age_days < windows["under_review"]],
        ["needs_response", "under_review"],
        closed,
    ).astype(object)


def generate_disputes(
    rng: np.random.Generator,
    charges: pd.DataFrame,
    tier_lifts: dict[str, float],
    settings: Settings,
    world: dict[str, Any],
) -> pd.DataFrame:
    """Public disputes table as of the end of analysis_date.

    Treatment-induced excess disputes are fraudulent, and fraud disputes have a longer lag.
    """
    cfg = world["disputes"]
    tier = charges["_risk_tier"].to_numpy()
    treated = charges["_treated"].to_numpy()
    lift = np.where(treated, pd.Series(tier).map(tier_lifts).to_numpy(dtype=float), 0.0)
    p_dispute = pd.Series(tier).map(cfg["base_rate_by_tier"]).to_numpy(dtype=float) * (1 + lift)
    disputed = charges["captured"].to_numpy() & (rng.random(len(charges)) < p_dispute)

    d = charges.loc[disputed]
    n = len(d)
    d_lift = lift[disputed]
    excess = rng.random(n) < d_lift / (1 + d_lift)
    reason = _reasons_by_tier(rng, tier[disputed], cfg["reason_mix_by_tier"])
    reason[excess] = "fraudulent"

    lag_cfg = cfg["lag_days"]
    span = lag_cfg["max"] - lag_cfg["min"]
    is_fraud = reason == "fraudulent"
    lag = np.empty(n)
    for mask, key in ((is_fraud, "fraudulent"), (~is_fraud, "other")):
        g = lag_cfg[key]
        lag[mask] = lag_cfg["min"] + _truncated_gamma(rng, int(mask.sum()), g["gamma_shape"], g["gamma_scale"], span)
    created = d["created"].to_numpy() + (lag * SECONDS_PER_DAY).astype(np.int64)

    snapshot = to_epoch(settings.analysis_date) + SECONDS_PER_DAY  # data through end of analysis_date
    disputes = pd.DataFrame(
        {
            "id": make_ids(rng, "dp_", n),
            "charge": d["id"].to_numpy(),
            "amount": d["amount_captured"].to_numpy(),
            "currency": d["currency"].to_numpy(),
            "reason": reason,
            "status": _statuses(rng, created, reason, snapshot, cfg),
            "created": created,
        }
    )
    return disputes.loc[disputes["created"] < snapshot].sort_values("created", kind="stable").reset_index(drop=True)
