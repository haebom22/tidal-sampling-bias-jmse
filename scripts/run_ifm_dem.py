"""Build Inundation-Frequency-Method (IFM) DEMs and compare to waterline DEMs.

Phase 1 of the §4.2 recommended workflow:

  Inputs (already on disk):
    - data/outputs/dem/{site}_v1.tif       (waterline DEM, band 5 = freq)
    - data/processed/{site}_icesat2_exposed.parquet

  Outputs:
    - data/outputs/dem/{site}_ifm_slm.tif      (linear)
    - data/outputs/dem/{site}_ifm_poly3.tif    (3rd-order polynomial)
    - data/outputs/dem/{site}_ifm_rf.tif       (random forest)
    - data/outputs/dem/{site}_ifm_summary.json (per-model metrics)
    - data/outputs/tables/ifm_vs_waterline.csv (cumulative comparison)

Usage:
    python scripts/run_ifm_dem.py --sites garorim
    python scripts/run_ifm_dem.py --sites ganghwa garorim gomso hampyeong suncheon
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import rasterio  # noqa: F401  - early import to avoid pyarrow conflict

from src.analysis.ifm import build_ifm_dem  # noqa: E402
from src.config import resolve_path  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
)
log = logging.getLogger("run_ifm_dem")

DEFAULT_SITES = ["garorim"]
DEFAULT_MODELS = ["slm", "poly3", "rf"]
DEFAULT_BASELINE_VARIANT = "v2"   # IFM-input: V2 (= L8+L9+S2+S1) gives S1-augmented freq band
DEFAULT_WATERLINE_BASELINE = "v4"  # head-to-head: V4 (= L8+L9+S2+S1+bias) is the SOTA waterline

# Manuscript-2 waterline RMSE (m), all five Korean sites, from
# data/outputs/tables/icesat2_validation_summary.csv (May 2026 run).
WATERLINE_RMSE_M: dict[str, dict[str, float]] = {
    "v1":     {"ganghwa": 1.521, "garorim": 1.166, "gomso": 1.515, "hampyeong": 1.048, "suncheon": 0.848},
    "v2":     {"ganghwa": 1.561, "garorim": 1.252, "gomso": 1.501, "hampyeong": 1.082, "suncheon": 0.784},
    "v3":     {"ganghwa": 1.738, "garorim": 1.186, "gomso": 1.826, "hampyeong": 0.943, "suncheon": 0.724},
    "v3khoa": {"ganghwa": 1.650, "garorim": 1.137, "gomso": 1.565, "hampyeong": 0.958, "suncheon": 0.724},
    "v4":     {"ganghwa": 1.796, "garorim": 1.233, "gomso": 1.457, "hampyeong": 0.945, "suncheon": 0.718},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sites", nargs="*", default=DEFAULT_SITES,
                   help="site ids (default: garorim)")
    p.add_argument("--baseline-variant", default=DEFAULT_BASELINE_VARIANT,
                   choices=["v1", "v2", "v3", "v4", "v3khoa"],
                   help="waterline variant whose frequency band is reused as IFM input "
                        "(default: v2 = L8+L9+S2+S1 → S1-augmented freq)")
    p.add_argument("--waterline-baseline", default=DEFAULT_WATERLINE_BASELINE,
                   choices=["v1", "v2", "v3", "v3khoa", "v4"],
                   help="waterline variant used as the comparison baseline in the "
                        "summary table (default: v4 = SOTA waterline)")
    p.add_argument("--output-suffix", default=None,
                   help="suffix for the per-site IFM tif files (default: derived "
                        "from --baseline-variant, e.g. v2 → 'ifm_s1_<model>')")
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS,
                   choices=["slm", "poly3", "rf"])
    p.add_argument("--freq-lo", type=float, default=0.03)
    p.add_argument("--freq-hi", type=float, default=0.97)
    p.add_argument("--test-fraction", type=float, default=0.20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--sigma-clip", type=float, default=2.0)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    dem_dir = resolve_path("data/outputs/dem")
    proc_dir = resolve_path("data/processed")
    tables_dir = resolve_path("data/outputs/tables")
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Suffix for the per-site IFM tif filenames.
    if args.output_suffix is not None:
        suffix = args.output_suffix
    elif args.baseline_variant == "v1":
        suffix = "ifm"            # back-compat with Phase 1
    elif args.baseline_variant == "v2":
        suffix = "ifm_s1"         # Phase 1b: optical + S1 SAR
    else:
        suffix = f"ifm_{args.baseline_variant}"

    baseline_table = WATERLINE_RMSE_M.get(args.waterline_baseline, {})
    label = args.waterline_baseline.upper()

    all_rows: list[dict] = []
    for site_id in args.sites:
        waterline_dem = dem_dir / f"{site_id}_{args.baseline_variant}.tif"
        icesat2_pq = proc_dir / f"{site_id}_icesat2_exposed.parquet"
        if not waterline_dem.exists():
            log.error("missing waterline DEM: %s — skipping %s", waterline_dem, site_id)
            continue
        if not icesat2_pq.exists():
            log.error("missing ICESat-2 cache: %s — skipping %s", icesat2_pq, site_id)
            continue

        summary = build_ifm_dem(
            waterline_dem_path=waterline_dem,
            icesat2_path=icesat2_pq,
            out_dir=dem_dir,
            site_id=site_id,
            models=args.models,
            freq_range=(args.freq_lo, args.freq_hi),
            test_fraction=args.test_fraction,
            random_state=args.seed,
            sigma_clip=args.sigma_clip,
            output_suffix=suffix,
        )

        for model_name, metrics in summary["models"].items():
            row = {
                "site_id": site_id,
                "ifm_input": args.baseline_variant,
                "model": model_name,
                "n_train": metrics["n_train"],
                "n_test": metrics["n_test"],
                "train_rmse_m": metrics["train_rmse_m"],
                "test_rmse_m": metrics["test_rmse_m"],
                "train_mae_m": metrics["train_mae_m"],
                "test_mae_m": metrics["test_mae_m"],
                "train_bias_m": metrics["train_bias_m"],
                "test_bias_m": metrics["test_bias_m"],
                "train_r2": metrics["train_r2"],
                "test_r2": metrics["test_r2"],
                "elevation_min_m": metrics["elevation_range_m"][0],
                "elevation_max_m": metrics["elevation_range_m"][1],
                "v3khoa_rmse_m": WATERLINE_RMSE_M["v3khoa"].get(site_id),
                "v4_rmse_m": WATERLINE_RMSE_M["v4"].get(site_id),
                "baseline_label": label,
                "baseline_rmse_m": baseline_table.get(site_id),
                "ifm_vs_baseline_pct": (
                    100.0 * (baseline_table[site_id] - metrics["test_rmse_m"])
                    / baseline_table[site_id]
                ) if site_id in baseline_table else None,
            }
            all_rows.append(row)

    if not all_rows:
        log.error("No IFM runs completed.")
        return

    df = pd.DataFrame(all_rows)
    out_csv = tables_dir / f"ifm_{args.baseline_variant}_vs_{args.waterline_baseline}.csv"
    df.to_csv(out_csv, index=False, float_format="%.4f")
    log.info("Saved per-(site, model) metrics → %s", out_csv)

    # Console summary
    print("\n" + "=" * 104)
    print(f" IFM RESULTS (input={args.baseline_variant.upper()}) — "
          f"held-out 20% ICESat-2 RMSE  vs.  waterline {label}")
    print("=" * 104)
    fmt = "{:<10} {:<6} {:>7} {:>7} {:>10} {:>9} {:>8} {:>11} {:>9}"
    print(fmt.format("site", "model", "n_train", "n_test",
                     "test_RMSE", "test_R²", "bias", label, "Δ %"))
    print("-" * 104)
    for _, r in df.iterrows():
        delta = r.get("ifm_vs_baseline_pct")
        delta_str = "—" if pd.isna(delta) else f"{delta:+.1f}"
        base = r.get("baseline_rmse_m")
        base_str = "—" if pd.isna(base) else f"{base:.3f}"
        print(fmt.format(
            r["site_id"], r["model"],
            int(r["n_train"]), int(r["n_test"]),
            f"{r['test_rmse_m']:.3f}",
            f"{r['test_r2']:+.3f}",
            f"{r['test_bias_m']:+.3f}",
            base_str, delta_str,
        ))
    print("=" * 104)
    print(f"(Δ > 0  →  IFM lower RMSE than waterline {label} at the same site)")


if __name__ == "__main__":
    main()
