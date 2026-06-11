"""Publication-style plots for tidal-aliasing analysis."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SENSOR_COLORS = {
    "L5": "#3b8da6",
    "L7": "#5db8a6",
    "L8": "#e6a042",
    "L9": "#d65f5f",
    "S2": "#7a52a3",
}


def plot_tide_distribution(
    scenes: pd.DataFrame,
    reference: np.ndarray,
    site_name: str,
    out_path: Path | None = None,
    bins: int = 40,
) -> plt.Figure:
    """Histogram of observed tide samples vs reference envelope, per sensor."""
    fig, ax = plt.subplots(figsize=(8, 5))

    ref_min, ref_max = float(np.nanquantile(reference, 0.001)), float(
        np.nanquantile(reference, 0.999)
    )
    edges = np.linspace(ref_min, ref_max, bins + 1)
    ref_hist, _ = np.histogram(reference, bins=edges, density=True)
    ax.step(
        edges[:-1],
        ref_hist,
        where="post",
        color="black",
        linewidth=1.5,
        label="Reference (FES2014 dense)",
    )

    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]["tide_m"].dropna()
        if sub.empty:
            continue
        ax.hist(
            sub,
            bins=edges,
            density=True,
            histtype="step",
            linewidth=1.4,
            color=SENSOR_COLORS.get(sensor, "gray"),
            label=f"{sensor} (n={len(sub)})",
        )

    ax.set_xlabel("Tide height (m)")
    ax.set_ylabel("Density")
    ax.set_title(f"Tidal sampling distribution – {site_name}")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200)
    return fig


def plot_spread_offset(
    stats_df: pd.DataFrame,
    out_path: Path | None = None,
) -> plt.Figure:
    """Bar plot of spread + offset stacked, per sensor across sites."""
    sites = sorted(stats_df["site_id"].unique())
    sensors = sorted(stats_df["sensor"].unique())
    n_sites = len(sites)
    width = 0.8 / max(1, len(sensors))

    fig, ax = plt.subplots(figsize=(1.2 * n_sites + 4, 5))
    for i, sensor in enumerate(sensors):
        sub = stats_df[stats_df["sensor"] == sensor].set_index("site_id").reindex(sites)
        x = np.arange(n_sites) + i * width
        spread = sub["spread"].fillna(0).to_numpy()
        low = sub["low_offset"].fillna(0).to_numpy()
        high = sub["high_offset"].fillna(0).to_numpy()
        ax.bar(x, spread, width, color=SENSOR_COLORS.get(sensor, "gray"), label=f"{sensor} spread")
        ax.bar(x, low, width, bottom=spread, color=SENSOR_COLORS.get(sensor, "gray"), alpha=0.4, hatch="///", label=f"{sensor} low-offset" if i == 0 else None)
        ax.bar(x, high, width, bottom=spread + low, color=SENSOR_COLORS.get(sensor, "gray"), alpha=0.2, hatch="\\\\\\", label=f"{sensor} high-offset" if i == 0 else None)

    ax.set_xticks(np.arange(n_sites) + (len(sensors) - 1) * width / 2)
    ax.set_xticklabels(sites, rotation=20, ha="right")
    ax.set_ylabel("Fraction of reference tide range")
    ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.set_title("Tidal aliasing: spread + offsets per sensor")
    ax.legend(loc="upper right", fontsize=8, ncols=2)
    fig.tight_layout()
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200)
    return fig


def plot_temporal_evolution(
    scenes: pd.DataFrame,
    site_name: str,
    out_path: Path | None = None,
) -> plt.Figure:
    """Scatter of observed tide vs acquisition year, coloured by sensor."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for sensor in sorted(scenes["sensor"].unique()):
        sub = scenes[scenes["sensor"] == sensor]
        ax.scatter(
            sub["datetime_utc"],
            sub["tide_m"],
            s=8,
            alpha=0.6,
            color=SENSOR_COLORS.get(sensor, "gray"),
            label=f"{sensor} (n={len(sub)})",
        )
    ax.set_xlabel("Acquisition date")
    ax.set_ylabel("Tide height (m)")
    ax.set_title(f"Observed tide heights over time – {site_name}")
    ax.legend(frameon=False, ncols=3, fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200)
    return fig
