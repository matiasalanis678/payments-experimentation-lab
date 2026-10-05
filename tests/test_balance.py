"""Permanent pre-experiment A/A checks on the generated warehouse (observable data only)."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from analysis.preperiod import AAResult, aa_check, load_customers
from generate.settings import load_settings

SETTINGS = load_settings()
pytestmark = [
    pytest.mark.full_data,
    pytest.mark.skipif(not SETTINGS.warehouse_path.exists(), reason="warehouse missing; run `make generate`"),
]


@pytest.fixture(scope="module")
def aa() -> AAResult:
    with duckdb.connect(str(SETTINGS.warehouse_path), read_only=True) as con:
        customers = load_customers(con, SETTINGS)
        variants = con.sql("select customer_id, variant from raw.experiment_assignments").df()
    customers = customers.merge(variants, on="customer_id", validate="one_to_one")
    return aa_check(customers, customers["variant"].to_numpy())


def test_preperiod_conversion_within_3_clustered_ses(aa: AAResult) -> None:
    assert abs(aa.conversion.z) < 3, f"pre-period A/A z={aa.conversion.z:+.2f}"


def test_observable_covariates_balanced(aa: AAResult) -> None:
    failing = {k: p for k, p in aa.covariate_p_values.items() if p <= 0.001}
    assert not failing, pd.Series(failing)
