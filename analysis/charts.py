"""Static charts for the readout (reports/figures/). Reads reports/results/ and the marts.

Style: reference palette from the dataviz method (light mode). Control = categorical slot 1 (blue),
treatment = slot 2 (orange); validated pair (CVD dE 24.7, normal dE 33.6, both >= 3:1 on the surface).
Recessive gray chrome, thin marks, direct labels, one x-scale per panel.

`uv run python -m analysis.charts`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.population import EXPOSED_CUSTOMERS_SQL
from analysis.prereg import load_prereg, window_weeks
from generate.assignment import CONTROL, TREATMENT
from generate.settings import PROJECT_ROOT, load_settings

FIG_DIR = PROJECT_ROOT / "reports" / "figures"
RESULTS = PROJECT_ROOT / "reports" / "results"

SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
SERIES = {CONTROL: "#2a78d6", TREATMENT: "#eb6834"}
SINGLE = "#2a78d6"
STATUS = {"qualifies": ("#0ca30c", "\u2713"), "inconclusive": ("#fab219", "?"), "harmful": ("#d03b3b", "\u00d7")}
WIDTH, HEIGHT = 7.2, 3.6
SMALL = 7.8  # annotation font size
TOP_PAD = 0.78  # headroom above the top row for margin labels


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.edgecolor": BASELINE, "axes.labelcolor": INK_2, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "legend.frameon": False, "savefig.dpi": 200, "savefig.bbox": "tight",
    })  # fmt: skip


def _save(fig: plt.Figure, name: str) -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / f"{name}.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def _subtitle(ax: plt.Axes, text: str) -> None:
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK_2, fontsize=8.5, va="bottom")


def _ci_rows(
    ax: plt.Axes,
    labels: list[str],
    est: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    color: str,
    values: list[str] | None = None,
) -> np.ndarray:
    """Horizontal dot-and-whisker rows, top to bottom; optional value labels just right of each CI."""
    y = np.arange(len(labels))[::-1]
    ax.hlines(y, lo, hi, color=color, linewidth=1.6)
    ax.plot(est, y, "o", color=color, markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
    for yy, h, text in zip(y, hi, values or [], strict=False):
        ax.annotate(text, (h, yy), textcoords="offset points", xytext=(5, 0), va="center", color=INK_2, fontsize=SMALL,
                    bbox={"boxstyle": "square,pad=0.15", "fc": SURFACE, "ec": "none"}, zorder=4)  # fmt: skip
    ax.set_yticks(y, labels)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    return y


def _level_label(level: str) -> str:
    """Country codes stay upper case; other levels are capitalized."""
    return level.upper() if len(level) == 2 else level.capitalize()


def funnel(con: duckdb.DuckDBPyConnection, prereg: dict[str, Any]) -> Path:
    """Share of in-window sessions reaching each funnel stage, by variant."""
    first, last = window_weeks(prereg, prereg["primary"]["window"])
    df = (
        con.sql(f"""
        select s.variant,
               avg(s.is_attempted::int) as attempted,
               avg(s.is_authorized::int) as authorized,
               avg(s.is_succeeded::int) as succeeded
        from marts.fct_checkout_sessions s join ({EXPOSED_CUSTOMERS_SQL}) pop using (customer_id)
        where s.experiment_week between {first} and {last}
        group by 1
    """)
        .df()
        .set_index("variant")
    )
    stages = {"attempted": "Submitted payment", "authorized": "Authorized", "succeeded": "Paid (captured)"}
    fig, ax = plt.subplots(figsize=(WIDTH, HEIGHT * 0.88))
    y = np.arange(len(stages))[::-1]
    h = 0.36
    for k, variant in enumerate((CONTROL, TREATMENT)):
        vals = df.loc[variant, list(stages)].to_numpy()
        pos = y + (h / 2 + 0.02) * (1 if k == 0 else -1)
        ax.barh(pos, vals, height=h, color=SERIES[variant], label=variant.capitalize())
        for p, v in zip(pos, vals, strict=True):
            ax.text(v + 0.006, p, f"{v:.1%}", va="center", color=INK_2, fontsize=8.5)
    ax.set_yticks(y, list(stages.values()))
    ax.set_xlim(0, max(df.max()) * 1.18)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    gain = df.loc[TREATMENT, "succeeded"] / df.loc[CONTROL, "succeeded"] - 1
    ax.set_title(f"More checkout sessions end in a payment without the CVC field ({gain:+.1%})", pad=18)
    _subtitle(ax, f"Share of checkout sessions reaching each stage, weeks {first}-{last}, exposed customers")
    ax.legend(loc="upper right", ncols=2, bbox_to_anchor=(1, -0.1), handlelength=1.2)
    return _save(fig, "funnel_by_variant")


def forest(results: dict[str, Any], prereg: dict[str, Any]) -> Path:
    """Relative lifts with 95% CIs: conversion estimators (left), each guardrail with its NI margin (right)."""
    sec, g = results["secondary"], results["guardrails"]
    first, last = window_weeks(prereg, prereg["economics"]["window"])
    conv = [
        ("Primary (all weeks)", results["primary"]["effect"]),
        (f"Weeks {first}-{last} only", sec["steady_state"]),
        ("CUPED", sec["cuped"]),
        ("Account-age adjusted", sec["account_age_adjusted"]),
    ]
    guards = [(k.replace("_", " ").capitalize(), k) for k in prereg["guardrails"]]
    fig = plt.figure(figsize=(WIDTH * 1.2, HEIGHT * 1.05))
    grid = fig.add_gridspec(len(guards), 2, wspace=0.12, hspace=1.1, width_ratios=[1.25, 1])
    a1 = fig.add_subplot(grid[:, 0])
    pct = matplotlib.ticker.PercentFormatter(1, decimals=1)
    _ci_rows(a1, [n for n, _ in conv], np.array([e["relative"] for _, e in conv]),
             np.array([e["relative_ci_low"] for _, e in conv]), np.array([e["relative_ci_high"] for _, e in conv]),
             SINGLE, [f"{e['relative']:+.1%}" for _, e in conv])  # fmt: skip
    a1.axvline(0, color=BASELINE, linewidth=1)
    a1.set_xlim(left=0, right=max(e["relative_ci_high"] for _, e in conv) * 1.3)
    a1.xaxis.set_major_formatter(pct)
    a1.set_title("Checkout conversion", fontsize=9.5)
    for k, (name, key) in enumerate(guards):
        ax = fig.add_subplot(grid[k, 1])
        e, ni = g[key]["effect"], g[key]["non_inferiority"]
        margin = ni["margin"] if ni["scale"] == "relative" else ni["margin"] / e["control"]
        _ci_rows(ax, [""], np.array([e["relative"]]), np.array([e["relative_ci_low"]]),
                 np.array([e["relative_ci_high"]]), SINGLE, [f"{e['relative']:+.1%}"])  # fmt: skip
        ax.axvline(0, color=BASELINE, linewidth=1)
        ax.axvline(margin, color=INK, linewidth=1.1, linestyle=(0, (4, 2)))
        span = [e["relative_ci_low"], e["relative_ci_high"], margin, 0.0]
        pad = (max(span) - min(span)) * 0.35
        ax.set_xlim(min(span) - pad, max(span) + pad)
        ax.set_ylim(-0.75, 0.75)
        ax.xaxis.set_major_formatter(pct)
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
        ax.set_title(f"{name}  ({'passes' if ni['passed'] else 'fails'} margin {margin:+.1%})", fontsize=9,
                     fontweight="normal", color=INK_2)  # fmt: skip
    fig.suptitle(f"Conversion rises about {results['primary']['effect']['relative']:.0%}; every guardrail passes "
                 "its margin overall", x=0.02, ha="left", fontweight="bold", fontsize=11, y=1.06)  # fmt: skip
    fig.text(0.02, 0.985, "Relative lift, treatment vs control, 95% CIs (customer-clustered). Dashed line = "
             "non-inferiority margin", color=INK_2, fontsize=8.5)  # fmt: skip
    return _save(fig, "forest_lifts")


def lift_by_week(results: dict[str, Any], prereg: dict[str, Any]) -> Path:
    """Weekly relative conversion lift with 95% CI band, plus the full and steady-state estimates."""
    wk = pd.read_csv(RESULTS / "weekly_lift.csv")
    key = prereg["secondary"]["weekly_lift"]["by"]
    first, last = window_weeks(prereg, prereg["economics"]["window"])
    fig, ax = plt.subplots(figsize=(WIDTH, HEIGHT))
    ax.fill_between(wk[key], wk["relative_ci_low"], wk["relative_ci_high"], color=SINGLE, alpha=0.16, linewidth=0)
    ax.plot(wk[key], wk["relative"], color=SINGLE, linewidth=2, marker="o", markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.2)  # fmt: skip
    for label, val, dy in (
        ("all weeks", results["primary"]["effect"]["relative"], 4),
        (f"weeks {first}-{last}", results["secondary"]["steady_state"]["relative"], -4),
    ):
        ax.axhline(val, color=MUTED, linewidth=1, linestyle=(0, (4, 2)))
        ax.annotate(f"{label} {val:+.1%}", (wk[key].max() + 0.35, val), textcoords="offset points", xytext=(0, dy),
                    va="bottom" if dy > 0 else "top", color=INK_2, fontsize=SMALL)  # fmt: skip
    ax.axhline(0, color=BASELINE, linewidth=1)
    ax.set_xticks(wk[key], [f"W{w}" for w in wk[key]])
    ax.set_xlim(wk[key].min() - 0.35, wk[key].max() + 1.9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
    ax.grid(axis="x", visible=False)
    w1 = wk.loc[wk[key] == wk[key].min(), "relative"].iloc[0]
    ax.set_title(f"Novelty: the lift starts at {w1:+.1%} in week 1 and settles near "
                 f"{results['secondary']['steady_state']['relative']:+.1%}", pad=18)  # fmt: skip
    _subtitle(ax, "Relative conversion lift by experiment week, 95% CI band")
    return _save(fig, "lift_by_week")


def _status_column(ax: plt.Axes, ys: np.ndarray, statuses: list[str]) -> None:
    for yy, s in zip(ys, statuses, strict=True):
        color, icon = STATUS[s]
        ax.text(1.02, yy, icon, transform=ax.get_yaxis_transform(), color=color, fontsize=11, va="center",
                fontweight="bold", fontfamily="DejaVu Sans")  # fmt: skip
        ax.text(1.07, yy, s, transform=ax.get_yaxis_transform(), color=INK, fontsize=8.5, va="center")


def dispute_by_band(results: dict[str, Any], prereg: dict[str, Any]) -> Path:
    """Absolute dispute rate change per risk band against the break-even margin, with band status."""
    bands = results["risk_bands"]
    order = [b for b in ("low", "medium", "high") if b in bands["dispute"]] or list(bands["dispute"])
    eff = [bands["dispute"][b] for b in order]
    margin = prereg["guardrails"]["dispute_rate"]["margin_absolute"]
    fig, ax = plt.subplots(figsize=(WIDTH, HEIGHT * 0.85))
    y = np.arange(len(order))[::-1]
    _ci_rows(ax, [f"{b.capitalize()} risk" for b in order], np.array([e["diff"] for e in eff]),
             np.array([e["ci_low"] for e in eff]), np.array([e["ci_high"] for e in eff]), SINGLE,
             [f"{100 * e['diff']:+.2f}pp ({e['relative']:+.0%})" for e in eff])  # fmt: skip
    ax.axvline(0, color=BASELINE, linewidth=1)
    ax.axvline(margin, color=INK, linewidth=1.1, linestyle=(0, (4, 2)))
    ax.text(margin, y.max() + 0.55, f"break-even margin +{100 * margin:.3f}pp", color=INK, fontsize=SMALL, ha="left")
    ax.set_ylim(-0.6, y.max() + TOP_PAD)
    ax.set_xlim(right=max(e["ci_high"] for e in eff) * 1.4)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{100 * v:+.2f}pp"))
    _status_column(ax, y, [bands["status"][b]["status"] for b in order])
    ax.set_title("Disputes rise only where risk is already high", pad=18)
    _subtitle(ax, "Change in dispute rate on matured charges (treatment minus control), 95% CI; status per "
                  "pre-registered rule")  # fmt: skip
    return _save(fig, "dispute_by_risk_band")


def early_read(results: dict[str, Any], prereg: dict[str, Any]) -> Path:
    """Dispute difference under the naive, lag-adjusted, and matured reads, against the margin."""
    er = results["early_dispute_read"]
    names = list(er["reads"])
    labels = {n: n.replace("_", " ").capitalize() for n in names}
    eff = [er["reads"][n] for n in names]
    margin = prereg["guardrails"]["dispute_rate"]["margin_absolute"]
    fig, ax = plt.subplots(figsize=(WIDTH, HEIGHT * 0.85))
    y = np.arange(len(names))[::-1]
    _ci_rows(ax, [labels[n] for n in names], np.array([e["diff"] for e in eff]),
             np.array([e["ci_low"] for e in eff]), np.array([e["ci_high"] for e in eff]), SINGLE,
             [f"{100 * e['diff']:+.3f}pp ({e['relative']:+.0%})" for e in eff])  # fmt: skip
    ax.axvline(0, color=BASELINE, linewidth=1)
    ax.axvline(margin, color=INK, linewidth=1.1, linestyle=(0, (4, 2)))
    ax.text(margin, y.max() + 0.55, f"margin +{100 * margin:.3f}pp ", color=INK, fontsize=SMALL, ha="right")
    ax.set_ylim(-0.6, y.max() + TOP_PAD)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{100 * v:+.2f}pp"))
    share = eff[0]["diff"] / eff[-1]["diff"]
    ax.set_title(f"Reading disputes at experiment end shows only {share:.0%} of the final increase", pad=18)
    _subtitle(ax, "Change in dispute rate under three reads, 95% CI (lag-adjusted uses the pre-period arrival curve)")
    return _save(fig, "early_dispute_read")


def net_value_by_segment(results: dict[str, Any], prereg: dict[str, Any]) -> Path:
    """Net value per session with 95% CI by risk band (decision segments) and, exploratory, brand and country."""
    seg = pd.read_csv(RESULTS / "segments.csv")
    value_metric = next(m for m in prereg["segments"]["metrics"] if m not in prereg["guardrails"]
                        and m != prereg["primary"]["metric"])  # fmt: skip
    seg = seg.loc[seg["metric"] == value_metric]
    dims = prereg["segments"]["dimensions"]
    sizes = [seg["dimension"].eq(d).sum() for d in dims]
    fig, axes = plt.subplots(len(dims), 1, figsize=(WIDTH, 0.32 * sum(sizes) + 1.6), sharex=True,
                             gridspec_kw={"height_ratios": sizes, "hspace": 0.35})  # fmt: skip
    overall = results["economics"]["effect"]
    for ax, dim in zip(axes, dims, strict=True):
        d = seg.loc[seg["dimension"] == dim].sort_values("diff", ascending=False)
        _ci_rows(ax, [_level_label(v) for v in d["level"].astype(str)], d["diff"].to_numpy(),
                 d["ci_low"].to_numpy(), d["ci_high"].to_numpy(), SINGLE)  # fmt: skip
        ax.axvline(0, color=BASELINE, linewidth=1)
        ax.axvline(overall["diff"], color=MUTED, linewidth=1, linestyle=(0, (4, 2)))
        tag = "decision segments" if dim == prereg["segments"]["targetable_dimension"] else "exploratory"
        ax.set_title(f"{dim.replace('_', ' ').capitalize()} ({tag})", fontsize=9, fontweight="normal", color=INK_2)
    axes[0].text(overall["diff"], axes[0].get_ylim()[1] + 0.35, f"overall ${overall['diff']:.2f}", color=MUTED,
                 fontsize=SMALL, ha="center")  # fmt: skip
    axes[-1].xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:+.2f}"))
    first, last = window_weeks(prereg, prereg["economics"]["window"])
    fig.suptitle("Net value per checkout session is positive except in the high-risk band", x=0.02, ha="left",
                 fontweight="bold", fontsize=11, y=1.03)  # fmt: skip
    fig.text(0.02, 0.985, f"USD per session, treatment minus control, weeks {first}-{last}, 95% CI", color=INK_2,
             fontsize=8.5)  # fmt: skip
    return _save(fig, "net_value_by_segment")


def main() -> None:
    """Render every readout chart."""
    _style()
    prereg = load_prereg()
    results = json.loads((RESULTS / "results.json").read_text())
    with duckdb.connect(str(load_settings().warehouse_path), read_only=True) as con:
        paths = [funnel(con, prereg)]
    paths += [fn(results, prereg) for fn in (forest, lift_by_week, dispute_by_band, early_read, net_value_by_segment)]
    for p in paths:
        print(f"wrote {p.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
