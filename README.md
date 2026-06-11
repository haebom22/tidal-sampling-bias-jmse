# Predicting tidal-sampling bias of sun-synchronous satellites

Manuscript and reproducibility pipeline for:

> **Predicting tidal-sampling bias of sun-synchronous satellites from overpass
> phase: theory and validation on macrotidal coasts**
> (manuscript prepared for *Remote Sensing of Environment*)

The waterline method for mapping intertidal DEMs from optical imagery assumes
satellites sample the local tidal cycle without systematic bias. We derive a
closed-form, first-order model in which the satellite-sampled tide bias equals
**β · A · ⟨cos θ⟩** (A = local tidal amplitude, ⟨cos θ⟩ = mean cosine of the
satellite-overpass tide phase) and validate it over five macrotidal Korean
tidal flats (2020–2024, 5,082 cloud-screened Landsat-8/9 + Sentinel-2 scenes)
against hourly KHOA tide-gauge observations. A single slope **β = 1.78**
reproduces the bias across sites and sensors (R² = 0.98); the bias is **bipolar**
(low-tide on the west coast, high-tide at Suncheon Bay) and reproducible from
the global **FES2022b** tide model alone (R² = 0.983).

## Study sites

| Site | Region | Lat/Lon (approx.) | Mean spring range | KHOA gauge |
|---|---|---|---|---|
| Ganghwa-do | NW (Gyeonggi Bay) | 37.60°N, 126.45°E | ~8 m | Incheon (DT_0001) |
| Garorim Bay | West (Chungnam) | 37.00°N, 126.40°E | ~6 m | Anheung (DT_0067) |
| Gomso Bay | West (Jeonbuk) | 35.60°N, 126.60°E | ~6 m | Gunsan (DT_0018) |
| Hampyeong Bay | SW (Jeonnam) | 35.10°N, 126.40°E | ~4 m | Yeonggwang (DT_0003) |
| Suncheon Bay | South (Jeonnam) | 34.90°N, 127.50°E | ~3 m | Yeosu (DT_0016) |

## Repository layout

```
tidalflat/
├── manuscript/            # The paper (source of truth = the *.md files)
│   ├── draft.md           #   main text  → draft.pdf / draft.docx
│   ├── draft_ko.md        #   Korean translation → draft_ko.{pdf,docx}
│   ├── supplementary.md   #   supplementary → supplementary.{pdf,docx}
│   ├── cover_letter.md    #   cover letter
│   ├── figures/           #   final figures embedded in the paper (tracked)
│   ├── figure_captions.md #   filename ↔ figure-number map
│   └── references.bib
├── src/                   # Analysis library (gee / tides / analysis / visualization)
├── scripts/               # Runnable entry points (figures, tables, builds)
├── config/                # Site definitions and settings
├── data/                  # Inputs + derived outputs — NOT tracked (see .gitignore)
└── requirements.txt
```

`data/` (24 GB FES2022b grids, raw KHOA/GEE pulls, derived tables/figures) and
external `reference/` PDFs are **git-ignored** — all are reproducible from the
steps below.

## Reproduce

### 0. Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # pandas, scipy, pyTMD, earthengine-api, matplotlib, cartopy, …
brew install pandoc tectonic             # for the manuscript PDF build
```

Scripts are run from the project root with the root on `PYTHONPATH`:

```bash
PYTHONPATH=. python scripts/<name>.py
```

### 1. Inputs / credentials

| Input | Source | Setup |
|---|---|---|
| Satellite scene metadata | Google Earth Engine (L8/L9/S2 collections) | `earthengine authenticate` |
| Hourly tide observations | KHOA Open API (`apis.data.go.kr/1192136`) | put key in `.khoa_api_key` |
| FES2022b global tide model | AVISO+ (registration) | grids under `data/raw/fes2022b/`; creds in `.aviso_credentials` |

Only acquisition **metadata** is pulled from GEE (no pixel downloads). Cached
pulls live under `data/raw/` and `data/processed/`.

### 2. Run the analysis (regenerates figures + tables under `data/outputs/`)

```bash
PYTHONPATH=. python scripts/generate_study_area_map.py      # Fig 1
PYTHONPATH=. python scripts/demo_aliasing_multisite.py      # Fig 2, 3, S1, S2 + Table 3 data
PYTHONPATH=. python scripts/demo_phase_analysis.py          # Fig 4, 5, S5
PYTHONPATH=. python scripts/demo_phase_stability.py         # Fig 6, S3, S4 + Table S1 data
PYTHONPATH=. python scripts/demo_dem_error.py               # Fig 7, S6, S7 + DEM error budget
PYTHONPATH=. python scripts/fes2022b_sensitivity.py         # Table S2 (FES2022b variant)
PYTHONPATH=. python scripts/demo_harmonic_decomposition.py  # Table S2 (M₂-amplitude variants)
```

Figures are written to `data/outputs/figures/` and the underlying tables to
`data/outputs/tables/`. The mapping from a generated PNG to its final
manuscript figure number is documented in
[`manuscript/figure_captions.md`](manuscript/figure_captions.md); copy the
regenerated PNGs into `manuscript/figures/` under the names listed there to
refresh the paper (the repo already ships the final copies).

### 3. Build the manuscript

PDFs use the LaTeX pipeline (pandoc → tectonic) so RSE's continuous line
numbering, double spacing and 2.5 cm margins are honoured:

```bash
bash scripts/build_manuscript_pdf.sh all      # draft, draft_ko, supplementary, cover_letter
# or one at a time:  draft | ko | supp | cover
```

Word versions (raw-LaTeX tables/figures converted to native Word tables,
images and OMML equations):

```bash
python scripts/build_docx.py draft            # or: ko | supp | cover
```

## Data and code availability

Raw KHOA tide-gauge data are public via the Korea Open Data Portal
(`apis.data.go.kr/1192136`); GEE scene metadata is reproducible from the public
collections `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2`,
`COPERNICUS/S2_HARMONIZED`. The derived parquet/CSV tables and figure-generation
scripts are intended for release on a Zenodo-archived snapshot of this
repository upon acceptance (DOI to be assigned).

## Key references

- Bishop-Taylor, R. et al. (2019). Between the tides… *Estuarine, Coastal and Shelf Science* 223, 115–128.
- Bishop-Taylor, R. et al. (2025). eo-tides: tide-modelling tools for large-scale EO. *JOSS* 10(109), 7786.
- Sagar, S. et al. (2017). Extracting the intertidal extent and topography… *Remote Sensing of Environment* 195, 153–169.
- Ryu, J.-H. et al. (2002). Waterline extraction from Landsat TM data in a tidal flat: Gomso Bay, Korea. *Remote Sensing of Environment* 83(3), 442–456.
- Lyard, F. et al. (2021) / Carrère, L. et al. (2022). FES2014 / FES2022 global ocean tide atlases. AVISO+.

Full bibliography in [`manuscript/references.bib`](manuscript/references.bib).
