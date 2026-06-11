"""Tidal-phase quantification across 5 Korean tidal-flat sites (2020-2024).

Builds on `demo_aliasing_multisite.py` by computing, for each satellite
acquisition time, the *tidal phase* (position within the HW → HW cycle)
of the nearest KHOA gauge.  Tests the central hypothesis:

    mean_bias  ≈   tidal_amplitude · ⟨ cos(theta_satellite) ⟩

i.e. the mean tide-height bias of a sensor at a site is set by the mean
cosine of the satellite-overpass phase relative to local HW.

Outputs:
    data/processed/multisite_5y_phases.parquet
    data/outputs/tables/multisite_5y_phase_summary.csv
    data/outputs/tables/multisite_5y_phase_regression.csv
    data/outputs/figures/phase_polar_grid.png
    data/outputs/figures/phase_bias_regression.png
    data/outputs/figures/phase_vs_tide_scatter.png
    data/outputs/figures/phase_coverage_bar.png
"""

from __future__ import annotations

import logging
import warnings
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sps

from src.analysis.phase import (
    compute_phase_hw,
    find_tide_extremes,
    phase_statistics,
)
from src.config import Site, load_sites
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times
from src.visualization.plots import SENSOR_COLORS

warnings.filterwarnings("ignore", category=UserWarning,
                        message="no explicit representation of timezones")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("phase_analysis")


YEAR_START, YEAR_END = 2020, 2024
CLOUD_THRESHOLD = 60

GEE_DIR = Path("data/raw/gee_metadata")
KHOA_DIR = Path("data/raw/khoa")
PROCESSED_DIR = Path("data/processed")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")

# Site display order (north → south).
SITE_ORDER = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]


# ---------------------------------------------------------------------------
# Data preparation per site
# ---------------------------------------------------------------------------

def load_site_data(site: Site) -> dict | None:
    sc_path = GEE_DIR / f"{site.id}_scenes.parquet"
    if not sc_path.exists():
        log.warning("Missing GEE metadata for %s", site.id)
        return None
    scenes = pd.read_parquet(sc_path)
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
    scenes = scenes[scenes["datetime_utc"].dt.year.between(YEAR_START, YEAR_END)]
    scenes = scenes[scenes["cloud_cover"] <= CLOUD_THRESHOLD].copy()

    station = site.khoa_stations[0]
    obs = fetch_tide_hourly_range(
        station.code, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
    )
    if obs.empty:
        log.warning("No KHOA data for %s", site.id)
        return None
    obs = obs.sort_values("datetime_utc").reset_index(drop=True)

    extremes = find_tide_extremes(obs)

    scenes["tide_m"] = interpolate_at_times(obs, scenes["datetime_utc"]).values
    scenes = scenes.dropna(subset=["tide_m"]).copy()

    scenes["phase_hw"] = compute_phase_hw(scenes["datetime_utc"], extremes.high_times)
    scenes["theta"] = 2 * np.pi * scenes["phase_hw"]
    scenes["cos_theta"] = np.cos(scenes["theta"])
    scenes["sin_theta"] = np.sin(scenes["theta"])
    scenes["site_id"] = site.id
    scenes["site_name"] = site.name_en
    scenes["tidal_range_m"] = float(site.tidal_range_m)
    scenes["lat"] = float(site.center["lat"])

    # Reference statistics: amplitude (half mean HW-LW range) and msl
    obs_clean = obs.dropna(subset=["tide_m"])
    hw_mean = float(np.mean(extremes.high_vals))
    lw_mean = float(np.mean(extremes.low_vals))
    amplitude = 0.5 * (hw_mean - lw_mean)
    ref_mean = float(obs_clean["tide_m"].mean())

    return dict(
        site=site,
        scenes=scenes,
        obs=obs,
        extremes=extremes,
        amplitude=amplitude,
        ref_mean=ref_mean,
        station=station,
    )


# ---------------------------------------------------------------------------
# Per-(site, sensor) summary table
# ---------------------------------------------------------------------------

def summarise(per_site: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for sid, info in per_site.items():
        scenes = info["scenes"]
        amp = info["amplitude"]
        ref_mean = info["ref_mean"]
        for sensor, sub in scenes.groupby("sensor"):
            phases = sub["phase_hw"].dropna().to_numpy()
            ps = phase_statistics(phases)
            obs_mean = float(sub["tide_m"].mean())
            mean_bias = obs_mean - ref_mean
            theta_mean = ps.get("mean_phase_deg", np.nan)
            row = {
                "site_id": sid,
                "site_name": info["site"].name_en,
                "tidal_range_m": float(info["site"].tidal_range_m),
                "amplitude_m": amp,
                "ref_mean_m": ref_mean,
                "sensor": sensor,
                "n_scenes": len(sub),
                "n_valid_phase": ps.get("n", 0),
                "mean_phase": ps.get("mean_phase", np.nan),
                "mean_phase_deg": theta_mean,
                "R_concentration": ps.get("R", np.nan),
                "cos_theta_mean": ps.get("cos_mean", np.nan),
                "sin_theta_mean": ps.get("sin_mean", np.nan),
                "obs_mean_m": obs_mean,
                "mean_bias_m": mean_bias,
                "predicted_bias_m": amp * ps.get("cos_mean", 0.0),
            }
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Regression: mean_bias vs amplitude * cos(theta_mean)
# ---------------------------------------------------------------------------

def regress_bias_vs_phase(table: pd.DataFrame) -> pd.DataFrame:
    """Fit  mean_bias = a + b * (amplitude * cos_theta_mean)  with OLS."""
    df = table.dropna(subset=["mean_bias_m", "amplitude_m", "cos_theta_mean"])
    x = df["amplitude_m"].to_numpy() * df["cos_theta_mean"].to_numpy()
    y = df["mean_bias_m"].to_numpy()
    result = sps.linregress(x, y)

    df = df.assign(
        x_predicted=x,
        residual=y - (result.intercept + result.slope * x),
    )

    summary = pd.DataFrame({
        "intercept_m": [result.intercept],
        "slope": [result.slope],
        "r_value": [result.rvalue],
        "r_squared": [result.rvalue ** 2],
        "p_value": [result.pvalue],
        "stderr_slope": [result.stderr],
        "n": [len(df)],
    })
    return summary, df


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_polar_grid(per_site: dict[str, dict], out_path: Path) -> None:
    sites = [s for s in SITE_ORDER if s in per_site]
    n = len(sites)
    fig, axes = plt.subplots(
        1, n, figsize=(3.0 * n, 3.4), subplot_kw=dict(projection="polar"),
    )
    if n == 1:
        axes = [axes]
    nbins = 24
    edges = np.linspace(0, 2 * np.pi, nbins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    width = 2 * np.pi / nbins

    for ax, sid in zip(axes, sites):
        info = per_site[sid]
        scenes = info["scenes"]
        phases = scenes["phase_hw"].dropna().to_numpy()
        thetas = 2 * np.pi * phases
        counts, _ = np.histogram(thetas, bins=edges)
        # Colour by mean phase relative to HW
        ax.bar(centers, counts, width=width, color="#7a52a3",
               edgecolor="black", linewidth=0.3, alpha=0.85)
        mean_theta = 2 * np.pi * phase_statistics(phases)["mean_phase"]
        max_count = max(counts.max(), 1)
        ax.plot([mean_theta, mean_theta], [0, max_count * 1.05],
                color="red", linewidth=1.8, label="mean θ")
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_xticks([0, np.pi / 2, np.pi, 3 * np.pi / 2])
        ax.set_xticklabels(["HW", "ebb", "LW", "flood"], fontsize=9)
        ax.set_yticks([])
        ax.set_title(
            f"{info['site'].name_en}\n"
            f"θ̄={phase_statistics(phases)['mean_phase_deg']:.0f}°  "
            f"⟨cosθ⟩={phase_statistics(phases)['cos_mean']:+.2f}",
            fontsize=10, pad=10,
        )
    fig.suptitle(
        "Satellite overpass tidal phase by site — 2020-2024 (all sensors combined)",
        y=1.04, fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_bias_regression(table: pd.DataFrame, fit_df: pd.DataFrame, summary: pd.DataFrame,
                         out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 6))
    df = table.dropna(subset=["mean_bias_m", "amplitude_m", "cos_theta_mean"])
    x = df["amplitude_m"] * df["cos_theta_mean"]
    y = df["mean_bias_m"]

    site_markers = {"ganghwa": "o", "garorim": "s", "gomso": "D",
                    "hampyeong": "^", "suncheon": "P"}

    for _, r in df.iterrows():
        ax.scatter(
            r["amplitude_m"] * r["cos_theta_mean"], r["mean_bias_m"],
            s=120, color=SENSOR_COLORS.get(r["sensor"], "gray"),
            marker=site_markers.get(r["site_id"], "o"),
            edgecolor="black", linewidth=0.6,
            label=f"{r['site_id']} {r['sensor']}",
        )

    # Regression line
    xfit = np.linspace(x.min() * 1.1, x.max() * 1.1, 50)
    yfit = summary["intercept_m"].iloc[0] + summary["slope"].iloc[0] * xfit
    ax.plot(xfit, yfit, "k--", linewidth=1.4,
            label=f"fit: y = {summary['slope'].iloc[0]:+.2f}·x {summary['intercept_m'].iloc[0]:+.2f}\n"
                  f"R² = {summary['r_squared'].iloc[0]:.3f},  p = {summary['p_value'].iloc[0]:.2e}")

    # 1:1 line (theoretical: slope = 1, intercept = 0)
    ax.plot(xfit, xfit, color="red", linestyle=":", linewidth=1.0,
            label="theoretical 1:1 (bias = A·⟨cosθ⟩)")

    ax.axhline(0, color="gray", linewidth=0.5)
    ax.axvline(0, color="gray", linewidth=0.5)
    ax.set_xlabel(r"$A \cdot \langle \cos\theta \rangle$  (m)")
    ax.set_ylabel(r"Observed mean bias (m): $\langle \eta_{sat} \rangle - \langle \eta_{ref} \rangle$")
    ax.set_title("Mean tide-height bias predicted by satellite overpass phase\n"
                 "5 sites × 3 sensors, 2020-2024")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="upper left", ncols=2, frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_phase_vs_tide(per_site: dict[str, dict], out_path: Path) -> None:
    """For each site, scatter individual scene phase vs measured tide_m."""
    sites = [s for s in SITE_ORDER if s in per_site]
    n = len(sites)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.4 * rows))
    axes = np.array(axes).reshape(-1)
    for ax, sid in zip(axes, sites):
        info = per_site[sid]
        scenes = info["scenes"]
        obs = info["obs"]
        ref_mean = info["ref_mean"]
        # background: smoothed reference tide as function of phase
        phases_ref = compute_phase_hw(obs["datetime_utc"], info["extremes"].high_times)
        df_ref = pd.DataFrame({"phase": phases_ref, "tide": obs["tide_m"]}).dropna()
        df_ref["bin"] = pd.cut(df_ref["phase"], np.linspace(0, 1, 31),
                                include_lowest=True)
        agg = df_ref.groupby("bin", observed=True)["tide"].agg(["mean", "std"]).reset_index()
        agg["x"] = [b.mid for b in agg["bin"]]
        ax.fill_between(agg["x"], agg["mean"] - agg["std"], agg["mean"] + agg["std"],
                        color="lightgray", alpha=0.6, label="KHOA ±1σ")
        ax.plot(agg["x"], agg["mean"], color="gray", linewidth=1.2)
        for sensor in sorted(scenes["sensor"].unique()):
            sub = scenes[scenes["sensor"] == sensor]
            ax.scatter(sub["phase_hw"], sub["tide_m"], s=14, alpha=0.7,
                       color=SENSOR_COLORS.get(sensor, "gray"),
                       edgecolor="black", linewidth=0.2,
                       label=f"{sensor} (n={len(sub)})")
        ax.axhline(ref_mean, color="black", linestyle="--", linewidth=0.7,
                   alpha=0.5, label="KHOA mean")
        ax.set_xlabel("Phase since HW (0=HW, 0.5≈LW, 1=next HW)")
        ax.set_ylabel("Tide height (m)")
        ax.set_title(f"{info['site'].name_en}")
        ax.set_xlim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7, frameon=False, loc="upper right")
    for i in range(len(sites), len(axes)):
        axes[i].axis("off")
    fig.suptitle("Satellite overpass phase vs sampled tide height — 2020-2024",
                 y=1.0, fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_phase_coverage(table: pd.DataFrame, out_path: Path) -> None:
    """Per-site bar chart showing cos_theta_mean and mean bias side-by-side."""
    pivot_cos = (
        table.groupby("site_id")["cos_theta_mean"].mean().reindex(SITE_ORDER)
    )
    pivot_bias = (
        table.groupby("site_id")["mean_bias_m"].mean().reindex(SITE_ORDER)
    )
    pivot_amp = table.groupby("site_id")["amplitude_m"].first().reindex(SITE_ORDER)

    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    x = np.arange(len(SITE_ORDER))
    ax.bar(x - 0.2, pivot_cos.values, width=0.4, color="#7a52a3",
           edgecolor="black", label=r"$\langle \cos\theta \rangle$  (sensor mean)")
    ax.bar(x + 0.2, pivot_bias.values, width=0.4, color="#d65f5f",
           edgecolor="black", label="mean bias (m, sensor mean)")
    ax.axhline(0, color="black", linewidth=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels([
        f"{s}\n(A≈{pivot_amp.loc[s]:.1f} m)"
        for s in SITE_ORDER if s in pivot_amp.index
    ], fontsize=9)
    ax.set_ylabel(r"$\langle \cos\theta \rangle$  /  mean bias (m)")
    ax.set_title("Phase-cosine vs measured mean bias — co-located by site")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False, fontsize=10, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sites = load_sites()
    sites = sorted(sites, key=lambda s: SITE_ORDER.index(s.id)
                   if s.id in SITE_ORDER else 99)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGS_DIR.mkdir(parents=True, exist_ok=True)

    per_site: dict[str, dict] = {}
    all_scenes: list[pd.DataFrame] = []
    for site in sites:
        log.info("=== %s (%s) ===", site.id, site.name_en)
        info = load_site_data(site)
        if info is None:
            continue
        per_site[site.id] = info
        all_scenes.append(info["scenes"])
        log.info("  scenes=%d  amplitude=%.2f m  HW events=%d",
                 len(info["scenes"]), info["amplitude"], len(info["extremes"].high_times))

    if not per_site:
        log.error("No sites loaded.")
        return

    table = summarise(per_site)
    table.to_csv(TABLES_DIR / "multisite_5y_phase_summary.csv",
                 index=False, float_format="%.4f")

    summary, fit_df = regress_bias_vs_phase(table)
    summary.to_csv(TABLES_DIR / "multisite_5y_phase_regression.csv",
                   index=False, float_format="%.5f")

    all_df = pd.concat(all_scenes, ignore_index=True)
    cols_keep = ["site_id", "site_name", "sensor", "scene_id", "datetime_utc",
                 "tide_m", "phase_hw", "theta", "cos_theta", "sin_theta"]
    cols_keep = [c for c in cols_keep if c in all_df.columns]
    all_df[cols_keep].to_parquet(PROCESSED_DIR / "multisite_5y_phases.parquet",
                                 index=False)

    plot_polar_grid(per_site, FIGS_DIR / "phase_polar_grid.png")
    plot_bias_regression(table, fit_df, summary, FIGS_DIR / "phase_bias_regression.png")
    plot_phase_vs_tide(per_site, FIGS_DIR / "phase_vs_tide_scatter.png")
    plot_phase_coverage(table, FIGS_DIR / "phase_coverage_bar.png")

    print()
    print("=" * 110)
    print(f"PHASE × BIAS summary — 5 sites × 3 sensors, {YEAR_START}-{YEAR_END}")
    print("=" * 110)
    cols = ["site_id", "tidal_range_m", "amplitude_m", "sensor", "n_scenes",
            "mean_phase_deg", "R_concentration", "cos_theta_mean",
            "obs_mean_m", "ref_mean_m", "mean_bias_m", "predicted_bias_m"]
    print(table[cols].to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    print()
    print("Regression  mean_bias = a + b · (A · ⟨cosθ⟩):")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))


if __name__ == "__main__":
    main()
