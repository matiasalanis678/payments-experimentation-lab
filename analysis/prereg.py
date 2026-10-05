"""Loader for config/prereg.yaml, the machine-readable pre-registration.

Every analysis parameter (metrics, estimators, alpha, margins, windows, segments, correction method,
decision rules, economic assumptions) comes from that file. tests/test_prereg.py fails if analysis
code hardcodes any of its values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from generate.settings import PROJECT_ROOT

PREREG_PATH = PROJECT_ROOT / "config" / "prereg.yaml"


def load_prereg(path: Path = PREREG_PATH) -> dict[str, Any]:
    """Return the pre-registration as a nested dict."""
    return yaml.safe_load(path.read_text())


def window_weeks(prereg: dict[str, Any], window: str) -> tuple[int, int]:
    """(first_week, last_week) of a pre-registered analysis window, inclusive."""
    w = prereg["windows"][window]
    return int(w["first_week"]), int(w["last_week"])
