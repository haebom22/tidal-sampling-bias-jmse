"""Validate all DEM variants against Copernicus GLO-30 (TanDEM-X derived).

For each (site, variant) it:
  1. Downloads (and caches) a GLO-30 raster covering the site bbox.
  2. Reprojects our 10 m DEM onto the 30 m GLO-30 grid (mean resampler).
  3. Applies a per-site KHOA→EGM2008 vertical-datum offset.
  4. Computes RMSE / MAE / mean bias on the intertidal subset
     (``0.05 ≤ inundation_frequency ≤ 0.95`` by default).
  5. Compares the observed mean bias to the manuscript prediction
     ``β · A · ⟨cos θ⟩`` derived from the diagnostics table.

Outputs
-------
- ``data/raw/glo30/<site>_glo30.tif``
- ``data/outputs/dem/<site>_<variant>_on_glo30.tif``
- ``data/outputs/tables/dem_validation.csv``
- ``data/outputs/tables/dem_validation_pred_vs_obs.csv``
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.validate_glo30 import (
    compare_to_glo30,
    fetch_glo30_for_bbox,
    reproject_to_glo30_grid,
    stats_to_dataframe,
)
from src.config import load_settings, load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.dem import BETA_DEFAULT, SITE_AMPLITUDE_M

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("dem_validation")

# Per-site KHOA datum (~ Lowest Astronomical Tide) → EGM2008 geoid offset.
# Approximate from KHOA mean sea level (MSL above LAT) and EGM2008 geoid
# heights at the gauge coordinates. Values in metres; positive offset
# means KHOA z + offset = EGM2008 z. These are *first-order* defaults;
# the user can override at the CLI.
KHOA_TO_EGM2008_M: dict[str, float] = {
    "garorim": 3.20,
    "suncheon": 1.80,
    "ganghwa": 4.30,
    "gomso": 3.50,
    "hampyeong": 2.40,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sites", nargs="*", default=["garorim", "suncheon"],
        help="Site IDs to validate",
    )
    p.add_argument(
        "--variants", nargs="*", default=["v1", "v2", "v3", "v4"],
        choices=["v1", "v2", "v3", "v4"],
    )
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument(
        "--inundation-min", type=float, default=0.05,
        help="Min inundation frequency to keep a pixel in the comparison",
    )
    p.add_argument(
        "--inundation-max", type=float, default=0.95,
        help="Max inundation frequency to keep a pixel in the comparison",
    )
    p.add_argument(
        "--datum-offset",
        action="append",
        default=None,
        help="Override per-site KHOA→EGM2008 offset: 'site_id=value' (repeatable)",
    )
    p.add_argument(
        "--skip-glo30-download", action="store_true",
        help="Use cached GLO-30 only",
    )
    return p.parse_args()


def _parse_datum_overrides(items: list[str] | None) -> dict[str, float]:
    out = dict(KHOA_TO_EGM2008_M)
    if not items:
        return out
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--datum-offset expects 'site=value', got {it!r}")
        site, val = it.split("=", 1)
        out[site] = float(val)
    return out


def _load_predicted_bias(
    site_id: str,
    variant: str,
    tables_dir: Path,
    beta: float = BETA_DEFAULT,
) -> float | None:
    """Compute β·A·⟨cos θ⟩ from the per-variant diagnostics table.

    The diagnostics table contains, for each scene that contributed to a
    variant, the (sensor, scene_id, tide_m, threshold, method) tuple.
    The manuscript predictor needs ⟨cos θ⟩ over the same population —
    we therefore re-derive it here from the *phases* parquet emitted by
    the Phase-0 diagnostic, joining on (site, sensor, scene_id).
    """
    diag_path = tables_dir / f"{site_id}_variant_diagnostics.csv"
    if not diag_path.exists():
        return None
    diag = pd.read_csv(diag_path)
    diag = diag[diag["variant"] == variant]
    if diag.empty:
        return None

    # Phases come from src/analysis/phase calculations. The Phase-0
    # diagnostic writes <site>_s1_phases.parquet for S1 and
    # multisite_5y_phases.parquet for the optical sensors.
    proj_root = tables_dir.parent.parent
    processed = proj_root / "processed"
    optical = None
    multi_path = processed / "multisite_5y_phases.parquet"
    if multi_path.exists():
        multi = pd.read_parquet(multi_path)
        optical = multi[multi["site_id"] == site_id][["sensor", "scene_id", "cos_theta"]]
    s1_path = processed / f"{site_id}_s1_phases.parquet"
    s1 = None
    if s1_path.exists():
        s1 = pd.read_parquet(s1_path)[["sensor", "scene_id", "cos_theta"]]
    if optical is None and s1 is None:
        return None
    parts = [df for df in (optical, s1) if df is not None]
    phases = pd.concat(parts, ignore_index=True)
    diag = diag.astype({"scene_id": str})
    phases = phases.astype({"scene_id": str})
    merged = diag.merge(phases, on=["sensor", "scene_id"], how="left")
    if merged["cos_theta"].isna().all():
        return None
    cos_mean = float(merged["cos_theta"].mean(skipna=True))
    A = SITE_AMPLITUDE_M.get(site_id)
    if A is None:
        return None
    return beta * A * cos_mean


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites_all = {s.id: s for s in load_sites()}
    offsets = _parse_datum_overrides(args.datum_offset)

    dem_dir = resolve_path("data/outputs/dem")
    glo30_dir = resolve_path("data/raw/glo30")
    tables_dir = resolve_path(settings["paths"]["tables"])
    glo30_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_glo30_download:
        log.info("Initialising Earth Engine (project=%s)", args.project)
        initialize(project=args.project)

    stats_list = []
    for site_id in args.sites:
        if site_id not in sites_all:
            log.warning("Skipping unknown site %s", site_id)
            continue
        site = sites_all[site_id]

        glo30_path = glo30_dir / f"{site_id}_glo30.tif"
        if not glo30_path.exists():
            if args.skip_glo30_download:
                log.warning("GLO-30 cache missing for %s; skipping", site_id)
                continue
            fetch_glo30_for_bbox(site.bbox, out_path=glo30_path)

        offset = offsets.get(site_id, 0.0)
        log.info("Site %s: datum offset KHOA→EGM2008 = %+0.2f m", site_id, offset)

        for variant in args.variants:
            dem_path = dem_dir / f"{site_id}_{variant}.tif"
            if not dem_path.exists():
                log.warning("Missing DEM: %s (build Phase 4 first)", dem_path)
                continue

            reprj_path = dem_dir / f"{site_id}_{variant}_on_glo30.tif"
            reproject_to_glo30_grid(dem_path, glo30_path, reprj_path)

            # Inundation freq lives on the original 10 m DEM (band 3) —
            # reproject it onto the GLO-30 grid the same way so we can
            # restrict the comparison to intertidal pixels.
            inund_path = dem_dir / f"{site_id}_{variant}_inundation_on_glo30.tif"
            _reproject_band_to_glo30(
                src_path=dem_path,
                src_band=3,
                glo30_path=glo30_path,
                out_path=inund_path,
            )

            predicted = _load_predicted_bias(site_id, variant, tables_dir)
            stats, _ = compare_to_glo30(
                reprj_path,
                glo30_path,
                site_id=site_id,
                variant=variant,
                khoa_to_egm2008_offset_m=offset,
                predicted_bias_m=predicted,
                inundation_min=args.inundation_min,
                inundation_max=args.inundation_max,
                inundation_path=inund_path,
            )
            stats_list.append(stats)
            log.info(
                "  %s %s: n=%d, RMSE=%.3f m, MAE=%.3f m, bias=%+.3f m (pred=%s)",
                site_id, variant, stats.n_pixels,
                stats.rmse_m, stats.mae_m, stats.mean_bias_m,
                f"{predicted:+.3f}" if predicted is not None else "n/a",
            )

    if not stats_list:
        log.warning("Nothing to validate")
        return

    df = stats_to_dataframe(stats_list)
    out_path = tables_dir / "dem_validation.csv"
    df.to_csv(out_path, index=False, float_format="%.4f")
    log.info("Wrote %s", out_path)
    print()
    print(df.to_string(index=False))


def _reproject_band_to_glo30(
    src_path: Path,
    src_band: int,
    glo30_path: Path,
    out_path: Path,
) -> Path:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    with rasterio.open(glo30_path) as ref:
        ref_transform = ref.transform
        ref_crs = ref.crs
        ref_height = ref.height
        ref_width = ref.width
        ref_profile = ref.profile.copy()

    with rasterio.open(src_path) as src:
        out_arr = np.full((ref_height, ref_width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, src_band),
            destination=out_arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            resampling=Resampling.average,
        )

    ref_profile.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **ref_profile) as dst:
        dst.write(out_arr.astype(np.float32), 1)
    return out_path


if __name__ == "__main__":
    main()
