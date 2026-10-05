"""End-to-end check that never-exposed customers are excluded from SRM and analysis inputs.

The main dataset exposes every customer, so this builds a separate mini warehouse: a small generator
run where a few returning customers lose all in-window activity (they stay assigned and keep their
pre-period sessions). dbt builds the marts on it, then the Python loaders and MetricFlow are checked.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from analysis.population import srm_counts
from analysis.preperiod import load_customers
from generate.pipeline import load_warehouse
from generate.settings import PROJECT_ROOT, load_settings, to_epoch

N_CUSTOMERS = 1_500
N_UNEXPOSED = 25
START = to_epoch(load_settings().start_date)


def _strip_in_window_activity(raw: Path, customers: set[str]) -> None:
    """Delete in-window sessions, their charges, and those charges' disputes for `customers`."""
    sessions = pd.read_parquet(raw / "checkout_sessions.parquet")
    drop = sessions["customer"].isin(customers) & (sessions["created"] >= START)
    dropped_pis = set(sessions.loc[drop, "payment_intent"])
    sessions.loc[~drop].to_parquet(raw / "checkout_sessions.parquet", index=False)

    charges = pd.read_parquet(raw / "charges.parquet")
    drop_charges = charges["payment_intent"].isin(dropped_pis)
    dropped_charge_ids = set(charges.loc[drop_charges, "id"])
    charges.loc[~drop_charges].to_parquet(raw / "charges.parquet", index=False)

    disputes = pd.read_parquet(raw / "disputes.parquet")
    disputes.loc[~disputes["charge"].isin(dropped_charge_ids)].to_parquet(raw / "disputes.parquet", index=False)


@pytest.fixture(scope="module")
def mini(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, set[str]]:
    root = tmp_path_factory.mktemp("mini")
    raw, truth = root / "raw", root / "truth"
    subprocess.run(
        [sys.executable, "-m", "generate", "--n-customers", str(N_CUSTOMERS), "--raw-dir", str(raw),
         "--truth-dir", str(truth), "--skip-load"],
        check=True,
        capture_output=True,
    )  # fmt: skip

    sessions = pd.read_parquet(raw / "checkout_sessions.parquet")
    with_pre = sessions.loc[sessions["created"] < START, "customer"].drop_duplicates().sort_values()
    unexposed = set(with_pre.iloc[:N_UNEXPOSED])
    _strip_in_window_activity(raw, unexposed)

    warehouse = root / "warehouse.duckdb"  # dbt views reference the catalog by file name
    load_warehouse(raw, warehouse)
    env = {**os.environ, "DBT_DUCKDB_PATH": str(warehouse)}
    dbt_dir = PROJECT_ROOT / "dbt"
    subprocess.run(
        ["uv", "run", "dbt", "run", "--target-path", str(root / "target")],
        cwd=dbt_dir, env=env, check=True, capture_output=True,
    )  # fmt: skip
    return warehouse, unexposed


def test_dim_experiment_flags_unexposed(mini: tuple[Path, set[str]]) -> None:
    warehouse, unexposed = mini
    with duckdb.connect(str(warehouse), read_only=True) as con:
        flags = con.sql("select customer_id, is_exposed from marts.dim_experiment").df()
    assert len(flags) == N_CUSTOMERS
    assert set(flags.loc[~flags["is_exposed"], "customer_id"]) == unexposed


def test_srm_counts_exclude_unexposed(mini: tuple[Path, set[str]]) -> None:
    warehouse, _ = mini
    with duckdb.connect(str(warehouse), read_only=True) as con:
        counts = srm_counts(con)
    assert sum(counts.values()) == N_CUSTOMERS - N_UNEXPOSED


def test_analysis_loader_excludes_unexposed(mini: tuple[Path, set[str]]) -> None:
    warehouse, unexposed = mini
    with duckdb.connect(str(warehouse), read_only=True) as con:
        customers = load_customers(con)
    assert len(customers) == N_CUSTOMERS - N_UNEXPOSED
    assert not unexposed & set(customers["customer_id"])


def test_metricflow_exposure_filter_excludes_unexposed(mini: tuple[Path, set[str]], tmp_path: Path) -> None:
    """The pre-period A/A saved query must drop the unexposed customers' pre-period sessions."""
    warehouse, _ = mini
    out = tmp_path / "pre.csv"
    subprocess.run(
        ["uv", "run", "mf", "query", "--saved-query", "preperiod_by_variant", "--csv", str(out)],
        cwd=PROJECT_ROOT / "dbt", env={**os.environ, "DBT_DUCKDB_PATH": str(warehouse)},
        check=True, capture_output=True,
    )  # fmt: skip
    mf_sessions = int(pd.read_csv(out)["sessions"].sum())
    with duckdb.connect(str(warehouse), read_only=True) as con:
        total, exposed = con.sql("""
            select count(*), count(*) filter (where e.is_exposed)
            from marts.fct_checkout_sessions s join marts.dim_experiment e using (customer_id)
            where s.period = 'pre_period'
        """).fetchone()
    assert mf_sessions == exposed < total
