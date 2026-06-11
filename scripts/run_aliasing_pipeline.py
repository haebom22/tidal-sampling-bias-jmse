"""End-to-end pipeline: GEE metadata -> tide computation -> aliasing stats.

This is the headline script that produces the paper-ready outputs.
Each stage caches its output, so the script can be safely re-run.

Required environment / inputs:

    EE_PROJECT          your Earth Engine Cloud project id
    FES2014 NetCDF      under data/raw/fes2014/ocean_tide/
                        (optional: ocean_tide_extrapolated/ for coasts)
    KHOA_API_KEY        for KHOA validation (only needed if --validate-khoa)

Outputs:

    data/processed/<site>_scenes_with_tide.parquet
    data/processed/reference_<site>.parquet
    data/outputs/tables/aliasing_stats.csv
    data/outputs/figures/*.png
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from src.analysis.aliasing import stats_table
from src.config import load_settings, load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.metadata import SENSOR_SPECS, extract_site_metadata, save_metadata
from src.tides.fes2014 import compute_tide_heights, synthetic_reference_series
from src.visualization.plots import (
    plot_spread_offset,
    plot_temporal_evolution,
    plot_tide_distribution,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("aliasing_pipeline")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument("--sites", nargs="*", default=None)
    p.add_argument(
        "--sensors",
        nargs="*",
        default=list(SENSOR_SPECS.keys()),
        choices=list(SENSOR_SPECS.keys()),
    )
    p.add_argument("--skip-gee", action="store_true", help="Reuse cached metadata")
    p.add_argument("--skip-tides", action="store_true", help="Reuse cached tides")
    p.add_argument(
        "--reference-years",
        type=int,
        default=None,
        help="Override reference synthetic span (years)",
    )
    return p.parse_args()


def stage_metadata(sites, sensors, start, end, out_dir: Path, skip: bool, project: str | None):
    if not skip:
        initialize(project=project)
    for site in sites:
        target = out_dir / f"{site.id}_scenes.parquet"
        if skip and target.exists():
            log.info("Reuse metadata: %s", target)
            continue
        df = extract_site_metadata(site, sensors, start, end)
        if df.empty:
            log.warning("No scenes for %s", site.id)
            continue
        save_metadata(df, out_dir, site.id)


def stage_tides(sites, gee_dir: Path, fes_dir: Path, processed_dir: Path, ref_cfg: dict, skip: bool):
    for site in sites:
        scenes_path = gee_dir / f"{site.id}_scenes.parquet"
        if not scenes_path.exists():
            log.warning("Missing metadata for %s, skipping", site.id)
            continue
        out_scenes = processed_dir / f"{site.id}_scenes_with_tide.parquet"
        out_ref = processed_dir / f"{site.id}_reference.parquet"

        scenes = pd.read_parquet(scenes_path)
        if skip and out_scenes.exists() and out_ref.exists():
            log.info("Reuse tides: %s", site.id)
            continue

        log.info("FES2014 at scene times: %s (n=%d)", site.id, len(scenes))
        scenes["tide_m"] = compute_tide_heights(
            lon=site.lon,
            lat=site.lat,
            times=scenes["datetime_utc"],
            model_directory=fes_dir,
        )
        scenes.to_parquet(out_scenes, index=False)

        years = ref_cfg["years"]
        start_ref = scenes["datetime_utc"].min()
        if pd.isna(start_ref):
            continue
        end_ref = start_ref + pd.Timedelta(days=int(365.25 * years))
        log.info("Reference series: %s (%s -> %s, %d-min)", site.id, start_ref, end_ref, ref_cfg["sampling_minutes"])
        ref = synthetic_reference_series(
            lon=site.lon,
            lat=site.lat,
            start=start_ref,
            end=end_ref,
            sampling_minutes=ref_cfg["sampling_minutes"],
            model_directory=fes_dir,
        )
        ref.to_parquet(out_ref, index=False)


def stage_stats(sites, processed_dir: Path, figs_dir: Path, tables_dir: Path, n_bins: int):
    all_scenes = []
    references = {}
    for site in sites:
        sp = processed_dir / f"{site.id}_scenes_with_tide.parquet"
        rp = processed_dir / f"{site.id}_reference.parquet"
        if not (sp.exists() and rp.exists()):
            continue
        scenes = pd.read_parquet(sp)
        ref = pd.read_parquet(rp)
        scenes["site_name"] = site.name_en
        all_scenes.append(scenes)
        references[site.id] = ref["tide_m"].to_numpy()

        plot_tide_distribution(
            scenes, references[site.id], site.name_en,
            out_path=figs_dir / f"distribution_{site.id}.png", bins=n_bins,
        )
        plot_temporal_evolution(
            scenes, site.name_en, out_path=figs_dir / f"temporal_{site.id}.png",
        )

    if not all_scenes:
        log.warning("No data to summarise.")
        return
    combined = pd.concat(all_scenes, ignore_index=True)
    stats = stats_table(combined, references, groupby=["site_id", "sensor"], n_bins=n_bins)
    tables_dir.mkdir(parents=True, exist_ok=True)
    stats.to_csv(tables_dir / "aliasing_stats.csv", index=False)
    log.info("Wrote %d stat rows.", len(stats))
    plot_spread_offset(stats, out_path=figs_dir / "spread_offsets.png")


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites = load_sites()
    if args.sites:
        sites = [s for s in sites if s.id in args.sites]

    gee_dir = resolve_path(settings["paths"]["gee_metadata"])
    fes_dir = resolve_path(settings["paths"]["fes2014"])
    processed_dir = resolve_path(settings["paths"]["processed"])
    figs_dir = resolve_path(settings["paths"]["figures"])
    tables_dir = resolve_path(settings["paths"]["tables"])

    ref_cfg = dict(settings["aliasing"]["reference_synthetic"])
    if args.reference_years:
        ref_cfg["years"] = args.reference_years

    stage_metadata(
        sites, args.sensors,
        settings["time_period"]["start"], settings["time_period"]["end"],
        gee_dir, skip=args.skip_gee, project=args.project,
    )
    stage_tides(sites, gee_dir, fes_dir, processed_dir, ref_cfg, skip=args.skip_tides)
    stage_stats(sites, processed_dir, figs_dir, tables_dir, settings["aliasing"]["histogram_bins"])


if __name__ == "__main__":
    main()
