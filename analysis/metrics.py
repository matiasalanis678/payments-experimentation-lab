"""Metric definitions as per-customer (numerator, denominator) pairs.

Function names match the metric names in config/prereg.yaml, so analysis code dispatches with
`metric_fn(name)` instead of comparing strings. Every metric is a ratio of sums over customers.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from analysis.economics import customer_net_value

Pair = tuple[np.ndarray, np.ndarray]
MetricFn = Callable[[pd.DataFrame, dict[str, Any]], Pair]


def _pair(frame: pd.DataFrame, num: str, den: str) -> Pair:
    return frame[num].to_numpy(dtype=float), frame[den].to_numpy(dtype=float)


def checkout_conversion_rate(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
    """Successful (captured) sessions / sessions."""
    return _pair(frame, "successful_sessions", "sessions")


def authorization_rate(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
    """Authorized charges / attempted charges."""
    return _pair(frame, "authorized", "attempts")


def revenue_per_transaction(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
    """Captured USD / captured charges."""
    return _pair(frame, "captured_usd", "captured")


def dispute_rate(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
    """Disputes / captured charges, matured charges only."""
    return _pair(frame, "matured_disputes", "matured_captured")


def net_value_per_session(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
    """USD net value (margin on sales minus expected dispute cost) / sessions, using prereg assumptions."""
    value = customer_net_value(
        frame["captured"].to_numpy(dtype=float),
        frame["captured_usd"].to_numpy(dtype=float),
        frame["matured_disputes"].to_numpy(dtype=float),
        frame["matured_disputed_usd"].to_numpy(dtype=float),
        prereg["economics"]["assumptions"],
    )
    return value, frame["sessions"].to_numpy(dtype=float)


def pre_period_conversion(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
    """Pre-period successful sessions / pre-period sessions (CUPED covariate)."""
    return _pair(frame, "pre_period_successful_sessions", "pre_period_sessions")


def metric_fn(name: str) -> MetricFn:
    """Look up a metric function by its pre-registered name."""
    return getattr(sys.modules[__name__], name)
