"""DEM-elevation-based tidal-flat area + 3-tier extent fusion.

Phase 1d of the methodology plan. Provides three core operations:

1. ``compute_tidal_flat_bounds`` — derive site-specific LAT/HAT elevation
   bounds from FES2014/FES2022b model tide quantiles at the site centre.
2. ``compute_dem_area`` — count valid DEM pixels inside
   ``[z_LAT, z_HAT]`` AND ``n_obs >= 5`` to give the elevation-based
   tidal-flat area $A_{\\mathrm{DEM}}$.
3. ``fuse_extent`` — combine the V4 DEM, the MSIC-OA binary, and the
   eo-tides QA-pass raster into a 4-class fused extent product:

       1  Tier-1 high-confidence  (DEM valid ∧ MSIC=1 ∧ QA-pass)
       2  Tier-2 DEM-only         (DEM valid ∧ MSIC=0)
       3  Tier-3 MSIC-only        (DEM invalid ∧ MSIC=1)
       0  Reject / not tidal flat
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Band indices in the existing waterline DEM GeoTIFF (matches dem.py).
BAND_DEM = 1
BAND_N_OBS = 4
BAND_IF = 5

# Default valid-data gates.
MIN_N_OBS = 5
DEFAULT_LAT_QUANTILE = 0.001
DEFAULT_HAT_QUANTILE = 0.999

# Intrinsic inundation-frequency gate (replaces the external JRC GSW
# occurrence mask). A true intertidal pixel is observed both wet and dry,
# so its inundation frequency (n_water / n_obs, from the *same* multi-
# sensor L8/L9/S2/S1 stack) lies strictly between 0 and 1. Permanent
# subtidal water saturates toward 1; supratidal land toward 0. Because the
# frequency includes the turbidity-robust SAR (S1) observations, it keeps
# high-turbidity flats (Incheon/Gyeonggi) that the optical-only JRC mask
# discards (JRC occurrence>95% there). Validated on the Ganghwa tile:
# capture 58%->82% of MOF, commission stays bounded.
IF_LO = 0.05
IF_HI = 0.95

# Pixel codes in fused extent raster.
TIER_HIGH = 1
TIER_DEM_ONLY = 2
TIER_MSIC_ONLY = 3
REJECT = 0


# ---------------------------------------------------------------------------
# LAT / HAT computation
# ---------------------------------------------------------------------------

@dataclass
class TidalFlatBounds:
    site_id: str
    z_lat_m: float  # in chart-datum / DEM vertical reference
    z_hat_m: float
    datum_offset_m: float
    model_name: str
    n_reference: int
    reference_period: tuple[str, str]


def compute_tidal_flat_bounds(
    lon: float,
    lat: float,
    site_id: str,
    reference_start: pd.Timestamp,
    reference_end: pd.Timestamp,
    model_directory: Path,
    *,
    model_name: str = "FES2014",
    sampling_minutes: int = 30,
    datum_offset_m: float = 0.0,
    lat_q: float = DEFAULT_LAT_QUANTILE,
    hat_q: float = DEFAULT_HAT_QUANTILE,
    bounds: Sequence[float] | None = None,
) -> TidalFlatBounds:
    """Estimate LAT/HAT elevation bounds at a site centre coordinate.

    ``datum_offset_m`` is added to the FES (mean sea level) tides so the
    resulting bounds are in the *same* vertical reference as the V4 DEM
    (typically KHOA chart datum). When IFM is run with ICESat-2, the
    per-site datum offset is stored in ``data/processed/{site}_ifm_*.json``;
    pass that value here.
    """
    from ..tides.fes2014 import synthetic_reference_series

    # Default to a ~1° pad around the site point if no bbox was supplied,
    # so pyfes only loads the regional NetCDF slice (≈ 5 s) instead of
    # the global grid (≈ 30 s per cold call).
    if bounds is None:
        bounds = [lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5]
    series = synthetic_reference_series(
        lon=lon, lat=lat,
        start=reference_start, end=reference_end,
        sampling_minutes=sampling_minutes,
        model_directory=model_directory,
        bounds=bounds,
    )
    if series.empty:
        raise RuntimeError(
            f"FES2014 series empty at ({lon}, {lat}); check model directory."
        )
    tides = series["tide_m"].dropna().to_numpy() + datum_offset_m
    z_lat = float(np.quantile(tides, lat_q))
    z_hat = float(np.quantile(tides, hat_q))
    log.info(
        "%s: z_LAT=%.2f m, z_HAT=%.2f m (n=%d, datum_offset=%.2f)",
        site_id, z_lat, z_hat, len(tides), datum_offset_m,
    )
    return TidalFlatBounds(
        site_id=site_id,
        z_lat_m=z_lat,
        z_hat_m=z_hat,
        datum_offset_m=datum_offset_m,
        model_name=model_name,
        n_reference=len(tides),
        reference_period=(str(reference_start.date()), str(reference_end.date())),
    )


# ---------------------------------------------------------------------------
# Pixel-area helper
# ---------------------------------------------------------------------------

def _pixel_area_m2(transform, crs, height: int, width: int) -> np.ndarray | float:
    """Return per-pixel area in m^2 (scalar for projected CRS; array for lonlat)."""
    if crs is None or crs.to_epsg() == 4326:
        # WGS84 → use approximate cos(lat) scaling at row centroids.
        from rasterio.transform import xy

        rows = np.arange(height)
        _, lats = xy(transform, rows, [width // 2] * len(rows), offset="center")
        lats = np.asarray(lats)
        px_w_deg = abs(transform.a)
        px_h_deg = abs(transform.e)
        # 1 deg lat ≈ 111.32 km
        per_row = (
            px_w_deg * 111_320.0 * np.cos(np.deg2rad(lats))
            * px_h_deg * 111_320.0
        )
        return per_row.reshape(-1, 1).repeat(width, axis=1)
    return abs(transform.a) * abs(transform.e)


# ---------------------------------------------------------------------------
# DEM-based area
# ---------------------------------------------------------------------------

@dataclass
class DemAreaResult:
    site_id: str
    year: int
    n_valid_pixels: int
    area_dem_km2: float
    z_lat_m: float
    z_hat_m: float
    dem_min_m: float
    dem_max_m: float


def compute_dem_area(
    dem_path: Path,
    bounds: TidalFlatBounds,
    *,
    year: int,
    min_n_obs: int = MIN_N_OBS,
    if_lo: float | None = IF_LO,
    if_hi: float | None = IF_HI,
) -> DemAreaResult:
    """Count V4 DEM pixels in ``[z_LAT, z_HAT]`` and ``n_obs >= min_n_obs``.

    If ``if_lo``/``if_hi`` are not ``None`` and the DEM carries an
    inundation-frequency band (``BAND_IF``), pixels are additionally gated
    to ``if_lo <= inundation_frequency <= if_hi`` (intrinsic intertidal
    filter; see ``IF_LO``/``IF_HI``). Pass ``None`` to disable.
    """
    import rasterio

    inund = None
    with rasterio.open(dem_path) as src:
        dem = src.read(BAND_DEM, masked=True).filled(np.nan)
        n_obs = src.read(BAND_N_OBS, masked=True).filled(0)
        if src.count >= BAND_IF and if_lo is not None and if_hi is not None:
            inund = src.read(BAND_IF, masked=True).filled(np.nan)
        transform = src.transform
        crs = src.crs
        height, width = src.height, src.width

    valid_dem = (dem >= bounds.z_lat_m) & (dem <= bounds.z_hat_m) & np.isfinite(dem)
    enough_obs = n_obs >= min_n_obs
    mask = valid_dem & enough_obs
    if inund is not None:
        mask &= np.isfinite(inund) & (inund >= if_lo) & (inund <= if_hi)
    pixel_area = _pixel_area_m2(transform, crs, height, width)
    area_m2 = (mask.astype(float) * pixel_area).sum() if mask.any() else 0.0
    return DemAreaResult(
        site_id=bounds.site_id,
        year=year,
        n_valid_pixels=int(mask.sum()),
        area_dem_km2=float(area_m2) / 1e6,
        z_lat_m=bounds.z_lat_m,
        z_hat_m=bounds.z_hat_m,
        dem_min_m=float(np.nanmin(dem[mask])) if mask.any() else np.nan,
        dem_max_m=float(np.nanmax(dem[mask])) if mask.any() else np.nan,
    )


# ---------------------------------------------------------------------------
# Raster alignment helpers
# ---------------------------------------------------------------------------

def _align_to_reference(
    src_path: Path, reference_path: Path, band: int = 1
) -> np.ndarray:
    """Reproject + resample ``src_path`` onto the grid of ``reference_path``.

    Returns the aligned array as float32 (NaN for nodata).
    """
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(reference_path) as ref:
        ref_profile = ref.profile.copy()
        dst_shape = (ref.height, ref.width)
        dst_crs = ref.crs
        dst_transform = ref.transform

    with rasterio.open(src_path) as src:
        src_arr = src.read(band, masked=True).filled(np.nan).astype(np.float32)
        src_transform = src.transform
        src_crs = src.crs

    dst_arr = np.full(dst_shape, np.nan, dtype=np.float32)
    reproject(
        source=src_arr,
        destination=dst_arr,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return dst_arr


# ---------------------------------------------------------------------------
# 3-tier extent fusion
# ---------------------------------------------------------------------------

@dataclass
class FusedExtentResult:
    site_id: str
    year: int
    tier1_pixels: int
    tier2_pixels: int
    tier3_pixels: int
    tier1_km2: float
    tier2_km2: float
    tier3_km2: float
    total_km2: float
    out_path: Path


def fuse_extent(
    dem_path: Path,
    msic_path: Path,
    qa_path: Path,
    bounds: TidalFlatBounds,
    *,
    site_id: str,
    year: int,
    out_path: Path,
    min_n_obs: int = MIN_N_OBS,
) -> FusedExtentResult:
    """Produce the 4-class fused extent raster and per-tier area summary.

    All three input rasters are aligned to the V4 DEM grid before
    fusion. If the QA raster is missing, all pixels are treated as
    QA-passing (issue a warning).
    """
    import rasterio

    with rasterio.open(dem_path) as src:
        dem = src.read(BAND_DEM, masked=True).filled(np.nan)
        n_obs = src.read(BAND_N_OBS, masked=True).filled(0)
        profile = src.profile.copy()
        transform = src.transform
        crs = src.crs
        height, width = src.height, src.width

    msic = _align_to_reference(msic_path, dem_path, band=1)
    msic_is_flat = np.isfinite(msic) & (msic >= 1)

    if qa_path is not None and Path(qa_path).exists():
        qa = _align_to_reference(qa_path, dem_path, band=4)
        qa_pass = (qa >= 0.5) & np.isfinite(qa)
    else:
        log.warning("No QA raster at %s — treating all pixels as QA-passing", qa_path)
        qa_pass = np.ones_like(dem, dtype=bool)

    dem_valid = (
        np.isfinite(dem)
        & (dem >= bounds.z_lat_m)
        & (dem <= bounds.z_hat_m)
        & (n_obs >= min_n_obs)
    )

    tier1 = dem_valid & msic_is_flat & qa_pass
    tier2 = dem_valid & ~msic_is_flat
    tier3 = ~dem_valid & msic_is_flat

    fused = np.zeros_like(dem, dtype=np.uint8)
    fused[tier3] = TIER_MSIC_ONLY
    fused[tier2] = TIER_DEM_ONLY
    fused[tier1] = TIER_HIGH  # tier1 wins ties

    pixel_area = _pixel_area_m2(transform, crs, height, width)
    if np.isscalar(pixel_area):
        pa = float(pixel_area)
        area_t1 = tier1.sum() * pa / 1e6
        area_t2 = tier2.sum() * pa / 1e6
        area_t3 = tier3.sum() * pa / 1e6
    else:
        area_t1 = float((tier1 * pixel_area).sum()) / 1e6
        area_t2 = float((tier2 * pixel_area).sum()) / 1e6
        area_t3 = float((tier3 * pixel_area).sum()) / 1e6

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(count=1, dtype="uint8", nodata=255, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(fused, 1)
        dst.set_band_description(1, "tier (0=reject,1=high,2=dem_only,3=msic_only)")
    log.info(
        "Fused extent %s %s → %s  T1=%.2f T2=%.2f T3=%.2f km^2",
        site_id, year, out_path.name, area_t1, area_t2, area_t3,
    )

    return FusedExtentResult(
        site_id=site_id,
        year=year,
        tier1_pixels=int(tier1.sum()),
        tier2_pixels=int(tier2.sum()),
        tier3_pixels=int(tier3.sum()),
        tier1_km2=float(area_t1),
        tier2_km2=float(area_t2),
        tier3_km2=float(area_t3),
        total_km2=float(area_t1 + area_t2 + area_t3),
        out_path=out_path,
    )


__all__ = [
    "BAND_DEM",
    "BAND_N_OBS",
    "BAND_IF",
    "MIN_N_OBS",
    "TIER_HIGH",
    "TIER_DEM_ONLY",
    "TIER_MSIC_ONLY",
    "REJECT",
    "TidalFlatBounds",
    "DemAreaResult",
    "FusedExtentResult",
    "compute_tidal_flat_bounds",
    "compute_dem_area",
    "fuse_extent",
]
