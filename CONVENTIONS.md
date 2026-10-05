# Conventions

Payments experimentation lab: synthetic Stripe-like checkout data, a dbt + DuckDB warehouse, a MetricFlow semantic layer, and a pre-registered A/B test analysis of removing the CVC field. The full plan lives in PLAN.md.

## Conventions
- Analysis code never reads config/truth.yaml; only tests/test_recovery.py may. The generator (src/generate/) is the only other consumer, because it plants the effects.
- All randomness seeded from config/settings.yaml.
- Transformations in dbt SQL; Python only for generation and statistics.
- No em dashes in any written docs or comments.
- Small typed functions, docstrings on public functions.
- Each phase ends with a review checkpoint before the next begins.

## Commands
- `uv sync` installs dependencies (Python 3.12).
- `make all` rebuilds everything from scratch.
- `make generate` writes data/raw/*.parquet and loads data/warehouse.duckdb.
- `make test` runs pytest; `make lint` runs ruff.
