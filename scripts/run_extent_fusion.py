"""Compute LAT/HAT, DEM-based area, and 3-tier fused extent per site x year.

Inputs (from Phase 1a-c):
  - data/outputs/dem/annual/<site>_v4_<year>.tif      (annual V4 DEM)
  - data/outputs/extent/<site>_msic_<year>.tif        (MSIC-OA binary)
  - data/outputs/extent/<site>_qa_<year>.tif          (4-band QA raster)

Outputs:
  - data/outputs/extent/<site>_fused_<year>.tif        (uint8 tier raster)
  - data/outputs/tables/annual_area_5sites.csv         (per-site, per-year:
        area_dem_km2, tier1/2/3_km2, total_km2, z_lat, z_hat)
  - data/outputs/tables/tidal_flat_bounds.csv          (LAT/HAT per site)

Usage:
    python scripts/run_extent_fusion.py --start-year 2016 --end-year 2024
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from src.analysis.extent import (
    IF_HI,
    IF_LO,
    compute_dem_area,
    compute_tidal_flat_bounds,
    fuse_extent,
)
from src.config import load_sites, resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("extent_fusion")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument("--sites", nargs="*", default=None)
    p.add_argument(
        "--model-dir",
        default=None,
        help="FES model directory (default: data/raw/fes2014).",
    )
    p.add_argument("--model-name", default="FES2014")
    p.add_argument(
        "--reference-years",
        type=int,
        default=5,
        help="Years of reference series for LAT/HAT (default 5).",
    )
    p.add_argument("--min-n-obs", type=int, default=5)
    p.add_argument(
        "--dem-suffix", default="v4",
        help="DEM filename stem (e.g. 'v4' or 'v5nojrc').",
    )
    p.add_argument(
        "--out-suffix", default="",
        help="Suffix appended to the output CSV stem "
             "(e.g. '_recover_nojrc' -> annual_area_5sites_recover_nojrc.csv). "
             "Empty overwrites the canonical annual_area_5sites.csv.",
    )
    p.add_argument(
        "--if-lo", type=float, default=IF_LO,
        help="Inundation-frequency lower gate; <0 disables the IF gate.",
    )
    p.add_argument("--if-hi", type=float, default=IF_HI)
    return p.parse_args()


def _datum_offset_for_site(site_id: str) -> float:
    """Read the IFM-RF datum offset (m) from the manuscript-2 artefact."""
    candidates = [
        resolve_path(f"data/processed/{site_id}_ifm_rf_v3khoa.json"),
        resolve_path(f"data/processed/{site_id}_ifm_rf.json"),
        resolve_path(f"data/processed/{site_id}_ifm_slm.json"),
    ]
    for c in candidates:
        if c.exists():
            with open(c) as f:
                data = json.load(f)
            offset = data.get("datum_offset_m")
            if offset is not None:
                log.info("  datum offset (from %s): %.3f m", c.name, offset)
                return float(offset)
    log.warning("No IFM datum offset for %s — using 0.0 m", site_id)
    return 0.0


def main() -> None:
    args = parse_args()
    sites_all = {s.id: s for s in load_sites()}
    site_ids = args.sites or list(sites_all.keys())

    if args.model_dir is None:
        for candidate in (
            "data/raw/fes2022b/ocean_tide_extrapolated",
            "data/raw/fes2014/ocean_tide_extrapolated",
            "data/raw/fes2014",
        ):
            p = resolve_path(candidate)
            if p.exists():
                model_dir = p
                break
        else:
            raise SystemExit("No FES model directory found under data/raw/")
    else:
        model_dir = Path(args.model_dir)
    log.info("Using tide model %s in %s", args.model_name, model_dir)

    extent_dir = resolve_path("data/outputs/extent")
    dem_dir = resolve_path("data/outputs/dem/annual")
    tables_dir = resolve_path("data/outputs/tables")
    extent_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    # 1. Compute LAT/HAT bounds per site (single reference period spanning study window).
    ref_start = pd.Timestamp(f"{args.start_year - 1}-01-01", tz="UTC")
    ref_end = pd.Timestamp(f"{args.start_year - 1 + args.reference_years}-12-31", tz="UTC")
    log.info("Reference period for LAT/HAT: %s .. %s", ref_start.date(), ref_end.date())

    bounds_rows: list[dict] = []
    bounds_by_site: dict = {}
    for site_id in site_ids:
        if site_id not in sites_all:
            log.warning("Unknown site %s", site_id)
            continue
        site = sites_all[site_id]
        datum = _datum_offset_for_site(site_id)
        try:
            b = compute_tidal_flat_bounds(
                lon=site.lon, lat=site.lat, site_id=site_id,
                reference_start=ref_start, reference_end=ref_end,
                model_directory=model_dir,
                model_name=args.model_name,
                datum_offset_m=datum,
                bounds=list(site.bbox),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("LAT/HAT failed for %s: %s", site_id, exc)
            continue
        bounds_by_site[site_id] = b
        bounds_rows.append({
            "site_id": site_id,
            "z_lat_m": b.z_lat_m,
            "z_hat_m": b.z_hat_m,
            "datum_offset_m": b.datum_offset_m,
            "n_reference": b.n_reference,
            "ref_start": b.reference_period[0],
            "ref_end": b.reference_period[1],
        })

    pd.DataFrame(bounds_rows).to_csv(
        tables_dir / "tidal_flat_bounds.csv", index=False, float_format="%.3f"
    )
    log.info("Wrote tidal_flat_bounds.csv (%d sites)", len(bounds_rows))

    # 2. Per-(site, year) fusion + area.
    area_rows: list[dict] = []
    for site_id, b in bounds_by_site.items():
        for year in range(args.start_year, args.end_year + 1):
            dem_path = dem_dir / f"{site_id}_{args.dem_suffix}_{year}.tif"
            msic_path = extent_dir / f"{site_id}_msic_{year}.tif"
            qa_path = extent_dir / f"{site_id}_qa_{year}.tif"
            fused_path = extent_dir / f"{site_id}_fused_{year}.tif"

            if not dem_path.exists():
                log.warning("  missing DEM %s — skip", dem_path.name)
                continue

            if_lo = args.if_lo if args.if_lo is not None and args.if_lo >= 0 else None
            if_hi = args.if_hi if if_lo is not None else None
            try:
                dem_area = compute_dem_area(
                    dem_path, b, year=year, min_n_obs=args.min_n_obs,
                    if_lo=if_lo, if_hi=if_hi,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("compute_dem_area failed: %s", exc)
                continue

            row = {
                "site_id": site_id,
                "year": year,
                "area_dem_km2": dem_area.area_dem_km2,
                "n_valid_dem_pixels": dem_area.n_valid_pixels,
                "z_lat_m": dem_area.z_lat_m,
                "z_hat_m": dem_area.z_hat_m,
                "dem_min_m": dem_area.dem_min_m,
                "dem_max_m": dem_area.dem_max_m,
                "tier1_km2": float("nan"),
                "tier2_km2": float("nan"),
                "tier3_km2": float("nan"),
                "total_km2": float("nan"),
            }

            if msic_path.exists():
                try:
                    fused = fuse_extent(
                        dem_path=dem_path,
                        msic_path=msic_path,
                        qa_path=qa_path,
                        bounds=b,
                        site_id=site_id,
                        year=year,
                        out_path=fused_path,
                        min_n_obs=args.min_n_obs,
                    )
                    row.update({
                        "tier1_km2": fused.tier1_km2,
                        "tier2_km2": fused.tier2_km2,
                        "tier3_km2": fused.tier3_km2,
                        "total_km2": fused.total_km2,
                    })
                except Exception as exc:  # noqa: BLE001
                    log.exception("fuse_extent failed: %s", exc)
            else:
                log.warning("  no MSIC raster %s — DEM area only", msic_path.name)
            area_rows.append(row)

    df = pd.DataFrame(area_rows)
    out = tables_dir / f"annual_area_5sites{args.out_suffix}.csv"
    df.to_csv(out, index=False, float_format="%.4f")
    log.info("Wrote %s (%d rows)", out, len(df))
    if not df.empty:
        print(
            df.groupby("site_id")[["area_dem_km2", "total_km2"]]
            .agg(["mean", "min", "max", "count"])
            .to_string()
        )


if __name__ == "__main__":
    main()
