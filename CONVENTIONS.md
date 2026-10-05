# Conventions

Payments experimentation lab: synthetic Stripe-like checkout data, a dbt + DuckDB warehouse, a MetricFlow semantic layer, and a pre-registered A/B test analysis of removing the CVC field. The full plan lives in PLAN.md.

## Conventions
- Analysis code never reads config/truth.yaml or data/truth/; only tests/test_recovery.py may. Two other exceptions: the generator (src/generate/), because it plants the effects, and tests/test_hidden_balance.py, which reads data/truth/customer_risk_tiers.parquet only to confirm hidden risk is balanced across arms. tests/test_conventions.py enforces this list.
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
