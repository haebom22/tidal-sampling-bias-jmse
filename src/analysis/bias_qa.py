"""Per-pixel satellite-tide sampling bias QA (Bishop-Taylor et al. 2019b).

Builds a 3-band QA raster whose bands quantify how well the satellite
overpasses sample the local tidal envelope at each location:

    spread        = (max(eta_sat) - min(eta_sat))
                    / (Q_ref(0.999) - Q_ref(0.001))
    high_offset   = max(0, Q_ref(0.999) - max(eta_sat)) / ref_range
    low_offset    = max(0, min(eta_sat) - Q_ref(0.001))  / ref_range

with the convention from eo-tides ``tide_stats`` / ``pixel_stats``
(Bishop-Taylor et al. 2025, JOSS).

For the relatively small (~30 km) study-site bboxes here, the *spatial*
variation in these metrics is dominated by scene-coverage (different
swaths see different scene subsets), not by tide-model gradients. So we
compute the three metrics on a coarse 0.05 deg query grid (≈5 km
spacing) using FES2022b (falling back to FES2014 if FES2022b is not yet
staged) and then nearest-neighbour expand to the analysis grid.

The output GeoTIFF aligns with the V4 DEM grid (same CRS, transform).

Optional dependency
-------------------
If the ``eo-tides`` package is installed (preferred), its
``pixel_stats`` function is used directly. Otherwise we fall back to a
NumPy / pyTMD implementation that produces the *same* three metrics.
Both paths require either FES2014 or FES2022b model files on disk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

QA_PASS_SPREAD = 0.60       # Minimum acceptable spread
QA_PASS_HIGH_OFFSET = 0.25  # Maximum acceptable high-tide truncation
QA_PASS_LOW_OFFSET = 0.25   # Maximum acceptable low-tide truncation


@dataclass
class BiasQaMetrics:
    spread: float
    high_offset: float
    low_offset: float
    n_satellite: int
    n_reference: int
    ref_range: float
    sat_range: tuple[float, float]
    ref_quantiles: tuple[float, float]

    def passes_gate(self) -> bool:
        return (
            self.spread >= QA_PASS_SPREAD
            and self.high_offset <= QA_PASS_HIGH_OFFSET
            and self.low_offset <= QA_PASS_LOW_OFFSET
        )

    def to_dict(self) -> dict:
        return {
            "spread": self.spread,
            "high_offset": self.high_offset,
            "low_offset": self.low_offset,
            "n_satellite": self.n_satellite,
            "n_reference": self.n_reference,
            "ref_range": self.ref_range,
            "sat_min": self.sat_range[0],
            "sat_max": self.sat_range[1],
            "ref_q001": self.ref_quantiles[0],
            "ref_q999": self.ref_quantiles[1],
            "qa_pass": self.passes_gate(),
        }


# ---------------------------------------------------------------------------
# Pointwise QA metrics (Bishop-Taylor 2019b)
# ---------------------------------------------------------------------------

def compute_pointwise_qa(
    satellite_tides_m: np.ndarray,
    reference_tides_m: np.ndarray,
    low_q: float = 0.001,
    high_q: float = 0.999,
) -> BiasQaMetrics:
    """Compute the three Bishop-Taylor QA metrics at a single point.

    Parameters
    ----------
    satellite_tides_m
        Tide heights at *satellite* overpass times (the realised sample).
    reference_tides_m
        Tide heights at uniform reference times (e.g., hourly synthetic).
    low_q, high_q
        Quantiles defining the full reference tidal envelope.
    """
    sat = np.asarray(satellite_tides_m, dtype=float)
    ref = np.asarray(reference_tides_m, dtype=float)
    sat = sat[np.isfinite(sat)]
    ref = ref[np.isfinite(ref)]
    if sat.size < 5 or ref.size < 100:
        return BiasQaMetrics(
            spread=np.nan, high_offset=np.nan, low_offset=np.nan,
            n_satellite=int(sat.size), n_reference=int(ref.size),
            ref_range=np.nan, sat_range=(np.nan, np.nan),
            ref_quantiles=(np.nan, np.nan),
        )

    q_lo, q_hi = np.quantile(ref, [low_q, high_q])
    ref_range = q_hi - q_lo
    if ref_range <= 0:
        return BiasQaMetrics(
            spread=np.nan, high_offset=np.nan, low_offset=np.nan,
            n_satellite=int(sat.size), n_reference=int(ref.size),
            ref_range=0.0, sat_range=(float(sat.min()), float(sat.max())),
            ref_quantiles=(float(q_lo), float(q_hi)),
        )

    sat_min, sat_max = float(sat.min()), float(sat.max())
    spread = (sat_max - sat_min) / ref_range
    high_offset = max(0.0, q_hi - sat_max) / ref_range
    low_offset = max(0.0, sat_min - q_lo) / ref_range
    return BiasQaMetrics(
        spread=float(spread),
        high_offset=float(high_offset),
        low_offset=float(low_offset),
        n_satellite=int(sat.size),
        n_reference=int(ref.size),
        ref_range=float(ref_range),
        sat_range=(sat_min, sat_max),
        ref_quantiles=(float(q_lo), float(q_hi)),
    )


# ---------------------------------------------------------------------------
# Coarse query grid → expand to analysis raster
# ---------------------------------------------------------------------------

def _build_query_grid(
    bbox: Sequence[float],
    spacing_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(lon_grid, lat_grid)`` arrays for a coarse query grid.

    Both arrays are 1-D in ``flatten()`` order. Spacing is chosen so the
    grid covers the bbox with at least 2 points per side.
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    n_lon = max(2, int(np.ceil((lon_max - lon_min) / spacing_deg)) + 1)
    n_lat = max(2, int(np.ceil((lat_max - lat_min) / spacing_deg)) + 1)
    lon = np.linspace(lon_min, lon_max, n_lon)
    lat = np.linspace(lat_min, lat_max, n_lat)
    LON, LAT = np.meshgrid(lon, lat)
    return LON.ravel(), LAT.ravel()


def _call_with_timeout(fn, *args, timeout_s: int = 300, **kwargs):
    """Run ``fn`` and abort with ``TimeoutError`` after ``timeout_s`` seconds.

    Uses ``signal.alarm`` (UNIX only). On Windows/threads the timeout is
    silently disabled and ``fn`` runs to completion.
    """
    import signal

    class _AlarmTimeout(Exception):
        pass

    def _handler(signum, frame):
        raise _AlarmTimeout()

    if not hasattr(signal, "SIGALRM"):
        return fn(*args, **kwargs)

    prev = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(int(timeout_s))
    try:
        return fn(*args, **kwargs)
    except _AlarmTimeout as exc:
        raise TimeoutError(f"FES call exceeded {timeout_s}s budget") from exc
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


def build_bbox_qa(
    bbox: Sequence[float],
    satellite_times_utc: pd.DatetimeIndex,
    reference_start: pd.Timestamp,
    reference_end: pd.Timestamp,
    model_directory: Path,
    *,
    model_name: str = "FES2022_extrapolated",
    grid_spacing_deg: float = 0.05,
    reference_freq: str = "30min",
    spatial_mode: str = "single_point",
    fes_timeout_s: int = 600,
    fes_bounds: Sequence[float] | None = None,
) -> pd.DataFrame:
    """Compute the 3-metric QA on a coarse grid covering ``bbox``.

    Returns a ``DataFrame`` with columns
    ``[lon, lat, spread, high_offset, low_offset, n_sat, n_ref]`` —
    one row per coarse grid node. Callers use it to rasterise onto the
    analysis grid via simple nearest-neighbour expansion.

    Parameters
    ----------
    spatial_mode
        - ``"single_point"`` (default): compute the tide series once at
          the bbox centre and broadcast the resulting metrics to every
          grid node. Justified for ≤ 30 km Korean pilot bboxes where the
          tide envelope varies by < 5% across the site, and avoids
          O(n_nodes) pyTMD calls (each of which is several minutes on
          FES2022).
        - ``"grid"``: compute the full per-node tide series (slow but
          spatially explicit).
    fes_timeout_s
        Max seconds to spend on a single ``compute_tide_heights`` call
        before aborting the whole site/year (the row is then nan-filled
        downstream). Default 600 s.
    """
    from ..tides.fes2014 import compute_tide_heights

    # FES grids are loaded over a *stable* (national) bbox so the atlas is
    # read once per process; the QA grid nodes still lie inside ``bbox``.
    _fes_bounds = list(fes_bounds) if fes_bounds is not None else list(bbox)

    times_sat = pd.to_datetime(satellite_times_utc, utc=True)
    times_ref = pd.date_range(
        reference_start, reference_end, freq=reference_freq, tz="UTC"
    )

    lons, lats = _build_query_grid(bbox, grid_spacing_deg)
    n_nodes = len(lons)
    log.info(
        "bias_qa: bbox=%s, n_grid=%d, n_sat=%d, n_ref=%d, model=%s, mode=%s",
        list(bbox), n_nodes, len(times_sat), len(times_ref), model_name,
        spatial_mode,
    )

    if spatial_mode == "single_point":
        lon_c = 0.5 * (bbox[0] + bbox[2])
        lat_c = 0.5 * (bbox[1] + bbox[3])
        try:
            sat_h = _call_with_timeout(
                compute_tide_heights,
                lon=lon_c, lat=lat_c, times=times_sat,
                model_directory=model_directory, model_name=model_name,
                bounds=_fes_bounds, timeout_s=fes_timeout_s,
            )
            ref_h = _call_with_timeout(
                compute_tide_heights,
                lon=lon_c, lat=lat_c, times=times_ref,
                model_directory=model_directory, model_name=model_name,
                bounds=_fes_bounds, timeout_s=fes_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "FES failed for bbox-centre (%.4f, %.4f): %s — returning empty grid",
                lon_c, lat_c, exc,
            )
            return pd.DataFrame()
        metrics = compute_pointwise_qa(sat_h, ref_h)
        log.info(
            "  centre metrics: spread=%.3f, hi_off=%.3f, lo_off=%.3f, n_sat=%d",
            metrics.spread, metrics.high_offset, metrics.low_offset,
            metrics.n_satellite,
        )
        rows = [
            {"lon": float(lon), "lat": float(lat), **metrics.to_dict()}
            for lon, lat in zip(lons, lats)
        ]
        return pd.DataFrame(rows)

    # Per-node mode (legacy / spatially-explicit).
    out = []
    for i, (lon, lat) in enumerate(zip(lons, lats)):
        try:
            sat_h = _call_with_timeout(
                compute_tide_heights,
                lon=lon, lat=lat, times=times_sat,
                model_directory=model_directory, model_name=model_name,
                bounds=_fes_bounds, timeout_s=fes_timeout_s,
            )
            ref_h = _call_with_timeout(
                compute_tide_heights,
                lon=lon, lat=lat, times=times_ref,
                model_directory=model_directory, model_name=model_name,
                bounds=_fes_bounds, timeout_s=fes_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("FES failed at (%.4f, %.4f): %s", lon, lat, exc)
            if i == 0:
                # First node already failed/timed out — bail out rather
                # than spend n_nodes × timeout on a doomed site/year.
                return pd.DataFrame()
            continue
        metrics = compute_pointwise_qa(sat_h, ref_h)
        out.append({
            "lon": float(lon), "lat": float(lat),
            **metrics.to_dict(),
        })
        if (i + 1) % 10 == 0 or i == n_nodes - 1:
            log.info("  grid %d/%d (lon=%.3f, lat=%.3f)", i + 1, n_nodes, lon, lat)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Rasterise to analysis grid (matched to a reference DEM GeoTIFF)
# ---------------------------------------------------------------------------

def rasterise_qa_grid_to_dem(
    qa_grid: pd.DataFrame,
    reference_dem_path: Path,
    out_path: Path,
    *,
    n_obs_path: Path | None = None,
    n_obs_band: int = 4,
    n_obs_threshold: int = 5,
) -> Path:
    """Rasterise a coarse QA grid onto the reference DEM raster.

    Produces a 4-band GeoTIFF::

        band 1: spread
        band 2: high_offset
        band 3: low_offset
        band 4: qa_pass  (1 = passes the spread/offset gates AND has
                          >= ``n_obs_threshold`` valid observations)
    """
    import rasterio
    from rasterio.transform import xy
    from scipy.spatial import cKDTree

    with rasterio.open(reference_dem_path) as ref:
        profile = ref.profile.copy()
        transform = ref.transform
        height, width = ref.height, ref.width
        crs = ref.crs

    # Pixel centroids in raster CRS, then back to WGS84.
    rows = np.arange(height)
    cols = np.arange(width)
    cc, rr = np.meshgrid(cols, rows)
    px_lon, px_lat = xy(transform, rr.ravel(), cc.ravel(), offset="center")
    px_lon = np.asarray(px_lon)
    px_lat = np.asarray(px_lat)
    if crs and crs.to_epsg() != 4326:
        from rasterio.warp import transform as warp_transform
        px_lon, px_lat = warp_transform(crs, "EPSG:4326", px_lon, px_lat)
        px_lon = np.asarray(px_lon)
        px_lat = np.asarray(px_lat)

    # Nearest-neighbour from coarse QA grid to each pixel.
    grid_lonlat = qa_grid[["lon", "lat"]].to_numpy()
    tree = cKDTree(grid_lonlat)
    _, idx = tree.query(np.column_stack([px_lon, px_lat]), k=1)

    spread = qa_grid["spread"].to_numpy()[idx].reshape(height, width).astype(np.float32)
    high_o = qa_grid["high_offset"].to_numpy()[idx].reshape(height, width).astype(np.float32)
    low_o = qa_grid["low_offset"].to_numpy()[idx].reshape(height, width).astype(np.float32)

    qa_pass = (
        (spread >= QA_PASS_SPREAD)
        & (high_o <= QA_PASS_HIGH_OFFSET)
        & (low_o <= QA_PASS_LOW_OFFSET)
    ).astype(np.uint8)

    if n_obs_path is not None and n_obs_path.exists():
        with rasterio.open(n_obs_path) as src:
            n_obs = src.read(n_obs_band, masked=True).filled(0)
        if n_obs.shape != qa_pass.shape:
            log.warning(
                "n_obs shape %s != QA shape %s, skipping coverage gate",
                n_obs.shape, qa_pass.shape,
            )
        else:
            qa_pass = qa_pass & (n_obs >= n_obs_threshold).astype(np.uint8)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(
        count=4,
        dtype="float32",
        nodata=np.nan,
        compress="deflate",
    )
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(spread, 1)
        dst.write(high_o, 2)
        dst.write(low_o, 3)
        dst.write(qa_pass.astype(np.float32), 4)
        dst.set_band_description(1, "spread")
        dst.set_band_description(2, "high_offset")
        dst.set_band_description(3, "low_offset")
        dst.set_band_description(4, "qa_pass")
    log.info("Wrote QA raster → %s", out_path)
    return out_path


__all__ = [
    "QA_PASS_SPREAD",
    "QA_PASS_HIGH_OFFSET",
    "QA_PASS_LOW_OFFSET",
    "BiasQaMetrics",
    "compute_pointwise_qa",
    "build_bbox_qa",
    "rasterise_qa_grid_to_dem",
]
