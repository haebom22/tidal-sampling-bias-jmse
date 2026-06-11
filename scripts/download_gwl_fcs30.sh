#!/usr/bin/env bash
# Download Zhang et al. (2024) GWL_FCS30 annual wetlands dataset for Korea.
# Zenodo DOI 10.5281/zenodo.10068479 (Xiao Zhang & Liangyun Liu).
#
# Structure on Zenodo:
#   - 23 ZIP files: GWL_FCS30_2000.zip … GWL_FCS30_2022.zip (each ~2.5 GB)
#   - Each ZIP contains 961 5°×5° tiles as multi-band (23 bands) GeoTIFFs.
#   - Tile naming: GWL_FCS30D_20002022_E<lon>N<lat>.tif
#     (upper-left corner coordinates)
#
# Wetland class values per band:
#   180 = permanent water   181 = swamp       182 = marsh
#   183 = flooded flats     184 = saline      185 = mangrove
#   186 = salt marsh         187 = tidal flat   0 = non-wetland  255 = ocean
#
# This script downloads ONE year's ZIP and extracts only the 4 Korean tiles.
#
# Usage:
#   bash scripts/download_gwl_fcs30.sh            # default: 2020
#   GWL_YEAR=2022 bash scripts/download_gwl_fcs30.sh

set -euo pipefail

YEAR="${GWL_YEAR:-2020}"
DATA_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/raw/reference/gwl_fcs30"
mkdir -p "$DATA_DIR"

ZENODO_BASE="https://zenodo.org/records/10068479/files"
ZIP_NAME="GWL_FCS30_${YEAR}.zip"
ZIP_PATH="${DATA_DIR}/${ZIP_NAME}"

# Korean tiles — 5°×5° grid upper-left corners.
# ZIP-internal layout (verified from GWL_FCS30_2020.zip):
#   2020/GWL_FCS30D_2020Maps_E<lon>N<lat>.tif
# The trailing local file (just the basename) is what we extract to.
KOREA_TILE_COORDS=(
    "E120N40"
    "E125N40"
    "E120N35"
    "E125N35"
)
KOREA_TILES=()
for c in "${KOREA_TILE_COORDS[@]}"; do
    KOREA_TILES+=("GWL_FCS30D_${YEAR}Maps_${c}")
done

echo "=== GWL_FCS30 download (year=${YEAR}) ==="
echo "Destination: $DATA_DIR"
echo ""

# Check if tiles already extracted.
all_present=true
for tile in "${KOREA_TILES[@]}"; do
    if [[ ! -f "${DATA_DIR}/${tile}.tif" ]]; then
        all_present=false
        break
    fi
done

if $all_present; then
    echo "  All Korean tiles already present — skipping download."
else
    # Download the year's ZIP (~2.5 GB).
    if [[ -f "$ZIP_PATH" ]]; then
        echo "  [skip download] ${ZIP_NAME} already exists."
    else
        echo "  Downloading ${ZIP_NAME} (~2.5 GB) ..."
        echo "  (This may take several minutes depending on your connection.)"
        curl -fSL --retry 3 --retry-delay 10 \
            --progress-bar \
            -o "$ZIP_PATH" \
            "${ZENODO_BASE}/${ZIP_NAME}" || {
            echo ""
            echo "  FAIL: Could not download ${ZIP_NAME}."
            echo "  Please download manually from:"
            echo "    ${ZENODO_BASE}/${ZIP_NAME}"
            echo "  and place it in: ${DATA_DIR}/"
            rm -f "$ZIP_PATH"
            exit 1
        }
    fi

    # Extract only the 4 Korean tiles from the ZIP.
    echo ""
    echo "  Extracting Korean tiles from ${ZIP_NAME} ..."
    extracted=0
    for tile in "${KOREA_TILES[@]}"; do
        # Try several layouts:
        #   <tile>.tif           (flat)
        #   <year>/<tile>.tif    (year subfolder, e.g. 2020/)
        #   */<tile>.tif         (any subfolder)
        found=false
        for pattern in "${tile}.tif" "${YEAR}/${tile}.tif" "*/${tile}.tif"; do
            if unzip -o -j "$ZIP_PATH" "$pattern" -d "$DATA_DIR" >/dev/null 2>&1; then
                if [[ -f "${DATA_DIR}/${tile}.tif" ]]; then
                    echo "  [OK] ${tile}.tif (pattern=${pattern})"
                    ((extracted++))
                    found=true
                    break
                fi
            fi
        done
        if ! $found; then
            echo "  [MISS] ${tile}.tif not found in ZIP — similar entries:"
            unzip -l "$ZIP_PATH" 2>/dev/null | grep -iE "E1[23][05]N[34][05]" | head -5 || true
        fi
    done
    echo ""
    echo "Extracted ${extracted}/${#KOREA_TILES[@]} tiles."

    if [[ $extracted -eq 0 ]]; then
        echo ""
        echo "WARNING: No Korean tiles found. ZIP entries (first 30):"
        unzip -l "$ZIP_PATH" 2>/dev/null | head -30
        echo "Adjust KOREA_TILES naming in this script to match."
        exit 1
    fi

    # Optionally remove the large ZIP to save space — only ask interactively.
    if [[ -t 0 ]]; then
        read -r -p "Remove ${ZIP_NAME} to save disk space? [y/N] " ans
        if [[ "${ans,,}" == "y" ]]; then
            rm -f "$ZIP_PATH"
            echo "  Removed ${ZIP_NAME}."
        fi
    else
        echo "  (Non-interactive run — keeping ${ZIP_NAME}.)"
    fi
fi

# Build a VRT for easy mosaic access.
tifs=("${DATA_DIR}"/GWL_FCS30D_*.tif)
if [[ ${#tifs[@]} -gt 0 ]] && command -v gdalbuildvrt >/dev/null 2>&1; then
    echo ""
    echo "Building mosaic VRT..."
    gdalbuildvrt -overwrite "${DATA_DIR}/gwl_fcs30_korea.vrt" "${tifs[@]}"
    echo "VRT: ${DATA_DIR}/gwl_fcs30_korea.vrt"
fi

echo ""
echo "Done."
