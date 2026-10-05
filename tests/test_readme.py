"""The README's headline numbers must match the committed results (guards against drift after a rerun)."""

from __future__ import annotations

import json

import pytest

from analysis.prereg import load_prereg
from analysis.readout import _usd_m, band_annual_values
from generate.settings import PROJECT_ROOT

README = (PROJECT_ROOT / "README.md").read_text()
RESULTS = PROJECT_ROOT / "reports" / "results" / "results.json"
COVERAGE = PROJECT_ROOT / "reports" / "coverage.json"
pytestmark = pytest.mark.skipif(not RESULTS.exists(), reason="run `make analyze` first")


@pytest.fixture(scope="module")
def results() -> dict:
    return json.loads(RESULTS.read_text())


def test_decision_matches(results: dict) -> None:
    assert results["decision"]["decision"].lower() in README.lower()


def test_dollar_figures_match(results: dict) -> None:
    values = band_annual_values(results, load_prereg())
    by_status = {}
    for v in values.values():
        by_status[v["status"]] = by_status.get(v["status"], 0.0) + v["annual"]
    for figure in (results["economics"]["annualized"]["annual"], by_status["qualifies"], by_status["inconclusive"]):
        assert _usd_m(figure) in README, _usd_m(figure)


def test_headline_lifts_match(results: dict) -> None:
    assert f"{results['primary']['effect']['relative']:+.1%}" in README
    assert f"{results['guardrails']['dispute_rate']['effect']['relative']:+.1%}" in README


@pytest.mark.skipif(not COVERAGE.exists(), reason="run `make coverage` first")
def test_coverage_table_matches() -> None:
    for row in json.loads(COVERAGE.read_text())["coverage"]:
        assert f"{int(row['sum'])}/{int(row['count'])}" in README, row["quantity"]
