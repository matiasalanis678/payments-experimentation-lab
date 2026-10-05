"""Orchestrates generation, writes parquet, and loads the DuckDB raw schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from generate.assignment import assign_variants, build_assignments
from generate.customers import generate_customers
from generate.disputes import generate_disputes, solve_dispute_lifts
from generate.sessions import build_charges, build_checkout_sessions, schedule_sessions, simulate_funnel
from generate.settings import Settings

RAW_TABLES = ("customers", "checkout_sessions", "charges", "disputes", "experiment_assignments", "fx_rates")
_STEPS = ("customers", "sessions", "funnel", "session_ids", "charges", "disputes")


@dataclass
class GeneratedData:
    """Public raw tables plus hidden labels and calibration details."""

    tables: dict[str, pd.DataFrame]
    hidden_risk_tiers: pd.DataFrame
    dispute_tier_lifts: dict[str, float]


def _public(df: pd.DataFrame) -> pd.DataFrame:
    """Drop private simulation columns (prefixed with `_`)."""
    return df.loc[:, [c for c in df.columns if not c.startswith("_")]]


def _fx_rates(world: dict[str, Any]) -> pd.DataFrame:
    """Reference table of currency exponents and fixed USD conversion rates."""
    rows = [
        {"currency": c, "usd_per_unit": v["usd_per_unit"], "exponent": v["exponent"]}
        for c, v in world["currencies"].items()
    ]
    return pd.DataFrame(rows)


def generate(settings: Settings, truth: dict[str, Any]) -> GeneratedData:
    """Build every raw table deterministically from settings.seed.

    Each step draws from its own child generator, so changing one step never shifts another's randomness.
    """
    world, effects = truth["world"], truth["effects"]
    children = np.random.SeedSequence(settings.seed).spawn(len(_STEPS))
    rngs = {step: np.random.default_rng(seq) for step, seq in zip(_STEPS, children, strict=True)}

    customers = generate_customers(rngs["customers"], settings, world)
    customer_ids = customers["id"].to_numpy()
    variants = assign_variants(customer_ids, settings.hash_salt, settings.treatment_share)

    sessions = schedule_sessions(rngs["sessions"], customers, settings)
    funnel = simulate_funnel(rngs["funnel"], sessions, customers, variants, settings, world, effects)
    checkout_sessions = build_checkout_sessions(rngs["session_ids"], funnel, customer_ids)
    charges = build_charges(rngs["charges"], funnel, checkout_sessions, world)

    tier_lifts = solve_dispute_lifts(funnel, world, effects["dispute"])
    disputes = generate_disputes(rngs["disputes"], charges, tier_lifts, settings, world)

    in_window = funnel["_week"].to_numpy() > 0
    first_exposure = funnel.loc[in_window].groupby("_customer_idx")["created"].min().reindex(range(len(customers)))
    assignments = build_assignments(customer_ids, variants, first_exposure.to_numpy(), settings.experiment_id)

    tables = {
        "customers": _public(customers),
        "checkout_sessions": checkout_sessions,
        "charges": _public(charges),
        "disputes": disputes,
        "experiment_assignments": assignments,
        "fx_rates": _fx_rates(world),
    }
    hidden = pd.DataFrame({"customer_id": customer_ids, "risk_tier": customers["_risk_tier"].to_numpy()})
    return GeneratedData(tables=tables, hidden_risk_tiers=hidden, dispute_tier_lifts=tier_lifts)


def write_parquet(data: GeneratedData, raw_dir: Path, truth_dir: Path) -> None:
    """Write public tables to raw_dir and hidden labels to truth_dir."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    for name, df in data.tables.items():
        df.to_parquet(raw_dir / f"{name}.parquet", index=False)
    data.hidden_risk_tiers.to_parquet(truth_dir / "customer_risk_tiers.parquet", index=False)


def load_warehouse(raw_dir: Path, warehouse_path: Path) -> dict[str, int]:
    """Load every raw parquet file into the `raw` schema of the DuckDB warehouse; return row counts."""
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with duckdb.connect(str(warehouse_path)) as con:
        con.execute("create schema if not exists raw")
        for name in RAW_TABLES:
            path = (raw_dir / f"{name}.parquet").as_posix()
            con.execute(f"create or replace table raw.{name} as select * from read_parquet('{path}')")
            counts[name] = con.execute(f"select count(*) from raw.{name}").fetchone()[0]
    return counts
