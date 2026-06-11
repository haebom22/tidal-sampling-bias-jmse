"""Build annual V4 DEMs (L8+L9+S2+S1, bias-corrected) for 5 pilot sites.

Phase 1c of the methodology plan. Reuses the existing
:mod:`src.gee.dem.build_dem_gee` server-side pipeline and the per-scene
bias correction ``apply_bias_correction``. The only new aspect is the
*annual* time slicing and the optional N-year rolling window.

Outputs
-------
- ``data/outputs/dem/annual/<site>_v4_<year>.tif`` per (site, year).
  Bands: 1=dem_m, 2=max_land_tide, 3=min_water_tide, 4=n_obs,
         5=inundation_frequency.
- ``data/outputs/tables/annual_v4_dem_summary.csv``: per-(site, year)
  diagnostics — scene counts per sensor, thresholds, etc.

Usage
-----
    EE_PROJECT=<project> python scripts/run_annual_v4_dem.py \\
        --start-year 2016 --end-year 2024 --rolling 3
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import ee
import numpy as np
import pandas as pd

from src.analysis.phase import compute_phase_hw, find_tide_extremes
from src.config import load_settings, load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.dem import (
    BETA_DEFAULT,
    SITE_AMPLITUDE_M,
    DemBuildSpec,
    apply_bias_correction,
    build_dem_gee,
)
from src.gee.exports import (
    export_image_to_drive,
    export_image_to_local,
    wait_for_task,
)
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times
from src.tides.fes2014 import compute_tide_heights

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("annual_v4")

ALL_SENSORS = ("L8", "L9", "S2", "S1")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument(
        "--rolling",
        type=int,
        default=3,
        help="N-year rolling window centred on each year (default 3).",
    )
    p.add_argument("--sites", nargs="*", default=None)
    p.add_argument(
        "--beta", type=float, default=BETA_DEFAULT,
        help="Bias-model slope (default 1.78 from manuscript pooled fit).",
    )
    p.add_argument(
        "--scale-m", type=int, default=10,
        help="Output DEM pixel size in metres (default 10).",
    )
    p.add_argument("--cloud-max", type=float, default=60.0)
    p.add_argument(
        "--export-mode",
        choices=["local", "drive", "none"],
        default="local",
    )
    p.add_argument(
        "--variants",
        nargs="*",
        default=["v4"],
        choices=["v1", "v2", "v3", "v4"],
        help="Variant(s) to build per year (default: v4 only).",
    )
    p.add_argument(
        "--no-jrc-mask", action="store_true",
        help="Do NOT clip the DEM to the JRC GSW intertidal zone "
             "(occurrence 5-95%%). The JRC mask discards valid SAR-derived "
             "waterlines in high-turbidity bays (Ganghwa/Hampyeong) where JRC "
             "saturates at occurrence>95%%; the n_obs gate + elevation band + "
             "intrinsic inundation-frequency gate already constrain the result.",
    )
    p.add_argument(
        "--dem-suffix", default=None,
        help="Override the filename stem (e.g. 'v5nojrc'). Defaults to the "
             "variant name (v4).",
    )
    return p.parse_args()


def _window_dates(year: int, rolling: int) -> tuple[str, str]:
    half = rolling // 2
    start_yr = max(2015, year - half)
    end_yr = year + half
    return f"{start_yr}-01-01", f"{end_yr}-12-31"


def _synthetic_tide_series(
    site,
    start: str,
    end: str,
    model_dir: Path,
    model_name: str = "FES2022_extrapolated",
    freq_minutes: int = 60,
) -> pd.DataFrame:
    """Generate a synthetic hourly tide series at the site centre via pyfes.

    Used as a drop-in replacement for the KHOA tide-gauge series when the
    cache is unavailable for the requested date range. Returns a
    DataFrame with the same ``[datetime_utc, tide_m]`` schema as the KHOA
    loader so the rest of the pipeline (extrema detection, phase, bias
    correction) works unchanged.
    """
    times = pd.date_range(
        pd.Timestamp(start, tz="UTC"),
        pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=23),
        freq=f"{freq_minutes}min", tz="UTC",
    )
    # site bbox is [lon_min, lat_min, lon_max, lat_max]
    lon_c = 0.5 * (site.bbox[0] + site.bbox[2])
    lat_c = 0.5 * (site.bbox[1] + site.bbox[3])
    heights = compute_tide_heights(
        lon=lon_c, lat=lat_c, times=times,
        model_directory=model_dir, model_name=model_name,
        bounds=list(site.bbox),
    )
    return pd.DataFrame({"datetime_utc": times, "tide_m": heights}).dropna()


def _load_scenes_with_tides(
    site,
    start: str,
    end: str,
    gee_dir: Path,
    khoa_dir: Path,
    primary_station: str,
    fes_model_dir: Path,
    fes_model_name: str = "FES2022_extrapolated",
) -> pd.DataFrame:
    """Load scenes + per-scene tide. Falls back to pyfes if KHOA is empty.

    Order of preference for the hourly reference tide series:
      1. KHOA hourly cache (per-station, per-day JSON under
         ``data/raw/khoa/tide_hourly``); requires an API key only on
         cache miss.
      2. FES2022b synthetic series at the site bbox centre (~few cm
         accuracy at our pilot sites; sufficient for tide-aware
         compositing & bias correction).
    """
    site_id = site.id
    scenes_path = gee_dir / f"{site_id}_scenes.parquet"
    if not scenes_path.exists():
        raise FileNotFoundError(scenes_path)
    scenes = pd.read_parquet(scenes_path)
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
    mask = (scenes["datetime_utc"] >= pd.Timestamp(start, tz="UTC")) & (
        scenes["datetime_utc"] <= pd.Timestamp(end, tz="UTC")
    )
    scenes = scenes[mask].copy()
    if scenes.empty:
        return scenes

    tide_source = "khoa"
    try:
        khoa = fetch_tide_hourly_range(
            primary_station,
            date.fromisoformat(start),
            date.fromisoformat(end),
            khoa_dir,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("KHOA fetch raised (%s) — will use FES2022b fallback.", exc)
        khoa = pd.DataFrame()

    # Treat KHOA as "usable" only when it covers a large enough share of
    # the requested window. A handful of stale cached days (e.g. a probe
    # call) is worse than no KHOA at all, because the resulting interp
    # gaps (max_gap_minutes=90) NaN-out every satellite scene.
    expected_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    khoa_days = (
        int(pd.to_datetime(khoa["datetime_utc"], utc=True).dt.floor("D").nunique())
        if not khoa.empty else 0
    )
    coverage = khoa_days / max(expected_days, 1)
    if coverage < 0.5:
        if khoa_days > 0:
            log.warning(
                "KHOA %s coverage %.0f%% (%d / %d days) < 50%% for %s..%s — "
                "using FES2022b fallback at site centre.",
                primary_station, coverage * 100, khoa_days, expected_days,
                start, end,
            )
        else:
            log.warning(
                "KHOA %s cache empty for %s..%s — using FES2022b fallback "
                "at site centre.",
                primary_station, start, end,
            )
        khoa = _synthetic_tide_series(site, start, end, fes_model_dir, fes_model_name)
        tide_source = "fes2022b"

    if khoa.empty:
        raise RuntimeError(
            f"Both KHOA cache and FES2022b fallback returned empty "
            f"series for {site_id} {start}..{end}."
        )

    scenes["tide_source"] = tide_source
    scenes["tide_m"] = interpolate_at_times(khoa, scenes["datetime_utc"]).to_numpy()
    extremes = find_tide_extremes(khoa)
    scenes["phase_hw"] = compute_phase_hw(scenes["datetime_utc"], extremes.high_times)
    scenes["theta"] = 2 * np.pi * scenes["phase_hw"]
    scenes["cos_theta"] = np.cos(scenes["theta"])
    scenes["sin_theta"] = np.sin(scenes["theta"])
    scenes = scenes.dropna(subset=["tide_m", "cos_theta"]).reset_index(drop=True)
    return scenes


def _variant_spec(
    variant: str,
    site_id: str,
    geometry: ee.Geometry,
    scenes: pd.DataFrame,
    start: str,
    end: str,
    beta: float,
    cloud_max: float,
    scale_m: int,
) -> DemBuildSpec:
    if variant in ("v1", "v3"):
        sensors = ("L8", "L9", "S2")
    elif variant in ("v2", "v4"):
        sensors = ALL_SENSORS
    else:
        raise ValueError(variant)

    if variant in ("v1", "v2"):
        tide_col = "tide_m"
        scenes_used = scenes
    else:
        scenes_used = apply_bias_correction(scenes, site_id, beta=beta)
        tide_col = "tide_corrected_m"

    return DemBuildSpec(
        site_id=site_id,
        geometry=geometry,
        sensors=sensors,
        scenes=scenes_used,
        tide_col=tide_col,
        start=start,
        end=end,
        cloud_max=cloud_max,
        output_scale_m=scale_m,
    )


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
            log.warning("Local export empty → submitting Drive: %s", out_path.name)
            task = export_image_to_drive(
                image, region=region, scale_m=scale_m,
                description=out_path.stem,
            )
            wait_for_task(task)
    else:
        task = export_image_to_drive(
            image, region=region, scale_m=scale_m, description=out_path.stem,
        )
        wait_for_task(task)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites_all = {s.id: s for s in load_sites()}
    site_ids = args.sites or list(sites_all.keys())

    gee_dir = resolve_path(settings["paths"]["gee_metadata"])
    khoa_dir = resolve_path(settings["paths"]["khoa"])
    fes_model_dir = resolve_path("data/raw")
    dem_dir = resolve_path("data/outputs/dem/annual")
    tables_dir = resolve_path(settings["paths"]["tables"])
    dem_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    initialize(project=args.project)

    summary: list[dict] = []
    for site_id in site_ids:
        if site_id not in sites_all:
            log.warning("Unknown site %s", site_id)
            continue
        if site_id not in SITE_AMPLITUDE_M:
            log.warning("No amplitude for %s — skip", site_id)
            continue
        site = sites_all[site_id]
        geometry = ee.Geometry.Rectangle(site.bbox, proj="EPSG:4326", geodesic=False)
        primary_station = site.khoa_stations[0].code

        for year in range(args.start_year, args.end_year + 1):
            start, end = _window_dates(year, args.rolling)
            log.info("=== %s %s (%s..%s) ===", site_id, year, start, end)
            try:
                scenes = _load_scenes_with_tides(
                    site, start, end, gee_dir, khoa_dir, primary_station,
                    fes_model_dir=fes_model_dir,
                )
            except FileNotFoundError:
                log.warning("No metadata for %s, skip", site_id)
                break
            if scenes.empty:
                log.warning("No scenes in window — skip")
                continue

            by_sensor = scenes.groupby("sensor").size().to_dict()
            log.info("  scenes by sensor: %s", by_sensor)

            for variant in args.variants:
                spec = _variant_spec(
                    variant, site_id, geometry, scenes,
                    start=start, end=end, beta=args.beta,
                    cloud_max=args.cloud_max, scale_m=args.scale_m,
                )
                try:
                    dem_img, _ = build_dem_gee(
                        spec, return_diagnostics=True,
                        apply_jrc_mask=not args.no_jrc_mask,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.exception("build_dem_gee failed: %s", exc)
                    continue

                stem = args.dem_suffix or variant
                out_path = dem_dir / f"{site_id}_{stem}_{year}.tif"
                _export(dem_img, geometry, out_path, args.scale_m, args.export_mode)
                summary.append({
                    "site_id": site_id,
                    "year": year,
                    "variant": variant,
                    "window_start": start,
                    "window_end": end,
                    "n_total_scenes": len(scenes),
                    **{f"n_{s}": by_sensor.get(s, 0) for s in ALL_SENSORS},
                    "output": str(out_path.relative_to(resolve_path("."))),
                })

    if summary:
        df = pd.DataFrame(summary)
        out_csv = tables_dir / "annual_v4_dem_summary.csv"
        df.to_csv(out_csv, index=False)
        log.info("Wrote %s (%d rows)", out_csv, len(df))


if __name__ == "__main__":
    main()
