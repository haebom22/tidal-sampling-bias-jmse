"""Tidal-phase quantification utilities.

Given a dense observed (or modelled) tide series, we extract local high-water
(HW) and low-water (LW) times, then for any "query" time t we compute the
normalised position of t within its tidal cycle.

Two complementary phase conventions are provided:

* ``phase_HW`` (float, [0, 1)):
    Position between *two consecutive HW events* containing t.
    0 = HW just passed, ~0.5 = LW, ~1 → next HW.
    The associated angle theta = 2π · phase_HW so that
        cos(theta) = +1 at HW
        cos(theta) = -1 at LW
    Useful for predicting bias direction: if satellites overpass at
    phases near 0 (HW), cos(theta) → +1 → positive (high) bias; near LW,
    cos(theta) → -1 → negative (low) bias.

* ``phase_normalised`` (float, [0, 1]):
    Position between the *nearest LW (below) and HW (above)* of t — this is
    a 0=LW / 1=HW scaling.  Useful as a tide-stage proxy regardless of
    cycle length.

The phase computation is vectorised using ``np.searchsorted``.

Why this works:
For a near-symmetric M2-dominated signal, the elevation can be written
    η(t) ≈ A(t) · cos(2π · phase_HW(t)) + msl_drift
so that the satellite-sampled mean bias is approximately
    ⟨η_sat⟩ − ⟨η_ref⟩ ≈ A · ⟨cos(theta_sat)⟩
i.e. the mean bias is proportional to the mean cosine of the satellite
overpass phase.  We verify this prediction empirically.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import find_peaks


@dataclass
class TideExtremes:
    high_times: np.ndarray   # datetime64[ns] (UTC)
    high_vals: np.ndarray
    low_times: np.ndarray
    low_vals: np.ndarray


def find_tide_extremes(
    obs: pd.DataFrame,
    time_col: str = "datetime_utc",
    tide_col: str = "tide_m",
    min_separation_hours: int = 8,
) -> TideExtremes:
    """Locate local high-water and low-water events from an hourly series.

    Parameters
    ----------
    obs
        DataFrame with hourly tide observations.  Must be sorted in
        chronological order with regular ~1h spacing.
    min_separation_hours
        Minimum index distance between consecutive peaks.  For 1-hour
        sampling and M2 dominance (~12.42 h cycle), 8 is conservative.
    """
    obs = obs.sort_values(time_col).reset_index(drop=True)
    tide = obs[tide_col].to_numpy(dtype=float)
    times = pd.to_datetime(obs[time_col], utc=True).to_numpy()

    high_idx, _ = find_peaks(tide, distance=min_separation_hours)
    low_idx, _ = find_peaks(-tide, distance=min_separation_hours)

    return TideExtremes(
        high_times=times[high_idx],
        high_vals=tide[high_idx],
        low_times=times[low_idx],
        low_vals=tide[low_idx],
    )


def compute_phase_hw(
    query_times: pd.Series | np.ndarray,
    high_times: np.ndarray,
) -> np.ndarray:
    """Normalised position within the HW → next-HW interval (∈ [0, 1)).

    Vectorised with ``np.searchsorted``.  Returns NaN if either bracket
    is unavailable (query at the very start/end of the record).
    """
    q = pd.to_datetime(query_times, utc=True).to_numpy()
    hw = pd.to_datetime(high_times, utc=True).to_numpy()

    q_i64 = q.astype("datetime64[ns]").astype("int64")
    hw_i64 = hw.astype("datetime64[ns]").astype("int64")

    idx_next = np.searchsorted(hw_i64, q_i64, side="right")
    idx_prev = idx_next - 1
    valid = (idx_prev >= 0) & (idx_next < len(hw_i64))

    phase = np.full(len(q_i64), np.nan)
    if valid.any():
        t_prev = hw_i64[idx_prev[valid]]
        t_next = hw_i64[idx_next[valid]]
        t_q = q_i64[valid]
        with np.errstate(divide="ignore", invalid="ignore"):
            cycle = (t_next - t_prev).astype(float)
            elapsed = (t_q - t_prev).astype(float)
            phase[valid] = np.where(cycle > 0, elapsed / cycle, np.nan)
    return phase


def compute_phase_normalised(
    query_times: pd.Series | np.ndarray,
    extremes: TideExtremes,
) -> np.ndarray:
    """0=LW, 1=HW scaling using nearest enclosing LW/HW bracket."""
    q = pd.to_datetime(query_times, utc=True).to_numpy()
    hw = pd.to_datetime(extremes.high_times, utc=True).to_numpy()
    lw = pd.to_datetime(extremes.low_times, utc=True).to_numpy()

    out = np.full(len(q), np.nan)
    q_i64 = q.astype("datetime64[ns]").astype("int64")
    hw_i64 = hw.astype("datetime64[ns]").astype("int64")
    lw_i64 = lw.astype("datetime64[ns]").astype("int64")

    for i, t in enumerate(q_i64):
        hw_after_idx = np.searchsorted(hw_i64, t, side="left")
        lw_after_idx = np.searchsorted(lw_i64, t, side="left")
        hw_before_idx = hw_after_idx - 1
        lw_before_idx = lw_after_idx - 1

        hw_before = hw_i64[hw_before_idx] if hw_before_idx >= 0 else None
        hw_after = hw_i64[hw_after_idx] if hw_after_idx < len(hw_i64) else None
        lw_before = lw_i64[lw_before_idx] if lw_before_idx >= 0 else None
        lw_after = lw_i64[lw_after_idx] if lw_after_idx < len(lw_i64) else None

        if (
            hw_before is not None and lw_before is not None
            and hw_before > lw_before
            and lw_after is not None
        ):
            t_lo = hw_before
            t_hi = lw_after
            ascend = False
        elif (
            lw_before is not None and hw_after is not None
            and (hw_before is None or lw_before > hw_before)
        ):
            t_lo = lw_before
            t_hi = hw_after
            ascend = True
        else:
            continue

        denom = t_hi - t_lo
        if denom <= 0:
            continue
        frac = (t - t_lo) / float(denom)
        out[i] = frac if ascend else 1.0 - frac
    return out


def circular_mean(phases: np.ndarray) -> float:
    """Mean of phases on the unit circle.  Returns in [0, 1)."""
    p = phases[~np.isnan(phases)]
    if p.size == 0:
        return float("nan")
    angles = 2 * np.pi * p
    mean_x = np.mean(np.cos(angles))
    mean_y = np.mean(np.sin(angles))
    mean_angle = np.arctan2(mean_y, mean_x)
    if mean_angle < 0:
        mean_angle += 2 * np.pi
    return float(mean_angle / (2 * np.pi))


def circular_std(phases: np.ndarray) -> float:
    """Circular standard deviation of phases."""
    p = phases[~np.isnan(phases)]
    if p.size == 0:
        return float("nan")
    angles = 2 * np.pi * p
    R = np.sqrt(np.mean(np.cos(angles)) ** 2 + np.mean(np.sin(angles)) ** 2)
    return float(np.sqrt(-2 * np.log(R))) if R > 0 else float("inf")


def phase_statistics(phases: np.ndarray) -> dict:
    """Summarise a vector of phases with circular statistics."""
    p = phases[~np.isnan(phases)]
    if p.size == 0:
        return dict(n=0)
    angles = 2 * np.pi * p
    cos_mean = float(np.mean(np.cos(angles)))
    sin_mean = float(np.mean(np.sin(angles)))
    R = np.sqrt(cos_mean ** 2 + sin_mean ** 2)
    mean_phase = circular_mean(p)
    return dict(
        n=int(p.size),
        mean_phase=mean_phase,
        mean_phase_deg=float(360 * mean_phase),
        cos_mean=cos_mean,
        sin_mean=sin_mean,
        R=float(R),
        circ_std=circular_std(p),
    )
