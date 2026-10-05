"""Run the pre-registered analysis of exp_remove_cvc and write reports/results/.

Order: SRM, primary, naive vs clustered CI, guardrails, economics, segments and decision, novelty,
CUPED, account-age regression, three-way early dispute read. Every parameter comes from
config/prereg.yaml. Outputs are labeled pre-registered, amendment (A1, committed before unblinding),
or exploratory (logged in reports/deviations.md).

`uv run python -m analysis.experiment`
"""

from __future__ import annotations

import copy
import itertools
import json
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analysis import metrics
from analysis.data import load_customer_week, load_customer_window
from analysis.decision import annualize, band_status, decide, non_inferiority, srm_test
from analysis.early_read import dispute_mix_by_arm, run_early_read
from analysis.estimators import Effect, estimate, estimator_fn
from analysis.population import srm_counts
from analysis.prereg import load_prereg, window_weeks
from generate.assignment import TREATMENT
from generate.settings import PROJECT_ROOT, load_settings

RESULTS_DIR = PROJECT_ROOT / "reports" / "results"
SIG_DIGITS = 9  # parallel float sums differ in the last digits run to run; round so outputs are byte-stable
PRE_REGISTERED = "pre-registered"
AMENDMENT = "amendment A1 (pre-unblinding)"
EXPLORATORY = "exploratory"


class SRMFailure(SystemExit):
    """Sample ratio mismatch: the analysis stops here."""


def _labeled(label: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"label": label, **payload}


def _metric_window(prereg: dict[str, Any], metric: str) -> str:
    """Window a metric is analyzed on: its guardrail or primary window, else the economics window."""
    if metric in prereg["guardrails"]:
        return prereg["guardrails"][metric]["window"]
    if metric == prereg["primary"]["metric"]:
        return prereg["primary"]["window"]
    return prereg["economics"]["window"]


def _with_assumptions(prereg: dict[str, Any], **overrides: float) -> dict[str, Any]:
    out = copy.deepcopy(prereg)
    out["economics"]["assumptions"].update(overrides)
    return out


def _net_value(frame: pd.DataFrame, prereg: dict[str, Any]) -> Effect:
    return estimator_fn(prereg["primary"]["estimator"])(frame, metrics.net_value_per_session, prereg)


def _by_level(frame: pd.DataFrame, dim: str, fn: Any) -> dict[str, Effect]:
    return {str(level): fn(group) for level, group in frame.groupby(dim, observed=True)}


def _economics(frames: dict[str, pd.DataFrame], prereg: dict[str, Any], annual_sessions: float) -> dict[str, Any]:
    frame = frames[prereg["economics"]["window"]]
    effect = _net_value(frame, prereg)
    return {"effect": effect, "annualized": annualize(effect, annual_sessions, prereg["alpha"])}


def _band_effects(frames: dict[str, pd.DataFrame], prereg: dict[str, Any], dispute_metric: str) -> dict[str, Any]:
    dim = prereg["segments"]["targetable_dimension"]
    est = estimator_fn(prereg["guardrails"][dispute_metric]["estimator"])
    dispute = _by_level(
        frames[prereg["guardrails"][dispute_metric]["window"]],
        dim,
        lambda g: est(g, metrics.metric_fn(dispute_metric), prereg),
    )
    value = _by_level(frames[prereg["economics"]["window"]], dim, lambda g: _net_value(g, prereg))
    return {"dispute": dispute, "value": value}


def _decision_for(
    prereg: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    primary: Effect,
    operational: dict[str, Any],
    dispute_ni: dict[str, Any],
    dispute_metric: str,
    annual_sessions: float,
) -> dict[str, Any]:
    """Economics, band statuses, and the decision under the economic assumptions in `prereg`."""
    g = prereg["guardrails"][dispute_metric]
    econ = _economics(frames, prereg, annual_sessions)
    bands = _band_effects(frames, prereg, dispute_metric)
    status = band_status(bands["dispute"], bands["value"], g["margin_absolute"], g["alpha_one_sided"],
                         prereg["segments"]["correction"])  # fmt: skip
    decision = decide(True, primary, prereg["alpha"], operational, dispute_ni, econ["annualized"], status)
    return {"economics": econ, "bands": bands, "band_status": status, "decision": decision}


def _segments(frames: dict[str, pd.DataFrame], prereg: dict[str, Any]) -> pd.DataFrame:
    """Exploratory segment effects, Holm-adjusted within each (dimension, metric) family."""
    seg = prereg["segments"]
    rows = []
    for dim, metric in itertools.product(seg["dimensions"], seg["metrics"]):
        frame = frames[_metric_window(prereg, metric)]
        fn = metrics.metric_fn(metric)
        effects = _by_level(frame, dim, lambda g, fn=fn: estimator_fn(prereg["primary"]["estimator"])(g, fn, prereg))
        family = [
            {"dimension": dim, "metric": metric, "level": k, **e.as_dict(prereg["alpha"])} for k, e in effects.items()
        ]
        adjusted = multipletests([r["p_value"] for r in family], alpha=prereg["alpha"], method=seg["correction"])[1]
        for r, p in zip(family, adjusted, strict=True):
            rows.append(r | {"p_value_holm": float(p), "label": EXPLORATORY})
    return pd.DataFrame(rows)


def _sensitivity_grid(prereg: dict[str, Any], frames: dict[str, pd.DataFrame], args: dict[str, Any]) -> pd.DataFrame:
    """Annual net value and decision at every combination of the pre-registered sensitivity grid."""
    grid = prereg["economics"]["sensitivity_grid"]
    rows = []
    for combo in itertools.product(*grid.values()):
        overrides = dict(zip(grid, combo, strict=True))
        res = _decision_for(_with_assumptions(prereg, **overrides), frames, **args)
        ann = res["economics"]["annualized"]
        rows.append(overrides | {
            "annual_net_value": ann["annual"],
            "annual_ci_low": ann["annual_ci"][0],
            "annual_ci_high": ann["annual_ci"][1],
            "decision": res["decision"]["decision"],
            "segments": ",".join(res["decision"].get("qualifying_segments", [])),
            **{f"band_{b}": s["status"] for b, s in res["band_status"].items()},
        })  # fmt: skip
    return pd.DataFrame(rows)


def _round(x: float) -> float:
    return float(f"{x:.{SIG_DIGITS}g}")


def _round_frame(df: pd.DataFrame) -> pd.DataFrame:
    floats = df.select_dtypes("float").columns
    return df.assign(**{c: df[c].map(_round) for c in floats})


def _jsonable(obj: Any, alpha: float) -> Any:
    if isinstance(obj, Effect):
        return _jsonable(obj.as_dict(alpha), alpha)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, alpha) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_jsonable(v, alpha) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, float | np.floating):
        return _round(float(obj))
    if isinstance(obj, bool | np.bool_):
        return bool(obj)
    return obj


def run(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Execute the analysis in pre-registered order and return all results."""
    prereg = load_prereg()
    alpha = prereg["alpha"]
    out: dict[str, Any] = {}

    # 1. SRM on exposed customers. Stop if it fails.
    srm = srm_test(srm_counts(con), prereg["srm"]["expected_treatment_share"], TREATMENT)
    srm["passed"] = srm["p_value"] >= prereg["srm"]["alpha"]
    out["srm"] = _labeled(PRE_REGISTERED, srm)
    if not srm["passed"]:
        _write(out, alpha)
        raise SRMFailure(f"SRM failed (p={srm['p_value']:.2e}); analysis stopped. See reports/results/results.json")

    frames = {w: load_customer_window(con, prereg, w) for w in prereg["windows"]}

    # 2. Primary.
    p = prereg["primary"]
    primary = estimate(p["estimator"], frames[p["window"]], p["metric"], prereg)
    out["primary"] = _labeled(PRE_REGISTERED, {"metric": p["metric"], "window": p["window"], "effect": primary})

    # 3. Naive vs clustered CI width.
    nb = prereg["secondary"]["naive_binomial"]
    naive = estimate(nb["estimator"], frames[nb["window"]], nb["metric"], prereg)
    out["naive_vs_clustered"] = _labeled(PRE_REGISTERED, {
        "naive": naive,
        "clustered": primary,
        "ci_width_ratio_clustered_to_naive": primary.se / naive.se,
        "naive_understates_ci_width_by": 1 - naive.se / primary.se,
    })  # fmt: skip

    # 4. Guardrails.
    guardrails, ni = {}, {}
    for name, g in prereg["guardrails"].items():
        effect = estimate(g["estimator"], frames[g["window"]], name, prereg)
        relative = "margin_relative" in g
        margin = g["margin_relative"] if relative else g["margin_absolute"]
        ni[name] = non_inferiority(effect, margin, g["alpha_one_sided"], relative)
        entry = {"effect": effect, "non_inferiority": ni[name]}
        if "robustness_estimator" in g:
            rob = estimate(g["robustness_estimator"], frames[g["window"]], name, prereg, reps=g["bootstrap_reps"])
            entry["robustness"] = {"effect": rob, "passed": rob.relative_ci(alpha)[0] > margin}
        guardrails[name] = entry
    out["guardrails"] = _labeled(PRE_REGISTERED, guardrails)
    operational = {k: ni[k] for k in prereg["decision_rules"]["operational_guardrails"]}
    dispute_metric = next(k for k in prereg["guardrails"] if k not in operational)

    # 5-6. Economics, segments, decision (frozen assumptions), then amendment A1 sensitivities.
    traffic = prereg["baselines"]["traffic"]
    annual_sessions = traffic["sessions_per_day"] * prereg["economics"]["annualization_days"]
    args = {"primary": primary, "operational": operational, "dispute_ni": ni[dispute_metric],
            "dispute_metric": dispute_metric, "annual_sessions": annual_sessions}  # fmt: skip
    frozen = _decision_for(prereg, frames, **args)
    out["economics"] = _labeled(PRE_REGISTERED, {
        "assumptions": prereg["economics"]["assumptions"],
        "window": prereg["economics"]["window"],
        "annual_sessions": annual_sessions,
        **frozen["economics"],
    })  # fmt: skip
    out["risk_bands"] = _labeled(PRE_REGISTERED, {
        "dispute": frozen["bands"]["dispute"], "net_value": frozen["bands"]["value"], "status": frozen["band_status"],
    })  # fmt: skip
    out["decision"] = _labeled(PRE_REGISTERED, frozen["decision"])

    observed_loss = prereg["baselines"]["preperiod"]["observed_dispute_loss_rate"]
    observed = _decision_for(_with_assumptions(prereg, dispute_loss_rate=observed_loss), frames, **args)
    out["decision_observed_loss_rate"] = _labeled(AMENDMENT, {
        "dispute_loss_rate": observed_loss,
        "economics": observed["economics"],
        "band_status": observed["band_status"],
        "decision": observed["decision"],
    })  # fmt: skip
    grid = _sensitivity_grid(prereg, frames, args)
    out["sensitivity_grid"] = _labeled(AMENDMENT, {
        "points": len(grid),
        "decisions": grid["decision"].value_counts().to_dict(),
        "primary_annual_net_value_percentile": float(
            stats.percentileofscore(grid["annual_net_value"], frozen["economics"]["annualized"]["annual"])
        ),
    })  # fmt: skip

    segments = _segments(frames, prereg)

    # 7. Novelty: weekly lifts and the steady-state window.
    first, last = window_weeks(prereg, prereg["primary"]["window"])
    wl = prereg["secondary"]["weekly_lift"]
    weekly = {w: estimate(wl["estimator"], load_customer_week(con, prereg, w), wl["metric"], prereg)
              for w in range(first, last + 1)}  # fmt: skip

    # 7-9. Remaining secondary analyses (steady state, CUPED, account-age regression).
    secondary = {
        name: estimate(spec["estimator"], frames[spec["window"]], spec["metric"], prereg)
        for name, spec in prereg["secondary"].items()
        if "window" in spec and spec["estimator"] != nb["estimator"]
    }
    out["secondary"] = _labeled(PRE_REGISTERED, {"weekly": weekly, **secondary})

    # 10. Three-way early dispute read, plus the exploratory reason and lag mix by arm.
    early = run_early_read(con, frames[prereg["guardrails"][dispute_metric]["window"]], prereg)
    g = prereg["guardrails"][dispute_metric]
    early["non_inferiority"] = {
        name: non_inferiority(e, g["margin_absolute"], g["alpha_one_sided"]) for name, e in early["reads"].items()
    }
    out["early_dispute_read"] = _labeled(PRE_REGISTERED, early)
    out["dispute_mix_by_arm"] = dispute_mix_by_arm(con, prereg)

    _write(out, alpha, segments=segments, grid=grid, weekly=weekly, weekly_key=wl["by"])
    return out


def _effect_rows(effects: dict[Any, Effect], alpha: float, key: str) -> pd.DataFrame:
    return pd.DataFrame([{key: k, **e.as_dict(alpha)} for k, e in effects.items()])


def _write(
    out: dict[str, Any],
    alpha: float,
    segments: pd.DataFrame | None = None,
    grid: pd.DataFrame | None = None,
    weekly: dict[int, Effect] | None = None,
    weekly_key: str = "week",
) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(_jsonable(out, alpha), indent=2))
    if segments is not None:
        _round_frame(segments).to_csv(RESULTS_DIR / "segments.csv", index=False)
    if grid is not None:
        _round_frame(grid).to_csv(RESULTS_DIR / "sensitivity_grid.csv", index=False)
    if weekly is not None:
        _round_frame(_effect_rows(weekly, alpha, weekly_key)).to_csv(RESULTS_DIR / "weekly_lift.csv", index=False)


def main() -> None:
    """Run the analysis if unblinded; write machine-readable results and the summary table."""
    settings = load_settings()
    if not settings.unblinded:
        raise SystemExit("analysis.unblinded is false in config/settings.yaml; run after pre-registration")
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as con:
        out = run(con)
    from analysis.summary import write_summary

    write_summary(out, load_prereg())
    print(f"wrote {RESULTS_DIR.relative_to(PROJECT_ROOT)}/: decision = {out['decision']['decision']}")


if __name__ == "__main__":
    main()
