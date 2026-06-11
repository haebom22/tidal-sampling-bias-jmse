"""FES2014 / FES2022b helpers for the national-scale pipeline.

Two operations needed when a KHOA tide gauge is unavailable:

1. **Hourly tide series at an arbitrary (lon, lat)** — drop-in
   replacement for ``fetch_tide_hourly_range`` used by the per-site
   waterline DEM driver.

2. **Local M2 amplitude (m)** — required for the per-scene bias
   correction ``η_corr = η_raw - β · A · cos θ``. Extracted directly
   from the FES M2 constituent NetCDF.

Both helpers default to FES2022b (if staged at
``data/raw/fes2022b``) and gracefully fall back to FES2014.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Default model directories searched in order.
DEFAULT_FES_DIRS = (
    "data/raw/fes2022b/ocean_tide_extrapolated",
    "data/raw/fes2014/ocean_tide_extrapolated",
    "data/raw/fes2014",
)


def find_fes_directory(project_root: Path) -> tuple[Path, str]:
    """Return ``(model_directory, model_name)`` for whichever FES is staged.

    Raises ``FileNotFoundError`` if neither is staged.
    """
    for rel in DEFAULT_FES_DIRS:
        p = project_root / rel
        if p.exists():
            name = "FES2022" if "fes2022" in rel else "FES2014"
            return p, name
    raise FileNotFoundError(
        f"No FES model directory found in any of: {DEFAULT_FES_DIRS}"
    )


# ---------------------------------------------------------------------------
# Hourly tide series at (lon, lat)
# ---------------------------------------------------------------------------

def fetch_tide_hourly_fes(
    lon: float,
    lat: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    model_directory: Path,
    *,
    model_name: str = "FES2014",
    sampling_minutes: int = 60,
    bounds: list[float] | None = None,
) -> pd.DataFrame:
    """Hourly tide series at ``(lon, lat)`` over ``[start, end]``.

    Returns a DataFrame with columns ``datetime_utc`` and ``tide_m``.
    Drop-in replacement for the KHOA-cached output schema.

    ``bounds`` (``[lon_min, lat_min, lon_max, lat_max]``) restricts the
    pyfes model load to a regional slice — strongly recommended on
    macOS, where loading the global grid can trigger NetCDF HDF errors
    and is ~6× slower than a 1° pad.
    """
    from .fes2014 import compute_tide_heights

    # Accept both tz-naive and tz-aware inputs. Newer pandas rejects
    # ``pd.Timestamp(value, tz=...)`` when value already carries tzinfo.
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    times = pd.date_range(start, end, freq=f"{sampling_minutes}min", tz="UTC")
    # Default to a ~1° pad around the point so pyfes only touches the
    # regional NetCDF slice. Callers (national_extent) can override with
    # the full tile bbox if they have one.
    if bounds is None:
        bounds = [lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5]
    heights = compute_tide_heights(
        lon=lon, lat=lat, times=times,
        model_directory=model_directory, model_name=model_name,
        bounds=bounds,
    )
    return pd.DataFrame({"datetime_utc": times, "tide_m": heights})


# ---------------------------------------------------------------------------
# M2 amplitude at (lon, lat) from FES NetCDF
# ---------------------------------------------------------------------------

def extract_m2_amplitude(
    lon: float,
    lat: float,
    model_directory: Path,
    *,
    constituent: str = "m2",
    robust: bool = True,
    window_cells: int = 4,
    outlier_margin_m: float = 1.0,
    cap_m: float | None = None,
) -> float:
    """Read the M2 (or other) amplitude (m) at ``(lon, lat)`` from FES NetCDF.

    The FES distribution stores ``<constituent>_<model>.nc`` with two
    variables: amplitude (cm) and phase (deg). Both FES2014 and
    FES2022b use the same conventions; the file name differs only by
    the trailing tag (``_fes2014.nc`` vs ``_fes2022.nc``).

    Robust extraction (default)
    ---------------------------
    The naive nearest-index lookup over the 1/30° FES grid is unreliable on
    complex coastlines: the chosen cell can be (i) land/NaN, or (ii) a coastal
    extrapolation node with an anomalously large amplitude (e.g. ~7 m in
    Gyeonggi Bay, where the true M2 is ~2–3 m). When ``robust=True`` we

      1. select the true nearest *valid* (finite, positive) ocean cell, and
      2. reject it as a coastal artefact if it deviates from the median of the
         surrounding ``window_cells`` window by more than ``outlier_margin_m``,
         falling back to that neighbourhood median;
      3. optionally clamp the result to ``cap_m`` (physical plausibility cap).
    """
    import xarray as xr

    candidates = (
        list(model_directory.glob(f"{constituent}*fes2022*.nc"))
        + list(model_directory.glob(f"{constituent}*fes2014*.nc"))
        + list(model_directory.glob(f"{constituent.upper()}*fes*.nc"))
        + list(model_directory.glob(f"{constituent}.nc"))
    )
    if not candidates:
        raise FileNotFoundError(
            f"No {constituent} NetCDF in {model_directory}"
        )
    ds = xr.open_dataset(candidates[0])
    amp_var = next(
        (v for v in ("amplitude", "Ha", "amp") if v in ds.data_vars),
        None,
    )
    if amp_var is None:
        ds.close()
        raise KeyError(
            f"No amplitude variable in {candidates[0]} (vars={list(ds.data_vars)})"
        )
    lon_arr = ds["lon"].values if "lon" in ds.coords else ds["longitude"].values
    lat_arr = ds["lat"].values if "lat" in ds.coords else ds["latitude"].values
    amp = np.asarray(ds[amp_var].values, dtype="float64")  # cm, (lat, lon)
    ds.close()
    amp = np.where(np.isfinite(amp) & (amp > 0), amp, np.nan)

    q_lon = lon if lon >= 0 else lon + 360.0
    i = int(np.argmin(np.abs(lon_arr - q_lon)))
    j = int(np.argmin(np.abs(lat_arr - lat)))

    if not robust:
        amp_cm = amp[j, i]
        if not np.isfinite(amp_cm) or amp_cm <= 0:
            return float("nan")
        return float(amp_cm / 100.0)

    # Neighbourhood median over a valid-ocean window (robust regional value).
    r = window_cells
    block = amp[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
    median_m = float(np.nanmedian(block) / 100.0) if np.isfinite(block).any() else float("nan")

    # Nearest *valid* cell (expanding rings up to 8 cells).
    nearest_m = float("nan")
    for rr in range(9):
        js = slice(max(0, j - rr), j + rr + 1)
        is_ = slice(max(0, i - rr), i + rr + 1)
        b = amp[js, is_]
        if np.isfinite(b).any():
            jj, ii = np.where(np.isfinite(b))
            cj = j - max(0, j - rr)
            ci = i - max(0, i - rr)
            d = (jj - cj) ** 2 + (ii - ci) ** 2
            nearest_m = float(b[jj[np.argmin(d)], ii[np.argmin(d)]] / 100.0)
            break

    value = nearest_m
    if not np.isfinite(value):
        value = median_m
    elif np.isfinite(median_m) and abs(value - median_m) > outlier_margin_m:
        # Treat the nearest cell as a coastal artefact; use the regional median.
        value = median_m

    if not np.isfinite(value) or value <= 0:
        return float("nan")
    if cap_m is not None:
        value = min(value, cap_m)
    return float(value)


__all__ = [
    "DEFAULT_FES_DIRS",
    "find_fes_directory",
    "fetch_tide_hourly_fes",
    "extract_m2_amplitude",
]
