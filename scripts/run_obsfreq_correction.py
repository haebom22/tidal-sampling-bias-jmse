"""Apply observation-frequency bias correction to the annual area time series.

Reads:
  - data/outputs/tables/annual_area_5sites.csv        (this project: A_DEM, total_km2)
  - data/outputs/tables/annual_v4_dem_summary.csv     (per (site, year) n_obs)
  - data/processed/reference_extents.parquet          (Murray, GWL_FCS30 for comparison)

Writes:
  - data/outputs/tables/annual_area_5sites_corrected.csv
  - data/outputs/tables/obsfreq_fit_summary.csv

For each site we fit ``A_t = γ_0 + γ_1 · N_t`` and produce a corrected
area column. The same correction is applied (when comparable scene
counts are available) to the reference datasets for the §3 cross-site
comparison.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from src.analysis.obsfreq_correction import correct_all_sites
from src.config import resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("obsfreq")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--area-col",
        default="total_km2",
        help="Area column to correct (total_km2 | area_dem_km2 | tier1_km2).",
    )
    p.add_argument("--n-boot", type=int, default=2000)
    p.add_argument("--alpha", type=float, default=0.05)
    return p.parse_args()


def _attach_n_scenes(area_df: pd.DataFrame) -> pd.DataFrame:
    summary_path = resolve_path("data/outputs/tables/annual_v4_dem_summary.csv")
    if not summary_path.exists():
        log.warning("No DEM summary at %s — using n_scenes=1", summary_path)
        out = area_df.copy()
        out["n_scenes"] = 1
        return out
    summary = pd.read_csv(summary_path)
    # Total per (site, year) across all sensors.
    sensor_cols = [c for c in summary.columns if c.startswith("n_") and c != "n_total_scenes"]
    if not sensor_cols and "n_total_scenes" in summary.columns:
        summary["n_scenes"] = summary["n_total_scenes"]
    else:
        summary["n_scenes"] = summary[sensor_cols].sum(axis=1).astype(int)
    merge_cols = ["site_id", "year"]
    return area_df.merge(
        summary[merge_cols + ["n_scenes"]],
        on=merge_cols, how="left", validate="many_to_one",
    )


def main() -> None:
    args = parse_args()
    tables_dir = resolve_path("data/outputs/tables")
    area_path = tables_dir / "annual_area_5sites.csv"
    if not area_path.exists():
        raise SystemExit(
            f"Missing {area_path}. Run scripts/run_extent_fusion.py first."
        )
    df = pd.read_csv(area_path)
    if args.area_col not in df.columns:
        raise SystemExit(
            f"Column {args.area_col} not in {area_path}. Have: {list(df.columns)}"
        )

    df = _attach_n_scenes(df)

    # Drop rows with missing scene counts or area.
    df_clean = df.dropna(subset=[args.area_col, "n_scenes"])

    corrected, fit_summary = correct_all_sites(
        df_clean,
        area_col=args.area_col,
        n_col="n_scenes",
        year_col="year",
        n_boot=args.n_boot,
        alpha=args.alpha,
    )
    out_csv = tables_dir / "annual_area_5sites_corrected.csv"
    corrected.to_csv(out_csv, index=False, float_format="%.4f")
    log.info("Wrote %s (%d rows)", out_csv, len(corrected))

    fit_csv = tables_dir / "obsfreq_fit_summary.csv"
    fit_summary.to_csv(fit_csv, index=False, float_format="%.4f")
    log.info("Wrote %s", fit_csv)

    print(fit_summary.to_string(index=False))


if __name__ == "__main__":
    main()
