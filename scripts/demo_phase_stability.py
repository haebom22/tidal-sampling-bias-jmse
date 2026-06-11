"""B-4a extension: stability of the phase × bias regression.

Tests whether the relationship

    mean_bias  =  intercept  +  slope · ( A · ⟨cos θ⟩ )

holds robustly when the data are partitioned along multiple axes:

    1. Annual (2020-2024)
    2. Seasonal (DJF / MAM / JJA / SON)
    3. Per-sensor (L8 / L9 / S2)
    4. Leave-one-site-out cross-validation
    5. Bootstrap confidence interval of slope/intercept

Each subset is treated identically: the satellite-mean tide ⟨η_sat⟩
and KHOA mean ⟨η_ref⟩ are computed *within* the subset, and the
amplitude A is recomputed from the subset's KHOA extremes.  This means
the regression captures purely the slope/intercept stability and not
artefacts of mixing periods.

Outputs:
    data/outputs/tables/phase_stability_annual.csv
    data/outputs/tables/phase_stability_seasonal.csv
    data/outputs/tables/phase_stability_sensor.csv
    data/outputs/tables/phase_stability_loo.csv
    data/outputs/tables/phase_stability_bootstrap.csv
    data/outputs/figures/phase_stability_panels.png
    data/outputs/figures/phase_stability_coefficients.png
    data/outputs/figures/phase_stability_loo.png
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

warnings.filterwarnings("ignore", category=UserWarning,
                        message="no explicit representation of timezones")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("phase_stability")


YEAR_START, YEAR_END = 2020, 2024
CLOUD_THRESHOLD = 60
MIN_OBS_PER_SUBSET = 20      # subsets with fewer scenes are dropped

GEE_DIR = Path("data/raw/gee_metadata")
KHOA_DIR = Path("data/raw/khoa")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")

SITE_ORDER = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]
SENSORS = ["L8", "L9", "S2"]
SEASONS = ["DJF", "MAM", "JJA", "SON"]
SEASON_OF_MONTH = {12: "DJF", 1: "DJF", 2: "DJF",
                   3: "MAM", 4: "MAM", 5: "MAM",
                   6: "JJA", 7: "JJA", 8: "JJA",
                   9: "SON", 10: "SON", 11: "SON"}


# ---------------------------------------------------------------------------
# Per-site data loading
# ---------------------------------------------------------------------------

def load_all_site_data() -> dict:
    sites = sorted(load_sites(),
                   key=lambda s: SITE_ORDER.index(s.id) if s.id in SITE_ORDER else 99)
    per_site = {}
    for site in sites:
        sc_path = GEE_DIR / f"{site.id}_scenes.parquet"
        if not sc_path.exists():
            log.warning("Missing GEE metadata for %s", site.id)
            continue
        scenes = pd.read_parquet(sc_path)
        scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
        scenes = scenes[scenes["datetime_utc"].dt.year.between(YEAR_START, YEAR_END)]
        scenes = scenes[scenes["cloud_cover"] <= CLOUD_THRESHOLD].copy()

        station = site.khoa_stations[0]
        obs = fetch_tide_hourly_range(
            station.code, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
        )
        if obs.empty:
            log.warning("No KHOA for %s", site.id)
            continue
        obs = obs.sort_values("datetime_utc").reset_index(drop=True)

        extremes_full = find_tide_extremes(obs)
        scenes["tide_m"] = interpolate_at_times(obs, scenes["datetime_utc"]).values
        scenes = scenes.dropna(subset=["tide_m"]).copy()
        scenes["phase_hw"] = compute_phase_hw(scenes["datetime_utc"],
                                              extremes_full.high_times)
        scenes["cos_theta"] = np.cos(2 * np.pi * scenes["phase_hw"])
        scenes["year"] = scenes["datetime_utc"].dt.year
        scenes["month"] = scenes["datetime_utc"].dt.month
        scenes["season"] = scenes["month"].map(SEASON_OF_MONTH)
        scenes["site_id"] = site.id
        scenes["site_name"] = site.name_en
        scenes["tidal_range_m"] = float(site.tidal_range_m)

        obs["year"] = obs["datetime_utc"].dt.year
        obs["month"] = obs["datetime_utc"].dt.month
        obs["season"] = obs["month"].map(SEASON_OF_MONTH)

        per_site[site.id] = dict(
            site=site, scenes=scenes, obs=obs, extremes=extremes_full,
        )
        log.info("  %s: %d scenes, %d HW events", site.id,
                 len(scenes), len(extremes_full.high_times))
    return per_site


# ---------------------------------------------------------------------------
# Per-subset (site, sensor, [time-window]) statistics builder
# ---------------------------------------------------------------------------

def subset_stats(
    sub_scenes: pd.DataFrame,
    sub_obs: pd.DataFrame,
) -> dict | None:
    """Compute amplitude, ref_mean, cos_theta_mean, obs_mean, bias for a subset."""
    if len(sub_scenes) < MIN_OBS_PER_SUBSET or len(sub_obs) < 24 * 30:
        return None
    extremes = find_tide_extremes(sub_obs)
    if len(extremes.high_vals) < 5 or len(extremes.low_vals) < 5:
        return None
    amp = 0.5 * (float(np.mean(extremes.high_vals)) - float(np.mean(extremes.low_vals)))
    ref_mean = float(sub_obs["tide_m"].mean())
    phases = sub_scenes["phase_hw"].dropna().to_numpy()
    ps = phase_statistics(phases)
    obs_mean = float(sub_scenes["tide_m"].mean())
    return {
        "n_scenes": len(sub_scenes),
        "amplitude_m": amp,
        "ref_mean_m": ref_mean,
        "cos_theta_mean": ps.get("cos_mean", np.nan),
        "mean_phase_deg": ps.get("mean_phase_deg", np.nan),
        "R_concentration": ps.get("R", np.nan),
        "obs_mean_m": obs_mean,
        "mean_bias_m": obs_mean - ref_mean,
        "x": amp * ps.get("cos_mean", np.nan),
    }


def build_subset_table(per_site: dict, axis: str) -> pd.DataFrame:
    """Build a stats table partitioned by `axis` in {"year", "season", "all"}."""
    rows = []
    for sid, info in per_site.items():
        scenes = info["scenes"]
        obs = info["obs"]
        for sensor, sub_sensor in scenes.groupby("sensor"):
            if axis == "all":
                groups = [("ALL", sub_sensor)]
                obs_groups = {"ALL": obs}
            else:
                groups = list(sub_sensor.groupby(axis))
                obs_groups = {k: g for k, g in obs.groupby(axis)}
            for key, sub in groups:
                sub_obs = obs_groups.get(key, obs)
                stats = subset_stats(sub, sub_obs)
                if stats is None:
                    continue
                stats.update(
                    site_id=sid,
                    sensor=sensor,
                    axis_key=str(key),
                )
                rows.append(stats)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Regression helper
# ---------------------------------------------------------------------------

def regress(df: pd.DataFrame) -> dict:
    """Fit  mean_bias = intercept + slope · x  where x = A·⟨cosθ⟩."""
    d = df.dropna(subset=["mean_bias_m", "x"])
    if len(d) < 3:
        return dict(n=len(d), intercept=np.nan, slope=np.nan,
                    r=np.nan, r2=np.nan, p=np.nan, stderr=np.nan,
                    rmse=np.nan, mae=np.nan)
    x = d["x"].to_numpy()
    y = d["mean_bias_m"].to_numpy()
    res = sps.linregress(x, y)
    pred = res.intercept + res.slope * x
    return dict(
        n=len(d),
        intercept=float(res.intercept),
        slope=float(res.slope),
        r=float(res.rvalue),
        r2=float(res.rvalue ** 2),
        p=float(res.pvalue),
        stderr=float(res.stderr),
        rmse=float(np.sqrt(np.mean((y - pred) ** 2))),
        mae=float(np.mean(np.abs(y - pred))),
    )


def regress_per_group(table: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for key, sub in table.groupby(group_col):
        r = regress(sub)
        r[group_col] = key
        rows.append(r)
    df = pd.DataFrame(rows)
    cols = [group_col, "n", "intercept", "slope", "r", "r2", "p", "stderr",
            "rmse", "mae"]
    return df[cols].sort_values(group_col)


# ---------------------------------------------------------------------------
# Leave-one-site-out validation
# ---------------------------------------------------------------------------

def loo_validation(per_site: dict) -> pd.DataFrame:
    """For each site, fit on the other 4 sites (5-year all-sensor pooled),
    predict the held-out site's site×sensor bias."""
    overall = build_subset_table(per_site, axis="all")
    rows = []
    for held_out in SITE_ORDER:
        train = overall[overall["site_id"] != held_out]
        test = overall[overall["site_id"] == held_out]
        if test.empty or train.empty:
            continue
        r = regress(train)
        test_x = test["x"].to_numpy()
        test_y = test["mean_bias_m"].to_numpy()
        pred = r["intercept"] + r["slope"] * test_x
        for sensor, x_val, y_val, p_val in zip(test["sensor"], test_x, test_y, pred):
            rows.append({
                "held_out_site": held_out,
                "sensor": sensor,
                "x": float(x_val),
                "measured_bias_m": float(y_val),
                "predicted_bias_m": float(p_val),
                "residual_m": float(y_val - p_val),
                "train_slope": r["slope"],
                "train_intercept": r["intercept"],
                "train_r2": r["r2"],
            })
    return pd.DataFrame(rows)


def bootstrap_ci(table: pd.DataFrame, n_boot: int = 2000, seed: int = 42) -> pd.DataFrame:
    """Bootstrap the OLS slope and intercept of the pooled (n=15) regression."""
    rng = np.random.default_rng(seed)
    d = table.dropna(subset=["mean_bias_m", "x"]).reset_index(drop=True)
    n = len(d)
    slopes, intercepts = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        boot = d.iloc[idx]
        res = sps.linregress(boot["x"].to_numpy(), boot["mean_bias_m"].to_numpy())
        slopes.append(res.slope)
        intercepts.append(res.intercept)
    slopes = np.array(slopes)
    intercepts = np.array(intercepts)
    out = pd.DataFrame({
        "param": ["slope", "intercept"],
        "mean": [float(np.mean(slopes)), float(np.mean(intercepts))],
        "median": [float(np.median(slopes)), float(np.median(intercepts))],
        "ci2.5": [float(np.percentile(slopes, 2.5)),
                  float(np.percentile(intercepts, 2.5))],
        "ci97.5": [float(np.percentile(slopes, 97.5)),
                   float(np.percentile(intercepts, 97.5))],
    })
    return out


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

SITE_MARKERS = {"ganghwa": "o", "garorim": "s", "gomso": "D",
                "hampyeong": "^", "suncheon": "P"}
SENSOR_COLORS = {"L8": "#e6a042", "L9": "#d65f5f", "S2": "#7a52a3"}


def _scatter(ax, df, title=None):
    for _, r in df.iterrows():
        ax.scatter(r["x"], r["mean_bias_m"], s=80,
                   color=SENSOR_COLORS.get(r["sensor"], "gray"),
                   marker=SITE_MARKERS.get(r["site_id"], "o"),
                   edgecolor="black", linewidth=0.4)
    if title:
        ax.set_title(title, fontsize=10)


def _fit_line(ax, df, color="black", linestyle="-", label=None):
    r = regress(df)
    if not np.isfinite(r["slope"]):
        return r
    x = df["x"].to_numpy()
    xs = np.linspace(x.min() - 0.05, x.max() + 0.05, 50)
    ys = r["intercept"] + r["slope"] * xs
    ax.plot(xs, ys, color=color, linestyle=linestyle, linewidth=1.4,
            label=label or f"slope={r['slope']:+.2f}, R²={r['r2']:.2f}, n={r['n']}")
    return r


def plot_stability_panels(annual: pd.DataFrame, seasonal: pd.DataFrame,
                          sensor: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(17, 5), sharex=False, sharey=False)
    fig_axes = axes.flatten()

    # Annual panel
    ax = axes[0]
    years = sorted(annual["axis_key"].unique())
    cmap = plt.cm.viridis(np.linspace(0.1, 0.9, len(years)))
    for c, y in zip(cmap, years):
        sub = annual[annual["axis_key"] == y]
        _scatter(ax, sub)
        _fit_line(ax, sub, color=c, label=f"{y}: slope={regress(sub)['slope']:+.2f}, R²={regress(sub)['r2']:.2f}, n={regress(sub)['n']}")
    ax.set_xlabel(r"$A \cdot \langle\cos\theta\rangle$ (m)")
    ax.set_ylabel("Measured mean bias (m)")
    ax.set_title("Annual stability (2020-2024)")
    ax.axhline(0, color="gray", linewidth=0.4)
    ax.axvline(0, color="gray", linewidth=0.4)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.grid(alpha=0.3)

    # Seasonal panel
    ax = axes[1]
    season_colors = {"DJF": "#1f77b4", "MAM": "#2ca02c",
                     "JJA": "#d62728", "SON": "#ff7f0e"}
    for s in SEASONS:
        sub = seasonal[seasonal["axis_key"] == s]
        if sub.empty:
            continue
        _scatter(ax, sub)
        _fit_line(ax, sub, color=season_colors[s],
                  label=f"{s}: slope={regress(sub)['slope']:+.2f}, R²={regress(sub)['r2']:.2f}, n={regress(sub)['n']}")
    ax.set_xlabel(r"$A \cdot \langle\cos\theta\rangle$ (m)")
    ax.set_ylabel("Measured mean bias (m)")
    ax.set_title("Seasonal stability (DJF/MAM/JJA/SON)")
    ax.axhline(0, color="gray", linewidth=0.4)
    ax.axvline(0, color="gray", linewidth=0.4)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.grid(alpha=0.3)

    # Sensor panel
    ax = axes[2]
    for s in SENSORS:
        sub = sensor[sensor["sensor"] == s]
        if sub.empty:
            continue
        _scatter(ax, sub)
        _fit_line(ax, sub, color=SENSOR_COLORS[s],
                  label=f"{s}: slope={regress(sub)['slope']:+.2f}, R²={regress(sub)['r2']:.2f}, n={regress(sub)['n']}")
    ax.set_xlabel(r"$A \cdot \langle\cos\theta\rangle$ (m)")
    ax.set_ylabel("Measured mean bias (m)")
    ax.set_title("Sensor stability (L8 / L9 / S2)")
    ax.axhline(0, color="gray", linewidth=0.4)
    ax.axvline(0, color="gray", linewidth=0.4)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.grid(alpha=0.3)

    fig.suptitle(
        "Phase × bias regression stability across years, seasons, and sensors",
        y=1.02, fontsize=13,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_coefficient_evolution(annual_fit: pd.DataFrame, seasonal_fit: pd.DataFrame,
                                sensor_fit: pd.DataFrame, bootstrap: pd.DataFrame,
                                out_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(15, 7), sharey=False)

    # Pooled fit reference (n=15) for comparison
    slope_b = bootstrap[bootstrap["param"] == "slope"]
    intercept_b = bootstrap[bootstrap["param"] == "intercept"]
    pooled_slope = float(slope_b["mean"].iloc[0])
    pooled_intercept = float(intercept_b["mean"].iloc[0])
    pooled_slope_ci = (float(slope_b["ci2.5"].iloc[0]), float(slope_b["ci97.5"].iloc[0]))
    pooled_intercept_ci = (float(intercept_b["ci2.5"].iloc[0]),
                           float(intercept_b["ci97.5"].iloc[0]))

    # Order seasons chronologically (DJF/MAM/JJA/SON) for the bar panel so it
    # matches Table S1b and the scatter panel (Figure S4).
    _ord = {s: i for i, s in enumerate(SEASONS)}
    seasonal_fit = (seasonal_fit
                    .assign(_o=seasonal_fit["axis_key"].map(_ord))
                    .sort_values("_o").drop(columns="_o").reset_index(drop=True))

    panels = [
        (annual_fit, "axis_key", "Year", axes[:, 0]),
        (seasonal_fit, "axis_key", "Season", axes[:, 1]),
        (sensor_fit, "sensor", "Sensor", axes[:, 2]),
    ]

    for fit, group_col, label, (ax_slope, ax_r2) in panels:
        labels = fit[group_col].astype(str).tolist()
        x = np.arange(len(labels))
        ax_slope.bar(x, fit["slope"], yerr=fit["stderr"], capsize=4,
                     color="#7a52a3", edgecolor="black", alpha=0.85)
        ax_slope.axhline(pooled_slope, color="red", linestyle="--", linewidth=1,
                         label=f"pooled = {pooled_slope:+.2f}")
        ax_slope.axhspan(*pooled_slope_ci, color="red", alpha=0.1,
                         label=f"95% CI {pooled_slope_ci[0]:+.2f}..{pooled_slope_ci[1]:+.2f}")
        ax_slope.set_xticks(x)
        ax_slope.set_xticklabels(labels, rotation=30 if label == "Season" else 0)
        ax_slope.set_ylabel("Regression slope (β)")
        ax_slope.set_title(f"Slope by {label}")
        ax_slope.legend(fontsize=8, frameon=False, loc="upper right")
        ax_slope.grid(axis="y", alpha=0.3)

        ax_r2.bar(x, fit["r2"], color="#3b8da6", edgecolor="black", alpha=0.85)
        for xi, n in zip(x, fit["n"]):
            ax_r2.text(xi, fit["r2"].iloc[int(xi)] + 0.02, f"n={int(n)}",
                       ha="center", fontsize=8, color="gray")
        ax_r2.axhline(0.98, color="red", linestyle="--", linewidth=1,
                      label="pooled R² = 0.98")
        ax_r2.set_xticks(x)
        ax_r2.set_xticklabels(labels, rotation=30 if label == "Season" else 0)
        ax_r2.set_ylabel("R²")
        ax_r2.set_title(f"R² by {label}")
        ax_r2.set_ylim(0, 1.05)
        ax_r2.legend(fontsize=8, frameon=False, loc="lower right")
        ax_r2.grid(axis="y", alpha=0.3)

    fig.suptitle(
        "Regression coefficient evolution — slope & R² stability across partitions",
        y=1.02, fontsize=13,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


def plot_loo(loo: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.4, 6.5))

    lim_lo = float(min(loo["measured_bias_m"].min(), loo["predicted_bias_m"].min())) - 0.05
    lim_hi = float(max(loo["measured_bias_m"].max(), loo["predicted_bias_m"].max())) + 0.05
    ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], "k--", linewidth=1, label="1:1")

    for _, r in loo.iterrows():
        ax.scatter(r["measured_bias_m"], r["predicted_bias_m"], s=100,
                   color=SENSOR_COLORS.get(r["sensor"], "gray"),
                   marker=SITE_MARKERS.get(r["held_out_site"], "o"),
                   edgecolor="black", linewidth=0.6)

    rmse = float(np.sqrt(np.mean((loo["measured_bias_m"] - loo["predicted_bias_m"]) ** 2)))
    mae = float(np.mean(np.abs(loo["measured_bias_m"] - loo["predicted_bias_m"])))
    r_loo = float(sps.pearsonr(loo["measured_bias_m"], loo["predicted_bias_m"])[0])

    # Stats text box stays at the upper-left corner of the plot
    # (this region is empty for these LOO data — points cluster along the
    # 1:1 diagonal in the lower-left quadrant plus Suncheon at +0.3 m).
    ax.text(0.03, 0.97,
            f"LOO  Pearson r = {r_loo:+.3f}\nRMSE = {rmse:.3f} m\nMAE = {mae:.3f} m",
            transform=ax.transAxes, va="top", ha="left",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="black", alpha=0.95),
            fontsize=10, zorder=5)

    # Both legends are placed *outside* the plot area on the right margin to
    # avoid colliding with the stats box (upper-left) and with the Suncheon
    # data cluster at (+0.3, ~0) which would otherwise be occluded by an
    # "upper-right" in-axes legend.
    from matplotlib.lines import Line2D
    site_handles = [Line2D([0], [0], marker=m, color="w", markeredgecolor="black",
                            markerfacecolor="gray", markersize=10, label=s)
                    for s, m in SITE_MARKERS.items()]
    sensor_handles = [Line2D([0], [0], marker="o", color="w", markeredgecolor="black",
                              markerfacecolor=SENSOR_COLORS[s], markersize=10, label=s)
                      for s in SENSORS]
    legend_sites = ax.legend(handles=site_handles, title="Held-out site",
                              bbox_to_anchor=(1.02, 1.0), loc="upper left",
                              fontsize=9, frameon=True, framealpha=1.0,
                              edgecolor="0.6", borderpad=0.4)
    ax.add_artist(legend_sites)
    ax.legend(handles=sensor_handles, title="Sensor",
              bbox_to_anchor=(1.02, 0.0), loc="lower left",
              fontsize=9, frameon=True, framealpha=1.0,
              edgecolor="0.6", borderpad=0.4)

    ax.set_xlabel("Measured mean bias (m)")
    ax.set_ylabel("LOO-predicted mean bias (m)")
    ax.set_title("Leave-one-site-out validation\n"
                 "(model fitted on 4 sites, predicts the 5th)")
    ax.set_xlim(lim_lo, lim_hi)
    ax.set_ylim(lim_lo, lim_hi)
    ax.grid(alpha=0.3)
    ax.axhline(0, color="gray", linewidth=0.4)
    ax.axvline(0, color="gray", linewidth=0.4)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGS_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Loading site data...")
    per_site = load_all_site_data()
    if not per_site:
        log.error("No sites loaded")
        return

    log.info("Building subset tables...")
    overall = build_subset_table(per_site, axis="all")
    annual = build_subset_table(per_site, axis="year")
    seasonal = build_subset_table(per_site, axis="season")
    # sensor stability uses the full 5y per site×sensor (=overall)
    sensor_tbl = overall.copy()

    annual_fit = regress_per_group(annual, "axis_key")
    annual_fit.to_csv(TABLES_DIR / "phase_stability_annual.csv",
                      index=False, float_format="%.4f")

    seasonal_fit = regress_per_group(seasonal, "axis_key")
    seasonal_fit.to_csv(TABLES_DIR / "phase_stability_seasonal.csv",
                        index=False, float_format="%.4f")

    sensor_fit = regress_per_group(sensor_tbl, "sensor")
    sensor_fit.to_csv(TABLES_DIR / "phase_stability_sensor.csv",
                      index=False, float_format="%.4f")

    log.info("Bootstrap CI on pooled fit (n=15)...")
    bootstrap = bootstrap_ci(overall, n_boot=2000)
    bootstrap.to_csv(TABLES_DIR / "phase_stability_bootstrap.csv",
                     index=False, float_format="%.4f")

    log.info("Leave-one-site-out validation...")
    loo = loo_validation(per_site)
    loo.to_csv(TABLES_DIR / "phase_stability_loo.csv",
               index=False, float_format="%.4f")

    plot_stability_panels(annual, seasonal, sensor_tbl,
                          FIGS_DIR / "phase_stability_panels.png")
    plot_coefficient_evolution(annual_fit, seasonal_fit, sensor_fit, bootstrap,
                                FIGS_DIR / "phase_stability_coefficients.png")
    plot_loo(loo, FIGS_DIR / "phase_stability_loo.png")

    print()
    print("=" * 100)
    print("ANNUAL stability (one regression per year, all sites × sensors pooled)")
    print("=" * 100)
    print(annual_fit.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    print()
    print("=" * 100)
    print("SEASONAL stability (one regression per season, all sites × sensors × years pooled)")
    print("=" * 100)
    print(seasonal_fit.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    print()
    print("=" * 100)
    print("SENSOR stability (one regression per sensor, 5 sites × 5y pooled)")
    print("=" * 100)
    print(sensor_fit.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    print()
    print("=" * 100)
    print("BOOTSTRAP (2000 resamples) of pooled (n=15) regression")
    print("=" * 100)
    print(bootstrap.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    print()
    print("=" * 100)
    print("LEAVE-ONE-SITE-OUT validation")
    print("=" * 100)
    print(loo.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    rmse = float(np.sqrt(np.mean((loo["measured_bias_m"] - loo["predicted_bias_m"]) ** 2)))
    mae = float(np.mean(np.abs(loo["measured_bias_m"] - loo["predicted_bias_m"])))
    print(f"  LOO RMSE = {rmse:.3f} m,  MAE = {mae:.3f} m")


if __name__ == "__main__":
    main()
