"""Build the MOF/KHOA official tidal flat reference statistics.

The Korean Ministry of Oceans and Fisheries (MOF) publishes a tidal-flat
survey every five years (현재 가장 최신 통계는 2018·2023 시점). The data
are downloadable from:

    haetbol.kosis.kr/index.do    (한국해양수산개발원 갯벌통계)
    https://www.mof.go.kr/        (해양수산부 통계자료실)

Because the dataset distribution policy and exact CSV layout change
year-to-year (and sometimes requires manual sign-in), this script
*assembles* the official numbers from a CSV the user has staged at
``data/raw/reference/mof_tidal_flat_survey_raw.csv`` and turns them into
a consistent ``data/raw/reference/mof_tidal_flat_survey.parquet`` with
columns:

    province     광역지자체 (시도)
    municipality 기초지자체 (시군구) — optional
    year         survey reference year
    area_km2     officially reported tidal-flat area
    source       URL / publication citation

This file then serves as the ground-truth reference for the Phase-3
validation. If the raw CSV is not present yet, the script prints
instructions for obtaining it manually.

Usage
-----
    python scripts/prepare_mof_reference.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from src.config import resolve_path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("mof_reference")

RAW_CSV_PATH = resolve_path("data/raw/reference/mof_tidal_flat_survey_raw.csv")
RAW_SHP_DIR = resolve_path("data/raw/reference/2023_갯벌_접경지역포함")
OUT_PATH = resolve_path("data/raw/reference/mof_tidal_flat_survey.parquet")

# Expected column variants the raw CSV may use (lower-cased, stripped).
COLUMN_ALIASES = {
    "province": ["province", "시도", "시.도", "광역", "sido"],
    "municipality": ["municipality", "시군구", "기초", "sigungu"],
    "year": ["year", "연도", "기준연도"],
    "area_km2": ["area_km2", "면적(km^2)", "면적_km2", "갯벌면적", "면적"],
    "source": ["source", "출처"],
}


def _instructions() -> str:
    return (
        "\n"
        "MOF tidal-flat survey CSV not found.\n"
        f"Place a CSV at: {RAW_PATH}\n"
        "\n"
        "Download instructions:\n"
        "  1. https://haetbol.kosis.kr/index.do  (KOSIS 갯벌통계)\n"
        "  2. Select '시도별/시군구별 갯벌면적', 2018+ surveys.\n"
        "  3. Export as CSV (UTF-8 with BOM). Provide at least the\n"
        "     columns: 시도, (시군구), 연도, 갯벌면적(km^2).\n"
        "  4. Alternatively, MOF publishes annual yearbooks at\n"
        "     https://www.mof.go.kr/statPortal/cate/statView.do — pick\n"
        "     '갯벌면적' and export.\n"
        "\n"
        "Then rerun this script to convert it to the canonical parquet.\n"
    )


def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Best-effort rename: pick the first matching alias for each canonical key."""
    cols_lc = {c.strip().lower(): c for c in df.columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a.lower() in cols_lc:
                mapping[cols_lc[a.lower()]] = canonical
                break
    return df.rename(columns=mapping)


def _from_csv() -> pd.DataFrame:
    """Load from a user-staged raw CSV."""
    log.info("Reading %s", RAW_CSV_PATH)
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            df = pd.read_csv(RAW_CSV_PATH, encoding=enc)
            log.info("  encoding=%s, %d rows", enc, len(df))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("Could not decode CSV in any of utf-8/utf-8-sig/cp949")

    df = _rename_columns(df)
    missing = [c for c in ("province", "year", "area_km2") if c not in df.columns]
    if missing:
        log.error("Missing required columns after rename: %s", missing)
        log.error("Available columns: %s", list(df.columns))
        sys.exit(3)

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["area_km2"] = pd.to_numeric(df["area_km2"], errors="coerce")
    df = df.dropna(subset=["year", "area_km2"])
    df["source"] = df.get("source", "MOF KOSIS 갯벌통계")
    if "municipality" not in df.columns:
        df["municipality"] = pd.NA
    return df[["province", "municipality", "year", "area_km2", "source"]]


def _from_shapefile() -> pd.DataFrame:
    """Load from the MOF 갯벌 shapefile (``2023_갯벌/*.shp``).

    The shapefile's ``area`` column already carries each polygon's area in km².
    We aggregate by province (``SD``) and municipality (``SG``) to produce
    the same schema as the CSV path.  The survey year is inferred from the
    directory name (e.g. ``2023_갯벌`` → 2023).
    """
    import os
    import geopandas as gpd

    shp_candidates = sorted(RAW_SHP_DIR.glob("*.shp"))
    if not shp_candidates:
        raise FileNotFoundError(f"No .shp file found in {RAW_SHP_DIR}")
    shp_path = shp_candidates[0]
    log.info("Reading shapefile %s", shp_path)

    os.environ.setdefault("SHAPE_ENCODING", "UTF-8")
    gdf = gpd.read_file(shp_path)
    log.info("  %d features, columns: %s", len(gdf), list(gdf.columns))

    # Infer survey year from the parent directory name.
    dir_name = RAW_SHP_DIR.name  # e.g. "2023_갯벌"
    year_str = "".join(c for c in dir_name if c.isdigit())
    if year_str:
        survey_year = int(year_str)
    else:
        survey_year = 2023
        log.warning("Could not infer year from dir name '%s'; defaulting to %d", dir_name, survey_year)

    # Aggregate by province + municipality using the shapefile's area column.
    by_prov = (
        gdf.groupby(["SD", "SG"])["area"]
        .sum()
        .reset_index()
        .rename(columns={"SD": "province", "SG": "municipality", "area": "area_km2"})
    )
    by_prov["year"] = survey_year
    by_prov["source"] = f"MOF 갯벌 shapefile ({survey_year})"

    # Also add province-level totals (municipality = NA) for downstream use.
    prov_total = (
        gdf.groupby("SD")["area"]
        .sum()
        .reset_index()
        .rename(columns={"SD": "province", "area": "area_km2"})
    )
    prov_total["municipality"] = pd.NA
    prov_total["year"] = survey_year
    prov_total["source"] = f"MOF 갯벌 shapefile ({survey_year})"

    df = pd.concat([prov_total, by_prov], ignore_index=True)
    df = df[["province", "municipality", "year", "area_km2", "source"]]
    return df


def main() -> None:
    # Prefer shapefile over CSV; fall back to CSV if shapefile dir is absent.
    if RAW_SHP_DIR.is_dir() and any(RAW_SHP_DIR.glob("*.shp")):
        df = _from_shapefile()
    elif RAW_CSV_PATH.exists():
        df = _from_csv()
    else:
        print(_instructions(), file=sys.stderr)
        sys.exit(2)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    log.info("Wrote %s (%d rows)", OUT_PATH, len(df))

    log.info("Summary by province (km²):")
    summary = df[df["municipality"].isna()].sort_values("area_km2", ascending=False)
    if summary.empty:
        summary = df.groupby("province")["area_km2"].sum().sort_values(ascending=False)
    print(summary.to_string())


if __name__ == "__main__":
    main()
