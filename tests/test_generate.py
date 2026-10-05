"""Fast generator tests on a small population. The generator runs as a black box via its CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from generate.assignment import assign_variants, hash_bucket
from generate.pipeline import RAW_TABLES
from generate.settings import load_settings, to_epoch

SMALL_N = 3_000


def _run_generator(out: Path, *extra: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "generate",
            "--n-customers",
            str(SMALL_N),
            "--raw-dir",
            str(out / "raw"),
            "--truth-dir",
            str(out / "truth"),
            "--skip-load",
            *extra,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    a, b = tmp_path_factory.mktemp("run_a"), tmp_path_factory.mktemp("run_b")
    _run_generator(a)
    _run_generator(b)
    return a / "raw", b / "raw"


def test_generation_is_deterministic(two_runs: tuple[Path, Path]) -> None:
    raw_a, raw_b = two_runs
    for name in RAW_TABLES:
        pd.testing.assert_frame_equal(
            pd.read_parquet(raw_a / f"{name}.parquet"), pd.read_parquet(raw_b / f"{name}.parquet")
        )


def test_no_private_columns_leak(two_runs: tuple[Path, Path]) -> None:
    raw_a, _ = two_runs
    for name in RAW_TABLES:
        cols = pd.read_parquet(raw_a / f"{name}.parquet").columns
        assert not [c for c in cols if c.startswith("_") or "risk_tier" in c], name


def test_small_run_has_one_assignment_per_customer(two_runs: tuple[Path, Path]) -> None:
    raw_a, _ = two_runs
    customers = pd.read_parquet(raw_a / "customers.parquet")
    assignments = pd.read_parquet(raw_a / "experiment_assignments.parquet")
    assert len(customers) == SMALL_N
    assert assignments["customer_id"].is_unique
    assert set(assignments["customer_id"]) == set(customers["id"])


def test_hash_bucket_is_stable() -> None:
    assert hash_bucket("cus_ABC123", "salt") == hash_bucket("cus_ABC123", "salt")
    assert hash_bucket("cus_ABC123", "salt") != hash_bucket("cus_ABC123", "other_salt")


def test_hash_assignment_is_balanced() -> None:
    ids = np.array([f"cus_{i:08d}" for i in range(100_000)], dtype=object)
    share = (assign_variants(ids, "exp_test", 0.5) == "treatment").mean()
    assert abs(share - 0.5) < 0.005


def test_preperiod_outcomes_do_not_depend_on_assignment(
    two_runs: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Re-bucketing customers with another salt must leave every pre-period outcome unchanged."""
    other = tmp_path_factory.mktemp("other_salt")
    _run_generator(other, "--hash-salt", "some_other_salt")
    start = to_epoch(load_settings().start_date)
    cols = ["payment_intent", "status", "captured", "amount"]

    def preperiod_charges(raw: Path) -> pd.DataFrame:
        sessions = pd.read_parquet(raw / "checkout_sessions.parquet")
        pre_pis = sessions.loc[sessions["created"] < start, "payment_intent"]
        charges = pd.read_parquet(raw / "charges.parquet")
        return charges.loc[charges["payment_intent"].isin(pre_pis), cols].sort_values("payment_intent")

    a = pd.read_parquet(two_runs[0] / "experiment_assignments.parquet")
    b = pd.read_parquet(other / "raw" / "experiment_assignments.parquet")
    assert (a["variant"] != b["variant"]).any()
    pd.testing.assert_frame_equal(
        preperiod_charges(two_runs[0]).reset_index(drop=True), preperiod_charges(other / "raw").reset_index(drop=True)
    )
