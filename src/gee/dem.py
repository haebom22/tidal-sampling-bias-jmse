"""Waterline DEM synthesis from per-scene water masks + per-scene tides.

Algorithm
---------
Given a stack of binary water masks ``W[k, y, x] ∈ {0, 1}`` and the
KHOA-interpolated tide height ``η[k]`` at each scene's acquisition time,
the per-pixel DEM elevation is estimated by the classical Mason (1995)
midpoint between the *highest tide at which the pixel was dry* and the
*lowest tide at which the pixel was wet*:

    z(y, x) = ( max{η[k]  |  W[k, y, x] = 0}
              + min{η[k]  |  W[k, y, x] = 1} ) / 2

Pixels that are wet in every scene or dry in every scene are masked out
(no intertidal information). The auxiliary ``inundation_frequency``
band — fraction of scenes in which the pixel was water — also drops
out of the same stack and is exported alongside the DEM for §5
truncation-band diagnostics.

There are two implementations:

* ``build_dem_gee``: runs the min/max reduce server-side and returns a
  single multi-band ``ee.Image``. This is the *default* path; one
  export is enough.
* ``build_dem_local_stream``: a fallback that processes already-exported
  per-scene mask GeoTIFFs on disk in a streaming fashion (constant
  memory). Useful when GEE compute / export limits are hit or when
  debugging the per-pixel logic locally.

Bias correction
---------------
Variants V3 and V4 of the pilot (`scripts/run_pilot_dem.py`) apply the
manuscript's *a priori* bias model

    η_corrected[k] = η_raw[k] − β · A · cos(θ_k)

before the min/max reduction. This removes the systematic phase-
correlated component from each scene's tide stamp, so the mean of the
corrected sample matches the reference distribution mean to leading
order. ``apply_bias_correction`` does the per-scene correction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import ee
import numpy as np
import pandas as pd

from .waterline import (
    NATIVE_SCALE_M,
    filter_collection,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-scene bias correction
# ---------------------------------------------------------------------------

BETA_DEFAULT = 1.78  # manuscript pooled fit (Section 4.3)

# Per-site time-mean tidal amplitudes (m), computed from KHOA HW/LW
# extremes in the 2020-2024 record. These match the values quoted in
# Tables 2-3 of the manuscript. (Garorim: Anheung; Suncheon: Yeosu.)
SITE_AMPLITUDE_M: dict[str, float] = {
    "ganghwa": 3.30,
    "garorim": 2.85,
    "gomso": 2.80,
    "hampyeong": 2.20,
    "suncheon": 1.45,
}


def apply_bias_correction(
    scenes: pd.DataFrame,
    site_id: str,
    beta: float = BETA_DEFAULT,
    amplitude_m: float | None = None,
    tide_col: str = "tide_m",
    cos_col: str = "cos_theta",
    out_col: str = "tide_corrected_m",
) -> pd.DataFrame:
    """Add a column with the per-scene bias-corrected tide.

    ``η_corr = η_raw − β · A · cos θ``

    Parameters
    ----------
    scenes
        DataFrame with at least ``tide_col`` and ``cos_col``.
    site_id
        Used to look up the default site amplitude (``SITE_AMPLITUDE_M``).
    beta
        Slope coefficient from the manuscript regression (default 1.78).
    amplitude_m
        Override the per-site amplitude (m). If ``None``, looked up.
    """
    out = scenes.copy()
    A = amplitude_m if amplitude_m is not None else SITE_AMPLITUDE_M.get(site_id)
    if A is None:
        raise ValueError(f"No amplitude registered for site_id={site_id!r}")
    out[out_col] = out[tide_col] - beta * A * out[cos_col]
    return out


# ---------------------------------------------------------------------------
# GEE-side DEM synthesis
# ---------------------------------------------------------------------------

@dataclass
class DemBuildSpec:
    """Inputs for one DEM build.

    Attributes
    ----------
    site_id
        Site identifier (e.g. ``"garorim"``).
    geometry
        Site analysis bbox (``ee.Geometry``).
    sensors
        Sensor IDs to include (subset of ``{"L8","L9","S2","S1"}``).
    scenes
        DataFrame with per-scene metadata. Must have columns
        ``sensor``, ``scene_id``, ``datetime_utc`` and either
        ``tide_m`` (V1, V2) or ``tide_corrected_m`` (V3, V4).
    tide_col
        Column with the per-scene tide height to use as elevation stamp.
    start, end
        Date range for the GEE collection filter.
    cloud_max
        Cloud cover threshold (% for optical; ignored for S1).
    output_scale_m
        Final DEM pixel size (default 10).
    """

    site_id: str
    geometry: ee.Geometry
    sensors: Sequence[str]
    scenes: pd.DataFrame
    tide_col: str = "tide_m"
    start: str = "2020-01-01"
    end: str = "2024-12-31"
    cloud_max: float = 60.0
    output_scale_m: int = 10


def compute_global_otsu(
    sensor: str,
    geometry: ee.Geometry,
    start: str,
    end: str,
    cloud_max: float = 30.0,
    n_samples: int = 20,
) -> float | None:
    """Compute a single Otsu threshold from a composite of representative scenes.

    Instead of running Otsu per-scene (O(N) getInfo calls), this samples
    a handful of low-cloud scenes, builds a median composite, and derives
    one global threshold.  Returns None if the histogram is degenerate.
    """
    from .waterline import (
        _compute_otsu,
        NATIVE_SCALE_M,
        filter_collection as _fc,
    )

    coll = _fc(sensor, geometry, start, end, cloud_max=cloud_max)
    coll = coll.limit(n_samples, "system:time_start")

    if sensor in ("L8", "L9"):
        green_key, swir_key = "SR_B3", "SR_B6"

        def _mndwi(img):
            g = img.select(green_key).multiply(2.75e-5).add(-0.2)
            s = img.select(swir_key).multiply(2.75e-5).add(-0.2)
            return g.subtract(s).divide(g.add(s)).rename("MNDWI")

        composite = coll.map(_mndwi).median()
    elif sensor == "S2":
        def _mndwi_s2(img):
            g = img.select("B3").divide(10000.0)
            s = img.select("B11").divide(10000.0)
            return g.subtract(s).divide(g.add(s)).rename("MNDWI")

        composite = coll.map(_mndwi_s2).median()
    elif sensor == "S1":
        composite = coll.select("VV").median()
    else:
        return None

    scale = NATIVE_SCALE_M.get(sensor, 30)
    if sensor == "S1":
        thr, _ = _compute_otsu(composite, geometry, scale, -25.0, -10.0)
    else:
        thr, _ = _compute_otsu(composite, geometry, scale, -0.6, 0.6)

    if thr is not None:
        log.info("Global Otsu for %s: %.4f", sensor, thr)
    else:
        log.warning("Global Otsu failed for %s; using default threshold", sensor)
    return thr


def _make_server_side_mapper(
    sensor: str,
    geometry: ee.Geometry,
    tide_dict: ee.Dictionary,
    id_prop: str,
    mndwi_threshold: float = 0.0,
    sar_threshold_db: float = -17.0,
):
    """Return a GEE-side .map() function for one sensor.

    The returned function takes an ``ee.Image``, computes a binary water
    mask using a *fixed* threshold (no Otsu — avoids per-scene getInfo),
    looks up the scene's tide height from ``tide_dict``, and returns a
    4-band image ``[land_tide, water_tide, n_obs, n_water]``.
    """

    def _mapper(image):
        image = ee.Image(image).clip(geometry)
        scene_id = image.get(id_prop)
        tide_val = ee.Number(tide_dict.get(scene_id, -9999))
        has_tide = tide_val.neq(-9999)

        if sensor in ("L8", "L9"):
            qa = image.select("QA_PIXEL")
            bad = (
                qa.bitwiseAnd(1 << 3).neq(0)
                .Or(qa.bitwiseAnd(1 << 4).neq(0))
                .Or(qa.bitwiseAnd(1 << 5).neq(0))
                .Or(qa.bitwiseAnd(1 << 1).neq(0))
            )
            clear = bad.Not()
            green = image.select("SR_B3").multiply(2.75e-5).add(-0.2)
            swir1 = image.select("SR_B6").multiply(2.75e-5).add(-0.2)
            idx = green.subtract(swir1).divide(green.add(swir1))
            water = idx.gte(mndwi_threshold).updateMask(clear)
        elif sensor == "S2":
            scl = image.select("SCL")
            bad = scl.eq(0).Or(scl.eq(1)).Or(scl.eq(3)).Or(scl.gte(8))
            clear = bad.Not()
            green = image.select("B3").divide(10000.0)
            swir1 = image.select("B11").divide(10000.0)
            idx = green.subtract(swir1).divide(green.add(swir1))
            water = idx.gte(mndwi_threshold).updateMask(clear)
        else:
            vv = image.select("VV")
            vv = vv.reduceNeighborhood(
                reducer=ee.Reducer.mean(),
                kernel=ee.Kernel.square(radius=2, units="pixels"),
            ).rename("VV")
            water = vv.lt(sar_threshold_db)

        valid = water.mask()
        tide_img = ee.Image.constant(tide_val)
        land_tide = tide_img.updateMask(water.eq(0).And(valid)).rename("land_tide")
        water_tide = tide_img.updateMask(water.eq(1).And(valid)).rename("water_tide")
        n_obs = ee.Image.constant(1).updateMask(valid).rename("n_obs")
        n_water = water.eq(1).updateMask(valid).rename("n_water")

        out = (
            land_tide.addBands(water_tide)
            .addBands(n_obs)
            .addBands(n_water)
            .toFloat()
        )
        return ee.Algorithms.If(has_tide, out, ee.Image.constant([0, 0, 0, 0]).selfMask())

    return _mapper


def _jrc_intertidal_mask(geometry: ee.Geometry) -> ee.Image:
    """Return a binary mask where 1 = likely intertidal (JRC occurrence 5-95%)."""
    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    return gsw.gte(5).And(gsw.lte(95)).clip(geometry).rename("intertidal")


def build_dem_gee(
    spec: DemBuildSpec,
    use_otsu: bool = False,
    return_diagnostics: bool = False,
    mndwi_threshold: float = 0.0,
    sar_threshold_db: float = -17.0,
    batch_size: int = 500,
    apply_jrc_mask: bool = True,
) -> tuple[ee.Image, pd.DataFrame]:
    """Build a multi-sensor DEM entirely server-side (zero getInfo calls).

    The key idea: per-scene tide heights are uploaded as an
    ``ee.Dictionary`` keyed by scene-id, and a ``.map()`` function
    attaches the tide value and computes a fixed-threshold water mask
    in a single pass. The whole collection is then reduced with
    ``ee.Reducer.max / min / sum`` to produce the DEM.

    For collections > ``batch_size`` scenes, processing is split into
    batches that are reduced separately and then merged, to stay within
    GEE's computation graph limits.

    Output bands
    ------------
    - ``dem_m``               Per-pixel waterline DEM elevation (m).
    - ``max_land_tide``       Highest tide at which the pixel was dry.
    - ``min_water_tide``      Lowest tide at which the pixel was wet.
    - ``n_obs``               Number of valid observations.
    - ``inundation_frequency`` Fraction of valid obs that were water.

    Parameters
    ----------
    use_otsu
        If True, compute a global Otsu threshold from a median composite
        (1 getInfo call per sensor) and override the fixed defaults.
    mndwi_threshold
        Fixed MNDWI threshold for optical sensors (default 0.0).
    sar_threshold_db
        Fixed sigma0 VV threshold for SAR (default -17 dB).
    batch_size
        Max scenes per GEE reduce batch.
    apply_jrc_mask
        If True, mask the final DEM to JRC Global Surface Water
        intertidal zone (occurrence 5-95%).
    """
    scenes = spec.scenes.copy()
    if spec.tide_col not in scenes.columns:
        raise KeyError(f"tide_col {spec.tide_col!r} missing from spec.scenes")
    scenes = scenes[scenes["sensor"].isin(spec.sensors)]
    scenes = scenes.dropna(subset=[spec.tide_col])
    # Pre-filter optical scenes by cloud cover at DataFrame level.
    optical_mask = scenes["sensor"].isin(["L8", "L9", "S2"])
    cloud_ok = scenes["cloud_cover"].fillna(0) <= spec.cloud_max
    scenes = scenes[~optical_mask | cloud_ok].copy()
    if scenes.empty:
        raise ValueError(f"No scenes after filtering on sensors={spec.sensors}")

    log.info(
        "build_dem_gee: site=%s sensors=%s n_scenes=%d tide_col=%s",
        spec.site_id, list(spec.sensors), len(scenes), spec.tide_col,
    )

    # Pre-compute global Otsu thresholds (1 getInfo per sensor).
    if use_otsu:
        for s in spec.sensors:
            thr = compute_global_otsu(
                s, spec.geometry, spec.start, spec.end,
                cloud_max=min(spec.cloud_max, 30.0),
            )
            if thr is not None:
                if s in ("L8", "L9", "S2"):
                    mndwi_threshold = thr
                elif s == "S1":
                    sar_threshold_db = thr

    diagnostics: list[dict] = []
    batch_reduced_images: list[ee.Image] = []

    for sensor in spec.sensors:
        sub = scenes[scenes["sensor"] == sensor]
        if sub.empty:
            continue

        id_prop = (
            "LANDSAT_PRODUCT_ID" if sensor in ("L8", "L9")
            else "PRODUCT_ID" if sensor == "S2"
            else "system:index"
        )

        tide_lookup: dict[str, float] = dict(
            zip(sub["scene_id"].astype(str), sub[spec.tide_col].astype(float))
        )
        # Remove non-finite tides.
        tide_lookup = {k: v for k, v in tide_lookup.items() if np.isfinite(v)}
        if not tide_lookup:
            continue
        scene_ids = list(tide_lookup)

        log.info(
            "  sensor=%s n_scenes=%d (sending %d tide entries to GEE)",
            sensor, len(sub), len(scene_ids),
        )

        coll = filter_collection(
            sensor, spec.geometry, spec.start, spec.end, cloud_max=spec.cloud_max
        )

        # Build mapper.
        ee_tide_dict = ee.Dictionary(tide_lookup)
        mapper = _make_server_side_mapper(
            sensor, spec.geometry, ee_tide_dict, id_prop,
            mndwi_threshold=mndwi_threshold,
            sar_threshold_db=sar_threshold_db,
        )

        # Process in batches to avoid GEE computation-graph limits.
        for batch_start in range(0, len(scene_ids), batch_size):
            batch_ids = scene_ids[batch_start : batch_start + batch_size]
            batch_coll = coll.filter(ee.Filter.inList(id_prop, batch_ids))
            mapped = batch_coll.map(mapper)
            max_land = mapped.select("land_tide").reduce(ee.Reducer.max()).rename("max_land_tide")
            min_water = mapped.select("water_tide").reduce(ee.Reducer.min()).rename("min_water_tide")
            n_obs = mapped.select("n_obs").reduce(ee.Reducer.sum()).rename("n_obs")
            n_water = mapped.select("n_water").reduce(ee.Reducer.sum()).rename("n_water")
            batch_reduced_images.append(
                max_land.addBands(min_water).addBands(n_obs).addBands(n_water)
            )

        for sid, tv in tide_lookup.items():
            diagnostics.append({
                "sensor": sensor, "scene_id": sid, "tide_m": tv,
                "threshold": mndwi_threshold if sensor != "S1" else sar_threshold_db,
                "method": "fixed",
                "n_valid_pixels": None,
            })

    if not batch_reduced_images:
        raise RuntimeError("No usable sensor collections produced any images")

    # Merge all per-sensor, per-batch partial reductions.
    merged = ee.ImageCollection.fromImages(batch_reduced_images)
    max_land = merged.select("max_land_tide").reduce(ee.Reducer.max()).rename("max_land_tide")
    min_water = merged.select("min_water_tide").reduce(ee.Reducer.min()).rename("min_water_tide")
    n_obs = merged.select("n_obs").reduce(ee.Reducer.sum()).rename("n_obs")
    n_water = merged.select("n_water").reduce(ee.Reducer.sum()).rename("n_water")
    inundation = n_water.divide(n_obs).rename("inundation_frequency")
    dem = max_land.add(min_water).divide(2).rename("dem_m")

    out = (
        dem.addBands(max_land)
        .addBands(min_water)
        .addBands(n_obs)
        .addBands(inundation)
        .toFloat()
        .clip(spec.geometry)
    )

    if apply_jrc_mask:
        jrc = _jrc_intertidal_mask(spec.geometry)
        out = out.updateMask(jrc)

    diag_df = pd.DataFrame(diagnostics)
    if return_diagnostics:
        return out, diag_df
    return out, diag_df


# ---------------------------------------------------------------------------
# Local fallback synthesis (streaming over disk-resident per-scene masks)
# ---------------------------------------------------------------------------

def build_dem_local_stream(
    mask_paths: Iterable[Path],
    tides_m: Iterable[float],
    out_path: Path,
    nodata: float = np.nan,
) -> Path:
    """Compute DEM from a directory of per-scene binary mask GeoTIFFs.

    Loops scene-by-scene to keep memory at ~2 × raster size. Each input
    GeoTIFF must be a single-band uint8 mask aligned to a common grid
    (1 = water, 0 = land, nodata = masked).

    Output GeoTIFF has bands [dem_m, n_obs, inundation_frequency].
    """
    try:
        import rasterio
        from rasterio.errors import RasterioIOError
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("rasterio is required for local DEM streaming") from exc

    mask_paths = list(mask_paths)
    tides_m = np.asarray(list(tides_m), dtype=np.float32)
    if len(mask_paths) != len(tides_m):
        raise ValueError("mask_paths and tides_m must have equal length")
    if not mask_paths:
        raise ValueError("no scene masks supplied")

    # Read the first to establish the grid.
    try:
        with rasterio.open(mask_paths[0]) as src0:
            profile = src0.profile.copy()
            height, width = src0.height, src0.width
            crs = src0.crs
            transform = src0.transform
    except RasterioIOError as exc:  # pragma: no cover
        raise RuntimeError(f"Could not open {mask_paths[0]}") from exc

    max_land = np.full((height, width), -np.inf, dtype=np.float32)
    min_water = np.full((height, width), +np.inf, dtype=np.float32)
    n_obs = np.zeros((height, width), dtype=np.int32)
    n_water = np.zeros((height, width), dtype=np.int32)

    for path, tide in zip(mask_paths, tides_m):
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True)  # masked array
        valid = ~arr.mask
        n_obs[valid] += 1
        water = arr.filled(0).astype(bool) & valid
        n_water[water] += 1
        # max_land update
        land = (~water) & valid
        max_land[land] = np.maximum(max_land[land], tide)
        # min_water update
        min_water[water] = np.minimum(min_water[water], tide)

    has_land = np.isfinite(max_land)
    has_water = np.isfinite(min_water)
    intertidal = has_land & has_water
    dem = np.full((height, width), nodata, dtype=np.float32)
    dem[intertidal] = (max_land[intertidal] + min_water[intertidal]) / 2.0

    with np.errstate(divide="ignore", invalid="ignore"):
        inundation = np.where(n_obs > 0, n_water / n_obs, nodata)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(
        count=3,
        dtype="float32",
        nodata=nodata,
        compress="deflate",
        crs=crs,
        transform=transform,
    )
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(dem.astype(np.float32), 1)
        dst.write(n_obs.astype(np.float32), 2)
        dst.write(inundation.astype(np.float32), 3)
        dst.set_band_description(1, "dem_m")
        dst.set_band_description(2, "n_obs")
        dst.set_band_description(3, "inundation_frequency")
    log.info("Wrote DEM (%d × %d, %d scenes) → %s", height, width, len(mask_paths), out_path)
    return out_path


__all__ = [
    "BETA_DEFAULT",
    "SITE_AMPLITUDE_M",
    "apply_bias_correction",
    "DemBuildSpec",
    "build_dem_gee",
    "build_dem_local_stream",
    "collection_for_sensor",
]
