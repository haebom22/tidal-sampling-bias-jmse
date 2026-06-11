"""Multi-site tidal aliasing analysis: 5 Korean tidal flats, 2020-2024.

Couples each site's GEE scene metadata with its nearest KHOA tide gauge,
computes aliasing statistics, and produces:

    1. Per-site distribution / CDF figures (reuse 5-year style)
    2. Combined comparison panels across sites
    3. Cross-site summary table (site x sensor)
    4. Latitude / tidal-range gradient plot

The site -> KHOA station mapping uses the *first* gauge listed in
``config/sites.yaml`` for each site.

Outputs:
    data/processed/multisite_5y_satellite_tides.parquet
    data/outputs/tables/multisite_5y_overall.csv
    data/outputs/figures/multisite_5y_distribution_grid.png
    data/outputs/figures/multisite_5y_cdf_grid.png
    data/outputs/figures/multisite_5y_gradient.png
    data/outputs/figures/multisite_5y_overpass_phase.png
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analysis.aliasing import compute_aliasing
from src.config import Site, load_sites
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times
from src.visualization.plots import SENSOR_COLORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("multisite_5y")


YEAR_START, YEAR_END = 2020, 2024
CLOUD_THRESHOLD = 60

GEE_DIR = Path("data/raw/gee_metadata")
KHOA_DIR = Path("data/raw/khoa")
PROCESSED_DIR = Path("data/processed")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_site_scenes(site: Site) -> pd.DataFrame:
    path = GEE_DIR / f"{site.id}_scenes.parquet"
    if not path.exists():
        log.warning("Missing GEE metadata for %s -- skipping", site.id)
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    df = df[df["datetime_utc"].dt.year.between(YEAR_START, YEAR_END)]
    df = df[df["cloud_cover"] <= CLOUD_THRESHOLD].copy()
    df["site_id"] = site.id
    df["site_name"] = site.name_en
    df["year"] = df["datetime_utc"].dt.year
    df["month"] = df["datetime_utc"].dt.month
    df["hour_kst"] = (df["datetime_utc"] + pd.Timedelta(hours=9)).dt.hour
    return df


def load_site_khoa(site: Site) -> tuple[pd.DataFrame, str]:
    station = site.khoa_stations[0]
    obs = fetch_tide_hourly_range(
        station.code, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
    )
    obs["year"] = obs["datetime_utc"].dt.year
    obs = obs[obs["year"].between(YEAR_START, YEAR_END)].copy()
    label = f"{station.name_en} ({station.code})"
    return obs, label


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

OUT_COLS = ["site_id", "site_name", "lat", "tidal_range_m", "sensor", "n_obs",
            "obs_min", "obs_max", "spread", "low_offset", "high_offset",
            "ks_statistic", "ks_pvalue", "mean_bias"]


def site_stats(site: Site, scenes: pd.DataFrame, ref: np.ndarray) -> pd.DataFrame:
    rows = []
    for sensor, sub in scenes.groupby("sensor"):
        st = compute_aliasing(sub["tide_m"].to_numpy(), ref, n_bins=40)
        d = st.as_dict()
        d.update({
            "site_id": site.id,
            "site_name": site.name_en,
            "lat": float(site.center["lat"]),
            "tidal_range_m": float(site.tidal_range_m),
            "sensor": sensor,
        })
        rows.append(d)
    return pd.DataFrame(rows)[OUT_COLS]


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_distribution_grid(
    per_site: dict[str, dict],
    out_path: Path,
) -> None:
    sites = list(per_site)
    n = len(sites)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.6 * rows), sharex=False)
    axes = np.array(axes).reshape(-1)

    for idx, sid in enumerate(sites):
        ax = axes[idx]
        info = per_site[sid]
        ref = info["ref"]
        scenes = info["scenes"]
        ref_min, ref_max = float(np.nanmin(ref)), float(np.nanmax(ref))
        edges = np.linspace(ref_min, ref_max, 31)
        ref_hist, _ = np.histogram(ref, bins=edges, density=True)
        ax.fill_between(edges[:-1], 0, ref_hist, step="post",
                        color="lightgray", alpha=0.8,
                        label=f"KHOA {info['station_label']}")
        for sensor in sorted(scenes["sensor"].unique()):
            sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna()
            if sub.empty:
                continue
            ax.hist(sub, bins=edges, density=True, histtype="step",
                    linewidth=1.6,
                    color=SENSOR_COLORS.get(sensor, "gray"),
                    label=f"{sensor} (n={len(sub)})")
        ax.set_title(f"{info['site_name']}  (tidal range ~{info['tidal_range_m']:.0f} m)",
                     fontsize=10)
        ax.set_xlabel("Tide height (m)")
        ax.set_ylabel("Density")
        ax.legend(frameon=False, fontsize=7, loc="upper right")
        ax.grid(alpha=0.3)
    for i in range(n, len(axes)):
        axes[i].axis("off")
    fig.suptitle(f"Tidal sampling distribution by site — 2020-2024", y=1.0, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_cdf_grid(per_site: dict[str, dict], out_path: Path) -> None:
    sites = list(per_site)
    n = len(sites)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.6 * rows))
    axes = np.array(axes).reshape(-1)
    for idx, sid in enumerate(sites):
        ax = axes[idx]
        info = per_site[sid]
        ref = info["ref"]
        scenes = info["scenes"]
        ref_sorted = np.sort(ref[~np.isnan(ref)])
        cdf_ref = np.arange(1, len(ref_sorted) + 1) / len(ref_sorted)
        ax.plot(ref_sorted, cdf_ref, color="black", linewidth=1.4,
                label=f"KHOA {info['station_label']}")
        for sensor in sorted(scenes["sensor"].unique()):
            sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna().to_numpy()
            if len(sub) == 0:
                continue
            s_sorted = np.sort(sub)
            cdf = np.arange(1, len(s_sorted) + 1) / len(s_sorted)
            ax.plot(s_sorted, cdf, color=SENSOR_COLORS.get(sensor, "gray"),
                    linewidth=1.6, label=f"{sensor} (n={len(sub)})")
        ax.set_title(f"{info['site_name']}", fontsize=10)
        ax.set_xlabel("Tide height (m)")
        ax.set_ylabel("Cumulative probability")
        ax.legend(frameon=False, fontsize=7, loc="lower right")
        ax.grid(alpha=0.3)
    for i in range(n, len(axes)):
        axes[i].axis("off")
    fig.suptitle("CDF of sampled tides by site — 2020-2024", y=1.0, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_gradient(stats: pd.DataFrame, out_path: Path) -> None:
    site_order = (
        stats.groupby("site_id")["lat"].first().sort_values(ascending=False).index.tolist()
    )
    sensors = sorted(stats["sensor"].unique())

    fig, axes = plt.subplots(1, 4, figsize=(16, 4.2))
    metrics = [
        ("spread", "Spread", (0.5, 1.0), False),
        ("high_offset", "High-tide offset", (0, 0.45), False),
        ("low_offset", "Low-tide offset", (0, 0.45), False),
        ("mean_bias", "Mean bias (m): obs − ref", None, True),
    ]
    x = np.arange(len(site_order))
    width = 0.8 / max(1, len(sensors))
    for ax, (col, label, ylim, signed) in zip(axes, metrics):
        for i, sensor in enumerate(sensors):
            vals = []
            for sid in site_order:
                v = stats[(stats["site_id"] == sid) & (stats["sensor"] == sensor)][col]
                vals.append(float(v.iloc[0]) if len(v) else np.nan)
            ax.bar(x + i * width, vals, width=width,
                   color=SENSOR_COLORS.get(sensor, "gray"),
                   edgecolor="black", linewidth=0.4,
                   label=sensor if ax is axes[0] else None)
        ax.set_xticks(x + (len(sensors) - 1) * width / 2)
        ax.set_xticklabels([
            f"{sid}\n({stats[stats.site_id==sid]['tidal_range_m'].iloc[0]:.0f}m)"
            for sid in site_order
        ], fontsize=8, rotation=0)
        ax.set_ylabel(label)
        if ylim:
            ax.set_ylim(*ylim)
        if signed:
            ax.axhline(0, color="black", linewidth=0.7, linestyle="--", alpha=0.5)
        ax.grid(alpha=0.3, axis="y")
    axes[0].legend(frameon=False, fontsize=9, loc="lower right")
    fig.suptitle(
        "Cross-site aliasing comparison — N→S along Korean west/south coast (label: site, mean spring range)",
        y=1.02, fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_overpass_phase(per_site: dict[str, dict], out_path: Path) -> None:
    """Hour-of-day KST distribution per site, all sensors stacked."""
    sites = list(per_site)
    n = len(sites)
    fig, axes = plt.subplots(1, n, figsize=(3.2 * n, 3.5), sharey=True)
    if n == 1:
        axes = [axes]
    bins = np.arange(-0.5, 24.5)
    for ax, sid in zip(axes, sites):
        scenes = per_site[sid]["scenes"]
        bottom = np.zeros(24, dtype=int)
        for sensor in sorted(scenes["sensor"].unique()):
            sub = scenes[scenes["sensor"] == sensor]
            hist, _ = np.histogram(sub["hour_kst"], bins=bins)
            ax.bar(np.arange(24), hist, bottom=bottom, width=0.9,
                   color=SENSOR_COLORS.get(sensor, "gray"),
                   edgecolor="black", linewidth=0.2,
                   label=f"{sensor}")
            bottom += hist
        ax.set_title(per_site[sid]["site_name"], fontsize=10)
        ax.set_xlabel("Hour of day (KST)")
        ax.set_xticks([0, 6, 12, 18])
        if ax is axes[0]:
            ax.set_ylabel("Scene count")
        ax.grid(alpha=0.3, axis="y")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("Satellite overpass time (KST) across sites — 2020-2024",
                 y=1.02, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sites = load_sites()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGS_DIR.mkdir(parents=True, exist_ok=True)

    per_site: dict[str, dict] = {}
    all_scenes_with_tide: list[pd.DataFrame] = []
    stats_rows: list[pd.DataFrame] = []

    for site in sites:
        log.info("=== %s (%s) ===", site.id, site.name_en)
        scenes = load_site_scenes(site)
        if scenes.empty:
            log.warning("Skipping %s: no GEE metadata", site.id)
            continue
        obs, station_label = load_site_khoa(site)
        if obs.empty:
            log.warning("Skipping %s: no KHOA data", site.id)
            continue
        log.info("  scenes=%d  KHOA=%d (%s)  tide %.2f~%.2f m",
                 len(scenes), len(obs), station_label,
                 obs["tide_m"].min(), obs["tide_m"].max())

        scenes["tide_m"] = interpolate_at_times(obs, scenes["datetime_utc"]).values
        scenes = scenes.dropna(subset=["tide_m"])

        ref = obs["tide_m"].to_numpy()
        stats = site_stats(site, scenes, ref)
        stats_rows.append(stats)

        per_site[site.id] = {
            "site_id": site.id,
            "site_name": site.name_en,
            "lat": float(site.center["lat"]),
            "tidal_range_m": float(site.tidal_range_m),
            "station_label": station_label,
            "scenes": scenes,
            "ref": ref,
        }
        all_scenes_with_tide.append(scenes)

    if not stats_rows:
        log.error("No sites processed. Aborting.")
        return

    overall = pd.concat(stats_rows, ignore_index=True)
    overall.to_csv(TABLES_DIR / "multisite_5y_overall.csv",
                   index=False, float_format="%.4f")

    all_scenes = pd.concat(all_scenes_with_tide, ignore_index=True)
    all_scenes.to_parquet(PROCESSED_DIR / "multisite_5y_satellite_tides.parquet",
                          index=False)
    log.info("Wrote multisite_5y_satellite_tides.parquet (%d rows)", len(all_scenes))

    plot_distribution_grid(per_site, FIGS_DIR / "multisite_5y_distribution_grid.png")
    plot_cdf_grid(per_site, FIGS_DIR / "multisite_5y_cdf_grid.png")
    plot_gradient(overall, FIGS_DIR / "multisite_5y_gradient.png")
    plot_overpass_phase(per_site, FIGS_DIR / "multisite_5y_overpass_phase.png")

    print()
    print("=" * 100)
    print(f"MULTI-SITE 5-YEAR aliasing summary — {YEAR_START}-{YEAR_END}")
    print("=" * 100)
    cols = ["site_id", "tidal_range_m", "sensor", "n_obs", "spread",
            "low_offset", "high_offset", "mean_bias", "ks_statistic"]
    print(overall[cols].to_string(index=False))


if __name__ == "__main__":
    main()
