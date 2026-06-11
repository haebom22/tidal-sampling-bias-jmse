"""Mosaic tile outputs + per-province zonal statistics (Phase 4c).

.. deprecated::
    The per-province zonal here clips DEM pixels to the admin
    ``korea_provinces.geojson`` polygons, whose boundary follows the
    high-water coastline. Tidal flat is intertidal and therefore lies
    *seaward* of that line, so ~83 % of the mapped flat is discarded and
    the national DEM area collapses (787 km² vs a true elevation-band
    extent of ~2,589 km²). Use ``scripts/run_national_area_corrected.py``
    for area accounting; this script is retained only for the VRT mosaics.


After ``run_national_extent.py`` has produced per-tile V4 DEM and MSIC-OA
extent rasters, this script:

  1. Builds a national VRT (virtual mosaic) per year for both DEM and
     extent (binary tidal-flat).
  2. Computes the elevation-based tidal-flat area (DEM in [z_LAT, z_HAT])
     per province from the VRTs, using a province shapefile.
  3. Writes ``data/outputs/tables/annual_area_national_by_region.csv``
     with columns ``province | year | area_km2_dem | area_km2_msic``.

Province polygons
-----------------
By default the script expects a GeoJSON/Shapefile at
``data/raw/admin/korea_provinces.geojson`` (광역지자체 17개). If not
present we fall back to GADM v3 country=KOR layer 1, which the user
must place there manually:

    https://gadm.org/download_country.html  → gadm36_KOR_1.shp

A user-curated tighter dissolve into 8 coastal provinces
(인천·경기·충남·전북·전남·부산·울산·경남) is also acceptable as long
as the ``NAME_1`` column is preserved.

Usage
-----
    python scripts/run_national_mosaic.py --start-year 2016 --end-year 2024
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.extent import (
    BAND_DEM,
    BAND_N_OBS,
    MIN_N_OBS,
)
from src.config import resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("national_mosaic")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument(
        "--admin",
        default="data/raw/admin/korea_provinces.geojson",
        help="Province polygons (GeoJSON or shapefile).",
    )
    p.add_argument(
        "--bounds-table",
        default="data/outputs/tables/tidal_flat_bounds.csv",
        help="Per-site LAT/HAT bounds (used to derive a national default).",
    )
    p.add_argument(
        "--min-n-obs", type=int, default=MIN_N_OBS,
        help="Minimum n_obs gate for valid DEM pixels.",
    )
    p.add_argument(
        "--default-z-lat", type=float, default=None,
        help="Override z_LAT (m). If absent, derived from --bounds-table.",
    )
    p.add_argument(
        "--default-z-hat", type=float, default=None,
        help="Override z_HAT (m). If absent, derived from --bounds-table.",
    )
    return p.parse_args()


def _build_vrt(year: int, tile_dir: Path, prefix: str, vrt_path: Path) -> bool:
    """Build a VRT from all tile GeoTIFFs for one year."""
    pattern = f"*_{prefix}_{year}.tif"
    tiles = sorted(tile_dir.glob(pattern))
    if not tiles:
        log.warning("No %s tiles for year %d (in %s)", prefix, year, tile_dir)
        return False
    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["gdalbuildvrt", "-overwrite", str(vrt_path)] + [str(t) for t in tiles]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        log.error(
            "gdalbuildvrt not on PATH: %s. Install GDAL (`brew install gdal`).",
            exc,
        )
        return False
    except subprocess.CalledProcessError as exc:
        log.error("gdalbuildvrt failed: %s\n%s", exc, exc.stderr)
        return False
    log.info("VRT %s ← %d tiles", vrt_path.name, len(tiles))
    return True


def _province_zonal(
    vrt_path: Path,
    admin_path: Path,
    *,
    z_lat: float,
    z_hat: float,
    n_obs_band: int = BAND_N_OBS,
    dem_band: int = BAND_DEM,
    min_n_obs: int = MIN_N_OBS,
    name_col: str = "NAME_1",
) -> dict[str, dict[str, float]]:
    """Zonal sum of valid DEM pixels per province → area in km^2."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds

    gdf = gpd.read_file(admin_path)
    if name_col not in gdf.columns:
        cand = next(
            (c for c in ("name", "name_1", "sido", "NAME_KO", "CTP_KOR_NM")
             if c in gdf.columns),
            None,
        )
        if cand is None:
            raise SystemExit(
                f"Province name column not found. Have: {list(gdf.columns)}"
            )
        name_col = cand
    gdf = gdf.to_crs(epsg=4326)

    result: dict[str, dict[str, float]] = {}
    with rasterio.open(vrt_path) as src:
        if src.crs and src.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(src.crs)
        for _, row in gdf.iterrows():
            province = str(row[name_col])
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            try:
                window = from_bounds(*geom.bounds, transform=src.transform)
                window = window.intersection(
                    rasterio.windows.Window(0, 0, src.width, src.height)
                )
            except rasterio.errors.WindowError:
                # Province fully outside raster footprint (inland prov.)
                continue
            except Exception:  # noqa: BLE001
                continue
            if window.width <= 0 or window.height <= 0:
                continue
            dem = src.read(dem_band, window=window, masked=True).filled(np.nan)
            n_obs = src.read(n_obs_band, window=window, masked=True).filled(0)
            win_transform = src.window_transform(window)
            poly_mask = ~geometry_mask(
                [geom], out_shape=dem.shape, transform=win_transform, invert=False
            )
            valid = (
                np.isfinite(dem) & (dem >= z_lat) & (dem <= z_hat)
                & (n_obs >= min_n_obs) & poly_mask
            )
            if not valid.any():
                area_km2 = 0.0
            else:
                # Pixel area for lonlat raster (approx cos lat).
                if src.crs and src.crs.to_epsg() == 4326:
                    rows_idx = np.arange(dem.shape[0])
                    lats = win_transform.f + rows_idx * win_transform.e
                    px_w = abs(win_transform.a) * 111_320.0
                    px_h = abs(win_transform.e) * 111_320.0
                    pa_row = px_w * np.cos(np.deg2rad(lats)) * px_h
                    area_km2 = float((valid * pa_row[:, None]).sum() / 1e6)
                else:
                    area_km2 = float(
                        valid.sum() * abs(win_transform.a) * abs(win_transform.e)
                        / 1e6
                    )
            result[province] = result.get(province, {})
            result[province]["area_km2_dem"] = (
                result[province].get("area_km2_dem", 0.0) + area_km2
            )
    return result


def _msic_zonal(
    vrt_path: Path,
    admin_path: Path,
    *,
    name_col: str = "NAME_1",
    target_value: int = 1,
) -> dict[str, float]:
    """Zonal area of MSIC tidal-flat pixels per province."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds

    gdf = gpd.read_file(admin_path)
    if name_col not in gdf.columns:
        cand = next(
            (c for c in ("name", "name_1", "sido", "NAME_KO", "CTP_KOR_NM")
             if c in gdf.columns),
            None,
        )
        if cand is None:
            raise SystemExit("Province name column not found")
        name_col = cand
    gdf = gdf.to_crs(epsg=4326)

    result: dict[str, float] = {}
    with rasterio.open(vrt_path) as src:
        if src.crs and src.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(src.crs)
        for _, row in gdf.iterrows():
            province = str(row[name_col])
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            try:
                window = from_bounds(*geom.bounds, transform=src.transform)
                window = window.intersection(
                    rasterio.windows.Window(0, 0, src.width, src.height)
                )
            except rasterio.errors.WindowError:
                # Province lies fully outside this raster's footprint
                # (e.g. inland provinces vs a coastal-tile subset).
                continue
            except Exception:  # noqa: BLE001
                continue
            if window.width <= 0 or window.height <= 0:
                continue
            data = src.read(1, window=window, masked=True).filled(0)
            win_transform = src.window_transform(window)
            poly_mask = ~geometry_mask(
                [geom], out_shape=data.shape, transform=win_transform, invert=False
            )
            valid = (data == target_value) & poly_mask
            if not valid.any():
                continue
            if src.crs and src.crs.to_epsg() == 4326:
                rows_idx = np.arange(data.shape[0])
                lats = win_transform.f + rows_idx * win_transform.e
                px_w = abs(win_transform.a) * 111_320.0
                px_h = abs(win_transform.e) * 111_320.0
                pa_row = px_w * np.cos(np.deg2rad(lats)) * px_h
                area_km2 = float((valid * pa_row[:, None]).sum() / 1e6)
            else:
                area_km2 = float(
                    valid.sum() * abs(win_transform.a) * abs(win_transform.e) / 1e6
                )
            result[province] = result.get(province, 0.0) + area_km2
    return result


def main() -> None:
    args = parse_args()

    dem_tile_dir = resolve_path("data/outputs/dem/national")
    extent_tile_dir = resolve_path("data/outputs/extent/national")
    vrt_dir = resolve_path("data/outputs/national/vrt")
    tables_dir = resolve_path("data/outputs/tables")
    vrt_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    admin_path = resolve_path(args.admin)
    if not admin_path.exists():
        raise SystemExit(
            f"Province polygons missing at {admin_path}.\n"
            "Download GADM v3 KOR layer 1: https://gadm.org/download_country.html"
        )

    # Derive default LAT/HAT from pilot-site stats if not provided.
    bounds_path = resolve_path(args.bounds_table)
    if args.default_z_lat is None or args.default_z_hat is None:
        if bounds_path.exists():
            b = pd.read_csv(bounds_path)
            z_lat = args.default_z_lat if args.default_z_lat is not None else float(b["z_lat_m"].min())
            z_hat = args.default_z_hat if args.default_z_hat is not None else float(b["z_hat_m"].max())
            log.info(
                "Default LAT/HAT from %s: z_LAT=%.2f, z_HAT=%.2f m",
                bounds_path.name, z_lat, z_hat,
            )
        else:
            z_lat, z_hat = -5.0, 5.0
            log.warning(
                "No bounds table — using conservative defaults z_LAT=-5, z_HAT=5 m"
            )
    else:
        z_lat = args.default_z_lat
        z_hat = args.default_z_hat

    rows = []
    for year in range(args.start_year, args.end_year + 1):
        dem_vrt = vrt_dir / f"national_dem_{year}.vrt"
        msic_vrt = vrt_dir / f"national_msic_{year}.vrt"
        has_dem = _build_vrt(year, dem_tile_dir, "v4", dem_vrt)
        has_msic = _build_vrt(year, extent_tile_dir, "msic", msic_vrt)

        dem_areas: dict[str, dict[str, float]] = {}
        if has_dem:
            try:
                dem_areas = _province_zonal(
                    dem_vrt, admin_path,
                    z_lat=z_lat, z_hat=z_hat, min_n_obs=args.min_n_obs,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("DEM zonal failed: %s", exc)

        msic_areas: dict[str, float] = {}
        if has_msic:
            try:
                msic_areas = _msic_zonal(msic_vrt, admin_path)
            except Exception as exc:  # noqa: BLE001
                log.exception("MSIC zonal failed: %s", exc)

        provinces = set(dem_areas) | set(msic_areas)
        for province in sorted(provinces):
            rows.append({
                "province": province,
                "year": year,
                "area_km2_dem": dem_areas.get(province, {}).get("area_km2_dem", 0.0),
                "area_km2_msic": msic_areas.get(province, 0.0),
            })

    df = pd.DataFrame(rows)
    out_csv = tables_dir / "annual_area_national_by_region.csv"
    df.to_csv(out_csv, index=False, float_format="%.4f")
    log.info("Wrote %s (%d rows)", out_csv, len(df))
    if not df.empty:
        pivot = df.pivot_table(
            index="province", columns="year",
            values="area_km2_dem", aggfunc="sum",
        )
        print(pivot.to_string(float_format="%.1f"))


if __name__ == "__main__":
    main()
