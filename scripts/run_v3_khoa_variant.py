"""Generate V3-KHOA DEMs using observed KHOA M2 amplitudes.

This script reproduces the V3 (a-priori bias correction) variant but
substitutes the site-specific tidal amplitude ``A`` in
``η_corr = η - β · A · cos θ`` with the harmonic-analysis M2 amplitude
derived from KHOA observations (``data/outputs/tables/harmonic_decomposition_constituents.csv``)
instead of the HW/LW half-range used by the original V3.

Rationale
---------
The original V3 used ``A = (HW − LW)/2`` averaged over 2020-2024, which
includes contributions from M2, S2, K1, O1, and M4. Because the bias model
``β · A · cos θ`` aligns ``cos θ`` with the M2 phase specifically, using the
broader HW/LW range over-estimates the M2 component and therefore over-applies
the correction at sites with significant semi-diurnal mixing (Ganghwa, Gomso).
Using the harmonic-analysis M2 amplitude isolates the matching constituent and
should reduce over-correction inside semi-enclosed bays.

Outputs
-------
- ``data/outputs/dem/<site>_v3khoa.tif``
- ``data/outputs/tables/<site>_v3khoa_diagnostics.csv``
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

import ee
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.phase import compute_phase_hw, find_tide_extremes  # noqa: E402
from src.config import load_settings, load_sites, resolve_path  # noqa: E402
from src.gee.auth import initialize  # noqa: E402
from src.gee.dem import (  # noqa: E402
    BETA_DEFAULT,
    DemBuildSpec,
    apply_bias_correction,
    build_dem_gee,
)
from src.gee.exports import export_image_to_local, export_image_to_drive, wait_for_task  # noqa: E402
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("v3_khoa")

OPTICAL = ("L8", "L9", "S2")

SITES_ORDER = ["suncheon", "hampyeong", "garorim", "gomso", "ganghwa"]

START = "2020-01-01"
END = "2024-12-31"
SCALE_M = 30
CLOUD_MAX = 60.0


def load_khoa_m2_amplitudes() -> dict[str, float]:
    csv_path = ROOT / "data" / "outputs" / "tables" / "harmonic_decomposition_constituents.csv"
    df = pd.read_csv(csv_path)
    amps = dict(zip(df["site_id"], df["amp_M2_m"]))
    log.info("Loaded KHOA M2 amplitudes: %s", {k: round(v, 3) for k, v in amps.items()})
    return amps


def _load_scenes(site, settings) -> pd.DataFrame:
    gee_dir = resolve_path(settings["paths"]["gee_metadata"])
    khoa_dir = resolve_path(settings["paths"]["khoa"])
    primary_station = site.khoa_stations[0].code

    scenes = pd.read_parquet(gee_dir / f"{site.id}_scenes.parquet")
    scenes["datetime_utc"] = pd.to_datetime(scenes["datetime_utc"], utc=True)
    mask = (scenes["datetime_utc"] >= pd.Timestamp(START, tz="UTC")) & (
        scenes["datetime_utc"] <= pd.Timestamp(END, tz="UTC")
    )
    scenes = scenes[mask].copy()

    khoa = fetch_tide_hourly_range(
        primary_station, date.fromisoformat(START), date.fromisoformat(END), khoa_dir,
    )
    if khoa.empty:
        raise RuntimeError(f"No KHOA cache for {primary_station}")

    scenes["tide_m"] = interpolate_at_times(khoa, scenes["datetime_utc"]).to_numpy()
    extremes = find_tide_extremes(khoa)
    scenes["phase_hw"] = compute_phase_hw(scenes["datetime_utc"], extremes.high_times)
    scenes["theta"] = 2 * np.pi * scenes["phase_hw"]
    scenes["cos_theta"] = np.cos(scenes["theta"])
    scenes["sin_theta"] = np.sin(scenes["theta"])
    scenes = scenes.dropna(subset=["tide_m", "cos_theta"]).reset_index(drop=True)
    log.info("[%s] %d valid scenes", site.id, len(scenes))
    return scenes


def build_one(site, scenes, amplitude_m, dem_dir, tables_dir) -> None:
    geometry = ee.Geometry.Rectangle(site.bbox, proj="EPSG:4326", geodesic=False)

    log.info("=== Building %s_v3khoa with A=%.3f m (KHOA M2) ===", site.id, amplitude_m)
    scenes_used = apply_bias_correction(
        scenes, site.id, beta=BETA_DEFAULT, amplitude_m=amplitude_m,
    )
    spec = DemBuildSpec(
        site_id=site.id,
        geometry=geometry,
        sensors=OPTICAL,
        scenes=scenes_used,
        tide_col="tide_corrected_m",
        start=START,
        end=END,
        cloud_max=CLOUD_MAX,
        output_scale_m=SCALE_M,
    )

    dem_image, diag = build_dem_gee(
        spec,
        use_otsu=True,
        return_diagnostics=True,
        apply_jrc_mask=True,
    )
    diag["variant"] = "v3khoa"
    diag["amplitude_m"] = amplitude_m
    diag_path = tables_dir / f"{site.id}_v3khoa_diagnostics.csv"
    diag.to_csv(diag_path, index=False, float_format="%.4f")
    log.info("Diagnostics → %s (%d rows)", diag_path, len(diag))

    out_path = dem_dir / f"{site.id}_v3khoa.tif"
    log.info("Exporting → %s", out_path)
    result = export_image_to_local(
        dem_image, region=geometry, scale_m=SCALE_M, out_path=out_path, overwrite=True,
    )
    if not result.ok:
        desc = f"{site.id}_v3khoa"
        log.warning("Local export failed; submitting Drive export (non-blocking): %s", desc)
        task = export_image_to_drive(
            dem_image, region=geometry, scale_m=SCALE_M, description=desc,
        )
        log.info("Drive task submitted: %s (id=%s); will not block", desc, task.id)
    else:
        log.info("Exported %.1f MB", result.n_bytes / 1e6)


def main() -> None:
    settings = load_settings()
    sites = {s.id: s for s in load_sites()}
    amps = load_khoa_m2_amplitudes()

    dem_dir = resolve_path("data/outputs/dem")
    tables_dir = resolve_path(settings["paths"]["tables"])
    dem_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    initialize(project=None)

    for sid in SITES_ORDER:
        if sid not in sites:
            log.warning("Site %s not in registry, skipping", sid)
            continue
        if sid not in amps:
            log.warning("No KHOA M2 amp for %s, skipping", sid)
            continue
        scenes = _load_scenes(sites[sid], settings)
        try:
            build_one(sites[sid], scenes, amps[sid], dem_dir, tables_dir)
        except Exception as e:
            log.error("[%s] failed: %s", sid, e, exc_info=True)


if __name__ == "__main__":
    main()
