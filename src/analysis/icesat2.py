"""ICESat-2 ATL03 ground photon extraction for intertidal DEM validation.

Uses the SlideRule Earth service (slideruleearth.io) for server-side ATL03
processing, avoiding large HDF5 downloads. The pipeline:

1. Query ATL03 granules intersecting each site bbox.
2. Extract signal photons (confidence >= 2) classified as ground.
3. Attach interpolated tide level at photon overpass time.
4. Filter to "exposed" photons (tide < photon elevation + buffer).
5. Return a GeoDataFrame suitable for DEM cross-validation.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

log = logging.getLogger(__name__)


def query_atl03_photons(
    bbox: list[float],
    start_date: str = "2019-01-01",
    end_date: str = "2025-12-31",
    min_confidence: int = 2,
) -> gpd.GeoDataFrame:
    """Query and extract ATL06-SR ground segments via SlideRule.

    Parameters
    ----------
    bbox
        [min_lon, min_lat, max_lon, max_lat]
    start_date, end_date
        Temporal range (ISO format).
    min_confidence
        Minimum signal_conf_ph (0-4). Default 2 = low confidence.

    Returns
    -------
    GeoDataFrame with columns including h_mean, time, geometry (Point).
    """
    from sliderule import sliderule, icesat2

    sliderule.init("slideruleearth.io", verbose=False)

    region = box(*bbox)
    poly = [{"lon": x, "lat": y} for x, y in region.exterior.coords]

    params = {
        "poly": poly,
        "t0": start_date,
        "t1": end_date,
        "srt": icesat2.SRT_LAND,
        "cnf": min_confidence,
        "len": 40,
        "res": 20,
    }

    log.info(
        "SlideRule ATL06-SR query: bbox=%s, %s → %s",
        bbox, start_date, end_date,
    )
    gdf = icesat2.atl06p(params)

    if gdf.empty:
        log.warning("No ATL06-SR data returned for bbox=%s", bbox)
        return gpd.GeoDataFrame(
            columns=["lon", "lat", "h_mean", "time", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    gdf = gdf.reset_index()
    if "geometry" not in gdf.columns:
        from shapely.geometry import Point
        gdf["geometry"] = [
            Point(row.get("lon", row.get("longitude", 0)),
                  row.get("lat", row.get("latitude", 0)))
            for _, row in gdf.iterrows()
        ]
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")

    log.info("Retrieved %d ATL06-SR segments", len(gdf))
    return gdf


def query_atl03_raw(
    bbox: list[float],
    start_date: str = "2019-01-01",
    end_date: str = "2025-12-31",
    min_confidence: int = 2,
) -> gpd.GeoDataFrame:
    """Query raw ATL03 photons via SlideRule atl03sp.

    Returns individual photon-level data with heights.
    """
    from sliderule import sliderule, icesat2

    sliderule.init("slideruleearth.io", verbose=False)

    region = box(*bbox)
    poly = [{"lon": x, "lat": y} for x, y in region.exterior.coords]

    params = {
        "poly": poly,
        "t0": start_date,
        "t1": end_date,
        "srt": icesat2.SRT_LAND,
        "cnf": min_confidence,
        "pass_invalid": False,
        "yapc": {"score": 0},
    }

    log.info(
        "SlideRule ATL03 photon query: bbox=%s, %s → %s",
        bbox, start_date, end_date,
    )
    gdf = icesat2.atl03sp(params)

    if gdf.empty:
        log.warning("No ATL03 photons returned for bbox=%s", bbox)
        return gpd.GeoDataFrame(
            columns=["lon", "lat", "height", "time", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    gdf = gdf.reset_index()
    log.info("Retrieved %d ATL03 photons", len(gdf))
    return gdf


def attach_tide_level(
    photons: gpd.GeoDataFrame,
    khoa_hourly: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Interpolate KHOA tide level at each photon's overpass time.

    Parameters
    ----------
    photons
        GeoDataFrame with a datetime index or 'time' column.
    khoa_hourly
        KHOA hourly tide data with 'datetime_utc' and 'level_m' columns.
    """
    from src.tides.khoa import interpolate_at_times

    if photons.empty:
        photons["tide_m"] = np.nan
        return photons

    out = photons.copy()
    if "time" in out.columns:
        times = pd.to_datetime(out["time"], utc=True)
    elif out.index.name == "time":
        times = pd.to_datetime(out.index, utc=True)
    else:
        times = pd.to_datetime(out.index, utc=True)

    times = times.astype("datetime64[us, UTC]")
    out["tide_m"] = interpolate_at_times(khoa_hourly, times).values
    return out


def filter_exposed_photons(
    photons: gpd.GeoDataFrame,
    height_col: str = "h_mean",
    tide_col: str = "tide_m",
    buffer_m: float = 0.2,
) -> gpd.GeoDataFrame:
    """Keep only photons that were exposed (above tide level) at overpass time.

    A photon is "exposed" if its elevation exceeds the tide level by at least
    ``buffer_m``. This ensures only ground surface points (not submerged
    seafloor returns) are used for DEM validation.
    """
    if photons.empty:
        return photons
    mask = photons[height_col] > (photons[tide_col] + buffer_m)
    exposed = photons[mask].copy()
    log.info(
        "Exposed filter: %d / %d photons retained (buffer=%.2f m)",
        len(exposed), len(photons), buffer_m,
    )
    return exposed


def extract_site_photons(
    site_id: str,
    bbox: list[float],
    khoa_hourly: pd.DataFrame,
    start_date: str = "2019-01-01",
    end_date: str = "2025-12-31",
    out_dir: Path | None = None,
) -> gpd.GeoDataFrame:
    """End-to-end pipeline: query → tide attach → exposure filter → save.

    Parameters
    ----------
    site_id
        Site identifier for file naming.
    bbox
        [min_lon, min_lat, max_lon, max_lat].
    khoa_hourly
        KHOA hourly tide DataFrame.
    start_date, end_date
        Temporal range.
    out_dir
        If provided, saves result as GeoParquet.

    Returns
    -------
    GeoDataFrame of exposed ground photons.
    """
    gdf = query_atl03_photons(bbox, start_date, end_date)
    if gdf.empty:
        log.warning("No ICESat-2 data for %s", site_id)
        return gdf

    gdf = attach_tide_level(gdf, khoa_hourly)
    exposed = filter_exposed_photons(gdf)

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{site_id}_icesat2_exposed.parquet"
        exposed.to_parquet(out_path)
        log.info("Saved %d exposed photons → %s", len(exposed), out_path)

    return exposed
