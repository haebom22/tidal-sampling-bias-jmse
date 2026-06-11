---
title: ""
documentclass: article
classoption: [11pt, a4paper]
geometry: margin=2.4cm
mainfont: "STIX Two Text"
sansfont: "Helvetica Neue"
fontsize: 11pt
linestretch: 1.20
header-includes:
  - \usepackage{microtype}
  - \usepackage{unicode-math}
  - \usepackage{newunicodechar}
  - \newunicodechar{⟨}{\ensuremath{\langle}}
  - \newunicodechar{⟩}{\ensuremath{\rangle}}
  - \newunicodechar{≈}{\ensuremath{\approx}}
  - \newunicodechar{·}{\ensuremath{\cdot}}
  - \newunicodechar{β}{\ensuremath{\beta}}
  - \newunicodechar{θ}{\ensuremath{\theta}}
  - \newunicodechar{₂}{\ensuremath{_2}}
  - \pagestyle{empty}
  - \setlength{\parskip}{0.45em}
  - \setlength{\parindent}{0pt}
---

\vspace*{0.2em}

\hfill [Author name TBD] · [Affiliation TBD]

\hfill [email] · [date: 2026-05-25]

\vspace{1.2em}

To the Editors of *Remote Sensing of Environment*

\vspace{0.6em}

Dear Editors,

We are pleased to submit our manuscript, **"Phase-Predictable Tidal-Sampling Bias of Sun-Synchronous Optical Satellites and Its Conversion into Waterline-DEM Errors over the Macrotidal Korean Coast,"** for consideration as an Original Research Article in *Remote Sensing of Environment*.

**The gap we address.** The waterline method underpins most operational intertidal Digital Elevation Models (DEMs), including the Digital Earth Australia Intertidal product (Bishop-Taylor et al., 2019), the global tidal-flat distributions of Murray et al. (2019, *Nature*), and a recent multi-sensor optimisation for the Korean west coast by Lee et al. (2025, *Estuarine, Coastal and Shelf Science* 318, 109235). All of these rely on the assumption that satellite imagery samples the local tidal cycle without systematic bias. Bishop-Taylor et al. (2019b) flagged this assumption as questionable for sun-synchronous orbits, but no closed-form prediction of the resulting bias has been published. The empirical workarounds proposed since then — including Lee et al.'s 5-month multi-sensor data-collection window — leave the *physical reason* for the optimum unquantified.

**What we contribute.** Using 5,082 cloud-screened Landsat-8/9 and Sentinel-2 scenes (2020–2024) over five tidal flats spanning the entire western and southern Korean coast, coupled with hourly Korea Hydrographic and Oceanographic Agency (KHOA) gauge observations, we derive and validate a single closed-form bias-prediction model: $\text{mean bias} \approx \beta \cdot A \cdot \langle \cos\theta \rangle$, where $A$ is the local tidal amplitude and $\langle \cos\theta \rangle$ is the mean cosine of the satellite-overpass phase. The model explains 98 % of the cross-site, cross-sensor variance (β = 1.78, 95 % CI 1.44–1.91), is stable across years, seasons, and sensors (leave-one-site-out RMSE = 0.16 m, 15/15 correct sign), and translates via quantile mapping into DEM-equivalent vertical elevation RMSE of 0.36–1.09 m — equivalent to permanently unsampled intertidal bands up to 2.5 km wide on Ganghwa-do. The departure β > 1 is itself a *physical diagnostic*: it decomposes analytically into a spring–neap × overpass-phase covariance term rather than residual scatter. A complementary sensitivity test replacing the KHOA reference with the global FES2022b ocean tide model (Carrère et al., 2022) reproduces the fit (β = 1.70, R² = 0.983, LOO RMSE = 0.11 m) with the bias sign correct at every site, confirming that the correction is applicable worldwide without any local tide-gauge access. To our knowledge this is the first analytical, *a priori* bias-correction tool of this kind for the optical-waterline workflow.

**Relation to recent Korean tidal-flat DEM work.** We are aware of two recent and highly relevant Korean studies that share this paper's topical neighbourhood: (i) **Lee et al. (2025, ECSS 318, 109235)** empirically optimised an optical+SAR fusion DEM on the Taean Peninsula and reported a 5-month minimum data-collection window with mean absolute error (MAE) 25.6 cm against UAV-LiDAR; and (ii) **Lee, K. et al. (2022, *Frontiers in Marine Science* 9, 810549)** demonstrated that altimetry-sampling-phase shifts inflate apparent sea-level-rise trends near Incheon. Our paper is **complementary, not redundant, to both**: Lee et al. (2025) characterise the phenomenon *empirically* and propose an operational solution; we provide the *first-principles model* that explains *why* their 5-month optimum exists and *predicts* coast-dependent variations of that optimum (Section 5.3, point c, of our manuscript). Lee, K. et al. (2022) address the *temporal* drift of sampling phase within altimetry footprints; we address the *spatial* counterpart for the optical-waterline workflow. Geographically, our five sites *bracket* without duplicating Lee et al.'s Taean Peninsula coverage: Garorim Bay (37.0 °N) lies ~30 km north of their Geunso Bay site, and Suncheon Bay (34.9 °N) extends the analysis to a south-coast amphidromic regime outside their study area. Section 1.3, Table 1 of the manuscript places this paper explicitly in that literature landscape.

**Why *Remote Sensing of Environment*.** The closed-form correction tool is region-agnostic: it depends only on local tidal amplitude and satellite overpass phase, both available from any global tide model (FES2022b, TPXO9) and satellite ephemeris. The bipolar bias polarity we report on the Korean coast is a *spatial* manifestation of a global mechanism that will recur wherever amphidromic phase gradients comparable to 1/4 M₂ cycle exist (Bay of Fundy, southern North Sea, the Wash, Australian north coast). As a concrete mission-design implication, our model predicts that a two-satellite optical constellation with overpass times staggered by 3 h (1/4 M₂ cycle) would halve the systematic bias — a gain unattainable by any increase in revisit frequency on a single sun-synchronous orbit. The manuscript thus aims to (a) provide a ready-to-use *a priori* bias correction for the existing global waterline-DEM community, (b) supply the physical basis for future multi-sensor DEM-optimisation work in macrotidal regions, and (c) inform the design of next-generation intertidal-observing missions — all squarely within *RSE*'s remit.

**Submission status.** The manuscript is original, has not been published or submitted elsewhere, and all authors have approved the submission. All raw KHOA observations and Google Earth Engine scene-metadata queries are publicly accessible; derived parquet tables and analysis scripts will be deposited in a Zenodo-archived GitHub repository upon acceptance. We declare no conflicts of interest.

We hope you find the manuscript suitable for *RSE* and look forward to the editorial process.

\vspace{0.6em}

Sincerely,

\vspace{0.8em}

[Author name TBD]

[Affiliation · email]

\vspace{0.6em}

\noindent\textbf{Suggested reviewers (non-conflicting; the authors have no prior collaboration with any of these):}

- Robbi Bishop-Taylor — Geoscience Australia (waterline accuracy, DEA Intertidal product)
- Nicholas J. Murray — James Cook University (tidal-flat global mapping)
- Edward Salameh — Université de Caen Normandie (intertidal remote sensing review)
- Joo-Hyung Ryu — Korea Institute of Ocean Science & Technology (Korean tidal-flat DEM specialist; coauthor of Lee et al. 2025 — would provide critical evaluation of the differentiation argument)
- Florent H. Lyard — LEGOS/CNRS (global tide modelling, FES2014 / FES2022b)
