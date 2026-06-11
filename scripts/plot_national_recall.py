"""Figures for the JRC-mask vs intrinsic-inundation-gate recall result (§3.4).

Produces:
    data/outputs/figures/national_recall_bars.png
        National MOF-footprint decomposition (captured / missed-no-DEM /
        missed-IF) under the two intertidal-domain choices.
    data/outputs/figures/recall_map_<tile>.png
        Two-panel map on a high-turbidity tile (default Ganghwa) showing how
        the inundation gate recovers turbid intertidal flat the JRC mask drops.

Usage:
    python scripts/plot_national_recall.py --tile K_1263_0375 --year 2023
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
from matplotlib.patches import Patch

from src.analysis.extent import (
    BAND_DEM, BAND_IF, BAND_N_OBS, IF_HI, IF_LO, MIN_N_OBS,
)
from src.config import resolve_path


def _categories(dem, n_obs, inund, mof_mask, z_lat, z_hat, use_if):
    """Return (captured, nodem, missed_if, commission) boolean masks."""
    has_dem = np.isfinite(dem) & (n_obs >= MIN_N_OBS)
    in_band = has_dem & (dem >= z_lat) & (dem <= z_hat)
    if use_if and inund is not None:
        if_ok = np.isfinite(inund) & (inund >= IF_LO) & (inund <= IF_HI)
    else:
        if_ok = np.ones_like(has_dem, dtype=bool)
    in_range = in_band & if_ok
    captured = mof_mask & in_range
    nodem = mof_mask & ~has_dem
    missed_if = mof_mask & in_band & ~if_ok
    commission = in_range & ~mof_mask
    return captured, nodem, missed_if, commission


def main() -> None:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from shapely.geometry import box as _box

    from src.gee.national_tiling import load_tiles_yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("--tile", default="K_1263_0375")  # Ganghwa / Han estuary
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--tiles-config", default="config/national_tiles_full.yaml")
    args = ap.parse_args()

    b = pd.read_csv(resolve_path("data/outputs/tables/tidal_flat_bounds.csv"))
    z_lat, z_hat = float(b["z_lat_m"].min()), float(b["z_hat_m"].max())
    mof = gpd.read_file(resolve_path("data/raw/reference/2023_갯벌_접경지역포함/2023_갯벌.shp"))
    dem_dir = resolve_path("data/outputs/dem/national")

    # ---- (1) national bar chart: accumulate both regimes in one pass ----
    tiles = load_tiles_yaml(resolve_path(args.tiles_config))
    agg = {"jrc": dict(cap=0.0, nod=0.0, mif=0.0),
           "if": dict(cap=0.0, nod=0.0, mif=0.0)}
    mof_total_px = 0.0
    for tile in tiles:
        v4 = dem_dir / f"{tile.id}_v4_{args.year}.tif"
        v5 = dem_dir / f"{tile.id}_v5nojrc_{args.year}.tif"
        if not v5.exists():
            continue
        with rasterio.open(v5) as src:
            bb, tr, cr = src.bounds, src.transform, src.crs
            H, W = src.height, src.width
            px = abs(tr.a) * abs(tr.e) / 1e6
            tg = gpd.GeoSeries([_box(bb.left, bb.bottom, bb.right, bb.top)],
                               crs=cr).to_crs(mof.crs).iloc[0]
            sub = mof[mof.intersects(tg)].to_crs(cr)
            if sub.empty:
                continue
            mm = rasterize([(g, 1) for g in sub.geometry if g and not g.is_empty],
                           out_shape=(H, W), transform=tr, fill=0,
                           dtype="uint8").astype(bool)
            if not mm.any():
                continue
            dem5 = src.read(BAND_DEM, masked=True).filled(np.nan)
            nobs5 = src.read(BAND_N_OBS, masked=True).filled(0)
            inun5 = src.read(BAND_IF, masked=True).filled(np.nan)
        mof_total_px += mm.sum() * px
        c, n, mi, _ = _categories(dem5, nobs5, inun5, mm, z_lat, z_hat, True)
        agg["if"]["cap"] += c.sum() * px
        agg["if"]["nod"] += n.sum() * px
        agg["if"]["mif"] += mi.sum() * px
        if v4.exists():
            with rasterio.open(v4) as s4:
                dem4 = s4.read(BAND_DEM, masked=True).filled(np.nan)
                nobs4 = s4.read(BAND_N_OBS, masked=True).filled(0)
            c4, n4, _, _ = _categories(dem4, nobs4, None, mm, z_lat, z_hat, False)
            agg["jrc"]["cap"] += c4.sum() * px
            agg["jrc"]["nod"] += n4.sum() * px

    M = mof_total_px
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    labels = ["JRC occurrence\nmask", "Intrinsic\ninundation gate"]
    keys = ["jrc", "if"]
    cap = [agg[k]["cap"] for k in keys]
    nod = [agg[k]["nod"] for k in keys]
    mif = [agg[k]["mif"] for k in keys]
    other = [M - cap[i] - nod[i] - mif[i] for i in range(2)]
    x = np.arange(2)
    ax.bar(x, cap, color="#1a9850", label="captured")
    ax.bar(x, nod, bottom=cap, color="#d73027", label="missed (no DEM)")
    ax.bar(x, mif, bottom=np.add(cap, nod), color="#fdae61",
           label="missed (inundation gate)")
    ax.bar(x, other, bottom=np.add(np.add(cap, nod), mif), color="#cccccc",
           label="other (above/below)")
    for i in range(2):
        ax.text(i, cap[i] / 2, f"{cap[i]:.0f}\n({cap[i]/M*100:.0f}%)",
                ha="center", va="center", color="white", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("MOF footprint area (km²)")
    ax.set_title(f"National MOF-footprint capture, {args.year}\n"
                 f"(rasterised MOF = {M:.0f} km²)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2, fontsize=8)
    fig.tight_layout()
    out1 = resolve_path("data/outputs/figures/national_recall_bars.png")
    out1.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out1, dpi=140, bbox_inches="tight")
    print("Wrote", out1, f"(JRC cap={cap[0]:.0f}, IF cap={cap[1]:.0f} km²)")

    # ---- (2) two-panel recall map on the Ganghwa tile ----
    v4 = dem_dir / f"{args.tile}_v4_{args.year}.tif"
    v5 = dem_dir / f"{args.tile}_v5nojrc_{args.year}.tif"
    fig2, axes = plt.subplots(1, 2, figsize=(13, 6.2), sharex=True, sharey=True)
    cmap = ListedColormap(["#f7f7f7", "#1a9850", "#d73027"])  # bg/cap/nodem
    for ax, path, title in [
        (axes[0], v4, "JRC occurrence mask (V4)"),
        (axes[1], v5, "Intrinsic inundation gate (V5)"),
    ]:
        with rasterio.open(path) as src:
            dem = src.read(BAND_DEM, masked=True).filled(np.nan)
            nobs = src.read(BAND_N_OBS, masked=True).filled(0)
            inun = (src.read(BAND_IF, masked=True).filled(np.nan)
                    if src.count >= BAND_IF else None)
            tr, cr = src.transform, src.crs
            H, W = src.height, src.width
            px = abs(tr.a) * abs(tr.e) / 1e6
            ext = [src.bounds.left, src.bounds.right,
                   src.bounds.bottom, src.bounds.top]
            tg = gpd.GeoSeries([_box(*src.bounds)], crs=cr).to_crs(mof.crs).iloc[0]
            sub = mof[mof.intersects(tg)].to_crs(cr)
            mm = rasterize([(g, 1) for g in sub.geometry if g and not g.is_empty],
                           out_shape=(H, W), transform=tr, fill=0,
                           dtype="uint8").astype(bool)
        use_if = "v5" in path.name
        c, n, _, _ = _categories(dem, nobs, inun, mm, z_lat, z_hat, use_if)
        cat = np.zeros((H, W), dtype="uint8")
        cat[n] = 2
        cat[c] = 1
        ax.imshow(cat, extent=ext, origin="upper", cmap=cmap, vmin=0, vmax=2,
                  interpolation="nearest")
        sub.boundary.plot(ax=ax, color="k", linewidth=0.4, alpha=0.6)
        ax.set_title(f"{title}\ncaptured {c.sum()*px:.0f} km²  "
                     f"({c.sum()/max(mm.sum(),1)*100:.0f}% of MOF)")
        ax.set_xlabel("Easting (m, UTM52N)")
    axes[0].set_ylabel("Northing (m)")
    handles = [Patch(color="#1a9850", label="captured (MOF ∩ mapped)"),
               Patch(color="#d73027", label="missed — no DEM")]
    fig2.legend(handles=handles, loc="lower center", ncol=2, fontsize=9)
    fig2.suptitle(f"Turbid-coast recall recovery — tile {args.tile} ({args.year})",
                  fontsize=12)
    fig2.tight_layout(rect=[0, 0.05, 1, 0.97])
    out2 = resolve_path(f"data/outputs/figures/recall_map_{args.tile}.png")
    fig2.savefig(out2, dpi=140)
    print("Wrote", out2)


if __name__ == "__main__":
    main()
