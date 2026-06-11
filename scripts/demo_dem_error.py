"""B-5: Translate tidal-sampling bias into waterline-DEM elevation error.

Methodology
-----------
For each (site, sensor), the bias in the satellite tide-height *distribution*
is mapped quantile-by-quantile into the elevation domain:

    error(p) = Q_sat(p) - Q_ref(p)        p ∈ [0.005, 0.995]

This yields a continuous DEM-error curve.  Aggregate metrics
(mean_bias, RMSE, max_abs_error, truncated low/high bands) summarise
the practical impact.  Vertical errors are also converted to
*horizontal contour displacement* using site-specific assumed tidal-
flat slopes (see ``config/settings.yaml`` → ``dem_error``).

Outputs
-------
    data/outputs/tables/dem_error_stats.csv
    data/outputs/tables/dem_error_curves.parquet
    data/outputs/figures/dem_error_curves.png       (5×3 panel grid)
    data/outputs/figures/dem_error_truncation.png
    data/outputs/figures/dem_error_horizontal.png
    data/outputs/figures/dem_error_schematic.png
"""

from __future__ import annotations

import logging
import warnings
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from src.analysis.dem_error import (
    DemErrorCurve,
    dem_error_stats,
    horizontal_equivalent,
    quantile_error_curve,
)
from src.config import load_settings, load_sites
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times
from src.visualization.plots import SENSOR_COLORS

warnings.filterwarnings("ignore", category=UserWarning,
                        message="no explicit representation of timezones")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("dem_error")


YEAR_START, YEAR_END = 2020, 2024
CLOUD_THRESHOLD = 60

GEE_DIR = Path("data/raw/gee_metadata")
KHOA_DIR = Path("data/raw/khoa")
PROCESSED_DIR = Path("data/processed")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")

SITE_ORDER = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]
SENSORS = ["L8", "L9", "S2"]


# ---------------------------------------------------------------------------
# Load data per site
# ---------------------------------------------------------------------------

def load_site_data(site) -> dict | None:
    sc_path = GEE_DIR / f"{site.id}_scenes.parquet"
    if not sc_path.exists():
        return None
    scenes = pd.read_parquet(sc_path)
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
    scenes = scenes[scenes["datetime_utc"].dt.year.between(YEAR_START, YEAR_END)]
    scenes = scenes[scenes["cloud_cover"] <= CLOUD_THRESHOLD].copy()
    if scenes.empty:
        return None

    station = site.khoa_stations[0]
    obs = fetch_tide_hourly_range(
        station.code, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
    )
    if obs.empty:
        return None
    scenes["tide_m"] = interpolate_at_times(obs, scenes["datetime_utc"]).values
    scenes = scenes.dropna(subset=["tide_m"]).copy()
    return {"site": site, "scenes": scenes, "obs": obs, "station": station}


# ---------------------------------------------------------------------------
# Build per-(site, sensor) DEM error stats and curves
# ---------------------------------------------------------------------------

def per_site_sensor_metrics(per_site, slopes) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    curve_rows = []
    for sid, info in per_site.items():
        scenes = info["scenes"]
        obs = info["obs"]
        slope = slopes.get(sid)
        ref = obs["tide_m"].to_numpy()
        for sensor, sub in scenes.groupby("sensor"):
            sat = sub["tide_m"].to_numpy()
            curve = quantile_error_curve(ref, sat)
            stats = dem_error_stats(ref, sat, curve)
            d = stats.as_dict()
            d.update({
                "site_id": sid,
                "site_name": info["site"].name_en,
                "tidal_range_m_assumed": float(info["site"].tidal_range_m),
                "sensor": sensor,
                "slope_assumed": slope,
                "rmse_horizontal_m": horizontal_equivalent(stats.rmse_m, slope),
                "mean_bias_horizontal_m": horizontal_equivalent(stats.mean_bias_m, slope),
                "trunc_low_horizontal_m": horizontal_equivalent(stats.truncated_low_m, slope),
                "trunc_high_horizontal_m": horizontal_equivalent(stats.truncated_high_m, slope),
            })
            rows.append(d)
            cdf_df = curve.as_dataframe()
            cdf_df["site_id"] = sid
            cdf_df["sensor"] = sensor
            curve_rows.append(cdf_df)
    stats_df = pd.DataFrame(rows)
    curves_df = pd.concat(curve_rows, ignore_index=True) if curve_rows else pd.DataFrame()
    cols_order = ["site_id", "site_name", "sensor", "n_sat", "n_ref",
                  "elevation_range_m", "mean_bias_m", "rmse_m",
                  "max_abs_error_m", "median_error_m",
                  "truncated_low_m", "truncated_high_m",
                  "truncated_low_frac", "truncated_high_frac",
                  "slope_assumed",
                  "rmse_horizontal_m", "mean_bias_horizontal_m",
                  "trunc_low_horizontal_m", "trunc_high_horizontal_m"]
    return stats_df[cols_order], curves_df


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_error_curves(curves: pd.DataFrame, stats: pd.DataFrame, out_path: Path) -> None:
    sites = [s for s in SITE_ORDER if s in curves["site_id"].unique()]
    cols = min(3, len(sites))
    rows = int(np.ceil(len(sites) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.6 * rows))
    axes = np.array(axes).reshape(-1)

    for ax, sid in zip(axes, sites):
        sub_curves = curves[curves["site_id"] == sid]
        sub_stats = stats[stats["site_id"] == sid]
        for sensor in sorted(sub_curves["sensor"].unique()):
            cv = sub_curves[sub_curves["sensor"] == sensor]
            ax.plot(cv["z_ref"], cv["error_m"],
                    color=SENSOR_COLORS.get(sensor, "gray"), linewidth=1.8,
                    label=f"{sensor}  RMSE={sub_stats[sub_stats.sensor==sensor]['rmse_m'].iloc[0]:.2f} m")
        ax.axhline(0, color="black", linewidth=0.6, linestyle="--")
        ax.set_xlabel("Elevation (m, KHOA datum)")
        ax.set_ylabel("DEM elevation error (m): z_sat − z_ref")
        site_name = sub_stats["site_name"].iloc[0] if not sub_stats.empty else sid
        ax.set_title(site_name, fontsize=11)
        ax.grid(alpha=0.3)
        ax.legend(frameon=False, fontsize=9, loc="best")
    for i in range(len(sites), len(axes)):
        axes[i].axis("off")
    fig.suptitle("Quantile-mapping DEM elevation error per (site × sensor) — 2020-2024",
                 y=1.0, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_truncation(stats: pd.DataFrame, out_path: Path) -> None:
    """Stacked bar of vertical truncation per site (mean across sensors)."""
    grouped = stats.groupby("site_id").agg(
        trunc_low=("truncated_low_m", "mean"),
        trunc_high=("truncated_high_m", "mean"),
        elev_range=("elevation_range_m", "first"),
        slope=("slope_assumed", "first"),
        site_name=("site_name", "first"),
    ).reindex(SITE_ORDER)

    fig, ax = plt.subplots(figsize=(10, 5.2))
    x = np.arange(len(grouped))
    sampled = grouped["elev_range"] - grouped["trunc_low"] - grouped["trunc_high"]

    ax.bar(x, grouped["trunc_low"], color="#3b8da6",
           edgecolor="black", linewidth=0.4, label="Low-tide truncation (missing band)")
    ax.bar(x, sampled, bottom=grouped["trunc_low"], color="lightgray",
           edgecolor="black", linewidth=0.4, label="Sampled range (recoverable DEM)")
    ax.bar(x, grouped["trunc_high"], bottom=grouped["trunc_low"] + sampled,
           color="#d65f5f", edgecolor="black", linewidth=0.4,
           label="High-tide truncation (missing band)")

    for xi, row in zip(x, grouped.itertuples()):
        # Annotate vertical extents
        if row.trunc_low > 0.05:
            ax.text(xi, row.trunc_low / 2, f"{row.trunc_low:.2f} m",
                    ha="center", va="center", fontsize=9, color="white")
        ax.text(xi, row.trunc_low + sampled.iloc[xi] / 2,
                f"{sampled.iloc[xi]:.2f} m", ha="center", va="center", fontsize=9)
        if row.trunc_high > 0.05:
            ax.text(xi, row.trunc_low + sampled.iloc[xi] + row.trunc_high / 2,
                    f"{row.trunc_high:.2f} m", ha="center", va="center",
                    fontsize=9, color="white")

    ax.set_xticks(x)
    ax.set_xticklabels([
        f"{sid}\n(slope≈{grouped.loc[sid, 'slope']*1000:.1f} m/km)"
        for sid in grouped.index
    ], fontsize=9)
    ax.set_ylabel("Vertical extent of intertidal range (m)")
    ax.set_title("Waterline-DEM coverage: sampled vs truncated elevation bands\n"
                 "(mean across L8/L9/S2 sensors, 2020-2024)")
    ax.legend(frameon=False, fontsize=10, loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_horizontal_equivalent(stats: pd.DataFrame, out_path: Path) -> None:
    grouped = stats.groupby("site_id").agg(
        rmse_z=("rmse_m", "mean"),
        bias_z=("mean_bias_m", "mean"),
        rmse_x=("rmse_horizontal_m", "mean"),
        bias_x=("mean_bias_horizontal_m", "mean"),
        trunc_low_x=("trunc_low_horizontal_m", "mean"),
        trunc_high_x=("trunc_high_horizontal_m", "mean"),
        slope=("slope_assumed", "first"),
        site_name=("site_name", "first"),
    ).reindex(SITE_ORDER)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.0))

    ax = axes[0]
    x = np.arange(len(grouped))
    w = 0.35
    ax.bar(x - w / 2, grouped["rmse_z"], w, color="#7a52a3",
           edgecolor="black", label="RMSE (vertical, m)")
    ax.bar(x + w / 2, np.abs(grouped["bias_z"]), w, color="#d65f5f",
           edgecolor="black", label="|mean bias| (vertical, m)")
    for xi, (rmse, bias) in enumerate(zip(grouped["rmse_z"], grouped["bias_z"])):
        ax.text(xi - w / 2, rmse + 0.02, f"{rmse:.2f}", ha="center", fontsize=8)
        ax.text(xi + w / 2, abs(bias) + 0.02, f"{bias:+.2f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(grouped.index, fontsize=10)
    ax.set_ylabel("Elevation error (m)")
    ax.set_title("Vertical DEM error")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    ax.bar(x - w / 2, grouped["rmse_x"], w, color="#7a52a3",
           edgecolor="black", label="RMSE (horizontal, m)")
    ax.bar(x + w / 2, np.abs(grouped["bias_x"]), w, color="#d65f5f",
           edgecolor="black", label="|mean bias| (horizontal, m)")
    for xi, (rmse, bias) in enumerate(zip(grouped["rmse_x"], grouped["bias_x"])):
        ax.text(xi - w / 2, rmse + 5, f"{rmse:.0f} m", ha="center", fontsize=8)
        ax.text(xi + w / 2, abs(bias) + 5, f"{bias:+.0f} m", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([
        f"{sid}\n(slope {grouped.loc[sid, 'slope']*1000:.1f} m/km)"
        for sid in grouped.index
    ], fontsize=9)
    ax.set_ylabel("Horizontal contour displacement (m)")
    ax.set_title("Horizontal-equivalent error (= z-error / slope)")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Waterline-DEM error per site — mean across sensors",
                 y=1.02, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_schematic(stats: pd.DataFrame, out_path: Path) -> None:
    """Illustrate the truncation on a planar tidal flat cross-section.

    For each site we draw a slope of `slope_assumed`, mark the KHOA-derived
    elevation range, and shade the truncated (un-sampled) bands.
    """
    sites = [s for s in SITE_ORDER if s in stats["site_id"].unique()]
    fig, axes = plt.subplots(len(sites), 1, figsize=(11, 1.6 * len(sites)),
                             sharex=False, sharey=False)
    if len(sites) == 1:
        axes = [axes]
    for ax, sid in zip(axes, sites):
        sub = stats[stats["site_id"] == sid]
        slope = float(sub["slope_assumed"].iloc[0])
        elev_lo = float(sub["mean_bias_m"].iloc[0])  # placeholder
        elev_range = float(sub["elevation_range_m"].iloc[0])
        trunc_lo = float(sub["truncated_low_m"].mean())
        trunc_hi = float(sub["truncated_high_m"].mean())

        # Build the cross section: from x=0 (low) to x=elev_range/slope (high)
        x_max = elev_range / slope
        xs = np.linspace(0, x_max, 200)
        zs = slope * xs

        ax.plot(xs / 1000, zs, color="#5e4633", linewidth=2.4, label="Tidal flat (planar)")
        ax.fill_between(xs / 1000, 0, zs, color="#d4b896", alpha=0.4)

        # Sampled band: between truncated_low and truncated_high
        z_min_sampled = trunc_lo
        z_max_sampled = elev_range - trunc_hi
        x_min_sampled = z_min_sampled / slope / 1000
        x_max_sampled = z_max_sampled / slope / 1000
        ax.axvspan(x_min_sampled, x_max_sampled, color="lightgreen", alpha=0.4,
                   label=f"Sampled band ({z_min_sampled:.2f}–{z_max_sampled:.2f} m)")
        if trunc_lo > 0:
            ax.axvspan(0, x_min_sampled, color="#3b8da6", alpha=0.4,
                       label=f"Low-trunc {trunc_lo:.2f} m vert / {trunc_lo/slope:.0f} m horiz")
        if trunc_hi > 0:
            ax.axvspan(x_max_sampled, x_max / 1000, color="#d65f5f", alpha=0.4,
                       label=f"High-trunc {trunc_hi:.2f} m vert / {trunc_hi/slope:.0f} m horiz")
        ax.set_xlim(0, x_max / 1000)
        ax.set_ylim(0, max(elev_range * 1.05, 0.5))
        ax.set_xlabel("Cross-shore distance (km)" if ax is axes[-1] else "")
        ax.set_ylabel("Elev (m)")
        ax.set_title(f"{sub['site_name'].iloc[0]} — slope ≈ {slope*1000:.1f} m/km, "
                     f"elev range {elev_range:.2f} m",
                     fontsize=9, loc="left")
        ax.legend(fontsize=7, frameon=False, loc="upper left")
        ax.grid(alpha=0.3)

    fig.suptitle("Planar tidal-flat cross-sections: sampled vs missing elevation bands",
                 y=1.0, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    settings = load_settings()
    slopes_cfg = settings.get("dem_error", {})
    site_slopes = slopes_cfg.get("site_slopes", {})
    default_slope = float(slopes_cfg.get("default_slope", 0.001))

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGS_DIR.mkdir(parents=True, exist_ok=True)

    sites = sorted(load_sites(),
                   key=lambda s: SITE_ORDER.index(s.id) if s.id in SITE_ORDER else 99)
    per_site = {}
    for site in sites:
        info = load_site_data(site)
        if info is None:
            log.warning("Skipping %s", site.id)
            continue
        per_site[site.id] = info
        log.info("Loaded %s: %d scenes, %d KHOA rows", site.id,
                 len(info["scenes"]), len(info["obs"]))

    if not per_site:
        log.error("No sites loaded")
        return

    slopes = {sid: float(site_slopes.get(sid, default_slope)) for sid in per_site}
    log.info("Site slopes (m/m): %s", slopes)

    stats_df, curves_df = per_site_sensor_metrics(per_site, slopes)
    stats_df.to_csv(TABLES_DIR / "dem_error_stats.csv",
                    index=False, float_format="%.4f")
    curves_df.to_parquet(PROCESSED_DIR / "dem_error_curves.parquet", index=False)
    log.info("Wrote dem_error_stats.csv (%d rows) and dem_error_curves.parquet (%d rows)",
             len(stats_df), len(curves_df))

    plot_error_curves(curves_df, stats_df, FIGS_DIR / "dem_error_curves.png")
    plot_truncation(stats_df, FIGS_DIR / "dem_error_truncation.png")
    plot_horizontal_equivalent(stats_df, FIGS_DIR / "dem_error_horizontal.png")
    plot_schematic(stats_df, FIGS_DIR / "dem_error_schematic.png")

    print()
    print("=" * 110)
    print("DEM-ERROR per (site × sensor) — 2020-2024")
    print("=" * 110)
    cols = ["site_id", "sensor", "n_sat", "elevation_range_m",
            "mean_bias_m", "rmse_m", "max_abs_error_m",
            "truncated_low_m", "truncated_high_m",
            "slope_assumed", "rmse_horizontal_m",
            "trunc_low_horizontal_m", "trunc_high_horizontal_m"]
    print(stats_df[cols].to_string(index=False,
                                   float_format=lambda v: f"{v:+.4f}"))


if __name__ == "__main__":
    main()
