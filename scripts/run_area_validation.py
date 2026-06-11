"""Cross-validate 5-site annual areas against Murray/GWL_FCS30/GTF30/MOF.

Phase 3 driver. Produces:
  - data/outputs/tables/reference_comparison_5sites.csv
  - data/outputs/tables/reference_comparison_summary.csv
  - data/outputs/tables/area_uncertainty_budget.csv
  - data/outputs/figures/area_scatter_blandaltman.png
  - data/outputs/figures/area_decomposition_5sites.png

Usage:
    python scripts/run_area_validation.py [--area-col total_km2]
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from src.analysis.area_validation import (
    build_comparison_table,
    decompose_error,
    plot_decomposition,
    plot_scatter_and_bland_altman,
    summarise_by_source,
)
from src.config import resolve_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("area_validation")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--area-col",
        default="total_km2",
        help="Area column to compare (total_km2 | area_dem_km2 | tier1_km2).",
    )
    p.add_argument(
        "--use-corrected",
        action="store_true",
        help="Use the obs-frequency corrected annual areas (Phase 2).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    tables_dir = resolve_path("data/outputs/tables")
    fig_dir = resolve_path("data/outputs/figures")
    proc_dir = resolve_path("data/processed")
    fig_dir.mkdir(parents=True, exist_ok=True)

    annual_path = (
        tables_dir / "annual_area_5sites_corrected.csv"
        if args.use_corrected
        else tables_dir / "annual_area_5sites.csv"
    )
    ref_path = proc_dir / "reference_extents.parquet"
    if not annual_path.exists():
        raise SystemExit(f"Missing {annual_path}. Run Phase 1d (or Phase 2).")
    if not ref_path.exists():
        raise SystemExit(f"Missing {ref_path}. Run Phase 0 ingest.")

    annual = pd.read_csv(annual_path)
    references = pd.read_parquet(ref_path)

    use_col = args.area_col
    if args.use_corrected:
        candidate = f"{args.area_col}_corrected"
        if candidate in annual.columns:
            use_col = candidate
    if use_col not in annual.columns:
        raise SystemExit(
            f"Column {use_col} not in {annual_path}: {list(annual.columns)}"
        )

    log.info("Comparing area column: %s", use_col)
    comp = build_comparison_table(annual, references, area_col_this=use_col)
    comp_path = tables_dir / "reference_comparison_5sites.csv"
    comp.to_csv(comp_path, index=False, float_format="%.4f")
    log.info("Wrote %s (%d rows)", comp_path, len(comp))

    summary = summarise_by_source(comp, area_col_this="area_this_km2")
    summary_path = tables_dir / "reference_comparison_summary.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    log.info("Wrote %s", summary_path)
    print(summary.to_string(index=False))

    decomp = decompose_error(annual.assign(_this=annual[use_col]), references,
                             area_col_this=use_col)
    decomp_path = tables_dir / "area_uncertainty_budget.csv"
    decomp.to_csv(decomp_path, index=False, float_format="%.4f")
    log.info("Wrote %s", decomp_path)

    if not comp.empty:
        plot_scatter_and_bland_altman(
            comp,
            fig_dir / "area_scatter_blandaltman.png",
            area_col_this="area_this_km2",
        )
    if not decomp.empty:
        plot_decomposition(decomp, fig_dir / "area_decomposition_5sites.png")


if __name__ == "__main__":
    main()
