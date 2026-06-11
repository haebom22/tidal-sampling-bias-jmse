"""Five-year tidal aliasing analysis: Ganghwa-do, 2020-2024.

Extends `demo_aliasing_2024.py` to:
    1. 5-year hourly KHOA reference (Incheon DT_0001)
    2. Year x sensor metric grid (spread, low/high offset, KS, mean bias)
    3. Inter-annual variability plots (line plots of metrics over years)
    4. Combined 5-year overall distribution / CDF
    5. Monthly phase heatmap revealing seasonal aliasing pattern

Outputs:
    data/processed/ganghwa_5y_satellite_tides.parquet
    data/outputs/tables/ganghwa_5y_overall.csv
    data/outputs/tables/ganghwa_5y_yearly.csv
    data/outputs/figures/ganghwa_5y_distribution.png
    data/outputs/figures/ganghwa_5y_cdf.png
    data/outputs/figures/ganghwa_5y_annual_metrics.png
    data/outputs/figures/ganghwa_5y_monthly_phase.png
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analysis.aliasing import compute_aliasing
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times
from src.visualization.plots import SENSOR_COLORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("demo_aliasing_5y")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SITE_ID = "ganghwa"
STATION_CODE = "DT_0001"
STATION_NAME = "Incheon"
YEAR_START, YEAR_END = 2020, 2024
CLOUD_THRESHOLD = 60

GEE_PATH = Path("data/raw/gee_metadata/ganghwa_scenes.parquet")
KHOA_DIR = Path("data/raw/khoa")
PROCESSED_DIR = Path("data/processed")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_satellite_metadata() -> pd.DataFrame:
    df = pd.read_parquet(GEE_PATH)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    df = df[df["datetime_utc"].dt.year.between(YEAR_START, YEAR_END)]
    df = df[df["cloud_cover"] <= CLOUD_THRESHOLD].copy()
    df["year"] = df["datetime_utc"].dt.year
    df["month"] = df["datetime_utc"].dt.month
    df["hour_kst"] = (df["datetime_utc"] + pd.Timedelta(hours=9)).dt.hour
    log.info("Satellite scenes %d (%d-%d, cloud<=%d)",
             len(df), YEAR_START, YEAR_END, CLOUD_THRESHOLD)
    return df


def load_khoa_reference() -> pd.DataFrame:
    obs = fetch_tide_hourly_range(
        STATION_CODE, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
    )
    obs = obs.sort_values("datetime_utc").reset_index(drop=True)
    obs["year"] = obs["datetime_utc"].dt.year
    obs = obs[obs["year"].between(YEAR_START, YEAR_END)].copy()
    log.info("KHOA reference %d rows; tide %.2f m ~ %.2f m",
             len(obs), obs["tide_m"].min(), obs["tide_m"].max())
    return obs


def attach_tide_to_scenes(scenes: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    out = scenes.copy()
    out["tide_m"] = interpolate_at_times(obs, out["datetime_utc"]).values
    n_missing = int(out["tide_m"].isna().sum())
    log.info("Interpolated tide: %d / %d (%d missing)",
             len(out) - n_missing, len(out), n_missing)
    return out.dropna(subset=["tide_m"])


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

OUT_COLS = ["sensor", "n_obs", "obs_min", "obs_max", "spread",
            "low_offset", "high_offset", "ks_statistic", "ks_pvalue",
            "mean_bias", "chi2_uniform"]


def stats_by_sensor(scenes: pd.DataFrame, reference: np.ndarray) -> pd.DataFrame:
    rows = []
    for sensor, sub in scenes.groupby("sensor"):
        st = compute_aliasing(sub["tide_m"].to_numpy(), reference, n_bins=40)
        d = st.as_dict()
        d["sensor"] = sensor
        rows.append(d)
    return pd.DataFrame(rows)[OUT_COLS]


def stats_by_year_sensor(scenes: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, sub_obs in obs.groupby("year"):
        ref = sub_obs["tide_m"].to_numpy()
        for sensor, sub in scenes[scenes["year"] == year].groupby("sensor"):
            if len(sub) < 5:
                continue
            st = compute_aliasing(sub["tide_m"].to_numpy(), ref, n_bins=30)
            d = st.as_dict()
            d.update({"year": int(year), "sensor": sensor})
            rows.append(d)
    cols = ["year", "sensor", "n_obs"] + [c for c in OUT_COLS if c not in {"sensor", "n_obs"}]
    return pd.DataFrame(rows)[cols]


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_distribution(scenes: pd.DataFrame, ref: np.ndarray, out_path: Path) -> None:
    bins = 35
    ref_min, ref_max = float(np.nanmin(ref)), float(np.nanmax(ref))
    edges = np.linspace(ref_min, ref_max, bins + 1)

    fig, ax = plt.subplots(figsize=(9, 5))
    ref_hist, _ = np.histogram(ref, bins=edges, density=True)
    ax.fill_between(edges[:-1], 0, ref_hist, step="post", color="lightgray",
                    alpha=0.8, label=f"Reference (KHOA hourly, n={len(ref):,})")

    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna()
        if sub.empty:
            continue
        ax.hist(sub, bins=edges, density=True, histtype="step",
                linewidth=2.0, color=SENSOR_COLORS.get(sensor, "gray"),
                label=f"{sensor} (n={len(sub):,})")

    ax.set_xlabel("Tide height (m, KHOA datum)")
    ax.set_ylabel("Density")
    ax.set_title(f"Tidal sampling distribution — Ganghwa-do {YEAR_START}-{YEAR_END}\n"
                 f"satellite scenes vs continuous KHOA observation at {STATION_NAME}")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    log.info("Wrote %s", out_path)


def plot_cdf(scenes: pd.DataFrame, ref: np.ndarray, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))

    ref_sorted = np.sort(ref[~np.isnan(ref)])
    cdf_ref = np.arange(1, len(ref_sorted) + 1) / len(ref_sorted)
    ax.plot(ref_sorted, cdf_ref, color="black", linewidth=1.5,
            label=f"Reference KHOA (n={len(ref):,})")

    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna().to_numpy()
        if len(sub) == 0:
            continue
        s_sorted = np.sort(sub)
        cdf = np.arange(1, len(s_sorted) + 1) / len(s_sorted)
        ax.plot(s_sorted, cdf, color=SENSOR_COLORS.get(sensor, "gray"),
                linewidth=2.0, label=f"{sensor} (n={len(sub):,})")

    ax.set_xlabel("Tide height (m)")
    ax.set_ylabel("Cumulative probability")
    ax.set_title(f"CDF of sampled tides — Ganghwa-do {YEAR_START}-{YEAR_END}")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    log.info("Wrote %s", out_path)


def plot_annual_metrics(yearly: pd.DataFrame, out_path: Path) -> None:
    metrics = [
        ("spread", "Spread (fraction of reference range)", (0, 1)),
        ("high_offset", "High-tide offset (missed fraction)", (0, 0.6)),
        ("mean_bias", "Mean bias (m): obs − ref", None),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharex=True)
    sensors = sorted(yearly["sensor"].unique())
    for ax, (col, label, ylim) in zip(axes, metrics):
        for sensor in sensors:
            sub = yearly[yearly["sensor"] == sensor].sort_values("year")
            if sub.empty:
                continue
            ax.plot(sub["year"], sub[col], "-o", linewidth=1.6, markersize=7,
                    color=SENSOR_COLORS.get(sensor, "gray"),
                    label=sensor)
            for _, r in sub.iterrows():
                ax.annotate(f"n={int(r['n_obs'])}", (r["year"], r[col]),
                            textcoords="offset points", xytext=(0, 6),
                            ha="center", fontsize=7, color="gray")
        ax.set_xlabel("Year")
        ax.set_ylabel(label)
        if ylim:
            ax.set_ylim(*ylim)
        ax.grid(alpha=0.3)
        ax.set_xticks(range(YEAR_START, YEAR_END + 1))
    if col == "mean_bias":
        axes[2].axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    axes[0].legend(frameon=False, loc="lower left", fontsize=9)
    fig.suptitle(f"Inter-annual variability of tidal aliasing — Ganghwa-do {YEAR_START}-{YEAR_END}",
                 y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_monthly_phase(scenes: pd.DataFrame, obs: pd.DataFrame, out_path: Path) -> None:
    """Compare tide-phase distribution by month between satellite samples and reference.

    The "tide phase" is computed as the normalised position within the local
    daily tidal envelope: 0 = monthly low tide, 1 = monthly high tide.  If
    satellites sampled uniformly, the mean phase per month would be ~0.5.
    """
    obs_local = obs.copy()
    obs_local["datetime_local"] = obs_local["datetime_utc"] + pd.Timedelta(hours=9)
    obs_local["month"] = obs_local["datetime_local"].dt.month
    monthly_min = obs_local.groupby("month")["tide_m"].min()
    monthly_max = obs_local.groupby("month")["tide_m"].max()

    def phase(month: int, tide: float) -> float:
        lo, hi = monthly_min[month], monthly_max[month]
        return (tide - lo) / (hi - lo) if hi > lo else np.nan

    obs_local["phase"] = [phase(m, t) for m, t in zip(obs_local["month"], obs_local["tide_m"])]
    sc = scenes.copy()
    sc["phase"] = [phase(m, t) for m, t in zip(sc["month"], sc["tide_m"])]

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), gridspec_kw={"width_ratios": [3, 2]})

    # Left: monthly tide-phase boxplot — reference (gray) vs satellite (per sensor mean)
    ax = axes[0]
    months = range(1, 13)
    bp_data = [obs_local[obs_local["month"] == m]["phase"].dropna() for m in months]
    ax.boxplot(bp_data, positions=list(months), widths=0.6, showfliers=False,
               patch_artist=True, boxprops=dict(facecolor="lightgray", color="gray"),
               medianprops=dict(color="black"))
    for sensor in sorted(sc["sensor"].unique()):
        sub = sc[sc["sensor"] == sensor]
        monthly_mean = sub.groupby("month")["phase"].mean()
        ax.plot(monthly_mean.index, monthly_mean.values, "-o",
                color=SENSOR_COLORS.get(sensor, "gray"),
                markersize=5, linewidth=1.5,
                label=f"{sensor} mean")
    ax.axhline(0.5, color="black", linestyle="--", linewidth=0.7, alpha=0.5)
    ax.set_xticks(list(months))
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    ax.set_xlabel("Month")
    ax.set_ylabel("Normalised tide phase (0=monthly low, 1=monthly high)")
    ax.set_title("Tide phase by month: KHOA (gray boxes) vs satellite samples")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.grid(alpha=0.3)

    # Right: KST hour-of-day distribution of satellite acquisitions
    ax = axes[1]
    hour_bins = np.arange(-0.5, 24.5)
    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]
        ax.hist(sub["hour_kst"], bins=hour_bins, alpha=0.6, histtype="stepfilled",
                color=SENSOR_COLORS.get(sensor, "gray"),
                edgecolor=SENSOR_COLORS.get(sensor, "gray"),
                label=f"{sensor}")
    ax.set_xlabel("Hour of day (KST)")
    ax.set_ylabel("Scene count")
    ax.set_title("Satellite overpass time (KST)")
    ax.set_xticks(range(0, 24, 3))
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.3)

    fig.suptitle(f"Seasonal & diurnal sampling pattern — Ganghwa-do {YEAR_START}-{YEAR_END}",
                 y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    scenes = load_satellite_metadata()
    obs = load_khoa_reference()
    scenes_t = attach_tide_to_scenes(scenes, obs)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGS_DIR.mkdir(parents=True, exist_ok=True)

    out_scenes = PROCESSED_DIR / f"{SITE_ID}_5y_satellite_tides.parquet"
    scenes_t.to_parquet(out_scenes, index=False)
    log.info("Wrote %s", out_scenes)

    ref = obs["tide_m"].to_numpy()
    overall = stats_by_sensor(scenes_t, ref)
    overall.to_csv(TABLES_DIR / f"{SITE_ID}_5y_overall.csv",
                   index=False, float_format="%.4f")

    yearly = stats_by_year_sensor(scenes_t, obs)
    yearly.to_csv(TABLES_DIR / f"{SITE_ID}_5y_yearly.csv",
                  index=False, float_format="%.4f")

    plot_distribution(scenes_t, ref, FIGS_DIR / f"{SITE_ID}_5y_distribution.png")
    plot_cdf(scenes_t, ref, FIGS_DIR / f"{SITE_ID}_5y_cdf.png")
    plot_annual_metrics(yearly, FIGS_DIR / f"{SITE_ID}_5y_annual_metrics.png")
    plot_monthly_phase(scenes_t, obs, FIGS_DIR / f"{SITE_ID}_5y_monthly_phase.png")

    print()
    print("=" * 80)
    print(f"5-YEAR OVERALL aliasing — Ganghwa-do {YEAR_START}-{YEAR_END}")
    print("=" * 80)
    print(overall.to_string(index=False))
    print()
    print("=" * 80)
    print(f"YEARLY breakdown — Ganghwa-do")
    print("=" * 80)
    print(yearly.to_string(index=False))
    print()
    print(f"KHOA reference: {len(ref):,} rows, range {ref.min():.2f} ~ {ref.max():.2f} m")
    print(f"Satellite scenes: {len(scenes_t):,}")


if __name__ == "__main__":
    main()
