"""Run Jia MSIC-OA tidal-flat mapping for the 5 pilot sites x N years.

Produces:
  - data/outputs/extent/<site>_msic_<year>.tif   (binary tidal_flat band + mndwi_range)
  - data/outputs/tables/msic_oa_areas.csv         (per-site, per-year area_km2)

Usage
-----
    # Always call the venv interpreter explicitly. A shell-level
    # `alias python=...` (common in zsh) outranks `source .venv/bin/activate`,
    # which is why ``python scripts/...`` may silently pick up the system
    # interpreter and fail with ``ModuleNotFoundError: No module named 'ee'``.
    EE_PROJECT=<project> .venv/bin/python scripts/run_msic_oa.py \
        --start-year 2016 --end-year 2024 --rolling 3

The ``--rolling`` option uses an N-year window centred on each year (DEA
Intertidal convention) to stabilise the MSIC composites — Jia (2021) uses
a single-year window for China, but Korean tidal flats have ~50% Yellow
Sea cloud coverage so we default to a 3-year rolling window.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import ee
import pandas as pd

from src.config import load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.exports import export_image_to_local, export_image_to_drive, wait_for_task
from src.gee.msic_oa import build_msic_oa_extent, msic_area_km2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("msic_oa")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default=None, help="EE Cloud project id")
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument(
        "--rolling",
        type=int,
        default=3,
        help="Window size in years centred on each year (default 3).",
    )
    p.add_argument(
        "--sites",
        nargs="*",
        default=None,
        help="Subset of site ids (default: all 5).",
    )
    p.add_argument(
        "--sensors",
        nargs="*",
        default=["L8", "L9", "S2"],
        choices=["L8", "L9", "S2"],
    )
    p.add_argument("--cloud-max", type=float, default=60.0)
    p.add_argument("--scale-m", type=int, default=10)
    p.add_argument(
        "--export-mode",
        choices=["local", "drive", "none"],
        default="local",
        help="GeoTIFF export mode (none = skip export, compute areas only).",
    )
    return p.parse_args()


def _window_dates(year: int, rolling: int) -> tuple[str, str]:
    half = rolling // 2
    start = f"{max(2015, year - half)}-01-01"
    end = f"{year + half}-12-31"
    return start, end


def main() -> None:
    args = parse_args()
    initialize(project=args.project)

    sites_all = {s.id: s for s in load_sites()}
    site_ids = args.sites or list(sites_all.keys())
    extent_dir = resolve_path("data/outputs/extent")
    tables_dir = resolve_path("data/outputs/tables")
    extent_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Resume support: pre-load previously checkpointed rows.
    out_csv = tables_dir / "msic_oa_areas.csv"
    rows: list[dict] = []
    done: set[tuple[str, int]] = set()
    if out_csv.exists():
        try:
            prev = pd.read_csv(out_csv)
            rows = prev.to_dict("records")
            done = {(str(r["site_id"]), int(r["year"])) for r in rows}
            log.info("Resume: %d existing (site, year) rows in %s", len(done), out_csv.name)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load %s (%s) — starting fresh.", out_csv, exc)

    for site_id in site_ids:
        if site_id not in sites_all:
            log.warning("Unknown site %s — skip", site_id)
            continue
        site = sites_all[site_id]
        geometry = ee.Geometry.Rectangle(site.bbox, proj="EPSG:4326", geodesic=False)
        for year in range(args.start_year, args.end_year + 1):
            if (site_id, year) in done:
                log.info("[skip] %s %s already in checkpoint CSV", site_id, year)
                continue
            start, end = _window_dates(year, args.rolling)
            log.info("=== %s %s (window %s..%s) ===", site_id, year, start, end)
            try:
                result = build_msic_oa_extent(
                    geometry=geometry,
                    start=start,
                    end=end,
                    cloud_max=args.cloud_max,
                    sensors=tuple(args.sensors),
                )
            except RuntimeError as exc:
                log.warning("  skip (%s)", exc)
                continue
            except Exception as exc:  # noqa: BLE001
                # MSIC builder hit a GEE-side error (timeout etc.).
                # Skip this site/year rather than killing the pipeline; the
                # next call to the pipeline will retry from the checkpoint.
                log.warning("  build_msic_oa_extent failed (%s) — skipping.", exc)
                continue

            try:
                area_km2 = msic_area_km2(result.image, geometry, scale_m=args.scale_m)
            except Exception as exc:  # noqa: BLE001
                # msic_area_km2 already auto-rescales on timeouts; any
                # exception that escapes is unrecoverable for this row.
                log.warning("  msic_area_km2 failed (%s) — area=nan.", exc)
                area_km2 = float("nan")
            log.info("  area = %.2f km^2 (n_scenes=%d)", area_km2, result.n_scenes)

            rows.append({
                "site_id": site_id,
                "year": year,
                "window_start": start,
                "window_end": end,
                "n_scenes": result.n_scenes,
                "tau_max": result.tau_max,
                "tau_min": result.tau_min,
                "tau_range": result.tau_range,
                "area_km2_msic": area_km2,
            })

            # Checkpoint after every site/year so a long run never loses
            # all areas to a single failure or Ctrl-C.
            pd.DataFrame(rows).to_csv(
                tables_dir / "msic_oa_areas.csv",
                index=False,
                float_format="%.4f",
            )

            if args.export_mode == "none":
                continue
            out_path = extent_dir / f"{site_id}_msic_{year}.tif"
            try:
                if args.export_mode == "local":
                    export_image_to_local(
                        result.image, region=geometry, scale_m=args.scale_m,
                        out_path=out_path, overwrite=False,
                    )
                else:
                    task = export_image_to_drive(
                        result.image, region=geometry, scale_m=args.scale_m,
                        description=f"{site_id}_msic_{year}",
                    )
                    wait_for_task(task)
            except Exception as exc:  # noqa: BLE001
                # Area is already persisted to CSV; raster is optional for
                # downstream fusion (extent.py also works DEM-only).
                log.warning("  raster export failed (%s) — area row kept.", exc)

    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(out_csv, index=False, float_format="%.4f")
        log.info("Wrote %s (%d rows)", out_csv, len(df))
        print(df.groupby("site_id")["area_km2_msic"].describe().to_string())
    else:
        log.warning("No areas computed.")


if __name__ == "__main__":
    main()
