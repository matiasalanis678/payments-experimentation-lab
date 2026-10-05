"""Customer-level experiment bucketing by deterministic hash."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

CONTROL = "control"
TREATMENT = "treatment"
_BUCKETS = 10_000


def hash_bucket(customer_id: str, salt: str) -> int:
    """Map a customer id to a stable bucket in [0, 10000) using sha256(salt:customer_id)."""
    digest = hashlib.sha256(f"{salt}:{customer_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % _BUCKETS


def assign_variants(customer_ids: np.ndarray, salt: str, treatment_share: float) -> np.ndarray:
    """Return 'control' or 'treatment' per customer. Same id and salt always give the same variant."""
    cutoff = round(treatment_share * _BUCKETS)
    buckets = np.fromiter((hash_bucket(c, salt) for c in customer_ids), dtype=np.int64)
    return np.where(buckets < cutoff, TREATMENT, CONTROL).astype(object)


def build_assignments(
    customer_ids: np.ndarray,
    variants: np.ndarray,
    first_exposure: np.ndarray,
    experiment_id: str,
) -> pd.DataFrame:
    """Assemble the experiment_assignments table; assigned_at is the customer's first in-window session."""
    return pd.DataFrame(
        {
            "customer_id": customer_ids,
            "experiment_id": experiment_id,
            "variant": variants,
            "assigned_at": first_exposure.astype(np.int64),
        }
    )
