# Figure & Table captions — quick-reference summary

> Authoritative captions are embedded inline in `draft.md` (main-text)
> and `supplementary.md` (Figure S1–S7, Tables S1–S2). This file is a
> filename ↔ figure-number map for the production team.

## Main-text figures (Figure 1–7)

| # | File (`manuscript/figures/`)               | Topic                                  |
|---|--------------------------------------------|----------------------------------------|
| 1 | `fig1_study_area.png`                       | Five-site study area + KHOA gauges     |
| 2 | `fig2_distribution_grid.png`                | Tide-height densities per site & sensor |
| 3 | `fig3_bipolar_bias.png`                     | Cross-site aliasing metrics (bipolarity)|
| 4 | `fig4_phase_polar.png`                      | Rose-diagram of overpass tide phase    |
| 5 | `fig5_phase_bias_regression.png`            | Mean bias vs *A* · ⟨cos θ⟩ (β = 1.78)   |
| 6 | `fig7_loo_validation.png`                   | Leave-one-site-out validation          |
| 7 | `fig9_truncation_bands.png` (panel a) + `fig10_horizontal_error.png` (panel b) | Waterline-DEM coverage: truncated bands (a) + vertical/horizontal RMSE (b) |

> Figure 7 is a two-panel composite (raw-LaTeX `figure` in `draft.md`);
> the two source PNGs are stacked as panels (a) and (b) under one caption.

## Supplementary figures (Figure S1–S7)

| #   | File (`manuscript/figures/`)              | Topic                                       |
|-----|-------------------------------------------|---------------------------------------------|
| S1  | `figS1_cdf_grid.png`                      | Cross-site CDFs (companion to Fig. 2)        |
| S2  | `figS2_overpass_hours.png`                | Hour-of-day of satellite overpasses          |
| S3  | `fig6_stability_coefficients.png`         | β and R² stability bars (companion to Fig. 5)|
| S4  | `figS3_stability_panels.png`              | Stability scatter (companion to Fig. S3)     |
| S5  | `figS4_phase_tide_scatter.png`            | Phase vs tide-height, per site               |
| S6  | `fig8_dem_error_curves.png`               | Elevation-domain DEM error curves            |
| S7  | `figS6_schematic.png`                     | Planar tidal-flat schematic cross-sections   |

> Moved to Supplementary for RSE (main-text figure diet): the stability
> coefficient bars (now S3, formerly main Fig. 6) and the elevation-domain
> DEM error curves (now S6, formerly main Fig. 8).
> Removed entirely: `figS5_phase_coverage_bar.png` (⟨cos θ⟩-vs-bias bars),
> redundant with main-text Figure 5.
> The four-variant robustness fit of Eq. 1 (variants a–d, incl. FES2022b)
> is presented numerically in Table S2; no separate figure is included.

## Tables

| #   | Source                                                     | Topic                                |
|-----|------------------------------------------------------------|--------------------------------------|
| 1   | LaTeX table in `draft.md`, §1.3                            | Positioning within Korean DEM/sampling literature |
| 2   | LaTeX table in `draft.md`, §2.3                            | Data inventory (5 sites × 3 sensors) |
| 3   | LaTeX table in `draft.md`, §4.1                            | Cross-site aliasing metrics          |
| S1  | Inline in `supplementary.md` (a–e); sources under `data/outputs/tables/` | Stability regression coefficients |
| S2  | Inline in `supplementary.md` (a–b)                         | Robustness to amplitude/reference (incl. FES2022b) |
