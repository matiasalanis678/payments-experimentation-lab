"""Enforce CONVENTIONS.md mechanically."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
TRUTH_MARKERS = ("truth.yaml", "load_truth", "generate.truth", "customer_risk_tiers", "truth_dir")
# The generator plants the effects, recovery checks them, hidden balance checks randomization,
# and this file names the markers.
TRUTH_ALLOWED = (
    "src/generate/",
    "tests/test_recovery.py",
    "tests/test_hidden_balance.py",
    "tests/test_conventions.py",
)
CODE_SUFFIXES = {".py", ".sql", ".sh", ".yml", ".yaml"}


def _tracked_and_untracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if (ROOT / line).is_file()]


def test_only_allowed_code_reads_truth() -> None:
    offenders = []
    for path in _tracked_and_untracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix not in CODE_SUFFIXES or rel.startswith(TRUTH_ALLOWED) or rel.startswith("config/"):
            continue
        text = path.read_text(errors="ignore")
        offenders += [f"{rel}: {m}" for m in TRUTH_MARKERS if m in text]
    assert not offenders, offenders


def test_no_em_dashes() -> None:
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in _tracked_and_untracked_files()
        if p.suffix in CODE_SUFFIXES | {".md", ".toml", ".txt"} and EM_DASH in p.read_text(errors="ignore")
    ]
    assert not offenders, offenders
