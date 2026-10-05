"""CLI: `uv run python -m generate [--n-customers N]`."""

from __future__ import annotations

import argparse
import dataclasses
import time
from pathlib import Path

from generate.pipeline import generate, load_warehouse, write_parquet
from generate.settings import load_settings
from generate.truth import load_truth


def main(argv: list[str] | None = None) -> None:
    """Generate raw parquet files and load them into the DuckDB warehouse."""
    parser = argparse.ArgumentParser(description="Generate the synthetic payments experiment dataset.")
    parser.add_argument("--n-customers", type=int, help="override simulation.n_customers")
    parser.add_argument("--raw-dir", type=Path, help="override paths.raw_dir")
    parser.add_argument("--truth-dir", type=Path, help="override paths.truth_dir")
    parser.add_argument("--hash-salt", help="override experiment.hash_salt")
    parser.add_argument("--seed", type=int, help="override the master seed (coverage simulations)")
    parser.add_argument("--skip-load", action="store_true", help="write parquet only")
    args = parser.parse_args(argv)

    settings = load_settings()
    overrides = {
        "n_customers": args.n_customers,
        "raw_dir": args.raw_dir,
        "truth_dir": args.truth_dir,
        "hash_salt": args.hash_salt,
        "seed": args.seed,
    }
    settings = dataclasses.replace(settings, **{k: v for k, v in overrides.items() if v is not None})

    t0 = time.perf_counter()
    data = generate(settings, load_truth())
    write_parquet(data, settings.raw_dir, settings.truth_dir)
    print(f"generated in {time.perf_counter() - t0:.1f}s (seed {settings.seed})")
    for name, df in data.tables.items():
        print(f"  {name:<24}{len(df):>12,}")
    lifts = ", ".join(f"{k} {v:+.1%}" for k, v in data.dispute_tier_lifts.items())
    print(f"  calibrated dispute lift by hidden tier: {lifts}")

    if not args.skip_load:
        counts = load_warehouse(settings.raw_dir, settings.warehouse_path)
        print(f"loaded {len(counts)} tables into {settings.warehouse_path.name} (schema raw)")


if __name__ == "__main__":
    main()
