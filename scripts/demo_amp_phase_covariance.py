"""Per-site covariance of local tidal amplitude A_local with cos θ.

This script quantifies the cov(A, cos θ) contribution to β > 1 demanded by
Section 5.1 mechanism (i) — spring-neap × phase covariance.

For every scene we recover the *local* tidal amplitude A_local from the KHOA
HW/LW envelope bracketing that scene's HW→HW cycle, then compute the per-site
statistics

    ⟨A_local⟩,
    ⟨cos θ⟩,
    ⟨A_local · cos θ⟩,
    cov(A_local, cos θ) = ⟨A·cos θ⟩ − ⟨A⟩⟨cos θ⟩,
    corr(A_local, cos θ) = cov / (σ_A · σ_cos).

If cov(A, cos θ) ≠ 0 the per-scene first-moment bias differs from
β · ⟨A⟩ · ⟨cos θ⟩ even at β = 1, so a positive covariance is sufficient by
itself to push the empirical β upward.

Outputs:
    data/outputs/tables/amp_phase_covariance.csv  (sensor + 'all' rows)
"""

from __future__ import annotations

import logging
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.phase import find_tide_extremes
from src.config import Site, load_sites
from src.tides.khoa import fetch_tide_hourly_range

warnings.filterwarnings("ignore", category=UserWarning,
                        message="no explicit representation of timezones")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("amp_phase_cov")

YEAR_START, YEAR_END = 2020, 2024

PHASE_PARQUET = Path("data/processed/multisite_5y_phases.parquet")
KHOA_DIR = Path("data/raw/khoa")
OUT_TABLE = Path("data/outputs/tables/amp_phase_covariance.csv")

SITE_ORDER = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]


def local_amplitudes(scene_times: np.ndarray,
                     hw_times: np.ndarray, hw_vals: np.ndarray,
                     lw_times: np.ndarray, lw_vals: np.ndarray) -> np.ndarray:
    """A_local = (prev HW + next HW)/2 − nearest LW in bracketed cycle.

    For each scene t we locate the prev/next HW that bracket t (same scheme as
    compute_phase_hw) and the LW occurring between them.  A_local is half the
    range of that single cycle.  Returns NaN if no bracketing trio is found.
    """
    q = scene_times.astype("datetime64[ns]").astype("int64")
    hw_i = hw_times.astype("datetime64[ns]").astype("int64")
    lw_i = lw_times.astype("datetime64[ns]").astype("int64")

    idx_next = np.searchsorted(hw_i, q, side="right")
    idx_prev = idx_next - 1
    valid_hw = (idx_prev >= 0) & (idx_next < len(hw_i))

    a = np.full(len(q), np.nan)
    if not valid_hw.any():
        return a

    hw_prev_t = hw_i[idx_prev[valid_hw]]
    hw_next_t = hw_i[idx_next[valid_hw]]
    hw_prev_v = hw_vals[idx_prev[valid_hw]]
    hw_next_v = hw_vals[idx_next[valid_hw]]

    # Find LW falling strictly inside (hw_prev_t, hw_next_t).
    lw_pos = np.searchsorted(lw_i, hw_prev_t, side="right")
    has_lw = (lw_pos < len(lw_i)) & (lw_i[np.clip(lw_pos, 0, len(lw_i) - 1)] < hw_next_t)
    lw_v = np.where(has_lw, lw_vals[np.clip(lw_pos, 0, len(lw_vals) - 1)], np.nan)

    mean_hw = 0.5 * (hw_prev_v + hw_next_v)
    a_loc = 0.5 * (mean_hw - lw_v)

    out = np.full(len(q), np.nan)
    out[np.where(valid_hw)[0]] = a_loc
    return out


def cov_stats(a: np.ndarray, c: np.ndarray) -> dict[str, float]:
    """Return summary stats for the (A_local, cos θ) pair, NaN-safe."""
    m = ~(np.isnan(a) | np.isnan(c))
    if m.sum() < 3:
        return dict(n=int(m.sum()), mean_A=np.nan, mean_cos=np.nan,
                    mean_Acos=np.nan, cov=np.nan, corr=np.nan,
                    std_A=np.nan, std_cos=np.nan,
                    Acos_minus_meanA_meancos=np.nan)
    a_, c_ = a[m], c[m]
    mean_a = float(a_.mean())
    mean_c = float(c_.mean())
    mean_ac = float((a_ * c_).mean())
    cov = mean_ac - mean_a * mean_c
    std_a = float(a_.std(ddof=1))
    std_c = float(c_.std(ddof=1))
    corr = cov / (std_a * std_c) if std_a > 0 and std_c > 0 else np.nan
    return dict(
        n=int(m.sum()),
        mean_A=mean_a,
        mean_cos=mean_c,
        mean_Acos=mean_ac,
        cov=cov,
        corr=corr,
        std_A=std_a,
        std_cos=std_c,
        Acos_minus_meanA_meancos=mean_ac - mean_a * mean_c,
    )


def load_extremes(site: Site) -> dict:
    """Pull the KHOA hourly cache and extract HW/LW extremes for the site."""
    station = site.khoa_stations[0]
    obs = fetch_tide_hourly_range(
        station.code, date(YEAR_START, 1, 1), date(YEAR_END, 12, 31), KHOA_DIR
    )
    obs = obs.sort_values("datetime_utc").reset_index(drop=True)
    ext = find_tide_extremes(obs)
    return dict(obs=obs, ext=ext, station=station)


def main() -> None:
    log.info("Loading cached phases parquet …")
    phases = pd.read_parquet(PHASE_PARQUET)
    phases["datetime_utc"] = pd.to_datetime(phases["datetime_utc"], utc=True)

    sites = {s.id: s for s in load_sites()}

    rows: list[dict] = []
    for sid in SITE_ORDER:
        if sid not in sites:
            log.warning("Site %s missing from config", sid)
            continue
        site = sites[sid]
        log.info("=== %s (%s) ===", sid, site.name_en)
        info = load_extremes(site)
        scenes = phases[phases["site_id"] == sid].copy()
        if scenes.empty:
            log.warning("No cached scenes for %s", sid)
            continue

        st = scenes["datetime_utc"].to_numpy().astype("datetime64[ns]")
        a_loc = local_amplitudes(
            st,
            info["ext"].high_times, info["ext"].high_vals,
            info["ext"].low_times, info["ext"].low_vals,
        )
        scenes = scenes.assign(A_local=a_loc)
        scenes = scenes.dropna(subset=["A_local", "cos_theta"])

        for sensor, sub in scenes.groupby("sensor"):
            s = cov_stats(sub["A_local"].to_numpy(),
                          sub["cos_theta"].to_numpy())
            rows.append({"site_id": sid, "sensor": sensor, **s})
        s_all = cov_stats(scenes["A_local"].to_numpy(),
                          scenes["cos_theta"].to_numpy())
        rows.append({"site_id": sid, "sensor": "all", **s_all})

    table = pd.DataFrame(rows)

    # Ensure deterministic column order.
    cols = ["site_id", "sensor", "n", "mean_A", "std_A", "mean_cos", "std_cos",
            "mean_Acos", "cov", "corr"]
    table = table[cols]

    OUT_TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_TABLE, index=False, float_format="%.5f")
    log.info("Wrote %s", OUT_TABLE)

    print()
    print("=" * 110)
    print("cov(A_local, cos θ) per site × sensor (cached KHOA + phases parquet, 2020-2024)")
    print("=" * 110)
    print(table.to_string(index=False, float_format=lambda v: f"{v:+.4f}"
                          if isinstance(v, float) else str(v)))

    # Decomposition of the β > 1 effect:
    # for each site, the empirical-bias predictor used in the OLS regression is
    #   β · ⟨A_5y⟩ · ⟨cos θ⟩,
    # whereas the *true* per-scene mean of A · cos θ equals
    #   ⟨A⟩⟨cos θ⟩ + cov(A, cos θ).
    # The implied β-inflation factor (still under cos θ correlation only) is
    #   1 + cov / (⟨A⟩ · ⟨cos θ⟩).
    print()
    print("Per-site implied β-inflation factor 1 + cov / (⟨A⟩⟨cos θ⟩):")
    summary = table[table["sensor"] == "all"].copy()
    summary["inflation_factor"] = 1.0 + (
        summary["cov"] / (summary["mean_A"] * summary["mean_cos"])
    )
    print(summary[["site_id", "n", "mean_A", "mean_cos", "cov", "corr",
                   "inflation_factor"]].to_string(
        index=False, float_format=lambda v: f"{v:+.4f}"))


if __name__ == "__main__":
    main()
