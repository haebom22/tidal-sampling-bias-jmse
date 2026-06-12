#!/usr/bin/env python3
"""Overseas a-priori transferability demo.

Applies the paper's bias model to macrotidal coasts OUTSIDE Korea using ONLY
public global data — no local tide gauge:

  * satellite overpass times  -> real Landsat-8/9 + Sentinel-2 scene metadata
                                 pulled live from Google Earth Engine
  * local tide                -> FES2022b global ocean-tide model (harmonic
                                 synthesis at the site coordinate)

For each site it reports the satellite-overpass phase concentration <cos theta>,
the FES tidal amplitude A, the model-predicted mean bias (beta * A * <cos theta>,
beta = 1.78 from the Korean fit), and the FES-self-consistent "observed" sampling
bias (mean FES tide at scene times, since the harmonic series has zero mean).
This is an a-priori PREDICTION (sign + magnitude), not an independent validation.

Run:  PYTHONPATH=. .venv/bin/python scripts/overseas_demo.py
Out:  data/outputs/tables/overseas_demo.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gee import metadata as gee_meta  # noqa: E402
from src.gee.auth import initialize as ee_init  # noqa: E402

FES_DIR = ROOT / "data" / "raw" / "fes2022b" / "ocean_tide_extrapolated"
OUT = ROOT / "data" / "outputs" / "tables" / "overseas_demo.csv"

CONST = ["m2", "s2", "k1", "o1", "n2", "p1", "k2", "q1"]
OMEGA = {"m2": 28.984104, "s2": 30.0, "k1": 15.041069, "o1": 13.943036,
         "n2": 28.439730, "p1": 14.958931, "k2": 30.082138, "q1": 13.398661}
EPOCH = pd.Timestamp("2000-01-01", tz="UTC")
START, END = "2020-01-01", "2024-12-31"
BETA = 1.78
CLOUD_MAX = 60.0
SENSORS = ["L8", "L9", "S2"]

# Macrotidal coasts spanning distinct regimes; centre is a tidal-flat/coastal
# water point used for FES synthesis, bbox is the GEE scene-search footprint.
SITES = [
    {"id": "king_sound",   "name": "King Sound, NW Australia (mixed)",
     "lon": 123.50, "lat": -16.90, "bbox": [123.20, -17.20, 123.90, -16.60]},
    {"id": "wadden_sea",   "name": "Wadden Sea / German Bight (M2 flats)",
     "lon": 8.30,   "lat": 53.85, "bbox": [8.00, 53.60, 8.70, 54.05]},
    {"id": "bay_of_fundy", "name": "Bay of Fundy / Minas Basin (max tide)",
     "lon": -64.00, "lat": 45.35, "bbox": [-64.40, 45.20, -63.60, 45.55]},
]


def extract(lon: float, lat: float) -> dict[str, tuple[float, float]]:
    out = {}
    for c in CONST:
        ds = xr.open_dataset(FES_DIR / f"{c}_fes2022.nc")
        amp = float(ds["amplitude"].interp(lon=lon % 360, lat=lat, method="linear").values)
        pha = float(ds["phase"].interp(lon=lon % 360, lat=lat, method="linear").values)
        ds.close()
        out[c] = (amp / 100.0, pha)  # cm -> m
    return out


def synth(cons: dict, times: pd.DatetimeIndex) -> np.ndarray:
    h = (times - EPOCH).total_seconds().values / 3600.0
    t = np.zeros(len(times))
    for c, (a, p) in cons.items():
        t += a * np.cos(np.radians(OMEGA[c] * h - p))
    return t


def cos_mean(scene_utc: np.ndarray, hw: np.ndarray) -> float:
    q = scene_utc.astype("datetime64[ns]").astype("int64")
    h = np.sort(hw.astype("datetime64[ns]").astype("int64"))
    nx = np.searchsorted(h, q, side="right")
    pv = nx - 1
    ok = (pv >= 0) & (nx < len(h))
    ph = np.full(len(q), np.nan)
    ph[ok] = (q[ok] - h[pv[ok]]).astype(float) / (h[nx[ok]] - h[pv[ok]]).astype(float)
    return float(np.nanmean(np.cos(2 * np.pi * ph)))


def main() -> None:
    ee_init()
    ref = pd.date_range(START, f"{END} 23:00", freq="1h", tz="UTC")
    rows = []
    for s in SITES:
        # 1. real satellite overpass times from GEE (metadata only)
        scenes = gee_meta.extract_bbox_metadata(
            s["id"], s["bbox"], SENSORS, START, END)
        scenes = scenes[scenes["cloud_cover"].fillna(0) <= CLOUD_MAX]
        sc_times = pd.to_datetime(scenes["datetime_utc"], utc=True)
        n = len(sc_times)

        # 2. FES tide at the site coordinate
        cons = extract(s["lon"], s["lat"])
        if not np.isfinite(cons["m2"][0]):
            print(f"  !! {s['id']}: FES NaN at centre (land cell) — nudge coords")
            continue
        tide = synth(cons, ref)
        hi, _ = find_peaks(tide, distance=8)
        lo, _ = find_peaks(-tide, distance=8)
        A = 0.5 * (tide[hi].mean() - tide[lo].mean())
        hw = ref.values[hi]

        # 3. phase concentration + biases
        cm = cos_mean(sc_times.values.astype("datetime64[ns]"), hw)
        pred = BETA * A * cm
        # FES-self-consistent observed bias: mean FES tide at scene times
        sc_idx = np.searchsorted(
            ref.values.astype("datetime64[ns]").astype("int64"),
            sc_times.values.astype("datetime64[ns]").astype("int64"))
        sc_idx = np.clip(sc_idx, 0, len(tide) - 1)
        obs = float(tide[sc_idx].mean() - tide.mean())

        rows.append({
            "site": s["name"], "n_scenes": n, "M2_amp_m": round(cons["m2"][0], 2),
            "A_m": round(A, 2), "cos_theta": round(cm, 3),
            "pred_bias_m": round(pred, 2), "fes_obs_bias_m": round(obs, 2),
            "sign": "+" if pred > 0 else "-"})
        print(f"  {s['name']:42s} n={n:4d}  M2={cons['m2'][0]:.2f}  "
              f"A={A:.2f}  <cosθ>={cm:+.3f}  pred={pred:+.2f}m  obs={obs:+.2f}m")

    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"\nwrote {OUT}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
