#!/usr/bin/env bash
# Drive the full pilot pipeline for both sites in sequence.
#
# Prerequisites (run once each):
#   1. python -m scripts.run_metadata_extraction --sites garorim suncheon
#   2. python -m scripts.run_s1_phase_diagnostic
#   3. KHOA hourly cache is warm (data/raw/khoa/tide_hourly/...)
#
# Output:
#   data/outputs/dem/garorim_v{1..4}.tif
#   data/outputs/dem/suncheon_v{1..4}.tif
#   data/outputs/tables/{site}_variant_diagnostics.csv

set -euo pipefail

PROJECT="${EE_PROJECT:-}"
ARGS=()
if [[ -n "${PROJECT}" ]]; then
  ARGS+=(--project "${PROJECT}")
fi

cd "$(dirname "$0")/.."

for SITE in ganghwa garorim gomso hampyeong suncheon; do
  echo "==============================================================="
  echo "  Pilot DEM for ${SITE}"
  echo "==============================================================="
  .venv/bin/python -m scripts.run_pilot_dem --site "${SITE}" "${ARGS[@]}" "$@"
done

echo ""
echo "All pilots complete. Next: scripts/run_dem_validation.py"
