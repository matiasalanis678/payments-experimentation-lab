"""Project settings loader. Safe for analysis code to import (does not touch truth.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class Settings:
    """Typed view of config/settings.yaml."""

    seed: int
    experiment_id: str
    experiment_name: str
    start_date: date
    weeks: int
    hash_salt: str
    treatment_share: float
    dispute_maturity_days: int
    analysis_date: date
    pre_period_weeks: int
    n_customers: int
    raw_dir: Path
    truth_dir: Path
    warehouse_path: Path

    @property
    def end_date(self) -> date:
        """Exclusive end of the experiment window."""
        return self.start_date + timedelta(weeks=self.weeks)

    @property
    def pre_start_date(self) -> date:
        """Inclusive start of the pre-experiment window."""
        return self.start_date - timedelta(weeks=self.pre_period_weeks)


def to_epoch(day: date) -> int:
    """Unix seconds at UTC midnight of `day`, matching Stripe's `created` convention."""
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Read settings.yaml into a frozen Settings object with paths resolved to the project root."""
    raw = yaml.safe_load(path.read_text())
    exp, analysis, paths = raw["experiment"], raw["analysis"], raw["paths"]
    return Settings(
        seed=int(raw["seed"]),
        experiment_id=exp["id"],
        experiment_name=exp["name"],
        start_date=exp["start_date"],
        weeks=int(exp["weeks"]),
        hash_salt=exp["hash_salt"],
        treatment_share=float(exp["treatment_share"]),
        dispute_maturity_days=int(analysis["dispute_maturity_days"]),
        analysis_date=analysis["analysis_date"],
        pre_period_weeks=int(analysis["pre_period_weeks"]),
        n_customers=int(raw["simulation"]["n_customers"]),
        raw_dir=PROJECT_ROOT / paths["raw_dir"],
        truth_dir=PROJECT_ROOT / paths["truth_dir"],
        warehouse_path=PROJECT_ROOT / paths["warehouse"],
    )
