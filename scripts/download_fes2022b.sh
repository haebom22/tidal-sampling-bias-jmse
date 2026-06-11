#!/usr/bin/env bash
# Download FES2022b tidal model data from AVISO+ THREDDS Data Server.
# Usage: bash scripts/download_fes2022b.sh
#
# Prerequisites:
#   - AVISO+ account (register at https://www.aviso.altimetry.fr/en/data/data-access/registration-form.html)
#   - Set environment variables AVISO_USER and AVISO_PASS, or enter interactively.

set -euo pipefail

# --- Configuration -----------------------------------------------------------
BASE_URL="https://tds-odatis.aviso.altimetry.fr/thredds/fileServer/dataset-auxiliary-fes-tide-model/fes2022b"
DATA_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/raw/fes2022b"

# Tidal constituents to download (main + shallow water nonlinear for tidal flats)
CONSTITUENTS=(
    # Primary constituents (required)
    m2 s2 k1 o1
    # Major secondary
    n2 p1 k2 q1
    # Shallow-water nonlinear (important for tidal flats)
    m4 ms4 mn4
    # Additional secondary
    nu2 mu2 2n2 j1 l2 lambda2 eps2
    # Long-period
    mf mm sa ssa msqm mtm msf
    # Other nonlinear
    m3 m6 m8 mks2 n4 s4
    # Remaining
    r2 s1 t2
)

# --- Credentials -------------------------------------------------------------
if [[ -z "${AVISO_USER:-}" ]]; then
    read -rp "AVISO+ email: " AVISO_USER
fi
if [[ -z "${AVISO_PASS:-}" ]]; then
    read -rsp "AVISO+ password: " AVISO_PASS
    echo
fi

# --- Helper -------------------------------------------------------------------
download_file() {
    local url="$1"
    local dest="$2"

    if [[ -f "$dest" ]]; then
        echo "  [skip] $(basename "$dest") already exists"
        return 0
    fi

    echo "  [download] $(basename "$dest")"
    curl -fSL --retry 3 --retry-delay 5 \
        -u "${AVISO_USER}:${AVISO_PASS}" \
        -o "$dest" \
        "$url" || {
        echo "  [FAIL] $(basename "$dest")" >&2
        rm -f "$dest"
        return 1
    }
}

decompress_xz() {
    local dir="$1"
    local count
    count=$(find "$dir" -name "*.nc.xz" 2>/dev/null | wc -l)
    if [[ "$count" -gt 0 ]]; then
        echo "  Decompressing $count .xz files in $(basename "$dir")..."
        xz -dk "$dir"/*.nc.xz 2>/dev/null || xz -d "$dir"/*.nc.xz
    fi
}

# --- Download ocean_tide_extrapolated ----------------------------------------
echo "=== Downloading ocean_tide_extrapolated (${#CONSTITUENTS[@]} constituents) ==="
OCEAN_DIR="${DATA_DIR}/ocean_tide_extrapolated"
mkdir -p "$OCEAN_DIR"

fail_count=0
for wave in "${CONSTITUENTS[@]}"; do
    download_file \
        "${BASE_URL}/ocean_tide_extrapolated/${wave}_fes2022.nc.xz" \
        "${OCEAN_DIR}/${wave}_fes2022.nc.xz" || ((fail_count++))
done

echo "  Ocean tide: $((${#CONSTITUENTS[@]} - fail_count))/${#CONSTITUENTS[@]} downloaded"
decompress_xz "$OCEAN_DIR"

# --- Download load_tide ------------------------------------------------------
echo ""
echo "=== Downloading load_tide (${#CONSTITUENTS[@]} constituents) ==="
LOAD_DIR="${DATA_DIR}/load_tide"
mkdir -p "$LOAD_DIR"

fail_count=0
for wave in "${CONSTITUENTS[@]}"; do
    download_file \
        "${BASE_URL}/load_tide/${wave}_fes2022.nc.xz" \
        "${LOAD_DIR}/${wave}_fes2022.nc.xz" || ((fail_count++))
done

echo "  Load tide: $((${#CONSTITUENTS[@]} - fail_count))/${#CONSTITUENTS[@]} downloaded"
decompress_xz "$LOAD_DIR"

# --- Download mask file ------------------------------------------------------
echo ""
echo "=== Downloading mask file ==="
mkdir -p "$DATA_DIR"

download_file \
    "${BASE_URL}/mask_fes2022B.nc" \
    "${DATA_DIR}/mask_fes2022B.nc"

# --- Summary -----------------------------------------------------------------
echo ""
echo "=== Done ==="
echo "Data saved to: ${DATA_DIR}"
echo ""
echo "Directory structure:"
find "$DATA_DIR" -type f -name "*.nc" | wc -l | xargs -I{} echo "  {} NetCDF files ready"
echo ""
echo "Next steps:"
echo "  - Use PyFES (>= v2025.2.0) for tidal prediction"
echo "  - Or use aviso-fes LIBFES v2.9.7 for cartesian grids"
