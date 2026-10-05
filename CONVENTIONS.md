# Conventions

Payments experimentation lab: synthetic Stripe-like checkout data, a dbt + DuckDB warehouse, a MetricFlow semantic layer, and a pre-registered A/B test analysis of removing the CVC field. The full plan lives in PLAN.md.

## Conventions
- Analysis code never reads config/truth.yaml or data/truth/; only tests/test_recovery.py may. Two other exceptions: the generator (src/generate/), because it plants the effects, and tests/test_hidden_balance.py, which reads data/truth/customer_risk_tiers.parquet only to confirm hidden risk is balanced across arms. tests/test_conventions.py enforces this list.
- All randomness seeded from config/settings.yaml.
- Transformations in dbt SQL; Python only for generation and statistics.
- No em dashes in any written docs or comments.
- Small typed functions, docstrings on public functions.
- Each phase ends with a review checkpoint before the next begins.
- Blindness: no in-window treatment vs control comparison runs while `analysis.unblinded` is false in config/settings.yaml. Variant splits are pre-period only or tagged `in_window_variant_split` and gated in scripts/mf_queries.sh (tests/test_dbt_config.py enforces this).
- Every analysis parameter (metrics, estimators, alpha, margins, windows, segments, correction, decision rules, economic assumptions) is read from config/prereg.yaml via `analysis.prereg.load_prereg`; never hardcode them (tests/test_prereg.py scans analysis/ for literals). Interpret prereg strings by passing them to libraries or dispatching by function name, not by comparing to literals.
- config/prereg.yaml and reports/preregistration.md are frozen at tag prereg-v1. Log any deviation in reports/deviations.md instead of editing them.
- Analysis population is exposed customers only: build every SRM and analysis input on `analysis.population.EXPOSED_CUSTOMERS_SQL`.

## Commands
- `uv sync` installs dependencies (Python 3.12).
- `make all` rebuilds everything from scratch.
- `make generate` writes data/raw/*.parquet and loads data/warehouse.duckdb.
- `make dbt` runs `dbt build` from inside dbt/ (all dbt and mf commands run from dbt/; the profile path is relative to it).
- dbt vars in dbt/dbt_project.yml must match config/settings.yaml (tests/test_dbt_config.py).
- `make charts` writes reports/figures/; `make readout` writes reports/experiment_readout.md from the results.
- `make coverage` (slow, about 3 minutes, not in `make all`) runs the CI coverage simulation into reports/coverage.md and reports/coverage.json.
- `make analyze` runs the pre-registered analysis (analysis/experiment.py) into reports/results/.
- `make semantic` runs `mf validate-configs`; `make mf-queries` runs scripts/mf_queries.sh into reports/mf/.
- `make test` runs pytest; `make lint` runs ruff.
