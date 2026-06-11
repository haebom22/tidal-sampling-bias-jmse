# Manuscript folder

First-draft research paper bundle for the Korean tidal-aliasing
study (B-2 → B-5).

## Contents

```
manuscript/
├── README.md                    this file
├── draft.md                     full paper draft (English, ~6,800 words)
├── abstract_ko.md               Korean abstract + section outline
├── figure_captions.md           detailed captions (main + supplementary)
├── references.bib               BibTeX entries (≈ 20 references)
└── figures/
    ├── fig1_study_area.png            Study sites map (Cartopy)
    ├── fig3_distribution_grid.png     Cross-site tide distributions
    ├── fig4_bipolar_bias.png          Spread/offset/bias bars per site
    ├── fig5_phase_polar.png           Polar histograms of overpass phase
    ├── fig6_phase_bias_regression.png Phase × bias regression (R²=0.98)
    ├── fig7_stability_coefficients.png Slope & R² stability bars
    ├── fig8_loo_validation.png        Leave-one-site-out validation
    ├── fig9_dem_error_curves.png      Per-quantile DEM error curves
    ├── fig10_truncation_bands.png     Sampled vs missing elevation
    ├── fig11_schematic.png            Planar tidal-flat cross-sections
    ├── fig12_horizontal_error.png     Vertical vs horizontal error
    └── figS1..S5_*.png                Supplementary figures
```

## Word count

```
abstract:            ~280 words
introduction:        ~880 words
methods:             ~880 words
results:           ~1,540 words
discussion:        ~1,400 words
conclusions:         ~300 words
————————————————————————————
total (excl refs):  ~5,300 words
```

## How to compile

> **Project rule.** The manuscript PDFs (`draft.pdf`, `cover_letter.pdf`)
> MUST be built with the LaTeX pipeline. Never use `weasyprint`,
> `playwright`, or `~/.cursor/tools/md2pdf.py` for the manuscript:
> those silently ignore the LaTeX header (`\linenumbers`, `linestretch`,
> `geometry`), so RSE's mandatory continuous line numbering, double
> spacing, and 2.5 cm margins will be missing from the output PDF.

### One-line build

From the project root:

```bash
bash scripts/build_manuscript_pdf.sh           # builds both PDFs
bash scripts/build_manuscript_pdf.sh draft     # only draft.pdf
bash scripts/build_manuscript_pdf.sh cover     # only cover_letter.pdf
```

### What the script runs under the hood

```bash
pandoc manuscript/draft.md \
    --pdf-engine=tectonic \
    --variable=papersize:a4 \
    -o manuscript/draft.pdf
```

### Dependencies

- `pandoc`            ≥ 3.0       (`brew install pandoc`)
- `tectonic`          ≥ 0.15      (`brew install tectonic`)
- macOS-default fonts: **STIX Two Text** + **STIX Two Math** + Helvetica Neue + Menlo (all pre-installed on macOS 13+)

The first compile downloads ~80 MB of LaTeX packages into
`~/Library/Caches/Tectonic/`; subsequent compiles take ~10 s.

The result is a single-column 11 pt A4 PDF (~31 pages, 2.5 MB) with
NavyBlue sectioned headings, booktabs tables, embedded figures with
LaTeX `\caption{}` numbering, **continuous line numbering on every
line** (required by RSE), double spacing (`linestretch: 2.0`), 2.5 cm
margins, and proper rendering of all unicode math glyphs (β, θ,
⟨cos θ⟩, R², ∞, etc.) through the STIX Two font family.

### Journal-native LaTeX

For final submission, use the publisher template (`elsarticle.cls`
for *Remote Sensing of Environment*, `copernicus.cls` for Copernicus
journals, etc.) and import the figure files from
`manuscript/figures/` directly.  The YAML front-matter of `draft.md`
already provides the title, abstract, keywords and most font options
needed by a typical template.

## Reviewer checklist (before submission)

- [ ] Author list, affiliations, ORCIDs
- [ ] Funding sources and acknowledgements
- [ ] BibTeX DOIs verified
- [ ] Figures retraced at 600+ dpi for journal style
- [ ] Supplementary tables (annual / seasonal / sensor / bootstrap / LOO)
      formatted as separate CSV files
- [ ] Code/data DOI from Zenodo embedded
- [ ] Compliance with journal style (e.g. *Remote Sensing of Environment*
      double-spaced, line numbered)

## Open items / future work

1. Confirm site-specific tidal-flat slopes (currently first-order
   estimates) using LiDAR / SRTM hypsometry.
2. Add SAR-based bias-removal experiment (Sentinel-1 6/18 LST).
3. Generalise to additional macrotidal coasts (Bay of Fundy, North Sea).
4. Convert vertical error → tidal-flat *area* error via per-site
   hypsometric area function.
