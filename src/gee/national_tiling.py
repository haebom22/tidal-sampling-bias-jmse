"""Coastal tiling for national-scale tidal-flat extent mapping.

Generates a list of ≈0.3° × 0.3° tiles (≈25 × 25 km) covering the
Korean west and south coast with two filtering steps:

1. **Coastal buffer**: keep only tiles that intersect a 30-km buffer
   around the GSHHG f-resolution coastline.
2. **JRC tidal-flat presence**: keep only tiles where at least
   ``min_intertidal_pixels`` pixels in JRC GSW Global Surface Water
   v1.4 have ``occurrence`` between 5 % and 95 %.

The resulting list is written to ``config/national_tiles.yaml`` (or
returned in memory) for the national pipeline driver.

Tile schema
-----------
::

    tiles:
      - id: "K_125_36"
        bbox: [125.0, 36.0, 125.3, 36.3]
        center: { lon: 125.15, lat: 36.15 }
        n_intertidal_pixels: 12345
        region_hint: "Yellow Sea, west of Taean"
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import ee
import yaml

log = logging.getLogger(__name__)


DEFAULT_BBOX = [124.0, 33.0, 130.5, 39.5]
DEFAULT_TILE_SIZE_DEG = 0.3
DEFAULT_BUFFER_M = 30_000   # coastal buffer
DEFAULT_MIN_PIXELS = 1_000  # ≈ 1 km² in 30 m pixels


@dataclass
class CoastalTile:
    id: str
    bbox: list[float]
    center: dict[str, float]
    n_intertidal_pixels: int
    region_hint: str | None = None

    def geometry(self) -> ee.Geometry:
        return ee.Geometry.Rectangle(self.bbox, proj="EPSG:4326", geodesic=False)


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------

def _tile_id(lon: float, lat: float) -> str:
    return f"K_{int(lon * 10):04d}_{int(lat * 10):04d}"


def candidate_tiles(
    overall_bbox: Sequence[float] = DEFAULT_BBOX,
    tile_size_deg: float = DEFAULT_TILE_SIZE_DEG,
) -> list[dict]:
    """Generate the raw 0.3-deg grid covering ``overall_bbox``.

    Returns a list of dicts with ``id``, ``bbox``, ``center``. Filtering
    is the caller's responsibility.
    """
    lon_min, lat_min, lon_max, lat_max = overall_bbox
    tiles = []
    lon = lon_min
    while lon < lon_max:
        lat = lat_min
        while lat < lat_max:
            bbox = [lon, lat, lon + tile_size_deg, lat + tile_size_deg]
            tiles.append({
                "id": _tile_id(lon, lat),
                "bbox": bbox,
                "center": {
                    "lon": float(lon + tile_size_deg / 2),
                    "lat": float(lat + tile_size_deg / 2),
                },
            })
            lat = round(lat + tile_size_deg, 4)
        lon = round(lon + tile_size_deg, 4)
    return tiles


def filter_coastal_with_intertidal(
    tiles: list[dict],
    *,
    buffer_m: int = DEFAULT_BUFFER_M,
    min_intertidal_pixels: int = DEFAULT_MIN_PIXELS,
    scale_m: int = 30,
) -> list[CoastalTile]:
    """Filter candidate tiles by coastal proximity + JRC tidal-flat presence.

    Requires an initialised EE session (call ``initialize()`` first).
    """
    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    intertidal = gsw.gte(5).And(gsw.lte(95))

    # Coastal buffer: GSHHG land polygons (the GADM admin polygon is also a
    # passable proxy when GSHHG is unavailable, but here we use the public
    # high-resolution coastline asset).
    coast = ee.FeatureCollection(
        "USDOS/LSIB_SIMPLE/2017"
    ).filter(ee.Filter.eq("country_co", "KS")).geometry()
    coastline = coast.buffer(buffer_m).difference(coast.buffer(-buffer_m), maxError=100)

    kept: list[CoastalTile] = []
    for i, t in enumerate(tiles):
        geom = ee.Geometry.Rectangle(t["bbox"], proj="EPSG:4326", geodesic=False)
        try:
            on_coast = geom.intersects(coastline, maxError=1000).getInfo()
        except Exception as exc:  # noqa: BLE001
            log.warning("coast check failed for %s: %s", t["id"], exc)
            continue
        if not on_coast:
            continue
        try:
            n_px = int(
                intertidal.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=geom,
                    scale=scale_m,
                    bestEffort=True,
                    maxPixels=int(1e10),
                ).get("occurrence").getInfo()
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("JRC check failed for %s: %s", t["id"], exc)
            continue
        if n_px < min_intertidal_pixels:
            continue
        kept.append(CoastalTile(
            id=t["id"], bbox=t["bbox"], center=t["center"],
            n_intertidal_pixels=n_px,
        ))
        log.info(
            "  [keep] %s (%d intertidal pixels @ %s)",
            t["id"], n_px, t["center"],
        )
        if (i + 1) % 25 == 0:
            log.info("  ... %d tiles screened, %d kept", i + 1, len(kept))
    return kept


def write_tiles_yaml(tiles: list[CoastalTile], out_path: Path) -> Path:
    """Write tiles to a YAML file consumable by the national driver."""
    payload = {
        "tile_size_deg": DEFAULT_TILE_SIZE_DEG,
        "tiles": [asdict(t) for t in tiles],
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
    log.info("Wrote %s (%d tiles)", out_path, len(tiles))
    return out_path


def load_tiles_yaml(path: Path) -> list[CoastalTile]:
    """Load a tile list previously written by ``write_tiles_yaml``."""
    with open(path, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    return [CoastalTile(**t) for t in payload["tiles"]]


__all__ = [
    "CoastalTile",
    "candidate_tiles",
    "filter_coastal_with_intertidal",
    "write_tiles_yaml",
    "load_tiles_yaml",
]


# ---------------------------------------------------------------------------
# CLI: regenerate config/national_tiles.yaml from JRC + GSHHG (uses EE)
# ---------------------------------------------------------------------------

def _main_cli() -> None:
    import argparse

    from .auth import initialize

    p = argparse.ArgumentParser(
        description="Regenerate config/national_tiles.yaml from JRC + LSIB.",
    )
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument(
        "--out",
        default="config/national_tiles.yaml",
        help="Output YAML path (relative to project root).",
    )
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        default=DEFAULT_BBOX,
        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
    )
    p.add_argument("--tile-size-deg", type=float, default=DEFAULT_TILE_SIZE_DEG)
    p.add_argument("--buffer-m", type=int, default=DEFAULT_BUFFER_M)
    p.add_argument("--min-pixels", type=int, default=DEFAULT_MIN_PIXELS)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    initialize(project=args.project)

    raw = candidate_tiles(args.bbox, args.tile_size_deg)
    log.info("Screening %d candidate tiles ...", len(raw))
    kept = filter_coastal_with_intertidal(
        raw, buffer_m=args.buffer_m, min_intertidal_pixels=args.min_pixels,
    )
    log.info("Kept %d / %d tiles", len(kept), len(raw))

    from ..config import resolve_path

    out = resolve_path(args.out)
    write_tiles_yaml(kept, out)


if __name__ == "__main__":
    _main_cli()
