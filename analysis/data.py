"""Customer-level inputs for the experiment analysis, built from the dbt marts (exposed customers only)."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from analysis.population import EXPOSED_CUSTOMERS_SQL
from analysis.prereg import window_weeks

_CUSTOMER_WINDOW_SQL = """
    with sessions as (
        select customer_id, count(*) as sessions, count(*) filter (where is_succeeded) as successful_sessions
        from marts.fct_checkout_sessions
        where experiment_week between {first} and {last}
        group by customer_id
    ),
    charges as (
        select
            customer_id,
            count(*) as attempts,
            count(*) filter (where is_authorized) as authorized,
            count(*) filter (where is_captured) as captured,
            coalesce(sum(captured_amount_usd), 0) as captured_usd,
            count(*) filter (where is_captured and is_matured) as matured_captured,
            count(*) filter (where is_disputed and is_matured) as matured_disputes,
            coalesce(sum(disputed_amount_usd) filter (where is_matured), 0) as matured_disputed_usd,
            count(*) filter (where is_disputed_at_experiment_end) as disputes_at_experiment_end
        from marts.fct_charges
        where experiment_week between {first} and {last}
        group by customer_id
    )
    select
        pop.customer_id,
        pop.variant,
        pop.pre_period_sessions,
        pop.pre_period_successful_sessions,
        customers.* exclude (customer_id),
        sessions.* exclude (customer_id),
        charges.* exclude (customer_id)
    from ({exposed}) pop
    join marts.dim_customers customers using (customer_id)
    join sessions using (customer_id)
    left join charges using (customer_id)
    order by pop.customer_id  -- stable row order so seeded resampling is reproducible
"""

COUNT_COLUMNS = (
    "attempts",
    "authorized",
    "captured",
    "captured_usd",
    "matured_captured",
    "matured_disputes",
    "matured_disputed_usd",
    "disputes_at_experiment_end",
)


def load_customer_window(con: duckdb.DuckDBPyConnection, prereg: dict[str, Any], window: str) -> pd.DataFrame:
    """One row per exposed customer with at least one session in the window: variant, segments, and sums."""
    first, last = window_weeks(prereg, window)
    sql = _CUSTOMER_WINDOW_SQL.format(first=first, last=last, exposed=EXPOSED_CUSTOMERS_SQL)
    frame = con.sql(sql).df()
    frame[list(COUNT_COLUMNS)] = frame[list(COUNT_COLUMNS)].fillna(0)
    return frame


def load_customer_week(con: duckdb.DuckDBPyConnection, prereg: dict[str, Any], week: int) -> pd.DataFrame:
    """Customer frame for a single experiment week."""
    return load_customer_window(con, {"windows": {"_week": {"first_week": week, "last_week": week}}}, "_week")
