"""Build the 4 pilot DEM variants for one site.

Variants (manuscript §5.3(c) prediction):

    V1  L8 + L9 + S2              (baseline)
    V2  L8 + L9 + S2 + S1         (phase-orthogonal SAR fusion)
    V3  L8 + L9 + S2 + bias       (a-priori β·A·cos θ correction)
    V4  L8 + L9 + S2 + S1 + bias  (combined)

For each variant the script:
  1. Loads cached per-scene metadata + tide + phase (from Phase 0).
  2. Applies (V3, V4) the per-scene bias correction.
  3. Builds the DEM server-side via ``build_dem_gee``.
  4. Exports the multi-band DEM to local GeoTIFF.

Inputs
------
- ``data/raw/gee_metadata/<site>_scenes.parquet`` (S1 rows merged in Phase 0)
- ``data/processed/<site>_s1_phases.parquet`` (S1 tide + phase)
- Hourly KHOA cache for the site's primary station

Outputs
-------
- ``data/outputs/dem/<site>_v{1..4}.tif``
- ``data/outputs/tables/<site>_variant_diagnostics.csv``
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import ee
import numpy as np
import pandas as pd

from src.analysis.phase import (
    compute_phase_hw,
    find_tide_extremes,
)
from src.config import load_settings, load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.dem import (
    BETA_DEFAULT,
    SITE_AMPLITUDE_M,
    DemBuildSpec,
    apply_bias_correction,
    build_dem_gee,
)
from src.gee.exports import export_image_to_local, export_image_to_drive, wait_for_task
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("pilot_dem")

OPTICAL = ("L8", "L9", "S2")
ALL_SENSORS = OPTICAL + ("S1",)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site", required=True, help="Site id (e.g. garorim)")
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument(
        "--beta", type=float, default=BETA_DEFAULT,
        help="Bias-model slope (default 1.78 from manuscript pooled fit)",
    )
    p.add_argument(
        "--variants", nargs="*", default=["v1", "v2", "v3", "v4"],
        choices=["v1", "v2", "v3", "v4"],
    )
    p.add_argument(
        "--scale-m", type=int, default=30,
        help="Output DEM pixel size in metres (default 30, matches GLO-30)",
    )
    p.add_argument(
        "--cloud-max", type=float, default=60.0,
        help="Cloud cover threshold for optical (%%, default 60)",
    )
    p.add_argument(
        "--use-otsu", action="store_true",
        help="Compute global Otsu threshold from median composite (1 getInfo/sensor)",
    )
    p.add_argument(
        "--no-jrc", action="store_true",
        help="Disable JRC Global Surface Water intertidal mask",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_scenes_with_tides(
    site_id: str,
    start: str,
    end: str,
    gee_dir: Path,
    khoa_dir: Path,
    primary_station: str,
) -> pd.DataFrame:
    """Load the cached scene metadata and attach tide + phase columns.

    The Phase-0 diagnostic script saves S1 phases to
    ``data/processed/<site>_s1_phases.parquet``; for the optical sensors
    we re-attach tide/phase from KHOA in this function so that all four
    sensors share an identical processing path.
    """
    scenes_path = gee_dir / f"{site_id}_scenes.parquet"
    if not scenes_path.exists():
        raise FileNotFoundError(scenes_path)
    scenes = pd.read_parquet(scenes_path)
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)

    # Restrict to the analysis date range.
    mask = (scenes["datetime_utc"] >= pd.Timestamp(start, tz="UTC")) & (
        scenes["datetime_utc"] <= pd.Timestamp(end, tz="UTC")
    )
    scenes = scenes[mask].copy()
    log.info("Loaded %d scenes for %s (%s → %s)", len(scenes), site_id, start, end)

    # KHOA tides (cached).
    khoa = fetch_tide_hourly_range(
        primary_station,
        date.fromisoformat(start),
        date.fromisoformat(end),
        khoa_dir,
    )
    if khoa.empty:
        raise RuntimeError(
            f"No KHOA cache for {primary_station}; run Phase 0 with KHOA_API_KEY set"
        )

    scenes["tide_m"] = interpolate_at_times(khoa, scenes["datetime_utc"]).to_numpy()
    extremes = find_tide_extremes(khoa)
    scenes["phase_hw"] = compute_phase_hw(scenes["datetime_utc"], extremes.high_times)
    scenes["theta"] = 2 * np.pi * scenes["phase_hw"]
    scenes["cos_theta"] = np.cos(scenes["theta"])
    scenes["sin_theta"] = np.sin(scenes["theta"])
    scenes = scenes.dropna(subset=["tide_m", "cos_theta"]).reset_index(drop=True)
    log.info("After tide/phase attach: %d valid scenes", len(scenes))
    return scenes


# ---------------------------------------------------------------------------
# Variant builder
# ---------------------------------------------------------------------------

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
        sensors = OPTICAL
    elif variant in ("v2", "v4"):
        sensors = ALL_SENSORS
    else:
        raise ValueError(f"Unknown variant: {variant!r}")

    if variant in ("v1", "v2"):
        tide_col = "tide_m"
        scenes_used = scenes
    else:  # v3, v4: per-scene bias correction
        scenes_used = apply_bias_correction(scenes, site_id, beta=beta)
        tide_col = "tide_corrected_m"

    log.info(
        "variant=%s sensors=%s tide_col=%s",
        variant, list(sensors), tide_col,
    )
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


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites = {s.id: s for s in load_sites()}
    if args.site not in sites:
        raise SystemExit(f"Unknown site {args.site!r}; choices: {list(sites)}")
    site = sites[args.site]

    if site.id not in SITE_AMPLITUDE_M:
        raise SystemExit(f"No registered amplitude for {site.id}; edit src/gee/dem.py")

    gee_dir = resolve_path(settings["paths"]["gee_metadata"])
    khoa_dir = resolve_path(settings["paths"]["khoa"])
    dem_dir = resolve_path("data/outputs/dem")
    tables_dir = resolve_path(settings["paths"]["tables"])
    dem_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    log.info("Initialising Earth Engine (project=%s)", args.project)
    initialize(project=args.project)

    primary_station = site.khoa_stations[0].code
    scenes = _load_scenes_with_tides(
        site.id, args.start, args.end, gee_dir, khoa_dir, primary_station
    )

    # Log how many scenes per sensor we have.
    by_sensor = scenes.groupby("sensor").size().to_dict()
    log.info("Scenes by sensor: %s", by_sensor)

    geometry = ee.Geometry.Rectangle(site.bbox, proj="EPSG:4326", geodesic=False)

    diagnostics_all: list[pd.DataFrame] = []
    for variant in args.variants:
        log.info("=== Building %s_%s ===", site.id, variant)
        spec = _variant_spec(
            variant, site.id, geometry, scenes,
            start=args.start, end=args.end,
            beta=args.beta, cloud_max=args.cloud_max, scale_m=args.scale_m,
        )
        dem_image, diag = build_dem_gee(
            spec,
            use_otsu=args.use_otsu,
            return_diagnostics=True,
            apply_jrc_mask=not args.no_jrc,
        )
        diag["variant"] = variant
        diagnostics_all.append(diag)

        out_path = dem_dir / f"{site.id}_{variant}.tif"
        log.info("Exporting → %s", out_path)
        result = export_image_to_local(
            dem_image,
            region=geometry,
            scale_m=args.scale_m,
            out_path=out_path,
            overwrite=True,
        )
        if not result.ok:
            desc = f"{site.id}_{variant}"
            log.warning(
                "Local export failed (likely >48 MB); submitting Drive export: %s",
                desc,
            )
            task = export_image_to_drive(
                dem_image, region=geometry, scale_m=args.scale_m, description=desc,
            )
            state = wait_for_task(task)
            if state == "COMPLETED":
                log.info("Drive export COMPLETED for %s (download from Drive)", desc)
            else:
                log.error("Drive export %s for %s", state, desc)
        else:
            log.info("Exported %.1f MB", result.n_bytes / 1e6)

    diag_df = pd.concat(diagnostics_all, ignore_index=True)
    diag_path = tables_dir / f"{site.id}_variant_diagnostics.csv"
    diag_df.to_csv(diag_path, index=False, float_format="%.4f")
    log.info("Wrote diagnostics → %s", diag_path)

    log.info("Per-variant scene counts:")
    print(
        diag_df.groupby(["variant", "sensor"])
        .agg(n_scenes=("scene_id", "count"), mean_tide=("tide_m", "mean"))
        .to_string()
    )


if __name__ == "__main__":
    main()
