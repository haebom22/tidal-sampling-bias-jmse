# A gauge-free predictive model for the tidal-sampling bias of sun-synchronous satellites

Manuscript and reproducibility pipeline for:

> **A Gauge-Free Predictive Model for the Tidal-Sampling Bias of Sun-Synchronous
> Satellites, Validated on Macrotidal Tidal Flats**
> Taeyoon Song, Mirinae Kim — submitted to *Journal of Marine Science and
> Engineering* (MDPI), Physical Oceanography section.

The waterline method for mapping intertidal DEMs from optical imagery assumes
satellites sample the local tidal cycle without systematic bias. We derive a
closed-form, first-order model in which the satellite-sampled tide bias equals
**β · A · ⟨cos θ⟩** (A = local tidal amplitude, ⟨cos θ⟩ = mean cosine of the
satellite-overpass tide phase) and validate it over five macrotidal Korean
tidal flats (2020–2024, 5,082 cloud-screened Landsat-8/9 + Sentinel-2 scenes)
against hourly KHOA tide-gauge observations. A single slope **β = 1.78**
reproduces the bias across sites and sensors (R² = 0.98); the bias is
**sign-reversing** (low-tide on the macrotidal west coast, high-tide at
south-coast Suncheon Bay) and is reproduced from the global **FES2022b** tide
model alone as a self-consistency check (R² = 0.983), though the global model
under-estimates the bias magnitude on resonant macrotidal coasts. Translated to
the elevation domain the bias implies a DEM RMSE of 0.36–1.09 m and permanently
unsampled intertidal bands up to ~2.5 km wide that no increase in optical
revisit frequency can recover.

## Study sites

| Site | Region | Lat/Lon (approx.) | Mean spring range | KHOA gauge |
|---|---|---|---|---|
| Ganghwa-do | Northwest coast (Gyeonggi Bay) | 37.60°N, 126.45°E | ~8 m | Incheon (DT_0001) |
| Garorim Bay | West coast (Chungnam) | 37.00°N, 126.40°E | ~6 m | Anheung (DT_0067) |
| Gomso Bay | West coast (Jeonbuk) | 35.60°N, 126.60°E | ~6 m | Gunsan (DT_0018) |
| Hampyeong Bay | Southwest coast (Jeonnam) | 35.10°N, 126.40°E | ~4 m | Yeonggwang (DT_0003) |
| Suncheon Bay | South coast (Jeonnam) | 34.90°N, 127.50°E | ~3 m | Yeosu (DT_0016) |

## Repository layout

```
tidal-sampling-bias/
├── manuscript/                 # JMSE submission (source of truth = the *.md files)
│   ├── draft_mdpi.md           #   main text  → draft_mdpi.{pdf,docx}
│   ├── supplementary.md        #   supplementary → supplementary.{pdf,docx}
│   ├── cover_letter_mdpi.md    #   cover letter → cover_letter_mdpi.pdf
│   ├── jmse_submission/        #   self-contained MDPI LaTeX package (jmse.tex + Definitions/ + figures/)
│   ├── figures/                #   final figures embedded in the markdown build
│   ├── references.bib          #   bibliography (pandoc citeproc)
│   └── mdpi.csl                #   MDPI citation style
├── src/                        # Analysis library (gee / tides / analysis / visualization)
├── scripts/                    # Runnable entry points (analysis, figures, builds)
├── config/                     # Site definitions (config/sites.yaml) and settings
├── data/                       # Inputs + derived outputs — NOT tracked (see .gitignore)
└── requirements.txt
```

`data/` (FES2022b grids, raw KHOA/GEE pulls, derived tables/figures) is
**git-ignored**; everything is reproducible from the steps below. Legacy
working files (the earlier RSE-targeted draft, Korean translation, the
superseded Remote Sensing LaTeX submission, etc.) are kept locally but are not
tracked.

## Reproduce

### 0. Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # pandas, numpy, scipy, earthengine-api, matplotlib, cartopy, …
brew install pandoc tectonic             # for the manuscript PDF build
```

FES2022b tide synthesis uses **pyfes** (the CNES/AVISO engine; see
`src/tides/`). Scripts are run from the project root with the root on
`PYTHONPATH`:

```bash
PYTHONPATH=. python scripts/<name>.py
```

### 1. Inputs / credentials

| Input | Source | Setup |
|---|---|---|
| Satellite scene metadata | Google Earth Engine (L8/L9/S2 collections) | `earthengine authenticate` |
| Hourly tide observations | KHOA Open API (`apis.data.go.kr/1192136`) | put key in `.khoa_api_key` |
| FES2022b global tide model | AVISO+ (registration) | grids under `data/raw/fes2022b/`; creds in `.aviso_credentials` |

Only acquisition **metadata** is pulled from GEE (no pixel downloads); cached
pulls live under `data/raw/` and `data/processed/`.

### 2. Run the analysis (regenerates figures + tables under `data/outputs/`)

```bash
PYTHONPATH=. python scripts/generate_study_area_map.py          # study-area map (Figure 1)
PYTHONPATH=. python scripts/demo_aliasing_multisite.py          # tide-height distributions + aliasing metrics
PYTHONPATH=. python scripts/demo_phase_analysis.py              # overpass-phase roses + β·A·⟨cosθ⟩ regression
PYTHONPATH=. python scripts/demo_phase_stability.py             # year/season/sensor stability + LOO validation
PYTHONPATH=. python scripts/demo_dem_error.py                   # elevation-domain error, truncation, DEM budget
PYTHONPATH=. python scripts/demo_harmonic_decomposition.py      # M₂ amplitude variants (Table S2)
PYTHONPATH=. python scripts/fes2022b_sensitivity.py             # FES2022b global-model variant (Table S2)
PYTHONPATH=. python scripts/demo_cos_theta_convergence_garorim.py  # 5-month-optimum cos θ trajectory (§5.3)
PYTHONPATH=. python scripts/demo_lee2025_comparison.py          # comparison with Lee, J. et al. (2025)
```

Figures are written to `data/outputs/figures/` and the underlying tables to
`data/outputs/tables/`. The repository already ships the final figure copies
under `manuscript/figures/`.

### 3. Build the manuscript

PDFs use the pandoc → tectonic pipeline (continuous line numbers, double
spacing, MDPI numeric citations via `mdpi.csl`):

```bash
bash scripts/build_mdpi.sh all       # draft_mdpi, cover_letter_mdpi, supplementary
# or one at a time:  draft | cover | supp
```

Word versions (raw-LaTeX tables/figures converted to native Word tables,
images and OMML equations):

```bash
python scripts/build_docx.py draft_mdpi      # main text  → draft_mdpi.docx
python scripts/build_docx.py supp            # supplementary → supplementary.docx
```

The self-contained MDPI LaTeX submission compiles directly:

```bash
cd manuscript/jmse_submission && tectonic jmse.tex
```

## Data and code availability

Raw KHOA tide-gauge data are public via the Korea Open Data Portal
(`apis.data.go.kr/1192136`); GEE scene metadata is reproducible from the public
collections `LANDSAT/LC08/C02/T1_L2`, `LANDSAT/LC09/C02/T1_L2`,
`COPERNICUS/S2_HARMONIZED`. The derived tables, analytical pipeline, and
figure-generation scripts are released as a Zenodo-archived snapshot of this
repository (`tidal-sampling-bias`); the DOI will be assigned upon acceptance.

## Citation

Song, T.; Kim, M. *A Gauge-Free Predictive Model for the Tidal-Sampling Bias of
Sun-Synchronous Satellites, Validated on Macrotidal Tidal Flats.* Journal of
Marine Science and Engineering (under review). DOI to be assigned.

## License

Code (`src/`, `scripts/`, `config/`, `notebooks/`) is released under the MIT
License (see [`LICENSE`](LICENSE)). The manuscript text and figures under
`manuscript/` are © the authors and are available under CC BY 4.0 upon
publication per the journal's open-access policy.

## Key references

- Bishop-Taylor, R. et al. (2019). Between the tides… *Estuarine, Coastal and Shelf Science* 223, 115–128.
- Bishop-Taylor, R. et al. (2025). eo-tides: tide-modelling tools for large-scale EO. *JOSS* 10(109), 7786.
- Sagar, S. et al. (2017). Extracting the intertidal extent and topography… *Remote Sensing of Environment* 195, 153–169.
- Ryu, J.-H. et al. (2002). Waterline extraction from Landsat TM data in a tidal flat: Gomso Bay, Korea. *Remote Sensing of Environment* 83(3), 442–456.
- Lyard, F. et al. (2021) / Carrère, L. et al. (2022). FES2014 / FES2022 global ocean tide atlases. AVISO+.

Full bibliography in [`manuscript/references.bib`](manuscript/references.bib).
