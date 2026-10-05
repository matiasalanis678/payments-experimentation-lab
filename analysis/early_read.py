"""Three-way early dispute read: naive at experiment end, lag-adjusted, and matured final.

Reads are named as in config/prereg.yaml (early_dispute_read.reads) and dispatched by name.
The lag-adjusted read divides each arm's disputes observed by experiment end by the expected share of
eventual disputes already observed, sum over charges of F(age), where F is the dispute arrival curve fit
on pre-period charges that had matured by experiment end.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from analysis.estimators import Effect, delta_method_diff
from analysis.metrics import Pair, metric_fn
from analysis.population import EXPOSED_CUSTOMERS_SQL
from analysis.prereg import window_weeks
from generate.settings import load_settings


def empirical_cdf(lags: np.ndarray) -> np.ndarray:
    """Sorted lags defining F(t) = share of lags <= t."""
    return np.sort(np.asarray(lags, dtype=float))


def evaluate_cdf(sorted_lags: np.ndarray, ages: np.ndarray) -> np.ndarray:
    """F(age) for each charge age in days (0 for ages before the first possible dispute)."""
    return np.searchsorted(sorted_lags, ages, side="right") / sorted_lags.size


def arrival_lags(con: duckdb.DuckDBPyConnection, experiment_end: date, maturity_days: int) -> np.ndarray:
    """Dispute lags for pre-period captured charges that had matured by experiment end."""
    cutoff = experiment_end - timedelta(days=maturity_days)
    return (
        con.sql(f"""
            select c.dispute_lag_days
            from marts.fct_charges c
            join ({EXPOSED_CUSTOMERS_SQL}) pop using (customer_id)
            where c.period = 'pre_period' and c.is_captured and c.is_disputed_at_experiment_end
              and c.created_at < timestamp '{cutoff.isoformat()}'
        """)
        .df()["dispute_lag_days"]
        .to_numpy()
    )


def expected_completeness(
    con: duckdb.DuckDBPyConnection, prereg: dict[str, Any], window: str, sorted_lags: np.ndarray, experiment_end: date
) -> pd.Series:
    """Per customer: sum over captured in-window charges of F(age at experiment end)."""
    first, last = window_weeks(prereg, window)
    charges = con.sql(f"""
        select c.customer_id,
               date_diff('second', c.created_at, timestamp '{experiment_end.isoformat()}') / 86400.0 as age_days
        from marts.fct_charges c
        join ({EXPOSED_CUSTOMERS_SQL}) pop using (customer_id)
        where c.is_captured and c.experiment_week between {first} and {last}
    """).df()
    charges["completeness"] = evaluate_cdf(sorted_lags, charges["age_days"].to_numpy())
    return charges.groupby("customer_id")["completeness"].sum()


def _observed_over(den_col: str) -> Any:
    def metric(frame: pd.DataFrame, prereg: dict[str, Any]) -> Pair:
        return frame["disputes_at_experiment_end"].to_numpy(dtype=float), frame[den_col].to_numpy(dtype=float)

    return metric


def naive_observed(frame: pd.DataFrame, prereg: dict[str, Any]) -> Effect:
    """Disputes opened before experiment end / all captured charges."""
    return delta_method_diff(frame, _observed_over("captured"), prereg)


def lag_adjusted(frame: pd.DataFrame, prereg: dict[str, Any]) -> Effect:
    """Disputes opened before experiment end / expected share already observed (sum of F(age))."""
    return delta_method_diff(frame, _observed_over("expected_completeness"), prereg)


def matured_final(frame: pd.DataFrame, prereg: dict[str, Any]) -> Effect:
    """Matured dispute rate at the readout date (the guardrail metric)."""
    return delta_method_diff(frame, metric_fn(_guardrail_metric(prereg)), prereg)


def _guardrail_metric(prereg: dict[str, Any]) -> str:
    """The guardrail measured on matured charges."""
    return next(name for name, g in prereg["guardrails"].items() if "population" in g)


def read_fn(name: str) -> Any:
    """Look up a read by its pre-registered name."""
    return getattr(sys.modules[__name__], name)


def run_early_read(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame, prereg: dict[str, Any]) -> dict[str, Any]:
    """All pre-registered reads, plus the arrival curve summary."""
    settings = load_settings()
    spec = prereg["early_dispute_read"]
    lags = read_fn(spec["arrival_curve"]["method"])(
        arrival_lags(con, settings.end_date, settings.dispute_maturity_days)
    )
    window = prereg["guardrails"][_guardrail_metric(prereg)]["window"]
    completeness = expected_completeness(con, prereg, window, lags, settings.end_date)
    frame = frame.assign(expected_completeness=frame["customer_id"].map(completeness).fillna(0.0))
    reads = {name: read_fn(name)(frame, prereg) for name in spec["reads"]}
    return {
        "reads": reads,
        "arrival_curve": {
            "n_disputes": int(lags.size),
            "median_lag_days": float(np.median(lags)),
            "share_by_week": {
                str(d): float(evaluate_cdf(lags, np.array([d]))[0])
                for d in range(7, settings.dispute_maturity_days + 1, 7)
            },
        },
    }


def dispute_mix_by_arm(con: duckdb.DuckDBPyConnection, prereg: dict[str, Any]) -> dict[str, Any]:
    """EXPLORATORY: dispute reason and lag by arm on matured in-window charges (tests the lag hypothesis)."""
    first, last = window_weeks(prereg, prereg["guardrails"][_guardrail_metric(prereg)]["window"])
    d = con.sql(f"""
        select pop.variant, c.dispute_reason, c.dispute_lag_days
        from marts.fct_charges c
        join ({EXPOSED_CUSTOMERS_SQL}) pop using (customer_id)
        where c.is_disputed and c.is_matured and c.experiment_week between {first} and {last}
    """).df()
    by_arm = d.groupby("variant").agg(
        disputes=("dispute_lag_days", "size"),
        median_lag_days=("dispute_lag_days", "median"),
        share_fraudulent=("dispute_reason", lambda r: float((r == "fraudulent").mean())),
    )
    arms = sorted(d["variant"].unique())
    ks = stats.ks_2samp(*(d.loc[d["variant"] == a, "dispute_lag_days"] for a in arms))
    return {"by_arm": by_arm.to_dict(orient="index"), "lag_ks_p_value": float(ks.pvalue), "label": "exploratory"}
