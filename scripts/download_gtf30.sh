#!/usr/bin/env bash
# Download Zhang et al. (2023) GTF30 global 30-m tidal flat map for Korea.
# Zenodo DOI 10.5281/zenodo.7936721
#
# The dataset consists of 588 5°×5° geographical tiles (binary raster,
# 1 = tidal flat, 0 = non-tidal-flat). Multiple naming conventions are
# tried because Zenodo file names may vary across dataset versions.
#
# Usage:
#   bash scripts/download_gtf30.sh

set -euo pipefail

DATA_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/raw/reference/gtf30"
mkdir -p "$DATA_DIR"

ZENODO_BASE="https://zenodo.org/records/7936721/files"

# Korean tiles — upper-left corner coordinates of 5°×5° grid cells.
# Try multiple naming conventions per tile.
download_tile() {
    local lon="$1" lat="$2"

    # Real filename pattern verified from the Zenodo record (Aug 2023):
    #   GTF30_2020maps_E125N40.tif   (lowercase 'maps')
    # Older drafts and earlier upload candidates are kept as fallbacks.
    local candidates=(
        "GTF30_2020maps_E${lon}N${lat}.tif"
        "GTF30_2020Maps_E${lon}N${lat}.tif"
        "GTF30_2020_E${lon}N${lat}.tif"
        "GTF30_E${lon}N${lat}.tif"
        "GTF30_E${lon}N${lat}_2020.tif"
        "E${lon}N${lat}.tif"
    )

    local dest
    for c in "${candidates[@]}"; do
        dest="${DATA_DIR}/${c}"
        if [[ -f "$dest" ]]; then
            echo "  [skip] ${c} already exists"
            return 0
        fi
    done

    for c in "${candidates[@]}"; do
        dest="${DATA_DIR}/${c}"
        echo "  [try] ${c}"
        if curl -fsSL --retry 2 -o "$dest" "${ZENODO_BASE}/${c}" 2>/dev/null; then
            echo "  [OK]  ${c}"
            return 0
        fi
        rm -f "$dest"
    done
    return 1
}

echo "=== GTF30 download ==="
echo "Destination: $DATA_DIR"
echo ""

tiles_ok=0
tiles_fail=0

# Korean peninsula tiles (approx 33-39N, 124-130E).
for pair in "120 40" "125 40" "120 35" "125 35"; do
    lon="${pair%% *}"
    lat="${pair##* }"
    if download_tile "$lon" "$lat"; then
        ((tiles_ok++))
    else
        ((tiles_fail++))
        echo "  [FAIL] E${lon}N${lat} — none of the candidate names worked"
    fi
done

echo ""
echo "Downloaded ${tiles_ok}/4 tiles."

# If individual tiles failed, try a global ZIP fallback.
if [[ $tiles_fail -gt 0 ]]; then
    echo ""
    echo "Trying global ZIP fallback..."
    zip_candidates=(
        "GTF30_2020.zip"
        "GTF30.zip"
        "GTF30_global_2020.zip"
    )
    zip_ok=false
    for zf in "${zip_candidates[@]}"; do
        echo "  [try] ${zf}"
        if curl -fsSL --retry 2 -o "${DATA_DIR}/${zf}" "${ZENODO_BASE}/${zf}" 2>/dev/null; then
            echo "  [OK] Downloaded ${zf} — extracting Korean tiles..."
            unzip -o -j "${DATA_DIR}/${zf}" '*E12[05]N[34][05]*' -d "$DATA_DIR" 2>/dev/null || \
                unzip -o "${DATA_DIR}/${zf}" -d "$DATA_DIR"
            zip_ok=true
            break
        fi
        rm -f "${DATA_DIR}/${zf}"
    done

    if ! $zip_ok; then
        echo ""
        echo "MANUAL STEP REQUIRED:"
        echo "  1. Visit https://zenodo.org/records/7936721"
        echo "  2. Download the file(s) covering E120-E130, N33-N40"
        echo "  3. Place the .tif files in: $DATA_DIR"
        echo ""
        echo "Then re-run the pipeline with SKIP_PHASE0=1 to continue."
        exit 1
    fi
fi

# Clip/merge to Korean bbox if gdalwarp is available.
#
# IMPORTANT: pick up only the raw 5°×5° Zenodo tiles (filenames matching
# the canonical `GTF30_..._E???N??.tif` pattern). A naive `*.tif` glob
# would also include the previous-run output `gtf30_2020_korea.tif`,
# which gdalbuildvrt then references inside the VRT — gdalwarp would
# then try to overwrite a file it is simultaneously reading and fail
# with "ERROR 4: ... not recognized as being in a supported file format".
shopt -s nullglob
tifs=("$DATA_DIR"/GTF30*E*N*.tif "$DATA_DIR"/E*N*.tif)
shopt -u nullglob
if [[ ${#tifs[@]} -gt 0 ]] && command -v gdalwarp >/dev/null 2>&1; then
    OUT="${DATA_DIR}/gtf30_2020_korea.tif"
    echo ""
    echo "Merging & clipping to Korean peninsula bbox..."
    # Remove the previous output (and its intermediate VRT) up-front so
    # gdalwarp doesn't trip over an existing/locked target on re-runs.
    rm -f "$OUT" "${DATA_DIR}/gtf30_merged.vrt"
    if [[ ${#tifs[@]} -eq 1 ]]; then
        gdalwarp -overwrite -te 124.0 33.0 130.5 39.5 -te_srs EPSG:4326 \
            -of GTiff -co COMPRESS=DEFLATE "${tifs[0]}" "$OUT"
    else
        VRT="${DATA_DIR}/gtf30_merged.vrt"
        gdalbuildvrt -overwrite "$VRT" "${tifs[@]}"
        gdalwarp -overwrite -te 124.0 33.0 130.5 39.5 -te_srs EPSG:4326 \
            -of GTiff -co COMPRESS=DEFLATE "$VRT" "$OUT"
    fi
    echo "Clipped: $OUT"
fi

echo ""
echo "Done."
