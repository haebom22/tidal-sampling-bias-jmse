"""Validate a waterline DEM against the Copernicus GLO-30 (TanDEM-X derived).

The Copernicus GLO-30 product (``COPERNICUS/DEM/GLO30`` on GEE) is the
free, globally available derivative of the original TanDEM-X 12 m
WorldDEM. Pixels are 30 m and elevations are referenced to the
EGM2008 geoid.

Two transformations are needed before our 10 m waterline DEM (in the
KHOA datum, approximate lowest low water — ALLW, the sum of the M2, S2,
K1, O1 amplitudes below mean sea level; distinct from and not equal to
the lowest astronomical tide) can be compared to GLO-30:

1. **Vertical datum**: KHOA = ALLW; GLO-30 = EGM2008 geoid.
   The site-specific offset between ALLW and EGM2008 is essentially the
   mean sea level above the chart datum, available either from the
   KHOA MSL constant for the gauge or from the FES2022b z0 offset.
   We accept it as a CLI argument so the user can supply the value
   appropriate for the gauge they used.

2. **Spatial grid**: 10 m UTM vs 30 m EGM2008 lat/lon. We reproject
   our DEM onto the GLO-30 grid using a mean resampler (3×3 average),
   which is the most defensible aggregator for a TanDEM-X comparison.

Compared quantities
-------------------
- per-pixel residual (our - GLO30)
- RMSE, MAE, mean bias
- spatial map of the residuals
- predicted bias from the manuscript model β · A · ⟨cos θ⟩
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class ValidationStats:
    site_id: str
    variant: str
    n_pixels: int
    rmse_m: float
    mae_m: float
    mean_bias_m: float           # our - GLO30
    median_bias_m: float
    p05_residual_m: float
    p95_residual_m: float
    predicted_bias_m: float | None  # from β·A·⟨cos θ⟩

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _read_dem(path: Path) -> tuple[np.ndarray, dict, "rasterio.io.DatasetReader"]:
    """Read the first band as a masked float32 array."""
    import rasterio
    src = rasterio.open(path)
    arr = src.read(1, masked=True).astype(np.float32)
    return arr, src.profile.copy(), src


def fetch_glo30_for_bbox(
    bbox: list[float],
    scale_m: int = 30,
    out_path: Path | None = None,
) -> Path:
    """Pull a GLO-30 raster covering ``bbox`` from GEE to local disk.

    Parameters
    ----------
    bbox
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.
    scale_m
        Output resolution (default 30, matching native GLO-30).
    out_path
        Destination GeoTIFF. Defaults to ``data/raw/glo30/<bbox-hash>.tif``.
    """
    import ee

    from ..gee.exports import export_image_to_local
    from .. import PROJECT_ROOT

    if out_path is None:
        bb_str = "_".join(f"{x:+.4f}" for x in bbox).replace(".", "p")
        out_path = PROJECT_ROOT / "data" / "raw" / "glo30" / f"glo30_{bb_str}.tif"

    geom = ee.Geometry.Rectangle(bbox, proj="EPSG:4326", geodesic=False)
    glo30 = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM").mosaic().rename("z_glo30")
    out_path = Path(out_path)
    result = export_image_to_local(
        glo30,
        region=geom,
        scale_m=scale_m,
        out_path=out_path,
        crs="EPSG:32652",
    )
    log.info("GLO-30: %.1f MB → %s", result.n_bytes / 1e6, out_path)
    return out_path


def reproject_to_glo30_grid(
    src_dem_path: Path,
    glo30_path: Path,
    out_path: Path,
) -> Path:
    """Reproject our 10 m DEM onto the 30 m GLO-30 grid using mean resampling."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    with rasterio.open(glo30_path) as ref:
        ref_transform = ref.transform
        ref_crs = ref.crs
        ref_height = ref.height
        ref_width = ref.width
        ref_profile = ref.profile.copy()

    with rasterio.open(src_dem_path) as src:
        out_arr = np.full((ref_height, ref_width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=out_arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            resampling=Resampling.average,
        )

    ref_profile.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **ref_profile) as dst:
        dst.write(out_arr.astype(np.float32), 1)
        dst.set_band_description(1, "dem_m_on_glo30_grid")
    log.info("Reprojected → %s", out_path)
    return out_path


def compare_to_glo30(
    dem_on_glo30_path: Path,
    glo30_path: Path,
    site_id: str,
    variant: str,
    khoa_to_egm2008_offset_m: float = 0.0,
    predicted_bias_m: float | None = None,
    *,
    inundation_min: float = 0.0,
    inundation_max: float = 1.0,
    inundation_path: Path | None = None,
) -> tuple[ValidationStats, dict]:
    """Compute residual statistics.

    Parameters
    ----------
    khoa_to_egm2008_offset_m
        Add this to our DEM to convert KHOA datum → EGM2008 geoid
        before differencing. Typical Korean west coast values are
        +2 to +5 m (MSL above ALLW, then -geoid offset).
    predicted_bias_m
        Predicted bias from the manuscript model (β·A·⟨cos θ⟩) for
        cross-comparison.
    inundation_path
        Path to a per-pixel inundation-frequency raster (same grid as
        the GLO-30 product). When given together with ``inundation_min``
        / ``inundation_max``, the comparison is restricted to pixels
        within that frequency band (e.g. ``0.05 < f < 0.95`` to keep
        only true intertidal pixels).
    """
    import rasterio

    with rasterio.open(dem_on_glo30_path) as src_d:
        ours = src_d.read(1).astype(np.float32)
    with rasterio.open(glo30_path) as src_g:
        glo = src_g.read(1).astype(np.float32)

    # Datum shift
    ours_egm = ours + float(khoa_to_egm2008_offset_m)

    # Intertidal-only restriction
    valid = np.isfinite(ours_egm) & np.isfinite(glo)
    if inundation_path is not None:
        with rasterio.open(inundation_path) as src_i:
            inund = src_i.read(1).astype(np.float32)
        valid &= (inund >= inundation_min) & (inund <= inundation_max)

    diff = ours_egm[valid] - glo[valid]
    n = int(diff.size)
    if n == 0:
        log.warning("No overlapping intertidal pixels for %s_%s", site_id, variant)
        stats = ValidationStats(
            site_id=site_id, variant=variant,
            n_pixels=0,
            rmse_m=float("nan"), mae_m=float("nan"),
            mean_bias_m=float("nan"), median_bias_m=float("nan"),
            p05_residual_m=float("nan"), p95_residual_m=float("nan"),
            predicted_bias_m=predicted_bias_m,
        )
        return stats, {"residuals": np.array([])}

    stats = ValidationStats(
        site_id=site_id,
        variant=variant,
        n_pixels=n,
        rmse_m=float(np.sqrt(np.mean(diff ** 2))),
        mae_m=float(np.mean(np.abs(diff))),
        mean_bias_m=float(np.mean(diff)),
        median_bias_m=float(np.median(diff)),
        p05_residual_m=float(np.percentile(diff, 5)),
        p95_residual_m=float(np.percentile(diff, 95)),
        predicted_bias_m=predicted_bias_m,
    )
    return stats, {"residuals": diff, "valid_mask": valid, "diff_map": np.where(valid, ours_egm - glo, np.nan)}


def stats_to_dataframe(stats: list[ValidationStats]) -> pd.DataFrame:
    return pd.DataFrame([s.as_dict() for s in stats])
