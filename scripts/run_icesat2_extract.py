"""Extract ICESat-2 ATL06-SR ground segments for all study sites.

Uses SlideRule Earth (slideruleearth.io) for server-side processing.
For each site:
  1. Query ATL06-SR (20 m segments) via SlideRule
  2. Attach interpolated KHOA tide at overpass time
  3. Filter to exposed-only segments (above tide)
  4. Save as GeoParquet

Outputs: data/processed/<site>_icesat2_exposed.parquet
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from src.analysis.icesat2 import extract_site_photons
from src.config import load_settings, load_sites, resolve_path
from src.tides.khoa import fetch_tide_hourly_range

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("icesat2_extract")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sites", nargs="*",
        default=["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"],
    )
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default="2025-12-31")
    return p.parse_args()


def main():
    args = parse_args()
    settings = load_settings()
    sites = {s.id: s for s in load_sites()}
    khoa_dir = resolve_path(settings["paths"]["khoa"])
    out_dir = resolve_path("data/processed")

    for site_id in args.sites:
        if site_id not in sites:
            log.warning("Unknown site %s, skipping", site_id)
            continue
        site = sites[site_id]
        log.info("=== %s (%s) ===", site_id, site.name_en)

        station_code = site.khoa_stations[0].code
        khoa = fetch_tide_hourly_range(
            station_code,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            khoa_dir,
        )
        if khoa.empty:
            log.error("No KHOA data for %s (%s); skipping", site_id, station_code)
            continue

        try:
            gdf = extract_site_photons(
                site_id=site_id,
                bbox=site.bbox,
                khoa_hourly=khoa,
                start_date=args.start,
                end_date=args.end,
                out_dir=out_dir,
            )
            log.info("  %s: %d exposed segments", site_id, len(gdf))
        except Exception as exc:
            log.error("Failed for %s: %s", site_id, exc)
            continue


if __name__ == "__main__":
    main()
