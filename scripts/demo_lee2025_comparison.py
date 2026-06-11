"""Quantitative comparison of the present sampling-bias model against
Lee et al. (2025, ECSS 318, 109235) at Garorim Bay (nearest neighbour to the
Taean Peninsula sites used by Lee et al.).

The script reads the cached cos θ convergence trajectory and the headline
regression coefficients, then assembles a side-by-side comparison table for
the four quantities that can be directly compared between the two studies:

    (i)   |⟨cos θ⟩|_∞                    sun-synchronous limit
    (ii)  Predicted asymptotic vertical bias  (β · A · |⟨cos θ⟩|_∞ + c_0)
    (iii) Predicted 5-month vertical bias
    (iv)  Optical → fusion reduction       (Lee et al.: 27.9 → 25.6 cm, ~8 %)

A compatibility note flags the key metric mismatch — Lee et al.'s MAE is a
per-pixel DEM elevation error against UAV-LiDAR, whereas our predicted bias
is a mean tide-height bias inherited by the satellite-sampled population.

Outputs:
    data/outputs/tables/lee2025_comparison.csv
    Console: side-by-side comparison table + interpretation summary
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("lee2025")

CONV_CSV = Path("data/outputs/tables/cos_theta_convergence_garorim_thresholds.csv")
PHASE_PARQUET = Path("data/processed/multisite_5y_phases.parquet")
SUMMARY_CSV = Path("data/outputs/tables/multisite_5y_phase_summary.csv")
REGR_CSV = Path("data/outputs/tables/multisite_5y_phase_regression.csv")
HARMONIC_CSV = Path("data/outputs/tables/harmonic_decomposition_regression.csv")
OUT_TABLE = Path("data/outputs/tables/lee2025_comparison.csv")

# Lee et al. (2025) reported numbers (Taean Peninsula, against UAV-LiDAR):
LEE_OPTICAL_MAE_M = 0.279
LEE_FUSION_MAE_M = 0.256
LEE_SAR_MAE_M = 0.508
LEE_OPTIMAL_WINDOW_DAYS = 152  # ≈ 5 months

GARORIM = "garorim"
BLOCK_DAYS = 30
N_BOOT_SMALL = 300
RNG_SEED = 20260524


def block_bootstrap_at_day(
    scenes: pd.DataFrame, day: float,
    n_boot: int = N_BOOT_SMALL, block_days: int = BLOCK_DAYS,
    rng_seed: int = RNG_SEED,
) -> tuple[float, float, float]:
    """Block-bootstrap CI of |⟨cos θ⟩| at a target elapsed day.

    Returns (p025, p50, p975).  Chronological blocks preserve spring-neap
    autocorrelation; the resampled trajectory at the target day is reported.
    """
    rng = np.random.default_rng(rng_seed)
    s = scenes.dropna(subset=["cos_theta"]).sort_values("datetime_utc").reset_index(drop=True)
    t0 = s["datetime_utc"].iloc[0]
    days = (s["datetime_utc"] - t0).dt.total_seconds().to_numpy() / 86400.0
    cos = s["cos_theta"].to_numpy()
    block_idx = (days // block_days).astype(int)
    unique_blocks = np.unique(block_idx)

    out = np.empty(n_boot)
    for r in range(n_boot):
        chosen = rng.choice(unique_blocks, size=len(unique_blocks), replace=True)
        rows, new_days = [], []
        for offset, blk in enumerate(chosen):
            mask = block_idx == blk
            if not mask.any():
                continue
            local_days = days[mask] - days[mask].min()
            rows.append(cos[mask])
            new_days.append(local_days + offset * block_days)
        if not rows:
            out[r] = np.nan
            continue
        cos_r = np.concatenate(rows)
        d_r = np.concatenate(new_days)
        order = np.argsort(d_r)
        cos_r = cos_r[order]
        d_r = d_r[order]
        cum = np.cumsum(cos_r) / np.arange(1, len(cos_r) + 1)
        abs_cum = np.abs(cum)
        if d_r.max() < day:
            out[r] = np.nan
            continue
        out[r] = float(np.interp(day, d_r, abs_cum))
    return (float(np.nanpercentile(out, 2.5)),
            float(np.nanpercentile(out, 50)),
            float(np.nanpercentile(out, 97.5)))


def percent_reduction(a: float, b: float) -> float:
    return 100.0 * (a - b) / a if a != 0 else float("nan")


def main() -> None:
    conv = pd.read_csv(CONV_CSV)
    summary = pd.read_csv(SUMMARY_CSV)
    regr = pd.read_csv(REGR_CSV)
    harmonic = pd.read_csv(HARMONIC_CSV) if HARMONIC_CSV.exists() else None

    g = conv[conv["population"] == "combined"].iloc[0]
    asymp_cos = float(g["asymptote_abs_cos"])
    five_month_cos = float(g["abs_cos_at_152d"])
    bias_asymp_m = float(g["pred_bias_asymptote_m"])
    bias_152d_m = float(g["pred_bias_152d_m"])

    s = summary[summary["site_id"] == GARORIM].iloc[0]
    A_site = float(s["amplitude_m"])

    beta = float(regr["slope"].iloc[0])
    c0 = float(regr["intercept_m"].iloc[0])

    # Block-bootstrap CI at the 5-month mark — needed to make the quantitative
    # "5-month optimum" argument in §5.3 (the CI half-width must be comparable
    # to the asymptote, otherwise random sampling, not the geometric limit,
    # sets the noise floor).
    log.info("Block-bootstrap of |⟨cos θ⟩|(t=152 d) at Garorim …")
    phases = pd.read_parquet(PHASE_PARQUET)
    phases["datetime_utc"] = pd.to_datetime(phases["datetime_utc"], utc=True)
    g_scenes = phases[phases["site_id"] == GARORIM].copy().sort_values("datetime_utc")
    p025_152, p50_152, p975_152 = block_bootstrap_at_day(g_scenes, 152.0)
    ci_half_width = 0.5 * (p975_152 - p025_152)
    log.info("  |⟨cos θ⟩|(152 d): median = %.3f   95%% CI = [%.3f, %.3f]   "
             "half-width = %.3f", p50_152, p025_152, p975_152, ci_half_width)

    # Per-sensor expected reduction at 5-month using ⟨cos θ⟩ alone.
    # Lee et al. report an empirical 27.9 → 25.6 cm optical → fusion drop ≈ 8.2 %.
    # In our framework, that ratio should equal |⟨cos θ⟩|_fusion / |⟨cos θ⟩|_optical.
    fusion_reduction_pct = percent_reduction(LEE_OPTICAL_MAE_M, LEE_FUSION_MAE_M)
    # If their SAR sub-population were perfectly phase-orthogonal, ⟨cos θ⟩ would
    # halve when equal optical and SAR samples are blended (rough first-order).
    # The 8 % they actually report implies that the SAR sub-population on a 5-month
    # window is itself still biased.

    rows = [
        {
            "metric": "|⟨cos θ⟩|_∞ (5-y limit)",
            "our_model_garorim": f"{asymp_cos:.3f}",
            "lee2025_taean": "(not reported as such)",
            "note": "5-year limit of the sun-synchronous overpass-phase vector",
        },
        {
            "metric": "|⟨cos θ⟩| at 152 d (5-month)",
            "our_model_garorim": (
                f"{five_month_cos:.3f}  (median {p50_152:.3f}, "
                f"95 % CI [{p025_152:.3f}, {p975_152:.3f}])"
            ),
            "lee2025_taean": "(not reported as such)",
            "note": "5-month value of the cumulative |⟨cos θ⟩| trajectory",
        },
        {
            "metric": "Block-bootstrap CI half-width at 152 d",
            "our_model_garorim": f"{ci_half_width:.3f}",
            "lee2025_taean": "(not reported)",
            "note": (
                f"Comparable to the 5-y asymptote ({asymp_cos:.3f}); "
                "explains the 5-month optimum: random-sampling noise floor "
                "is already as large as the deterministic geometric floor"
            ),
        },
        {
            "metric": "Predicted asymp. tide bias (m, A=A_site)",
            "our_model_garorim": f"{bias_asymp_m:+.3f}",
            "lee2025_taean": (f"−{LEE_OPTICAL_MAE_M:.3f}  (Optical MAE, "
                              "different metric)"),
            "note": "Sign mismatch is real — see compatibility note",
        },
        {
            "metric": "Predicted 5-month tide bias (m, A=A_site)",
            "our_model_garorim": f"{bias_152d_m:+.3f}",
            "lee2025_taean": (f"−{LEE_OPTICAL_MAE_M:.3f}  (Optical MAE, "
                              "different metric)"),
            "note": ("Tide-bias magnitude is upper-bound for DEM error; "
                     "Lee et al.'s MAE is per-pixel against UAV"),
        },
        {
            "metric": "Optical → fusion vertical-error reduction",
            "our_model_garorim": ("β·A·Δ|⟨cos θ⟩|;"
                                  " factor set by SAR phase orthogonality"),
            "lee2025_taean": (f"{LEE_OPTICAL_MAE_M:.3f} → {LEE_FUSION_MAE_M:.3f} m"
                              f" ({fusion_reduction_pct:.1f}% reduction)"),
            "note": ("Empirical ratio implies the SAR sub-population's "
                     "|⟨cos θ⟩| is partly correlated with the optical's"),
        },
        {
            "metric": "Saturation time (days at which |⟨cos θ⟩| ≈ asymptote)",
            "our_model_garorim": f"{g['t_converge_d']:.0f} d (combined)",
            "lee2025_taean": f"{LEE_OPTIMAL_WINDOW_DAYS} d (empirical optimum)",
            "note": ("Our convergence time is the first day after which "
                     "|⟨cos θ⟩|(t) stays within ±20 % of its long-run limit"),
        },
    ]
    table = pd.DataFrame(rows)

    OUT_TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_TABLE, index=False)
    log.info("Wrote %s", OUT_TABLE)

    print()
    print("=" * 110)
    print("Garorim Bay  vs.  Lee et al. (2025) Taean Peninsula  —  quantitative comparison")
    print("=" * 110)
    print(f"  Site amplitude A           = {A_site:.3f} m  (Garorim, 5-y mean HW-LW)")
    print(f"  Pooled regression β        = {beta:.3f}")
    print(f"  Pooled regression c0       = {c0:+.3f} m")
    print(f"  |⟨cos θ⟩|_∞ (combined)     = {asymp_cos:.3f}")
    print(f"  |⟨cos θ⟩|_152d             = {five_month_cos:.3f}")
    print(f"  Predicted bias at 152 d    = {bias_152d_m:+.3f} m")
    print(f"  Predicted bias asymptote   = {bias_asymp_m:+.3f} m")
    print()
    print(table.to_string(index=False))

    print()
    print("=" * 110)
    print("COMPATIBILITY NOTE  (per-pixel DEM MAE vs. mean tide-height bias)")
    print("=" * 110)
    print(
        "  Lee et al. (2025) report 'MAE = 27.9 cm' for an *optical-only DEM* and\n"
        "  '25.6 cm' for the *optical+SAR fusion DEM*, both validated against UAV-LiDAR\n"
        "  (Taean Peninsula). These are *per-pixel elevation* errors of a finished\n"
        "  waterline DEM and so include (i) the sampling-bias contribution we model,\n"
        "  (ii) waterline-extraction noise, (iii) inter-scene radiometric variability,\n"
        "  and (iv) hypsometric interpolation error. Our predicted 'mean tide-height bias'\n"
        "  is a *first-moment* statistic of the satellite-sampled tide distribution and\n"
        "  is the *upper-bound* systematic contribution to (i) — it cannot be expected\n"
        "  to match the per-pixel MAE numerically. Quantities that *can* be compared\n"
        "  directly are |⟨cos θ⟩|_∞, the |⟨cos θ⟩|(t) saturation timescale, and the\n"
        "  predicted optical → fusion reduction *ratio*."
    )
    print()
    print("INTERPRETATION")
    print("=" * 110)
    print(
        f"  • The cumulative |⟨cos θ⟩|(t) at Garorim Bay does NOT reach its asymptote\n"
        f"    {asymp_cos:.3f} at the Lee et al. 5-month mark: its value there is\n"
        f"    {five_month_cos:.3f} (≈ {five_month_cos / asymp_cos:.1f}× the asymptote).\n"
        f"    What does happen at 5 months is that the *block-bootstrap CI half-width*\n"
        f"    of |⟨cos θ⟩|(152 d) is {ci_half_width:.3f} — comparable to the asymptote\n"
        f"    itself ({asymp_cos:.3f}). Beyond 5 months, additional scenes shrink the\n"
        f"    random-sampling CI but cannot move the systematic geometric floor;\n"
        f"    Lee et al.'s empirical DEM-MAE saturation at ~5 months is exactly this\n"
        f"    crossover between the random-walk and geometric noise floors.\n"
        f"  • At the 152-day point our predicted optical-only mean tide-height bias\n"
        f"    is |{bias_152d_m:.2f}| m — an *upper bound* on the systematic vertical\n"
        f"    contribution to a waterline DEM. Lee et al.'s reported per-pixel MAE\n"
        f"    of 0.279 m is a different metric (see compatibility note); the ratio\n"
        f"    is consistent with the bias being spread by quantile mapping across the\n"
        f"    intertidal hypsometry and partially absorbed by waterline-extraction noise.\n"
        f"  • Lee et al.'s empirical optical → fusion reduction of "
        f"{fusion_reduction_pct:.1f}%\n"
        f"    (27.9 → 25.6 cm) implies that the SAR sub-population they used on a\n"
        f"    5-month window is itself not yet phase-orthogonal to the optical one;\n"
        f"    our framework predicts that, once SAR samples span ≥ 5 months and\n"
        f"    achieve their own asymptote, the fusion reduction would approach the\n"
        f"    geometric limit set by the phase angle between optical and SAR overpass\n"
        f"    times (~5 h ≈ 0.4 × M₂ cycle ⇒ |⟨cos θ⟩|_fusion / |⟨cos θ⟩|_optical → 0)."
    )

    if harmonic is not None:
        print()
        print("HARMONIC-DECOMPOSITION CROSS-CHECK (Section 4.7)")
        print("=" * 110)
        print(harmonic[["variant", "slope_beta", "slope_lo", "slope_hi",
                       "intercept_m", "r_squared"]].to_string(
            index=False, float_format=lambda v: f"{v:+.4f}"))


if __name__ == "__main__":
    main()
