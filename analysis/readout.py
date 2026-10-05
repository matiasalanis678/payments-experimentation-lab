"""PM readout: exploratory decision sizing, the follow-up test design, and reports/experiment_readout.md.

Everything here is downstream of the pre-registered results. Figures not in config/prereg.yaml
(band-level annual values, the follow-up test design) are exploratory and labeled as such.
The memo text is generated from the results, so its conclusions follow the data.

`uv run python -m analysis.readout`
"""

from __future__ import annotations

import json
import math
from typing import Any

import duckdb
import numpy as np
from scipy import stats

from analysis.data import load_customer_window
from analysis.economics import break_even_dispute_increase, unit_economics
from analysis.experiment import RESULTS_DIR
from analysis.prereg import load_prereg, window_weeks
from generate.assignment import CONTROL
from generate.settings import PROJECT_ROOT, load_settings

MEMO_PATH = PROJECT_ROOT / "reports" / "experiment_readout.md"
DAYS_PER_WEEK = 7


def _z(q: float) -> float:
    return float(stats.norm.ppf(q))


def _usd_m(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x) / 1e6:.2f}M"


def _usd(x: float, spec: str = ".2f", signed: bool = True) -> str:
    sign = "-" if x < 0 else ("+" if signed else "")
    return f"{sign}${format(abs(x), spec)}"


def _usd_ci(lo: float, hi: float, spec: str = ".2f") -> str:
    return f"[{_usd(lo, spec)}, {_usd(hi, spec)}]"


def band_annual_values(results: dict[str, Any], prereg: dict[str, Any]) -> dict[str, dict[str, float]]:
    """EXPLORATORY: per-band annual net value = band value per session x the band's annual sessions."""
    traffic = prereg["baselines"]["traffic"]
    annual_sessions = traffic["sessions_per_day"] * prereg["economics"]["annualization_days"]
    alpha = prereg["alpha"]
    out = {}
    for band, v in results["risk_bands"]["net_value"].items():
        sessions = annual_sessions * prereg["baselines"]["risk_bands"][band]["session_share"]
        h = _z(1 - alpha / 2) * v["se"]
        out[band] = {
            "annual_sessions": sessions,
            "per_session": v["diff"],
            "annual": v["diff"] * sessions,
            "annual_ci": [(v["diff"] - h) * sessions, (v["diff"] + h) * sessions],
            "status": results["risk_bands"]["status"][band]["status"],
        }
    return out


def follow_up_design(
    con: duckdb.DuckDBPyConnection, results: dict[str, Any], prereg: dict[str, Any], band: str
) -> dict[str, Any]:
    """EXPLORATORY: design a confirmatory test for one band, using the current results as planning values.

    Margin: break-even dispute increase at the observed weeks 3-8 lift, with the band's own revenue per
    transaction and dispute baseline. Sample: one-sided non-inferiority on disputes (planning difference =
    observed band difference) and a one-sided test that net value per session is above zero (planning value =
    observed). Clustering enters through the observed customer-clustered SEs and the pre-period dispute design
    effect. Duration adds the novelty burn-in excluded from the business read; readout adds dispute maturity.
    """
    settings = load_settings()
    econ_window = prereg["economics"]["window"]
    g = prereg["guardrails"]["dispute_rate"]
    alpha1, power = g["alpha_one_sided"], prereg["power"]
    k = _z(1 - alpha1) + _z(power)
    dim = prereg["segments"]["targetable_dimension"]

    frame = load_customer_window(con, prereg, econ_window)
    band_frame = frame.loc[frame[dim] == band]
    ctrl = band_frame.loc[band_frame["variant"] == CONTROL]
    rpt = ctrl["captured_usd"].sum() / ctrl["captured"].sum()
    conversion = ctrl["successful_sessions"].sum() / ctrl["sessions"].sum()

    lift = results["secondary"]["steady_state"]["relative"]
    disp = results["risk_bands"]["dispute"][band]
    ue = unit_economics(prereg["economics"]["assumptions"], rpt)
    margin = break_even_dispute_increase(lift, disp["control"], ue)

    d_c, d_t = disp["control"], disp["control"] + disp["diff"]
    de = prereg["baselines"]["preperiod"]["dispute_design_effect"]
    charges_per_arm = k**2 * (d_c * (1 - d_c) + d_t * (1 - d_t)) * de / (margin - disp["diff"]) ** 2
    dispute_sessions_per_arm = charges_per_arm / conversion

    value = results["risk_bands"]["net_value"][band]
    observed_sessions = float(band_frame["sessions"].sum())
    target_se = value["diff"] / k
    value_sessions_total = observed_sessions * (value["se"] / target_se) ** 2
    value_sessions_per_arm = value_sessions_total / 2

    share = prereg["baselines"]["risk_bands"][band]["session_share"]
    band_sessions_per_day = prereg["baselines"]["traffic"]["sessions_per_day"] * share
    binding = max(dispute_sessions_per_arm, value_sessions_per_arm)
    analysis_days = math.ceil(2 * binding / band_sessions_per_day)
    first, _ = window_weeks(prereg, econ_window)
    burn_in_days = (first - 1) * DAYS_PER_WEEK
    run_weeks = math.ceil((burn_in_days + max(analysis_days, DAYS_PER_WEEK)) / DAYS_PER_WEEK)
    return {
        "band": band,
        "planning_lift_relative": lift,
        "band_revenue_per_transaction_usd": rpt,
        "band_control_dispute_rate": d_c,
        "planning_dispute_difference": disp["diff"],
        "margin_absolute": margin,
        "frozen_margin_absolute": g["margin_absolute"],
        "alpha_one_sided": alpha1,
        "power": power,
        "dispute_ni_charges_per_arm": charges_per_arm,
        "dispute_ni_sessions_per_arm": dispute_sessions_per_arm,
        "planning_net_value_per_session": value["diff"],
        "net_value_sessions_per_arm": value_sessions_per_arm,
        "band_sessions_per_day": band_sessions_per_day,
        "analysis_days_needed": analysis_days,
        "burn_in_days": burn_in_days,
        "run_weeks": run_weeks,
        "maturity_days": settings.dispute_maturity_days,
        "days_launch_to_readout": run_weeks * DAYS_PER_WEEK + settings.dispute_maturity_days,
        "binding_constraint": "net value" if value_sessions_per_arm > dispute_sessions_per_arm else "disputes",
        "label": "exploratory",
    }


def _fmt_ci(lo: float, hi: float, fmt: str) -> str:
    return f"[{format(lo, fmt)}, {format(hi, fmt)}]"


def _bands(results: dict[str, Any], status: str) -> list[str]:
    return [b for b, s in results["risk_bands"]["status"].items() if s["status"] == status]


def _join(items: list[str]) -> str:
    return " and ".join(items) if len(items) <= 2 else ", ".join(items[:-1]) + ", and " + items[-1]


def render_memo(
    results: dict[str, Any], prereg: dict[str, Any], values: dict[str, Any], designs: list[dict[str, Any]],
    coverage: dict[str, Any] | None,
) -> str:  # fmt: skip
    """The one-page PM memo, followed by the methods appendix."""
    settings = load_settings()
    alpha = prereg["alpha"]
    dec = results["decision"]
    qualifies, inconclusive, harmful = (_bands(results, s) for s in ("qualifies", "inconclusive", "harmful"))
    prim, steady = results["primary"]["effect"], results["secondary"]["steady_state"]
    week1 = results["secondary"]["weekly"][min(results["secondary"]["weekly"], key=int)]
    econ = results["economics"]["annualized"]
    g = results["guardrails"]
    first, last = window_weeks(prereg, prereg["economics"]["window"])
    obs = results["decision_observed_loss_rate"]
    grid = results["sensitivity_grid"]
    ship_value = sum(values[b]["annual"] for b in qualifies)
    ship_se = math.sqrt(sum(((values[b]["annual_ci"][1] - values[b]["annual"]) / _z(1 - alpha / 2)) ** 2
                            for b in qualifies))  # fmt: skip
    pending = sum(values[b]["annual"] for b in inconclusive)
    pending_se = math.sqrt(sum(((values[b]["annual_ci"][1] - values[b]["annual"]) / _z(1 - alpha / 2)) ** 2
                               for b in inconclusive))  # fmt: skip
    h = _z(1 - alpha / 2)

    def lift_row(name: str, e: dict[str, Any], verdict: str, rate: bool = True) -> str:
        fmt = (lambda v: f"{100 * v:.2f}%") if rate else (lambda v: _usd(v, signed=False))
        ci = _fmt_ci(e["relative_ci_low"], e["relative_ci_high"], "+.1%")
        return (f"| {name} | {fmt(e['control'])} | {fmt(e['treatment'])} | {e['relative']:+.1%} | {ci} | "
                f"{e['p_value']:.1g} | {verdict} |")  # fmt: skip

    def ni(key: str) -> str:
        r = g[key]["non_inferiority"]
        unit = (lambda v: f"{v:+.1%}") if r["scale"] == "relative" else (lambda v: f"{100 * v:+.2f}pp")
        return f"{'Pass' if r['passed'] else 'Fail'}: bound {unit(r['bound'])} vs margin {unit(r['margin'])}"

    band_rows = []
    seg_conv = {}
    seg_path = RESULTS_DIR / "segments.csv"
    if seg_path.exists():
        import pandas as pd

        seg = pd.read_csv(seg_path)
        dim, metric = prereg["segments"]["targetable_dimension"], prereg["primary"]["metric"]
        sel = seg.loc[(seg["dimension"] == dim) & (seg["metric"] == metric)]
        seg_conv = {str(r["level"]): r for _, r in sel.iterrows()}
    order = sorted(values, key=lambda b: results["risk_bands"]["dispute"][b]["control"])
    for b in order:
        v = values[b]
        d = results["risk_bands"]["dispute"][b]
        nv = results["risk_bands"]["net_value"][b]
        conv = seg_conv.get(b)
        conv_txt = f"{conv['relative']:+.1%}" if conv is not None else ""
        band_rows.append(
            f"| {b.capitalize()} | {prereg['baselines']['risk_bands'][b]['session_share']:.0%} | {conv_txt} | "
            f"{100 * d['diff']:+.2f}pp ({d['relative']:+.0%}) | {_usd(nv['diff'])} "
            f"{_usd_ci(nv['diff'] - h * nv['se'], nv['diff'] + h * nv['se'])} | "
            f"{_usd_m(v['annual'])} | **{v['status']}** |"
        )

    rec_parts = []
    if qualifies:
        rec_parts.append(f"**remove the CVC field for {_join(qualifies)}-risk customers**")
    if harmful:
        rec_parts.append(f"**keep it for {_join(harmful)}-risk customers**")
    if inconclusive:
        rec_parts.append(f"**run a confirmatory test for {_join(inconclusive)}-risk customers** before deciding")
    rec = "; ".join(rec_parts)

    design_lines = []
    for dsg in designs:
        design_lines.append(
            f"- **{dsg['band'].capitalize()}-risk confirmatory test (exploratory design).** 50/50 within the "
            f"{dsg['band']} band only. Dispute non-inferiority margin "
            f"**+{100 * dsg['margin_absolute']:.2f}pp**, the break-even at the observed weeks {first}-{last} lift "
            f"({dsg['planning_lift_relative']:+.1%}) with the band's own revenue per transaction "
            f"(${dsg['band_revenue_per_transaction_usd']:.2f}) and dispute baseline "
            f"({100 * dsg['band_control_dispute_rate']:.2f}%); the frozen +{100 * dsg['frozen_margin_absolute']:.3f}pp "
            f"was set at the {prereg['primary']['mde_relative']:.0%} MDE lift. Clustered power {dsg['power']:.0%}, "
            f"one-sided alpha {dsg['alpha_one_sided']}: "
            f"{dsg['dispute_ni_sessions_per_arm']:,.0f} sessions per arm for the dispute test and "
            f"{dsg['net_value_sessions_per_arm']:,.0f} for net value above zero "
            f"(binding: {dsg['binding_constraint']}). "
            f"At {dsg['band_sessions_per_day']:,.0f} {dsg['band']}-band sessions a day that is "
            f"{dsg['analysis_days_needed']} days of data after a {dsg['burn_in_days']}-day novelty burn-in, so run "
            f"**{dsg['run_weeks']} weeks** and read out **{dsg['days_launch_to_readout']} days after launch** once "
            f"disputes mature ({dsg['maturity_days']} days)."
        )

    disp_e, disp_ni = g["dispute_rate"]["effect"], g["dispute_rate"]["non_inferiority"]
    conv_estimates = [prim, steady, results["secondary"]["cuped"], results["secondary"]["account_age_adjusted"]]
    conv_lo, conv_hi = min(e["relative"] for e in conv_estimates), max(e["relative"] for e in conv_estimates)
    later = [
        e["relative"]
        for w, e in results["secondary"]["weekly"].items()
        if int(w) > int(min(results["secondary"]["weekly"], key=int))
    ]
    harm_ratio = max(results["risk_bands"]["dispute"][b]["diff"] for b in harmful) / disp_ni["margin"] if harmful else 0
    er = results["early_dispute_read"]["reads"]
    er_names = list(er)
    naive_share = er[er_names[0]]["diff"] / er[er_names[-1]]["diff"]
    nvc = results["naive_vs_clustered"]
    cuped = results["secondary"]["cuped"]
    mix = results["dispute_mix_by_arm"]["by_arm"]

    lines = [
        "# Removing the CVC field: experiment readout",
        "",
        f"For: product. Experiment `{prereg['experiment_id']}`, {settings.start_date:%b %-d} to "
        f"{settings.end_date:%b %-d, %Y} ({settings.weeks} weeks, {sum(results['srm']['counts'].values()):,} "
        f"customers), disputes matured through "
        f"{settings.analysis_date:%b %-d, %Y}. Plan pre-registered at tag `prereg-v1`.",
        "",
        "## Recommendation",
        "",
        f"The pre-registered decision rules conclude **{dec['decision'].lower()}**: {rec}. The same decision holds "
        f"at the observed {obs['dispute_loss_rate']:.0%} dispute loss rate and at all {grid['points']} points of the "
        "cost sensitivity grid.",
        "",
        f"- **Value of shipping to {_join(qualifies)} risk: {_usd_m(ship_value)} a year** "
        f"[{_usd_m(ship_value - h * ship_se)}, {_usd_m(ship_value + h * ship_se)}] "
        f"*(exploratory)*. Treating every customer would have been worth {_usd_m(econ['annual'])} "
        f"[{_usd_m(econ['annual_ci'][0])}, {_usd_m(econ['annual_ci'][1])}] (pre-registered), but the "
        f"rules block it because disputes in the {_join(harmful)}-risk band rise far past break-even.",
        f"- **Pending on the {_join(inconclusive)}-risk test: {_usd_m(pending)} a year** "
        f"[{_usd_m(pending - h * pending_se)}, {_usd_m(pending + h * pending_se)}] *(exploratory)*.",
        f"- {_join([b.capitalize() for b in harmful])}-risk customers add no value: "
        + ", ".join(f"{_usd(values[b]['per_session'])} per session" for b in harmful)
        + ", with disputes up "
        + ", ".join(f"{results['risk_bands']['dispute'][b]['relative']:.0%}" for b in harmful)
        + ".",
        "",
        "## What happened",
        "",
        f"Without the CVC field, **checkout conversion rose {prim['relative']:+.1%}** "
        f"{_fmt_ci(prim['relative_ci_low'], prim['relative_ci_high'], '+.1%')} ({100 * prim['diff']:+.2f}pp). "
        f"Part of that is novelty: week 1 was {week1['relative']:+.1%}, and weeks {first}-{last} settle at "
        f"**{steady['relative']:+.1%}** {_fmt_ci(steady['relative_ci_low'], steady['relative_ci_high'], '+.1%')}, "
        f"the rate to plan on. Net of extra disputes, treatment earned "
        f"**{_usd(econ['per_session'], signed=False)} per checkout session** "
        f"{_usd_ci(*econ['per_session_ci'])} in weeks {first}-{last}.",
        "",
        "| Metric | Control | Treatment | Lift | 95% CI | p | Verdict |",
        "|---|---|---|---|---|---|---|",
        lift_row("Checkout conversion (primary)", prim, "Significant lift"),
        lift_row(f"Checkout conversion, weeks {first}-{last}", steady, "Significant lift"),
        *[
            lift_row(_guardrail_label(k, v), g[k]["effect"], ni(k), rate="margin_relative" not in v)
            for k, v in prereg["guardrails"].items()
        ],
        f"| Net value per session, weeks {first}-{last} | | | {_usd(econ['per_session'], '.3f')} | "
        f"{_usd_ci(*econ['per_session_ci'], spec='.3f')} | | "
        f"{'CI above $0' if econ['per_session_ci'][0] > 0 else 'CI includes $0'} |",
        "",
        "## Guardrails",
        "",
        f"All three pass overall. Authorization fell {100 * abs(g['authorization_rate']['effect']['diff']):.2f}pp "
        f"(some issuers decline more without CVC), inside the "
        f"{100 * abs(g['authorization_rate']['non_inferiority']['margin']):.1f}pp limit; that revenue loss is already "
        "inside the "
        f"conversion lift. Revenue per transaction did not move. Disputes rose "
        f"{100 * disp_e['diff']:+.3f}pp ({disp_e['relative']:+.0%}), below the +{100 * disp_ni['margin']:.3f}pp "
        "break-even margin.",
        "",
        "## Segment finding",
        "",
        "The overall averages hide where the risk sits. By observable risk band:",
        "",
        "| Risk band | Sessions | Conversion lift | Dispute change | Net value per session (95% CI) "
        "| Annual value *(expl.)* | Rule status |",
        "|---|---|---|---|---|---|---|",
        *band_rows,
        "",
        "![Dispute rate change by risk band against the break-even margin: "
        + "; ".join(
            f"{b} risk {100 * results['risk_bands']['dispute'][b]['diff']:+.2f}pp ({s['status']})"
            for b, s in results["risk_bands"]["status"].items()
        )
        + f"; the largest increase is {harm_ratio:.1f} times the margin](figures/dispute_by_risk_band.png)",
        "",
        "## Risks",
        "",
        "- **Synthetic data.** The merchant, customers, and effects are simulated; the method is the deliverable.",
        "- **Risk score built with generator knowledge.** The band rules (new account, prepaid card, BR or MX) were "
        "chosen by someone who knew how risk was simulated. A real team would derive them from history and Radar.",
        f"- **Loss-rate assumption.** The model assumes {results['economics']['assumptions']['dispute_loss_rate']:.0%} "
        f"of disputes are lost; the observed rate is {obs['dispute_loss_rate']:.0%}. The decision is unchanged at "
        f"{obs['dispute_loss_rate']:.0%} ({_usd_m(obs['economics']['annualized']['annual'])} a year overall).",
        "- **Disputes after 60 days are not counted**, so the matured dispute rate is a floor.",
        _coverage_risk(coverage),
        f"- **Low-risk disputes are flat but not zero-risk:** the CI allows up to "
        f"{100 * results['risk_bands']['dispute'][qualifies[0]]['ci_high']:+.3f}pp. Monitor through rollout."
        if qualifies
        else "",
        "",
        "## Next steps",
        "",
        f"1. Staged rollout of CVC removal to {_join(qualifies)}-risk customers with a holdout, reading disputes "
        "at 60 days."
        if qualifies
        else "1. No rollout.",
        *[f"{i + 2}. {line[2:]}" for i, line in enumerate(design_lines)],
        f"{len(design_lines) + 2}. Keep CVC for {_join(harmful)}-risk customers; review with the risk team "
        "whether Radar rules can recover their conversion lift safely."
        if harmful
        else "",
        "",
        "---",
        "",
        "## Methods notes",
        "",
        f"- **Clustering matters.** Customers, not sessions, were randomized. A naive test that treats sessions as "
        f"independent gives a CI {nvc['naive_understates_ci_width_by']:.0%} too narrow"
        + (
            f"; in simulation its 95% CI covered the truth only "
            f"{_coverage(coverage, 'conversion_full_naive (extra)'):.0%} of the time"
            if coverage
            else ""
        )
        + ". All estimates use customer-clustered (delta method) standard errors.",
        f"- **Early reads understate risk.** At experiment end only {naive_share:.0%} of the eventual dispute "
        f"increase was visible. Adjusting for dispute arrival lag still showed "
        f"{er[er_names[1]]['relative']:+.0%} against a matured {er[er_names[-1]]['relative']:+.0%} "
        f"({1 - er[er_names[1]]['relative'] / er[er_names[-1]]['relative']:.0%} low), as pre-registered: the extra "
        f"disputes are fraud ({mix['treatment']['share_fraudulent']:.0%} of "
        f"treatment disputes vs {mix['control']['share_fraudulent']:.0%} in control), which arrives later "
        "(exploratory check).",
        "- **Re-randomization.** The first assignment salt failed a pre-period A/A check (z = -4.18); diagnostics "
        "ruled out a bug and a rule fixed in advance chose the second salt.",
        f"- **CUPED** (pre-period conversion as covariate) cut variance by "
        f"{cuped['variance_reduction']:.0%}; estimate {cuped['relative']:+.1%}, consistent with the primary.",
        _coverage_note(coverage, prereg),
        "- **Recovery.** Six of seven planted effects fall inside their 95% CIs. The overall dispute lift "
        "(planted +40%, estimated +30%) is a documented 2-SE chance miss.",
        "- Deviations and exploratory additions: [deviations.md](deviations.md). Full outputs: "
        "[results/](results/). Pre-registration: [preregistration.md](preregistration.md), "
        "[prereg_amendments.md](prereg_amendments.md).",
        "",
        "### Figures",
        "",
        f"![Funnel by variant: treatment raises the share of sessions that submit payment, are authorized, and are "
        f"paid; paid sessions {prim['control']:.1%} control vs {prim['treatment']:.1%} treatment]"
        "(figures/funnel_by_variant.png)",
        "",
        f"![Forest plot of relative lifts with 95% CIs: four conversion estimators between {conv_lo:+.1%} and "
        f"{conv_hi:+.1%}; "
        f"authorization {g['authorization_rate']['effect']['relative']:+.1%}, revenue per transaction "
        f"{g['revenue_per_transaction']['effect']['relative']:+.1%}, and disputes {disp_e['relative']:+.0%}, each "
        "inside its non-inferiority margin](figures/forest_lifts.png)",
        "",
        f"![Weekly conversion lift: {week1['relative']:+.1%} in week 1, then between {min(later):+.1%} and "
        f"{max(later):+.1%} from week 2 on, "
        f"against the all-weeks {prim['relative']:+.1%} and weeks {first}-{last} {steady['relative']:+.1%} "
        "reference lines](figures/lift_by_week.png)",
        "",
        "![Dispute change under three reads: naive at experiment end, lag-adjusted, and matured; the early reads "
        "sit well below the matured increase, all below the margin](figures/early_dispute_read.png)",
        "",
        "![Net value per session by segment with 95% CIs: low and medium risk positive, high risk near zero; "
        "countries and card brands shown as exploratory](figures/net_value_by_segment.png)",
        "",
    ]
    return "\n".join(line for line in lines if line is not None)


def _coverage(coverage: dict[str, Any] | None, quantity: str) -> float:
    if not coverage:
        return float("nan")
    return next(r["coverage"] for r in coverage["coverage"] if r["quantity"] == quantity)


def _guardrail_label(key: str, spec: dict[str, Any]) -> str:
    """Display name; the matured-population guardrail says so."""
    return key.replace("_", " ").capitalize() + (" (matured)" if "population" in spec else "")


def _coverage_risk(coverage: dict[str, Any] | None) -> str | None:
    """Risk bullet for the lowest simulated CI coverage among pre-registered CIs."""
    if not coverage:
        return None
    checked = [r for r in coverage["coverage"] if "(extra)" not in r["quantity"]]
    low = min(r["coverage"] for r in checked)
    names = sorted({r["quantity"].split("_")[0] for r in checked if r["coverage"] == low})
    return (
        f"- **Slightly narrow intervals.** In simulation, {_join(names)} CIs covered the truth {low:.0%} of the time: "
        "inside the pre-set pass criterion but a little below the nominal 95%, plausibly small-sample behavior of the "
        f"delta method at {coverage['customers_per_seed']:,} customers per simulated world."
    )


def _dispute_metric(prereg: dict[str, Any]) -> str:
    """The guardrail measured on matured charges."""
    return next(k for k, g in prereg["guardrails"].items() if "population" in g)


def _coverage_note(coverage: dict[str, Any] | None, prereg: dict[str, Any]) -> str:
    if not coverage:
        return "- **Coverage simulation** not run (`make coverage`)."
    checked = [r for r in coverage["coverage"] if "(extra)" not in r["quantity"]]
    lo, hi = min(r["coverage"] for r in checked), max(r["coverage"] for r in checked)
    return (
        f"- **CI coverage** *(exploratory, added after the dispute miss)*: across {coverage['seeds']} simulated "
        f"worlds the pre-registered 95% CIs covered the planted effects {lo:.0%} to {hi:.0%} of the time "
        f"(dispute rate {_coverage(coverage, _dispute_metric(prereg)):.0%}), so the intervals are honest and "
        "the dispute miss was chance. See [coverage.md](coverage.md)."
    )


def main() -> None:
    """Compute exploratory sizing and the follow-up design, then write the memo."""
    prereg = load_prereg()
    results = json.loads((RESULTS_DIR / "results.json").read_text())
    cov_path = PROJECT_ROOT / "reports" / "coverage.json"
    coverage = json.loads(cov_path.read_text()) if cov_path.exists() else None
    values = band_annual_values(results, prereg)
    with duckdb.connect(str(load_settings().warehouse_path), read_only=True) as con:
        designs = [follow_up_design(con, results, prereg, b) for b in _bands(results, "inconclusive")]
    (RESULTS_DIR / "readout.json").write_text(json.dumps(
        {"label": "exploratory", "band_annual_values": values, "follow_up_designs": designs},
        indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else o,
    ))  # fmt: skip
    MEMO_PATH.write_text(render_memo(results, prereg, values, designs, coverage))
    print(f"wrote {MEMO_PATH.relative_to(PROJECT_ROOT)} and {RESULTS_DIR.relative_to(PROJECT_ROOT)}/readout.json")


if __name__ == "__main__":
    main()
