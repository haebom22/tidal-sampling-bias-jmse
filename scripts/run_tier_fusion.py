"""Tiered tidal-flat extent fusion (commission removal) — national 2023.

The elevation-band DEM alone over-maps permanent/subtidal water (national
"commission" ~1,690 km²: Saemangeum reclaimed lake, deep channels, turbid
bays). This driver fuses three independent signals per tile to produce a
defensible extent:

    jrc_intertidal : JRC GSW occurrence in [5, 95] %  (periodically wet)
    jrc_water      : JRC GSW occurrence > 95 %        (permanent water)
    dem_in_range   : finite DEM, n_obs>=gate, z_LAT<=DEM<=z_HAT
    msic_flat      : MSIC-OA tidal-flat == 1

    Tier 1 (high) : dem_in_range & jrc_intertidal
    Tier 2 (med)  : (dem_in_range | msic_flat) & ~jrc_water & ~Tier1
    Tier 3 (low)  : jrc_intertidal & ~Tier1 & ~Tier2   (gap-fill, no DEM/MSIC)

    fused extent  : Tier1 | Tier2 | Tier3  (permanent water excluded)

JRC occurrence is exported per tile from Earth Engine (cached). Areas are
attributed to provinces by nearest MOF zone (same rule as
run_national_area_corrected.py).

Outputs:
    data/outputs/extent/national/<tile>_tier_2023.tif   (0/1/2/3)
    data/outputs/extent/national/<tile>_jrc_2023.tif    (occurrence %)
    data/outputs/tables/national_tier_fusion_2023.csv   (province x tier)

Usage:
    EE_PROJECT=... python scripts/run_tier_fusion.py --year 2023
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.extent import BAND_DEM, BAND_N_OBS, MIN_N_OBS
from src.config import resolve_path

os.environ.setdefault("SHAPE_ENCODING", "UTF-8")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("tier_fusion")

SD_EN = {
    "강원도": "Gangwon", "경기도": "Gyeonggi", "경상남도": "South Gyeongsang",
    "경상북도": "North Gyeongsang", "부산광역시": "Busan", "울산광역시": "Ulsan",
    "인천광역시": "Incheon", "전라남도": "South Jeolla", "전라북도": "North Jeolla",
    "제주도": "Jeju", "충청남도": "South Chungcheong",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=None)
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--dem-dir", default="data/outputs/dem/national")
    p.add_argument("--extent-dir", default="data/outputs/extent/national")
    p.add_argument("--tiles-config", default="config/national_tiles_full.yaml")
    p.add_argument("--mof", default="data/raw/reference/2023_갯벌_접경지역포함/2023_갯벌.shp")
    p.add_argument("--bounds-table", default="data/outputs/tables/tidal_flat_bounds.csv")
    p.add_argument("--occ-lo", type=float, default=5.0)
    p.add_argument("--occ-hi", type=float, default=95.0)
    p.add_argument("--min-n-obs", type=int, default=MIN_N_OBS)
    p.add_argument(
        "--water-source", choices=["jrc", "recent"], default="recent",
        help="jrc = JRC GSW 1984-2021 occurrence (long record, mislabels "
             "reclaimed flats); recent = 2022-2024 MNDWI water frequency "
             "(reflects post-reclamation state — removes diked commission).",
    )
    p.add_argument("--rolling", type=int, default=3)
    return p.parse_args()


def _window(year: int, rolling: int) -> tuple[str, str]:
    half = rolling // 2
    return f"{max(2015, year - half)}-01-01", f"{year + half}-12-31"


def _export_jrc(tile, out_path: Path, occ_lo: float) -> bool:
    """Export JRC GSW occurrence (%) for a tile bbox to a local GeoTIFF."""
    import ee
    from src.gee.exports import export_image_to_local

    if out_path.exists():
        return True
    occ = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    # Unmask land (never-water) to 0 so the raster is dense.
    occ = occ.unmask(0).toFloat()
    region = ee.Geometry.Rectangle(list(tile.bbox), proj="EPSG:4326", geodesic=False)
    res = export_image_to_local(
        occ, region=region, scale_m=30, out_path=out_path, overwrite=False,
    )
    return res.ok


def _export_recent_waterfreq(
    tile, out_path: Path, start: str, end: str, min_obs: int = 5,
) -> bool:
    """Export a *recent* (JRC GSW YearlyHistory 2021) pseudo-occurrence.

    The full 2022-24 MNDWI-mean composite is too heavy for a synchronous
    ``getDownloadURL`` (hundreds of scenes per tile). Instead we use the
    JRC GSW YearlyHistory ``waterClass`` for the latest year (2021), which
    is a single pre-computed image and reflects the *post-reclamation*
    regime (Saemangeum was impounded in 2010). We re-encode it into the
    same 0-100 scale the fusion expects:

        waterClass 1 (not water)       -> 0    (land / diked-drained)
        waterClass 2 (seasonal water)  -> 50   (intertidal)
        waterClass 3 (permanent water) -> 100  (subtidal / impounded lake)
        waterClass 0 (no data)         -> 255  (no data)
    """
    import ee
    from src.gee.exports import export_image_to_local

    if out_path.exists():
        return True
    geom = ee.Geometry.Rectangle(list(tile.bbox), proj="EPSG:4326", geodesic=False)
    yh = (ee.ImageCollection("JRC/GSW1_4/YearlyHistory")
          .filter(ee.Filter.eq("year", 2021)).first().select("waterClass"))
    # Map classes -> pseudo-occurrence; unmapped/0 -> 255.
    pseudo = (ee.Image(255)
              .where(yh.eq(1), 0)
              .where(yh.eq(2), 50)
              .where(yh.eq(3), 100)).toFloat().rename("waterfreq")
    res = export_image_to_local(
        pseudo, region=geom, scale_m=30, out_path=out_path, overwrite=False,
    )
    return res.ok


def _reproj_to(ref_path: Path, src_path: Path, band: int = 1,
               resampling=None) -> np.ndarray:
    """Read ``src_path`` band and reproject onto ``ref_path`` grid."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    if resampling is None:
        resampling = Resampling.nearest
    with rasterio.open(ref_path) as ref:
        H, W = ref.height, ref.width
        dst_transform, dst_crs = ref.transform, ref.crs
    out = np.zeros((H, W), dtype="float32")
    with rasterio.open(src_path) as src:
        reproject(
            source=src.read(band), destination=out,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=resampling,
        )
    return out


def main() -> None:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from scipy import ndimage
    from shapely.geometry import box as _box

    from src.gee.auth import initialize
    from src.gee.national_tiling import load_tiles_yaml

    args = parse_args()
    initialize(project=args.project)

    b = pd.read_csv(resolve_path(args.bounds_table))
    z_lat, z_hat = float(b["z_lat_m"].min()), float(b["z_hat_m"].max())
    log.info("z_LAT=%.2f z_HAT=%.2f n_obs>=%d occ=[%.0f,%.0f]",
             z_lat, z_hat, args.min_n_obs, args.occ_lo, args.occ_hi)

    mof = gpd.read_file(resolve_path(args.mof))
    mof_total = float(mof.to_crs(epsg=5186).geometry.area.sum() / 1e6)
    sd_codes = {sd: i + 1 for i, sd in enumerate(sorted(mof["SD"].dropna().unique()))}
    code_sd = {v: k for k, v in sd_codes.items()}

    tiles = load_tiles_yaml(resolve_path(args.tiles_config))
    dem_dir = resolve_path(args.dem_dir)
    extent_dir = resolve_path(args.extent_dir)

    acc: dict[str, dict[str, float]] = {}

    def _add(code: int, key: str, area: float) -> None:
        en = SD_EN.get(code_sd.get(int(code), "unknown"), "unknown")
        acc.setdefault(en, {"tier1": 0.0, "tier2": 0.0, "tier3": 0.0,
                            "fused": 0.0, "fused_in_mof": 0.0})
        acc[en][key] += area

    for tile in tiles:
        dem_path = dem_dir / f"{tile.id}_v4_{args.year}.tif"
        if not dem_path.exists():
            continue
        if args.water_source == "jrc":
            water_path = extent_dir / f"{tile.id}_jrc_{args.year}.tif"
            ok = _export_jrc(tile, water_path, args.occ_lo)
        else:
            water_path = extent_dir / f"{tile.id}_wfreq_{args.year}.tif"
            wstart, wend = _window(args.year, args.rolling)
            ok = _export_recent_waterfreq(tile, water_path, wstart, wend)
        if not ok:
            log.warning("  water-mask export failed for %s — skip", tile.id)
            continue

        with rasterio.open(dem_path) as src:
            dem = src.read(BAND_DEM, masked=True).filled(np.nan).astype("float32")
            n_obs = src.read(BAND_N_OBS, masked=True).filled(0)
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
            prov = rasterize(
                [(g, sd_codes[sd]) for g, sd in zip(sub.geometry, sub["SD"])
                 if g and not g.is_empty and sd in sd_codes],
                out_shape=(H, W), transform=transform, fill=0, dtype="int32")
            if not (prov > 0).any():
                continue
            idx = ndimage.distance_transform_edt(
                prov == 0, return_distances=False, return_indices=True)
            prov_filled = prov[tuple(idx)]
            mof_mask = rasterize(
                [(g, 1) for g in sub.geometry if g and not g.is_empty],
                out_shape=(H, W), transform=transform, fill=0, dtype="uint8"
            ).astype(bool)

        occ = _reproj_to(dem_path, water_path, band=1)
        valid = occ != 255  # 255 = recent-freq no-data (JRC path has none)
        wf_intertidal = valid & (occ >= args.occ_lo) & (occ <= args.occ_hi)
        wf_water = valid & (occ > args.occ_hi)          # permanently wet
        wf_land = valid & (occ < args.occ_lo)           # currently dry (incl. diked)
        # Definitively *not* tidal flat now: permanent water or drained/diked land.
        exclude = wf_water | wf_land

        msic = np.zeros((H, W), dtype=bool)
        mpath = extent_dir / f"{tile.id}_msic_{args.year}.tif"
        if mpath.exists():
            msic = _reproj_to(dem_path, mpath, band=1) == 1

        dem_in = np.isfinite(dem) & (n_obs >= args.min_n_obs) \
            & (dem >= z_lat) & (dem <= z_hat)

        tier1 = dem_in & wf_intertidal
        tier2 = (dem_in | msic) & ~exclude & ~tier1
        tier3 = wf_intertidal & ~tier1 & ~tier2
        fused = tier1 | tier2 | tier3

        # Write tier raster (0 bg / 1 / 2 / 3).
        tier = np.zeros((H, W), dtype="uint8")
        tier[tier3] = 3
        tier[tier2] = 2
        tier[tier1] = 1
        tpath = extent_dir / f"{tile.id}_tier_{args.year}.tif"
        with rasterio.open(dem_path) as src:
            prof = src.profile
        prof.update(count=1, dtype="uint8", nodata=0)
        with rasterio.open(tpath, "w", **prof) as dst:
            dst.write(tier, 1)

        for code in np.unique(prov_filled):
            if code == 0:
                continue
            pm = prov_filled == code
            _add(code, "tier1", float((tier1 & pm).sum()) * px)
            _add(code, "tier2", float((tier2 & pm).sum()) * px)
            _add(code, "tier3", float((tier3 & pm).sum()) * px)
            _add(code, "fused", float((fused & pm).sum()) * px)
            _add(code, "fused_in_mof", float((fused & pm & mof_mask).sum()) * px)
        log.info("  %s fused so far: %.0f km^2",
                 tile.id, sum(v["fused"] for v in acc.values()))

    rows = [{"province": p, "year": args.year, **v} for p, v in sorted(acc.items())]
    df = pd.DataFrame(rows)
    out = resolve_path(f"data/outputs/tables/national_tier_fusion_{args.year}.csv")
    df.to_csv(out, index=False, float_format="%.3f")
    log.info("Wrote %s", out)

    t1, t2, t3 = df["tier1"].sum(), df["tier2"].sum(), df["tier3"].sum()
    fu, fim = df["fused"].sum(), df["fused_in_mof"].sum()
    print(f"\n=== Tier-fusion national extent, {args.year} ===")
    print(f"  Tier 1 (DEM & intertidal) : {t1:8.1f} km^2")
    print(f"  Tier 2 (DEM|MSIC, not excl): {t2:8.1f} km^2")
    print(f"  Tier 3 (water-freq fill)   : {t3:8.1f} km^2")
    print(f"  FUSED total           : {fu:8.1f} km^2  ({fu/mof_total*100:.0f}% of MOF)")
    print(f"  fused within MOF      : {fim:8.1f} km^2  ({fim/mof_total*100:.0f}% of MOF)")
    print(f"  MOF official          : {mof_total:8.1f} km^2")
    print("\nPer province (Tier1 | Tier2 | Tier3 | fused | MOF, km^2):")
    mofp = mof.to_crs(epsg=5186).assign(en=mof["SD"].map(SD_EN)).groupby("en").apply(
        lambda d: d.geometry.area.sum() / 1e6)
    for _, r in df.sort_values("fused", ascending=False).iterrows():
        mv = float(mofp.get(r.province, float("nan")))
        print(f"  {r.province:18s} {r.tier1:7.1f} {r.tier2:7.1f} {r.tier3:7.1f} "
              f"{r.fused:8.1f} {mv:8.1f}")


if __name__ == "__main__":
    main()
