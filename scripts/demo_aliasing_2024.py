"""First-iteration tidal aliasing analysis: Ganghwa-do, 2024.

Inputs:
    data/raw/gee_metadata/ganghwa_scenes.parquet  (L8/L9/S2 scene metadata)
    data/raw/khoa/tide_hourly/                    (KHOA Incheon hourly tide)

Outputs:
    data/processed/ganghwa_2024_satellite_tides.parquet
    data/outputs/tables/ganghwa_2024_aliasing.csv
    data/outputs/figures/ganghwa_2024_distribution.png
    data/outputs/figures/ganghwa_2024_timeseries.png
    data/outputs/figures/ganghwa_2024_cdf.png

This is a demonstration of the methodology using KHOA observed hourly tide as
the *reference* (instead of FES2014). Hourly observations include weather
effects (storm surge, atmospheric pressure) but at one-year scale, the
astronomical signal dominates and the analysis result is meaningful.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

from src.analysis.aliasing import compute_aliasing
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times
from src.visualization.plots import SENSOR_COLORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("demo_aliasing_2024")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SITE_ID = "ganghwa"
STATION_CODE = "DT_0001"          # Incheon (nearest tide gauge for Ganghwa)
STATION_NAME = "Incheon"
YEAR = 2024
CLOUD_THRESHOLD = 60              # filter scenes with >60% cloud cover

GEE_PATH = Path("data/raw/gee_metadata/ganghwa_scenes.parquet")
KHOA_DIR = Path("data/raw/khoa")
PROCESSED_DIR = Path("data/processed")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")


# ---------------------------------------------------------------------------
# Stage 1: Load and prepare data
# ---------------------------------------------------------------------------

def load_satellite_metadata() -> pd.DataFrame:
    df = pd.read_parquet(GEE_PATH)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    df = df[(df["datetime_utc"].dt.year == YEAR)]
    df = df[df["cloud_cover"] <= CLOUD_THRESHOLD]
    log.info("Satellite scenes %d (year=%d, cloud<=%d)", len(df), YEAR, CLOUD_THRESHOLD)
    log.info("  by sensor: %s", df.groupby("sensor").size().to_dict())
    return df


def load_khoa_reference() -> pd.DataFrame:
    obs = fetch_tide_hourly_range(
        STATION_CODE, date(YEAR, 1, 1), date(YEAR, 12, 31), KHOA_DIR
    )
    log.info("KHOA reference %d rows; tide %.2f m ~ %.2f m",
             len(obs), obs["tide_m"].min(), obs["tide_m"].max())
    return obs


# ---------------------------------------------------------------------------
# Stage 2: Couple satellite times with KHOA tide
# ---------------------------------------------------------------------------

def attach_tide_to_scenes(scenes: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    out = scenes.copy()
    out["tide_m"] = interpolate_at_times(obs, out["datetime_utc"]).values
    n_missing = int(out["tide_m"].isna().sum())
    log.info("Interpolated tide: %d / %d (%d missing)",
             len(out) - n_missing, len(out), n_missing)
    return out.dropna(subset=["tide_m"])


# ---------------------------------------------------------------------------
# Stage 3: Aliasing statistics
# ---------------------------------------------------------------------------

def compute_stats(scenes: pd.DataFrame, reference: np.ndarray) -> pd.DataFrame:
    rows = []
    for sensor, sub in scenes.groupby("sensor"):
        st = compute_aliasing(sub["tide_m"].to_numpy(), reference, n_bins=40)
        d = st.as_dict()
        d.update({"sensor": sensor})
        rows.append(d)
    df = pd.DataFrame(rows)
    cols = ["sensor", "n_obs", "obs_min", "obs_max", "spread",
            "low_offset", "high_offset", "ks_statistic", "ks_pvalue",
            "mean_bias", "chi2_uniform"]
    return df[cols]


# ---------------------------------------------------------------------------
# Stage 4: Plotting
# ---------------------------------------------------------------------------

def plot_distribution(scenes: pd.DataFrame, ref: np.ndarray, out_path: Path) -> None:
    bins = 30
    ref_min, ref_max = float(np.nanmin(ref)), float(np.nanmax(ref))
    edges = np.linspace(ref_min, ref_max, bins + 1)

    fig, ax = plt.subplots(figsize=(8.5, 5))
    ref_hist, _ = np.histogram(ref, bins=edges, density=True)
    ax.fill_between(edges[:-1], 0, ref_hist, step="post", color="lightgray",
                    alpha=0.7, label=f"Reference (KHOA hourly, n={len(ref)})")

    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna()
        if sub.empty:
            continue
        ax.hist(sub, bins=edges, density=True, histtype="step",
                linewidth=2.0, color=SENSOR_COLORS.get(sensor, "gray"),
                label=f"{sensor} (n={len(sub)})")

    ax.set_xlabel("Tide height (m, KHOA datum)")
    ax.set_ylabel("Density")
    ax.set_title(f"Tidal sampling distribution — Ganghwa-do {YEAR}\n"
                 f"satellite scenes vs continuous KHOA observation at {STATION_NAME}")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    log.info("Wrote %s", out_path)


def plot_timeseries(scenes: pd.DataFrame, obs: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 4.5))
    ax.plot(obs["datetime_utc"], obs["tide_m"], color="lightgray",
            linewidth=0.4, alpha=0.8, label="KHOA hourly tide")
    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]
        ax.scatter(sub["datetime_utc"], sub["tide_m"], s=18, alpha=0.85,
                   color=SENSOR_COLORS.get(sensor, "gray"),
                   edgecolor="black", linewidth=0.3,
                   label=f"{sensor} (n={len(sub)})")
    ax.set_xlabel("2024 (UTC)")
    ax.set_ylabel("Tide height (m)")
    ax.set_title(f"Satellite acquisition tide heights — Ganghwa-do {YEAR}")
    ax.legend(frameon=False, ncols=4, fontsize=9, loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    log.info("Wrote %s", out_path)


def plot_cdf(scenes: pd.DataFrame, ref: np.ndarray, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5))

    ref_sorted = np.sort(ref[~np.isnan(ref)])
    cdf_ref = np.arange(1, len(ref_sorted) + 1) / len(ref_sorted)
    ax.plot(ref_sorted, cdf_ref, color="black", linewidth=1.5,
            label="Reference (KHOA hourly)")

    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna().to_numpy()
        if len(sub) == 0:
            continue
        s_sorted = np.sort(sub)
        cdf = np.arange(1, len(s_sorted) + 1) / len(s_sorted)
        ax.plot(s_sorted, cdf, color=SENSOR_COLORS.get(sensor, "gray"),
                linewidth=2.0, label=f"{sensor} (n={len(sub)})")

    ax.set_xlabel("Tide height (m)")
    ax.set_ylabel("Cumulative probability")
    ax.set_title(f"CDF of sampled tides — Ganghwa-do {YEAR}")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    scenes = load_satellite_metadata()
    obs = load_khoa_reference()

    scenes_with_tide = attach_tide_to_scenes(scenes, obs)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_scenes = PROCESSED_DIR / f"{SITE_ID}_{YEAR}_satellite_tides.parquet"
    scenes_with_tide.to_parquet(out_scenes, index=False)
    log.info("Wrote %s", out_scenes)

    ref = obs["tide_m"].to_numpy()
    stats = compute_stats(scenes_with_tide, ref)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    stats_path = TABLES_DIR / f"{SITE_ID}_{YEAR}_aliasing.csv"
    stats.to_csv(stats_path, index=False, float_format="%.4f")
    log.info("Wrote %s", stats_path)

    plot_distribution(scenes_with_tide, ref, FIGS_DIR / f"{SITE_ID}_{YEAR}_distribution.png")
    plot_timeseries(scenes_with_tide, obs, FIGS_DIR / f"{SITE_ID}_{YEAR}_timeseries.png")
    plot_cdf(scenes_with_tide, ref, FIGS_DIR / f"{SITE_ID}_{YEAR}_cdf.png")

    print()
    print("=" * 80)
    print(f"Tidal aliasing summary — Ganghwa-do {YEAR}")
    print("=" * 80)
    print(stats.to_string(index=False))
    print()
    print(f"Tide range observed by KHOA: {ref.min():.2f} ~ {ref.max():.2f} m")
    print(f"Total satellite scenes (cloud<{CLOUD_THRESHOLD}%): {len(scenes_with_tide)}")


if __name__ == "__main__":
    main()
