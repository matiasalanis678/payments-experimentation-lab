"""Checkout sessions and the session -> attempt -> authorization -> capture funnel."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from generate.assignment import TREATMENT
from generate.ids import make_ids
from generate.settings import SECONDS_PER_DAY, Settings, to_epoch

SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY


def _logit(p: np.ndarray | float) -> np.ndarray | float:
    return np.log(p / (1 - p))


def _expit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _map(values: np.ndarray, mapping: dict[str, Any]) -> np.ndarray:
    """Vectorized dict lookup returning a float array."""
    return pd.Series(values).map(mapping).to_numpy(dtype=float)


def _field(table: dict[str, Any], field: str) -> dict[str, Any]:
    """Project {key: {field: v}} to {key: v}."""
    return {k: v[field] for k, v in table.items()}


def _uniform_times(
    rng: np.random.Generator, counts: np.ndarray, lo: np.ndarray, hi: int
) -> tuple[np.ndarray, np.ndarray]:
    """Place counts[i] timestamps uniformly in [lo[i], hi) for each customer i."""
    idx = np.repeat(np.arange(counts.size), counts)
    times = lo[idx] + rng.random(idx.size) * (hi - lo[idx])
    return idx, times


def schedule_sessions(rng: np.random.Generator, customers: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Return one row per checkout session: `_customer_idx` and `created` (epoch seconds).

    Every customer has at least one session inside the experiment window (that is what puts them
    in the experiment). Returning customers also have pre-period sessions, used later for CUPED.
    """
    start, end = to_epoch(settings.start_date), to_epoch(settings.end_date)
    pre_start = to_epoch(settings.pre_start_date)
    is_new = customers["_is_new"].to_numpy()
    arrival = customers["_arrival"].to_numpy().astype(float)
    created = customers["created"].to_numpy().astype(float)
    rate = customers["_sessions_per_week"].to_numpy()

    window_open = np.where(is_new, arrival, float(start))
    n_exp = 1 + rng.poisson(rate * (end - window_open) / SECONDS_PER_WEEK)
    exp_idx, exp_times = _uniform_times(rng, n_exp, window_open, end)
    first_pos = np.cumsum(n_exp) - n_exp
    exp_times[first_pos[is_new]] = arrival[is_new]  # a new customer's first session is their arrival

    pre_open = np.maximum(float(pre_start), created)
    pre_weeks = np.where(is_new, 0.0, np.clip(start - pre_open, 0, None) / SECONDS_PER_WEEK)
    n_pre = rng.poisson(rate * pre_weeks)
    pre_idx, pre_times = _uniform_times(rng, n_pre, pre_open, start)

    sessions = pd.DataFrame(
        {
            "_customer_idx": np.concatenate([exp_idx, pre_idx]),
            "created": np.floor(np.concatenate([exp_times, pre_times])).astype(np.int64),
        }
    )
    return sessions.sort_values(["created", "_customer_idx"], kind="stable").reset_index(drop=True)


def conversion_lift_by_week(week: np.ndarray, conversion: dict[str, float]) -> np.ndarray:
    """Planted relative conversion lift for experiment week `week` (1-based), novelty included."""
    extra = conversion["novelty_week1_extra_relative_lift"] * conversion["novelty_weekly_decay"] ** (week - 1)
    return conversion["steady_state_relative_lift"] + extra


def _amounts(rng: np.random.Generator, country: np.ndarray, world: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Cart totals in minor units of the customer's local currency (JPY has no minor unit)."""
    cfg = world["amounts"]
    usd = cfg["median_usd"] * _map(country, _field(world["countries"], "amount_multiplier"))
    usd = np.maximum(usd * rng.lognormal(0.0, cfg["log_sd"], country.size), cfg["min_usd"])
    currency = pd.Series(country).map(_field(world["countries"], "currency")).to_numpy(dtype=object)
    usd_per_unit = _map(currency, _field(world["currencies"], "usd_per_unit"))
    exponent = _map(currency, _field(world["currencies"], "exponent"))
    minor = np.maximum(np.round(usd / usd_per_unit * 10**exponent), 1).astype(np.int64)
    return minor, currency


def simulate_funnel(
    rng: np.random.Generator,
    sessions: pd.DataFrame,
    customers: pd.DataFrame,
    variants: np.ndarray,
    settings: Settings,
    world: dict[str, Any],
    effects: dict[str, Any],
) -> pd.DataFrame:
    """Add funnel probabilities and outcomes to `sessions`.

    Treatment is applied so that, per session, P(success) is exactly (1 + lift) times control and
    P(authorized | attempt) moves by the brand-specific delta. The attempt probability absorbs the
    difference, so the planted conversion lift is net of the authorization hit.
    """
    funnel = world["funnel"]
    start = to_epoch(settings.start_date)
    ci = sessions["_customer_idx"].to_numpy()
    created = sessions["created"].to_numpy()

    country = customers["address_country"].to_numpy()[ci]
    brand = customers["default_card_brand"].to_numpy()[ci]
    funding = customers["default_card_funding"].to_numpy()[ci]
    tier = customers["_risk_tier"].to_numpy()[ci]
    is_new = customers["_is_new"].to_numpy()[ci]

    in_window = created >= start
    week = np.where(in_window, (created - start) // SECONDS_PER_WEEK + 1, 0)
    treated = in_window & (variants[ci] == TREATMENT)

    eta_attempt = (
        funnel["attempt_intercept"]
        + _map(country, _field(world["countries"], "attempt_logit"))
        + funnel["returning_attempt_logit"] * ~is_new
        + customers["_attempt_effect"].to_numpy()[ci]
    )
    p_attempt_ctrl = funnel["attempt_cap"] * _expit(eta_attempt)
    eta_auth = (
        _logit(funnel["auth_base_rate"])
        + _map(brand, _field(world["card_brands"], "auth_logit"))
        + _map(country, _field(world["countries"], "auth_logit"))
        + _map(funding, _field(world["card_funding"], "auth_logit"))
        + _map(tier, funnel["auth_logit_by_tier"])
    )
    p_auth_ctrl = _expit(eta_auth)
    capture = funnel["capture_rate"]
    p_success_ctrl = p_attempt_ctrl * p_auth_ctrl * capture

    lift = np.where(treated, conversion_lift_by_week(week, effects["conversion"]), 0.0)
    auth_delta = np.where(treated, _map(brand, effects["authorization"]["absolute_delta_by_card_brand"]), 0.0)
    p_auth = p_auth_ctrl + auth_delta
    p_success = p_success_ctrl * (1 + lift)
    p_attempt = p_success / (p_auth * capture)
    if p_attempt.max() >= 1.0:
        raise ValueError("treatment attempt probability exceeds 1; lower attempt_cap")

    n = len(sessions)
    attempted = rng.random(n) < p_attempt
    authorized = attempted & (rng.random(n) < p_auth)
    captured = authorized & (rng.random(n) < capture)
    amount, currency = _amounts(rng, country, world)

    out = sessions.copy()
    out["_week"] = week
    out["_treated"] = treated
    out["_risk_tier"] = tier
    out["_p_success"] = p_success
    out["_attempted"] = attempted
    out["_authorized"] = authorized
    out["_captured"] = captured
    out["amount_total"] = amount
    out["currency"] = currency
    out["_card_brand"] = brand
    out["_card_country"] = country
    out["_card_funding"] = funding
    return out


def build_checkout_sessions(rng: np.random.Generator, funnel: pd.DataFrame, customer_ids: np.ndarray) -> pd.DataFrame:
    """Public checkout_sessions table shaped like Stripe Checkout Session objects."""
    n = len(funnel)
    out = pd.DataFrame(
        {
            "id": make_ids(rng, "cs_", n),
            "customer": customer_ids[funnel["_customer_idx"].to_numpy()],
            "created": funnel["created"].to_numpy(),
            "expires_at": funnel["created"].to_numpy() + SECONDS_PER_DAY,
            "mode": "payment",
            "status": np.where(funnel["_authorized"], "complete", "expired").astype(object),
            "payment_status": np.where(funnel["_captured"], "paid", "unpaid").astype(object),
            "amount_total": funnel["amount_total"].to_numpy(),
            "currency": funnel["currency"].to_numpy(),
            "payment_intent": make_ids(rng, "pi_", n),
        }
    )
    return out


def _decline_reasons(rng: np.random.Generator, treated: np.ndarray, reasons: dict[str, float]) -> np.ndarray:
    """Issuer decline reasons; treatment cannot produce incorrect_cvc because no CVC is sent."""
    keys = np.array(list(reasons), dtype=object)
    probs = np.array(list(reasons.values()), dtype=float)
    out = rng.choice(keys, size=treated.size, p=probs / probs.sum())
    no_cvc = probs * (keys != "incorrect_cvc")
    out[treated] = rng.choice(keys, size=int(treated.sum()), p=no_cvc / no_cvc.sum())
    return out


def build_charges(
    rng: np.random.Generator,
    funnel_df: pd.DataFrame,
    sessions_public: pd.DataFrame,
    world: dict[str, Any],
) -> pd.DataFrame:
    """Public charges table (one charge per attempted session) with flattened outcome fields.

    Also carries private `_risk_tier` and `_treated` columns for dispute simulation.
    """
    cfg = world["funnel"]
    att = funnel_df["_attempted"].to_numpy()
    f = funnel_df.loc[att]
    s = sessions_public.loc[att]
    n = len(f)
    tier = f["_risk_tier"].to_numpy()
    treated = f["_treated"].to_numpy()
    authorized = f["_authorized"].to_numpy()
    captured = f["_captured"].to_numpy()
    amount = f["amount_total"].to_numpy()

    declined = ~authorized
    blocked = declined & (rng.random(n) < _map(tier, cfg["blocked_share_of_declines_by_tier"]))
    issuer_declined = declined & ~blocked
    reason = np.full(n, None, dtype=object)
    reason[issuer_declined] = _decline_reasons(rng, treated[issuer_declined], cfg["issuer_decline_reasons"])
    reason[blocked] = "highest_risk_level"

    outcome_type = np.select([authorized, blocked], ["authorized", "blocked"], "issuer_declined").astype(object)
    network_status = np.select(
        [authorized, blocked], ["approved_by_network", "not_sent_to_network"], "declined_by_network"
    ).astype(object)
    elevated = rng.random(n) < _map(tier, cfg["elevated_risk_level_by_tier"])
    risk_level = np.select([blocked, elevated], ["highest", "elevated"], "normal").astype(object)

    failure_code = np.full(n, None, dtype=object)
    failure_code[declined] = "card_declined"
    for code in ("incorrect_cvc", "expired_card"):
        failure_code[reason == code] = code

    cvc_check = np.where(reason == "incorrect_cvc", "fail", "pass").astype(object)
    cvc_check[blocked | treated] = None

    delay = rng.uniform(cfg["charge_delay_seconds"]["min"], cfg["charge_delay_seconds"]["max"], n)
    return pd.DataFrame(
        {
            "id": make_ids(rng, "ch_", n),
            "payment_intent": s["payment_intent"].to_numpy(),
            "customer": s["customer"].to_numpy(),
            "created": s["created"].to_numpy() + delay.astype(np.int64),
            "amount": amount,
            "amount_captured": np.where(captured, amount, 0),
            "currency": f["currency"].to_numpy(),
            "status": np.where(authorized, "succeeded", "failed").astype(object),
            "captured": captured,
            "outcome_type": outcome_type,
            "outcome_reason": reason,
            "outcome_network_status": network_status,
            "outcome_risk_level": risk_level,
            "failure_code": failure_code,
            "card_brand": f["_card_brand"].to_numpy(),
            "card_country": f["_card_country"].to_numpy(),
            "card_funding": f["_card_funding"].to_numpy(),
            "cvc_check": cvc_check,
            "_risk_tier": tier,
            "_treated": treated,
        }
    ).reset_index(drop=True)
