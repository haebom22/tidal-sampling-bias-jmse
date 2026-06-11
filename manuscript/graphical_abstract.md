---
title: "Graphical abstract — design spec"
---

# Graphical abstract (optional, per RSE Guide for Authors)

RSE encourages, but does not require, a single-image graphical abstract
that captures the main finding at a glance. This file documents the
intended composition; the rendered image is to be saved at:

```
manuscript/figures/graphical_abstract.png         (raster, ≥ 300 DPI)
manuscript/figures/graphical_abstract.pdf         (vector, preferred)
```

## Recommended dimensions

| Parameter         | RSE spec                |
|-------------------|-------------------------|
| Width × height    | 1328 × 531 px @ 300 DPI |
|                   | (≈ 11.26 × 4.50 cm)     |
| File size         | < 15 MB                 |
| Format            | PNG / TIFF / PDF / EPS  |
| Text size         | ≥ 6 pt at print size    |

## Visual composition (three horizontal panels, left → right)

1. **Cause** — sun-synchronous satellite icon (Landsat 8/9, Sentinel-2)
   above a clock showing 10:30 LST, with an arrow down to a tide-cycle
   sketch where only the LW (low-water) shoulder is highlighted with
   sample dots. Tag-line: *"Optical satellites sample the tide at a
   fixed local time."*

2. **Mechanism** — the single closed-form equation in display style:

   $$\text{mean bias} \;=\; \beta \cdot A \cdot \langle\cos\theta\rangle,
     \qquad \beta = 1.78,\ R^2 = 0.98$$

   below which a small scatter plot (15 points) shows the regression
   line, with a faint over-plotted FES2022b-only fit
   ($\beta = 1.70,\ R^2 = 0.986$) annotated *"reproduced from a global
   tide model alone."* Tag-line: *"A one-parameter model captures the
   bias — and is portable worldwide."*

3. **Consequence** — a stylised Korean Peninsula outline (W coast +
   south coast) with red minus signs over Ganghwa-do / Garorim /
   Gomso / Hampyeong and a blue plus sign over Suncheon Bay,
   illustrating the bipolar sign of the elevation error, with the
   header *"–1.1 m to +0.3 m in the satellite waterline DEM."*
   A small footnote-style line below reads *"up to 2.5 km of
   permanently unsampled tidal-flat width on Ganghwa-do."*

## Colour palette (sensor-consistent with main figures)

| Element     | Hex     |
|-------------|---------|
| Landsat 8   | `#E69F00` (orange) |
| Landsat 9   | `#D55E00` (red)    |
| Sentinel-2  | `#9467BD` (purple) |
| Negative bias zone | `#D62728` (RSE-safe red) |
| Positive bias zone | `#1F77B4` (RSE-safe blue) |
| Background  | white   |

## Build instructions

A reference Python script for rendering this composition is left for
the figure-finalisation pass:

```bash
python scripts/draw_graphical_abstract.py       # to be added
```

Until then, the cover letter and main-text Figures 1, 4, and 5 can be
combined manually in Inkscape / Illustrator to produce the abstract.

> **Status:** *Optional and deferred to the figure-finalisation pass*;
> the manuscript can be submitted to RSE without it (the journal
> editor will simply not display a graphical abstract on the article
> landing page).
