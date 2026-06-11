#!/usr/bin/env bash
# End-to-end driver for the Korean tidal-flat area methodology
# (korea-tidal-flat-area plan, Phases 0-5).
#
# Each phase is idempotent: re-running it skips already-cached outputs.
# Set ``EE_PROJECT`` and ``KHOA_API_KEY`` in your environment before
# invoking. Adjust the date range with the env vars below.
#
# Usage:
#   EE_PROJECT=<project> KHOA_API_KEY=<key> bash scripts/run_korea_tidalflat_pipeline.sh
#
# Skip individual phases with the SKIP_* env vars (e.g. SKIP_PHASE0=1).

set -euo pipefail

START_YEAR="${START_YEAR:-2016}"
END_YEAR="${END_YEAR:-2024}"
ROLLING="${ROLLING:-3}"
# MSIC-OA export scale. 10 m respects Jia (2021) but exceeds the GEE 50 MB
# sync download cap on Korean coastal bboxes (~30 km × 30 km). The default
# is 30 m so raster artefacts download in one shot; bump back to 10 with
# MSIC_SCALE_M=10 if you have set MSIC_EXPORT_MODE=drive or none.
MSIC_SCALE_M="${MSIC_SCALE_M:-30}"
MSIC_EXPORT_MODE="${MSIC_EXPORT_MODE:-local}"

cd "$(dirname "$0")/.."

# Resolve to the venv interpreter explicitly. Zsh aliases like
# `alias python=/usr/local/bin/python3` win over PATH after `source
# .venv/bin/activate`, so we bypass `python` entirely and call PYTHON
# directly throughout the pipeline.
PYTHON="${PWD}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: project venv not found at $PYTHON" >&2
    echo "Create it with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi
echo "[pipeline] Using venv python: $PYTHON ($($PYTHON --version))"

# Ensure `from src.xxx import …` resolves from the project root.
export PYTHONPATH="${PWD}:${PYTHONPATH:-}"

# Headless matplotlib + writable config dir. The macOS font-cache build path
# can SIGABRT inside the sandbox if `~/.matplotlib` is not writable and the
# default backend tries to talk to system_profiler. Pin both to safe values.
export MPLBACKEND="${MPLBACKEND:-Agg}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-${PWD}/.cache/matplotlib}"
mkdir -p "$MPLCONFIGDIR"

run_step() {
    local name="$1"
    shift
    echo ""
    echo "=== ${name} ==="
    "$@"
}

# ---------------------------------------------------------------------------
# Phase 0: reference data
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_PHASE0:-}" ]]; then
    run_step "Phase 0a Murray v1.1 / JCU-2019" \
        "$PYTHON" scripts/download_murray_v12.py
    run_step "Phase 0b GWL_FCS30" \
        bash scripts/download_gwl_fcs30.sh || true
    run_step "Phase 0c GTF30" \
        bash scripts/download_gtf30.sh || true
    run_step "Phase 0d MOF (if raw CSV staged)" \
        "$PYTHON" scripts/prepare_mof_reference.py || true
    run_step "Phase 0e ingest references" \
        "$PYTHON" scripts/ingest_reference_extents.py
fi

# ---------------------------------------------------------------------------
# Phase 1: pilot sites
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_PHASE1A:-}" ]]; then
    run_step "Phase 1a MSIC-OA" \
        "$PYTHON" scripts/run_msic_oa.py \
        --start-year "${START_YEAR}" --end-year "${END_YEAR}" --rolling "${ROLLING}" \
        --scale-m "${MSIC_SCALE_M}" --export-mode "${MSIC_EXPORT_MODE}"
fi

if [[ -z "${SKIP_PHASE1B:-}" ]]; then
    # Phase 1b depends on FES2022b/FES2014 NetCDFs being present and
    # readable by pyTMD; if the model files are missing or pyTMD hangs
    # on FES2022 (a known issue with the unconverted .nc layout) the
    # script exits with placeholder nan rows. We mark the step optional
    # with `|| true` so downstream phases (1c, 1d, 2, 3) still run.
    run_step "Phase 1b bias-QA" \
        "$PYTHON" scripts/run_bias_qa.py \
        --start-year "${START_YEAR}" --end-year "${END_YEAR}" --rolling "${ROLLING}" \
        || echo "[pipeline] Phase 1b returned non-zero — continuing."
fi

if [[ -z "${SKIP_PHASE1C:-}" ]]; then
    run_step "Phase 1c annual V4 DEM" \
        "$PYTHON" scripts/run_annual_v4_dem.py \
        --start-year "${START_YEAR}" --end-year "${END_YEAR}" --rolling "${ROLLING}"
fi

if [[ -z "${SKIP_PHASE1D:-}" ]]; then
    run_step "Phase 1d extent fusion + DEM area" \
        "$PYTHON" scripts/run_extent_fusion.py \
        --start-year "${START_YEAR}" --end-year "${END_YEAR}"
fi

# ---------------------------------------------------------------------------
# Phase 2: observation-frequency correction
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_PHASE2:-}" ]]; then
    run_step "Phase 2 obs-frequency correction" \
        "$PYTHON" scripts/run_obsfreq_correction.py
fi

# ---------------------------------------------------------------------------
# Phase 3: cross-validation
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_PHASE3:-}" ]]; then
    run_step "Phase 3 area validation" \
        "$PYTHON" scripts/run_area_validation.py --use-corrected
fi

# ---------------------------------------------------------------------------
# Phase 4: national extension
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_PHASE4:-}" ]]; then
    run_step "Phase 4b national extent" \
        "$PYTHON" scripts/run_national_extent.py \
        --start-year "${START_YEAR}" --end-year "${END_YEAR}" --rolling "${ROLLING}"
    # Phase 4c: per-province area. We use the CORRECTED accounting
    # (run_national_area_corrected.py): the legacy run_national_mosaic.py
    # clips DEM pixels to admin coastline polygons, which discards ~83% of
    # tidal flat lying seaward of the high-water mark. The corrected driver
    # attributes each flat pixel to its nearest MOF province zone instead.
    for _yr in $(seq "${START_YEAR}" "${END_YEAR}"); do
        run_step "Phase 4c national area (corrected) ${_yr}" \
            "$PYTHON" scripts/run_national_area_corrected.py --year "${_yr}" || true
    done
fi

# ---------------------------------------------------------------------------
# Phase 5: report
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_PHASE5:-}" ]]; then
    run_step "Phase 5 figures + master CSV" \
        "$PYTHON" scripts/run_phase5_report.py
fi

echo ""
echo "=== Pipeline complete. Outputs:"
echo "  data/outputs/tables/area_summary_master.csv"
echo "  data/outputs/figures/*.png"
echo "  data/outputs/extent/, data/outputs/dem/annual/, data/outputs/national/"
