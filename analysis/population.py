"""The analysis population: exposed customers only. Every SRM and analysis input builds on this."""

from __future__ import annotations

import duckdb

# Customers with at least one in-window session. Assigned but never-exposed customers never saw
# either checkout, so including them would dilute effects and distort the SRM check.
EXPOSED_CUSTOMERS_SQL = """
    select
        customer_id,
        variant,
        first_exposure_at,
        pre_period_sessions,
        pre_period_successful_sessions
    from marts.dim_experiment
    where is_exposed
"""


def srm_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Exposed customers per variant: the input to the sample ratio mismatch check."""
    rows = con.sql(f"select variant, count(*) from ({EXPOSED_CUSTOMERS_SQL}) group by variant").fetchall()
    return {variant: int(n) for variant, n in rows}
