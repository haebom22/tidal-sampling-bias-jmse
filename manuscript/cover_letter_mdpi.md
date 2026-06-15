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

\hfill Taeyoon Song · Haebom Data Inc.

\hfill #904, Gasan A1 Tower, 205-27 Gasan 1-ro, Geumcheon-gu, Seoul 08503, Republic of Korea

\hfill tysong@haebomdata.com · 13 June 2026

\vspace{1.2em}

To the Editors of *Remote Sensing* (MDPI)

\vspace{0.6em}

Dear Editors,

We are pleased to submit our manuscript, **"Predicting Tidal-Sampling Bias of Sun-Synchronous Satellites from Overpass Phase: Theory and Validation on Macrotidal Coasts,"** for consideration as a research article in *Remote Sensing*.

**The gap we address.** The waterline method underpins most operational intertidal Digital Elevation Models (DEMs), including the Digital Earth Australia Intertidal product (Bishop-Taylor et al., 2019), the global tidal-flat distributions of Murray et al. (2019, *Nature*), and a recent multi-sensor optimisation for the Korean west coast by Lee et al. (2025, *Estuarine, Coastal and Shelf Science* 318, 109235). All of these rely on the assumption that satellite imagery samples the local tidal cycle without systematic bias. Bishop-Taylor et al. (2019) flagged this assumption as questionable for sun-synchronous orbits, but no closed-form prediction of the resulting bias has been published, and the empirical workarounds proposed since — such as Lee et al.'s 5-month multi-sensor data-collection window — leave the *physical reason* for the optimum unquantified.

**What we contribute.** Using 5,082 cloud-screened Landsat-8/9 and Sentinel-2 scenes (2020–2024) over five tidal flats spanning the entire western and southern Korean coast, coupled with hourly Korea Hydrographic and Oceanographic Agency (KHOA) gauge observations, we derive and validate a single closed-form bias-prediction model: mean bias ≈ β · A · ⟨cos θ⟩, where A is the local tidal amplitude and ⟨cos θ⟩ the mean cosine of the satellite-overpass phase. The model explains 98 % of the cross-site, cross-sensor variance (β = 1.78, 95 % CI 1.44–1.91), is stable across years, seasons, and sensors (leave-one-site-out RMSE = 0.16 m, 15/15 correct sign), and translates via quantile mapping into a DEM-equivalent vertical RMSE of 0.36–1.09 m — equivalent to permanently unsampled intertidal bands up to 2.5 km wide at Ganghwa-do. The departure β > 1 is itself a *physical diagnostic*: it decomposes analytically into a spring–neap × overpass-phase covariance term rather than residual scatter. Crucially, replacing the local KHOA reference with the global FES2022b ocean tide model reproduces the fit (β = 1.70, R² = 0.983, LOO RMSE = 0.11 m) with the bias sign correct at every site, confirming that the correction is applicable worldwide without any local tide-gauge access. To our knowledge this is the first analytical, *a priori* bias-correction tool of this kind for the optical-waterline workflow. We also report the first quantitative demonstration that the bias *changes sign* across a regional amphidromic phase gradient — negative (low-tide) on the macrotidal west coast, positive (high-tide) at south-coast Suncheon Bay.

**Relation to recent Korean tidal-flat DEM work.** We note two recent and highly relevant Korean studies in this topical neighbourhood: (i) **Lee et al. (2025, ECSS 318, 109235)** empirically optimised an optical+SAR fusion DEM on the Taean Peninsula, reporting a 5-month minimum data-collection window with a mean absolute error of 25.6 cm against UAV-LiDAR; and (ii) **Lee, K. et al. (2022, *Frontiers in Marine Science* 9, 810549)** showed that altimetry-sampling-phase shifts inflate apparent sea-level-rise trends near Incheon. Our paper is **complementary to, not redundant with, both**: Lee et al. (2025) characterise the phenomenon *empirically* and propose an operational solution, whereas we provide the *first-principles model* that explains *why* their 5-month optimum exists and *predicts* its coast-dependent variation (Section 5.3); Lee, K. et al. (2022) address the *temporal* drift of sampling phase within altimetry footprints, whereas we address the *spatial* counterpart for the optical-waterline workflow. Geographically, our five sites *bracket without duplicating* the Taean Peninsula coverage of Lee et al. (Garorim Bay lies ~30 km north; Suncheon Bay extends the analysis to a south-coast amphidromic regime outside their study area). Section 1.3 and Table 1 of the manuscript place this paper explicitly in that landscape.

**Why *Remote Sensing*.** The correction tool is region-agnostic: it depends only on local tidal amplitude and satellite overpass phase, both available from any global tide model (FES2022b, TPXO9) and satellite ephemeris. The bipolar bias polarity we report is a *spatial* manifestation of a global mechanism that will recur wherever amphidromic phase gradients comparable to 1/4 of an M₂ cycle exist (Bay of Fundy, southern North Sea, the Wash, the Australian north coast). As a concrete mission-design implication, our model predicts that a two-satellite optical constellation with overpass times staggered by 3 h (1/4 M₂ cycle) would halve the systematic bias — a gain unattainable by any increase in revisit frequency on a single sun-synchronous orbit. The manuscript therefore (a) provides a ready-to-use *a priori* bias correction for the existing global waterline-DEM community, (b) supplies the physical basis for future multi-sensor DEM optimisation in macrotidal regions, and (c) informs the design of next-generation intertidal-observing missions — topics squarely within the scope of *Remote Sensing*'s coverage of satellite remote sensing of coastal and intertidal environments.

**Submission status.** The manuscript is original, has not been published or submitted elsewhere, and all authors have approved the submission. All raw KHOA observations and Google Earth Engine scene-metadata queries are publicly accessible; derived tables and analysis scripts will be deposited in a Zenodo-archived GitHub repository upon acceptance. The authors declare no conflicts of interest.

We hope you find the manuscript suitable for *Remote Sensing* and look forward to the review process.

\vspace{0.6em}

Sincerely,

\vspace{0.8em}

Taeyoon Song (on behalf of both authors)

Haebom Data Inc., Republic of Korea · tysong@haebomdata.com

\vspace{0.6em}

\noindent\textbf{Suggested reviewers} (international experts with no prior collaboration with the authors; e-mail addresses supplied in the submission system):

- **Robbi Bishop-Taylor** — Geoscience Australia (Digital Earth Australia Intertidal; tidal-aliasing diagnostics — the work this study extends)
- **Stephen Sagar** — Geoscience Australia (continental-scale intertidal extent and topography)
- **Nicholas J. Murray** — James Cook University, Australia (global tidal-flat distribution and change)
- **Kuo-Hsin Tseng** — National Central University, Taiwan (optical reconstruction of time-varying tidal-flat topography)
- **Nan Xu** — Shenzhen University, China (ICESat-2 + Sentinel-2 intertidal topography and vertical referencing)

\noindent\textbf{Opposed reviewers:} none.
