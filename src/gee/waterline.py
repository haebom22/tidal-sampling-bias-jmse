"""Per-scene water/land masks from Sentinel-2, Landsat 8/9, and Sentinel-1.

Each helper returns a binary GEE image (1 = water, 0 = exposed land,
masked = invalid / cloud / outside bbox) at the *native* resolution of the
sensor. Downstream code (`src/gee/dem.py`) is responsible for reprojecting
all per-scene masks onto a common 10 m grid before stacking.

Algorithm overview
------------------
- **L8/L9** : Modified Normalised Difference Water Index
    MNDWI = (Green - SWIR1) / (Green + SWIR1)
  with QA_PIXEL-based cloud/shadow/snow masking. Threshold is either the
  caller-supplied value (default 0.0), or a per-scene Otsu threshold
  computed from the histogram of MNDWI inside the site bbox.

- **S2**   : Same MNDWI definition (B3, B11) with SCL-based masking
  (drop classes 1/3/8/9/10/11).

- **S1**   : See ``sar_water_mask``. Speckle-filtered VV sigma0 with
  an Otsu threshold over a fixed search window around -17 dB.

The Otsu helper expects a histogram dictionary (the output of
``image.reduceRegion(ee.Reducer.histogram(...))``); it is implemented in
pure NumPy so the actual Otsu computation happens locally and the
threshold is sent back as a constant ``ee.Number``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import ee
import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants and per-sensor configuration
# ---------------------------------------------------------------------------

OPTICAL_SENSORS = ("L8", "L9", "S2")
ALL_SENSORS = OPTICAL_SENSORS + ("S1",)

# Native resolution per sensor (metres).
NATIVE_SCALE_M: dict[str, int] = {
    "L8": 30,
    "L9": 30,
    "S2": 10,
    "S1": 10,
}

# Default thresholds (applied if Otsu cannot be computed).
DEFAULT_MNDWI_THRESHOLD = 0.0
DEFAULT_SAR_VV_THRESHOLD_DB = -17.0


@dataclass
class WaterMaskResult:
    """Output of a per-scene water-mask call.

    Attributes
    ----------
    image
        ``ee.Image`` with a single ``water`` band (1=water, 0=land).
        Areas outside the valid mask are *masked* (not 0).
    threshold
        Numeric threshold actually used (MNDWI for optical, dB for SAR).
        ``None`` if the scene was rejected.
    method
        ``"otsu"``, ``"fallback"``, or ``"fixed"``.
    n_valid_pixels
        Pixel count used by the Otsu histogram (informational).
    """

    image: ee.Image | None
    threshold: float | None
    method: str
    n_valid_pixels: int | None = None


# ---------------------------------------------------------------------------
# Otsu (NumPy implementation; the GEE side only needs to produce the histogram)
# ---------------------------------------------------------------------------

def otsu_threshold_from_histogram(hist: dict | None) -> float | None:
    """Otsu's between-class variance threshold from a GEE histogram dict.

    Parameters
    ----------
    hist
        Output of ``ee.Reducer.histogram``: a dict with ``bucketMeans``
        and ``histogram`` arrays (or ``None`` if the reduction failed).

    Returns
    -------
    Threshold in the same units as the input image, or ``None`` if the
    histogram is degenerate (single class, empty, etc.).
    """
    if hist is None:
        return None
    counts_in = hist.get("histogram")
    means_in = hist.get("bucketMeans")
    if counts_in is None or means_in is None:
        return None
    counts = np.asarray(counts_in, dtype=float)
    means = np.asarray(means_in, dtype=float)
    if counts.size != means.size or counts.size < 2:
        return None

    total = counts.sum()
    if total <= 0:
        return None
    cumcount = np.cumsum(counts)
    cumsum = np.cumsum(counts * means)
    sum_total = cumsum[-1]

    w_b = cumcount[:-1]
    w_f = total - w_b
    mu_b = np.divide(cumsum[:-1], w_b, out=np.zeros_like(w_b), where=w_b > 0)
    mu_f = np.divide(
        sum_total - cumsum[:-1], w_f, out=np.zeros_like(w_f), where=w_f > 0
    )
    variance = w_b * w_f * (mu_b - mu_f) ** 2
    if not np.isfinite(variance).any() or variance.max() <= 0:
        return None
    idx = int(np.argmax(variance))
    return float(0.5 * (means[idx] + means[idx + 1]))


def _compute_otsu(
    image: ee.Image,
    geometry: ee.Geometry,
    scale: float,
    min_value: float,
    max_value: float,
    n_bins: int = 256,
    max_pixels: int = int(1e8),
) -> tuple[float | None, int | None]:
    """Return (otsu_threshold, n_pixels). Single-band image only."""
    reducer = ee.Reducer.histogram(maxBuckets=n_bins, minBucketWidth=None) \
        .combine(ee.Reducer.count(), sharedInputs=True)
    # tileScale=16 splits the reduceRegion across 16× more workers, which
    # is the standard GEE escape hatch for "Computation timed out" on
    # large bboxes / dense ImageCollections.
    try:
        result = image.reduceRegion(
            reducer=reducer,
            geometry=geometry,
            scale=scale,
            bestEffort=True,
            maxPixels=max_pixels,
            tileScale=16,
        ).getInfo()
    except Exception as exc:  # noqa: BLE001
        log.warning("Otsu reduce failed: %s", exc)
        return None, None
    if result is None:
        return None, None
    band_name = image.bandNames().get(0).getInfo()
    hist = result.get(f"{band_name}_histogram")
    n_pixels = int(result.get(f"{band_name}_count", 0) or 0)
    if hist is None or n_pixels == 0:
        return None, n_pixels
    thr = otsu_threshold_from_histogram(hist)
    if thr is None or not (min_value <= thr <= max_value):
        return None, n_pixels
    return thr, n_pixels


# ---------------------------------------------------------------------------
# Optical preprocessing: cloud masking + MNDWI
# ---------------------------------------------------------------------------

def _landsat_qa_mask(image: ee.Image) -> ee.Image:
    """Boolean mask, 1 where the pixel is clear of cloud/shadow/snow."""
    qa = image.select("QA_PIXEL")
    cloud = qa.bitwiseAnd(1 << 3).neq(0)
    cloud_shadow = qa.bitwiseAnd(1 << 4).neq(0)
    snow = qa.bitwiseAnd(1 << 5).neq(0)
    dilated = qa.bitwiseAnd(1 << 1).neq(0)
    return cloud.Or(cloud_shadow).Or(snow).Or(dilated).Not()


def _s2_scl_mask(image: ee.Image) -> ee.Image:
    """Boolean mask, 1 where the SCL class is clear."""
    scl = image.select("SCL")
    # SCL codes:
    #   0=NO_DATA, 1=SATURATED, 3=CLOUD_SHADOW, 8=CLOUD_MED,
    #   9=CLOUD_HIGH, 10=THIN_CIRRUS, 11=SNOW.
    bad = (
        scl.eq(0)
        .Or(scl.eq(1))
        .Or(scl.eq(3))
        .Or(scl.gte(8))
    )
    return bad.Not()


def _landsat_scale_to_reflectance(image: ee.Image, band: str) -> ee.Image:
    """Apply Landsat C02/T1_L2 scale factors to a single band."""
    return image.select(band).multiply(2.75e-5).add(-0.2)


def mndwi(image: ee.Image, sensor: str) -> ee.Image:
    """Compute the Modified NDWI = (Green - SWIR1) / (Green + SWIR1)."""
    if sensor in ("L8", "L9"):
        green = _landsat_scale_to_reflectance(image, "SR_B3")
        swir1 = _landsat_scale_to_reflectance(image, "SR_B6")
    elif sensor == "S2":
        green = image.select("B3").divide(10000.0)
        swir1 = image.select("B11").divide(10000.0)
    else:
        raise ValueError(f"Unsupported optical sensor for MNDWI: {sensor!r}")
    return green.subtract(swir1).divide(green.add(swir1)).rename("MNDWI")


def optical_water_mask(
    image: ee.Image,
    sensor: str,
    geometry: ee.Geometry,
    threshold: float | None = None,
    use_otsu: bool = True,
) -> WaterMaskResult:
    """Per-scene water/land binary mask for an optical scene.

    Parameters
    ----------
    image
        A single ``ee.Image`` from the L2/SR collection of ``sensor``.
    sensor
        ``"L8"``, ``"L9"``, or ``"S2"``.
    geometry
        Site-level analysis bbox (used both for cloud-pct gating and as
        the histogram region for Otsu).
    threshold
        Override the Otsu / default threshold with this fixed value
        (MNDWI units; e.g. 0.0).
    use_otsu
        If ``True`` (default), compute a per-scene Otsu threshold from
        the MNDWI histogram. If Otsu fails (degenerate or out of range),
        fall back to ``DEFAULT_MNDWI_THRESHOLD = 0.0``.
    """
    if sensor not in OPTICAL_SENSORS:
        raise ValueError(f"optical_water_mask: sensor must be one of {OPTICAL_SENSORS}")

    image = image.clip(geometry)

    if sensor in ("L8", "L9"):
        clear = _landsat_qa_mask(image)
    else:
        clear = _s2_scl_mask(image)

    mndwi_band = mndwi(image, sensor).updateMask(clear)

    scale = NATIVE_SCALE_M[sensor]
    method = "fixed"
    thr_used = threshold
    n_pixels = None
    if threshold is None:
        if use_otsu:
            thr_used, n_pixels = _compute_otsu(
                mndwi_band,
                geometry=geometry,
                scale=scale,
                min_value=-0.6,
                max_value=0.6,
            )
            method = "otsu" if thr_used is not None else "fallback"
        if thr_used is None:
            thr_used = DEFAULT_MNDWI_THRESHOLD
            method = "fallback" if use_otsu else "fixed"

    water = mndwi_band.gte(thr_used).rename("water").toByte()
    water = water.updateMask(clear)
    return WaterMaskResult(
        image=water, threshold=float(thr_used), method=method, n_valid_pixels=n_pixels
    )


# ---------------------------------------------------------------------------
# SAR — Sentinel-1 GRD (IW, VV)
# ---------------------------------------------------------------------------

def _s1_boxcar(image: ee.Image, radius_px: int = 2) -> ee.Image:
    """Simple square-mean speckle suppression on log-space sigma0.

    A 5x5 (radius=2) boxcar kills most multiplicative speckle while
    preserving the sharp land/water boundary on flat tidal flats. This is
    intentionally simpler than refined-Lee: tidal-flat dynamic range is
    modest and the dominant downstream operation is a global threshold,
    which is robust to residual speckle.
    """
    return image.reduceNeighborhood(
        reducer=ee.Reducer.mean(),
        kernel=ee.Kernel.square(radius=radius_px, units="pixels"),
    )


def sar_water_mask(
    image: ee.Image,
    geometry: ee.Geometry,
    threshold_db: float | None = None,
    use_otsu: bool = True,
    boxcar_radius_px: int = 2,
) -> WaterMaskResult:
    """Per-scene SAR water mask using sigma0_VV.

    Pipeline:
    1. Select VV, clip to ``geometry``.
    2. Boxcar speckle suppression (default 5x5 px).
    3. Otsu threshold over the bbox histogram, restricted to the
       physically plausible band ``[-25, -10] dB``. Outside that range
       (e.g. scene is dominated by exposed flat or by water alone),
       fall back to ``DEFAULT_SAR_VV_THRESHOLD_DB = -17 dB``.
    4. Pixels with ``sigma0_VV < threshold`` are labelled water (1).

    Parameters
    ----------
    image
        A single ``ee.Image`` from ``COPERNICUS/S1_GRD`` (IW, VV).
        Already calibrated to sigma0 (dB) and terrain-corrected by GEE.
    geometry
        Site-level analysis bbox.
    threshold_db
        Override threshold (dB). If supplied, ``use_otsu`` is ignored.
    use_otsu
        If ``True``, derive threshold from the histogram.
    boxcar_radius_px
        Radius (pixels) of the speckle-suppression kernel. Set to 0
        to disable.
    """
    vv = image.select("VV").clip(geometry)
    if boxcar_radius_px > 0:
        vv = _s1_boxcar(vv, radius_px=boxcar_radius_px).rename("VV")

    scale = NATIVE_SCALE_M["S1"]
    method = "fixed"
    thr_used = threshold_db
    n_pixels = None
    if threshold_db is None:
        if use_otsu:
            thr_used, n_pixels = _compute_otsu(
                vv,
                geometry=geometry,
                scale=scale,
                min_value=-25.0,
                max_value=-10.0,
            )
            method = "otsu" if thr_used is not None else "fallback"
        if thr_used is None:
            thr_used = DEFAULT_SAR_VV_THRESHOLD_DB
            method = "fallback" if use_otsu else "fixed"

    water = vv.lt(thr_used).rename("water").toByte()
    return WaterMaskResult(
        image=water, threshold=float(thr_used), method=method, n_valid_pixels=n_pixels
    )


def sar_orbit_filter(
    collection: ee.ImageCollection,
    pass_direction: str | None = None,
    relative_orbit: int | None = None,
) -> ee.ImageCollection:
    """Optional helper to restrict S1 to one pass direction / relative orbit.

    Used by the DEM pipeline to (i) include both ASCENDING and DESCENDING
    by default (the manuscript's *both* sample the orthogonal phase
    window), or (ii) cleanly slice into separate ASC and DESC variants
    when investigating per-pass biases.
    """
    if pass_direction is not None:
        collection = collection.filter(
            ee.Filter.eq("orbitProperties_pass", pass_direction)
        )
    if relative_orbit is not None:
        collection = collection.filter(
            ee.Filter.eq("relativeOrbitNumber_start", int(relative_orbit))
        )
    return collection


def filter_wind(
    collection: ee.ImageCollection,
    max_wind_ms: float = 8.0,
) -> ee.ImageCollection:
    """Optional ERA5-based wind filter.

    Wind-roughening above ~8 m/s lifts open-water sigma0_VV by 2-5 dB
    and can break the water/land contrast. This filter drops S1 scenes
    whose acquisition-time ERA5-Land 10 m wind exceeds ``max_wind_ms``.

    Implementation note: we read ECMWF ERA5-Land hourly u10/v10 at the
    image's geometry centroid and bail out (keep the scene) if no
    matching ERA5 record exists.
    """
    era5 = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").select(
        ["u_component_of_wind_10m", "v_component_of_wind_10m"]
    )

    def _ok(img: ee.Image) -> ee.Image:
        t = ee.Date(img.get("system:time_start"))
        # ERA5-Land is hourly; floor to the hour.
        t_hr = ee.Date.fromYMD(t.get("year"), t.get("month"), t.get("day")).advance(
            t.get("hour"), "hour"
        )
        wind_img = era5.filterDate(t_hr, t_hr.advance(1, "hour")).first()
        # If there is no ERA5 image, default to "keep" (assume calm).
        keep = ee.Algorithms.If(
            wind_img,
            wind_img.select("u_component_of_wind_10m").pow(2)
            .add(wind_img.select("v_component_of_wind_10m").pow(2))
            .sqrt()
            .reduceRegion(
                reducer=ee.Reducer.first(),
                geometry=img.geometry().centroid(maxError=1000),
                scale=11132,
                bestEffort=True,
            )
            .get("u_component_of_wind_10m"),
            ee.Number(0),
        )
        keep_n = ee.Number(keep).max(0)
        return img.set("era5_wind_ms", keep_n)

    annotated = collection.map(_ok)
    return annotated.filter(ee.Filter.lte("era5_wind_ms", max_wind_ms))


def _validate_sensor(sensor: str) -> None:
    if sensor not in ALL_SENSORS:
        raise ValueError(f"Unknown sensor {sensor!r}; expected one of {ALL_SENSORS}")


def collection_for_sensor(sensor: str) -> ee.ImageCollection:
    """Return the canonical GEE ImageCollection for ``sensor``."""
    _validate_sensor(sensor)
    mapping = {
        "L8": "LANDSAT/LC08/C02/T1_L2",
        "L9": "LANDSAT/LC09/C02/T1_L2",
        "S2": "COPERNICUS/S2_SR_HARMONIZED",
        "S1": "COPERNICUS/S1_GRD",
    }
    return ee.ImageCollection(mapping[sensor])


def filter_collection(
    sensor: str,
    geometry: ee.Geometry,
    start: str,
    end: str,
    cloud_max: float = 60.0,
) -> ee.ImageCollection:
    """Filter the canonical collection by bbox, date, and cloud cover.

    For S1, the cloud filter is ignored and IW/VV gating is applied.
    """
    coll = collection_for_sensor(sensor).filterBounds(geometry).filterDate(start, end)
    if sensor in ("L8", "L9"):
        coll = coll.filter(ee.Filter.lte("CLOUD_COVER", cloud_max))
    elif sensor == "S2":
        coll = coll.filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_max))
    elif sensor == "S1":
        coll = (
            coll.filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        )
    return coll


def water_mask(
    image: ee.Image,
    sensor: str,
    geometry: ee.Geometry,
    **kwargs,
) -> WaterMaskResult:
    """Dispatch helper: optical → ``optical_water_mask``; S1 → ``sar_water_mask``."""
    _validate_sensor(sensor)
    if sensor in OPTICAL_SENSORS:
        return optical_water_mask(image, sensor, geometry, **kwargs)
    return sar_water_mask(image, geometry, **kwargs)


def iter_water_masks(
    collection: ee.ImageCollection,
    sensor: str,
    geometry: ee.Geometry,
    limit: int | None = None,
    **kwargs,
) -> Iterable[tuple[ee.Image, WaterMaskResult]]:
    """Iterate (image, mask_result) pairs over a filtered collection.

    Used for serial export loops. Heavy: triggers one Otsu per scene.
    """
    size = collection.size().getInfo()
    if limit is not None:
        size = min(size, int(limit))
    images = collection.toList(size)
    for i in range(size):
        img = ee.Image(images.get(i))
        result = water_mask(img, sensor, geometry, **kwargs)
        yield img, result
