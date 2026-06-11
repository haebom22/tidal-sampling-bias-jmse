"""Quantile-mapping DEM-error estimation for waterline tidal-flat DEMs.

Theory
------
In the waterline method, the shoreline observed in a satellite image at
acquisition time t lies along the iso-elevation contour z = η(t), where
η is the tide height at the gauge representative of the site.  Stacking
many waterlines from images taken at different tidal stages produces a
discrete sampling of the intertidal hypsometric curve, which is then
interpolated into a DEM.

If the *true* set of waterlines were uniformly distributed in time, the
empirical distribution of η_sat would match the reference tide
distribution η_ref.  Because sun-synchronous satellites sample a biased
subset of phases, the two distributions differ -- and the DEM inherits
the difference.

For a fixed cumulative probability p,
    z_true(p) = Q_ref(p)        ← elevation that is exceeded with prob 1-p
    z_DEM(p)  = Q_sat(p)        ← elevation assigned to that point by sat sampling
    error(p)  = z_DEM(p) - z_true(p)

This is a *quantile-quantile* mapping of the bias from the tide-height
distribution to the elevation domain.

Two derived quantities are particularly informative:

1. Mean elevation bias  ≡ ⟨error⟩  (=  ⟨η_sat⟩ - ⟨η_ref⟩,  same as the
   bias studied in B-3/B-4a).
2. RMSE elevation       ≡ √⟨error²⟩  -- a measure of the *typical*
   DEM error magnitude across the intertidal zone, sensitive to both
   mean shift and distribution shape (not only the mean).
3. Truncated elevation bands -- portions of the intertidal range that
   are never sampled by satellites (z above max-sat or below min-sat).
   These produce *missing contours*; in practice waterline DEMs
   extrapolate or just leave gaps in these bands.

Tidal flats are roughly planar with slope s [m/m] (typical 0.0005 to
0.005).  The vertical errors translate directly to horizontal
displacement of contours by  dx = dz / s, so all metrics in the
elevation domain also give the equivalent shoreline-position error.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DemErrorCurve:
    p: np.ndarray
    z_ref: np.ndarray
    z_sat: np.ndarray
    error_m: np.ndarray

    def as_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame({
            "p": self.p, "z_ref": self.z_ref,
            "z_sat": self.z_sat, "error_m": self.error_m,
        })


def quantile_error_curve(
    ref: np.ndarray,
    sat: np.ndarray,
    n_grid: int = 101,
    p_min: float = 0.005,
    p_max: float = 0.995,
) -> DemErrorCurve:
    """Per-quantile elevation error: Q_sat(p) - Q_ref(p)."""
    ref = np.asarray(ref, dtype=float)
    sat = np.asarray(sat, dtype=float)
    ref = ref[~np.isnan(ref)]
    sat = sat[~np.isnan(sat)]
    p = np.linspace(p_min, p_max, n_grid)
    z_ref = np.quantile(ref, p)
    z_sat = np.quantile(sat, p)
    return DemErrorCurve(p=p, z_ref=z_ref, z_sat=z_sat, error_m=z_sat - z_ref)


@dataclass
class DemErrorStats:
    n_sat: int
    n_ref: int
    elevation_range_m: float        # Q_ref(0.995) - Q_ref(0.005)
    mean_bias_m: float              # ⟨z_sat - z_ref⟩ = ⟨η_sat - η_ref⟩
    rmse_m: float                   # √⟨(z_sat - z_ref)²⟩
    max_abs_error_m: float
    median_error_m: float
    # Truncation: portions of the elevation range NOT sampled
    truncated_low_m: float          # below Q_sat_min within reference range
    truncated_high_m: float         # above Q_sat_max within reference range
    truncated_low_frac: float       # as a fraction of elevation_range_m
    truncated_high_frac: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def dem_error_stats(
    ref: np.ndarray,
    sat: np.ndarray,
    curve: DemErrorCurve | None = None,
    p_min: float = 0.005,
    p_max: float = 0.995,
) -> DemErrorStats:
    ref = np.asarray(ref, dtype=float)
    sat = np.asarray(sat, dtype=float)
    ref = ref[~np.isnan(ref)]
    sat = sat[~np.isnan(sat)]

    if curve is None:
        curve = quantile_error_curve(ref, sat, p_min=p_min, p_max=p_max)

    ref_lo = float(np.quantile(ref, p_min))
    ref_hi = float(np.quantile(ref, p_max))
    sat_lo = float(np.quantile(sat, p_min))
    sat_hi = float(np.quantile(sat, p_max))

    elev_range = ref_hi - ref_lo
    trunc_lo = max(0.0, sat_lo - ref_lo)
    trunc_hi = max(0.0, ref_hi - sat_hi)

    return DemErrorStats(
        n_sat=int(sat.size),
        n_ref=int(ref.size),
        elevation_range_m=float(elev_range),
        mean_bias_m=float(np.mean(curve.error_m)),
        rmse_m=float(np.sqrt(np.mean(curve.error_m ** 2))),
        max_abs_error_m=float(np.max(np.abs(curve.error_m))),
        median_error_m=float(np.median(curve.error_m)),
        truncated_low_m=float(trunc_lo),
        truncated_high_m=float(trunc_hi),
        truncated_low_frac=float(trunc_lo / elev_range) if elev_range > 0 else float("nan"),
        truncated_high_frac=float(trunc_hi / elev_range) if elev_range > 0 else float("nan"),
    )


def horizontal_equivalent(
    error_m: float | np.ndarray,
    slope: float,
) -> float | np.ndarray:
    """Convert vertical DEM error (m) to horizontal contour displacement (m).

    On a planar intertidal slope, ``dx = dz / slope``.
    """
    if slope <= 0:
        raise ValueError("slope must be positive")
    return error_m / slope
