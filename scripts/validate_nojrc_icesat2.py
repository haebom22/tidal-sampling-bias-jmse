"""Independent ICESat-2 validation of the JRC-free (v5nojrc) recovered DEMs.

Purpose
-------
Section 3.1/3.4 of manuscript-3 argues that removing the external JRC GSW
occurrence mask recovers genuine intertidal pixels at the two turbid pilot
sites (Ganghwa, Hampyeong) that the masked V4 product discards. This script
tests, against an *independent* reference (ICESat-2 ATL06 exposed-ground
segments), whether those recovered pixels are real intertidal surface or
noise: it compares the elevation accuracy (RMSE / bias / std / R^2) of the
JRC-masked annual V4 DEM and the JRC-free annual v5nojrc DEM at the same
ICESat-2 locations.

The per-site WGS84(ICESat-2) -> KHOA-datum(DEM) offset is estimated once from
the published composite V1 DEM and applied consistently to every annual DEM so
that the bias term is comparable across variants and years.

Outputs
-------
- data/outputs/tables/icesat2_validation_nojrc.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import rasterio  # noqa: F401 — import early to avoid pyarrow conflict

from src.analysis.validate_icesat2 import validate_dem_vs_icesat2
from src.config import resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("validate_nojrc")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sites", nargs="*", default=["ganghwa", "hampyeong"])
    p.add_argument("--variants", nargs="*", default=["v4", "v5nojrc"])
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2024)
    return p.parse_args()


def _site_datum_offset(site_id: str, dem_dir: Path, icesat2_path: Path) -> float | None:
    """Estimate the per-site datum offset from the composite V1 DEM."""
    comp_v1 = dem_dir / f"{site_id}_v1.tif"
    if not comp_v1.exists():
        log.warning("No composite V1 for %s — offset will be per-DEM median.", site_id)
        return None
    out = validate_dem_vs_icesat2(
        comp_v1, icesat2_path, site_id, "v1_offset_probe", datum_offset=None,
    )
    if out is None:
        return None
    _, offset = out
    return offset


def main() -> None:
    args = parse_args()
    dem_dir = resolve_path("data/outputs/dem")
    annual_dir = resolve_path("data/outputs/dem/annual")
    icesat2_dir = resolve_path("data/processed")
    tables_dir = resolve_path("data/outputs/tables")
    tables_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for site_id in args.sites:
        icesat2_path = icesat2_dir / f"{site_id}_icesat2_exposed.parquet"
        offset = _site_datum_offset(site_id, dem_dir, icesat2_path)
        log.info("Site %s: fixed datum offset = %s",
                 site_id, f"{offset:.3f} m" if offset is not None else "per-DEM median")

        for variant in args.variants:
            for year in range(args.start_year, args.end_year + 1):
                dem_path = annual_dir / f"{site_id}_{variant}_{year}.tif"
                if not dem_path.exists():
                    continue
                out = validate_dem_vs_icesat2(
                    dem_path, icesat2_path, site_id, f"{variant}_{year}",
                    datum_offset=offset,
                )
                if out is None:
                    rows.append({
                        "site_id": site_id, "variant": variant, "year": year,
                        "n_points": 0, "rmse_m": None, "bias_m": None,
                        "std_m": None, "r_squared": None,
                    })
                    continue
                r, _ = out
                rows.append({
                    "site_id": site_id, "variant": variant, "year": year,
                    "n_points": r.n_points, "rmse_m": r.rmse_m,
                    "mae_m": r.mae_m, "bias_m": r.bias_m,
                    "std_m": r.std_m, "r_squared": r.r_squared,
                })

    df = pd.DataFrame(rows)
    out_path = tables_dir / "icesat2_validation_nojrc.csv"
    df.to_csv(out_path, index=False, float_format="%.4f")
    log.info("Wrote %s (%d rows)", out_path, len(df))

    print("\n" + "=" * 78)
    print("ICESat-2 validation: JRC-masked V4 vs JRC-free v5nojrc (annual)")
    print("=" * 78)
    ok = df[df["n_points"] > 0]
    if not ok.empty:
        summ = (ok.groupby(["site_id", "variant"])
                  .agg(years=("year", "count"),
                       n_pts_mean=("n_points", "mean"),
                       rmse_mean=("rmse_m", "mean"),
                       bias_mean=("bias_m", "mean"),
                       std_mean=("std_m", "mean"))
                  .reset_index())
        print(summ.to_string(index=False, float_format="%.3f"))
        print("\nPer-year detail:")
        print(ok[["site_id", "variant", "year", "n_points", "rmse_m",
                  "bias_m", "std_m"]].to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
