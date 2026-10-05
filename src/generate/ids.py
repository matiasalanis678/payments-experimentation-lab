"""Stripe-style object identifiers (e.g. cus_..., ch_...)."""

from __future__ import annotations

import numpy as np

_ALPHABET = np.frombuffer(b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", dtype=np.uint8)


def make_ids(rng: np.random.Generator, prefix: str, n: int, length: int = 24) -> np.ndarray:
    """Return `n` unique random ids like `prefix + 24 base62 chars`, deterministic given `rng`."""
    chars = _ALPHABET[rng.integers(0, len(_ALPHABET), size=(n, length))]
    bodies = chars.view(f"S{length}").ravel().astype(str)
    ids = np.char.add(prefix, bodies).astype(object)
    if len(set(ids)) != n:
        raise ValueError(f"id collision while generating {prefix} ids")
    return ids
