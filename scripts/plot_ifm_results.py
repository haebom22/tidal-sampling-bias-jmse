"""Plot IFM Phase-1 results: calibration curves and DEM-difference maps.

For each site this script produces:

  data/outputs/figures/{site}_ifm_calibration.png
      Frequency-elevation scatter + the three fitted models (SLM, Poly3, RF),
      with ICESat-2 calibration / hold-out split colour-coded.

  data/outputs/figures/{site}_ifm_vs_v3khoa_map.png
      IFM-RF DEM and the V3-KHOA waterline DEM side-by-side plus the
      pixel-wise difference (IFM − V3-KHOA), all in chart-datum metres.

A combined summary figure ``data/outputs/figures/ifm_phase1_summary.png``
shows the per-site RMSE comparison bar chart.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import LinearSegmentedColormap

from src.analysis.ifm import (  # noqa: E402
    DEFAULT_FREQ_RANGE,
    DEFAULT_RANDOM_STATE,
    DEFAULT_TEST_FRACTION,
    prepare_calibration_sample,
)
from src.config import resolve_path  # noqa: E402

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("plot_ifm")
log.setLevel(logging.INFO)

DEFAULT_SITES = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sites", nargs="*", default=DEFAULT_SITES)
    p.add_argument("--baseline-variant", default="v2",
                   help="waterline variant whose freq band was used as IFM input "
                        "(default: v2 = optical + S1)")
    p.add_argument("--waterline-baseline", default="v4",
                   help="waterline DEM variant to use as comparison baseline "
                        "in the side-by-side maps (default: v4)")
    p.add_argument("--suffix", default=None,
                   help="IFM file suffix (default: derived from --baseline-variant)")
    p.add_argument("--metrics-csv", default=None,
                   help="path to the metrics CSV (default: ifm_<bv>_vs_<wb>.csv)")
    p.add_argument("--figure-tag", default=None,
                   help="extra tag prepended to figure filenames "
                        "(default: derived from suffix)")
    return p.parse_args()


def _split(sample: pd.DataFrame, seed: int = DEFAULT_RANDOM_STATE,
           test_fraction: float = DEFAULT_TEST_FRACTION):
    rng = np.random.default_rng(seed)
    idx = np.arange(len(sample))
    rng.shuffle(idx)
    n_test = int(round(len(sample) * test_fraction))
    return idx[n_test:], idx[:n_test]


def plot_calibration(
    site_id: str,
    sample: pd.DataFrame,
    summary: dict,
    out_path: Path,
    input_label: str = "V1",
) -> None:
    train_idx, test_idx = _split(sample)
    train = sample.iloc[train_idx]
    test = sample.iloc[test_idx]

    fig, ax = plt.subplots(figsize=(7.5, 5.5), dpi=150)
    ax.scatter(train["freq"], train["h_chart"], s=2, alpha=0.18,
               color="#4c72b0", label=f"train  (n={len(train)})", rasterized=True)
    ax.scatter(test["freq"], test["h_chart"], s=2, alpha=0.45,
               color="#c44e52", label=f"hold-out  (n={len(test)})", rasterized=True)

    f_grid = np.linspace(*DEFAULT_FREQ_RANGE, 200)

    # SLM
    slm = summary["models"]["slm"]["coefficients"]
    a, b = slm
    ax.plot(f_grid, a + b * f_grid, color="#dd8452", lw=1.8,
            label=f"SLM    (RMSE={summary['models']['slm']['test_rmse_m']:.3f} m)")

    # Poly3
    p3 = summary["models"]["poly3"]["coefficients"]
    c0, c1, c2, c3 = p3
    ax.plot(f_grid, c0 + c1 * f_grid + c2 * f_grid**2 + c3 * f_grid**3,
            color="#55a868", lw=1.8,
            label=f"Poly3  (RMSE={summary['models']['poly3']['test_rmse_m']:.3f} m)")

    # RF: re-fit quickly to draw the curve
    from sklearn.ensemble import RandomForestRegressor
    X_tr = train["freq"].to_numpy().reshape(-1, 1)
    y_tr = train["h_chart"].to_numpy()
    rf = RandomForestRegressor(
        n_estimators=200, min_samples_leaf=10, n_jobs=-1, random_state=DEFAULT_RANDOM_STATE,
    )
    rf.fit(X_tr, y_tr)
    rf_curve = rf.predict(f_grid.reshape(-1, 1))
    ax.plot(f_grid, rf_curve, color="#8172b3", lw=1.8,
            label=f"RF     (RMSE={summary['models']['rf']['test_rmse_m']:.3f} m)")

    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("Inundation frequency  $f$")
    ax.set_ylabel("Elevation, chart datum  (m)")
    ax.set_title(
        f"{site_id.capitalize()} — IFM calibration "
        f"(input={input_label}, ATL06-SR, n={len(sample)})"
    )
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, framealpha=0.92)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    log.info("  wrote %s", out_path)


def plot_dem_compare(
    site_id: str,
    ifm_tif: Path,
    waterline_tif: Path,
    out_path: Path,
    waterline_label: str = "V3-KHOA",
    ifm_label: str = "IFM-RF",
) -> None:
    from rasterio.warp import Resampling, reproject

    with rasterio.open(ifm_tif) as src:
        ifm = src.read(1, masked=True)
        ref_transform = src.transform
        ref_crs = src.crs
        ref_shape = src.shape
        ref_nodata = src.nodata
    with rasterio.open(waterline_tif) as src:
        if src.shape == ref_shape and src.crs == ref_crs and src.transform == ref_transform:
            wl = src.read(1, masked=True)
        else:
            dst = np.full(ref_shape, np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=dst,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata,
                dst_nodata=np.nan,
            )
            wl = np.ma.masked_invalid(dst)

    common = ifm.mask | wl.mask
    a = np.ma.array(ifm, mask=common)
    b = np.ma.array(wl, mask=common)
    diff = a - b

    finite_all = np.concatenate([
        np.asarray(a.compressed()), np.asarray(b.compressed()),
    ])
    vmin = float(np.nanpercentile(finite_all, 2))
    vmax = float(np.nanpercentile(finite_all, 98))

    dmax = float(np.nanpercentile(np.abs(np.asarray(diff.compressed())), 98))
    if dmax == 0:
        dmax = 1.0

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=150,
                             constrained_layout=True)
    cmap = LinearSegmentedColormap.from_list(
        "intertidal", ["#08306b", "#41b6c4", "#ffffbf", "#fdae61", "#a50026"],
    )
    im0 = axes[0].imshow(a, cmap=cmap, vmin=vmin, vmax=vmax)
    im1 = axes[1].imshow(b, cmap=cmap, vmin=vmin, vmax=vmax)
    im2 = axes[2].imshow(diff, cmap="RdBu_r", vmin=-dmax, vmax=dmax)

    axes[0].set_title(f"{site_id.capitalize()} — {ifm_label} DEM")
    axes[1].set_title(f"Manuscript-2 {waterline_label} waterline DEM")
    axes[2].set_title(f"Difference  ({ifm_label} − {waterline_label})")
    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])

    fig.colorbar(im0, ax=axes[0], label="elev (m, chart)", shrink=0.85)
    fig.colorbar(im1, ax=axes[1], label="elev (m, chart)", shrink=0.85)
    fig.colorbar(im2, ax=axes[2], label="Δ elev (m)", shrink=0.85)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    log.info("  wrote %s", out_path)


def plot_summary(
    metrics_csv: Path,
    out_path: Path,
    baseline_label: str = "V3-KHOA",
    input_label: str = "V1",
) -> None:
    df = pd.read_csv(metrics_csv)
    sites = df["site_id"].unique()
    models = ["slm", "poly3", "rf"]

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    width = 0.18
    x = np.arange(len(sites))

    base_col = "baseline_rmse_m" if "baseline_rmse_m" in df.columns else f"{baseline_label.lower()}_rmse_m"
    delta_col = "ifm_vs_baseline_pct" if "ifm_vs_baseline_pct" in df.columns else f"ifm_vs_{baseline_label.lower()}_pct"
    base_series = df.drop_duplicates("site_id").set_index("site_id")[base_col]
    ax.bar(x - 2.0 * width, base_series.reindex(sites), width=width,
           color="#bdbdbd", edgecolor="black",
           label=f"{baseline_label} waterline (manuscript-2)")

    palette = ["#dd8452", "#55a868", "#8172b3"]
    for i, m in enumerate(models):
        vals = df[df["model"] == m].set_index("site_id")["test_rmse_m"].reindex(sites)
        ax.bar(x + (i - 0.5) * width, vals, width=width,
               color=palette[i], edgecolor="black", label=f"IFM-{m.upper()}")

    ax.set_xticks(x)
    ax.set_xticklabels([s.capitalize() for s in sites])
    ax.set_ylabel("Held-out ICESat-2 RMSE  (m)")
    ax.set_title(
        f"IFM (input={input_label}) vs manuscript-2 {baseline_label} waterline "
        f"— 5 Korean macrotidal sites"
    )
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)

    for i, site in enumerate(sites):
        rf_row = df[(df["site_id"] == site) & (df["model"] == "rf")].iloc[0]
        delta = rf_row[delta_col]
        ax.annotate(
            f"−{delta:.0f}%", xy=(i + 0.5 * width, rf_row["test_rmse_m"]),
            xytext=(0, 6), textcoords="offset points",
            ha="center", fontsize=8, color="#8172b3",
        )

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    log.info("  wrote %s", out_path)


def plot_coverage_gain(
    sites: list[str],
    dem_dir: Path,
    out_path: Path,
    freq_range: tuple[float, float] = DEFAULT_FREQ_RANGE,
) -> None:
    """For each site bar-plot the IFM-applicable pixel count, V1 vs V2."""
    rows = []
    for s in sites:
        for v in ("v1", "v2"):
            p = dem_dir / f"{s}_{v}.tif"
            if not p.exists():
                continue
            with rasterio.open(p) as src:
                freq = src.read(5, masked=True).filled(np.nan)
            valid = np.isfinite(freq)
            intertidal = valid & (freq >= freq_range[0]) & (freq <= freq_range[1])
            upper = valid & (freq >= 0.50) & (freq <= freq_range[1])
            rows.append({
                "site": s, "variant": v,
                "intertidal_px": int(intertidal.sum()),
                "upper_px": int(upper.sum()),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), dpi=150,
                             sharey=False, constrained_layout=True)
    x = np.arange(len(sites))
    width = 0.36

    for ax, col, title in (
        (axes[0], "intertidal_px", "Intertidal pixels (freq ∈ [0.03, 0.97])"),
        (axes[1], "upper_px",      "Upper intertidal pixels (freq ∈ [0.50, 0.97])"),
    ):
        v1 = df[df["variant"] == "v1"].set_index("site")[col].reindex(sites)
        v2 = df[df["variant"] == "v2"].set_index("site")[col].reindex(sites)
        ax.bar(x - 0.5 * width, v1 / 1000.0, width=width,
               color="#bdbdbd", edgecolor="black",
               label="V1  (L8 + L9 + S2)")
        ax.bar(x + 0.5 * width, v2 / 1000.0, width=width,
               color="#4c72b0", edgecolor="black",
               label="V2  (L8 + L9 + S2 + S1)")
        for i, s in enumerate(sites):
            v1_val = v1.loc[s]
            v2_val = v2.loc[s]
            if v1_val and v2_val:
                pct = 100.0 * (v2_val - v1_val) / v1_val
                ax.annotate(f"+{pct:.0f}%",
                            xy=(i + 0.5 * width, v2_val / 1000.0),
                            xytext=(0, 4), textcoords="offset points",
                            ha="center", fontsize=8, color="#4c72b0")
        ax.set_xticks(x)
        ax.set_xticklabels([s.capitalize() for s in sites])
        ax.set_ylabel("Pixel count  (thousands, 30 m)")
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(fontsize=9, framealpha=0.95)

    fig.suptitle("Adding Sentinel-1 SAR to the optical stack — IFM coverage gain",
                 fontsize=11, y=1.04)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    log.info("  wrote %s", out_path)


def plot_v1_v2_dem_compare(
    site_id: str,
    ifm_v1_tif: Path,
    ifm_v2_tif: Path,
    out_path: Path,
) -> None:
    """Side-by-side maps: IFM-RF using V1 freq vs V2 freq input, plus difference."""
    from rasterio.warp import Resampling, reproject

    with rasterio.open(ifm_v2_tif) as src:
        v2 = src.read(1, masked=True)
        ref_transform = src.transform
        ref_crs = src.crs
        ref_shape = src.shape
    with rasterio.open(ifm_v1_tif) as src:
        if src.shape == ref_shape and src.crs == ref_crs and src.transform == ref_transform:
            v1 = src.read(1, masked=True)
        else:
            dst = np.full(ref_shape, np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1), destination=dst,
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=ref_transform, dst_crs=ref_crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata, dst_nodata=np.nan,
            )
            v1 = np.ma.masked_invalid(dst)

    a = v1
    b = v2
    finite_all = np.concatenate([
        np.asarray(a.compressed()), np.asarray(b.compressed()),
    ])
    if finite_all.size == 0:
        return
    vmin = float(np.nanpercentile(finite_all, 2))
    vmax = float(np.nanpercentile(finite_all, 98))

    common = a.mask | b.mask
    only_v2 = a.mask & ~b.mask   # pixels gained by adding S1
    gain_overlay = np.zeros(b.shape, dtype=bool)
    gain_overlay[only_v2] = True

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=150,
                             constrained_layout=True)
    cmap = LinearSegmentedColormap.from_list(
        "intertidal", ["#08306b", "#41b6c4", "#ffffbf", "#fdae61", "#a50026"],
    )
    im0 = axes[0].imshow(a, cmap=cmap, vmin=vmin, vmax=vmax)
    im1 = axes[1].imshow(b, cmap=cmap, vmin=vmin, vmax=vmax)
    overlay = np.ma.array(b, mask=~gain_overlay)
    im2 = axes[2].imshow(b, cmap=cmap, vmin=vmin, vmax=vmax, alpha=0.35)
    axes[2].imshow(overlay, cmap="autumn", vmin=vmin, vmax=vmax)

    axes[0].set_title(f"{site_id.capitalize()} — IFM-RF (V1 freq, optical only)")
    axes[1].set_title("IFM-RF (V2 freq, + Sentinel-1)")
    axes[2].set_title("Pixels added by S1 (warm overlay)")
    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])

    fig.colorbar(im0, ax=axes[0], label="elev (m, chart)", shrink=0.85)
    fig.colorbar(im1, ax=axes[1], label="elev (m, chart)", shrink=0.85)

    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    log.info("  wrote %s", out_path)


def main() -> None:
    args = parse_args()
    dem_dir = resolve_path("data/outputs/dem")
    proc_dir = resolve_path("data/processed")
    fig_dir = resolve_path("data/outputs/figures")
    fig_dir.mkdir(parents=True, exist_ok=True)

    bv = args.baseline_variant
    wb = args.waterline_baseline
    if args.suffix is not None:
        suffix = args.suffix
    elif bv == "v1":
        suffix = "ifm"
    elif bv == "v2":
        suffix = "ifm_s1"
    else:
        suffix = f"ifm_{bv}"

    fig_tag = args.figure_tag or (suffix if suffix != "ifm" else "ifm")

    for site_id in args.sites:
        wl_freq_tif = dem_dir / f"{site_id}_{bv}.tif"
        ic = proc_dir / f"{site_id}_icesat2_exposed.parquet"
        summary_path = dem_dir / f"{site_id}_{suffix}_summary.json"
        if not summary_path.exists():
            log.warning("missing IFM summary for %s (%s) — run run_ifm_dem.py first",
                        site_id, summary_path.name)
            continue
        with open(summary_path) as f:
            summary = json.load(f)

        sample, _ = prepare_calibration_sample(wl_freq_tif, ic)
        plot_calibration(site_id, sample, summary,
                         fig_dir / f"{site_id}_{fig_tag}_calibration.png",
                         input_label=bv.upper())

        rf_tif = dem_dir / f"{site_id}_{suffix}_rf.tif"
        baseline_tif = dem_dir / f"{site_id}_{wb}.tif"
        if rf_tif.exists() and baseline_tif.exists():
            plot_dem_compare(
                site_id, rf_tif, baseline_tif,
                fig_dir / f"{site_id}_{fig_tag}_vs_{wb}_map.png",
                waterline_label=wb.upper(),
            )

        # If we are on the V2 run, also produce the V1↔V2 IFM gain map.
        if bv == "v2":
            v1_rf = dem_dir / f"{site_id}_ifm_rf.tif"
            if rf_tif.exists() and v1_rf.exists():
                plot_v1_v2_dem_compare(
                    site_id, v1_rf, rf_tif,
                    fig_dir / f"{site_id}_ifm_v1_v2_gain_map.png",
                )

    metrics_csv = (
        Path(args.metrics_csv) if args.metrics_csv else
        resolve_path(f"data/outputs/tables/ifm_{bv}_vs_{wb}.csv")
    )
    if not metrics_csv.exists():
        # Fall back to the Phase-1 default name.
        metrics_csv = resolve_path("data/outputs/tables/ifm_vs_waterline.csv")
    if metrics_csv.exists():
        plot_summary(
            metrics_csv, fig_dir / f"{fig_tag}_summary.png",
            baseline_label=wb.upper(), input_label=bv.upper(),
        )

    if bv == "v2":
        plot_coverage_gain(args.sites, dem_dir,
                           fig_dir / "ifm_s1_coverage_gain.png")


if __name__ == "__main__":
    main()
