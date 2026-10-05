"""Pre-experiment A/A check: pre-period conversion and covariate balance between arms.

Reads the dbt marts and uses exposed customers only.

Uses only pre-period outcomes and customer attributes, so it never measures a treatment effect.
Run `uv run python -m analysis.preperiod` to check the configured salt, or add
`--scan N` to evaluate the next N candidate salts with the pre-registered selection rule.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from analysis.stats import RatioDiff, clustered_ratio, diff_in_ratios
from generate.assignment import CONTROL, TREATMENT, assign_variants
from generate.settings import load_settings

COVARIATES = ("country", "card_brand", "card_funding", "is_returning", "account_age_band")
MAX_ABS_Z = 2.0  # salt selection rule: pre-period conversion |z| below this
MIN_COVARIATE_P = 0.05  # salt selection rule: every covariate chi-square p above this


@dataclass(frozen=True)
class AAResult:
    """Outcome of the pre-experiment A/A check for one assignment."""

    conversion: RatioDiff
    covariate_p_values: dict[str, float]

    def passes(self, max_abs_z: float = MAX_ABS_Z, min_p: float = MIN_COVARIATE_P) -> bool:
        """True if pre-period conversion and all covariates are balanced."""
        return abs(self.conversion.z) < max_abs_z and min(self.covariate_p_values.values()) > min_p


def load_customers(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per exposed customer: variant, observable covariates, and pre-period sessions and successes."""
    return con.sql("""
        select
            e.customer_id,
            e.variant,
            c.country,
            c.card_brand,
            c.card_funding,
            c.is_returning,
            c.account_age_band,
            e.pre_period_sessions,
            e.pre_period_successful_sessions
        from marts.dim_experiment e
        join marts.dim_customers c using (customer_id)
        where e.is_exposed
    """).df()


def aa_check(customers: pd.DataFrame, variant: np.ndarray) -> AAResult:
    """Clustered pre-period conversion difference and chi-square balance on observable covariates."""
    arms = {}
    for arm in (CONTROL, TREATMENT):
        d = customers.loc[(variant == arm) & (customers["pre_period_sessions"] > 0)]
        arms[arm] = clustered_ratio(d["pre_period_successful_sessions"].to_numpy(), d["pre_period_sessions"].to_numpy())
    p_values = {col: float(stats.chi2_contingency(pd.crosstab(customers[col], variant)).pvalue) for col in COVARIATES}
    return AAResult(conversion=diff_in_ratios(arms[CONTROL], arms[TREATMENT]), covariate_p_values=p_values)


def candidate_salts(base_salt: str, n: int) -> list[str]:
    """Deterministic candidate sequence: <base without _vK>_v2, _v3, ..."""
    stem = base_salt.rsplit("_v", 1)[0]
    return [f"{stem}_v{k}" for k in range(2, n + 2)]


def _report(salt: str, result: AAResult) -> str:
    c = result.conversion
    worst = min(result.covariate_p_values, key=result.covariate_p_values.get)
    return (
        f"{salt:<22} pre-period diff {c.diff * 100:+.3f}pp  clustered SE {c.se * 100:.3f}pp  z={c.z:+.2f}  "
        f"min covariate p={result.covariate_p_values[worst]:.3f} ({worst})  {'PASS' if result.passes() else 'FAIL'}"
    )


def main(argv: list[str] | None = None) -> None:
    """Print the A/A check for the configured salt, optionally scanning candidate salts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=int, default=0, help="evaluate this many candidate salts")
    args = parser.parse_args(argv)

    settings = load_settings()
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        customers = load_customers(con)
    ids = customers["customer_id"].to_numpy()
    for salt in [settings.hash_salt, *candidate_salts(settings.hash_salt, args.scan)]:
        print(_report(salt, aa_check(customers, assign_variants(ids, salt, settings.treatment_share))))


if __name__ == "__main__":
    main()
