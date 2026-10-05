#!/usr/bin/env bash
# Run the five standard MetricFlow saved queries and write CSVs to reports/mf/.
#
# Blindness gate: the three in-window treatment vs control queries run only when
# analysis.unblinded is true in config/settings.yaml. It stays false until the
# "pre-registration" commit; Phase 5 flips it. Until then only the pooled and
# pre-period (A/A) queries run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/reports/mf"
mkdir -p "$OUT"
cd "$ROOT/dbt"

run() {
  local name=$1; shift
  echo "mf query --saved-query $name $*"
  uv run mf query --saved-query "$name" "$@" --csv "$OUT/$name.csv" > /dev/null
  # Parallel float sums differ in the last digits run to run; round so outputs are stable:
  # USD totals to the cent, rates and per-transaction values to 8 decimals.
  uv run python - "$OUT/$name.csv" <<'PY'
import sys
import pandas as pd
df = pd.read_csv(sys.argv[1])
num = df.select_dtypes("float").columns
df[num] = df[num].apply(lambda col: col.round(2) if col.abs().max() >= 1000 else col.round(8))
df.to_csv(sys.argv[1], index=False)
PY
}

UNBLINDED=$(uv run python -c "from generate.settings import load_settings; print(str(load_settings().unblinded).lower())")

# 1. By week, pooled across variants (no treatment comparison).
run weekly_kpis --order metric_time__week
# 2. By variant, pre-period only (A/A: no treatment had been applied).
run preperiod_by_variant --order customer__variant

if [[ "$UNBLINDED" == "true" ]]; then
  # 3. By variant, experiment window: the headline scorecard.
  run experiment_scorecard_by_variant --order customer__variant
  # 4. By week and variant, experiment window: novelty check.
  run experiment_weekly_by_variant --order metric_time__week,customer__variant
  # 5. By country and variant, experiment window.
  run experiment_country_by_variant --order customer__country,customer__variant
else
  echo "Skipping 3 in-window variant queries: analysis.unblinded is false (pre-registration not committed yet)."
fi
echo "Wrote $(ls "$OUT" | wc -l | tr -d ' ') CSV files to reports/mf/"
