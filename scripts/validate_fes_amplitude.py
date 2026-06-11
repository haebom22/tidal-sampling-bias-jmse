"""Re-validate the FES2022b M2 amplitude extraction for the national tiles.

Motivation
----------
The national pipeline extracts the local M2 amplitude per tile with a
nearest-index ``searchsorted`` lookup that (a) is not a true nearest neighbour
and (b) does no land/NaN or coastal-artefact handling. Over the complex
Gyeonggi-Bay coastline this returns implausible values (e.g. 7.0 m at
K_1263_0378), which then over-scale the per-scene bias correction
``η_corr = η - β·A·cosθ``.

This script:
  1. Re-extracts the M2 amplitude at every pilot site and national tile centre
     with three estimators: the current ``searchsorted`` value, a true
     nearest-*valid* (finite, positive) cell, and a neighbourhood median over a
     small window of valid ocean cells.
  2. Flags tiles where the current value is a coastal-node artefact (deviates
     from the neighbourhood median by > THRESH or exceeds a physical cap).
  3. Benchmarks the pilot estimates against the trusted KHOA-derived
     amplitudes (``SITE_AMPLITUDE_M``).

Output
------
- data/outputs/tables/fes_amplitude_validation.csv
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

from src.config import load_sites, resolve_path
from src.gee.dem import SITE_AMPLITUDE_M
from src.tides.fes_helpers import extract_m2_amplitude, find_fes_directory

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("fes_amp")

# Physical cap for the Korean coast: the largest credible M2 amplitude in
# Gyeonggi Bay is ~3 m; anything above this at a tile centre is treated as a
# coastal-extrapolation artefact and re-estimated.
PHYS_CAP_M = 3.5
WINDOW_CELLS = 4  # +/- cells (~0.13 deg ~ 12 km) for the robust median


class FesAmpGrid:
    def __init__(self, model_dir: Path):
        cands = list(model_dir.glob("m2*fes2022*.nc")) + list(model_dir.glob("m2*fes2014*.nc"))
        if not cands:
            raise FileNotFoundError(f"No m2 NetCDF in {model_dir}")
        ds = xr.open_dataset(cands[0])
        self.lon = ds["lon"].values
        self.lat = ds["lat"].values
        amp = ds["amplitude"].values.astype("float64")  # cm, (lat, lon)
        amp = np.where(np.isfinite(amp) & (amp > 0), amp, np.nan)
        self.amp_cm = amp
        ds.close()

    def _idx(self, lon: float, lat: float) -> tuple[int, int]:
        q = lon if lon >= 0 else lon + 360.0
        i = int(np.argmin(np.abs(self.lon - q)))
        j = int(np.argmin(np.abs(self.lat - lat)))
        return j, i

    def nearest_valid(self, lon: float, lat: float, max_r: int = 8) -> float:
        j, i = self._idx(lon, lat)
        for r in range(max_r + 1):
            js = slice(max(0, j - r), j + r + 1)
            is_ = slice(max(0, i - r), i + r + 1)
            block = self.amp_cm[js, is_]
            if np.isfinite(block).any():
                # nearest valid within the smallest enclosing ring
                jj, ii = np.where(np.isfinite(block))
                cj = j - max(0, j - r)
                ci = i - max(0, i - r)
                d = (jj - cj) ** 2 + (ii - ci) ** 2
                return float(block[jj[np.argmin(d)], ii[np.argmin(d)]] / 100.0)
        return float("nan")

    def window_median(self, lon: float, lat: float, r: int = WINDOW_CELLS) -> float:
        j, i = self._idx(lon, lat)
        block = self.amp_cm[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
        if np.isfinite(block).any():
            return float(np.nanmedian(block) / 100.0)
        return float("nan")


def _load_tiles() -> list[dict]:
    cfg = yaml.safe_load(open(resolve_path("config/national_tiles_full.yaml")))
    return cfg["tiles"]


def main() -> None:
    model_dir, model_name = find_fes_directory(resolve_path("."))
    log.info("FES model: %s (%s)", model_name, model_dir)
    grid = FesAmpGrid(model_dir)

    rows: list[dict] = []

    # --- pilots vs KHOA reference ---
    for site in load_sites():
        if site.id not in SITE_AMPLITUDE_M:
            continue
        raw = extract_m2_amplitude(site.lon, site.lat, model_dir, robust=False)
        rows.append({
            "kind": "pilot", "id": site.id, "lon": site.lon, "lat": site.lat,
            "amp_raw_m": raw,
            "amp_nearest_valid_m": grid.nearest_valid(site.lon, site.lat),
            "amp_window_median_m": grid.window_median(site.lon, site.lat),
            "khoa_ref_m": SITE_AMPLITUDE_M[site.id],
            "region": "",
        })

    # --- national tiles ---
    for t in _load_tiles():
        lon = t["center"]["lon"]; lat = t["center"]["lat"]
        raw = extract_m2_amplitude(lon, lat, model_dir, robust=False)
        rob = extract_m2_amplitude(lon, lat, model_dir, robust=True, cap_m=PHYS_CAP_M)
        rows.append({
            "kind": "tile", "id": t["id"], "lon": lon, "lat": lat,
            "amp_raw_m": raw,
            "amp_robust_m": rob,
            "amp_nearest_valid_m": grid.nearest_valid(lon, lat),
            "amp_window_median_m": grid.window_median(lon, lat),
            "khoa_ref_m": np.nan,
            "region": t.get("region_hint", ""),
        })

    df = pd.DataFrame(rows)
    # Artefact flag: raw exceeds the physical cap OR deviates from the robust
    # window median by > 1.0 m.
    df["artefact"] = (
        (df["amp_raw_m"] > PHYS_CAP_M)
        | ((df["amp_raw_m"] - df["amp_window_median_m"]).abs() > 1.0)
    )
    # Recommended amplitude: window median (robust), clamped to the cap.
    df["amp_corrected_m"] = np.minimum(df["amp_window_median_m"], PHYS_CAP_M)

    out = resolve_path("data/outputs/tables/fes_amplitude_validation.csv")
    df.to_csv(out, index=False, float_format="%.4f")
    log.info("Wrote %s (%d rows)", out, len(df))

    print("\n=== PILOTS: FES raw vs robust vs KHOA ===")
    p = df[df["kind"] == "pilot"][
        ["id", "amp_raw_m", "amp_nearest_valid_m", "amp_window_median_m", "khoa_ref_m"]
    ]
    print(p.to_string(index=False, float_format="%.3f"))

    tiles = df[df["kind"] == "tile"]
    art = tiles[tiles["artefact"]]
    print(f"\n=== NATIONAL TILES: {len(art)} / {len(tiles)} flagged as artefact ===")
    if not art.empty:
        print(art[["id", "region", "amp_raw_m", "amp_window_median_m",
                   "amp_corrected_m"]].to_string(index=False, float_format="%.3f"))
    print(f"\nTile amp_raw: min={tiles.amp_raw_m.min():.2f} max={tiles.amp_raw_m.max():.2f} "
          f"mean={tiles.amp_raw_m.mean():.2f}")
    print(f"Tile amp_corrected: min={tiles.amp_corrected_m.min():.2f} "
          f"max={tiles.amp_corrected_m.max():.2f} mean={tiles.amp_corrected_m.mean():.2f}")


if __name__ == "__main__":
    main()
