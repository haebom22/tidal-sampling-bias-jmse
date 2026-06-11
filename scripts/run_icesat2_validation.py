"""Run ICESat-2 validation for all site × variant DEMs.

Outputs:
  - data/outputs/tables/icesat2_validation_summary.csv
  - Console summary table
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import rasterio  # noqa: F401 — import early to avoid pyarrow conflict

from src.analysis.validate_icesat2 import run_full_validation
from src.config import resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("dem_validation")

SITES = ["ganghwa", "garorim", "gomso", "hampyeong", "suncheon"]
VARIANTS = ["v1", "v2", "v3", "v4"]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sites", nargs="*", default=SITES)
    p.add_argument("--variants", nargs="*", default=VARIANTS)
    return p.parse_args()


def main():
    args = parse_args()
    dem_dir = resolve_path("data/outputs/dem")
    icesat2_dir = resolve_path("data/processed")
    tables_dir = resolve_path("data/outputs/tables")
    tables_dir.mkdir(parents=True, exist_ok=True)

    df = run_full_validation(
        dem_dir=dem_dir,
        icesat2_dir=icesat2_dir,
        sites=args.sites,
        variants=args.variants,
    )

    if df.empty:
        log.warning("No validation results. Ensure DEMs exist in %s", dem_dir)
        return

    out_path = tables_dir / "icesat2_validation_summary.csv"
    df.to_csv(out_path, index=False, float_format="%.4f")
    log.info("Saved validation summary → %s", out_path)

    print("\n" + "=" * 80)
    print("ICESat-2 VALIDATION SUMMARY")
    print("=" * 80)
    pivot = df.pivot_table(
        index="site_id",
        columns="variant",
        values=["rmse_m", "bias_m", "n_points"],
    )
    print(pivot.to_string(float_format="%.3f"))

    print("\n--- Mean across sites ---")
    mean_by_variant = df.groupby("variant")[["rmse_m", "mae_m", "bias_m"]].mean()
    print(mean_by_variant.to_string(float_format="%.3f"))

    print("\n--- Improvement V1→V3 (bias correction effect) ---")
    for site in args.sites:
        site_df = df[df["site_id"] == site]
        v1 = site_df[site_df["variant"] == "v1"]
        v3 = site_df[site_df["variant"] == "v3"]
        if not v1.empty and not v3.empty:
            rmse_v1 = v1.iloc[0]["rmse_m"]
            rmse_v3 = v3.iloc[0]["rmse_m"]
            pct = (rmse_v1 - rmse_v3) / rmse_v1 * 100
            print(f"  {site}: {rmse_v1:.3f} → {rmse_v3:.3f} m ({pct:+.1f}%)")


if __name__ == "__main__":
    main()
