"""Spatial diagnosis of the DEM-vs-MOF area gap (national 2023 snapshot).

For every national tile DEM raster we rasterise the MOF 2023 tidal-flat
polygons onto the tile grid and cross-tabulate each MOF pixel into:

    captured       finite DEM, n_obs >= gate, z_LAT <= DEM <= z_HAT
    missed_no_dem  DEM is NaN  *or*  n_obs < gate  (never seen wet+dry)
    missed_above   finite DEM, n_obs >= gate, DEM >  z_HAT (supratidal /
                   reclaimed / aquaculture dike — "too high")
    missed_below   finite DEM, n_obs >= gate, DEM <  z_LAT (subtidal /
                   permanent channel — "too low")

We also count DEM-mapped flat *outside* MOF (commission) and record the
elevation histogram of MOF pixels that do carry a DEM value. Output:

    data/outputs/tables/mof_gap_breakdown.csv         (per province + national)
    data/outputs/tables/mof_gap_elev_hist.csv         (MOF-pixel elevation pdf)

Usage:
    python scripts/diagnose_mof_gap.py --year 2023
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
log = logging.getLogger("mof_gap")

CATS = ["captured", "missed_no_dem", "missed_above", "missed_below", "missed_if"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--dem-dir", default="data/outputs/dem/national")
    p.add_argument("--mof", default="data/raw/reference/2023_갯벌_접경지역포함/2023_갯벌.shp")
    p.add_argument("--bounds-table", default="data/outputs/tables/tidal_flat_bounds.csv")
    p.add_argument("--z-lat", type=float, default=None)
    p.add_argument("--z-hat", type=float, default=None)
    p.add_argument("--min-n-obs", type=int, default=MIN_N_OBS)
    p.add_argument("--dem-suffix", default="v4")
    p.add_argument("--if-lo", type=float, default=IF_LO,
                   help="Inundation-frequency lower gate; <0 disables.")
    p.add_argument("--if-hi", type=float, default=IF_HI)
    return p.parse_args()


def main() -> None:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize

    args = parse_args()

    # LAT/HAT defaults from pilot bounds (same rule as the mosaic).
    b = pd.read_csv(resolve_path(args.bounds_table))
    z_lat = args.z_lat if args.z_lat is not None else float(b["z_lat_m"].min())
    z_hat = args.z_hat if args.z_hat is not None else float(b["z_hat_m"].max())
    use_if = args.if_lo >= 0.0
    log.info("z_LAT=%.2f m, z_HAT=%.2f m, n_obs>=%d  IF gate=%s suffix=%s",
             z_lat, z_hat, args.min_n_obs,
             f"[{args.if_lo:.2f},{args.if_hi:.2f}]" if use_if else "off",
             args.dem_suffix)

    mof = gpd.read_file(resolve_path(args.mof))
    log.info("MOF polygons: %d (%.0f km^2 by attr)", len(mof), mof["area"].sum())

    dem_dir = resolve_path(args.dem_dir)
    tiles = sorted(dem_dir.glob(f"*_{args.dem_suffix}_{args.year}.tif"))
    log.info("national DEM tiles: %d", len(tiles))

    # Per-province accumulators (km^2).
    prov_cat: dict[str, dict[str, float]] = {}
    commission_km2 = 0.0
    mof_total_px_km2 = 0.0
    elev_vals: list[np.ndarray] = []
    elev_wts: list[np.ndarray] = []

    for tif in tiles:
        with rasterio.open(tif) as src:
            dem = src.read(BAND_DEM, masked=True).filled(np.nan).astype("float32")
            n_obs = src.read(BAND_N_OBS, masked=True).filled(0)
            inund = (src.read(BAND_IF, masked=True).filled(np.nan)
                     if (use_if and src.count >= BAND_IF) else None)
            transform = src.transform
            crs = src.crs
            px_area_km2 = abs(transform.a) * abs(transform.e) / 1e6
            H, W = dem.shape

            # MOF polygons clipped to this tile (in the tile CRS).
            tb = src.bounds
            from shapely.geometry import box as _box
            tile_geom = gpd.GeoSeries([_box(tb.left, tb.bottom, tb.right, tb.top)],
                                      crs=crs).to_crs(mof.crs).iloc[0]
            sub = mof[mof.intersects(tile_geom)]
            if sub.empty:
                continue
            sub = sub.to_crs(crs)
            # Province of each polygon (SD) → rasterise a province-id grid too.
            mof_mask = rasterize(
                [(g, 1) for g in sub.geometry if g and not g.is_empty],
                out_shape=(H, W), transform=transform, fill=0, dtype="uint8",
            ).astype(bool)
            if not mof_mask.any():
                continue

            # Dominant province for this tile (area-weighted) — tiles rarely
            # straddle a provincial coast boundary, so a single label is fine
            # for the breakdown granularity we need.
            prov = str(sub.dissolve(by="SD")["area"].idxmax()
                       if "SD" in sub.columns else "unknown")
            try:
                prov = str(sub.groupby("SD")["area"].sum().idxmax())
            except Exception:  # noqa: BLE001
                prov = "unknown"

            has_dem = np.isfinite(dem) & (n_obs >= args.min_n_obs)
            in_band = has_dem & (dem >= z_lat) & (dem <= z_hat)
            if inund is not None:
                if_ok = np.isfinite(inund) & (inund >= args.if_lo) & (inund <= args.if_hi)
            else:
                if_ok = np.ones_like(has_dem, dtype=bool)
            in_range = in_band & if_ok

            captured = mof_mask & in_range
            missed_no_dem = mof_mask & ~has_dem
            missed_above = mof_mask & has_dem & (dem > z_hat)
            missed_below = mof_mask & has_dem & (dem < z_lat)
            # In elevation band but rejected by the inundation-frequency gate
            # (subtidal-saturated freq>hi, or supratidal-dry freq<lo).
            missed_if = mof_mask & in_band & ~if_ok

            # Commission: mapped flat outside MOF.
            commission = in_range & ~mof_mask

            d = prov_cat.setdefault(prov, {c: 0.0 for c in CATS})
            d["captured"] += float(captured.sum()) * px_area_km2
            d["missed_no_dem"] += float(missed_no_dem.sum()) * px_area_km2
            d["missed_above"] += float(missed_above.sum()) * px_area_km2
            d["missed_below"] += float(missed_below.sum()) * px_area_km2
            d["missed_if"] += float(missed_if.sum()) * px_area_km2
            commission_km2 += float(commission.sum()) * px_area_km2
            mof_total_px_km2 += float(mof_mask.sum()) * px_area_km2

            # Elevation pdf of MOF pixels that carry a DEM value.
            mof_dem = dem[mof_mask & np.isfinite(dem)]
            if mof_dem.size:
                elev_vals.append(mof_dem)
                elev_wts.append(np.full(mof_dem.size, px_area_km2))

        log.info("  %s: MOF px area so far %.1f km^2", tif.stem, mof_total_px_km2)

    # ---- assemble breakdown ----
    rows = []
    for prov, d in sorted(prov_cat.items()):
        tot = sum(d.values())
        rows.append({"province": prov, **{c: round(d[c], 2) for c in CATS},
                     "mof_px_total": round(tot, 2)})
    df = pd.DataFrame(rows)
    nat = {c: round(df[c].sum(), 2) for c in CATS}
    nat_tot = sum(nat.values())
    df_nat = pd.DataFrame([{"province": "NATIONAL", **nat,
                            "mof_px_total": round(nat_tot, 2)}])
    df = pd.concat([df, df_nat], ignore_index=True)

    out = resolve_path("data/outputs/tables/mof_gap_breakdown.csv")
    df.to_csv(out, index=False)
    log.info("Wrote %s", out)

    # ---- elevation histogram ----
    if elev_vals:
        vals = np.concatenate(elev_vals)
        wts = np.concatenate(elev_wts)
        bins = np.arange(-6, 6.01, 0.25)
        hist, edges = np.histogram(vals, bins=bins, weights=wts)
        eh = pd.DataFrame({"z_lo": edges[:-1], "z_hi": edges[1:],
                           "area_km2": np.round(hist, 3)})
        eh_out = resolve_path("data/outputs/tables/mof_gap_elev_hist.csv")
        eh.to_csv(eh_out, index=False)
        log.info("Wrote %s", eh_out)

    # ---- console summary ----
    print("\n=== MOF-area gap breakdown (national 2023) ===")
    print(f"MOF rasterised total : {nat_tot:8.1f} km^2")
    for c in CATS:
        print(f"  {c:14s}: {nat[c]:8.1f} km^2  ({nat[c]/nat_tot*100:5.1f}%)")
    print(f"commission (mapped flat outside MOF): {commission_km2:8.1f} km^2")
    print("\nPer-province (captured / no_dem / above / below / if, km^2):")
    for _, r in df[df.province != "NATIONAL"].sort_values(
        "mof_px_total", ascending=False
    ).head(10).iterrows():
        print(f"  {r.province:14s} {r.captured:7.1f} {r.missed_no_dem:7.1f} "
              f"{r.missed_above:7.1f} {r.missed_below:7.1f} {r.missed_if:7.1f}")


if __name__ == "__main__":
    main()
