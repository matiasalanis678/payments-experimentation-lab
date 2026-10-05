"""Loader for config/truth.yaml. Only the generator and tests/test_recovery.py may import this."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from generate.settings import PROJECT_ROOT

TRUTH_PATH = PROJECT_ROOT / "config" / "truth.yaml"


def load_truth(path: Path = TRUTH_PATH) -> dict[str, Any]:
    """Return the data-generating process: `world` (baseline behavior) and `effects` (planted lifts)."""
    return yaml.safe_load(path.read_text())
