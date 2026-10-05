"""Finance-style reconciliation: every MetricFlow metric must tie out to hand-written SQL on the marts.

Pooled across variants, experiment window only (no treatment comparison). Counts must match exactly,
currency to the cent, and ratios to 6 decimals. The hand SQL filters on raw timestamps rather than the
dbt `period` column, so it independently checks the window logic too.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from generate.settings import PROJECT_ROOT, load_settings

SETTINGS = load_settings()
START, END = SETTINGS.start_date.isoformat(), SETTINGS.end_date.isoformat()
pytestmark = [
    pytest.mark.full_data,
    pytest.mark.skipif(not SETTINGS.warehouse_path.exists(), reason="run `make generate dbt` first"),
]

COUNTS = [
    "sessions",
    "successful_sessions",
    "attempted_charges",
    "authorized_charges",
    "successful_charges",
    "disputed_charges",
    "disputed_charges_at_experiment_end",
]
CURRENCY = ["total_payment_volume"]
RATIOS = [
    "checkout_conversion_rate",
    "authorization_rate",
    "revenue_per_transaction",
    "dispute_rate",
    "dispute_rate_observed_at_experiment_end",
]

HAND_SQL = f"""
with sessions as (
    select
        count(*) as sessions,
        count(*) filter (where is_succeeded) as successful_sessions
    from marts.fct_checkout_sessions
    where created_at >= timestamp '{START}' and created_at < timestamp '{END}'
),
charges as (
    select
        count(*) as attempted_charges,
        count(*) filter (where is_authorized) as authorized_charges,
        count(*) filter (where is_captured) as successful_charges,
        count(*) filter (where is_disputed) as disputed_charges,
        count(*) filter (where is_disputed_at_experiment_end) as disputed_charges_at_experiment_end,
        count(*) filter (where is_disputed and is_matured) as matured_disputed_charges,
        count(*) filter (where is_captured and is_matured) as matured_successful_charges,
        sum(captured_amount_usd) as total_payment_volume
    from marts.fct_charges
    where session_created_at >= timestamp '{START}' and session_created_at < timestamp '{END}'
)
select
    sessions.*,
    charges.* exclude (matured_disputed_charges, matured_successful_charges),
    successful_sessions / sessions as checkout_conversion_rate,
    authorized_charges / attempted_charges as authorization_rate,
    total_payment_volume / successful_charges as revenue_per_transaction,
    matured_disputed_charges / matured_successful_charges as dispute_rate,
    disputed_charges_at_experiment_end / successful_charges as dispute_rate_observed_at_experiment_end
from sessions, charges
"""


@pytest.fixture(scope="module")
def mf_result(tmp_path_factory: pytest.TempPathFactory) -> pd.Series:
    out: Path = tmp_path_factory.mktemp("mf") / "reconciliation.csv"
    where = (
        f"{{{{ TimeDimension('metric_time', 'day') }}}} >= '{START}' "
        f"and {{{{ TimeDimension('metric_time', 'day') }}}} < '{END}'"
    )
    subprocess.run(
        ["uv", "run", "mf", "query", "--metrics", ",".join(COUNTS + CURRENCY + RATIOS), "--where", where,
         "--csv", str(out)],
        cwd=PROJECT_ROOT / "dbt",
        check=True,
        capture_output=True,
    )  # fmt: skip
    return pd.read_csv(out).iloc[0]


@pytest.fixture(scope="module")
def sql_result() -> pd.Series:
    with duckdb.connect(str(SETTINGS.warehouse_path), read_only=True) as con:
        return con.sql(HAND_SQL).df().iloc[0]


@pytest.mark.parametrize("metric", COUNTS)
def test_counts_tie_out_exactly(metric: str, mf_result: pd.Series, sql_result: pd.Series) -> None:
    assert int(mf_result[metric]) == int(sql_result[metric])


@pytest.mark.parametrize("metric", CURRENCY)
def test_currency_ties_out_to_the_cent(metric: str, mf_result: pd.Series, sql_result: pd.Series) -> None:
    assert round(float(mf_result[metric]), 2) == round(float(sql_result[metric]), 2)


@pytest.mark.parametrize("metric", RATIOS)
def test_ratios_tie_out_to_6_decimals(metric: str, mf_result: pd.Series, sql_result: pd.Series) -> None:
    assert abs(float(mf_result[metric]) - float(sql_result[metric])) < 5e-7
