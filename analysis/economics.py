"""Unit economics of removing CVC: margin from extra conversions vs the cost of extra disputes.

Notation (per checkout session, control baseline):
    c  conversion rate (session -> captured charge)
    d  dispute rate per captured charge
    A  revenue per transaction (USD)
    L  relative conversion lift in treatment
    M  margin per successful sale   = (contribution_margin_rate - processing_fee_rate) * A - processing_fee_fixed
    K  expected cost per dispute    = dispute_fee + dispute_ops_cost + dispute_loss_rate * A

Net value per session of treatment vs control:
    V = c(1+L)M - c(1+L)(d + dd)K - (cM - cdK) = c[L*M - K(L*d + (1+L)*dd)]
Setting V = 0 gives the break-even dispute rate increase:
    dd* = L(M/K - d) / (1+L)

Conversion is measured end to end (session -> captured), so revenue lost to a lower authorization
rate is already inside L. `authorization_drop_value` reports it separately for attribution only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class UnitEconomics:
    """Per-sale margin and per-dispute expected cost, in USD."""

    margin_per_sale: float
    cost_per_dispute: float


def unit_economics(assumptions: dict[str, Any], revenue_per_transaction: float) -> UnitEconomics:
    """Compute M and K from labeled assumptions and the baseline revenue per transaction."""
    a = assumptions
    margin = (a["contribution_margin_rate"] - a["processing_fee_rate"]) * revenue_per_transaction
    margin -= a["processing_fee_fixed_usd"]
    cost = a["dispute_fee_usd"] + a["dispute_ops_cost_usd"] + a["dispute_loss_rate"] * revenue_per_transaction
    return UnitEconomics(margin_per_sale=margin, cost_per_dispute=cost)


def break_even_dispute_increase(lift_relative: float, dispute_rate: float, ue: UnitEconomics) -> float:
    """Absolute dispute rate increase dd* at which a relative conversion lift L is fully eaten."""
    return lift_relative * (ue.margin_per_sale / ue.cost_per_dispute - dispute_rate) / (1 + lift_relative)


def net_value_per_session(
    conversion_control: float,
    conversion_treatment: float,
    dispute_rate_control: float,
    dispute_rate_treatment: float,
    ue: UnitEconomics,
) -> float:
    """Expected USD value per session of treatment minus control."""
    sales = conversion_treatment - conversion_control
    disputes = conversion_treatment * dispute_rate_treatment - conversion_control * dispute_rate_control
    return sales * ue.margin_per_sale - disputes * ue.cost_per_dispute


def authorization_drop_value(
    attempts_per_session: float, authorization_delta: float, capture_rate: float, ue: UnitEconomics
) -> float:
    """USD per session attributable to the authorization change (already included in the conversion lift)."""
    return attempts_per_session * authorization_delta * capture_rate * ue.margin_per_sale


def customer_net_value(
    successful_sessions: np.ndarray,
    captured_usd: np.ndarray,
    disputes: np.ndarray,
    disputed_usd: np.ndarray,
    assumptions: dict[str, Any],
) -> np.ndarray:
    """Per-customer USD value: margin on captured sales minus expected dispute costs.

    Uses actual amounts rather than averages. Divided by sessions (a ratio metric), its arm difference
    is the net value per session, estimated with the same customer-clustered delta method as conversion.
    """
    a = assumptions
    margin = (a["contribution_margin_rate"] - a["processing_fee_rate"]) * captured_usd
    margin -= a["processing_fee_fixed_usd"] * successful_sessions
    cost = (a["dispute_fee_usd"] + a["dispute_ops_cost_usd"]) * disputes + a["dispute_loss_rate"] * disputed_usd
    return margin - cost
