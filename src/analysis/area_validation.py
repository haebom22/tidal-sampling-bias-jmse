"""5-site cross-validation: this study vs Murray / GWL_FCS30 / GTF30 / MOF.

Phase 3 of the methodology plan. Reads:

  - data/outputs/tables/annual_area_5sites.csv           (this study)
  - data/outputs/tables/annual_area_5sites_corrected.csv (Phase 2 corrected)
  - data/processed/reference_extents.parquet             (Phase 0 references)

For each (site, year) it computes the area difference vs each reference
source and decomposes the difference into four physical components,
adopting the manuscript-2 framework:

  Δ_phase      = (V4 − V1)               (phase bias removed by SAR + β·A·cosθ)
  Δ_aqua       = (Murray − GWL_FCS30)    (aquaculture overcommission in Murray)
  Δ_resolution = (10m − 30m resampling)  (sub-pixel intertidal margins)
  Δ_period     = (annual − multi-year)   (33yr mean Murray vs 1-3yr current)

The script writes:

  - data/outputs/tables/reference_comparison_5sites.csv
  - data/outputs/tables/area_uncertainty_budget.csv
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Approximate Murray v1.2 epoch mid-years (3-year overlapping windows).
MURRAY_EPOCH_MIDPOINT = {
    "1999-2001": 2000, "2002-2004": 2003, "2005-2007": 2006,
    "2008-2010": 2009, "2011-2013": 2012, "2014-2016": 2015,
    "2017-2019": 2018,
}


@dataclass
class DiffStats:
    mean_diff_km2: float
    rmse_km2: float
    mae_km2: float
    bias_pct: float
    pearson_r: float
    n_pairs: int


def _pair_stats(this: np.ndarray, ref: np.ndarray) -> DiffStats:
    a = np.asarray(this, dtype=float)
    b = np.asarray(ref, dtype=float)
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    if a.size < 2:
        return DiffStats(np.nan, np.nan, np.nan, np.nan, np.nan, int(a.size))
    diff = a - b
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    mae = float(np.mean(np.abs(diff)))
    r = float(np.corrcoef(a, b)[0, 1]) if a.size > 2 else np.nan
    bias_pct = float(np.mean(diff) / np.mean(b) * 100.0) if np.mean(b) != 0 else np.nan
    return DiffStats(
        mean_diff_km2=float(np.mean(diff)),
        rmse_km2=rmse,
        mae_km2=mae,
        bias_pct=bias_pct,
        pearson_r=r,
        n_pairs=int(a.size),
    )


def build_comparison_table(
    this_study: pd.DataFrame,
    references: pd.DataFrame,
    *,
    area_col_this: str = "total_km2",
) -> pd.DataFrame:
    """Outer-merge this study with each reference dataset on (site_id, year).

    The references parquet's ``source`` column distinguishes the four
    products.  For Murray, year is the epoch midpoint.
    """
    rows = []
    for site_id in this_study["site_id"].unique():
        this_site = this_study[this_study["site_id"] == site_id]
        ref_site = references[references["site_id"] == site_id]
        for source in ref_site["source"].unique():
            src_rows = ref_site[ref_site["source"] == source]
            merged = this_site.merge(
                src_rows[["year", "area_km2"]].rename(
                    columns={"area_km2": "area_ref_km2"}
                ),
                on="year",
                how="inner",
            )
            if merged.empty:
                # Try a tolerant join: nearest reference year within ±2 years.
                merged = _tolerant_join(this_site, src_rows, tol_years=2)
                if merged.empty:
                    continue
            for _, r in merged.iterrows():
                rows.append({
                    "site_id": site_id,
                    "year": int(r["year"]),
                    "source": source,
                    "area_this_km2": r[area_col_this],
                    "area_ref_km2": r["area_ref_km2"],
                    "diff_km2": r[area_col_this] - r["area_ref_km2"],
                    "diff_pct": (
                        (r[area_col_this] - r["area_ref_km2"])
                        / r["area_ref_km2"] * 100.0
                        if r["area_ref_km2"] not in (0, None) and np.isfinite(r["area_ref_km2"])
                        else np.nan
                    ),
                })
    return pd.DataFrame(rows)


def _tolerant_join(this_site: pd.DataFrame, ref_site: pd.DataFrame, tol_years: int = 2) -> pd.DataFrame:
    """Match each row in ``this_site`` to the nearest ref-year row within ``tol_years``."""
    if ref_site.empty or this_site.empty:
        return pd.DataFrame()
    rows = []
    for _, t in this_site.iterrows():
        ref_site2 = ref_site.copy()
        ref_site2["dt"] = (ref_site2["year"] - t["year"]).abs()
        ref_site2 = ref_site2[ref_site2["dt"] <= tol_years]
        if ref_site2.empty:
            continue
        nearest = ref_site2.sort_values("dt").iloc[0]
        rows.append({
            **t.to_dict(),
            "area_ref_km2": nearest["area_km2"],
        })
    return pd.DataFrame(rows)


def summarise_by_source(comparison: pd.DataFrame, area_col_this: str = "area_this_km2") -> pd.DataFrame:
    """Aggregate diff statistics per (site, source)."""
    rows = []
    for (site_id, source), grp in comparison.groupby(["site_id", "source"]):
        stats = _pair_stats(grp[area_col_this].to_numpy(), grp["area_ref_km2"].to_numpy())
        rows.append({
            "site_id": site_id,
            "source": source,
            "n_pairs": stats.n_pairs,
            "mean_diff_km2": stats.mean_diff_km2,
            "rmse_km2": stats.rmse_km2,
            "mae_km2": stats.mae_km2,
            "bias_pct": stats.bias_pct,
            "pearson_r": stats.pearson_r,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Error decomposition (4 components, from manuscript-2)
# ---------------------------------------------------------------------------

def decompose_error(
    this_study: pd.DataFrame,
    references: pd.DataFrame,
    *,
    area_col_this: str = "total_km2",
    area_col_v1: str | None = "area_v1_km2",
) -> pd.DataFrame:
    """Per-site decomposition of (this − Murray) into the 4 physical components.

    Δ_total = (this − Murray)
    Δ_phase = mean(area_this) − mean(area_v1)   if V1 area available
            else 0 (only V4 is present)
    Δ_aqua  = mean(area_Murray − area_GWL_FCS30)
    Δ_res   = 0.05 · mean(area_Murray)          (heuristic; 5% sub-pixel margin)
    Δ_period = mean(this) − mean(area_Murray @ this years)

    Component magnitudes are signed (+ = this study larger).
    """
    rows = []
    for site_id in this_study["site_id"].unique():
        this_site = this_study[this_study["site_id"] == site_id]
        if this_site.empty:
            continue
        ref_site = references[references["site_id"] == site_id]

        a_this = this_site[area_col_this].mean()

        murray = ref_site[ref_site["source"] == "murray_v1_2"]
        gwl = ref_site[ref_site["source"] == "gwl_fcs30"]

        a_murray = murray["area_km2"].mean() if not murray.empty else np.nan
        a_gwl = gwl["area_km2"].mean() if not gwl.empty else np.nan

        # Δ_phase needs V1 area in the same table.
        delta_phase = (
            a_this - this_site[area_col_v1].mean()
            if area_col_v1 and area_col_v1 in this_site.columns
            and this_site[area_col_v1].notna().any()
            else np.nan
        )

        delta_aqua = a_murray - a_gwl if np.isfinite(a_murray) and np.isfinite(a_gwl) else np.nan
        delta_res = 0.05 * a_murray if np.isfinite(a_murray) else np.nan

        if np.isfinite(a_this) and np.isfinite(a_murray):
            # Δ_period = compare same-year subsets where possible.
            recent = murray[murray["year"] >= this_site["year"].min()]
            delta_period = (
                a_this - recent["area_km2"].mean()
                if not recent.empty else a_this - a_murray
            )
        else:
            delta_period = np.nan

        rows.append({
            "site_id": site_id,
            "this_study_mean_km2": a_this,
            "murray_mean_km2": a_murray,
            "gwl_fcs30_mean_km2": a_gwl,
            "delta_total_km2": a_this - a_murray if np.isfinite(a_murray) else np.nan,
            "delta_phase_km2": delta_phase,
            "delta_aqua_km2": delta_aqua,
            "delta_resolution_km2": delta_res,
            "delta_period_km2": delta_period,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

# Reference display order, labels, and colours.
_SOURCE_LABEL = {
    "mof": "MOF 2023",
    "murray_v1_1": "Murray v1.1",
    "murray_v1_2": "Murray v1.2",
    "gtf30": "GTF30",
    "gwl_fcs30": "GWL_FCS30",
}
_SOURCE_ORDER = ["mof", "murray_v1_1", "murray_v1_2", "gtf30", "gwl_fcs30"]
_SOURCE_COLOR = {
    "mof": "#33a02c",
    "murray_v1_1": "#1f78b4",
    "murray_v1_2": "#1f78b4",
    "gtf30": "#ff7f00",
    "gwl_fcs30": "#6a3d9a",
}

# Pairs that are not interpretable and are excluded from the pooled statistics
# (the Ganghwa MOF bounding-box clip captures <2 % of the survey polygons; see
# manuscript §3.3).
_EXCLUDE_PAIRS = {("ganghwa", "mof")}


def plot_scatter_and_bland_altman(
    comparison: pd.DataFrame,
    out_path: Path,
    *,
    area_col_this: str = "area_this_km2",
) -> Path:
    """Two-panel reference comparison figure.

    (a) Grouped bars per site: this-study estimate alongside each independent
        benchmark, so the site-dependent magnitude and the consistent
        this-study $\\ge$ field-survey $>$ Murray ordering are read at a glance.
    (b) Pooled Bland-Altman across *all* interpretable site/reference pairs
        (coloured by reference), with the mean bias and 95 % limits of
        agreement — the statistically valid view that the per-pair panels
        cannot give. The non-interpretable Ganghwa MOF-clip pair is excluded.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    sites = sorted(comparison["site_id"].unique())
    present = [s for s in _SOURCE_ORDER if s in set(comparison["source"])]

    fig, (ax_bar, ax_ba) = plt.subplots(1, 2, figsize=(13.5, 5.4))

    # ---- (a) grouped bars per site --------------------------------------
    n_series = 1 + len(present)  # this study + references
    width = 0.8 / n_series
    x = np.arange(len(sites))
    # this study (mean of available years per site)
    this_mean = [comparison.loc[comparison["site_id"] == s, area_col_this].mean()
                 for s in sites]
    ax_bar.bar(x - 0.4 + 0.5 * width, this_mean, width=width,
               color="#e31a1c", label="This study", zorder=3)
    for k, src in enumerate(present, start=1):
        vals = []
        for s in sites:
            if (s, src) in _EXCLUDE_PAIRS:
                vals.append(np.nan)
                continue
            sub = comparison[(comparison["site_id"] == s) & (comparison["source"] == src)]
            vals.append(sub["area_ref_km2"].mean() if not sub.empty else np.nan)
        ax_bar.bar(x - 0.4 + (k + 0.5) * width, vals, width=width,
                   color=_SOURCE_COLOR.get(src, "#888"),
                   label=_SOURCE_LABEL.get(src, src), zorder=3)
    ax_bar.set_xticks(x)
    ax_bar.set_xticklabels([s.capitalize() for s in sites])
    ax_bar.set_ylabel("Tidal-flat area (km²)")
    ax_bar.set_title("(a) Area by site and source")
    ax_bar.grid(True, axis="y", alpha=0.3, zorder=0)
    ax_bar.legend(fontsize=8, ncol=2, loc="upper right")

    # ---- (b) pooled Bland-Altman ----------------------------------------
    pool = comparison[
        ~comparison.apply(
            lambda r: (r["site_id"], r["source"]) in _EXCLUDE_PAIRS, axis=1)
    ].copy()
    a = pool[area_col_this].to_numpy(dtype=float)
    b = pool["area_ref_km2"].to_numpy(dtype=float)
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    pool = pool[keep]
    diff = a - b
    mean = (a + b) / 2.0
    md = float(np.mean(diff))
    sd = float(np.std(diff, ddof=1)) if diff.size > 1 else 0.0
    for src in present:
        m = pool["source"].to_numpy() == src
        if not m.any():
            continue
        ax_ba.scatter(mean[m], diff[m], s=42, alpha=0.85,
                      color=_SOURCE_COLOR.get(src, "#888"),
                      edgecolor="k", linewidth=0.3,
                      label=_SOURCE_LABEL.get(src, src))
    ax_ba.axhline(0, color="k", lw=0.8)
    ax_ba.axhline(md, ls="-", color="#444", lw=1.2)
    ax_ba.axhline(md + 1.96 * sd, ls="--", color="gray", lw=1.0)
    ax_ba.axhline(md - 1.96 * sd, ls="--", color="gray", lw=1.0)
    xr = ax_ba.get_xlim()[1]
    ax_ba.text(xr, md, f"  mean +{md:.0f}", va="center", fontsize=8, color="#444")
    ax_ba.text(xr, md + 1.96 * sd, f"  +1.96 SD", va="center", fontsize=8, color="gray")
    ax_ba.text(xr, md - 1.96 * sd, f"  −1.96 SD", va="center", fontsize=8, color="gray")
    ax_ba.set_xlabel("mean of this study and reference (km²)")
    ax_ba.set_ylabel("this study − reference (km²)")
    ax_ba.set_title(f"(b) Pooled Bland–Altman (n={diff.size}; "
                    f"bias +{md:.1f} km², ±1.96 SD = {1.96*sd:.1f})")
    ax_ba.grid(True, alpha=0.3)
    ax_ba.legend(fontsize=8, loc="lower right")

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s (pooled n=%d, bias=%.2f, SD=%.2f)", out_path, diff.size, md, sd)
    return out_path


def plot_decomposition(decomp: pd.DataFrame, out_path: Path) -> Path:
    """Stacked-bar decomposition figure (one bar per site)."""
    import matplotlib.pyplot as plt

    if decomp.empty:
        log.warning("Empty decomposition table — skipping plot")
        return out_path

    components = [
        ("delta_phase_km2", "phase bias"),
        ("delta_aqua_km2", "aquaculture"),
        ("delta_resolution_km2", "resolution"),
        ("delta_period_km2", "period"),
    ]
    sites = decomp["site_id"].tolist()
    fig, ax = plt.subplots(figsize=(max(6.0, 1.5 * len(sites)), 4.0))
    x = np.arange(len(sites))
    width = 0.18
    for i, (col, label) in enumerate(components):
        if col not in decomp.columns:
            continue
        ax.bar(x + (i - 1.5) * width, decomp[col], width=width, label=label)
    ax.set_xticks(x)
    ax.set_xticklabels(sites)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("Δ area (km²)")
    ax.set_title("Decomposition of (this − Murray) tidal-flat area difference")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", out_path)
    return out_path


__all__ = [
    "DiffStats",
    "build_comparison_table",
    "summarise_by_source",
    "decompose_error",
    "plot_scatter_and_bland_altman",
    "plot_decomposition",
]
