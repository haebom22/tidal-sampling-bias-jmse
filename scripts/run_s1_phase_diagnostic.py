"""Phase-0 diagnostic: extract Sentinel-1 scenes and compute ⟨cos θ⟩_S1.

For the two pilot sites (Garorim Bay, Suncheon Bay) this script:

  1. Pulls Sentinel-1 GRD (IW/VV) scene metadata over 2020-01-01 → 2024-12-31
     from Google Earth Engine.
  2. Merges the result with each site's cached optical metadata
     (``data/raw/gee_metadata/<site>_scenes.parquet``) so that all sensors
     live in the same parquet.
  3. Pulls the relevant KHOA hourly tide series, interpolates the tide
     height at every S1 acquisition time, and applies the project's
     HW-based phase convention to compute θ and cos θ for each scene.
  4. Writes a per-site summary table comparing ⟨cos θ⟩_optical and
     ⟨cos θ⟩_S1, validating the manuscript's §5.3(c) prediction that
     SAR overpasses are phase-orthogonal to the 11:00 KST optical
     window.

Outputs
-------
- ``data/raw/gee_metadata/<site>_scenes.parquet``  (S1 rows appended)
- ``data/processed/<site>_s1_phases.parquet``
- ``data/outputs/tables/s1_vs_optical_phase.csv``
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.phase import (
    find_tide_extremes,
    compute_phase_hw,
    phase_statistics,
)
from src.config import load_settings, load_sites, resolve_path
from src.gee.auth import initialize
from src.gee.metadata import extract_site_metadata, save_metadata
from src.tides.khoa import fetch_tide_hourly_range, interpolate_at_times

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("s1_phase_diagnostic")

PILOT_SITES = ("ganghwa", "garorim", "gomso", "hampyeong", "suncheon")
DEFAULT_START = "2020-01-01"
DEFAULT_END = "2024-12-31"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=str, default=None, help="EE Cloud project id")
    p.add_argument(
        "--sites",
        nargs="*",
        default=list(PILOT_SITES),
        help="Site ids (default: garorim suncheon)",
    )
    p.add_argument("--start", type=str, default=DEFAULT_START)
    p.add_argument("--end", type=str, default=DEFAULT_END)
    p.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip GEE extraction; use cached parquet only",
    )
    return p.parse_args()


def _attach_phase(
    scenes: pd.DataFrame,
    khoa_obs: pd.DataFrame,
) -> pd.DataFrame:
    """Add tide_m, phase_hw, theta, cos_theta, sin_theta columns."""
    out = scenes.copy()
    out["datetime_utc"] = pd.to_datetime(out["datetime_utc"], utc=True)
    out["tide_m"] = interpolate_at_times(khoa_obs, out["datetime_utc"]).to_numpy()

    extremes = find_tide_extremes(khoa_obs)
    out["phase_hw"] = compute_phase_hw(out["datetime_utc"], extremes.high_times)
    out["theta"] = 2 * np.pi * out["phase_hw"]
    out["cos_theta"] = np.cos(out["theta"])
    out["sin_theta"] = np.sin(out["theta"])
    return out


def main() -> None:
    args = parse_args()
    settings = load_settings()
    sites_all = {s.id: s for s in load_sites()}
    sites = [sites_all[s_id] for s_id in args.sites if s_id in sites_all]
    if not sites:
        raise SystemExit(f"No matching sites among {list(sites_all)}")

    gee_dir = resolve_path(settings["paths"]["gee_metadata"])
    khoa_dir = resolve_path(settings["paths"]["khoa"])
    processed_dir = resolve_path(settings["paths"]["processed"])
    tables_dir = resolve_path(settings["paths"]["tables"])
    for p in (gee_dir, khoa_dir, processed_dir, tables_dir):
        p.mkdir(parents=True, exist_ok=True)

    if not args.skip_extract:
        log.info("Initialising Earth Engine (project=%s)", args.project)
        initialize(project=args.project)

    summary_rows: list[dict] = []

    for site in sites:
        log.info("=== Site: %s (%s) ===", site.id, site.name_en)

        # --- 1. Extract S1 metadata from GEE (or load cache) --------------
        scenes_path = gee_dir / f"{site.id}_scenes.parquet"
        if scenes_path.exists():
            cached = pd.read_parquet(scenes_path)
            log.info("Cached metadata: %d total scenes", len(cached))
        else:
            cached = pd.DataFrame()

        if not args.skip_extract:
            log.info("Querying Sentinel-1 (%s → %s)", args.start, args.end)
            s1_df = extract_site_metadata(site, ["S1"], args.start, args.end)
            log.info("  -> %d S1 scenes", len(s1_df))
            if not s1_df.empty:
                if cached.empty:
                    merged = s1_df
                else:
                    cached_no_s1 = cached[cached["sensor"] != "S1"]
                    merged = pd.concat([cached_no_s1, s1_df], ignore_index=True)
                merged = merged.sort_values("datetime_utc").reset_index(drop=True)
                save_metadata(merged, gee_dir, site.id)
                cached = merged
                log.info("Saved merged metadata (%d rows) → %s", len(merged), scenes_path)
        if cached.empty:
            log.warning("No scenes available for %s; skipping", site.id)
            continue

        s1 = cached[cached["sensor"] == "S1"].copy()
        if s1.empty:
            log.warning("No S1 rows for %s; skipping phase computation", site.id)
            continue

        # --- 2. Pull/Load KHOA hourly tides for the primary station ------
        station = site.khoa_stations[0]
        log.info(
            "KHOA: %s (%s) %s → %s",
            station.name_en,
            station.code,
            args.start,
            args.end,
        )
        khoa_obs = fetch_tide_hourly_range(
            station.code,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            khoa_dir,
        )
        log.info("  -> %d hourly tide rows", len(khoa_obs))
        if khoa_obs.empty:
            log.warning(
                "No KHOA observations for %s; cannot attach phases for S1.",
                station.code,
            )
            continue

        # --- 3. Compute phase for S1 (and for the cached optical rows) --
        s1_phases = _attach_phase(s1, khoa_obs)
        s1_out = processed_dir / f"{site.id}_s1_phases.parquet"
        s1_phases.to_parquet(s1_out, index=False)
        log.info("Saved S1 phase table → %s", s1_out)

        optical = cached[cached["sensor"].isin(["L8", "L9", "S2"])].copy()
        if not optical.empty:
            optical = _attach_phase(optical, khoa_obs)

        # --- 4. Summary statistics ---------------------------------------
        for sensor_group, label in [(optical, "optical (L8+L9+S2)"), (s1_phases, "S1")]:
            if sensor_group.empty:
                continue
            stats = phase_statistics(sensor_group["phase_hw"].to_numpy())
            summary_rows.append({
                "site_id": site.id,
                "site_name": site.name_en,
                "group": label,
                "n_scenes": stats["n"],
                "mean_phase_deg": stats.get("mean_phase_deg", float("nan")),
                "cos_theta_mean": stats.get("cos_mean", float("nan")),
                "sin_theta_mean": stats.get("sin_mean", float("nan")),
                "R": stats.get("R", float("nan")),
                "mean_tide_m": float(sensor_group["tide_m"].mean(skipna=True)),
            })

        # Per-pass breakdown for S1
        if "orbitproperties_pass" in s1_phases.columns:
            for pass_dir, sub in s1_phases.groupby("orbitproperties_pass"):
                if sub.empty:
                    continue
                stats = phase_statistics(sub["phase_hw"].to_numpy())
                summary_rows.append({
                    "site_id": site.id,
                    "site_name": site.name_en,
                    "group": f"S1 {pass_dir}",
                    "n_scenes": stats["n"],
                    "mean_phase_deg": stats.get("mean_phase_deg", float("nan")),
                    "cos_theta_mean": stats.get("cos_mean", float("nan")),
                    "sin_theta_mean": stats.get("sin_mean", float("nan")),
                    "R": stats.get("R", float("nan")),
                    "mean_tide_m": float(sub["tide_m"].mean(skipna=True)),
                })

    if not summary_rows:
        log.warning("No summary rows produced.")
        return

    summary = pd.DataFrame(summary_rows)
    summary_path = tables_dir / "s1_vs_optical_phase.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    log.info("Wrote summary → %s", summary_path)

    print()
    print("=" * 80)
    print("PHASE-0 SUMMARY: ⟨cos θ⟩ optical vs SAR")
    print("=" * 80)
    cols = ["site_name", "group", "n_scenes", "cos_theta_mean", "mean_tide_m"]
    print(summary[cols].to_string(index=False))
    print()
    print("Manuscript §5.3(c) prediction:")
    print("  S1 overpasses (~06:00/18:00 KST) are ~5 h offset from optical (~11:00 KST)")
    print("  5 h ≈ 0.4 × M2 period → cos θ_S1 should be ≈ orthogonal to cos θ_optical.")
    print("  Concretely: |cos θ_S1| should be small and/or have a different sign.")


if __name__ == "__main__":
    main()
