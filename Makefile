.PHONY: all install generate test test-fast lint format clean

all: clean install generate lint test

install:
	uv sync

generate:
	uv run python -m generate

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
	rm -rf data/raw data/truth data/warehouse.duckdb data/warehouse.duckdb.wal
