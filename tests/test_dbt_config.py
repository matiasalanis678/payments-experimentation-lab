"""dbt vars must agree with config/settings.yaml, the single source of truth for experiment design."""

from __future__ import annotations

import yaml

from generate.settings import PROJECT_ROOT, load_settings


def test_dbt_vars_match_settings() -> None:
    settings = load_settings()
    dbt_vars = yaml.safe_load((PROJECT_ROOT / "dbt" / "dbt_project.yml").read_text())["vars"]
    expected = {
        "experiment_id": settings.experiment_id,
        "experiment_start_date": settings.start_date.isoformat(),
        "experiment_end_date": settings.end_date.isoformat(),
        "pre_period_start_date": settings.pre_start_date.isoformat(),
        "analysis_date": settings.analysis_date.isoformat(),
        "dispute_maturity_days": settings.dispute_maturity_days,
    }
    assert {k: dbt_vars[k] for k in expected} == expected


SAVED_QUERIES = yaml.safe_load((PROJECT_ROOT / "dbt" / "models" / "semantic" / "_saved_queries.yml").read_text())[
    "saved_queries"
]
GATE_TAG = "in_window_variant_split"


def _where(sq: dict) -> str:
    return " ".join(sq["query_params"].get("where", []))


def test_saved_query_dates_match_settings() -> None:
    settings = load_settings()
    allowed = {f"'{settings.start_date.isoformat()}'", f"'{settings.end_date.isoformat()}'"}
    for sq in SAVED_QUERIES:
        quoted_dates = {tok for tok in _where(sq).split() if tok.startswith("'2026-")}
        assert quoted_dates <= allowed, (sq["name"], quoted_dates)


def test_variant_splits_are_preperiod_only_or_gated() -> None:
    """Blindness: a variant split must be pre-period only, or tagged and run only behind the unblinded gate."""
    script = (PROJECT_ROOT / "scripts" / "mf_queries.sh").read_text()
    gate = script.index('if [[ "$UNBLINDED" == "true" ]]; then')
    gate_end = script.index("else", gate)
    start = load_settings().start_date.isoformat()
    for sq in SAVED_QUERIES:
        if not any("variant" in g for g in sq["query_params"]["group_by"]):
            continue
        name, where = sq["name"], _where(sq)
        preperiod_only = f"< '{start}'" in where and f">= '{start}'" not in where
        if preperiod_only:
            assert GATE_TAG not in sq.get("tags", []), name
            continue
        assert GATE_TAG in sq.get("tags", []), f"{name} splits by variant in-window but is not tagged"
        calls = [i for i in range(len(script)) if script.startswith(f"run {name} ", i)]
        assert calls and all(gate < i < gate_end for i in calls), f"{name} runs outside the unblinded gate"
