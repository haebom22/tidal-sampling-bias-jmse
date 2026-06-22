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

\hfill Taeyoon Song · Inha University and Haebom Data Inc.

\hfill #904, Gasan A1 Tower, 205-27 Gasan 1-ro, Geumcheon-gu, Seoul 08503, Republic of Korea

\hfill tysong@haebomdata.com · 22 June 2026

\vspace{1.2em}

To the Editors of *Journal of Marine Science and Engineering* (MDPI)

\vspace{0.6em}

Dear Editors,

We are pleased to submit our manuscript, **"A Gauge-Free Predictive Model for the Tidal-Sampling Bias of Sun-Synchronous Satellites, Validated on Macrotidal Tidal Flats,"** for consideration as a research article in *Journal of Marine Science and Engineering*.

**The gap we address.** The waterline method underpins most operational intertidal Digital Elevation Models (DEMs), including the Digital Earth Australia Intertidal product (Bishop-Taylor et al., 2019), the global tidal-flat distributions of Murray et al. (2019, *Nature*), and a recent multi-sensor optimisation for the Korean west coast by Lee, J. et al. (2025, *Estuarine, Coastal and Shelf Science* 318, 109235). All of these rely on the assumption that satellite imagery samples the local tidal cycle without systematic bias. Bishop-Taylor et al. (2019) flagged this assumption as questionable for sun-synchronous orbits, but no closed-form prediction of the resulting bias has been published, and the empirical workarounds proposed since — such as Lee, J. et al.'s 5-month multi-sensor data-collection window — leave the *physical reason* for the optimum unquantified.

**What we contribute.** Using 5,082 cloud-screened Landsat-8/9 and Sentinel-2 scenes (2020–2024) over five tidal flats spanning the western and southern Korean coast, with hourly Korea Hydrographic and Oceanographic Agency (KHOA) tide-gauge data, we derive and validate a single closed-form model — mean bias ≈ β · A · ⟨cos θ⟩ — that predicts the systematic tide-sampling bias from local tidal amplitude and satellite-overpass phase alone. It explains 98 % of the cross-site, cross-sensor variance and, crucially, is reproduced from the global FES2022b tide model with the bias sign correct at every site, making the correction applicable worldwide without any local gauge. To our knowledge this is the first analytical, *a priori* bias-correction tool for the optical-waterline workflow; we also give an explicit quantitative demonstration that the bias *changes sign* across a regional amphidromic gradient — negative (low-tide) on the macrotidal west coast, positive (high-tide) at south-coast Suncheon Bay. Translated into the elevation domain, the bias implies metre-scale vertical errors and permanently unsampled intertidal bands up to 2.5 km wide that no increase in optical revisit frequency can recover.

**Relation to recent Korean tidal-flat DEM work.** We note two recent and highly relevant Korean studies in this topical neighbourhood: (i) **Lee, J. et al. (2025, ECSS 318, 109235)** empirically optimised an optical+SAR fusion DEM on the Taean Peninsula, reporting a 5-month minimum data-collection window with a mean absolute error of 25.6 cm against UAV-LiDAR; and (ii) **Lee, K. et al. (2022, *Frontiers in Marine Science* 9, 810549)** showed that altimetry-sampling-phase shifts inflate apparent sea-level-rise trends near Incheon. Our paper is **complementary to, not redundant with, both**: Lee, J. et al. (2025) characterise the phenomenon *empirically* and propose an operational solution, whereas we provide the *first-principles model* that explains *why* their 5-month optimum exists and *predicts* its coast-dependent variation (Section 5.3); Lee, K. et al. (2022) address the *temporal* drift of sampling phase within altimetry footprints, whereas we address the *spatial* counterpart for the optical-waterline workflow. Geographically, our five sites *bracket without duplicating* the Taean Peninsula coverage of Lee, J. et al. (Garorim Bay lies ~30 km north; Suncheon Bay extends the analysis to a south-coast amphidromic regime outside their study area). Section 1.3 and Table 1 of the manuscript place this paper explicitly in that landscape.

**Why *Journal of Marine Science and Engineering*.** This study sits squarely within the *Physical Oceanography* scope of JMSE, which expressly encourages theoretical, observational (in situ or remote-sensing), and modelling studies of coastal and estuarine processes. It is a natural fit alongside JMSE's established work on tidal dynamics and the satellite observation of tidal coasts — including accuracy assessment of global ocean-tide models against tide gauges in the East-Asian marginal seas, cotidal-chart analysis of the Yellow and Bohai Seas, waterline/intertidal-foreshore detection, and optical-plus-SAR shoreline mapping on macro-tidal coasts. The correction itself is region-agnostic: it depends only on local tidal amplitude and satellite overpass phase, both available from any global tide model (FES2022b, TPXO) and satellite ephemeris, so the sign-reversing bias polarity we report recurs wherever amphidromic phase gradients comparable to 1/4 of an M₂ cycle exist (Bay of Fundy, southern North Sea, the Wash, the Australian north coast). As a concrete mission-design implication, our model predicts that a two-satellite optical constellation with overpass times staggered by 3 h (1/4 M₂ cycle) would halve the systematic bias — a gain unattainable by any increase in revisit frequency on a single sun-synchronous orbit. The manuscript therefore (a) provides a ready-to-use *a priori* bias correction for the global waterline-DEM community, (b) supplies the physical basis for multi-sensor DEM optimisation in macrotidal regions, and (c) informs the design of next-generation intertidal-observing missions — squarely within JMSE's coverage of physical oceanography and the satellite observation of coastal and intertidal environments.

**Submission status.** The manuscript is original, has not been published or submitted elsewhere, and all authors have approved the submission. All raw KHOA observations and Google Earth Engine scene-metadata queries are publicly accessible; derived tables and analysis scripts will be deposited in a Zenodo-archived GitHub repository upon acceptance. This research was supported by the 2026 National Blue Carbon Monitoring project of the Korea Marine Environment Management Corporation (KOEM; No. R26TA01845857-00), which had no role in the study or the decision to publish; both authors are employees of Haebom Data Inc. and declare no other conflict of interest. The full funding and conflict-of-interest statements are provided in the manuscript.

We hope you find the manuscript suitable for *Journal of Marine Science and Engineering* and look forward to the review process.

\vspace{0.6em}

Sincerely,

\vspace{0.8em}

Taeyoon Song (on behalf of both authors)

Inha University and Haebom Data Inc., Republic of Korea · tysong@haebomdata.com

\vspace{0.6em}

\noindent\textbf{Suggested reviewers} (three internationally recognised experts spanning ocean-tide dynamics and the satellite observation of tidal coasts, with no prior collaboration with the authors; we leave any further reviewer selection to the Editor's discretion. E-mail addresses supplied in the submission system):

- **Richard D. Ray** — NASA Goddard Space Flight Center, USA (ocean tides and the tidal aliasing of satellite sampling — the physical basis this study builds on)
- **Robbi Bishop-Taylor** — Geoscience Australia (Digital Earth Australia Intertidal and tidal-aliasing diagnostics — the operational waterline-DEM context this study addresses)
- **Gary D. Egbert** — Oregon State University, USA (global ocean-tide modelling, TPXO, and tide-model validation against tide gauges)

\noindent\textbf{Opposed reviewers:} none.
