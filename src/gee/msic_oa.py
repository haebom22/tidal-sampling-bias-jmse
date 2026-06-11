"""Jia et al. (2021) MSIC-OA tidal-flat mapping in Earth Engine.

Reference
---------
Jia, M., Wang, Z., Mao, D., Ren, C., Wang, C., Wang, Y. (2021).
*Rapid, robust, and automated mapping of tidal flats in China using time
series Sentinel-2 images and Google Earth Engine.* RSE 255, 112285.

Algorithm
---------
For each pixel and a one- (or three-) year time window:

1. Maximum Spectral Index Composite (MSIC):
   - ``mndwi_max(p) = max_{k: clear} MNDWI_k(p)``  → represents the
     pixel at *highest water extent* (i.e. high tide).
   - ``mndwi_min(p) = min_{k: clear} MNDWI_k(p)``  → represents the
     pixel at *lowest water extent* (i.e. low tide).

2. Tidal flat candidate = pixels where the *maximum* is water and the
   *minimum* is land:
        tidal_flat(p) = (mndwi_max(p) > tau_w) AND (mndwi_min(p) < tau_l)
   where ``tau_w`` and ``tau_l`` are Otsu thresholds derived from
   the histograms of ``mndwi_max`` and ``mndwi_min`` respectively.

3. Aquaculture / floating-mud rejection: drop pixels whose
   between-composite difference (``mndwi_max - mndwi_min``) is below a
   small Otsu-derived threshold (these are pixels that never expose;
   typically aquaculture ponds with consistently fresh water).

4. Apply the JRC Global Surface Water occurrence 5–95% mask
   (consistent with the rest of this codebase).

5. Connectivity filter: drop connected components < ``min_pixels`` to
   suppress isolated speckle noise.

Output
------
A single ``ee.Image`` with two bands:
- ``tidal_flat``: uint8 binary (1 = tidal flat).
- ``mndwi_range``: float32, ``mndwi_max - mndwi_min`` (diagnostic).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import ee

from .waterline import (
    NATIVE_SCALE_M,
    _compute_otsu,
    _landsat_qa_mask,
    _landsat_scale_to_reflectance,
    _s2_scl_mask,
    filter_collection,
)

log = logging.getLogger(__name__)


@dataclass
class MsicOaResult:
    image: ee.Image
    tau_max: float | None
    tau_min: float | None
    tau_range: float | None
    n_scenes: int


# ---------------------------------------------------------------------------
# Per-scene MNDWI image (multi-sensor optical) — independent of the waterline
# DEM pipeline so MSIC can be run as a standalone baseline.
# ---------------------------------------------------------------------------

def _mndwi_clear(image: ee.Image, sensor: str) -> ee.Image:
    if sensor in ("L8", "L9"):
        clear = _landsat_qa_mask(image)
        green = _landsat_scale_to_reflectance(image, "SR_B3")
        swir1 = _landsat_scale_to_reflectance(image, "SR_B6")
    elif sensor == "S2":
        clear = _s2_scl_mask(image)
        green = image.select("B3").divide(10000.0)
        swir1 = image.select("B11").divide(10000.0)
    else:
        raise ValueError(f"Unsupported sensor: {sensor!r}")
    idx = green.subtract(swir1).divide(green.add(swir1)).rename("MNDWI")
    return idx.updateMask(clear)


def _build_collection(
    geometry: ee.Geometry,
    start: str,
    end: str,
    cloud_max: float,
    sensors: Sequence[str],
) -> ee.ImageCollection:
    """Merge L8 + L9 + S2 (or any subset) into one MNDWI collection."""
    merged: ee.ImageCollection | None = None
    for sensor in sensors:
        if sensor not in ("L8", "L9", "S2"):
            log.warning("Ignoring non-optical sensor %s for MSIC-OA", sensor)
            continue
        coll = filter_collection(sensor, geometry, start, end, cloud_max=cloud_max)
        coll = coll.map(lambda img, s=sensor: _mndwi_clear(img, s).clip(geometry))
        merged = coll if merged is None else merged.merge(coll)
    if merged is None:
        raise ValueError("No usable optical sensors supplied to MSIC-OA")
    return merged


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_msic_oa_extent(
    geometry: ee.Geometry,
    start: str,
    end: str,
    cloud_max: float = 60.0,
    sensors: Sequence[str] = ("L8", "L9", "S2"),
    min_pixels: int = 4,
    apply_jrc_mask: bool = True,
    fallback_tau_max: float = 0.0,
    fallback_tau_min: float = 0.0,
    fallback_tau_range: float = 0.1,
) -> MsicOaResult:
    """Build a binary tidal-flat extent image via MSIC-OA.

    Parameters
    ----------
    geometry
        Site bbox (``ee.Geometry``).
    start, end
        Date range, e.g. ``"2020-01-01"`` to ``"2020-12-31"``.
    cloud_max
        Cloud cover threshold (%) for the optical filter.
    sensors
        Subset of {"L8", "L9", "S2"}. Sentinel-2 alone (Jia's original
        approach) is also supported; passing all three is a strict
        super-set that increases temporal density at the cost of
        slightly heterogeneous MNDWI dynamic range across sensors.
    min_pixels
        Minimum connected-component size (pixels) to keep — drop smaller
        speckle blobs.
    apply_jrc_mask
        If ``True``, restrict the output to JRC Global Surface Water
        occurrence 5–95% (= the dynamic intertidal zone).
    fallback_tau_*
        Used if the corresponding Otsu reduction fails (degenerate
        histogram). Defaults are the conservative manuscript-2 values.
    """
    coll = _build_collection(geometry, start, end, cloud_max, sensors)
    n_scenes = int(coll.size().getInfo())
    if n_scenes == 0:
        raise RuntimeError(
            f"No optical scenes for MSIC-OA over {start}..{end} in this bbox"
        )

    mndwi_max = coll.select("MNDWI").reduce(ee.Reducer.max()).rename("mndwi_max")
    mndwi_min = coll.select("MNDWI").reduce(ee.Reducer.min()).rename("mndwi_min")
    mndwi_range = mndwi_max.subtract(mndwi_min).rename("mndwi_range")

    # Otsu thresholds for the three diagnostic distributions.
    # The histograms are statistical — they don't need native (10 m)
    # resolution. Use ~60 m to keep the reduceRegion inside the GEE
    # 5-minute sync compute budget on Korean coastal bboxes.
    otsu_scale = max(NATIVE_SCALE_M["S2"] * 6, 60)
    tau_max, _ = _compute_otsu(
        mndwi_max, geometry=geometry, scale=otsu_scale, min_value=-0.5, max_value=0.8
    )
    if tau_max is None:
        log.warning("Otsu for mndwi_max degenerate, using fallback %.3f", fallback_tau_max)
        tau_max = fallback_tau_max
    tau_min, _ = _compute_otsu(
        mndwi_min, geometry=geometry, scale=otsu_scale, min_value=-0.8, max_value=0.5
    )
    if tau_min is None:
        log.warning("Otsu for mndwi_min degenerate, using fallback %.3f", fallback_tau_min)
        tau_min = fallback_tau_min
    tau_range, _ = _compute_otsu(
        mndwi_range, geometry=geometry, scale=otsu_scale, min_value=0.02, max_value=0.8
    )
    if tau_range is None:
        log.warning("Otsu for mndwi_range degenerate, using fallback %.3f", fallback_tau_range)
        tau_range = fallback_tau_range

    log.info(
        "MSIC-OA thresholds: tau_max=%.3f, tau_min=%.3f, tau_range=%.3f (n_scenes=%d)",
        tau_max, tau_min, tau_range, n_scenes,
    )

    # Tidal flat candidate: max is water AND min is land AND range exceeds noise floor.
    is_water_at_max = mndwi_max.gte(tau_max)
    is_land_at_min = mndwi_min.lt(tau_min)
    enough_dynamic = mndwi_range.gte(tau_range)
    tidal_flat = (
        is_water_at_max.And(is_land_at_min).And(enough_dynamic)
        .rename("tidal_flat")
        .toByte()
    )

    if apply_jrc_mask:
        gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
        intertidal_mask = gsw.gte(5).And(gsw.lte(95)).clip(geometry)
        tidal_flat = tidal_flat.updateMask(intertidal_mask)

    # Connectivity filter — drop components smaller than ``min_pixels``.
    if min_pixels > 1:
        cc = tidal_flat.selfMask().connectedPixelCount(maxSize=min_pixels + 1, eightConnected=True)
        big_enough = cc.gte(min_pixels)
        tidal_flat = tidal_flat.updateMask(big_enough)

    out = tidal_flat.unmask(0).addBands(mndwi_range.toFloat())
    return MsicOaResult(
        image=out.clip(geometry),
        tau_max=float(tau_max),
        tau_min=float(tau_min),
        tau_range=float(tau_range),
        n_scenes=n_scenes,
    )


def msic_area_km2(
    msic_image: ee.Image,
    geometry: ee.Geometry,
    scale_m: int = 10,
    max_rescale_factor: int = 8,
) -> float:
    """Compute the tidal-flat area (km^2) inside ``geometry`` from an MSIC image.

    On large bboxes the lazy MSIC chain (max/min reduce over hundreds of
    optical scenes) blows past the GEE 5-minute sync compute budget and
    raises ``EEException: Computation timed out``. We catch that and
    automatically retry at progressively coarser ``scale`` (doubling each
    time, up to ``max_rescale_factor``). ``tileScale=16`` also splits the
    work across more workers to push back the timeout boundary.
    """
    flat = msic_image.select("tidal_flat").eq(1)
    pixel_area = ee.Image.pixelArea().multiply(flat)

    factor = 1
    current_scale = float(scale_m)
    while True:
        try:
            stats = pixel_area.reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=geometry,
                scale=current_scale,
                maxPixels=int(1e10),
                bestEffort=True,
                tileScale=16,
            )
            val = stats.get("area")
            if val is None:
                return float("nan")
            return float(ee.Number(val).divide(1e6).getInfo())
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "timed out" not in text and "deadline" not in text:
                log.warning("msic_area_km2 failed at scale=%.0fm: %s", current_scale, exc)
                return float("nan")
            factor *= 2
            if factor > max_rescale_factor:
                log.warning(
                    "msic_area_km2 exhausted rescale (final scale=%.0fm): timeout persisted",
                    current_scale,
                )
                return float("nan")
            new_scale = float(scale_m) * factor
            log.warning(
                "msic_area_km2 timed out at scale=%.0fm; retrying coarser scale=%.0fm (x%d)",
                current_scale, new_scale, factor,
            )
            current_scale = new_scale


__all__ = [
    "MsicOaResult",
    "build_msic_oa_extent",
    "msic_area_km2",
]
