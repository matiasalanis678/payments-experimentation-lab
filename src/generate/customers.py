"""Customer population: observable attributes plus a hidden risk tier."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from generate.ids import make_ids
from generate.settings import SECONDS_PER_DAY, Settings, to_epoch

RISK_TIERS = ("low", "medium", "high")


def _choice(rng: np.random.Generator, options: dict[str, Any], n: int) -> np.ndarray:
    """Draw `n` keys from a {key: {weight: ...}} mapping."""
    keys = list(options)
    weights = np.array([options[k]["weight"] for k in keys], dtype=float)
    return rng.choice(np.array(keys, dtype=object), size=n, p=weights / weights.sum())


def _lookup(values: np.ndarray, table: dict[str, Any], field: str) -> np.ndarray:
    """Map each key in `values` to `table[key][field]`."""
    return pd.Series(values).map({k: v[field] for k, v in table.items()}).to_numpy(dtype=float)


def _risk_tiers(rng: np.random.Generator, latent_observable: np.ndarray, risk: dict[str, Any]) -> np.ndarray:
    """Cut latent risk (observable part + noise) into low/medium/high by the configured shares."""
    latent = latent_observable + rng.normal(0.0, risk["noise_sd"], size=latent_observable.size)
    shares = risk["tier_shares"]
    cuts = np.quantile(latent, [shares["low"], shares["low"] + shares["medium"]])
    return np.array(RISK_TIERS, dtype=object)[np.searchsorted(cuts, latent)]


def generate_customers(rng: np.random.Generator, settings: Settings, world: dict[str, Any]) -> pd.DataFrame:
    """Create the customer population.

    Returns public Stripe-like columns (id, created, address_country, default_card_*) plus
    private simulation columns prefixed with `_` that never reach data/raw.
    """
    n = settings.n_customers
    start, end = to_epoch(settings.start_date), to_epoch(settings.end_date)

    ids = make_ids(rng, "cus_", n, length=14)
    country = _choice(rng, world["countries"], n)
    brand = _choice(rng, world["card_brands"], n)
    funding = _choice(rng, world["card_funding"], n)
    is_new = rng.random(n) < world["new_customer_share"]

    # New customers sign up during the experiment, at their first checkout.
    arrival = start + rng.random(n) * (end - start)
    age_cfg = world["account_age_days"]
    age_days = np.clip(rng.lognormal(age_cfg["log_mean"], age_cfg["log_sd"], n), 1, age_cfg["max"])
    created = np.where(is_new, arrival - rng.uniform(60, 900, n), start - age_days * SECONDS_PER_DAY)

    rate_cfg = world["sessions_per_week"]
    shape = rate_cfg["gamma_shape"]
    sessions_per_week = rng.gamma(shape, rate_cfg["mean"] / shape, n)
    attempt_effect = rng.normal(0.0, world["funnel"]["customer_effect_sd"], n)

    risk = world["risk"]
    young_account = ~is_new & (age_days < risk["young_account_days"])
    latent_observable = (
        risk["new_customer"] * is_new
        + risk["young_account"] * young_account
        + _lookup(country, world["countries"], "risk")
        + _lookup(funding, world["card_funding"], "risk")
    )
    tier = _risk_tiers(rng, latent_observable, risk)

    return pd.DataFrame(
        {
            "id": ids,
            "created": created.astype(np.int64),
            "address_country": country,
            "default_card_brand": brand,
            "default_card_funding": funding,
            "_is_new": is_new,
            "_arrival": arrival.astype(np.int64),
            "_sessions_per_week": sessions_per_week,
            "_attempt_effect": attempt_effect,
            "_risk_tier": tier,
        }
    )
