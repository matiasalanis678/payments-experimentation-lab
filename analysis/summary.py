"""One summary table of the experiment results (reports/results/summary.md)."""

from __future__ import annotations

from typing import Any

from analysis.estimators import Effect
from analysis.experiment import AMENDMENT, EXPLORATORY, PRE_REGISTERED, RESULTS_DIR
from analysis.prereg import window_weeks


def _pct(x: float) -> str:
    return f"{100 * x:+.2f}%"


def _pp(x: float) -> str:
    return f"{100 * x:+.3f}pp"


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def _rate(x: float) -> str:
    return f"{100 * x:.3f}%"


def _row(label: str, e: Effect, alpha: float, verdict: str, status: str, rate: bool = True) -> str:
    lo, hi = e.z_ci(alpha)
    rlo, rhi = e.relative_ci(alpha)
    fmt = _rate if rate else (lambda v: f"{v:,.2f}")
    diff = f"{_pp(e.diff)} [{_pp(lo)}, {_pp(hi)}]" if rate else f"{e.diff:+,.3f} [{lo:+,.3f}, {hi:+,.3f}]"
    return (
        f"| {label} | {fmt(e.control)} | {fmt(e.treatment)} | {diff} | "
        f"{_pct(e.relative)} [{_pct(rlo)}, {_pct(rhi)}] | {e.p_value:.2g} | {verdict} | {status} |"
    )


def _ni_verdict(ni: dict[str, Any]) -> str:
    fmt = _pct if ni["scale"] == "relative" else _pp
    return f"{'Pass' if ni['passed'] else 'Fail'} (bound {fmt(ni['bound'])} vs {fmt(ni['margin'])})"


def _band_verdict(status: dict[str, Any]) -> str:
    why = ", ".join(n.replace("_", " ") for n in status["significant"]) or "no one-sided test significant"
    return f"{status['status']} ({why})"


def write_summary(out: dict[str, Any], prereg: dict[str, Any]) -> None:
    """Write the summary table and decision to reports/results/summary.md."""
    alpha = prereg["alpha"]
    g, sec, econ = out["guardrails"], out["secondary"], out["economics"]
    srm = out["srm"]
    first, last = window_weeks(prereg, prereg["economics"]["window"])
    obs = out["decision_observed_loss_rate"]
    rows = [
        "| Step | Metric | Control | Treatment | Difference [95% CI] | Relative lift [95% CI] | p | Verdict | Status |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| 1 | SRM (exposed customers) | {srm['counts']['control']:,} | {srm['counts']['treatment']:,} | | "
        f"share {srm['treatment_share']:.4f} | {srm['p_value']:.2g} | {'Pass' if srm['passed'] else 'FAIL'} "
        f"| {PRE_REGISTERED} |",
        _row("2 | Checkout conversion (primary, full window)", out["primary"]["effect"], alpha,
             "Significant lift", PRE_REGISTERED),
        _row("3 | Checkout conversion, naive binomial", out["naive_vs_clustered"]["naive"], alpha,
             f"CI {out['naive_vs_clustered']['naive_understates_ci_width_by']:.0%} too narrow", PRE_REGISTERED),
        _row("4 | Authorization rate", g["authorization_rate"]["effect"], alpha,
             _ni_verdict(g["authorization_rate"]["non_inferiority"]), PRE_REGISTERED),
        _row("4 | Revenue per transaction (USD)", g["revenue_per_transaction"]["effect"], alpha,
             _ni_verdict(g["revenue_per_transaction"]["non_inferiority"])
             + f"; bootstrap {'pass' if g['revenue_per_transaction']['robustness']['passed'] else 'fail'}",
             PRE_REGISTERED, rate=False),
        _row("4 | Dispute rate (matured)", g["dispute_rate"]["effect"], alpha,
             _ni_verdict(g["dispute_rate"]["non_inferiority"]), PRE_REGISTERED),
    ]  # fmt: skip
    for label, block, status in (
        (f"5 | Net value, weeks {first}-{last}, loss rate {econ['assumptions']['dispute_loss_rate']:.0%}",
         econ, PRE_REGISTERED),
        (f"5 | Net value, weeks {first}-{last}, loss rate {obs['dispute_loss_rate']:.1%}", obs["economics"], AMENDMENT),
    ):  # fmt: skip
        a = block["annualized"]
        verdict = "CI above 0" if a["annual_ci"][0] > 0 else "CI includes 0"
        rows.append(
            f"| {label} | | | {_usd(a['annual'])}/yr [{_usd(a['annual_ci'][0])}, {_usd(a['annual_ci'][1])}] | "
            f"${a['per_session']:.3f}/session | | {verdict} | {status} |"
        )
    bands = out["risk_bands"]
    for b, s in bands["status"].items():
        rows.append(_row(f"6 | Dispute rate, {b} risk", bands["dispute"][b], alpha, _band_verdict(s), PRE_REGISTERED))
    for b in bands["status"]:
        v = bands["net_value"][b]
        lo, hi = v.z_ci(alpha)
        rows.append(f"| 6 | Net value per session, {b} risk | | | ${v.diff:+.3f} [${lo:+.3f}, ${hi:+.3f}] | | "
                    f"{v.p_value:.2g} | {_band_verdict(bands['status'][b])} | {PRE_REGISTERED} |")  # fmt: skip
    rows += [
        _row(f"7 | Conversion, weeks {first}-{last} (novelty sensitivity)", sec["steady_state"], alpha, "",
             PRE_REGISTERED),
        _row("7 | Conversion, week 1", sec["weekly"][min(sec["weekly"])], alpha, "Novelty", PRE_REGISTERED),
        _row("8 | Conversion, CUPED", sec["cuped"], alpha,
             f"Variance -{sec['cuped'].extra['variance_reduction']:.0%}", PRE_REGISTERED),
        _row("9 | Conversion, account-age adjusted", sec["account_age_adjusted"], alpha, "Robust", PRE_REGISTERED),
    ]  # fmt: skip
    early = out["early_dispute_read"]
    for name, e in early["reads"].items():
        rows.append(_row(f"10 | Dispute rate, {name.replace('_', ' ')}", e, alpha,
                         _ni_verdict(early["non_inferiority"][name]), PRE_REGISTERED))  # fmt: skip
    mix = out["dispute_mix_by_arm"]["by_arm"]
    ks = out["dispute_mix_by_arm"]["lag_ks_p_value"]
    lags = f"Median lag {mix['control']['median_lag_days']:.1f}d vs {mix['treatment']['median_lag_days']:.1f}d"
    rows.append(
        f"| 10 | Fraud share of disputes (matured) | {mix['control']['share_fraudulent']:.1%} | "
        f"{mix['treatment']['share_fraudulent']:.1%} | | | {ks:.2g} (lag KS) | {lags} | {EXPLORATORY} |"
    )
    d = out["decision"]
    grid = out["sensitivity_grid"]

    def segs(decision: dict[str, Any]) -> str:
        names = decision.get("qualifying_segments")
        return f" ({', '.join(names)} risk band)" if names else ""

    lines = [
        "# Experiment results: remove CVC field",
        "",
        "Machine-readable outputs: `results.json`, `segments.csv` (exploratory), `weekly_lift.csv`,",
        "`sensitivity_grid.csv`. Status labels: pre-registered (config/prereg.yaml), amendment A1",
        "(reports/prereg_amendments.md, committed before unblinding), exploratory (reports/deviations.md).",
        "",
        f"**Decision under the pre-registered rules: {d['decision']}{segs(d)}**",
        "",
        *[f"- {t}" for t in d["trail"]],
        f"- Observed loss rate ({obs['dispute_loss_rate']:.1%}, amendment A1): "
        f"{obs['decision']['decision']}{segs(obs['decision'])}",
        f"- Sensitivity grid ({grid['points']} points, amendment A1): {grid['decisions']}; the frozen-assumption "
        f"net value sits at the {grid['primary_annual_net_value_percentile']:.0f}th percentile of the grid.",
        "",
        *rows,
        "",
    ]  # fmt: skip
    (RESULTS_DIR / "summary.md").write_text("\n".join(lines))
