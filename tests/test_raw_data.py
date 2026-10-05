"""Checks on the full generated dataset in data/raw. Run `make generate` first.

Baseline checks use the control arm only: treatment effects are not computed before pre-registration.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from scipy import stats

from generate.pipeline import RAW_TABLES
from generate.settings import load_settings, to_epoch

SETTINGS = load_settings()
pytestmark = [
    pytest.mark.full_data,
    pytest.mark.skipif(
        not all((SETTINGS.raw_dir / f"{t}.parquet").exists() for t in RAW_TABLES),
        reason="full dataset missing; run `make generate`",
    ),
]
START, END = to_epoch(SETTINGS.start_date), to_epoch(SETTINGS.end_date)


@pytest.fixture(scope="module")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    c = duckdb.connect()
    for t in RAW_TABLES:
        c.execute(f"create view {t} as select * from read_parquet('{(SETTINGS.raw_dir / f'{t}.parquet').as_posix()}')")
    yield c
    c.close()


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    return con.execute(sql).fetchone()[0]


# Row counts


def test_customer_count(con: duckdb.DuckDBPyConnection) -> None:
    assert scalar(con, "select count(*) from customers") == SETTINGS.n_customers


def test_experiment_session_count(con: duckdb.DuckDBPyConnection) -> None:
    n = scalar(con, f"select count(*) from checkout_sessions where created >= {START} and created < {END}")
    assert 1_350_000 <= n <= 1_650_000


def test_sessions_within_generated_range(con: duckdb.DuckDBPyConnection) -> None:
    pre_start = to_epoch(SETTINGS.pre_start_date)
    assert scalar(con, f"select count(*) from checkout_sessions where created < {pre_start} or created >= {END}") == 0


# Keys and referential integrity


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("customers", "id"),
        ("checkout_sessions", "id"),
        ("checkout_sessions", "payment_intent"),
        ("charges", "id"),
        ("charges", "payment_intent"),
        ("disputes", "id"),
        ("disputes", "charge"),
        ("experiment_assignments", "customer_id"),
    ],
)
def test_keys_unique_and_not_null(con: duckdb.DuckDBPyConnection, table: str, key: str) -> None:
    dupes_or_nulls = scalar(con, f"select count(*) - count(distinct {key}) from {table}")
    assert dupes_or_nulls == 0


@pytest.mark.parametrize(
    ("child", "fk", "parent", "pk"),
    [
        ("checkout_sessions", "customer", "customers", "id"),
        ("charges", "payment_intent", "checkout_sessions", "payment_intent"),
        ("charges", "customer", "customers", "id"),
        ("disputes", "charge", "charges", "id"),
        ("experiment_assignments", "customer_id", "customers", "id"),
        ("charges", "currency", "fx_rates", "currency"),
    ],
)
def test_referential_integrity(con: duckdb.DuckDBPyConnection, child: str, fk: str, parent: str, pk: str) -> None:
    orphans = scalar(
        con, f"select count(*) from {child} c left join {parent} p on c.{fk} = p.{pk} where p.{pk} is null"
    )
    assert orphans == 0


def test_every_customer_has_exactly_one_assignment(con: duckdb.DuckDBPyConnection) -> None:
    sql = """
        select count(*) from customers c
        left join experiment_assignments a on a.customer_id = c.id
        where a.customer_id is null
    """
    assert scalar(con, sql) == 0


def test_charge_belongs_to_session_customer(con: duckdb.DuckDBPyConnection) -> None:
    sql = (
        "select count(*) from charges c join checkout_sessions s using (payment_intent) where c.customer <> s.customer"
    )
    assert scalar(con, sql) == 0


def test_assigned_at_is_first_experiment_session(con: duckdb.DuckDBPyConnection) -> None:
    sql = f"""
        select count(*) from experiment_assignments a
        join (select customer, min(created) first_seen from checkout_sessions where created >= {START} group by 1) s
          on s.customer = a.customer_id
        where a.assigned_at <> s.first_seen
    """
    assert scalar(con, sql) == 0


# Assignment balance


def test_assignment_balance(con: duckdb.DuckDBPyConnection) -> None:
    n_treat = scalar(con, "select count(*) from experiment_assignments where variant = 'treatment'")
    n = SETTINGS.n_customers
    p_value = stats.chisquare([n_treat, n - n_treat]).pvalue
    assert p_value > 0.001
    assert abs(n_treat / n - SETTINGS.treatment_share) < 0.005


# Disputes timing and eligibility


def test_dispute_lag_between_7_and_60_days(con: duckdb.DuckDBPyConnection) -> None:
    sql = """
        select min(d.created - c.created) / 86400, max(d.created - c.created) / 86400
        from disputes d join charges c on c.id = d.charge
    """
    lo, hi = con.execute(sql).fetchone()
    assert lo >= 7 and hi <= 60


def test_disputes_only_on_captured_charges(con: duckdb.DuckDBPyConnection) -> None:
    assert scalar(con, "select count(*) from disputes d join charges c on c.id = d.charge where not c.captured") == 0


def test_disputes_observed_through_analysis_date(con: duckdb.DuckDBPyConnection) -> None:
    snapshot_end = to_epoch(SETTINGS.analysis_date) + 86_400
    assert scalar(con, "select max(created) from disputes") < snapshot_end


# Funnel consistency


def test_status_consistency(con: duckdb.DuckDBPyConnection) -> None:
    sql = """
        select count(*) from charges
        where (status = 'succeeded') <> (outcome_type = 'authorized')
           or (captured and status <> 'succeeded')
           or (captured <> (amount_captured > 0))
    """
    assert scalar(con, sql) == 0


def test_zero_decimal_currency_amounts(con: duckdb.DuckDBPyConnection) -> None:
    """JPY is stored in whole yen, so typical amounts are thousands, not hundreds of thousands."""
    median_jpy = scalar(con, "select median(amount_total) from checkout_sessions where currency = 'jpy'")
    assert 3_000 < median_jpy < 20_000


# Baseline rates (control arm, experiment window only)

CONTROL_SESSIONS = f"""
    select s.created, c.status as charge_status, c.captured from checkout_sessions s
    join experiment_assignments a on a.customer_id = s.customer and a.variant = 'control'
    left join charges c using (payment_intent)
    where s.created >= {START} and s.created < {END}
"""


@pytest.mark.parametrize(
    ("name", "expr", "lo", "hi"),
    [
        ("attempt rate", "avg((charge_status is not null)::int)", 0.50, 0.65),
        ("authorization rate", "sum((charge_status = 'succeeded')::int) / count(charge_status)", 0.89, 0.95),
        ("conversion rate", "avg(coalesce(captured, false)::int)", 0.45, 0.58),
    ],
)
def test_control_funnel_rates_in_band(
    con: duckdb.DuckDBPyConnection, name: str, expr: str, lo: float, hi: float
) -> None:
    rate = scalar(con, f"select {expr} from ({CONTROL_SESSIONS})")
    assert lo <= rate <= hi, f"{name} {rate:.4f} outside [{lo}, {hi}]"


def test_control_dispute_rate_in_band(con: duckdb.DuckDBPyConnection) -> None:
    sql = f"""
        select count(d.id) / count(*) from charges c
        join checkout_sessions s using (payment_intent)
        join experiment_assignments a on a.customer_id = c.customer and a.variant = 'control'
        left join disputes d on d.charge = c.id
        where c.captured and s.created >= {START} and s.created < {END}
    """
    assert 0.002 <= scalar(con, sql) <= 0.006


def test_new_customer_share_in_band(con: duckdb.DuckDBPyConnection) -> None:
    assert 0.30 <= scalar(con, f"select avg((created >= {START})::int) from customers") <= 0.40
