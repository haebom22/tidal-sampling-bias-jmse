"""Generate the per-pixel sampling-bias QA raster for each pilot site.

For each (site, year) we:

1. Load the cached satellite metadata (``data/raw/gee_metadata``) and
   take all scenes whose acquisition falls in ``year ± rolling/2``.
2. Compute the FES2014 (or FES2022b if present) tide heights at the
   scene times AND at a 30-min reference grid spanning the same window.
3. Build the 3-metric QA on a 0.05 deg coarse grid covering the site
   bbox using the FES2022b-preferred ``build_bbox_qa``.
4. Rasterise the result onto the V4 DEM grid and write a 4-band QA
   GeoTIFF at ``data/outputs/extent/<site>_qa_<year>.tif``.

This is the Phase 1b deliverable of the methodology plan.

Usage
-----
    python scripts/run_bias_qa.py --start-year 2016 --end-year 2024 --rolling 3
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from src.config import load_settings, load_sites, resolve_path
from src.analysis.bias_qa import build_bbox_qa, rasterise_qa_grid_to_dem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("run_bias_qa")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument("--rolling", type=int, default=3)
    p.add_argument("--sites", nargs="*", default=None)
    p.add_argument(
        "--model-name",
        default="FES2022_extrapolated",
        help="FES atlas identifier (FES2022_extrapolated, FES2022, FES2014).",
    )
    p.add_argument(
        "--model-dir",
        default=None,
        help="Override the tide model root directory (default: data/raw, "
             "which resolves fes2022b/ocean_tide_extrapolated/...).",
    )
    p.add_argument(
        "--grid-spacing",
        type=float,
        default=0.05,
        help="QA query grid spacing in degrees (default 0.05 ≈ 5 km).",
    )
    p.add_argument(
        "--reference-freq",
        default="30min",
        help="Reference tide sampling interval (default 30min).",
    )
    p.add_argument(
        "--n-obs-threshold",
        type=int,
        default=5,
        help="Minimum n_obs per pixel for the QA-pass gate (default 5).",
    )
    p.add_argument(
        "--spatial-mode",
        choices=["single_point", "grid"],
        default="single_point",
        help="single_point (default): one FES call at bbox centre, "
             "broadcast metrics to every node. grid: per-node FES call "
             "(slow on FES2022b).",
    )
    p.add_argument(
        "--fes-timeout",
        type=int,
        default=600,
        help="Per-FES-call wallclock budget in seconds (default 600).",
    )
    return p.parse_args()


def _window_dates(year: int, rolling: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    half = rolling // 2
    start = pd.Timestamp(f"{max(2015, year - half)}-01-01", tz="UTC")
    end = pd.Timestamp(f"{year + half}-12-31 23:59:59", tz="UTC")
    return start, end


def _load_scene_times(site_id: str, gee_dir: Path, start, end) -> pd.DatetimeIndex:
    scenes_path = gee_dir / f"{site_id}_scenes.parquet"
    if not scenes_path.exists():
        raise FileNotFoundError(scenes_path)
    df = pd.read_parquet(scenes_path)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    mask = (df["datetime_utc"] >= start) & (df["datetime_utc"] <= end)
    times = df.loc[mask, "datetime_utc"].sort_values().reset_index(drop=True)
    return pd.DatetimeIndex(times)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites_all = {s.id: s for s in load_sites()}
    site_ids = args.sites or list(sites_all.keys())

    gee_dir = resolve_path(settings["paths"]["gee_metadata"])
    extent_dir = resolve_path("data/outputs/extent")
    tables_dir = resolve_path(settings["paths"]["tables"])
    extent_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    # The pyfes-backed compute_tide_heights resolves model layouts
    # relative to `model_directory` (e.g. data/raw → fes2022b/ocean_tide_extrapolated/...).
    if args.model_dir is None:
        model_dir = resolve_path("data/raw")
    else:
        model_dir = Path(args.model_dir)
    log.info("Tide model dir: %s (model=%s)", model_dir, args.model_name)

    fes2022b_leaf = model_dir / "fes2022b" / "ocean_tide_extrapolated"
    fes2014_leaf = model_dir / "fes2014" / "ocean_tide"
    if args.model_name.startswith("FES2022") and not fes2022b_leaf.exists():
        if fes2014_leaf.exists():
            log.warning(
                "FES2022b leaf %s missing — falling back to FES2014",
                fes2022b_leaf,
            )
            args.model_name = "FES2014"
        else:
            raise SystemExit(
                f"Neither FES2022b ({fes2022b_leaf}) nor FES2014 "
                f"({fes2014_leaf}) NetCDFs found. Place model files in "
                f"data/raw/fes2022b/ocean_tide_extrapolated/ and rerun, "
                f"or set SKIP_PHASE1B=1 to skip this phase."
            )

    summary_rows: list[dict] = []
    for site_id in site_ids:
        if site_id not in sites_all:
            log.warning("Unknown site %s — skip", site_id)
            continue
        site = sites_all[site_id]
        for year in range(args.start_year, args.end_year + 1):
            start, end = _window_dates(year, args.rolling)
            log.info("=== %s %s (window %s..%s) ===", site_id, year, start.date(), end.date())
            try:
                sat_times = _load_scene_times(site_id, gee_dir, start, end)
            except FileNotFoundError:
                log.warning("No metadata for %s, skip", site_id)
                continue
            if len(sat_times) < 5:
                log.warning("Too few scenes (%d), skip", len(sat_times))
                continue

            try:
                qa_grid = build_bbox_qa(
                    bbox=site.bbox,
                    satellite_times_utc=sat_times,
                    reference_start=start,
                    reference_end=end,
                    model_directory=model_dir,
                    model_name=args.model_name,
                    grid_spacing_deg=args.grid_spacing,
                    reference_freq=args.reference_freq,
                    spatial_mode=args.spatial_mode,
                    fes_timeout_s=args.fes_timeout,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("build_bbox_qa raised (%s) — recording nan row.", exc)
                qa_grid = pd.DataFrame()

            if qa_grid.empty or "n_satellite" not in qa_grid.columns:
                log.warning(
                    "QA grid empty for %s %s — recording placeholder nan row.",
                    site_id, year,
                )
                import numpy as np
                summary_rows.append({
                    "site_id": site_id,
                    "year": year,
                    "n_satellite": int(len(sat_times)),
                    "n_reference": -1,
                    "spread_med": float("nan"),
                    "high_offset_med": float("nan"),
                    "low_offset_med": float("nan"),
                    "qa_pass_frac": float("nan"),
                })
                continue

            # Per-site annual summary (median across the coarse grid).
            summary_rows.append({
                "site_id": site_id,
                "year": year,
                "n_satellite": int(qa_grid["n_satellite"].median()),
                "n_reference": int(qa_grid["n_reference"].median()),
                "spread_med": float(qa_grid["spread"].median()),
                "high_offset_med": float(qa_grid["high_offset"].median()),
                "low_offset_med": float(qa_grid["low_offset"].median()),
                "qa_pass_frac": float(qa_grid["qa_pass"].mean()),
            })

            # Rasterise on the V4 DEM grid (or annual V4 if present).
            v4_annual = resolve_path(f"data/outputs/dem/annual/{site_id}_v4_{year}.tif")
            v4_full = resolve_path(f"data/outputs/dem/{site_id}_v4.tif")
            ref_dem = v4_annual if v4_annual.exists() else v4_full
            if not ref_dem.exists():
                log.warning("No reference DEM (%s); writing coarse grid only", ref_dem)
                qa_grid.to_csv(
                    extent_dir / f"{site_id}_qa_{year}_coarse.csv",
                    index=False, float_format="%.4f",
                )
                continue

            out_path = extent_dir / f"{site_id}_qa_{year}.tif"
            try:
                rasterise_qa_grid_to_dem(
                    qa_grid=qa_grid,
                    reference_dem_path=ref_dem,
                    out_path=out_path,
                    n_obs_path=ref_dem,
                    n_obs_band=4,  # band 4 of the V4 DEM is n_obs
                    n_obs_threshold=args.n_obs_threshold,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("rasterise_qa_grid_to_dem failed (%s)", exc)

    if summary_rows:
        df = pd.DataFrame(summary_rows)
        out_csv = tables_dir / "bias_qa_summary.csv"
        df.to_csv(out_csv, index=False, float_format="%.4f")
        log.info("Wrote %s (%d rows)", out_csv, len(df))
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
