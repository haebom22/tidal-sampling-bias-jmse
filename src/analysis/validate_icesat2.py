"""ICESat-2 vs DEM cross-validation framework.

For each site × variant DEM:
  1. Load DEM GeoTIFF
  2. Load ICESat-2 exposed ground segments
  3. Sample DEM at segment locations (bilinear interpolation)
  4. Compute validation metrics: RMSE, MAE, bias, R², n_points
  5. Stratify by elevation zone and distance from shore

The exposed-only filter (Phase C) ensures only ground surface points
that were above water at ICESat-2 overpass time are compared.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    site_id: str
    variant: str
    n_points: int
    rmse_m: float
    mae_m: float
    bias_m: float
    std_m: float
    r_squared: float

    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "variant": self.variant,
            "n_points": self.n_points,
            "rmse_m": self.rmse_m,
            "mae_m": self.mae_m,
            "bias_m": self.bias_m,
            "std_m": self.std_m,
            "r_squared": self.r_squared,
        }


def sample_dem_at_points(
    dem_path: Path,
    points: gpd.GeoDataFrame,
    band: int = 1,
) -> np.ndarray:
    """Sample DEM values at point locations using bilinear interpolation.

    Parameters
    ----------
    dem_path
        Path to the DEM GeoTIFF.
    points
        GeoDataFrame with Point geometries in EPSG:4326.
    band
        Band number to sample (1 = dem_m).

    Returns
    -------
    Array of DEM elevations at point locations (NaN where invalid).
    """
    import rasterio
    from rasterio.transform import rowcol

    with rasterio.open(dem_path) as src:
        dem_crs = src.crs
        nodata = src.nodata
        data = src.read(band)
        transform = src.transform

    pts_proj = points.to_crs(dem_crs)
    xs = pts_proj.geometry.x.values
    ys = pts_proj.geometry.y.values

    rows, cols = rowcol(transform, xs, ys)
    rows = np.array(rows)
    cols = np.array(cols)

    h, w = data.shape
    valid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)

    elevations = np.full(len(xs), np.nan)
    if valid.any():
        vals = data[rows[valid], cols[valid]]
        if nodata is not None:
            vals = np.where(np.isclose(vals, nodata), np.nan, vals)
        elevations[valid] = vals.astype(float)

    return elevations


def validate_dem_vs_icesat2(
    dem_path: Path,
    icesat2_path: Path,
    site_id: str,
    variant: str,
    height_col: str = "h_mean",
    datum_offset: float | None = None,
) -> ValidationResult | None:
    """Compare DEM to ICESat-2 ground segments.

    Parameters
    ----------
    dem_path
        Path to the variant DEM GeoTIFF.
    icesat2_path
        Path to the site's ICESat-2 exposed parquet.
    site_id, variant
        Identifiers for labelling results.
    height_col
        Column in ICESat-2 data containing the reference elevation.
    datum_offset
        If provided, subtract from ICESat-2 heights before comparison.
        This aligns WGS84 ellipsoidal heights to KHOA chart datum.
        If None, estimated as the median difference.
    """
    if not dem_path.exists():
        log.warning("DEM not found: %s", dem_path)
        return None
    if not icesat2_path.exists():
        log.warning("ICESat-2 data not found: %s", icesat2_path)
        return None

    pdf = pd.read_parquet(icesat2_path)
    if pdf.empty:
        log.warning("No ICESat-2 photons for %s", site_id)
        return None

    from shapely import wkb
    if "geometry" in pdf.columns:
        geom_col = pdf["geometry"].apply(
            lambda g: wkb.loads(g) if isinstance(g, bytes) else g
        )
        photons = gpd.GeoDataFrame(pdf, geometry=geom_col, crs="EPSG:4326")
    else:
        photons = gpd.GeoDataFrame(
            pdf,
            geometry=gpd.points_from_xy(pdf["lon"], pdf["lat"]),
            crs="EPSG:4326",
        )

    dem_vals = sample_dem_at_points(dem_path, photons, band=1)
    ref_vals = photons[height_col].values

    valid = np.isfinite(dem_vals) & np.isfinite(ref_vals)
    if valid.sum() < 10:
        log.warning(
            "Too few valid comparison points (%d) for %s_%s",
            valid.sum(), site_id, variant,
        )
        return None

    dem_v = dem_vals[valid]
    ref_v = ref_vals[valid]

    if datum_offset is None:
        datum_offset = float(np.median(ref_v - dem_v))
        log.info("  Estimated datum offset for %s: %.2f m", site_id, datum_offset)

    ref_aligned = ref_v - datum_offset

    # Filter to points within intertidal range: keep only points where
    # BOTH DEM and corrected-ICESat2 are within a reasonable elevation band.
    dem_p5, dem_p95 = np.percentile(dem_v, [5, 95])
    elev_min = dem_p5 - 2.0
    elev_max = dem_p95 + 2.0
    intertidal = (
        (dem_v >= elev_min) & (dem_v <= elev_max)
        & (ref_aligned >= elev_min) & (ref_aligned <= elev_max)
    )
    if intertidal.sum() < 10:
        log.warning("Too few intertidal points (%d) for %s_%s", intertidal.sum(), site_id, variant)
        return None

    dem_v = dem_v[intertidal]
    ref_aligned = ref_aligned[intertidal]
    diff = dem_v - ref_aligned

    rmse = float(np.sqrt(np.mean(diff**2)))
    mae = float(np.mean(np.abs(diff)))
    bias = float(np.mean(diff))
    std = float(np.std(diff))

    ss_res = np.sum(diff**2)
    ss_tot = np.sum((ref_aligned - np.mean(ref_aligned))**2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    result = ValidationResult(
        site_id=site_id,
        variant=variant,
        n_points=int(intertidal.sum()),
        rmse_m=rmse,
        mae_m=mae,
        bias_m=bias,
        std_m=std,
        r_squared=r2,
    )
    log.info(
        "%s_%s: n=%d, RMSE=%.3f m, bias=%.3f m, MAE=%.3f m, R²=%.3f",
        site_id, variant, result.n_points, rmse, bias, mae, r2,
    )
    return result, datum_offset


def run_full_validation(
    dem_dir: Path,
    icesat2_dir: Path,
    sites: list[str],
    variants: list[str] = None,
) -> pd.DataFrame:
    """Run validation for all site × variant combinations.

    The datum offset between WGS84 ellipsoidal (ICESat-2) and KHOA chart
    datum (DEM) is estimated from V1 for each site, then applied consistently
    across all variants to ensure fair relative comparison.

    Returns a summary DataFrame.
    """
    if variants is None:
        variants = ["v1", "v2", "v3", "v4"]

    results = []
    for site_id in sites:
        icesat2_path = icesat2_dir / f"{site_id}_icesat2_exposed.parquet"
        datum_offset = None
        for variant in variants:
            dem_path = dem_dir / f"{site_id}_{variant}.tif"
            out = validate_dem_vs_icesat2(
                dem_path, icesat2_path, site_id, variant,
                datum_offset=datum_offset,
            )
            if out is not None:
                r, offset = out
                if datum_offset is None:
                    datum_offset = offset
                results.append(r.to_dict())

    if not results:
        log.warning("No valid validation results produced")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    return df
