"""Extract scene-level metadata (acquisition times, cloud cover) from GEE.

The goal of this module is to produce, for each study site and sensor,
a tabular record of all available scenes with at least:

    - sensor id (e.g. L5, L7, L8, L9, S2)
    - scene id
    - acquisition datetime (UTC, ISO-8601)
    - cloud cover (%)
    - WRS path/row (Landsat) or MGRS tile (Sentinel-2)

No pixel data is downloaded: only metadata, which is cheap and avoids any
GEE compute quota concerns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import ee
import pandas as pd

from ..config import Site

log = logging.getLogger(__name__)


# Sensor-specific GEE metadata field mapping.
# Keep cloud_cover field name explicit since it differs across sensors.
SENSOR_SPECS: dict[str, dict[str, Any]] = {
    "L5": {
        "collection": "LANDSAT/LT05/C02/T1_L2",
        "cloud_field": "CLOUD_COVER",
        "id_field": "LANDSAT_PRODUCT_ID",
        "extra_fields": ["WRS_PATH", "WRS_ROW"],
    },
    "L7": {
        "collection": "LANDSAT/LE07/C02/T1_L2",
        "cloud_field": "CLOUD_COVER",
        "id_field": "LANDSAT_PRODUCT_ID",
        "extra_fields": ["WRS_PATH", "WRS_ROW"],
    },
    "L8": {
        "collection": "LANDSAT/LC08/C02/T1_L2",
        "cloud_field": "CLOUD_COVER",
        "id_field": "LANDSAT_PRODUCT_ID",
        "extra_fields": ["WRS_PATH", "WRS_ROW"],
    },
    "L9": {
        "collection": "LANDSAT/LC09/C02/T1_L2",
        "cloud_field": "CLOUD_COVER",
        "id_field": "LANDSAT_PRODUCT_ID",
        "extra_fields": ["WRS_PATH", "WRS_ROW"],
    },
    "S2": {
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "cloud_field": "CLOUDY_PIXEL_PERCENTAGE",
        "id_field": "PRODUCT_ID",
        "extra_fields": ["MGRS_TILE"],
    },
    # Sentinel-1 SAR (GRD, IW mode). Carries no cloud field; the value of
    # the optional ``cloud_field`` is set to ``None`` and downstream code
    # must populate the ``cloud_cover`` column with NaN. Filtering for
    # IW mode and VV polarisation is done inside ``_scenes_for_sensor``.
    "S1": {
        "collection": "COPERNICUS/S1_GRD",
        "cloud_field": None,
        "id_field": "system:index",
        "extra_fields": [
            "orbitProperties_pass",
            "instrumentMode",
            "transmitterReceiverPolarisation",
            "relativeOrbitNumber_start",
        ],
    },
}


@dataclass
class SceneRecord:
    site_id: str
    sensor: str
    scene_id: str
    datetime_utc: datetime
    cloud_cover: float
    extra: dict[str, Any]


def _bbox_geometry(bbox: list[float]) -> ee.Geometry:
    return ee.Geometry.Rectangle(bbox, proj="EPSG:4326", geodesic=False)


def _scenes_for_sensor(
    site: Site,
    sensor: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Return a DataFrame with one row per scene intersecting ``site`` bbox."""
    spec = SENSOR_SPECS[sensor]
    geom = _bbox_geometry(site.bbox)

    coll = (
        ee.ImageCollection(spec["collection"])
        .filterBounds(geom)
        .filterDate(start, end)
    )

    if sensor == "S1":
        # IW (Interferometric Wide) is the only routinely-acquired mode
        # over Korea; VV is the primary polarisation we care about for
        # water/land thresholding on tidal flats.
        coll = (
            coll.filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        )

    cloud_field = spec.get("cloud_field")
    fields = ["system:time_start", spec["id_field"]] + spec["extra_fields"]
    if cloud_field is not None:
        fields.insert(1, cloud_field)

    # GEE rejects toList(0); fetch the size first so we can short-circuit
    # empty collections (e.g. L9 over tiles in 2015 — before its launch).
    n_scenes = int(coll.size().getInfo() or 0)
    if n_scenes == 0:
        return pd.DataFrame(
            columns=["site_id", "sensor", "scene_id", "datetime_utc", "cloud_cover"]
            + [f.lower() for f in spec["extra_fields"]]
        )

    info = coll.toList(n_scenes).map(
        lambda img: ee.Image(img).toDictionary(fields)
    ).getInfo()

    if not info:
        return pd.DataFrame(
            columns=["site_id", "sensor", "scene_id", "datetime_utc", "cloud_cover"]
            + [f.lower() for f in spec["extra_fields"]]
        )

    rows: list[dict[str, Any]] = []
    for d in info:
        ts_ms = d.get("system:time_start")
        if ts_ms is None:
            continue
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        scene_id = d.get(spec["id_field"])
        if scene_id is None and sensor == "S1":
            # GEE's S1 collection lacks an explicit ID field — derive one
            # from acquisition time + relative orbit so dedup still works.
            rel = d.get("relativeOrbitNumber_start")
            scene_id = f"S1_{dt.strftime('%Y%m%dT%H%M%S')}_r{rel}"
        if cloud_field is not None:
            cc = float(d.get(cloud_field, float("nan")))
        else:
            cc = float("nan")
        row = {
            "site_id": site.id,
            "sensor": sensor,
            "scene_id": scene_id,
            "datetime_utc": dt,
            "cloud_cover": cc,
        }
        for f in spec["extra_fields"]:
            value = d.get(f)
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            row[f.lower()] = value
        rows.append(row)

    return pd.DataFrame(rows)


def extract_site_metadata(
    site: Site,
    sensors: Iterable[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Pull metadata for one site across all requested sensors."""
    frames: list[pd.DataFrame] = []
    for sensor in sensors:
        if sensor not in SENSOR_SPECS:
            log.warning("Unknown sensor %s, skipping", sensor)
            continue
        log.info("Querying %s for %s (%s - %s)", sensor, site.id, start, end)
        df = _scenes_for_sensor(site, sensor, start, end)
        log.info("  -> %d scenes", len(df))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("datetime_utc")


def save_metadata(df: pd.DataFrame, out_dir: Path, site_id: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{site_id}_scenes.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def extract_bbox_metadata(
    tile_id: str,
    bbox: list[float],
    sensors: Iterable[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Variant of ``extract_site_metadata`` that takes a raw bbox.

    Returns the same schema with ``site_id`` set to ``tile_id`` so the
    rest of the pipeline (build_dem_gee, bias correction) works
    unchanged.
    """
    # Construct a thin shim Site-like object: only ``id`` and ``bbox``
    # are used by ``_scenes_for_sensor``. Note: a class body is its own
    # scope, so referencing ``bbox`` on the right-hand side of an
    # assignment to ``bbox`` raises NameError. Bind to a local first.
    _tile_id = tile_id
    _bbox_list = list(bbox)

    class _T:
        id = _tile_id
        bbox = _bbox_list

    frames: list[pd.DataFrame] = []
    for sensor in sensors:
        if sensor not in SENSOR_SPECS:
            log.warning("Unknown sensor %s, skipping", sensor)
            continue
        log.info("Querying %s for tile %s (%s - %s)", sensor, tile_id, start, end)
        df = _scenes_for_sensor(_T(), sensor, start, end)  # type: ignore[arg-type]
        log.info("  -> %d scenes", len(df))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("datetime_utc")
