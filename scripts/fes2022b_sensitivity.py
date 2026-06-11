#!/usr/bin/env python3
"""FES2022b sensitivity analysis — fast version.

Extracts per-constituent amplitude & phase at each site coordinate
directly from the NetCDF grids, then synthesises tide heights via
harmonic summation (avoiding full-grid loading via pyTMD).

Outputs
-------
- data/outputs/tables/fes2022b_sensitivity.csv   (15-row comparison)
- data/outputs/tables/fes2022b_regression.csv     (regression summary)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy import stats
from scipy.signal import find_peaks

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FES_DIR = PROJECT_ROOT / "data" / "raw" / "fes2022b" / "ocean_tide_extrapolated"

# 8 major constituents (captures >95 % of tidal variance)
CONSTITUENTS = ["m2", "s2", "k1", "o1", "n2", "p1", "k2", "q1"]

# Angular speeds (°/hour) — standard values from Doodson/Schureman
OMEGA_DEG_PER_HOUR = {
    "m2": 28.984104,
    "s2": 30.000000,
    "k1": 15.041069,
    "o1": 13.943036,
    "n2": 28.439730,
    "p1": 14.958931,
    "k2": 30.082138,
    "q1": 13.398661,
}

# Two coordinate sets: tidal-flat centre vs. nearest KHOA gauge (port)
SITES_FLAT = {
    "ganghwa":   {"lon": 126.450, "lat": 37.600, "name": "Ganghwa-do"},
    "garorim":   {"lon": 126.400, "lat": 37.000, "name": "Garorim Bay"},
    "gomso":     {"lon": 126.600, "lat": 35.600, "name": "Gomso Bay"},
    "hampyeong": {"lon": 126.400, "lat": 35.100, "name": "Hampyeong Bay"},
    "suncheon":  {"lon": 127.500, "lat": 34.900, "name": "Suncheon Bay"},
}
SITES_GAUGE = {
    "ganghwa":   {"lon": 126.5916, "lat": 37.4513, "name": "Ganghwa-do (Incheon gauge)"},
    "garorim":   {"lon": 126.1283, "lat": 36.6739, "name": "Garorim Bay (Anheung gauge)"},
    "gomso":     {"lon": 126.7150, "lat": 35.9919, "name": "Gomso Bay (Gunsan gauge)"},
    "hampyeong": {"lon": 126.4169, "lat": 35.2769, "name": "Hampyeong Bay (Yeonggwang gauge)"},
    "suncheon":  {"lon": 127.7647, "lat": 34.7472, "name": "Suncheon Bay (Yeosu gauge)"},
}
SITES = SITES_GAUGE  # default: gauge coordinates for FES

START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp("2024-12-31 23:00", tz="UTC")
EPOCH = pd.Timestamp("2000-01-01", tz="UTC")


def extract_constituents(lon: float, lat: float) -> dict[str, tuple[float, float]]:
    """Extract (amplitude_m, phase_deg) for each constituent at (lon, lat)."""
    result = {}
    for c in CONSTITUENTS:
        nc_path = FES_DIR / f"{c}_fes2022.nc"
        ds = xr.open_dataset(nc_path)
        amp = float(ds["amplitude"].interp(lon=lon, lat=lat, method="linear").values)
        pha = float(ds["phase"].interp(lon=lon, lat=lat, method="linear").values)
        ds.close()
        # FES amplitude is in cm → convert to metres
        result[c] = (amp / 100.0, pha)
    return result


def synthesize_tide(constituents: dict[str, tuple[float, float]],
                    times: pd.DatetimeIndex) -> np.ndarray:
    """Harmonic synthesis: η(t) = Σ Aᵢ cos(ωᵢt − φᵢ)."""
    hours = (times - EPOCH).total_seconds().values / 3600.0
    tide = np.zeros(len(times))
    for c, (amp, phase_deg) in constituents.items():
        omega = OMEGA_DEG_PER_HOUR[c]
        tide += amp * np.cos(np.radians(omega * hours - phase_deg))
    return tide


def hw_times(tide: np.ndarray, times: np.ndarray) -> np.ndarray:
    idx, _ = find_peaks(tide, distance=8)
    return times[idx]


def amplitude_from_series(tide: np.ndarray) -> float:
    hi, _ = find_peaks(tide, distance=8)
    lo, _ = find_peaks(-tide, distance=8)
    if len(hi) < 5 or len(lo) < 5:
        return float("nan")
    return 0.5 * (np.mean(tide[hi]) - np.mean(tide[lo]))


def phase_hw(q_times: np.ndarray, hw: np.ndarray) -> np.ndarray:
    q = q_times.astype("datetime64[ns]").astype("int64")
    h = hw.astype("datetime64[ns]").astype("int64")
    idx_next = np.searchsorted(h, q, side="right")
    idx_prev = idx_next - 1
    ok = (idx_prev >= 0) & (idx_next < len(h))
    phase = np.full(len(q), np.nan)
    if ok.any():
        prev = h[idx_prev[ok]]
        nxt = h[idx_next[ok]]
        cyc = (nxt - prev).astype(float)
        elap = (q[ok] - prev).astype(float)
        phase[ok] = np.where(cyc > 0, elap / cyc, np.nan)
    return phase


def ols_with_loo(df: pd.DataFrame) -> dict:
    x = df["A_cos_theta"].values
    y = df["mean_bias"].values
    slope, intercept, r_val, p_val, se = stats.linregress(x, y)

    sites = df["site_id"].unique()
    pred = np.full(len(df), np.nan)
    for hold in sites:
        trn = df[df["site_id"] != hold]
        tst = df["site_id"] == hold
        s, i, *_ = stats.linregress(trn["A_cos_theta"], trn["mean_bias"])
        pred[tst] = i + s * df.loc[tst, "A_cos_theta"]
    resid = y - pred
    loo_rmse = float(np.sqrt(np.nanmean(resid**2)))
    loo_r = float(np.corrcoef(y, pred)[0, 1])

    rng = np.random.default_rng(42)
    betas = [stats.linregress(
        x[ix := rng.choice(len(x), len(x), replace=True)], y[ix]
    )[0] for _ in range(2000)]
    ci_lo, ci_hi = np.percentile(betas, [2.5, 97.5])

    return dict(beta=slope, intercept=intercept, R2=r_val**2, p=p_val,
                ci_lo=ci_lo, ci_hi=ci_hi, loo_rmse=loo_rmse, loo_r=loo_r)


def main():
    t_start = time.time()
    print("=" * 62)
    print(" FES2022b Sensitivity Analysis (fast harmonic synthesis)")
    print("=" * 62)

    # 1. Load satellite scenes (with KHOA-interpolated tide_m)
    scenes = pd.read_parquet(
        PROJECT_ROOT / "data" / "processed" / "multisite_5y_satellite_tides.parquet"
    )
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
    print(f"\nSatellite scenes: {len(scenes):,}", flush=True)

    # 2. Load existing KHOA overall stats
    khoa_stats = pd.read_csv(
        PROJECT_ROOT / "data" / "outputs" / "tables" / "multisite_5y_overall.csv"
    )

    # 3. For each site: extract constituents, synthesize, compute bias
    print("\n[1/2] Extracting FES2022b constituents & synthesizing...", flush=True)
    times_1h = pd.date_range(START, END, freq="1h", tz="UTC")

    rows = []
    for sid, info in SITES.items():
        t0 = time.time()
        print(f"  {info['name']:15s} ... ", end="", flush=True)

        # Extract amp/phase at site coordinate
        site_const = extract_constituents(info["lon"], info["lat"])

        # Synthesize 5-year reference
        fes_tide = synthesize_tide(site_const, times_1h)
        fes_mean = float(np.mean(fes_tide))
        fes_A = amplitude_from_series(fes_tide)
        fes_hw = hw_times(fes_tide, times_1h.to_numpy())

        # Satellite-overpass FES tides (interpolate from reference)
        site_sc = scenes[scenes["site_id"] == sid].copy()
        sc_times = pd.to_datetime(site_sc["datetime_utc"], utc=True)
        fes_at_sat = np.interp(
            sc_times.values.astype("datetime64[ns]").astype("int64"),
            times_1h.values.astype("datetime64[ns]").astype("int64"),
            fes_tide,
        )

        # Phase from FES HW
        ph = phase_hw(sc_times.values.astype("datetime64[ns]"), fes_hw)
        cos_all = np.cos(2 * np.pi * ph)

        for sensor in sorted(site_sc["sensor"].unique()):
            mask = (site_sc["sensor"] == sensor).values
            n = int(mask.sum())
            cos_mean = float(np.nanmean(cos_all[mask]))

            # FES-based bias
            fes_bias = float(np.nanmean(fes_at_sat[mask])) - fes_mean

            # KHOA-based bias (from existing table)
            kr = khoa_stats[
                (khoa_stats["site_id"] == sid) & (khoa_stats["sensor"] == sensor)
            ]
            khoa_bias = float(kr["mean_bias"].iloc[0]) if len(kr) else float("nan")

            rows.append(dict(
                site_id=sid, site_name=info["name"], sensor=sensor, n=n,
                fes_A=fes_A, cos_theta=cos_mean,
                A_cos_theta=fes_A * cos_mean,
                mean_bias=fes_bias,
                khoa_mean_bias=khoa_bias,
                fes_mean_bias=fes_bias,
            ))

        # Report M2 amplitude
        m2_amp = site_const["m2"][0]
        print(f"A={fes_A:.2f} m  M2={m2_amp:.2f} m  ({time.time()-t0:.1f}s)", flush=True)

    result = pd.DataFrame(rows)

    # 4. Regression
    print("\n[2/2] OLS regression ...", flush=True)
    reg = ols_with_loo(result)

    print(f"\n{'='*62}")
    print(f" FES2022b reference regression")
    print(f"{'='*62}")
    print(f"  β         = {reg['beta']:.2f}  (95 % CI [{reg['ci_lo']:.2f}, {reg['ci_hi']:.2f}])")
    print(f"  intercept = {reg['intercept']:.3f} m")
    print(f"  R²        = {reg['R2']:.3f}")
    print(f"  LOO RMSE  = {reg['loo_rmse']:.2f} m")
    print(f"  LOO r     = {reg['loo_r']:.3f}")

    print(f"\n{'─'*62}")
    print(f" Side-by-side comparison")
    print(f"{'─'*62}")
    fmt = "  {:<22s} {:>6s} {:>8s} {:>10s}"
    print(fmt.format("Reference", "β", "R²", "LOO RMSE"))
    print(fmt.format("KHOA obs (§4.3)", "1.78", "0.980", "0.16 m"))
    print(fmt.format("UTide astro (§4.7c)", "1.90", "0.974", "~0.17 m"))
    print(f"  {'FES2022b':<22s} {reg['beta']:>6.2f} {reg['R2']:>8.3f} {reg['loo_rmse']:>.2f} m")

    # Per-site bias comparison
    print(f"\n{'─'*62}")
    print(f" Per-sensor bias comparison (KHOA vs FES2022b)")
    print(f"{'─'*62}")
    print(f"  {'Site':<15s} {'Sensor':>6s} {'KHOA bias':>10s} {'FES bias':>10s} {'Δ':>8s}")
    for _, r in result.iterrows():
        delta = r["fes_mean_bias"] - r["khoa_mean_bias"]
        print(f"  {r['site_name']:<15s} {r['sensor']:>6s} "
              f"{r['khoa_mean_bias']:>10.3f} {r['fes_mean_bias']:>10.3f} {delta:>+8.3f}")

    # Save
    out = PROJECT_ROOT / "data" / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    result.to_csv(out / "fes2022b_sensitivity.csv", index=False)
    pd.DataFrame([reg]).to_csv(out / "fes2022b_regression.csv", index=False)
    print(f"\n  Saved: {out / 'fes2022b_sensitivity.csv'}")
    print(f"  Saved: {out / 'fes2022b_regression.csv'}")
    print(f"\n  Total time: {time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
