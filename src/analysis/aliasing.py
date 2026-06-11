"""Tidal-aliasing statistics.

Given two tide-height samples for the same location -- a dense
``reference`` series representing the full astronomical tidal envelope,
and a sparse ``observed`` series taken at satellite acquisition times --
this module computes the bias metrics introduced by Bishop-Taylor et al.
(2019) and Geoscience Australia's ``eo-tides``:

    - spread       : observed tidal range / reference tidal range
    - low_offset   : fraction of the reference range below the lowest
                     observed tide (i.e. low tides never sampled)
    - high_offset  : fraction of the reference range above the highest
                     observed tide (i.e. high tides never sampled)
    - quantile_bias: KS-statistic between observed and reference CDFs
    - chi2_uniform : chi-squared statistic against a uniform reference
                     histogram (equal-area bins on the reference range)

All metrics are unit-less and bounded -- a perfectly unbiased sensor has
spread = 1, offsets = 0, and a low KS statistic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class AliasingStats:
    n_obs: int
    n_ref: int
    obs_min: float
    obs_max: float
    ref_min: float
    ref_max: float
    spread: float
    low_offset: float
    high_offset: float
    ks_statistic: float
    ks_pvalue: float
    chi2_uniform: float
    obs_mean: float
    ref_mean: float
    mean_bias: float

    def as_dict(self) -> dict[str, float | int]:
        return self.__dict__.copy()


def _percentile_range(arr: np.ndarray, low_q: float = 0.001, high_q: float = 0.999) -> tuple[float, float]:
    """Robust min/max using extreme percentiles (avoids outlier sensitivity)."""
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return float("nan"), float("nan")
    return float(np.quantile(arr, low_q)), float(np.quantile(arr, high_q))


def compute_aliasing(
    observed: np.ndarray,
    reference: np.ndarray,
    n_bins: int = 40,
) -> AliasingStats:
    """Compute aliasing metrics for one (sensor, site, period) combination.

    Parameters
    ----------
    observed
        Tide heights at satellite acquisition times.
    reference
        Dense synthetic tide series representing the full astronomical
        envelope at the same location.
    n_bins
        Number of bins for the chi-squared uniformity test.
    """
    obs = np.asarray(observed, dtype=float)
    ref = np.asarray(reference, dtype=float)
    obs = obs[~np.isnan(obs)]
    ref = ref[~np.isnan(ref)]

    if obs.size < 5 or ref.size < 5:
        return AliasingStats(
            n_obs=int(obs.size),
            n_ref=int(ref.size),
            obs_min=float("nan"),
            obs_max=float("nan"),
            ref_min=float("nan"),
            ref_max=float("nan"),
            spread=float("nan"),
            low_offset=float("nan"),
            high_offset=float("nan"),
            ks_statistic=float("nan"),
            ks_pvalue=float("nan"),
            chi2_uniform=float("nan"),
            obs_mean=float("nan"),
            ref_mean=float("nan"),
            mean_bias=float("nan"),
        )

    ref_min, ref_max = _percentile_range(ref)
    obs_min, obs_max = float(obs.min()), float(obs.max())
    ref_range = ref_max - ref_min
    if ref_range <= 0:
        spread = float("nan")
        low_offset = float("nan")
        high_offset = float("nan")
    else:
        spread = (obs_max - obs_min) / ref_range
        low_offset = max(0.0, (obs_min - ref_min) / ref_range)
        high_offset = max(0.0, (ref_max - obs_max) / ref_range)

    ks_stat, ks_p = stats.ks_2samp(obs, ref)

    # Chi-squared against uniform reference on equal-area bins.
    bin_edges = np.linspace(ref_min, ref_max, n_bins + 1)
    obs_hist, _ = np.histogram(obs, bins=bin_edges)
    expected = np.full(n_bins, obs.size / n_bins)
    # Guard against zero-expected bins (shouldn't happen with even bins).
    with np.errstate(divide="ignore", invalid="ignore"):
        chi2 = float(np.nansum((obs_hist - expected) ** 2 / expected))

    return AliasingStats(
        n_obs=int(obs.size),
        n_ref=int(ref.size),
        obs_min=obs_min,
        obs_max=obs_max,
        ref_min=ref_min,
        ref_max=ref_max,
        spread=float(spread),
        low_offset=float(low_offset),
        high_offset=float(high_offset),
        ks_statistic=float(ks_stat),
        ks_pvalue=float(ks_p),
        chi2_uniform=chi2,
        obs_mean=float(obs.mean()),
        ref_mean=float(ref.mean()),
        mean_bias=float(obs.mean() - ref.mean()),
    )


def stats_table(
    scenes: pd.DataFrame,
    references: dict[str, np.ndarray],
    groupby: list[str] | None = None,
    n_bins: int = 40,
) -> pd.DataFrame:
    """Compute aliasing stats across many (site, sensor, period) groups.

    Parameters
    ----------
    scenes
        Per-scene table with at least ``site_id``, ``sensor``, ``tide_m``
        columns (and any optional grouping columns such as ``subperiod``).
    references
        Mapping ``site_id -> reference tide series (ndarray, metres)``.
    groupby
        Columns to group by. Defaults to ``["site_id", "sensor"]``.
    """
    groupby = groupby or ["site_id", "sensor"]
    rows: list[dict] = []
    for keys, group in scenes.groupby(groupby):
        if not isinstance(keys, tuple):
            keys = (keys,)
        site_id = group["site_id"].iloc[0]
        ref = references.get(site_id)
        if ref is None or len(ref) == 0:
            continue
        st = compute_aliasing(group["tide_m"].to_numpy(), ref, n_bins=n_bins)
        row = {col: val for col, val in zip(groupby, keys)}
        row.update(st.as_dict())
        rows.append(row)
    return pd.DataFrame(rows)
