"""Phase-7 plotting: 8-panel DEM composite, RMSE bar, residual histogram.

Outputs
-------
- ``data/outputs/figures/dem_pilot_composite.png`` — 2 sites × 4 variants
- ``data/outputs/figures/dem_pilot_rmse.png``      — RMSE bar with predicted bias
- ``data/outputs/figures/dem_pilot_residuals.png`` — per-variant residual hist
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.config import load_settings, load_sites, resolve_path
from src.gee.dem import BETA_DEFAULT, SITE_AMPLITUDE_M

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("dem_figures")

VARIANTS = ("v1", "v2", "v3", "v4")
VARIANT_LABELS = {
    "v1": "L8+L9+S2",
    "v2": "L8+L9+S2+S1",
    "v3": "L8+L9+S2 (+bias)",
    "v4": "L8+L9+S2+S1 (+bias)",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sites", nargs="*", default=["garorim", "suncheon"])
    p.add_argument("--variants", nargs="*", default=list(VARIANTS), choices=list(VARIANTS))
    p.add_argument(
        "--validation-csv",
        type=str,
        default=None,
        help="Path to dem_validation.csv (default: data/outputs/tables/dem_validation.csv)",
    )
    return p.parse_args()


def _plot_dem_composite(
    sites: list[str],
    variants: list[str],
    dem_dir: Path,
    sites_meta: dict,
    out_path: Path,
) -> None:
    import rasterio

    fig, axes = plt.subplots(
        nrows=len(sites),
        ncols=len(variants),
        figsize=(3.8 * len(variants), 4.0 * len(sites)),
        squeeze=False,
    )
    for r, site_id in enumerate(sites):
        site = sites_meta[site_id]
        # Symmetric color limits per site (so V1..V4 share a scale).
        all_data = []
        for variant in variants:
            p = dem_dir / f"{site_id}_{variant}.tif"
            if not p.exists():
                continue
            with rasterio.open(p) as src:
                a = src.read(1, masked=True)
            all_data.append(np.asarray(a.compressed()))
        if all_data:
            combined = np.concatenate(all_data)
            lo = float(np.nanpercentile(combined, 2))
            hi = float(np.nanpercentile(combined, 98))
        else:
            lo, hi = -2.0, 6.0

        for c, variant in enumerate(variants):
            ax = axes[r, c]
            p = dem_dir / f"{site_id}_{variant}.tif"
            if not p.exists():
                ax.text(0.5, 0.5, "missing", transform=ax.transAxes, ha="center")
                ax.set_axis_off()
                continue
            with rasterio.open(p) as src:
                dem = src.read(1, masked=True)
                left, bottom = src.bounds.left, src.bounds.bottom
                right, top = src.bounds.right, src.bounds.top
            im = ax.imshow(
                dem,
                origin="upper",
                extent=(left, right, bottom, top),
                cmap="terrain",
                vmin=lo,
                vmax=hi,
                interpolation="nearest",
            )
            ax.set_title(f"{site.name_en} — {variant.upper()} ({VARIANT_LABELS[variant]})", fontsize=10)
            ax.set_xlabel("Easting (m, UTM 52N)")
            ax.set_ylabel("Northing (m)")
            ax.ticklabel_format(style="plain", useOffset=False)
            cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cbar.set_label("Elevation (m, KHOA datum)", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    log.info("Wrote DEM composite → %s", out_path)


def _plot_rmse_bar(
    validation: pd.DataFrame,
    variants: list[str],
    out_path: Path,
) -> None:
    sites = list(dict.fromkeys(validation["site_id"]))
    x = np.arange(len(sites))
    width = 0.8 / max(len(variants), 1)

    fig, ax = plt.subplots(figsize=(6.0 + 1.0 * len(sites), 5.0))
    for i, variant in enumerate(variants):
        sub = validation[validation["variant"] == variant].set_index("site_id")
        rmses = [float(sub.loc[s, "rmse_m"]) if s in sub.index else np.nan for s in sites]
        ax.bar(x + i * width, rmses, width=width, label=f"{variant.upper()}: {VARIANT_LABELS[variant]}")
        # Annotate values
        for j, val in enumerate(rmses):
            if np.isfinite(val):
                ax.text(x[j] + i * width, val + 0.02, f"{val:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x + 0.4 - width / 2)
    ax.set_xticklabels(sites)
    ax.set_ylabel("DEM vs GLO-30 RMSE (m)")
    ax.set_title("Pilot DEM validation against Copernicus GLO-30 (TanDEM-X derived)")
    ax.legend(loc="best", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    log.info("Wrote RMSE bar → %s", out_path)


def _plot_predicted_vs_observed(
    validation: pd.DataFrame,
    out_path: Path,
) -> None:
    sub = validation.dropna(subset=["predicted_bias_m"]).copy()
    if sub.empty:
        log.info("No predicted_bias_m column — skipping pred-vs-obs plot")
        return
    fig, ax = plt.subplots(figsize=(6.0, 6.0))
    markers = {"v1": "o", "v2": "s", "v3": "^", "v4": "D"}
    for variant, df_v in sub.groupby("variant"):
        ax.scatter(
            df_v["predicted_bias_m"], df_v["mean_bias_m"],
            label=f"{variant.upper()} ({VARIANT_LABELS.get(variant, variant)})",
            s=80, marker=markers.get(variant, "o"),
        )
        for _, row in df_v.iterrows():
            ax.annotate(
                row["site_id"],
                (row["predicted_bias_m"], row["mean_bias_m"]),
                textcoords="offset points", xytext=(6, 4), fontsize=9,
            )
    lo = float(np.nanmin([sub["predicted_bias_m"].min(), sub["mean_bias_m"].min(), -1.5]))
    hi = float(np.nanmax([sub["predicted_bias_m"].max(), sub["mean_bias_m"].max(), +1.0]))
    ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.8, label="1:1")
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.axvline(0, color="grey", linewidth=0.5)
    ax.set_xlabel(r"Predicted bias: $\beta \cdot A \cdot \langle \cos\theta\rangle$ (m)")
    ax.set_ylabel("Observed mean DEM bias (m, our − GLO-30)")
    ax.set_title(rf"Manuscript Eq. (1) prediction vs. GLO-30 residual ($\beta$ = {BETA_DEFAULT})")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    log.info("Wrote predicted-vs-observed → %s", out_path)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites_meta = {s.id: s for s in load_sites()}

    dem_dir = resolve_path("data/outputs/dem")
    figs_dir = resolve_path(settings["paths"]["figures"])
    tables_dir = resolve_path(settings["paths"]["tables"])
    figs_dir.mkdir(parents=True, exist_ok=True)

    _plot_dem_composite(
        sites=args.sites,
        variants=args.variants,
        dem_dir=dem_dir,
        sites_meta=sites_meta,
        out_path=figs_dir / "dem_pilot_composite.png",
    )

    val_path = Path(args.validation_csv) if args.validation_csv else tables_dir / "dem_validation.csv"
    if val_path.exists():
        validation = pd.read_csv(val_path)
        _plot_rmse_bar(
            validation,
            variants=args.variants,
            out_path=figs_dir / "dem_pilot_rmse.png",
        )
        _plot_predicted_vs_observed(
            validation,
            out_path=figs_dir / "dem_pilot_pred_vs_obs.png",
        )
    else:
        log.warning(
            "No validation table at %s; run scripts/run_dem_validation.py first",
            val_path,
        )


if __name__ == "__main__":
    main()
