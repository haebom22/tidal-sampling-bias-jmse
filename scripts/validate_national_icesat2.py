"""Extend ICESat-2 validation from the pilot DEMs to the national mosaic tiles.

§3.5 validates the JRC-free *pilot* DEMs against ICESat-2. This script validates
the *national mosaic* tiles (``data/outputs/dem/national/<tile>_v5nojrc_2023.tif``)
themselves, using the existing pilot ATL06 exposed-ground parquets wherever they
spatially overlap a national tile — i.e. an independent elevation check of the
delivered national product, with no new data download.

Each national tile is matched to every pilot ICESat-2 parquet whose points fall
inside the tile bbox; the tile DEM (band 1) is sampled at those points and the
RMSE/bias/std/R² computed after a per-tile WGS84→datum alignment.

Output
------
- data/outputs/tables/icesat2_validation_national.csv
"""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio  # noqa: F401 — import early to avoid pyarrow conflict
from shapely import wkb

from src.analysis.validate_icesat2 import validate_dem_vs_icesat2
from src.config import resolve_path
from src.gee.national_tiling import load_tiles_yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("nat_icesat")

MIN_POINTS = 200


def _parquet_extent(path: Path) -> tuple[float, float, float, float]:
    df = pd.read_parquet(path, columns=["geometry"])
    g = df["geometry"].iloc[::50].apply(lambda x: wkb.loads(x) if isinstance(x, bytes) else x)
    gs = gpd.GeoSeries(g)
    return float(gs.x.min()), float(gs.y.min()), float(gs.x.max()), float(gs.y.max())


def main() -> None:
    dem_dir = resolve_path("data/outputs/dem/national")
    tiles = load_tiles_yaml(resolve_path("config/national_tiles_full.yaml"))

    parquets = {Path(p).name.split("_")[0]: Path(p)
                for p in glob.glob(str(resolve_path("data/processed/*_icesat2_exposed.parquet")))}
    extents = {k: _parquet_extent(v) for k, v in parquets.items()}
    log.info("ICESat-2 parquets: %s", list(parquets))

    rows = []
    for tile in tiles:
        dem_path = dem_dir / f"{tile.id}_v5nojrc_2023.tif"
        if not dem_path.exists():
            continue
        lon0, lat0, lon1, lat1 = tile.bbox
        for site, (e0, f0, e1, f1) in extents.items():
            # bbox overlap test
            if e1 < lon0 or e0 > lon1 or f1 < lat0 or f0 > lat1:
                continue
            out = validate_dem_vs_icesat2(
                dem_path, parquets[site], tile.id, f"nat_{site}",
                datum_offset=None,
            )
            if out is None:
                continue
            r, offset = out
            if r.n_points < MIN_POINTS:
                continue
            rows.append({
                "tile": tile.id, "icesat2_src": site, "n_points": r.n_points,
                "rmse_m": r.rmse_m, "mae_m": r.mae_m, "bias_m": r.bias_m,
                "std_m": r.std_m, "r_squared": r.r_squared,
                "datum_offset_m": offset, "region": tile.region_hint,
            })
            log.info("%s vs %s: n=%d RMSE=%.2f std=%.2f", tile.id, site,
                     r.n_points, r.rmse_m, r.std_m)

    df = pd.DataFrame(rows)
    out_path = resolve_path("data/outputs/tables/icesat2_validation_national.csv")
    df.to_csv(out_path, index=False, float_format="%.4f")
    log.info("Wrote %s (%d national-tile validations)", out_path, len(df))
    if not df.empty:
        print("\n=== National-mosaic tiles validated against ICESat-2 ===")
        print(df[["tile", "icesat2_src", "n_points", "rmse_m", "bias_m",
                  "std_m", "region"]].to_string(index=False, float_format="%.2f"))
        print(f"\nMean RMSE = {df.rmse_m.mean():.2f} m over {len(df)} tiles "
              f"(n_points {int(df.n_points.sum()):,})")


if __name__ == "__main__":
    main()
