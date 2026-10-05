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
