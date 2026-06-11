"""Corrected national / per-province tidal-flat area (Phase 4c fix).

The original ``run_national_mosaic.py`` clipped DEM pixels to admin
``korea_provinces.geojson`` polygons. Those polygons trace the high-water
coastline, so ~83 % of tidal flat — which is intertidal and therefore
*seaward* of the high-water mark — fell outside them and was discarded
(national DEM area collapsed to 787 km²). This driver fixes the
attribution by assigning every flat pixel to the **nearest MOF province
zone** (rasterise MOF ``SD`` → nearest-fill), so seaward flats are kept.

Definitions (same gates as the mosaic):
    DEM flat  : finite DEM, n_obs >= gate, z_LAT <= DEM <= z_HAT
    MSIC flat : MSIC raster == 1

Outputs:
    data/outputs/tables/annual_area_national_by_region_corrected.csv
        province | year | area_km2_dem | area_km2_msic | area_km2_dem_in_mof

Usage:
    python scripts/run_national_area_corrected.py --year 2023
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.extent import BAND_DEM, BAND_IF, BAND_N_OBS, IF_HI, IF_LO, MIN_N_OBS
from src.config import resolve_path

os.environ.setdefault("SHAPE_ENCODING", "UTF-8")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("national_corrected")

SD_EN = {
    "강원도": "Gangwon", "경기도": "Gyeonggi", "경상남도": "South Gyeongsang",
    "경상북도": "North Gyeongsang", "부산광역시": "Busan", "울산광역시": "Ulsan",
    "인천광역시": "Incheon", "전라남도": "South Jeolla", "전라북도": "North Jeolla",
    "제주도": "Jeju", "충청남도": "South Chungcheong",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--dem-dir", default="data/outputs/dem/national")
    p.add_argument("--extent-dir", default="data/outputs/extent/national")
    p.add_argument("--mof", default="data/raw/reference/2023_갯벌_접경지역포함/2023_갯벌.shp")
    p.add_argument("--bounds-table", default="data/outputs/tables/tidal_flat_bounds.csv")
    p.add_argument("--z-lat", type=float, default=None)
    p.add_argument("--z-hat", type=float, default=None)
    p.add_argument("--min-n-obs", type=int, default=MIN_N_OBS)
    p.add_argument("--dem-suffix", default="v4",
                   help="DEM filename stem suffix (e.g. 'v4' or 'v5nojrc').")
    p.add_argument("--if-lo", type=float, default=IF_LO,
                   help="Inundation-frequency lower gate; <0 disables.")
    p.add_argument("--if-hi", type=float, default=IF_HI,
                   help="Inundation-frequency upper gate.")
    return p.parse_args()


def main() -> None:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from scipy import ndimage
    from shapely.geometry import box as _box

    args = parse_args()
    b = pd.read_csv(resolve_path(args.bounds_table))
    z_lat = args.z_lat if args.z_lat is not None else float(b["z_lat_m"].min())
    z_hat = args.z_hat if args.z_hat is not None else float(b["z_hat_m"].max())
    use_if = args.if_lo >= 0.0
    log.info("z_LAT=%.2f z_HAT=%.2f n_obs>=%d  IF gate=%s suffix=%s",
             z_lat, z_hat, args.min_n_obs,
             f"[{args.if_lo:.2f},{args.if_hi:.2f}]" if use_if else "off",
             args.dem_suffix)

    mof = gpd.read_file(resolve_path(args.mof))
    mof_total_km2 = float(mof.to_crs(epsg=5186).geometry.area.sum() / 1e6)
    log.info("MOF official total: %.1f km^2 (%s)", mof_total_km2, Path(args.mof).parent.name)
    sd_codes = {sd: i + 1 for i, sd in enumerate(sorted(mof["SD"].dropna().unique()))}
    code_sd = {v: k for k, v in sd_codes.items()}

    dem_dir = resolve_path(args.dem_dir)
    extent_dir = resolve_path(args.extent_dir)
    tiles = sorted(dem_dir.glob(f"*_{args.dem_suffix}_{args.year}.tif"))
    log.info("DEM tiles: %d", len(tiles))

    acc: dict[str, dict[str, float]] = {}

    def _add(prov_code: int, key: str, area: float) -> None:
        sd = code_sd.get(int(prov_code), "unknown")
        en = SD_EN.get(sd, sd)
        acc.setdefault(en, {"area_km2_dem": 0.0, "area_km2_msic": 0.0,
                            "area_km2_dem_in_mof": 0.0})
        acc[en][key] += area

    for tif in tiles:
        tid = tif.stem.replace(f"_{args.dem_suffix}_{args.year}", "")
        with rasterio.open(tif) as src:
            dem = src.read(BAND_DEM, masked=True).filled(np.nan).astype("float32")
            n_obs = src.read(BAND_N_OBS, masked=True).filled(0)
            inund = (src.read(BAND_IF, masked=True).filled(np.nan)
                     if (use_if and src.count >= BAND_IF) else None)
            transform, crs = src.transform, src.crs
            H, W = dem.shape
            px = abs(transform.a) * abs(transform.e) / 1e6
            bb = src.bounds
            tile_geom = gpd.GeoSeries(
                [_box(bb.left, bb.bottom, bb.right, bb.top)], crs=crs
            ).to_crs(mof.crs).iloc[0]
            sub = mof[mof.intersects(tile_geom)].to_crs(crs)
            if sub.empty:
                continue
            # Province-code raster (0 where no MOF) then nearest-fill.
            prov = rasterize(
                [(g, sd_codes[sd]) for g, sd in zip(sub.geometry, sub["SD"])
                 if g and not g.is_empty and sd in sd_codes],
                out_shape=(H, W), transform=transform, fill=0, dtype="int32",
            )
            mof_mask = prov > 0
            if not mof_mask.any():
                continue
            # Nearest-fill: every pixel inherits the nearest MOF province.
            idx = ndimage.distance_transform_edt(
                prov == 0, return_distances=False, return_indices=True
            )
            prov_filled = prov[tuple(idx)]

        has_dem = np.isfinite(dem) & (n_obs >= args.min_n_obs)
        in_range = has_dem & (dem >= z_lat) & (dem <= z_hat)
        if inund is not None:
            in_range &= np.isfinite(inund) & (inund >= args.if_lo) & (inund <= args.if_hi)

        # MSIC tile (optional).
        msic = None
        mpath = extent_dir / f"{tid}_msic_{args.year}.tif"
        if mpath.exists():
            with rasterio.open(mpath) as ms:
                if (ms.width, ms.height) == (W, H):
                    msic = ms.read(1, masked=True).filled(0) == 1
                else:
                    # Resample MSIC onto DEM grid (nearest) when sizes differ.
                    from rasterio.warp import reproject, Resampling
                    dst = np.zeros((H, W), dtype="float32")
                    reproject(
                        source=ms.read(1), destination=dst,
                        src_transform=ms.transform, src_crs=ms.crs,
                        dst_transform=transform, dst_crs=crs,
                        resampling=Resampling.nearest,
                    )
                    msic = dst == 1

        for code in np.unique(prov_filled):
            if code == 0:
                continue
            pm = prov_filled == code
            _add(code, "area_km2_dem", float((in_range & pm).sum()) * px)
            _add(code, "area_km2_dem_in_mof",
                 float((in_range & pm & mof_mask).sum()) * px)
            if msic is not None:
                _add(code, "area_km2_msic", float((msic & pm).sum()) * px)
        log.info("  %s done", tid)

    rows = [{"province": p, "year": args.year, **v} for p, v in sorted(acc.items())]
    df = pd.DataFrame(rows)
    out = resolve_path("data/outputs/tables/annual_area_national_by_region_corrected.csv")
    df.to_csv(out, index=False, float_format="%.3f")
    log.info("Wrote %s", out)

    dem_t = df["area_km2_dem"].sum()
    msic_t = df["area_km2_msic"].sum()
    inmof_t = df["area_km2_dem_in_mof"].sum()
    M = mof_total_km2
    print("\n=== Corrected national area (no admin clip), year", args.year, "===")
    print(f"  DEM flat (elev-band, unconstrained): {dem_t:8.1f} km^2  ({dem_t/M*100:.0f}% of MOF)")
    print(f"  DEM flat within MOF footprint      : {inmof_t:8.1f} km^2  ({inmof_t/M*100:.0f}% of MOF)")
    print(f"  MSIC flat                          : {msic_t:8.1f} km^2  ({msic_t/M*100:.0f}% of MOF)")
    print(f"  MOF 2023 official                  : {M:8.1f} km^2")
    print("\nPer province (DEM | DEM∩MOF | MSIC, km^2):")
    for _, r in df.sort_values("area_km2_dem", ascending=False).iterrows():
        print(f"  {r.province:18s} {r.area_km2_dem:8.1f} | "
              f"{r.area_km2_dem_in_mof:8.1f} | {r.area_km2_msic:8.1f}")


if __name__ == "__main__":
    main()
