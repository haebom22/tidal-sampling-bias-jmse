"""Phase 5: aggregate all CSVs into one summary table + generate 6 figures.

Figures produced (per plan §7):
  1. data/outputs/figures/pilot_fused_extent.png
     — 5-site fused extent maps with 3-tier colour coding.
  2. data/outputs/figures/area_scatter_blandaltman.png      (from Phase 3)
  3. data/outputs/figures/v1_vs_v4_phase_bars.png
     — Phase bias correction effect (V1 vs V4 mean area per site).
  4. data/outputs/figures/obsfreq_raw_vs_corrected.png
     — Per-site raw vs obs-frequency-corrected time series.
  5. data/outputs/figures/national_area_map_2024.png
     — Wall-to-wall national tidal-flat area for 2024 epoch.
  6. data/outputs/figures/region_year_heatmap.png
     — Province × year heatmap of tidal-flat area.

The script gracefully skips a figure if its input CSV/raster is missing.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.extent import TIER_DEM_ONLY, TIER_HIGH, TIER_MSIC_ONLY
from src.config import resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("phase5")


# ---------------------------------------------------------------------------
# Figure 1: pilot fused extent (3-tier)
# ---------------------------------------------------------------------------

def _figure_pilot_extents(year: int, out_path: Path) -> None:
    import matplotlib.pyplot as plt
    import rasterio
    from matplotlib.colors import ListedColormap

    sites_all = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]
    fig, axes = plt.subplots(1, len(sites_all), figsize=(4 * len(sites_all), 5))
    cmap = ListedColormap(["#f0f0f0", "#1b7837", "#dfc27d", "#c2a5cf"])  # reject, T1, T2, T3
    any_drawn = False
    for ax, site in zip(axes, sites_all):
        tif = resolve_path(f"data/outputs/extent/{site}_fused_{year}.tif")
        if not tif.exists():
            ax.set_title(f"{site} (missing)")
            ax.set_axis_off()
            continue
        with rasterio.open(tif) as src:
            arr = src.read(1)
            extent = (
                src.bounds.left, src.bounds.right,
                src.bounds.bottom, src.bounds.top,
            )
        ax.imshow(arr, cmap=cmap, vmin=0, vmax=3, extent=extent, origin="upper")
        ax.set_title(site)
        ax.set_aspect("equal")
        any_drawn = True

    if not any_drawn:
        plt.close(fig)
        return
    # legend
    from matplotlib.patches import Patch
    legend_elems = [
        Patch(facecolor="#1b7837", label="Tier 1 (DEM∩MSIC∩QA)"),
        Patch(facecolor="#dfc27d", label="Tier 2 (DEM only)"),
        Patch(facecolor="#c2a5cf", label="Tier 3 (MSIC only)"),
    ]
    fig.legend(handles=legend_elems, loc="lower center", ncol=3, frameon=False)
    fig.suptitle(f"Pilot fused tidal-flat extent — {year}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Figure 3: V1 vs V4 phase-bias bars
# ---------------------------------------------------------------------------

def _figure_v1_vs_v4(out_path: Path) -> None:
    """Compare V1 (uncorrected, optical-only) vs V4 mean areas per site."""
    import matplotlib.pyplot as plt

    annual = resolve_path("data/outputs/tables/annual_area_5sites.csv")
    if not annual.exists():
        log.warning("missing %s — skip figure 3", annual)
        return
    df = pd.read_csv(annual)

    summary = resolve_path("data/outputs/tables/annual_v4_dem_summary.csv")
    if summary.exists():
        s = pd.read_csv(summary)
        v1_areas = s[s["variant"] == "v1"] if "variant" in s.columns else pd.DataFrame()
    else:
        v1_areas = pd.DataFrame()

    by_site = df.groupby("site_id")["total_km2"].mean().reset_index()
    sites = by_site["site_id"].tolist()
    v4_means = by_site["total_km2"].tolist()
    v1_means = [
        float(v1_areas.loc[v1_areas["site_id"] == s, "n_total_scenes"].mean())
        if not v1_areas.empty and (v1_areas["site_id"] == s).any()
        else np.nan
        for s in sites
    ]

    fig, ax = plt.subplots(figsize=(max(6, 1.5 * len(sites)), 4))
    x = np.arange(len(sites))
    width = 0.35
    ax.bar(x - width / 2, v1_means, width=width, label="V1 (optical, raw)")
    ax.bar(x + width / 2, v4_means, width=width, label="V4 (multi-sensor, bias-corrected)")
    ax.set_xticks(x)
    ax.set_xticklabels(sites)
    ax.set_ylabel("mean area (km²)")
    ax.set_title("Phase-bias correction effect: V1 vs V4")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Figure 4: obs-frequency raw vs corrected time series
# ---------------------------------------------------------------------------

def _figure_obsfreq(out_path: Path) -> None:
    import matplotlib.pyplot as plt

    p = resolve_path("data/outputs/tables/annual_area_5sites_corrected.csv")
    if not p.exists():
        log.warning("missing %s — skip figure 4", p)
        return
    df = pd.read_csv(p)
    area_cols = [c for c in df.columns if c.endswith("_km2") and not c.endswith("_corrected")]
    base_col = next((c for c in ("total_km2", "area_dem_km2") if c in area_cols), area_cols[0])
    corrected_col = f"{base_col}_corrected"
    if corrected_col not in df.columns:
        log.warning("no corrected column — skip figure 4")
        return

    sites = sorted(df["site_id"].unique())
    fig, axes = plt.subplots(1, len(sites), figsize=(4 * len(sites), 3.5), sharey=False)
    if len(sites) == 1:
        axes = [axes]
    for ax, site in zip(axes, sites):
        sub = df[df["site_id"] == site].sort_values("year")
        ax.plot(sub["year"], sub[base_col], "o-", label="raw")
        ax.plot(sub["year"], sub[corrected_col], "s--", label="corrected")
        ax.set_title(site)
        ax.set_xlabel("year")
        ax.set_ylabel("area (km²)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Figure 5: national area map (single epoch) using the DEM VRT
# ---------------------------------------------------------------------------

def _figure_national_map(year: int, out_path: Path) -> None:
    import matplotlib.pyplot as plt
    import rasterio

    vrt = resolve_path(f"data/outputs/national/vrt/national_dem_{year}.vrt")
    if not vrt.exists():
        log.warning("missing %s — skip figure 5", vrt)
        return
    with rasterio.open(vrt) as src:
        dem = src.read(1, masked=True).filled(np.nan)
        extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)

    fig, ax = plt.subplots(figsize=(10, 12))
    img = ax.imshow(
        dem, cmap="terrain", vmin=-3.0, vmax=5.0, extent=extent, origin="upper",
    )
    ax.set_title(f"Korean peninsula tidal-flat DEM — {year}")
    ax.set_xlabel("longitude (°E)")
    ax.set_ylabel("latitude (°N)")
    plt.colorbar(img, ax=ax, label="elevation (m, chart datum)", shrink=0.7)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Figure 6: province × year heatmap
# ---------------------------------------------------------------------------

def _figure_region_heatmap(out_path: Path) -> None:
    import matplotlib.pyplot as plt

    p = resolve_path("data/outputs/tables/annual_area_national_by_region.csv")
    if not p.exists():
        log.warning("missing %s — skip figure 6", p)
        return
    df = pd.read_csv(p)
    pivot = df.pivot_table(
        index="province", columns="year",
        values="area_km2_dem", aggfunc="sum",
    ).fillna(0.0)
    if pivot.empty:
        return

    fig, ax = plt.subplots(figsize=(max(6, pivot.shape[1] * 0.6), max(4, pivot.shape[0] * 0.4)))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("year")
    ax.set_title("Tidal-flat area by province (km², DEM-based)")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            ax.text(
                j, i, f"{pivot.values[i, j]:.0f}",
                ha="center", va="center", fontsize=7,
                color="black" if pivot.values[i, j] < pivot.values.max() / 2 else "white",
            )
    plt.colorbar(im, ax=ax, shrink=0.7)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Combined CSV
# ---------------------------------------------------------------------------

def _build_consolidated_csv() -> None:
    out = resolve_path("data/outputs/tables/area_summary_master.csv")
    parts = []
    for name, source in (
        ("annual_5sites", "data/outputs/tables/annual_area_5sites.csv"),
        ("annual_5sites_corrected", "data/outputs/tables/annual_area_5sites_corrected.csv"),
        ("national_by_region", "data/outputs/tables/annual_area_national_by_region.csv"),
        ("reference_comparison", "data/outputs/tables/reference_comparison_5sites.csv"),
        ("uncertainty_budget", "data/outputs/tables/area_uncertainty_budget.csv"),
    ):
        p = resolve_path(source)
        if not p.exists():
            log.warning("master CSV: missing %s", source)
            continue
        df = pd.read_csv(p)
        df["__table__"] = name
        parts.append(df)
    if not parts:
        log.warning("master CSV: no inputs available")
        return
    merged = pd.concat(parts, ignore_index=True, sort=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out, index=False)
    log.info("Wrote %s (%d rows)", out, len(merged))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fig1-year", type=int, default=2024)
    p.add_argument("--fig5-year", type=int, default=2024)
    p.add_argument("--no-figures", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    fig_dir = resolve_path("data/outputs/figures")
    fig_dir.mkdir(parents=True, exist_ok=True)

    _build_consolidated_csv()

    if args.no_figures:
        return

    _figure_pilot_extents(args.fig1_year, fig_dir / "pilot_fused_extent.png")
    _figure_v1_vs_v4(fig_dir / "v1_vs_v4_phase_bars.png")
    _figure_obsfreq(fig_dir / "obsfreq_raw_vs_corrected.png")
    _figure_national_map(args.fig5_year, fig_dir / "national_area_map_2024.png")
    _figure_region_heatmap(fig_dir / "region_year_heatmap.png")
    log.info("Phase 5 done.")


if __name__ == "__main__":
    main()
