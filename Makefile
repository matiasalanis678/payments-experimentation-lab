# Homebrew tools (gh) live outside the default non-login PATH on Apple Silicon.
export PATH := /opt/homebrew/bin:$(PATH)

.PHONY: all install generate dbt dbt-docs semantic mf-queries power test test-fast lint format clean

all: clean install generate dbt semantic mf-queries power lint test

install:
	uv sync

generate:
	uv run python -m generate

dbt:
	cd dbt && uv run dbt build

semantic:
	cd dbt && uv run mf validate-configs

mf-queries:
	scripts/mf_queries.sh

power:
	uv run python -m analysis.power

dbt-docs:
	cd dbt && uv run dbt docs generate

test:
	uv run pytest -q

test-fast:
	uv run pytest -q -m "not full_data"

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

clean:
	rm -rf data/raw data/truth data/warehouse.duckdb data/warehouse.duckdb.wal dbt/target dbt/logs reports/mf
