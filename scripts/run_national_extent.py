"""National-scale annual tidal-flat extent pipeline.

For every tile defined in ``config/national_tiles.yaml`` and every year
in the requested range, this driver runs the *full* per-tile pipeline:

  1. Extract scene metadata for the tile bbox via GEE.
  2. Synthesise the tide at every scene's acquisition time using
     FES2022b / FES2014 (no KHOA gauge needed).
  3. Extract the local M2 amplitude from the FES NetCDF for the
     per-scene bias correction (η_corr = η_raw - β · A · cos θ).
  4. Run :func:`src.gee.dem.build_dem_gee` (V4 = L8+L9+S2+S1, corrected).
  5. Run :func:`src.gee.msic_oa.build_msic_oa_extent` (MSIC-OA).
  6. Optionally run :func:`src.analysis.bias_qa.build_bbox_qa` per tile.
  7. Export tile V4 DEM + MSIC + QA GeoTIFFs.

Output layout::

    data/outputs/dem/national/<tile_id>_v4_<year>.tif
    data/outputs/extent/national/<tile_id>_msic_<year>.tif
    data/outputs/extent/national/<tile_id>_qa_<year>.tif
    data/outputs/tables/national_tile_summary.csv

The tile mosaic is built by ``scripts/run_national_mosaic.py``
(Phase 4c).

Usage
-----
    EE_PROJECT=<project> python scripts/run_national_extent.py \\
        --start-year 2016 --end-year 2024 --rolling 3 \\
        --tiles K_1262_3766 K_1262_3676   # subset for testing
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import ee
import numpy as np
import pandas as pd

from src.analysis.bias_qa import build_bbox_qa, rasterise_qa_grid_to_dem
from src.analysis.phase import compute_phase_hw, find_tide_extremes
from src.config import resolve_path
from src.gee.auth import initialize
from src.gee.dem import (
    BETA_DEFAULT,
    DemBuildSpec,
    apply_bias_correction,
    build_dem_gee,
)
from src.gee.exports import (
    export_image_to_drive,
    export_image_to_local,
    wait_for_task,
)
from src.gee.metadata import extract_bbox_metadata
from src.gee.msic_oa import build_msic_oa_extent
from src.gee.national_tiling import CoastalTile, load_tiles_yaml
from src.tides.fes_helpers import (
    extract_m2_amplitude,
    fetch_tide_hourly_fes,
    find_fes_directory,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("national_extent")

# FES atlases are loaded once over this stable national envelope (rather
# than a fresh per-tile bbox), so the HDF5/NetCDF grids are read a single
# time per process. Re-opening them every tile triggers the intermittent
# ``RuntimeError: NetCDF: HDF error`` that previously killed the run.
NATIONAL_FES_BBOX = [122.0, 31.0, 132.0, 40.0]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=None)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument("--rolling", type=int, default=3)
    p.add_argument(
        "--tiles", nargs="*", default=None,
        help="Subset of tile ids (default: all in config/national_tiles.yaml).",
    )
    p.add_argument(
        "--tiles-config",
        default="config/national_tiles.yaml",
        help="Tile list YAML (default: config/national_tiles.yaml).",
    )
    p.add_argument("--scale-m", type=int, default=10)
    p.add_argument("--cloud-max", type=float, default=60.0)
    p.add_argument("--beta", type=float, default=BETA_DEFAULT)
    p.add_argument(
        "--skip-qa", action="store_true",
        help="Skip the eo-tides-style QA layer (faster).",
    )
    p.add_argument(
        "--export-mode",
        choices=["local", "drive", "none"], default="local",
    )
    p.add_argument(
        "--no-jrc-mask", action="store_true",
        help="Do NOT clip the DEM to the JRC GSW intertidal zone "
             "(occurrence 5-95%%). The JRC mask discards valid SAR-derived "
             "waterlines in high-turbidity bays (Incheon/Gyeonggi), where "
             "JRC saturates at occurrence>95%%; the n_obs gate + elevation "
             "band already constrain the result to true intertidal.",
    )
    p.add_argument(
        "--dem-suffix", default="v4",
        help="Filename stem suffix for the DEM (e.g. 'v4' or 'v5nojrc').",
    )
    return p.parse_args()


def _window(year: int, rolling: int) -> tuple[str, str]:
    half = rolling // 2
    return f"{max(2015, year - half)}-01-01", f"{year + half}-12-31"


def _enrich_scenes_with_fes(
    scenes: pd.DataFrame,
    lon: float,
    lat: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    fes_dir: Path,
    fes_name: str,
    bounds: list[float] | None = None,
) -> pd.DataFrame:
    """Attach tide + cos θ to the per-scene metadata via FES (no KHOA)."""
    if scenes.empty:
        return scenes
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
    hourly = fetch_tide_hourly_fes(
        lon=lon, lat=lat, start=start, end=end,
        model_directory=fes_dir, model_name=fes_name,
        bounds=bounds,
    )
    # Interpolate FES hourly series at scene times.
    h = hourly.sort_values("datetime_utc").reset_index(drop=True)
    times_num = h["datetime_utc"].astype("int64").to_numpy()
    sc_times = scenes["datetime_utc"].astype("int64").to_numpy()
    scenes["tide_m"] = np.interp(sc_times, times_num, h["tide_m"].to_numpy())
    extremes = find_tide_extremes(h)
    scenes["phase_hw"] = compute_phase_hw(scenes["datetime_utc"], extremes.high_times)
    scenes["theta"] = 2 * np.pi * scenes["phase_hw"]
    scenes["cos_theta"] = np.cos(scenes["theta"])
    scenes["sin_theta"] = np.sin(scenes["theta"])
    return scenes.dropna(subset=["tide_m", "cos_theta"]).reset_index(drop=True)


def _export(image: ee.Image, region: ee.Geometry, out_path: Path,
            scale_m: int, mode: str) -> None:
    if mode == "none":
        return
    if mode == "local":
        result = export_image_to_local(
            image, region=region, scale_m=scale_m,
            out_path=out_path, overwrite=False,
        )
        if not result.ok:
            task = export_image_to_drive(
                image, region=region, scale_m=scale_m, description=out_path.stem,
            )
            wait_for_task(task)
    else:
        task = export_image_to_drive(
            image, region=region, scale_m=scale_m, description=out_path.stem,
        )
        wait_for_task(task)


def _process_tile(
    tile: CoastalTile,
    year: int,
    *,
    start: str,
    end: str,
    args: argparse.Namespace,
    fes_dir: Path,
    fes_name: str,
    dem_dir: Path,
    extent_dir: Path,
) -> dict | None:
    """Run V4 + MSIC + QA + export for one (tile, year). Returns summary row."""
    log.info("=== Tile %s | year %d (%s..%s) ===", tile.id, year, start, end)
    geometry = tile.geometry()

    scenes = extract_bbox_metadata(
        tile.id, tile.bbox,
        sensors=("L8", "L9", "S2", "S1"),
        start=start, end=end,
    )
    if scenes.empty:
        log.warning("  no scenes — skip")
        return None

    scenes = _enrich_scenes_with_fes(
        scenes, lon=tile.center["lon"], lat=tile.center["lat"],
        start=pd.Timestamp(start, tz="UTC"),
        end=pd.Timestamp(end, tz="UTC"),
        fes_dir=fes_dir, fes_name=fes_name,
        bounds=NATIONAL_FES_BBOX,
    )

    # Tile-specific M2 amplitude (robust: nearest-valid ocean cell, with
    # neighbourhood-median rejection of FES coastal-extrapolation artefacts and
    # a physical cap for the Korean coast; see scripts/validate_fes_amplitude.py).
    A_m = extract_m2_amplitude(
        tile.center["lon"], tile.center["lat"], fes_dir,
        robust=True, cap_m=3.5,
    )
    if not np.isfinite(A_m):
        log.warning("  M2 amplitude unavailable; using 2.0 m fallback")
        A_m = 2.0
    log.info("  local M2 amplitude = %.2f m", A_m)
    scenes = apply_bias_correction(
        scenes, site_id=tile.id, beta=args.beta, amplitude_m=A_m,
    )

    spec = DemBuildSpec(
        site_id=tile.id, geometry=geometry,
        sensors=("L8", "L9", "S2", "S1"),
        scenes=scenes, tide_col="tide_corrected_m",
        start=start, end=end,
        cloud_max=args.cloud_max, output_scale_m=args.scale_m,
    )
    try:
        dem_img, _ = build_dem_gee(
            spec, return_diagnostics=True,
            apply_jrc_mask=not args.no_jrc_mask,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("  build_dem_gee failed: %s", exc)
        return None

    dem_path = dem_dir / f"{tile.id}_{args.dem_suffix}_{year}.tif"
    _export(dem_img, geometry, dem_path, args.scale_m, args.export_mode)

    # MSIC-OA. Skip the (expensive) GEE build when the tile already exists
    # — the national MSIC layer is unchanged by the DEM JRC-mask rebuild.
    msic_path = extent_dir / f"{tile.id}_msic_{year}.tif"
    if msic_path.exists():
        log.info("  MSIC exists, skipping build: %s", msic_path.name)
    else:
        try:
            msic = build_msic_oa_extent(
                geometry=geometry, start=start, end=end,
                cloud_max=args.cloud_max,
            )
            _export(msic.image, geometry, msic_path, args.scale_m, args.export_mode)
        except Exception as exc:  # noqa: BLE001
            log.warning("  MSIC-OA failed for %s %d: %s", tile.id, year, exc)
            msic_path = None

    # Optional QA layer.
    qa_summary = {}
    if not args.skip_qa and dem_path.exists():
        try:
            qa_grid = build_bbox_qa(
                bbox=tile.bbox,
                satellite_times_utc=pd.DatetimeIndex(scenes["datetime_utc"]),
                reference_start=pd.Timestamp(start, tz="UTC"),
                reference_end=pd.Timestamp(end, tz="UTC"),
                model_directory=fes_dir, model_name=fes_name,
                fes_bounds=NATIONAL_FES_BBOX,
            )
            qa_path = extent_dir / f"{tile.id}_qa_{year}.tif"
            rasterise_qa_grid_to_dem(
                qa_grid, dem_path, qa_path,
                n_obs_path=dem_path, n_obs_band=4,
            )
            qa_summary = {
                "qa_spread_med": float(qa_grid["spread"].median()),
                "qa_high_off_med": float(qa_grid["high_offset"].median()),
                "qa_low_off_med": float(qa_grid["low_offset"].median()),
                "qa_pass_frac": float(qa_grid["qa_pass"].mean()),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("  QA failed for %s %d: %s", tile.id, year, exc)

    return {
        "tile_id": tile.id,
        "year": year,
        "window_start": start,
        "window_end": end,
        "n_scenes": len(scenes),
        "n_intertidal_pixels_jrc": tile.n_intertidal_pixels,
        "m2_amplitude_m": A_m,
        "dem_path": str(dem_path),
        "msic_path": str(msic_path) if msic_path else "",
        "region_hint": tile.region_hint or "",
        **qa_summary,
    }


def main() -> None:
    args = parse_args()
    initialize(project=args.project)

    project_root = resolve_path(".")
    try:
        fes_dir, fes_name = find_fes_directory(project_root)
    except FileNotFoundError as exc:
        raise SystemExit(f"{exc}\nRun scripts/download_fes2022b.sh first.")
    log.info("Using tide model %s in %s", fes_name, fes_dir)

    tiles = load_tiles_yaml(resolve_path(args.tiles_config))
    if args.tiles:
        tiles = [t for t in tiles if t.id in set(args.tiles)]
    log.info("Processing %d tiles", len(tiles))

    dem_dir = resolve_path("data/outputs/dem/national")
    extent_dir = resolve_path("data/outputs/extent/national")
    tables_dir = resolve_path("data/outputs/tables")
    dem_dir.mkdir(parents=True, exist_ok=True)
    extent_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    out_csv = tables_dir / "national_tile_summary.csv"
    rows: list[dict] = []
    n_jobs = len(tiles) * (args.end_year - args.start_year + 1)
    done = 0
    failed: list[str] = []
    for tile in tiles:
        for year in range(args.start_year, args.end_year + 1):
            done += 1
            start, end = _window(year, args.rolling)
            try:
                row = _process_tile(
                    tile, year, start=start, end=end, args=args,
                    fes_dir=fes_dir, fes_name=fes_name,
                    dem_dir=dem_dir, extent_dir=extent_dir,
                )
            except Exception as exc:  # noqa: BLE001
                # One bad tile/year must never abort the whole national run.
                log.exception(
                    "[%d/%d] tile %s year %d FAILED: %s — skipping",
                    done, n_jobs, tile.id, year, exc,
                )
                failed.append(f"{tile.id}:{year}")
                row = None
            if row is not None:
                rows.append(row)
                # Incremental save: a later crash never loses prior tiles.
                pd.DataFrame(rows).to_csv(out_csv, index=False)
            log.info("[%d/%d] complete (%d ok, %d failed)",
                     done, n_jobs, len(rows), len(failed))

    if rows:
        pd.DataFrame(rows).to_csv(out_csv, index=False)
        log.info("Wrote %s (%d rows)", out_csv, len(rows))
    if failed:
        log.warning("%d tile-years failed: %s", len(failed), ", ".join(failed))


if __name__ == "__main__":
    main()
