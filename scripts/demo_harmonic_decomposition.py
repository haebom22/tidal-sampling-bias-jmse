"""utide harmonic decomposition and three-variant β reconstruction.

This is the §4.7 robustness analysis: it isolates the three mechanisms that
inflate the empirical regression slope β above the leading-order value of 1
(Section 5.1 mechanisms i/ii/iii). The strategy is to re-run the *same*
15-point OLS fit under three different definitions of the amplitude *A* and
the reference series:

    (a) baseline      A = ½(mean HW − mean LW)        reference = KHOA observed
    (b) M2-amplitude  A = A_M2 from utide.solve       reference = KHOA observed
    (c) astronomical  A = A_M2                        reference = utide.reconstruct

Comparing β across the three variants attributes β > 1 to each mechanism:
    Δ(b)−(a) ≈ amplitude-definition effect          (mechanism iii)
    Δ(c)−(b) ≈ non-astronomical / weather effect    (mechanism ii)
    Residual β(c)−1 ≈ spring-neap × phase covariance (mechanism i)

Outputs:
    data/outputs/tables/harmonic_decomposition_constituents.csv
    data/outputs/tables/harmonic_decomposition_regression.csv
    data/outputs/figures/figS7_harmonic_decomposition.png
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

import utide

from src.analysis.phase import (
    compute_phase_hw,
    find_tide_extremes,
    phase_statistics,
)
from src.config import Site, load_sites
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times

warnings.filterwarnings("ignore", category=UserWarning,
                        message="no explicit representation of timezones")
warnings.filterwarnings("ignore", message=".*Wunsch.*", category=UserWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("harmonic_decomp")

YEAR_START, YEAR_END = 2020, 2024

PHASE_PARQUET = Path("data/processed/multisite_5y_phases.parquet")
KHOA_DIR = Path("data/raw/khoa")
TABLES_DIR = Path("data/outputs/tables")
FIGS_DIR = Path("data/outputs/figures")

CONSTIT_CSV = TABLES_DIR / "harmonic_decomposition_constituents.csv"
REGR_CSV = TABLES_DIR / "harmonic_decomposition_regression.csv"
COMP_FIG = FIGS_DIR / "figS7_harmonic_decomposition.png"

SITE_ORDER = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]

# Headline constituents we extract for the constituent table.
HEADLINE = ["M2", "S2", "K1", "O1", "M4"]

BOOTSTRAP_N = 2000
RNG_SEED = 20260524


# ---------------------------------------------------------------------------
# Per-site utide solve + reconstruct
# ---------------------------------------------------------------------------

def run_utide(site: Site) -> dict:
    """Solve utide on the 5-y KHOA hourly series and reconstruct astro tide."""
    station = site.khoa_stations[0]
    obs = fetch_tide_hourly_range(
        station.code, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
    )
    obs = obs.sort_values("datetime_utc").reset_index(drop=True)
    if obs.empty:
        raise RuntimeError(f"No KHOA data for {site.id}")

    # utide accepts pandas datetime arrays directly (UTC-aware → naive).
    t = obs["datetime_utc"].dt.tz_convert(None).to_numpy()
    h = obs["tide_m"].to_numpy()

    coef = utide.solve(
        t, h, lat=float(site.lat),
        method="ols", conf_int="linear", trend=False, verbose=False,
    )
    tide = utide.reconstruct(t, coef, verbose=False)
    astro = pd.Series(tide.h, index=obs["datetime_utc"], name="astro_m")
    obs = obs.assign(astro_m=astro.values)
    obs["residual_m"] = obs["tide_m"] - obs["astro_m"]

    # Build a {name: amp} dict.
    amps = {n: float(a) for n, a in zip(coef.name, coef.A)}
    return dict(obs=obs, coef=coef, amps=amps, station=station, site=site)


# ---------------------------------------------------------------------------
# Build the 15-point predictor table for one (A_def, ref_def) variant
# ---------------------------------------------------------------------------

def assemble_variant(
    per_site: dict[str, dict],
    phases: pd.DataFrame,
    *,
    amp_source: str,     # "hwlw" or "m2"
    ref_source: str,     # "khoa" or "astro"
) -> pd.DataFrame:
    """Return a tidy table with one row per (site, sensor) for an OLS fit."""
    rows = []
    for sid in SITE_ORDER:
        if sid not in per_site:
            continue
        info = per_site[sid]
        obs = info["obs"]
        if ref_source == "khoa":
            ref_series = obs[["datetime_utc", "tide_m"]].rename(
                columns={"tide_m": "ref_m"})
        else:
            ref_series = obs[["datetime_utc", "astro_m"]].rename(
                columns={"astro_m": "ref_m"})
        ref_mean = float(ref_series["ref_m"].mean())

        # Local HW envelope, with reference choice affecting it.
        ext_src = ref_series.rename(columns={"ref_m": "tide_m"})
        ext = find_tide_extremes(ext_src)
        amp_hwlw = 0.5 * (
            float(np.mean(ext.high_vals)) - float(np.mean(ext.low_vals))
        )
        amp_m2 = info["amps"].get("M2", np.nan)
        amplitude = amp_hwlw if amp_source == "hwlw" else amp_m2

        # Phase at scene times must be measured against the same reference's
        # extremes; for the astro variant we re-derive phases.
        scenes = phases[phases["site_id"] == sid].copy()
        scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
        if ref_source == "astro":
            scenes["phase_hw"] = compute_phase_hw(
                scenes["datetime_utc"], ext.high_times,
            )
            scenes["theta"] = 2 * np.pi * scenes["phase_hw"]
            scenes["cos_theta"] = np.cos(scenes["theta"])
            scenes["sin_theta"] = np.sin(scenes["theta"])
            scenes["tide_m"] = interpolate_at_times(
                ext_src, scenes["datetime_utc"]
            ).values

        scenes = scenes.dropna(subset=["phase_hw", "cos_theta", "tide_m"])

        for sensor, sub in scenes.groupby("sensor"):
            phs = sub["phase_hw"].dropna().to_numpy()
            ps = phase_statistics(phs)
            obs_mean = float(sub["tide_m"].mean())
            mean_bias = obs_mean - ref_mean
            rows.append({
                "site_id": sid,
                "site_name": info["site"].name_en,
                "sensor": sensor,
                "n_scenes": int(len(sub)),
                "amplitude_m": float(amplitude),
                "amp_m2_m": float(amp_m2) if not np.isnan(amp_m2) else np.nan,
                "amp_hwlw_m": float(amp_hwlw),
                "cos_theta_mean": float(ps.get("cos_mean", np.nan)),
                "ref_mean_m": ref_mean,
                "obs_mean_m": obs_mean,
                "mean_bias_m": mean_bias,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# OLS + bootstrap CI on the 15-point fit
# ---------------------------------------------------------------------------

def ols_with_bootstrap(table: pd.DataFrame, rng_seed: int = RNG_SEED,
                      n_boot: int = BOOTSTRAP_N) -> dict:
    df = table.dropna(subset=["mean_bias_m", "amplitude_m", "cos_theta_mean"])
    x = df["amplitude_m"].to_numpy() * df["cos_theta_mean"].to_numpy()
    y = df["mean_bias_m"].to_numpy()

    r = sps.linregress(x, y)
    rng = np.random.default_rng(rng_seed)
    slopes = np.empty(n_boot)
    intercepts = np.empty(n_boot)
    idx = np.arange(len(x))
    for i in range(n_boot):
        s = rng.choice(idx, size=len(idx), replace=True)
        rb = sps.linregress(x[s], y[s])
        slopes[i] = rb.slope
        intercepts[i] = rb.intercept
    return dict(
        slope=float(r.slope),
        intercept=float(r.intercept),
        r_squared=float(r.rvalue ** 2),
        p_value=float(r.pvalue),
        stderr_slope=float(r.stderr),
        n=int(len(df)),
        slope_lo=float(np.percentile(slopes, 2.5)),
        slope_hi=float(np.percentile(slopes, 97.5)),
        intercept_lo=float(np.percentile(intercepts, 2.5)),
        intercept_hi=float(np.percentile(intercepts, 97.5)),
        x_fit=x,
        y_fit=y,
    )


def plot_panels(variants: dict[str, tuple[pd.DataFrame, dict]],
                out_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.7), sharey=True)
    titles = {
        "baseline": "(a) baseline: A=½(HW−LW), ref=KHOA",
        "m2": "(b) A=A_M2 (utide), ref=KHOA",
        "astro": "(c) A=A_M2, ref=astronomical (utide reconstruct)",
    }
    for ax, key in zip(axes, ["baseline", "m2", "astro"]):
        table, stats = variants[key]
        x = stats["x_fit"]
        y = stats["y_fit"]
        ax.scatter(x, y, s=60, color="#7a52a3", edgecolor="black", linewidth=0.5,
                   alpha=0.85)
        xf = np.linspace(min(x.min(), -1.5) * 1.05, max(x.max(), 0.6) * 1.05, 50)
        yf = stats["intercept"] + stats["slope"] * xf
        ax.plot(xf, yf, "k--", linewidth=1.4,
                label=(f"β = {stats['slope']:+.2f}  "
                       f"[{stats['slope_lo']:.2f}, {stats['slope_hi']:.2f}]\n"
                       f"c0 = {stats['intercept']:+.3f}  R² = {stats['r_squared']:.3f}"))
        ax.plot(xf, xf, color="red", linestyle=":", linewidth=1.0,
                label="theoretical 1:1")
        ax.axhline(0, color="gray", linewidth=0.4)
        ax.axvline(0, color="gray", linewidth=0.4)
        ax.set_title(titles[key], fontsize=10)
        ax.set_xlabel(r"$A \cdot \langle \cos\theta \rangle$  (m)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    axes[0].set_ylabel(r"mean bias (m)  $\langle\eta_{sat}\rangle - \langle\eta_{ref}\rangle$")
    fig.suptitle("Three-variant robustness fit (Section 4.7)", y=1.02, fontsize=12)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGS_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Loading cached phases parquet …")
    phases = pd.read_parquet(PHASE_PARQUET)
    sites = {s.id: s for s in load_sites()}

    per_site: dict[str, dict] = {}
    for sid in SITE_ORDER:
        if sid not in sites:
            continue
        log.info("=== utide solve: %s ===", sid)
        per_site[sid] = run_utide(sites[sid])
        amps = per_site[sid]["amps"]
        log.info("  M2=%.3f m  S2=%.3f m  K1=%.3f m  O1=%.3f m  M4=%.4f m",
                 amps.get("M2", np.nan), amps.get("S2", np.nan),
                 amps.get("K1", np.nan), amps.get("O1", np.nan),
                 amps.get("M4", np.nan))

    # ------------------------------------------------------------------
    # Constituent table
    # ------------------------------------------------------------------
    rows = []
    for sid in SITE_ORDER:
        info = per_site[sid]
        obs = info["obs"]
        row = {
            "site_id": sid,
            "site_name": info["site"].name_en,
            "obs_std_m": float(obs["tide_m"].std()),
            "residual_std_m": float(obs["residual_m"].std()),
            "amp_hwlw_m": 0.5 * (
                float(np.mean(find_tide_extremes(obs).high_vals)) -
                float(np.mean(find_tide_extremes(obs).low_vals))
            ),
        }
        for c in HEADLINE:
            row[f"amp_{c}_m"] = info["amps"].get(c, np.nan)
        rows.append(row)
    constit_df = pd.DataFrame(rows)
    constit_df.to_csv(CONSTIT_CSV, index=False, float_format="%.4f")
    log.info("Wrote %s", CONSTIT_CSV)

    # ------------------------------------------------------------------
    # Three regression variants
    # ------------------------------------------------------------------
    variants = {}
    for key, (amp_src, ref_src) in {
        "baseline": ("hwlw", "khoa"),
        "m2": ("m2", "khoa"),
        "astro": ("m2", "astro"),
    }.items():
        log.info("--- variant %s: A=%s, ref=%s ---", key, amp_src, ref_src)
        table = assemble_variant(per_site, phases,
                                 amp_source=amp_src, ref_source=ref_src)
        stats = ols_with_bootstrap(table)
        variants[key] = (table, stats)
        log.info("  β = %+.4f  [%+.4f, %+.4f]   c0 = %+.4f  [%+.4f, %+.4f]   R² = %.4f",
                 stats["slope"], stats["slope_lo"], stats["slope_hi"],
                 stats["intercept"], stats["intercept_lo"], stats["intercept_hi"],
                 stats["r_squared"])

    # ------------------------------------------------------------------
    # Regression-comparison table
    # ------------------------------------------------------------------
    regr_rows = []
    for key in ["baseline", "m2", "astro"]:
        table, st = variants[key]
        regr_rows.append({
            "variant": key,
            "amp_source": "hwlw" if key == "baseline" else "m2",
            "ref_source": "khoa" if key in ("baseline", "m2") else "astro",
            "n": st["n"],
            "slope_beta": st["slope"],
            "slope_lo": st["slope_lo"],
            "slope_hi": st["slope_hi"],
            "intercept_m": st["intercept"],
            "intercept_lo": st["intercept_lo"],
            "intercept_hi": st["intercept_hi"],
            "r_squared": st["r_squared"],
            "stderr_slope": st["stderr_slope"],
            "p_value": st["p_value"],
        })
    regr_df = pd.DataFrame(regr_rows)
    regr_df.to_csv(REGR_CSV, index=False, float_format="%.5f")
    log.info("Wrote %s", REGR_CSV)

    plot_panels(variants, COMP_FIG)

    # ------------------------------------------------------------------
    # Console summary + β-decomposition
    # ------------------------------------------------------------------
    print()
    print("=" * 110)
    print("HARMONIC CONSTITUENTS (utide, 5-y KHOA hourly)")
    print("=" * 110)
    print(constit_df.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))

    print()
    print("=" * 110)
    print("REGRESSION VARIANTS (β > 1 decomposition)")
    print("=" * 110)
    print(regr_df.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    b_base = variants["baseline"][1]["slope"]
    b_m2 = variants["m2"][1]["slope"]
    b_astro = variants["astro"][1]["slope"]
    print()
    print("β-decomposition (Section 5.1 mechanisms i / ii / iii):")
    print(f"  baseline                                  β = {b_base:+.3f}")
    print(f"  (b) − (a) Δβ  ≈ amplitude-definition (iii)  = {b_m2 - b_base:+.3f}")
    print(f"  (c) − (b) Δβ  ≈ non-astronomical / weather (ii) = {b_astro - b_m2:+.3f}")
    print(f"  (c) − 1   residual ≈ spring-neap × phase cov (i)  = {b_astro - 1:+.3f}")
    print(f"  Σ of (i)+(ii)+(iii) = {(b_astro - 1) + (b_astro - b_m2) + (b_m2 - b_base):+.3f}  "
          f"vs. β − 1 = {b_base - 1:+.3f}")


if __name__ == "__main__":
    main()
