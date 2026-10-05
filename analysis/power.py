"""Power analysis and frozen baselines for the pre-registration.

Blind by construction: uses pre-period outcomes (both arms pooled, before any treatment) and
in-window session counts (traffic, not outcomes). Never reads an in-window outcome or splits by variant.

Clustering: with customer-level randomization and session-level metrics, the delta-method variance of a
ratio is the naive binomial variance times a design effect DE = 1 + rho * (m_eff - 1), where
m_eff = sum(n_i^2) / sum(n_i) is the session-weighted cluster size and rho the intra-customer correlation.
rho is estimated on the pre-period; m_eff comes from the actual in-window traffic at each duration.

`uv run python -m analysis.power` writes reports/power_analysis.md; add `--emit-yaml` to print the
baselines and derived blocks for config/prereg.yaml.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import yaml
from scipy import stats

from analysis.economics import (
    authorization_drop_value,
    break_even_dispute_increase,
    net_value_per_session,
    unit_economics,
)
from analysis.population import EXPOSED_CUSTOMERS_SQL
from analysis.prereg import load_prereg, window_weeks
from analysis.stats import clustered_ratio
from generate.settings import PROJECT_ROOT, load_settings

REPORT_PATH = PROJECT_ROOT / "reports" / "power_analysis.md"
SIG_DIGITS = 6

PREPERIOD_SQL = f"""
    with sessions as (
        select customer_id, count(*) as sessions, count(*) filter (where is_succeeded) as successes
        from marts.fct_checkout_sessions
        where period = 'pre_period'
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
            count(*) filter (where dispute_status in ('won', 'lost')) as closed_disputes,
            count(*) filter (where dispute_status = 'lost') as lost_disputes
        from marts.fct_charges
        where period = 'pre_period'
        group by customer_id
    )
    select pop.customer_id, c.risk_score_band, sessions.*exclude (customer_id), charges.* exclude (customer_id)
    from ({EXPOSED_CUSTOMERS_SQL}) pop
    join marts.dim_customers c using (customer_id)
    join sessions using (customer_id)
    left join charges using (customer_id)
"""

TRAFFIC_SQL = f"""
    select s.customer_id, c.risk_score_band, s.session_date, count(*) as sessions
    from marts.fct_checkout_sessions s
    join ({EXPOSED_CUSTOMERS_SQL}) pop using (customer_id)
    join marts.dim_customers c using (customer_id)
    where s.period = 'experiment'
    group by all
"""


@dataclass(frozen=True)
class ClusterStats:
    """Rate, design effect, effective cluster size, and implied intra-customer correlation."""

    rate: float
    design_effect: float
    effective_cluster_size: float
    icc: float


def cluster_stats(num: np.ndarray, den: np.ndarray) -> ClusterStats:
    """Design effect of a customer-clustered ratio relative to a naive binomial on the same units."""
    est = clustered_ratio(num, den)
    naive_var = est.rate * (1 - est.rate) / est.n_units
    de = est.variance / naive_var
    m_eff = float((den.astype(float) ** 2).sum() / den.sum())
    return ClusterStats(rate=est.rate, design_effect=de, effective_cluster_size=m_eff, icc=(de - 1) / (m_eff - 1))


def traffic_curve(traffic: pd.DataFrame, start: pd.Timestamp, days: int) -> pd.DataFrame:
    """Cumulative sessions N(D) and session-weighted cluster size m_eff(D) for durations D = 1..days."""
    cust = pd.factorize(traffic["customer_id"])[0]
    day = (pd.to_datetime(traffic["session_date"]) - start).dt.days.to_numpy()
    counts = np.zeros((cust.max() + 1, days), dtype=np.int32)
    np.add.at(counts, (cust, day), traffic["sessions"].to_numpy())
    cum = counts.cumsum(axis=1).astype(float)
    n = cum.sum(axis=0)
    return pd.DataFrame({"days": np.arange(1, days + 1), "sessions": n, "m_eff": (cum**2).sum(axis=0) / n})


def design_effect(icc: float, m_eff: np.ndarray | float) -> np.ndarray | float:
    """DE = 1 + rho * (m_eff - 1)."""
    return 1 + icc * (np.asarray(m_eff) - 1)


def se_diff(rate: float, total_units: np.ndarray | float, de: np.ndarray | float) -> np.ndarray | float:
    """SE of a difference in rates with an even split of `total_units` across two arms."""
    return np.sqrt(4 * rate * (1 - rate) * np.asarray(de) / np.asarray(total_units))


def z(q: float) -> float:
    """Standard normal quantile."""
    return float(stats.norm.ppf(q))


def charge_cluster_size(conversion: float, m_eff_sessions: np.ndarray | float) -> np.ndarray | float:
    """m_eff for captured charges after binomial thinning of sessions: p * m_eff + (1 - p)."""
    return conversion * np.asarray(m_eff_sessions) + (1 - conversion)


def _round(x: float) -> float:
    return float(f"{x:.{SIG_DIGITS}g}")


def compute_baselines(con: duckdb.DuckDBPyConnection, prereg: dict[str, Any]) -> dict[str, Any]:
    """Pre-period rates and clustering, plus in-window traffic. These are the values frozen in prereg.yaml."""
    settings = load_settings()
    pre = con.sql(PREPERIOD_SQL).df().fillna(0)
    traffic = con.sql(TRAFFIC_SQL).df()
    days = (settings.end_date - settings.start_date).days
    curve = traffic_curve(traffic, pd.Timestamp(settings.start_date), days)

    conv = cluster_stats(pre["successes"].to_numpy(), pre["sessions"].to_numpy())
    has_matured = pre["matured_captured"] > 0
    disp = cluster_stats(
        pre.loc[has_matured, "matured_disputes"].to_numpy(), pre.loc[has_matured, "matured_captured"].to_numpy()
    )
    band_dim = prereg["segments"]["targetable_dimension"]
    band_pre = pre.groupby(band_dim)[["successes", "sessions", "matured_disputes", "matured_captured"]].sum()
    band_traffic = traffic.groupby(band_dim)["sessions"].sum()
    band_curves = {
        b: traffic_curve(traffic.loc[traffic[band_dim] == b], pd.Timestamp(settings.start_date), days).iloc[-1]
        for b in band_traffic.index
    }

    out = {
        "preperiod": {
            "conversion_rate": conv.rate,
            "conversion_design_effect": conv.design_effect,
            "conversion_effective_cluster_size": conv.effective_cluster_size,
            "conversion_icc": conv.icc,
            "dispute_rate": disp.rate,
            "dispute_design_effect": disp.design_effect,
            "dispute_effective_cluster_size": disp.effective_cluster_size,
            "dispute_icc": disp.icc,
            "revenue_per_transaction_usd": pre["captured_usd"].sum() / pre["captured"].sum(),
            "attempts_per_session": pre["attempts"].sum() / pre["sessions"].sum(),
            "authorization_rate": pre["authorized"].sum() / pre["attempts"].sum(),
            "capture_rate": pre["captured"].sum() / pre["authorized"].sum(),
            "observed_dispute_loss_rate": pre["lost_disputes"].sum() / pre["closed_disputes"].sum(),
            "customers": len(pre),
            "sessions": int(pre["sessions"].sum()),
        },
        "traffic": {
            "experiment_days": days,
            "exposed_customers": int(traffic["customer_id"].nunique()),
            "sessions": int(curve["sessions"].iloc[-1]),
            "sessions_per_day": curve["sessions"].iloc[-1] / days,
            "effective_cluster_size": curve["m_eff"].iloc[-1],
        },
        "risk_bands": {
            b: {
                "session_share": band_traffic[b] / band_traffic.sum(),
                "sessions": int(band_traffic[b]),
                "effective_cluster_size": band_curves[b]["m_eff"],
                "preperiod_conversion_rate": band_pre.loc[b, "successes"] / band_pre.loc[b, "sessions"],
                "preperiod_dispute_rate": band_pre.loc[b, "matured_disputes"] / band_pre.loc[b, "matured_captured"],
                "preperiod_matured_charges": int(band_pre.loc[b, "matured_captured"]),
            }
            for b in band_traffic.index
        },
    }
    return _round_tree(out)


def _round_tree(tree: Any) -> Any:
    if isinstance(tree, dict):
        return {k: _round_tree(v) for k, v in tree.items()}
    if isinstance(tree, float | np.floating):
        return _round(float(tree))
    if isinstance(tree, np.integer):
        return int(tree)
    return tree


def compute_derived(prereg: dict[str, Any], baselines: dict[str, Any]) -> dict[str, Any]:
    """Unit economics and the break-even dispute margin, from frozen baselines and labeled assumptions."""
    pre = baselines["preperiod"]
    ue = unit_economics(prereg["economics"]["assumptions"], pre["revenue_per_transaction_usd"])
    margin = break_even_dispute_increase(prereg["primary"]["mde_relative"], pre["dispute_rate"], ue)
    return _round_tree(
        {
            "margin_per_sale_usd": ue.margin_per_sale,
            "cost_per_dispute_usd": ue.cost_per_dispute,
            "dispute_margin_absolute": margin,
            "dispute_margin_relative_to_baseline": margin / pre["dispute_rate"],
        }
    )


def power_tables(prereg: dict[str, Any], baselines: dict[str, Any], curve: pd.DataFrame) -> dict[str, Any]:
    """Naive vs clustered power for conversion, dispute non-inferiority power, and high-risk band power."""
    alpha, target = prereg["alpha"], prereg["power"]
    z_a, z_b = z(1 - alpha / 2), z(target)
    pre, tr = baselines["preperiod"], baselines["traffic"]
    p, icc = pre["conversion_rate"], pre["conversion_icc"]
    delta = p * prereg["primary"]["mde_relative"]

    de = design_effect(icc, curve["m_eff"].to_numpy())
    n_per_arm_naive = (z_a + z_b) ** 2 * 2 * p * (1 - p) / delta**2
    se_naive = se_diff(p, curve["sessions"].to_numpy(), 1.0)
    se_clustered = se_diff(p, curve["sessions"].to_numpy(), de)
    curve = curve.assign(
        design_effect=de,
        power_naive=stats.norm.cdf(delta / se_naive - z_a),
        power_clustered=stats.norm.cdf(delta / se_clustered - z_a),
        mde_relative_naive=(z_a + z_b) * se_naive / p,
        mde_relative_clustered=(z_a + z_b) * se_clustered / p,
    )
    day_naive = int(curve.loc[curve["power_naive"] >= target, "days"].min())
    day_clustered = int(curve.loc[curve["power_clustered"] >= target, "days"].min())
    de_at = float(curve.loc[curve["days"] == day_clustered, "design_effect"].iloc[0])

    # Dispute non-inferiority on matured charges at the full duration (true difference 0).
    g = prereg["guardrails"]["dispute_rate"]
    margin = (
        g["margin_absolute"]
        if g["margin_absolute"] is not None
        else compute_derived(prereg, baselines)["dispute_margin_absolute"]
    )
    z_ni = z(1 - g["alpha_one_sided"])
    d = pre["dispute_rate"]
    charges = tr["sessions"] * p
    de_d = design_effect(pre["dispute_icc"], charge_cluster_size(p, tr["effective_cluster_size"]))
    se_d = se_diff(d, charges, de_d)

    bands = {}
    for band, b in baselines["risk_bands"].items():
        pb, db = b["preperiod_conversion_rate"], b["preperiod_dispute_rate"]
        se_cb = se_diff(pb, b["sessions"], design_effect(icc, b["effective_cluster_size"]))
        se_db = se_diff(
            db,
            b["sessions"] * pb,
            design_effect(pre["dispute_icc"], charge_cluster_size(pb, b["effective_cluster_size"])),
        )
        n_bands = len(baselines["risk_bands"])
        bands[band] = {
            "mde_relative_unadjusted": (z_a + z_b) * se_cb / pb,
            "mde_relative_holm_worst_case": (z(1 - alpha / 2 / n_bands) + z_b) * se_cb / pb,
            "dispute_ni_power_unadjusted": float(stats.norm.cdf(margin / se_db - z_ni)),
            "dispute_ni_power_holm_worst_case": float(
                stats.norm.cdf(margin / se_db - z(1 - g["alpha_one_sided"] / n_bands))
            ),
            "expected_matured_charges": b["sessions"] * pb,
            "expected_disputes_per_arm": b["sessions"] * pb * db / 2,
        }
    return {
        "curve": curve,
        "conversion": {
            "mde_absolute": delta,
            "required_sessions_per_arm_naive": n_per_arm_naive,
            "required_sessions_per_arm_clustered": n_per_arm_naive * de_at,
            "days_naive": day_naive,
            "days_clustered": day_clustered,
            "design_effect_at_clustered_duration": de_at,
            "design_effect_full_duration": float(de[-1]),
            "power_full_duration_clustered": float(curve["power_clustered"].iloc[-1]),
            "mde_relative_full_duration_naive": float(curve["mde_relative_naive"].iloc[-1]),
            "mde_relative_full_duration_clustered": float(curve["mde_relative_clustered"].iloc[-1]),
        },
        "dispute": {
            "margin_absolute": margin,
            "expected_matured_charges": charges,
            "design_effect": float(de_d),
            "se_difference": float(se_d),
            "ni_power_full_duration": float(stats.norm.cdf(margin / se_d - z_ni)),
        },
        "bands": bands,
    }


def window_mde(
    prereg: dict[str, Any], baselines: dict[str, Any], traffic: pd.DataFrame, window: str
) -> dict[str, float]:
    """Naive and clustered MDE (relative) for the conversion difference in a pre-registered week window."""
    settings = load_settings()
    first, last = window_weeks(prereg, window)
    start = pd.Timestamp(settings.start_date) + pd.Timedelta(weeks=first - 1)
    days = 7 * (last - first + 1)
    in_window = (pd.to_datetime(traffic["session_date"]) >= start) & (
        pd.to_datetime(traffic["session_date"]) < start + pd.Timedelta(days=days)
    )
    end = traffic_curve(traffic.loc[in_window], start, days).iloc[-1]
    pre = baselines["preperiod"]
    p = pre["conversion_rate"]
    k = z(1 - prereg["alpha"] / 2) + z(prereg["power"])
    de = float(design_effect(pre["conversion_icc"], end["m_eff"]))
    return {
        "sessions": float(end["sessions"]),
        "design_effect": de,
        "mde_relative_naive": float(k * se_diff(p, end["sessions"], 1.0) / p),
        "mde_relative_clustered": float(k * se_diff(p, end["sessions"], de) / p),
    }


def economics_at_mde(prereg: dict[str, Any], baselines: dict[str, Any]) -> dict[str, float]:
    """Net value of a lift equal to the MDE with no dispute change, and the cost of the worst allowed auth drop."""
    pre, tr = baselines["preperiod"], baselines["traffic"]
    ue = unit_economics(prereg["economics"]["assumptions"], pre["revenue_per_transaction_usd"])
    c, d = pre["conversion_rate"], pre["dispute_rate"]
    value = net_value_per_session(c, c * (1 + prereg["primary"]["mde_relative"]), d, d, ue)
    auth = authorization_drop_value(
        pre["attempts_per_session"],
        prereg["guardrails"]["authorization_rate"]["margin_absolute"],
        pre["capture_rate"],
        ue,
    )
    annual_sessions = tr["sessions_per_day"] * prereg["economics"]["annualization_days"]
    return {
        "net_value_per_session": value,
        "net_value_annual": value * annual_sessions,
        "auth_margin_value_per_session": auth,
        "auth_margin_value_annual": auth * annual_sessions,
        "annual_sessions": annual_sessions,
    }


def sensitivity(prereg: dict[str, Any], baselines: dict[str, Any]) -> pd.DataFrame:
    """Break-even dispute margin across the pre-registered assumption grid."""
    grid = prereg["economics"]["sensitivity_grid"]
    base = prereg["economics"]["assumptions"]
    pre = baselines["preperiod"]
    rows = []
    for key, values in grid.items():
        for v in values:
            ue = unit_economics({**base, key: v}, pre["revenue_per_transaction_usd"])
            m = break_even_dispute_increase(prereg["primary"]["mde_relative"], pre["dispute_rate"], ue)
            rows.append(
                {"assumption": key, "value": v, "margin_pp": 100 * m, "margin_relative": m / pre["dispute_rate"]}
            )
    return pd.DataFrame(rows)


def _markdown(
    prereg: dict[str, Any],
    baselines: dict[str, Any],
    derived: dict[str, Any],
    t: dict[str, Any],
    steady: dict[str, float],
    econ: dict[str, float],
) -> str:
    c, dsp = t["conversion"], t["dispute"]
    pre, tr = baselines["preperiod"], baselines["traffic"]
    days, target = tr["experiment_days"], prereg["power"]
    de_at, de_full = c["design_effect_at_clustered_duration"], c["design_effect_full_duration"]
    first, last = window_weeks(prereg, prereg["economics"]["window"])
    g = prereg["guardrails"]["dispute_rate"]
    curve = t["curve"]
    weekly = curve.loc[curve["days"] % 7 == 0].assign(weeks=lambda f: f["days"] // 7).set_index("weeks")
    weekly = weekly[["sessions", "m_eff", "design_effect", "power_naive", "power_clustered",
                     "mde_relative_naive", "mde_relative_clustered"]]  # fmt: skip
    band_cols = ["session_share", "preperiod_dispute_rate", "preperiod_matured_charges"]
    bands = pd.DataFrame(t["bands"]).T.join(pd.DataFrame(baselines["risk_bands"]).T[band_cols])
    n_naive, n_clus = c["required_sessions_per_arm_naive"], c["required_sessions_per_arm_clustered"]
    mde_naive, mde_clus = c["mde_relative_full_duration_naive"], c["mde_relative_full_duration_clustered"]
    lines = [
        "# Power analysis",
        "",
        "Generated by `uv run python -m analysis.power`. Inputs: pre-period outcomes (both arms pooled, before",
        "any treatment) and in-window session counts. No in-window outcome or variant split is used.",
        "",
        "## Conversion: naive vs clustered",
        "",
        f"Baseline conversion {pre['conversion_rate']:.4f}; MDE {prereg['primary']['mde_relative']:.1%} relative "
        f"({100 * c['mde_absolute']:.3f}pp); alpha {prereg['alpha']} two-sided; power {target}.",
        f"Pre-period design effect {pre['conversion_design_effect']:.2f} at m_eff "
        f"{pre['conversion_effective_cluster_size']:.1f} sessions, implying intra-customer correlation "
        f"{pre['conversion_icc']:.4f}.",
        "",
        "| | Naive binomial | Clustered (delta method) |",
        "|---|---|---|",
        f"| Required sessions per arm | {n_naive:,.0f} | {n_clus:,.0f} |",
        f"| Days to reach {target:.0%} power | {c['days_naive']} | {c['days_clustered']} |",
        f"| MDE at {days} days | {mde_naive:.2%} | {mde_clus:.2%} |",
        "",
        f"The naive calculation understates the required sample by a factor of {de_at:.2f} (the design effect "
        f"at that duration) and the duration by {c['days_clustered'] - c['days_naive']} days. At the full "
        f"{days} days the design effect is {de_full:.2f}, so naive standard errors would be "
        f"{np.sqrt(de_full):.2f}x too narrow.",
        "",
        f"Steady-state window (weeks {first}-{last}, used for the business case): {steady['sessions']:,.0f} "
        f"sessions, design effect {steady['design_effect']:.2f}, MDE {steady['mde_relative_naive']:.2%} naive vs "
        f"{steady['mde_relative_clustered']:.2%} clustered.",
        "",
        "### By duration",
        "",
        weekly.to_markdown(floatfmt=",.4f"),
        "",
        "## Dispute guardrail (non-inferiority, matured charges)",
        "",
        f"Margin {100 * dsp['margin_absolute']:.3f}pp absolute "
        f"({derived['dispute_margin_relative_to_baseline']:.0%} of the {100 * pre['dispute_rate']:.3f}% baseline), "
        f"one-sided alpha {g['alpha_one_sided']}.",
        f"Expected matured captured charges: {dsp['expected_matured_charges']:,.0f}; design effect "
        f"{dsp['design_effect']:.2f}; SE of the difference {100 * dsp['se_difference']:.4f}pp; power if the true "
        f"difference is 0: {dsp['ni_power_full_duration']:.1%}.",
        "",
        "## Risk bands (exploratory)",
        "",
        bands.to_markdown(floatfmt=",.4f"),
        "",
        "Holm worst case divides alpha by the number of bands for the smallest p-value.",
        "",
        "## Economics at the MDE",
        "",
        f"Margin per sale ${derived['margin_per_sale_usd']:.2f}; expected cost per dispute "
        f"${derived['cost_per_dispute_usd']:.2f}.",
        f"A lift equal to the MDE with no dispute change is worth ${econ['net_value_per_session']:.4f} per "
        f"session, about ${econ['net_value_annual']:,.0f} a year at {econ['annual_sessions']:,.0f} sessions.",
        f"An authorization drop at the guardrail limit would cost ${-econ['auth_margin_value_per_session']:.4f} "
        f"per session (${-econ['auth_margin_value_annual']:,.0f} a year); this is already inside the end-to-end "
        "conversion lift.",
        "",
        "## Dispute margin sensitivity",
        "",
        sensitivity(prereg, baselines).to_markdown(index=False, floatfmt=",.4f"),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Compute baselines, derived margin, and power; write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-yaml", action="store_true", help="print baselines and derived blocks")
    args = parser.parse_args(argv)
    prereg = load_prereg()
    settings = load_settings()
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        baselines = compute_baselines(con, prereg)
        traffic = con.sql(TRAFFIC_SQL).df()
    derived = compute_derived(prereg, baselines)
    curve = traffic_curve(traffic, pd.Timestamp(settings.start_date), baselines["traffic"]["experiment_days"])
    tables = power_tables(prereg, baselines, curve)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    steady = window_mde(prereg, baselines, traffic, prereg["economics"]["window"])
    econ = economics_at_mde(prereg, baselines)
    REPORT_PATH.write_text(_markdown(prereg, baselines, derived, tables, steady, econ))
    print(f"wrote {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    if args.emit_yaml:
        print(yaml.safe_dump({"baselines": baselines, "derived": derived}, sort_keys=False))


if __name__ == "__main__":
    main()
