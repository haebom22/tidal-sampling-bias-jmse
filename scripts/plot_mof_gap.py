"""Visualise the DEM-vs-MOF gap: a representative tile map + elevation pdf.

Produces:
    data/outputs/figures/mof_gap_tile_<id>.png   (captured / no-DEM / commission)
    data/outputs/figures/mof_gap_elev_hist.png   (MOF-pixel elevation pdf)
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("SHAPE_ENCODING", "UTF-8")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from src.analysis.extent import BAND_DEM, BAND_N_OBS, MIN_N_OBS
from src.config import resolve_path


def main() -> None:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from shapely.geometry import box as _box

    ap = argparse.ArgumentParser()
    ap.add_argument("--tile", default="K_1260_0348")  # 전남 최대 갯벌 타일
    ap.add_argument("--year", type=int, default=2023)
    args = ap.parse_args()

    b = pd.read_csv(resolve_path("data/outputs/tables/tidal_flat_bounds.csv"))
    z_lat, z_hat = float(b["z_lat_m"].min()), float(b["z_hat_m"].max())

    tif = resolve_path(f"data/outputs/dem/national/{args.tile}_v4_{args.year}.tif")
    mof = gpd.read_file(resolve_path("data/raw/reference/2023_갯벌_접경지역포함/2023_갯벌.shp"))

    with rasterio.open(tif) as src:
        dem = src.read(BAND_DEM, masked=True).filled(np.nan).astype("float32")
        n_obs = src.read(BAND_N_OBS, masked=True).filled(0)
        transform, crs = src.transform, src.crs
        H, W = dem.shape
        extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
        tile_geom = gpd.GeoSeries(
            [_box(src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)],
            crs=crs).to_crs(mof.crs).iloc[0]
        sub = mof[mof.intersects(tile_geom)].to_crs(crs)
        mof_mask = rasterize(
            [(g, 1) for g in sub.geometry if g and not g.is_empty],
            out_shape=(H, W), transform=transform, fill=0, dtype="uint8").astype(bool)

    has_dem = np.isfinite(dem) & (n_obs >= MIN_N_OBS)
    in_range = has_dem & (dem >= z_lat) & (dem <= z_hat)

    # Category raster: 0 bg, 1 captured (MOF & mapped), 2 missed-no-DEM (MOF & !dem),
    # 3 commission (mapped & !MOF)
    cat = np.zeros((H, W), dtype="uint8")
    cat[in_range & ~mof_mask] = 3
    cat[mof_mask & ~has_dem] = 2
    cat[mof_mask & in_range] = 1

    fig, (axm, axh) = plt.subplots(1, 2, figsize=(14, 6))

    cmap = ListedColormap(["#f7f7f7", "#1a9850", "#d73027", "#4575b4"])
    axm.imshow(cat, extent=extent, origin="upper", cmap=cmap, vmin=0, vmax=3,
               interpolation="nearest")
    sub.boundary.plot(ax=axm, color="k", linewidth=0.4, alpha=0.6)
    axm.set_title(f"{args.tile}  ({args.year})\n"
                  "green=captured  red=missed (no DEM)  blue=commission")
    axm.set_xlabel("Easting (m, UTM52N)")
    axm.set_ylabel("Northing (m)")

    cap = float((cat == 1).sum())
    nod = float((cat == 2).sum())
    com = float((cat == 3).sum())
    px = abs(transform.a) * abs(transform.e) / 1e6
    axm.text(0.02, 0.02,
             f"captured {cap*px:.1f} km²\nmissed   {nod*px:.1f} km²\n"
             f"commission {com*px:.1f} km²",
             transform=axm.transAxes, va="bottom", fontsize=9,
             bbox=dict(boxstyle="round", fc="white", alpha=0.8))

    # Elevation pdf (national).
    eh = pd.read_csv(resolve_path("data/outputs/tables/mof_gap_elev_hist.csv"))
    zc = 0.5 * (eh["z_lo"] + eh["z_hi"])
    axh.bar(zc, eh["area_km2"], width=0.23, color="#1a9850", alpha=0.8)
    axh.axvline(z_lat, color="b", ls="--", label=f"z_LAT={z_lat:.1f}")
    axh.axvline(z_hat, color="r", ls="--", label=f"z_HAT={z_hat:.1f}")
    axh.set_title("Elevation of MOF pixels carrying a DEM value (national)")
    axh.set_xlabel("DEM elevation (m, MSL)")
    axh.set_ylabel("area (km² per 0.25 m bin)")
    axh.legend()

    fig.tight_layout()
    out = resolve_path(f"data/outputs/figures/mof_gap_{args.tile}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    print("Wrote", out)


if __name__ == "__main__":
    main()
