"""Extract Landsat and Sentinel-2 scene metadata for all study sites.

Usage:

    python -m scripts.run_metadata_extraction \
        --project YOUR_EE_CLOUD_PROJECT \
        [--sites ganghwa garorim ...] \
        [--sensors L5 L7 L8 L9 S2]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.config import load_settings, load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.metadata import SENSOR_SPECS, extract_site_metadata, save_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("metadata_extraction")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=str, default=None, help="EE Cloud project id")
    parser.add_argument("--sites", nargs="*", default=None, help="Subset of site ids")
    parser.add_argument(
        "--sensors",
        nargs="*",
        default=list(SENSOR_SPECS.keys()),
        choices=list(SENSOR_SPECS.keys()),
        help="Sensors to query",
    )
    parser.add_argument("--start", type=str, default=None, help="Override start date")
    parser.add_argument("--end", type=str, default=None, help="Override end date")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites = load_sites()

    if args.sites:
        sites = [s for s in sites if s.id in args.sites]
    if not sites:
        raise SystemExit("No sites matched.")

    start = args.start or settings["time_period"]["start"]
    end = args.end or settings["time_period"]["end"]
    out_dir = resolve_path(settings["paths"]["gee_metadata"])

    initialize(project=args.project)

    for site in sites:
        log.info("=== Site: %s (%s) ===", site.id, site.name_en)
        df = extract_site_metadata(site, args.sensors, start, end)
        if df.empty:
            log.warning("No scenes found for %s", site.id)
            continue
        out_path = save_metadata(df, Path(out_dir), site.id)
        log.info("Saved %d scenes -> %s", len(df), out_path)


if __name__ == "__main__":
    main()
