"""Download Murray Global Intertidal Change v1.1 (1984-2016) for Korea.

Source assets
-------------
1. ``UQ/murray/Intertidal/v1_1/global_intertidal`` (GEE ImageCollection).
   11 three-year composites 1984-2016, ``classification`` band: 1 = tidal flat.
2. ``JCU/Murray/GIC/global_tidal_wetland_change/2019`` (GEE Image).
   Single-epoch tidal-wetland change product (1999-2019).

Coverage
--------
Korean peninsula bounding box: ``[124.0, 33.0, 130.5, 39.5]``.

Output
------
- ``data/raw/reference/murray_v1_1_korea_<epoch>.tif``
- ``data/processed/reference_murray_v1_2_areas.parquet`` (kept for
  downstream compatibility — contains per-site km^2 for each epoch)

Usage
-----
    EE_PROJECT=<your-project> python scripts/download_murray_v12.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import ee
import pandas as pd

from src.config import load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.exports import export_image_to_drive, wait_for_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("download_murray")

V11_ASSET = "UQ/murray/Intertidal/v1_1/global_intertidal"
JCU_ASSET = "JCU/Murray/GIC/global_tidal_wetland_change/2019"

V11_EPOCHS = [
    "1984-1986", "1987-1989", "1990-1992", "1993-1995", "1996-1998",
    "1999-2001", "2002-2004", "2005-2007", "2008-2010", "2011-2013",
    "2014-2016",
]

KOREA_BBOX = [124.0, 33.0, 130.5, 39.5]

CLASS_TIDAL_FLAT = 1  # v1.1 classification band: 1 = tidal flat


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument(
        "--export-mode",
        choices=["local", "drive"],
        default="drive",
        help="local uses getDownloadURL (48 MB cap); drive submits async export.",
    )
    p.add_argument("--scale-m", type=int, default=30, help="Output scale in metres.")
    p.add_argument(
        "--epochs",
        nargs="*",
        default=None,
        help="Subset of epoch labels to export (default: all 11).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-export even if cached outputs exist.",
    )
    return p.parse_args()


def _site_area_km2(image: ee.Image, geometry: ee.Geometry, scale_m: int) -> float:
    """Compute total tidal-flat area (km^2) inside *geometry*."""
    flat = image.eq(CLASS_TIDAL_FLAT)
    pixel_area = ee.Image.pixelArea().multiply(flat)
    stats = pixel_area.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=geometry,
        scale=scale_m,
        maxPixels=int(1e10),
        bestEffort=True,
    )
    val = stats.get("area")
    return ee.Number(val).divide(1e6).getInfo() if val is not None else float("nan")


def _build_epoch_images(col: ee.ImageCollection):
    """Return list of (epoch_label, ee.Image) from the v1.1 collection."""
    info = col.getInfo()
    out = []
    for feat in info["features"]:
        sid = feat["id"].split("/")[-1]
        out.append((sid, ee.Image(feat["id"]).select("classification")))
    return sorted(out, key=lambda x: x[0])


def main() -> None:
    args = parse_args()

    out_dir = resolve_path("data/raw/reference")
    out_dir.mkdir(parents=True, exist_ok=True)
    proc_dir = resolve_path("data/processed")
    proc_dir.mkdir(parents=True, exist_ok=True)
    out_parquet = proc_dir / "reference_murray_v1_2_areas.parquet"

    # Short-circuit: if the per-site area table is already populated, skip
    # GEE entirely. The downstream code only needs the per-site area numbers;
    # the local rasters are nice-to-have. Use --force to redo.
    if out_parquet.exists() and not args.force:
        cached_rasters = sorted(out_dir.glob("murray_v1_[12]_korea*.tif"))
        log.info(
            "Murray cache hit: %s already exists (%d rasters on disk). "
            "Skipping GEE call. Use --force to redo.",
            out_parquet,
            len(cached_rasters),
        )
        return

    initialize(project=args.project)

    sites = load_sites()
    region = ee.Geometry.Rectangle(KOREA_BBOX, proj="EPSG:4326", geodesic=False)

    col = ee.ImageCollection(V11_ASSET).filterBounds(region)

    epoch_images = _build_epoch_images(col)
    log.info("Found %d epochs in v1.1 collection", len(epoch_images))

    requested = set(args.epochs) if args.epochs else None

    # --- 1. Export each epoch clipped to Korea ---
    for label, img in epoch_images:
        if requested and label not in requested:
            continue

        # Skip if local file already exists (idempotent rerun).
        local_path = out_dir / f"murray_v1_1_korea_{label}.tif"
        if local_path.exists() and local_path.stat().st_size > 0:
            log.info("[skip] %s already on disk (%s)", label, local_path.name)
            continue

        clipped = img.clip(region)

        if args.export_mode == "drive":
            desc = f"murray_v1_1_korea_{label}"
            log.info("Submitting Drive export: %s", desc)
            task = export_image_to_drive(
                clipped,
                region=region,
                scale_m=args.scale_m,
                description=desc,
                folder="tidalflat_reference",
            )
            state = wait_for_task(task)
            log.info("Drive export %s → %s", desc, state)
        else:
            from src.gee.exports import export_image_to_local

            log.info("Exporting %s → %s", label, local_path)
            export_image_to_local(
                clipped,
                region=region,
                scale_m=args.scale_m,
                out_path=local_path,
                overwrite=False,
            )

    # --- 2. Per-site tidal-flat area (km^2) for each epoch ---
    if out_parquet.exists() and not args.force:
        log.info("[skip] %s already exists — keeping cached area table.", out_parquet)
        return

    rows = []
    for site in sites:
        geom = ee.Geometry.Rectangle(site.bbox, proj="EPSG:4326", geodesic=False)
        for label, img in epoch_images:
            if requested and label not in requested:
                continue
            area_km2 = _site_area_km2(img, geom, args.scale_m)
            log.info("%-10s %s: %.2f km² tidal flat", site.id, label, area_km2)
            rows.append({
                "source": "murray_v1_1",
                "site_id": site.id,
                "epoch": label,
                "tidal_flat_km2": area_km2,
            })

    df = pd.DataFrame(rows)
    df.to_parquet(out_parquet, index=False)
    log.info("Wrote %s (%d rows)", out_parquet, len(df))


if __name__ == "__main__":
    main()
