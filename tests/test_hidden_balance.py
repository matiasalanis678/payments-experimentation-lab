"""Balance of the hidden risk tier across arms.

Truth exception (see CONVENTIONS.md): this test reads data/truth/customer_risk_tiers.parquet. A real company
cannot see this label; we check it only to confirm randomization did not split hidden risk unevenly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from generate.settings import load_settings

SETTINGS = load_settings()
TIERS_PATH = SETTINGS.truth_dir / "customer_risk_tiers.parquet"
ASSIGNMENTS_PATH = SETTINGS.raw_dir / "experiment_assignments.parquet"
pytestmark = [
    pytest.mark.full_data,
    pytest.mark.skipif(not (TIERS_PATH.exists() and ASSIGNMENTS_PATH.exists()), reason="run `make generate`"),
]


@pytest.fixture(scope="module")
def tiers() -> pd.DataFrame:
    return pd.read_parquet(TIERS_PATH).merge(pd.read_parquet(ASSIGNMENTS_PATH), on="customer_id", validate="one_to_one")


def test_risk_tier_distribution_balanced(tiers: pd.DataFrame) -> None:
    assert stats.chi2_contingency(pd.crosstab(tiers["risk_tier"], tiers["variant"])).pvalue > 0.001


def test_high_risk_share_within_3_ses(tiers: pd.DataFrame) -> None:
    high = tiers["risk_tier"].eq("high")
    by_arm = high.groupby(tiers["variant"]).agg(["mean", "count"])
    p = by_arm["mean"]
    se = np.sqrt((p * (1 - p) / by_arm["count"]).sum())
    z = (p["treatment"] - p["control"]) / se
    assert abs(z) < 3, f"high-tier share z={z:+.2f}"
