"""Recovery test: the analysis must recover the effects planted by the generator.

Truth exception (see CONVENTIONS.md): this is the only test allowed to read config/truth.yaml. It reads the
analysis output (reports/results/results.json) and checks that each 95% CI contains the planted effect.
Where the planted value is defined per week or per card brand, the expected pooled value is computed with
the experiment's own traffic weights.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pytest

from generate.sessions import conversion_lift_by_week
from generate.settings import PROJECT_ROOT, load_settings
from generate.truth import load_truth

SETTINGS = load_settings()
RESULTS = PROJECT_ROOT / "reports" / "results" / "results.json"
pytestmark = [
    pytest.mark.full_data,
    pytest.mark.skipif(not RESULTS.exists(), reason="run `make analyze` first"),
]
EFFECTS = load_truth()["effects"]


@pytest.fixture(scope="module")
def results() -> dict[str, Any]:
    return json.loads(RESULTS.read_text())


@pytest.fixture(scope="module")
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(str(SETTINGS.warehouse_path), read_only=True)
    yield c
    c.close()


def _expected_conversion_lift(con: duckdb.DuckDBPyConnection, first: int, last: int) -> float:
    """Planted lift pooled over weeks, weighted by control successes per week (the estimator's weights)."""
    w = con.sql(f"""
        select experiment_week, count(*) filter (where is_succeeded) as successes
        from marts.fct_checkout_sessions
        where variant = 'control' and experiment_week between {first} and {last}
        group by 1 order by 1
    """).df()
    lifts = conversion_lift_by_week(w["experiment_week"].to_numpy(), EFFECTS["conversion"])
    return float((w["successes"] * (1 + lifts)).sum() / w["successes"].sum() - 1)


def _contains(effect: dict[str, Any], value: float, relative: bool = True) -> bool:
    lo, hi = (
        (effect["relative_ci_low"], effect["relative_ci_high"]) if relative else (effect["ci_low"], effect["ci_high"])
    )
    return lo <= value <= hi


def test_primary_conversion_lift_recovered(results: dict[str, Any], con: duckdb.DuckDBPyConnection) -> None:
    expected = _expected_conversion_lift(con, 1, SETTINGS.weeks)
    effect = results["primary"]["effect"]
    assert _contains(effect, expected), (expected, effect["relative_ci_low"], effect["relative_ci_high"])


def test_steady_state_lift_recovered(results: dict[str, Any], con: duckdb.DuckDBPyConnection) -> None:
    effect = results["secondary"]["steady_state"]
    expected = _expected_conversion_lift(con, 3, SETTINGS.weeks)
    assert _contains(effect, expected), (expected, effect["relative_ci_low"], effect["relative_ci_high"])


def test_week_one_novelty_recovered(results: dict[str, Any]) -> None:
    expected = float(conversion_lift_by_week(np.array([1]), EFFECTS["conversion"])[0])
    assert _contains(results["secondary"]["weekly"]["1"], expected)


def _expected_auth_delta(con: duckdb.DuckDBPyConnection) -> float:
    """Planted per-brand deltas, weighted by treatment attempts per brand."""
    attempts = con.sql("""
        select card_brand, count(*) as n from marts.fct_charges
        where variant = 'treatment' and period = 'experiment' group by 1
    """).df()
    deltas = attempts["card_brand"].map(EFFECTS["authorization"]["absolute_delta_by_card_brand"])
    return float((attempts["n"] * deltas).sum() / attempts["n"].sum())


def test_authorization_delta_recovered(results: dict[str, Any], con: duckdb.DuckDBPyConnection) -> None:
    expected = _expected_auth_delta(con)
    assert abs(expected - EFFECTS["authorization"]["expected_overall_absolute_delta"]) < 0.0005
    assert _contains(results["guardrails"]["authorization_rate"]["effect"], expected, relative=False)


def test_revenue_per_transaction_unchanged(results: dict[str, Any]) -> None:
    assert _contains(
        results["guardrails"]["revenue_per_transaction"]["effect"], EFFECTS["revenue_per_transaction"]["relative_lift"]
    )


def test_dispute_lift_calibrated_given_realized_mix(con: duckdb.DuckDBPyConnection) -> None:
    """The generator plants +40% exactly in expectation: check the expected lift given each arm's realized
    hidden risk mix of matured captured charges (base rates times planted tier lifts)."""
    world = load_truth()["world"]["disputes"]
    tiers = pd.read_parquet(SETTINGS.truth_dir / "customer_risk_tiers.parquet")
    charges = (
        con.sql("""
        select customer_id, variant from marts.fct_charges
        where period = 'experiment' and is_captured and is_matured
    """)
        .df()
        .merge(tiers, on="customer_id")
    )
    base = charges["risk_tier"].map(world["base_rate_by_tier"])
    by_arm = base.groupby(charges["variant"]).mean()
    tier_counts = charges.loc[charges["variant"] == "treatment", "risk_tier"].value_counts()
    weights = tier_counts * pd.Series(world["base_rate_by_tier"])
    planted = EFFECTS["dispute"]["relative_lift_by_risk_tier"]
    fixed = sum(weights[t] * (1 + planted[t]) for t in planted)
    high = ((1 + EFFECTS["dispute"]["overall_relative_lift"]) * weights.sum() - fixed) / weights["high"] - 1
    lifts = charges["risk_tier"].map({**planted, "high": high})
    expected_t = (base * (1 + lifts))[charges["variant"] == "treatment"].mean()
    expected_lift = expected_t / by_arm["control"] - 1
    assert abs(expected_lift - EFFECTS["dispute"]["overall_relative_lift"]) < 0.02


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known 95% miss: observed +30.3% [21.0%, 39.7%] vs planted +40%. Given each arm's realized hidden "
        "risk mix the expected lift is +39.9% (see the calibration test), so the gap is Bernoulli noise in "
        "dispute draws: control +1.2 SD, treatment -1.7 SD, about 2 SE combined (p ~ 0.05)."
    ),
)
def test_dispute_lift_recovered(results: dict[str, Any]) -> None:
    effect = results["guardrails"]["dispute_rate"]["effect"]
    assert _contains(effect, EFFECTS["dispute"]["overall_relative_lift"])


# Coverage simulation (`make coverage`, marked slow, excluded from `make all`).
# Post-hoc method validation added after the dispute CI missed (logged in reports/deviations.md):
# rerun generator + dbt + the pre-registered estimators across many seeds at reduced scale and
# measure how often each 95% CI contains the planted value.

COVERAGE_SEEDS = 200
COVERAGE_CUSTOMERS = 50_000
COVERAGE_LEVEL_CHECK = 0.99  # nominal 95% must sit inside this Clopper-Pearson interval of empirical coverage
COVERAGE_JSON = PROJECT_ROOT / "reports" / "coverage.json"  # outside results/: `make all` does not rerun it
COVERAGE_MD = PROJECT_ROOT / "reports" / "coverage.md"


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True)


def _coverage_one_seed(seed: int, workdir: Path) -> list[dict[str, Any]]:
    """Generate, build, and analyze one small world; return each quantity's CI and planted value."""
    from analysis.data import load_customer_week, load_customer_window
    from analysis.estimators import estimate
    from analysis.prereg import load_prereg
    from generate.pipeline import load_warehouse

    prereg = load_prereg()
    d = workdir / f"seed_{seed}"
    _run([sys.executable, "-m", "generate", "--seed", str(seed), "--n-customers", str(COVERAGE_CUSTOMERS),
          "--raw-dir", str(d / "raw"), "--truth-dir", str(d / "truth"), "--skip-load"])  # fmt: skip
    warehouse = d / "warehouse.duckdb"
    load_warehouse(d / "raw", warehouse)
    env = {**os.environ, "DBT_DUCKDB_PATH": str(warehouse)}
    _run(["uv", "run", "dbt", "run", "--exclude", "metricflow_time_spine", "--target-path", str(d / "target"),
          "--log-path", str(d / "logs"), "-q"], cwd=PROJECT_ROOT / "dbt", env=env)  # fmt: skip

    alpha = prereg["alpha"]
    with duckdb.connect(str(warehouse), read_only=True) as c:
        full = load_customer_window(c, prereg, "full")
        steady = load_customer_window(c, prereg, "steady_state")
        week1 = load_customer_week(c, prereg, 1)
        planted = {
            "conversion_full": _expected_conversion_lift(c, 1, SETTINGS.weeks),
            "conversion_weeks_3_8": _expected_conversion_lift(c, 3, SETTINGS.weeks),
            "conversion_week_1": float(conversion_lift_by_week(np.array([1]), EFFECTS["conversion"])[0]),
            "authorization_delta": _expected_auth_delta(c),
        }
    conv = "checkout_conversion_rate"
    checks = [
        ("conversion_full", estimate("delta_method_diff", full, conv, prereg), True),
        ("conversion_weeks_3_8", estimate("delta_method_diff", steady, conv, prereg), True),
        ("conversion_week_1", estimate("delta_method_diff", week1, conv, prereg), True),
        ("authorization_delta", estimate("delta_method_diff", full, "authorization_rate", prereg), False),
        ("revenue_per_transaction", estimate("delta_method_diff", full, "revenue_per_transaction", prereg), True),
        ("dispute_rate", estimate("delta_method_diff", full, "dispute_rate", prereg), True),
        ("conversion_full_naive (extra)", estimate("naive_two_proportion", full, conv, prereg), True),
        ("conversion_full_cuped (extra)", estimate("cuped_delta_method", full, conv, prereg), True),
    ]  # fmt: skip
    planted |= {
        "revenue_per_transaction": EFFECTS["revenue_per_transaction"]["relative_lift"],
        "dispute_rate": EFFECTS["dispute"]["overall_relative_lift"],
        "conversion_full_naive (extra)": planted["conversion_full"],
        "conversion_full_cuped (extra)": planted["conversion_full"],
    }
    rows = []
    for name, effect, relative in checks:
        lo, hi = effect.relative_ci(alpha) if relative else effect.z_ci(alpha)
        rows.append({"seed": seed, "quantity": name, "planted": planted[name], "ci_low": lo, "ci_high": hi,
                     "covered": bool(lo <= planted[name] <= hi)})  # fmt: skip
    shutil.rmtree(d, ignore_errors=True)
    return rows


def _write_coverage(runs: pd.DataFrame, elapsed: float) -> pd.DataFrame:
    from statsmodels.stats.proportion import proportion_confint

    summary = runs.groupby("quantity", sort=False)["covered"].agg(["sum", "count"])
    summary["coverage"] = summary["sum"] / summary["count"]
    lo95, hi95 = proportion_confint(summary["sum"], summary["count"], alpha=0.05, method="beta")
    lo99, hi99 = proportion_confint(summary["sum"], summary["count"], alpha=1 - COVERAGE_LEVEL_CHECK, method="beta")
    summary = summary.assign(ci95_low=lo95, ci95_high=hi95, ci99_low=lo99, ci99_high=hi99)
    COVERAGE_JSON.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_JSON.write_text(json.dumps({
        "seeds": int(runs["seed"].nunique()), "customers_per_seed": COVERAGE_CUSTOMERS, "elapsed_seconds": elapsed,
        "label": "exploratory (post-hoc method validation)",
        "coverage": summary.round(4).reset_index().to_dict(orient="records"),
    }, indent=2))  # fmt: skip
    lines = [
        "# CI coverage simulation",
        "",
        "Post-hoc method validation, added after the overall dispute CI missed its planted value (see",
        "reports/deviations.md). Exploratory: not part of the pre-registration.",
        "",
        f"{runs['seed'].nunique()} independent worlds (generator seeds), {COVERAGE_CUSTOMERS:,} customers each "
        f"(a quarter of full scale), each built with dbt and analyzed with the pre-registered estimators. "
        f"Each row is the share of seeds whose 95% CI contains the planted value, with a Clopper-Pearson 95% "
        f"interval. Runtime {elapsed / 60:.1f} minutes. Seeds were not re-randomized by the A/A rule.",
        "",
        "| Quantity | Covered | Coverage | 95% interval |",
        "|---|---|---|---|",
        *[f"| {q} | {int(r['sum'])}/{int(r['count'])} | {r['coverage']:.1%} | "
          f"[{r['ci95_low']:.1%}, {r['ci95_high']:.1%}] |" for q, r in summary.iterrows()],
        "",
        "Rows marked (extra) are not recovery checks: the naive binomial CI ignores customer clustering, and",
        "CUPED is a secondary estimator.",
        "",
    ]  # fmt: skip
    COVERAGE_MD.write_text("\n".join(lines))
    return summary


@pytest.mark.slow
def test_ci_coverage_simulation(tmp_path: Path) -> None:
    """Pre-specified check: for each pre-registered CI, nominal 95% lies in the 99% interval of coverage."""
    start = time.perf_counter()
    workers = max(1, (os.cpu_count() or 2) - 2)
    seeds = [SETTINGS.seed + 1 + k for k in range(COVERAGE_SEEDS)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = pd.DataFrame(
            [row for rows in pool.map(lambda s: _coverage_one_seed(s, tmp_path), seeds) for row in rows]
        )
    summary = _write_coverage(runs, time.perf_counter() - start)
    checked = summary.loc[[q for q in summary.index if "(extra)" not in q]]
    off = checked.loc[(checked["ci99_low"] > 0.95) | (checked["ci99_high"] < 0.95)]
    assert off.empty, off[["coverage", "ci99_low", "ci99_high"]]
