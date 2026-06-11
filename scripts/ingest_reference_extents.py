"""Aggregate downloaded reference tidal-flat datasets onto the 5 pilot sites.

After:
    1. ``download_murray_v12.py``      (Murray v1.2, 7 epochs, GeoTIFFs)
    2. ``download_gwl_fcs30.sh``       (Zhang 2023, per-year tiled GeoTIFFs)
    3. ``download_gtf30.sh``           (Zhang 2023, single 2020 GeoTIFF)
    4. ``prepare_mof_reference.py``    (MOF/KOSIS official statistics)

this script computes the tidal-flat area (km^2) inside each pilot site's
bounding box for every year / epoch / dataset and writes the combined
``data/processed/reference_extents.parquet``.

Output columns:
    source     {murray_v1_2, gwl_fcs30, gtf30, mof}
    site_id    one of the 5 pilots
    year       calendar year or epoch midpoint
    area_km2   tidal-flat area
    epoch_id   original epoch / band identifier (optional)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

# NB: rasterio is *lazy-imported* inside the raster helpers below. Importing
# rasterio at module load time registers a GDAL handler for the ``file://``
# URI scheme that conflicts with pyarrow's LocalFileSystem factory and
# subsequently breaks ``pd.DataFrame.to_parquet``.

from src.config import load_sites, resolve_path
from src.utils.safe_parquet import to_parquet as safe_to_parquet

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("ingest_refs")

# Class codes — match the official dataset specifications.
MURRAY_TIDAL_FLAT = 1       # v1.1 classification band: 1 = tidal flat
GWL_FCS30_TIDAL_FLAT = 187  # GWL_FCS30D 8-class system: 187 = tidal flat
GTF30_TIDAL_FLAT = 1        # binary: 1 = tidal flat

REF_DIR = resolve_path("data/raw/reference")
OUT_DIR = resolve_path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _area_in_bbox(raster_path: Path, bbox: list[float], target_value: int) -> float:
    """Return area (km^2) of pixels == target_value inside [lon_min, lat_min, lon_max, lat_max]."""
    import rasterio
    from rasterio.windows import from_bounds  # noqa: F401  (re-exported below if needed)

    with rasterio.open(raster_path) as src:
        # Reproject bbox to raster CRS if needed.
        if src.crs.to_epsg() != 4326:
            from rasterio.warp import transform_bounds
            bounds = transform_bounds("EPSG:4326", src.crs, *bbox)
        else:
            bounds = bbox
        try:
            window = from_bounds(*bounds, transform=src.transform)
        except rasterio.errors.WindowError as exc:
            log.warning("Window error for %s: %s", raster_path, exc)
            return float("nan")
        try:
            window = window.intersection(
                rasterio.windows.Window(0, 0, src.width, src.height)
            )
        except rasterio.errors.WindowError:
            return float("nan")
        if window.width <= 0 or window.height <= 0:
            return 0.0
        data = src.read(1, window=window)
        # Pixel area in m^2 (approximate; assumes ~constant lat).
        px_w_deg = abs(src.transform.a)
        px_h_deg = abs(src.transform.e)
        # Latitude midpoint for the window.
        win_transform = src.window_transform(window)
        lat_mid = win_transform.f + (window.height / 2) * win_transform.e
        if src.crs.to_epsg() == 4326:
            # 1 deg lat ~ 111.32 km, 1 deg lon = 111.32 * cos(lat).
            pixel_area_m2 = (
                px_w_deg * 111_320.0 * np.cos(np.deg2rad(lat_mid))
                * px_h_deg * 111_320.0
            )
        else:
            pixel_area_m2 = px_w_deg * px_h_deg
        count = int((data == target_value).sum())
        return count * pixel_area_m2 / 1e6


def _ingest_murray() -> list[dict]:
    rows: list[dict] = []
    murray_dir = REF_DIR

    # Fast path: the download script already produces per-site area parquet
    # via GEE reduceRegion. Prefer this over re-computing from rasters.
    parquet_path = OUT_DIR / "reference_murray_v1_2_areas.parquet"
    if parquet_path.exists():
        import pandas as pd
        df = pd.read_parquet(parquet_path)
        for _, r in df.iterrows():
            epoch_id = str(r["epoch"])
            rows.append({
                "source": str(r.get("source", "murray_v1_1")),
                "site_id": str(r["site_id"]),
                "year": _epoch_midyear(epoch_id),
                "epoch_id": epoch_id,
                "area_km2": float(r["tidal_flat_km2"]),
            })
        log.info("Murray: %d rows ingested from cached parquet", len(rows))
        return rows

    candidates = sorted(murray_dir.glob("murray_v1_[12]_korea*.tif"))
    if not candidates:
        log.warning("No Murray v1.1/v1.2 rasters found in %s", murray_dir)
        return rows
    import rasterio  # lazy

    sites = load_sites()
    for tif in candidates:
        # Filename may be either single-band per-epoch or a multi-band image.
        with rasterio.open(tif) as src:
            n_bands = src.count
            band_descriptions = src.descriptions
        for band_idx in range(1, n_bands + 1):
            epoch_id = (
                band_descriptions[band_idx - 1]
                if band_descriptions and band_descriptions[band_idx - 1]
                else f"band{band_idx}"
            )
            for site in sites:
                area = _area_in_bbox_band(tif, site.bbox, MURRAY_TIDAL_FLAT, band_idx)
                year = _epoch_midyear(epoch_id)
                rows.append({
                    "source": "murray_v1_2",
                    "site_id": site.id,
                    "year": year,
                    "epoch_id": epoch_id,
                    "area_km2": area,
                })
                log.info("  murray  %-10s %-12s -> %.2f km^2", site.id, epoch_id, area)
    return rows


def _area_in_bbox_band(
    raster_path: Path, bbox: list[float], target_value: int, band: int
) -> float:
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(raster_path) as src:
        if src.crs.to_epsg() != 4326:
            from rasterio.warp import transform_bounds
            bounds = transform_bounds("EPSG:4326", src.crs, *bbox)
        else:
            bounds = bbox
        try:
            window = from_bounds(*bounds, transform=src.transform)
        except rasterio.errors.WindowError:
            return float("nan")
        try:
            window = window.intersection(
                rasterio.windows.Window(0, 0, src.width, src.height)
            )
        except rasterio.errors.WindowError:
            # Site bbox lies entirely outside this raster tile.
            return float("nan")
        if window.width <= 0 or window.height <= 0:
            return 0.0
        data = src.read(band, window=window)
        win_transform = src.window_transform(window)
        lat_mid = win_transform.f + (window.height / 2) * win_transform.e
        px_area_m2 = (
            abs(win_transform.a) * 111_320.0 * np.cos(np.deg2rad(lat_mid))
            * abs(win_transform.e) * 111_320.0
        )
        return int((data == target_value).sum()) * px_area_m2 / 1e6


def _epoch_midyear(epoch_id: str) -> int:
    """Parse 'YYYY-YYYY' into midpoint year; fallback to 0 if unknown."""
    import re
    m = re.match(r"(\d{4})[-_](\d{4})", epoch_id)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    m = re.search(r"\d{4}", epoch_id)
    return int(m.group(0)) if m else 0


def _ingest_gwl_fcs30() -> list[dict]:
    rows: list[dict] = []
    gwl_dir = REF_DIR / "gwl_fcs30"
    if not gwl_dir.exists():
        log.warning("No GWL_FCS30 directory at %s", gwl_dir)
        return rows
    tifs = sorted(gwl_dir.glob("GWL_FCS30*.tif"))
    if not tifs:
        log.warning("No GWL_FCS30 tiles in %s", gwl_dir)
        return rows
    import rasterio  # lazy

    sites = load_sites()
    # Each tile holds 23 bands (2000..2022).
    for tif in tifs:
        with rasterio.open(tif) as src:
            n_bands = src.count
        for band_idx in range(1, n_bands + 1):
            year = 2000 + (band_idx - 1) if n_bands >= 23 else _epoch_midyear(tif.stem)
            for site in sites:
                area = _area_in_bbox_band(tif, site.bbox, GWL_FCS30_TIDAL_FLAT, band_idx)
                if np.isfinite(area):
                    rows.append({
                        "source": "gwl_fcs30",
                        "site_id": site.id,
                        "year": int(year),
                        "epoch_id": f"{year}",
                        "area_km2": area,
                    })
    log.info("GWL_FCS30: %d (site, year) rows", len(rows))
    return rows


def _ingest_gtf30() -> list[dict]:
    rows: list[dict] = []
    gtf_dir = REF_DIR / "gtf30"
    if not gtf_dir.exists():
        log.warning("No GTF30 directory at %s", gtf_dir)
        return rows
    candidates = [
        gtf_dir / "gtf30_2020_korea.tif",
        gtf_dir / "GTF30_2020_global.tif",
        gtf_dir / "GTF30_2020.tif",
    ]
    src_path = next((p for p in candidates if p.exists()), None)
    if src_path is None:
        log.warning("No GTF30 raster found in %s", gtf_dir)
        return rows
    sites = load_sites()
    for site in sites:
        area = _area_in_bbox(src_path, site.bbox, GTF30_TIDAL_FLAT)
        rows.append({
            "source": "gtf30",
            "site_id": site.id,
            "year": 2020,
            "epoch_id": "2020",
            "area_km2": area,
        })
        log.info("  gtf30   %-10s 2020         -> %.2f km^2", site.id, area)
    return rows


def _ingest_mof() -> list[dict]:
    """Intersect MOF shapefile polygons with each pilot-site bbox.

    Rather than naively mapping provinces to sites (which gives province-
    wide totals), we clip the individual MOF polygons to each site's
    bounding box and sum the clipped area. This gives the MOF-official
    tidal-flat area *within* each pilot site — directly comparable to our
    DEM/MSIC estimates.

    Falls back to the province-mapping approach if geopandas is
    unavailable or the shapefile dir does not exist.
    """
    import os

    shp_dir = resolve_path("data/raw/reference/2023_갯벌_접경지역포함")
    shps = sorted(shp_dir.glob("*.shp")) if shp_dir.is_dir() else []

    if shps:
        return _ingest_mof_shapefile(shps[0])

    # Fallback: province-level parquet (coarse, kept for back-compat).
    parquet = REF_DIR / "mof_tidal_flat_survey.parquet"
    if not parquet.exists():
        log.warning("No MOF shapefile or parquet found (skip)")
        return []
    return _ingest_mof_parquet(parquet)


def _ingest_mof_shapefile(shp_path: Path) -> list[dict]:
    """Clip MOF polygons to site bboxes and sum clipped area."""
    import os
    import geopandas as gpd
    from shapely.geometry import box

    os.environ.setdefault("SHAPE_ENCODING", "UTF-8")
    gdf = gpd.read_file(shp_path).to_crs(epsg=5186)
    log.info("MOF shapefile: %d features from %s", len(gdf), shp_path.name)

    dir_name = shp_path.parent.name
    year_str = "".join(c for c in dir_name if c.isdigit())
    survey_year = int(year_str) if year_str else 2023

    sites = load_sites()
    rows = []
    for site in sites:
        sid = site.id
        bbox_4326 = box(site.bbox[0], site.bbox[1], site.bbox[2], site.bbox[3])
        bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_4326], crs="EPSG:4326").to_crs(epsg=5186)
        bbox_geom = bbox_gdf.geometry[0]

        clipped = gdf.intersection(bbox_geom)
        area_km2 = float(clipped.area.sum() / 1e6)
        if area_km2 < 1e-6:
            log.info("  MOF × %s: 0.000 km² (no overlap)", sid)
            continue
        log.info("  MOF × %s: %.3f km²", sid, area_km2)
        rows.append({
            "source": "mof",
            "site_id": sid,
            "year": survey_year,
            "epoch_id": str(survey_year),
            "area_km2": area_km2,
        })
    log.info("MOF shapefile: %d (site, year) rows", len(rows))
    return rows


def _ingest_mof_parquet(parquet: Path) -> list[dict]:
    """Province-level fallback (coarse mapping)."""
    df = pd.read_parquet(parquet)
    province_to_site = {
        "인천광역시": "ganghwa",
        "경기도": "ganghwa",
        "충청남도": "garorim",
        "전라북도": "gomso",
        "전북특별자치도": "gomso",
        "전라남도": "hampyeong",
    }
    rows = []
    for _, r in df.iterrows():
        sid = province_to_site.get(r.get("province"))
        if sid is None:
            continue
        rows.append({
            "source": "mof",
            "site_id": sid,
            "year": int(r["year"]),
            "epoch_id": str(int(r["year"])),
            "area_km2": float(r["area_km2"]),
        })
    log.info("MOF parquet (province fallback): %d rows", len(rows))
    return rows


def main() -> None:
    import os
    import argparse

    parser = argparse.ArgumentParser(description="Aggregate reference tidal-flat datasets.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if reference_extents.parquet already exists.",
    )
    args = parser.parse_args()

    out = OUT_DIR / "reference_extents.parquet"
    if out.exists() and not args.force and not os.getenv("FORCE_INGEST"):
        log.info(
            "[skip] %s already exists (%d bytes). Use --force or FORCE_INGEST=1 to redo.",
            out, out.stat().st_size,
        )
        return

    all_rows: list[dict] = []
    all_rows.extend(_ingest_murray())
    all_rows.extend(_ingest_gwl_fcs30())
    all_rows.extend(_ingest_gtf30())
    all_rows.extend(_ingest_mof())
    if not all_rows:
        log.error("No reference data ingested. Run the four download steps first.")
        return
    df = pd.DataFrame(all_rows)

    # Collapse duplicates that arise when a single site crosses multiple raster
    # tiles (e.g. GWL_FCS30 5°×5° tile boundaries split hampyeong / suncheon).
    # Downstream cross-validation expects one (source, site, year/epoch) row
    # per dataset, so we *sum* areas of partial tiles before writing.
    before = len(df)
    df = (
        df.groupby(
            ["source", "site_id", "year", "epoch_id"], as_index=False
        )["area_km2"]
        .sum()
    )
    after = len(df)
    if after < before:
        log.info("Collapsed %d duplicate tile rows → %d unique (source, site, epoch) rows.", before - after, after)

    safe_to_parquet(df, out, index=False)
    log.info("Wrote %s (%d rows)", out, len(df))
    print(
        df.groupby(["source", "site_id"])["area_km2"]
        .agg(["mean", "min", "max", "count"])
        .to_string()
    )


if __name__ == "__main__":
    main()
