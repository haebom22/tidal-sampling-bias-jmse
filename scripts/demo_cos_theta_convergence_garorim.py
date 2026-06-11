"""Cumulative-sample convergence of |⟨cos θ⟩|(t) at Garorim Bay.

Tests Reviewer #2 (RSE-style) M6: does the residual sun-synchronous overpass
phase vector converge to its systematic asymptote on the ~5-month timescale
empirically reported by Lee et al. (2025, ECSS 318, 109235)?

Inputs (cached, no external calls required):
    data/processed/multisite_5y_phases.parquet  (per-scene phase, cos θ, sin θ)
    data/outputs/tables/multisite_5y_phase_summary.csv  (per-sensor amplitudes)
    data/outputs/tables/multisite_5y_phase_regression.csv (β, intercept)

Outputs:
    data/processed/cos_theta_convergence_garorim.parquet
    data/outputs/tables/cos_theta_convergence_garorim_thresholds.csv
    data/outputs/figures/cos_theta_convergence_garorim.png

Methodology:
1.  Filter to Garorim Bay, sort chronologically.
2.  For four sample populations (L8, L9, S2, combined) compute, at every
    scene index k = 1 .. N:
        c_k = (1/k) Σ_{i≤k} cos θ_i
        s_k = (1/k) Σ_{i≤k} sin θ_i
        |⟨cos θ⟩|_k = |c_k|
        R_k         = √(c_k² + s_k²)
    Track elapsed time t_k = (datetime_k − datetime_1) in days.
3.  30-day block bootstrap (n=1000) on the chronological combined-sensor
    series → 95 % percentile envelope of |⟨cos θ⟩|(t).
4.  Identify convergence time t* = first t at which |⟨cos θ⟩|(t') stays
    within ±20 % of its 5-year asymptote for all t' ≥ t.
5.  Plot |⟨cos θ⟩|(t) and the implied mean-bias β·A·|⟨cos θ⟩|(t) curve,
    annotate 5-month / 152-day vertical line and the asymptote.
6.  Report numerical comparisons against the empirical 5-month optimum of
    Lee et al. (2025).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("convergence_garorim")

SITE = "garorim"
THRESHOLDS = (0.05, 0.10, 0.15)
ASYMPTOTE_BAND = 0.20  # ±20 % of long-run value defines "converged"
BOOTSTRAP_N = 1000
BLOCK_DAYS = 30
RNG_SEED = 20260524

PHASE_PARQUET = Path("data/processed/multisite_5y_phases.parquet")
SUMMARY_CSV = Path("data/outputs/tables/multisite_5y_phase_summary.csv")
REGRESSION_CSV = Path("data/outputs/tables/multisite_5y_phase_regression.csv")
OUT_PARQUET = Path("data/processed/cos_theta_convergence_garorim.parquet")
OUT_TABLE = Path("data/outputs/tables/cos_theta_convergence_garorim_thresholds.csv")
OUT_FIG = Path("data/outputs/figures/cos_theta_convergence_garorim.png")

SENSOR_COLORS = {"L8": "#e07b00", "L9": "#c8203b", "S2": "#7a52a3",
                 "combined": "#1f4a7a"}


def cumulative_mean(x: np.ndarray) -> np.ndarray:
    """Running mean of a 1-D array, output same length."""
    return np.cumsum(x) / np.arange(1, len(x) + 1)


def trajectory(scenes: pd.DataFrame) -> pd.DataFrame:
    """For an ordered set of scenes, build the cumulative cos/sin trajectory."""
    s = scenes.dropna(subset=["cos_theta", "sin_theta"]).sort_values("datetime_utc").reset_index(drop=True)
    if len(s) == 0:
        return pd.DataFrame()
    t0 = s["datetime_utc"].iloc[0]
    days = (s["datetime_utc"] - t0).dt.total_seconds().to_numpy() / 86400.0
    c = cumulative_mean(s["cos_theta"].to_numpy())
    si = cumulative_mean(s["sin_theta"].to_numpy())
    R = np.sqrt(c ** 2 + si ** 2)
    return pd.DataFrame({
        "scene_index": np.arange(1, len(s) + 1),
        "days_since_start": days,
        "cum_cos": c,
        "cum_sin": si,
        "cum_abs_cos": np.abs(c),
        "cum_R": R,
        "sensor": s["sensor"].to_numpy(),
        "datetime_utc": s["datetime_utc"].to_numpy(),
    })


def first_threshold_crossing(traj: pd.DataFrame, threshold: float) -> float | None:
    """First day at which |⟨cos θ⟩| drops below `threshold` and stays below
    thereafter.  Returns None if never reached.

    The "stays below" condition matters because |⟨cos θ⟩| oscillates around
    its mean for small samples; we want the saturation crossing, not a
    transient dip.
    """
    below = traj["cum_abs_cos"].to_numpy() < threshold
    if not below.any():
        return None
    # Find last index where it's above; everything after must be below.
    not_below = np.where(~below)[0]
    if len(not_below) == 0:
        return float(traj["days_since_start"].iloc[0])
    last_above = not_below[-1]
    if last_above == len(below) - 1:
        return None
    return float(traj["days_since_start"].iloc[last_above + 1])


def asymptote_convergence(traj: pd.DataFrame, band: float = ASYMPTOTE_BAND) -> dict:
    """First day at which |⟨cos θ⟩|(t) enters a band of ±`band` (relative) of
    its long-run value and stays inside thereafter.
    """
    a = traj["cum_abs_cos"].to_numpy()
    if len(a) < 50:
        return dict(asymptote=float("nan"), t_converge=float("nan"))
    asy = float(a[-1])
    lo, hi = (1 - band) * asy, (1 + band) * asy
    inside = (a >= lo) & (a <= hi)
    not_inside = np.where(~inside)[0]
    if len(not_inside) == 0:
        return dict(asymptote=asy, t_converge=float(traj["days_since_start"].iloc[0]))
    last_out = not_inside[-1]
    if last_out == len(inside) - 1:
        return dict(asymptote=asy, t_converge=float("nan"))
    return dict(
        asymptote=asy,
        t_converge=float(traj["days_since_start"].iloc[last_out + 1]),
    )


def block_bootstrap_envelope(
    scenes: pd.DataFrame,
    n_resamples: int = BOOTSTRAP_N,
    block_days: int = BLOCK_DAYS,
    rng_seed: int = RNG_SEED,
) -> pd.DataFrame:
    """Block-bootstrap |⟨cos θ⟩|(t) envelope on a chronological combined sample.

    We assign each scene to a 30-day calendar block, resample blocks with
    replacement, splice scenes inside resampled blocks back into a
    chronological order using their original within-block timestamps, and
    rebuild the trajectory.  We then linearly interpolate the trajectory
    onto a common time grid and report 2.5 / 50 / 97.5 percentile bands.
    """
    rng = np.random.default_rng(rng_seed)
    s = scenes.dropna(subset=["cos_theta", "sin_theta"]).sort_values("datetime_utc").reset_index(drop=True)
    t0 = s["datetime_utc"].iloc[0]
    days = (s["datetime_utc"] - t0).dt.total_seconds().to_numpy() / 86400.0
    block_idx = (days // block_days).astype(int)
    unique_blocks = np.unique(block_idx)

    # Common time grid (in days).  Stop a hair short of the maximum to avoid
    # edge issues with interpolation.
    t_grid = np.arange(7, days.max() - 1, 7)  # weekly samples
    samples = np.empty((n_resamples, len(t_grid)))
    samples[:] = np.nan

    cos = s["cos_theta"].to_numpy()
    for r in range(n_resamples):
        chosen = rng.choice(unique_blocks, size=len(unique_blocks), replace=True)
        rows = []
        new_days = []
        for offset, blk in enumerate(chosen):
            mask = block_idx == blk
            if mask.sum() == 0:
                continue
            local_days = days[mask] - days[mask].min()
            rows.append(cos[mask])
            new_days.append(local_days + offset * block_days)
        if not rows:
            continue
        cos_r = np.concatenate(rows)
        d_r = np.concatenate(new_days)
        order = np.argsort(d_r)
        cos_r = cos_r[order]
        d_r = d_r[order]
        cum = np.cumsum(cos_r) / np.arange(1, len(cos_r) + 1)
        abs_cum = np.abs(cum)
        valid = d_r <= t_grid.max()
        if valid.sum() < 2:
            continue
        interp = np.interp(t_grid, d_r[valid], abs_cum[valid], left=np.nan, right=np.nan)
        samples[r] = interp

    p025 = np.nanpercentile(samples, 2.5, axis=0)
    p50 = np.nanpercentile(samples, 50, axis=0)
    p975 = np.nanpercentile(samples, 97.5, axis=0)
    return pd.DataFrame({
        "days": t_grid, "p025": p025, "p50": p50, "p975": p975,
    })


def start_time_sensitivity(scenes: pd.DataFrame, n_starts: int = 5) -> dict[str, pd.DataFrame]:
    """Re-run combined-sensor trajectory starting from n different calendar
    dates evenly distributed within the data record.  Tests whether the
    convergence time depends on the absolute calendar start (= depends on
    spring-neap phase at start).
    """
    s = scenes.sort_values("datetime_utc").reset_index(drop=True)
    t0, t1 = s["datetime_utc"].min(), s["datetime_utc"].max()
    starts = pd.date_range(t0, t1 - pd.Timedelta(days=365), periods=n_starts)
    out: dict[str, pd.DataFrame] = {}
    for st in starts:
        sub = s[s["datetime_utc"] >= st].copy()
        if len(sub) < 100:
            continue
        out[st.strftime("%Y-%m-%d")] = trajectory(sub)
    return out


def main() -> None:
    log.info("Loading cached parquets …")
    phases = pd.read_parquet(PHASE_PARQUET)
    summary = pd.read_csv(SUMMARY_CSV)
    regression = pd.read_csv(REGRESSION_CSV)

    g = phases[phases["site_id"] == SITE].copy()
    g["datetime_utc"] = pd.to_datetime(g["datetime_utc"], utc=True)
    g = g.sort_values("datetime_utc").reset_index(drop=True)
    log.info("Garorim Bay: %d scenes  (%s → %s)",
             len(g), g["datetime_utc"].min().date(), g["datetime_utc"].max().date())

    # Amplitude & regression context.
    A_site = float(summary[summary.site_id == SITE]["amplitude_m"].iloc[0])
    beta = float(regression["slope"].iloc[0])
    c0 = float(regression["intercept_m"].iloc[0])
    log.info("Site A = %.3f m   |   pooled β = %.3f   c0 = %+.3f m", A_site, beta, c0)

    # ------------------------------------------------------------------
    # Trajectories
    # ------------------------------------------------------------------
    trajs: dict[str, pd.DataFrame] = {}
    for sensor in ["L8", "L9", "S2"]:
        sub = g[g["sensor"] == sensor]
        trajs[sensor] = trajectory(sub)
    trajs["combined"] = trajectory(g)

    rows = []
    for label, tr in trajs.items():
        conv = asymptote_convergence(tr)
        row = {
            "population": label,
            "n_scenes": len(tr),
            "duration_days": tr["days_since_start"].max() if len(tr) else float("nan"),
            "asymptote_abs_cos": conv["asymptote"],
            "t_converge_d": conv["t_converge"],
            "abs_cos_at_152d": float(np.interp(152, tr["days_since_start"], tr["cum_abs_cos"])),
        }
        for th in THRESHOLDS:
            row[f"days_below_{int(th*100):03d}pct"] = first_threshold_crossing(tr, th)
        # Predicted mean bias at 5-year asymptote and at 152d:
        row["pred_bias_asymptote_m"] = -beta * A_site * conv["asymptote"] + c0  # negative because cos<0 here
        row["pred_bias_152d_m"] = -beta * A_site * row["abs_cos_at_152d"] + c0
        rows.append(row)
    thr_df = pd.DataFrame(rows)
    OUT_TABLE.parent.mkdir(parents=True, exist_ok=True)
    thr_df.to_csv(OUT_TABLE, index=False, float_format="%.4f")
    log.info("Wrote %s", OUT_TABLE)

    # ------------------------------------------------------------------
    # Block bootstrap envelope on the combined series
    # ------------------------------------------------------------------
    log.info("Running %d-resample block bootstrap (%d-day blocks) …",
             BOOTSTRAP_N, BLOCK_DAYS)
    env = block_bootstrap_envelope(g, n_resamples=BOOTSTRAP_N, block_days=BLOCK_DAYS)

    # ------------------------------------------------------------------
    # Start-time sensitivity
    # ------------------------------------------------------------------
    sens = start_time_sensitivity(g, n_starts=5)

    # ------------------------------------------------------------------
    # Persist long-form trajectory parquet
    # ------------------------------------------------------------------
    long_rows = []
    for label, tr in trajs.items():
        tr2 = tr.copy()
        tr2["population"] = label
        long_rows.append(tr2[["population", "scene_index", "days_since_start",
                              "cum_cos", "cum_sin", "cum_abs_cos", "cum_R"]])
    pd.concat(long_rows, ignore_index=True).to_parquet(OUT_PARQUET, index=False)
    log.info("Wrote %s", OUT_PARQUET)

    # ------------------------------------------------------------------
    # Figure
    # ------------------------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    ax_main, ax_bias = axes[0]
    ax_sens, ax_zoom = axes[1]

    # (a) Main: |⟨cos θ⟩|(t) by sensor + combined + bootstrap envelope.
    ax_main.fill_between(env["days"], env["p025"], env["p975"],
                         color="#1f4a7a", alpha=0.15,
                         label="combined, block-bootstrap 95 % CI")
    for label, tr in trajs.items():
        ax_main.plot(tr["days_since_start"], tr["cum_abs_cos"],
                     color=SENSOR_COLORS[label],
                     linewidth=1.6 if label == "combined" else 1.0,
                     label=f"{label}  (n={len(tr)})")
    asymp_combined = trajs["combined"]["cum_abs_cos"].iloc[-1]
    ax_main.axhline(asymp_combined, color="#1f4a7a", linestyle=":",
                    linewidth=1.0, alpha=0.7,
                    label=f"combined 5-y asymptote = {asymp_combined:.3f}")
    ax_main.axvline(152, color="gray", linestyle="--", linewidth=1.0,
                    label="5 months (Lee et al. 2025)")
    for th in THRESHOLDS:
        ax_main.axhline(th, color="black", linestyle=":", linewidth=0.5, alpha=0.4)
    ax_main.set_xlabel("Days since first scene")
    ax_main.set_ylabel(r"$|\langle \cos\theta \rangle|$")
    ax_main.set_title("(a) Cumulative-sample convergence at Garorim Bay")
    ax_main.set_xlim(0, trajs["combined"]["days_since_start"].max())
    ax_main.set_ylim(0, max(0.6, asymp_combined * 1.6))
    ax_main.grid(alpha=0.3)
    ax_main.legend(fontsize=8, loc="upper right", frameon=False)

    # (b) Implied mean-bias trajectory β·A·|⟨cos θ⟩| (signed for cos<0).
    sign = -1.0 if trajs["combined"]["cum_cos"].iloc[-1] < 0 else 1.0
    for label, tr in trajs.items():
        bias = sign * beta * A_site * tr["cum_abs_cos"] + c0
        ax_bias.plot(tr["days_since_start"], bias, color=SENSOR_COLORS[label],
                     linewidth=1.6 if label == "combined" else 1.0,
                     label=f"{label}")
    asymp_bias = sign * beta * A_site * asymp_combined + c0
    ax_bias.axhline(asymp_bias, color="#1f4a7a", linestyle=":",
                    linewidth=1.0, alpha=0.7,
                    label=f"combined asymptote = {asymp_bias:+.2f} m")
    ax_bias.axvline(152, color="gray", linestyle="--", linewidth=1.0,
                    label="5 months")
    ax_bias.axhline(-0.279, color="red", linestyle=":", linewidth=1.2,
                    label="Lee et al. (2025) optical-only MAE −0.279 m")
    ax_bias.set_xlabel("Days since first scene")
    ax_bias.set_ylabel("Predicted mean tide-height bias (m)")
    ax_bias.set_title(rf"(b) Implied bias $-\beta \cdot A \cdot |\langle\cos\theta\rangle| + c_0$  "
                      rf"($\beta$={beta:.2f}, $A$={A_site:.2f} m)")
    ax_bias.grid(alpha=0.3)
    ax_bias.legend(fontsize=8, loc="upper right", frameon=False)

    # (c) Start-time sensitivity.
    for stamp, tr in sens.items():
        ax_sens.plot(tr["days_since_start"], tr["cum_abs_cos"],
                     linewidth=1.0, label=f"start {stamp}")
    ax_sens.axhline(asymp_combined, color="#1f4a7a", linestyle=":",
                    linewidth=1.0, alpha=0.7)
    ax_sens.axvline(152, color="gray", linestyle="--", linewidth=1.0)
    ax_sens.set_xlim(0, 600)
    ax_sens.set_xlabel("Days since (chosen) start")
    ax_sens.set_ylabel(r"$|\langle \cos\theta \rangle|$")
    ax_sens.set_title("(c) Start-time sensitivity (combined sensors)")
    ax_sens.grid(alpha=0.3)
    ax_sens.legend(fontsize=8, loc="upper right", frameon=False)

    # (d) Zoom on first year.
    ax_zoom.fill_between(env["days"], env["p025"], env["p975"],
                         color="#1f4a7a", alpha=0.15)
    for label, tr in trajs.items():
        ax_zoom.plot(tr["days_since_start"], tr["cum_abs_cos"],
                     color=SENSOR_COLORS[label],
                     linewidth=1.6 if label == "combined" else 1.0,
                     label=label)
    ax_zoom.axhline(asymp_combined, color="#1f4a7a", linestyle=":",
                    linewidth=1.0, alpha=0.7)
    ax_zoom.axvline(152, color="gray", linestyle="--", linewidth=1.4,
                    label="5 months")
    ax_zoom.axhspan((1 - ASYMPTOTE_BAND) * asymp_combined,
                    (1 + ASYMPTOTE_BAND) * asymp_combined,
                    color="#1f4a7a", alpha=0.07,
                    label=f"±{int(ASYMPTOTE_BAND*100)} % asymptote band")
    ax_zoom.set_xlim(0, 365)
    ax_zoom.set_ylim(0, max(0.6, asymp_combined * 1.6))
    ax_zoom.set_xlabel("Days since first scene")
    ax_zoom.set_ylabel(r"$|\langle \cos\theta \rangle|$")
    ax_zoom.set_title("(d) Zoom: first 365 days")
    ax_zoom.grid(alpha=0.3)
    ax_zoom.legend(fontsize=8, loc="upper right", frameon=False)

    fig.suptitle(
        f"Convergence of $|\\langle\\cos\\theta\\rangle|$ at Garorim Bay (2020–2024) — "
        f"empirical test of the 5-month optimum (Lee et al. 2025)",
        y=1.00, fontsize=12,
    )
    fig.tight_layout()
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=200, bbox_inches="tight")
    log.info("Wrote %s", OUT_FIG)

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    print()
    print("=" * 90)
    print(f"GARORIM BAY |⟨cos θ⟩|(t) convergence summary — A = {A_site:.2f} m, "
          f"β = {beta:.2f}")
    print("=" * 90)
    cols = ["population", "n_scenes", "duration_days",
            "asymptote_abs_cos", "t_converge_d", "abs_cos_at_152d",
            "pred_bias_asymptote_m", "pred_bias_152d_m"]
    for th in THRESHOLDS:
        cols.append(f"days_below_{int(th*100):03d}pct")
    print(thr_df[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    print()
    print("Block-bootstrap envelope at key times (combined sensors):")
    for d in [30, 60, 90, 120, 152, 180, 365, 730]:
        row = env.iloc[(env["days"] - d).abs().argmin()]
        print(f"  t = {int(row['days']):4d} d : |⟨cos θ⟩| ∈ [{row['p025']:.3f}, "
              f"{row['p975']:.3f}]  median = {row['p50']:.3f}")


if __name__ == "__main__":
    main()
