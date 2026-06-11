"""Evaluate spatial-coherence constraints against the recall–precision wall (§3.4).

The intrinsic inundation gate recovers turbid-coast recall (77 % MOF capture)
but admits ~22,000 km² of open-/shallow-water commission at ~0 m elevation that
no occurrence threshold, elevation cut, or coastal dilation removes (§3.4).

This script tests whether a *spatial-coherence* constraint can break that wall.
Two physically-motivated filters are applied to the inundation-gated extent and
swept over their main parameter:

  S  minimum connected-component size (px): genuine flats are large contiguous
     bodies; flicker open water tends to fragment into small specks.
  L  land-adjacency: keep only components whose R-pixel dilation touches a
     supratidal "land" seed (DEM > z_HAT), i.e. flats physically attached to the
     shore; offshore flicker is disconnected from land.

For each setting we accumulate, across all national tiles, the captured area
(inside the MOF footprint) and the commission area (outside it), tracing a
recall (capture) vs precision (1 - commission/mapped) curve.

Output
------
- data/outputs/tables/spatial_constraint_sweep.csv
- data/outputs/figures/spatial_constraint_tradeoff.png
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.analysis.extent import BAND_DEM, BAND_IF, BAND_N_OBS, IF_HI, IF_LO, MIN_N_OBS
from src.config import resolve_path


def _load_inputs():
    import geopandas as gpd
    from src.gee.national_tiling import load_tiles_yaml
    b = pd.read_csv(resolve_path("data/outputs/tables/tidal_flat_bounds.csv"))
    z_lat, z_hat = float(b["z_lat_m"].min()), float(b["z_hat_m"].max())
    mof = gpd.read_file(
        resolve_path("data/raw/reference/2023_갯벌_접경지역포함/2023_갯벌.shp"))
    tiles = load_tiles_yaml(resolve_path("config/national_tiles_full.yaml"))
    return z_lat, z_hat, mof, tiles


def main() -> None:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from scipy import ndimage as ndi
    from shapely.geometry import box as _box

    z_lat, z_hat, mof, tiles = _load_inputs()
    dem_dir = resolve_path("data/outputs/dem/national")
    year = 2023

    # Parameter sweep. S in pixels (10 m px -> 100 px ~ 1 ha).
    size_grid = [0, 50, 200, 1000, 5000, 20000]
    land_dilate_px = 3  # ~30 m tolerance for "touches land"

    # Per-setting accumulators: keyed by (mode, S).
    acc = {}
    def _key(mode, S):
        return (mode, S)
    for mode in ("size", "size+land"):
        for S in size_grid:
            acc[_key(mode, S)] = dict(cap=0.0, comm=0.0, mapped=0.0)

    n_tiles = 0
    for tile in tiles:
        v5 = dem_dir / f"{tile.id}_v5nojrc_{year}.tif"
        if not v5.exists():
            continue
        with rasterio.open(v5) as src:
            tr, cr = src.transform, src.crs
            H, W = src.height, src.width
            px = abs(tr.a) * abs(tr.e) / 1e6
            dem = src.read(BAND_DEM, masked=True).filled(np.nan)
            nobs = src.read(BAND_N_OBS, masked=True).filled(0)
            inun = src.read(BAND_IF, masked=True).filled(np.nan)
            tg = gpd.GeoSeries([_box(*src.bounds)], crs=cr).to_crs(mof.crs).iloc[0]
            sub = mof[mof.intersects(tg)].to_crs(cr)
            if not sub.empty:
                mm = rasterize(
                    [(g, 1) for g in sub.geometry if g and not g.is_empty],
                    out_shape=(H, W), transform=tr, fill=0, dtype="uint8").astype(bool)
            else:
                mm = np.zeros((H, W), dtype=bool)
        n_tiles += 1

        has_dem = np.isfinite(dem) & (nobs >= MIN_N_OBS)
        in_band = has_dem & (dem >= z_lat) & (dem <= z_hat)
        if_ok = np.isfinite(inun) & (inun >= IF_LO) & (inun <= IF_HI)
        in_range = in_band & if_ok

        # Land seed: persistently-dry pixels (observed but almost never water).
        # Genuine flats abut dry land; open-water flicker commission abuts
        # persistently-wet water (inun ~ 1) and is far from dry land.
        observed = nobs >= MIN_N_OBS
        land_seed = observed & np.isfinite(inun) & (inun < IF_LO)
        if land_dilate_px > 0 and land_seed.any():
            land_near = ndi.binary_dilation(land_seed, iterations=land_dilate_px)
        else:
            land_near = land_seed

        # Connected components of the gated extent (8-connectivity).
        structure = np.ones((3, 3), dtype=int)
        lbl, nlab = ndi.label(in_range, structure=structure)
        if nlab == 0:
            continue
        comp_sizes = np.bincount(lbl.ravel())
        comp_sizes[0] = 0
        # Which components touch land?
        touches_land = np.zeros(nlab + 1, dtype=bool)
        if land_near.any():
            land_labels = np.unique(lbl[land_near])
            touches_land[land_labels[land_labels > 0]] = True

        size_of = comp_sizes[lbl]  # per-pixel component size

        for S in size_grid:
            keep_size = in_range & (size_of >= max(S, 1))
            # mode: size only
            k1 = keep_size
            acc[_key("size", S)]["cap"] += (k1 & mm).sum() * px
            acc[_key("size", S)]["comm"] += (k1 & ~mm).sum() * px
            acc[_key("size", S)]["mapped"] += k1.sum() * px
            # mode: size + land adjacency
            keep_land = touches_land[lbl]
            k2 = keep_size & keep_land
            acc[_key("size+land", S)]["cap"] += (k2 & mm).sum() * px
            acc[_key("size+land", S)]["comm"] += (k2 & ~mm).sum() * px
            acc[_key("size+land", S)]["mapped"] += k2.sum() * px

    rows = []
    for (mode, S), d in acc.items():
        mapped = d["mapped"]
        prec = (1 - d["comm"] / mapped) if mapped > 0 else np.nan
        rows.append({
            "mode": mode, "min_size_px": S,
            "captured_km2": d["cap"], "commission_km2": d["comm"],
            "mapped_km2": mapped, "precision": prec,
        })
    df = pd.DataFrame(rows).sort_values(["mode", "min_size_px"]).reset_index(drop=True)
    out = resolve_path("data/outputs/tables/spatial_constraint_sweep.csv")
    df.to_csv(out, index=False, float_format="%.2f")
    print(f"Tiles processed: {n_tiles}")
    print(df.to_string(index=False, float_format="%.2f"))
    print("Wrote", out)

    # Trade-off plot: captured (recall) vs commission.
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    for mode, marker in [("size", "o"), ("size+land", "s")]:
        sub = df[df["mode"] == mode]
        ax.plot(sub["commission_km2"], sub["captured_km2"],
                marker=marker, label=mode)
        for _, r in sub.iterrows():
            ax.annotate(f"S={int(r.min_size_px)}",
                        (r["commission_km2"], r["captured_km2"]),
                        fontsize=7, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("commission area outside MOF (km²)  →  worse precision")
    ax.set_ylabel("captured area inside MOF (km²)  →  better recall")
    ax.set_title("Spatial-coherence constraint: recall vs commission")
    ax.legend()
    fig.tight_layout()
    out_fig = resolve_path("data/outputs/figures/spatial_constraint_tradeoff.png")
    fig.savefig(out_fig, dpi=140)
    print("Wrote", out_fig)


if __name__ == "__main__":
    main()
