"""Guards on the pre-registration (config/prereg.yaml, reports/preregistration.md, tag prereg-v1)."""

from __future__ import annotations

import ast
import math
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest

from analysis.power import compute_baselines, compute_derived
from analysis.prereg import PREREG_PATH, load_prereg
from generate.settings import PROJECT_ROOT, load_settings

PREREG = load_prereg()
SETTINGS = load_settings()
TAG = "prereg-v1"
FROZEN_FILES = ("config/prereg.yaml", "reports/preregistration.md")
# Numbers too generic to attribute to the pre-registration (0, 1, 2, halves, percent scaling).
TRIVIAL_NUMBERS = {0, 1, -1, 2, 0.5, 100}


def _leaves(tree: Any) -> Iterator[Any]:
    if isinstance(tree, dict):
        for v in tree.values():
            yield from _leaves(v)
    elif isinstance(tree, list):
        for v in tree:
            yield from _leaves(v)
    else:
        yield tree


def _prereg_values() -> tuple[set[float], set[str]]:
    numbers, strings = set(), set()
    for v in _leaves(PREREG):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int | float) and v not in TRIVIAL_NUMBERS:
            numbers.add(float(v))
        elif isinstance(v, str):
            strings.add(v)
    return numbers, strings


def _name_positions(tree: ast.AST) -> set[int]:
    """ids of Constant nodes used as names (dict keys, subscripts) or docstrings, which are allowed."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            allowed |= {id(k) for k in node.keys if k is not None}
        elif isinstance(node, ast.Subscript):
            allowed.add(id(node.slice))
        elif isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef) and ast.get_docstring(node) is not None:
            allowed.add(id(node.body[0].value))
    return allowed


def test_analysis_code_does_not_hardcode_prereg_values() -> None:
    numbers, strings = _prereg_values()
    offenders = []
    for path in sorted((PROJECT_ROOT / "analysis").glob("*.py")):
        tree = ast.parse(path.read_text())
        allowed = _name_positions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or id(node) in allowed or isinstance(node.value, bool):
                continue
            v = node.value
            hit = (isinstance(v, str) and v in strings) or (
                isinstance(v, int | float) and any(math.isclose(v, n, rel_tol=1e-12) for n in numbers)
            )
            if hit:
                offenders.append(f"{path.name}:{node.lineno} {v!r}")
    assert not offenders, "read these from config/prereg.yaml instead: " + ", ".join(offenders)


def test_prereg_sections_present() -> None:
    required = {"population", "srm", "alpha", "power", "windows", "primary", "secondary", "guardrails",
                "early_dispute_read", "segments", "economics", "baselines", "derived", "decision_rules"}  # fmt: skip
    assert required <= PREREG.keys()


def test_dispute_margin_follows_from_economics() -> None:
    assert compute_derived(PREREG, PREREG["baselines"]) == PREREG["derived"]
    assert PREREG["guardrails"]["dispute_rate"]["margin_absolute"] == PREREG["derived"]["dispute_margin_absolute"]


@pytest.mark.full_data
@pytest.mark.skipif(not SETTINGS.warehouse_path.exists(), reason="run `make generate dbt` first")
def test_baselines_reproduce_from_preperiod_data() -> None:
    with duckdb.connect(str(SETTINGS.warehouse_path), read_only=True) as con:
        fresh = compute_baselines(con, PREREG)
    assert fresh == PREREG["baselines"]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


def _tag_exists() -> bool:
    return _git("rev-parse", "-q", "--verify", f"refs/tags/{TAG}").returncode == 0


def test_unblinding_requires_prereg_tag() -> None:
    if SETTINGS.unblinded:
        assert _tag_exists(), f"analysis.unblinded is true but tag {TAG} does not exist"


@pytest.mark.parametrize("rel", FROZEN_FILES)
def test_preregistration_unchanged_since_tag(rel: str) -> None:
    if not _tag_exists():
        pytest.skip(f"tag {TAG} not created yet")
    tagged = _git("show", f"{TAG}:{rel}")
    assert tagged.returncode == 0, f"{rel} missing from {TAG}"
    assert (PROJECT_ROOT / rel).read_text() == tagged.stdout, f"{rel} changed since {TAG}; log deviations elsewhere"


def test_prereg_path_is_config() -> None:
    assert Path(PREREG_PATH).relative_to(PROJECT_ROOT).as_posix() == "config/prereg.yaml"
