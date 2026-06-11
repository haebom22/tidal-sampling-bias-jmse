"""Observation-frequency bias correction (Xin et al. 2025).

When a tidal-flat extent product is derived from satellite imagery, the
number of usable scenes per year ``N_t`` grows monotonically through
time (Landsat-9 joined Landsat-8 in 2021; Sentinel-2B was launched in
2017; cloud-free coverage improves). If the *reported* area ``A_t`` is
also positively correlated with ``N_t``, part of the apparent trend is
a *coverage artifact* rather than real tidal-flat change.

Xin et al. (2025; RSE) proposed an area-weighted regression to estimate
and remove this spurious component:

    A_t = γ_0 + γ_1 · N_t + ε_t

where the regression weight for each year is the reported area itself
(so a 0-km^2 year doesn't drag the slope). The corrected area is then

    A_t^corr = A_t - γ_1 · (N_t - N̄)

i.e. the time series is recentred to the long-term mean coverage.
A bootstrap CI on ``γ_1`` quantifies the significance of the
correction; if 0 lies inside the CI we report the raw value.

Usage
-----
This module is self-contained NumPy/SciPy. Provide a ``DataFrame``
with at least ``year``, ``area_km2``, and ``n_scenes`` columns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class ObsFreqFit:
    site_id: str
    gamma_0: float
    gamma_1: float
    gamma_1_ci_low: float
    gamma_1_ci_high: float
    significant: bool
    n_bar: float
    n_years: int


def _weighted_lsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """Weighted least squares for ``y = a + b * x``. Returns (intercept, slope)."""
    w = np.asarray(w, dtype=float)
    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    if w.sum() <= 0:
        b = np.polyfit(x, y, 1)
        return float(b[1]), float(b[0])
    W = np.diag(w)
    X = np.column_stack([np.ones_like(x), x])
    XtW = X.T @ W
    coef = np.linalg.solve(XtW @ X, XtW @ y)
    return float(coef[0]), float(coef[1])


def bootstrap_slope_ci(
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    n_boot: int = 2000,
    alpha: float = 0.05,
    random_state: int | None = 0,
) -> tuple[float, float]:
    """Bootstrap a 1-α confidence interval on the weighted slope.

    Resamples (x, y, w) triples with replacement.
    """
    rng = np.random.default_rng(random_state)
    n = len(x)
    if n < 4:
        return float("nan"), float("nan")
    slopes = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        _, b = _weighted_lsq(x[idx], y[idx], w[idx])
        slopes[i] = b
    lo, hi = np.quantile(slopes, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def fit_obsfreq_bias(
    df: pd.DataFrame,
    site_id: str,
    *,
    area_col: str = "area_km2",
    n_col: str = "n_scenes",
    year_col: str = "year",
    n_boot: int = 2000,
    alpha: float = 0.05,
) -> ObsFreqFit:
    """Estimate the area-weighted slope ``γ_1`` for one site's time series.

    Parameters
    ----------
    df
        DataFrame with at least the three columns.
    site_id
        For logging / book-keeping only.
    """
    sub = df.dropna(subset=[area_col, n_col, year_col])
    if len(sub) < 4:
        return ObsFreqFit(
            site_id=site_id, gamma_0=np.nan, gamma_1=np.nan,
            gamma_1_ci_low=np.nan, gamma_1_ci_high=np.nan,
            significant=False, n_bar=np.nan, n_years=len(sub),
        )

    x = sub[n_col].to_numpy(dtype=float)
    y = sub[area_col].to_numpy(dtype=float)
    w = sub[area_col].to_numpy(dtype=float)
    a, b = _weighted_lsq(x, y, w)
    lo, hi = bootstrap_slope_ci(x, y, w, n_boot=n_boot, alpha=alpha)
    significant = not (lo <= 0.0 <= hi)
    n_bar = float(np.mean(x))
    log.info(
        "%s: γ_1=%.3f km^2/scene (CI[%.3f, %.3f], %ssig.), N̄=%.1f, n_years=%d",
        site_id, b, lo, hi, "" if significant else "not ", n_bar, len(sub),
    )
    return ObsFreqFit(
        site_id=site_id, gamma_0=a, gamma_1=b,
        gamma_1_ci_low=lo, gamma_1_ci_high=hi,
        significant=significant, n_bar=n_bar, n_years=len(sub),
    )


def apply_obsfreq_correction(
    df: pd.DataFrame,
    fit: ObsFreqFit,
    *,
    area_col: str = "area_km2",
    n_col: str = "n_scenes",
    out_col: str | None = None,
    only_if_significant: bool = True,
) -> pd.DataFrame:
    """Add the corrected area column ``A_t^corr = A_t - γ_1 · (N_t - N̄)``.

    If ``only_if_significant=True`` and the slope CI brackets 0, the
    correction is *not* applied (corrected = raw).
    """
    out = df.copy()
    out_col = out_col or f"{area_col}_corrected"
    if (
        not np.isfinite(fit.gamma_1)
        or (only_if_significant and not fit.significant)
    ):
        out[out_col] = out[area_col]
        out["gamma_1_used"] = 0.0
    else:
        delta = fit.gamma_1 * (out[n_col].astype(float) - fit.n_bar)
        out[out_col] = out[area_col] - delta
        out["gamma_1_used"] = fit.gamma_1
    return out


def correct_all_sites(
    df: pd.DataFrame,
    site_col: str = "site_id",
    area_col: str = "area_km2",
    n_col: str = "n_scenes",
    year_col: str = "year",
    **fit_kwargs,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply per-site obs-frequency correction; return (corrected_df, fit_summary)."""
    fits: list[ObsFreqFit] = []
    corrected_chunks = []
    for site_id, chunk in df.groupby(site_col):
        fit = fit_obsfreq_bias(
            chunk, site_id=str(site_id),
            area_col=area_col, n_col=n_col, year_col=year_col,
            **fit_kwargs,
        )
        fits.append(fit)
        corrected_chunks.append(
            apply_obsfreq_correction(chunk, fit, area_col=area_col, n_col=n_col)
        )
    corrected = pd.concat(corrected_chunks, ignore_index=True)
    fit_df = pd.DataFrame([
        {
            "site_id": f.site_id,
            "gamma_0": f.gamma_0,
            "gamma_1_km2_per_scene": f.gamma_1,
            "gamma_1_ci_low": f.gamma_1_ci_low,
            "gamma_1_ci_high": f.gamma_1_ci_high,
            "significant": f.significant,
            "n_bar": f.n_bar,
            "n_years": f.n_years,
        }
        for f in fits
    ])
    return corrected, fit_df


__all__ = [
    "ObsFreqFit",
    "bootstrap_slope_ci",
    "fit_obsfreq_bias",
    "apply_obsfreq_correction",
    "correct_all_sites",
]
