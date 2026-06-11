---
title: |
  Predicting tidal-sampling bias of sun-synchronous satellites from overpass phase: theory and validation on macrotidal coasts
author:
  - "[Author name TBD]^1^"
date: "First draft v0.1 — 2026-05-21 · Target journal: *Remote Sensing of Environment* · ~6,900 words (incl. References)"
documentclass: article
classoption: [11pt, a4paper]
geometry: margin=2.5cm
linkcolor: NavyBlue
urlcolor: NavyBlue
colorlinks: true
numbersections: false
fontsize: 11pt
linestretch: 2.0
mainfont: "STIX Two Text"
sansfont: "Helvetica Neue"
monofont: "Menlo"
mathfont: "STIX Two Math"
header-includes:
  - \usepackage[svgnames]{xcolor}
  - \usepackage{microtype}
  - \usepackage{booktabs}
  - \usepackage{longtable}
  - \usepackage{float}
  - \floatplacement{figure}{!htbp}
  - \usepackage{array}
  - \usepackage{lineno}
  - \linenumbers
  - \modulolinenumbers[1]
  - \usepackage{unicode-math}
  - \usepackage{newunicodechar}
  - \newunicodechar{⟨}{\ensuremath{\langle}}
  - \newunicodechar{⟩}{\ensuremath{\rangle}}
  - \newunicodechar{≥}{\ensuremath{\geq}}
  - \newunicodechar{≤}{\ensuremath{\leq}}
  - \newunicodechar{≈}{\ensuremath{\approx}}
  - \newunicodechar{·}{\ensuremath{\cdot}}
  - \newunicodechar{×}{\ensuremath{\times}}
  - \newunicodechar{∈}{\ensuremath{\in}}
  - \newunicodechar{√}{\ensuremath{\surd}}
  - \newunicodechar{Δ}{\ensuremath{\Delta}}
  - \newunicodechar{→}{\ensuremath{\rightarrow}}
  - \newunicodechar{←}{\ensuremath{\leftarrow}}
  - \newunicodechar{∞}{\ensuremath{\infty}}
  - \usepackage[font=small,labelfont=bf,justification=raggedright,singlelinecheck=false]{caption}
  - \captionsetup[figure]{labelsep=period}
  - \captionsetup[table]{labelsep=period}
  - \usepackage{titlesec}
  - \titleformat{\section}{\Large\bfseries\sffamily\color{NavyBlue}}{\thesection.}{0.6em}{}
  - \titleformat{\subsection}{\large\bfseries\sffamily\color{NavyBlue!85!black}}{\thesubsection}{0.6em}{}
  - \titleformat{\subsubsection}{\normalsize\bfseries\sffamily}{\thesubsubsection}{0.6em}{}
  - \renewcommand{\abstractname}{\sffamily\bfseries\color{NavyBlue}Abstract}
  - \usepackage{enumitem}
  - \setlist{topsep=2pt,itemsep=2pt,parsep=0pt}
abstract: |
  The waterline method for mapping intertidal Digital Elevation Models (DEMs) from optical satellite imagery assumes that satellite scenes sample the local tidal cycle without systematic bias. We derive a closed-form, first-order model in which the satellite-sampled tide bias equals $\beta \cdot A \cdot \langle \cos\theta\rangle$, where $A$ is the local tidal amplitude and $\langle \cos\theta\rangle$ is the mean cosine of the satellite-overpass tide phase, and we validate it over the macrotidal Korean coast using 5,082 cloud-screened Landsat-8/9 and Sentinel-2 acquisitions (2020–2024) at five tidal flats (Ganghwa-do, Garorim Bay, Gomso Bay, Hampyeong Bay, Suncheon Bay) coupled with hourly tide-gauge observations of the Korea Hydrographic and Oceanographic Agency (KHOA). Sun-synchronous satellites sample only 70–80 % of the local astronomical tidal envelope, systematically missing one extremity. The resulting mean bias has *opposite signs* on the macrotidal west coast (low-tide bias, −0.5 to −1.2 m) and on the south coast (high-tide bias, +0.3 m), reflecting the regional amphidromic (i.e., tidal-phase-rotation) offset — to our knowledge the first quantitative demonstration of a spatially sign-reversed satellite tide-sampling bias in the optical-waterline literature.

  A bootstrap slope $\beta = 1.78$ (95 % CI 1.44–1.91) reproduces the bias across 5 sites and 3 sensors with $R^{2} = 0.98$ and is stable across years, seasons, and sensors (leave-one-site-out Pearson $r = 0.97$, RMSE = 0.16 m, correct sign at 15/15 held-out points), the departure $\beta > 1$ itself decomposing analytically into a spring–neap × overpass-phase covariance term that is a physical diagnostic rather than a model deficiency. Replacing the local tide-gauge reference with the global FES2022b astronomical-tide model reproduces the fit ($\beta = 1.70$, $R^{2} = 0.983$, LOO RMSE = 0.11 m) and the bias sign at every site, demonstrating that the correction is feasible without any local gauge data. Quantile mapping translates the tide-height bias into an elevation-domain RMSE of 0.36–1.09 m and into horizontal contour errors of 179–1,359 m on planar tidal flats, with permanently unsampled intertidal bands up to 2.5 km wide on the macrotidal west coast. Because all current sun-synchronous optical missions cluster near 10:30 local solar time, increasing optical revisit frequency cannot remove the bias; only radar overpasses at a substantially different local solar time (e.g., Sentinel-1 SAR at 06:00 / 18:00 LST, hereafter termed *phase-orthogonal*) can close the gap. The closed-form model provides an *a priori* bias-correction tool requiring only satellite ephemeris and a global tide model, and predicts that the optimal multi-sensor data-collection window is regime-dependent — longer on the macrotidal west coast than in the southern amphidromic regime.

  *Keywords*: tidal flat; intertidal DEM; waterline method; tidal aliasing; sun-synchronous orbit; amphidromic system
---

<!--
The H1 title above is rendered by pandoc's \maketitle.  The abstract is
also rendered through the YAML metadata.  Both are repeated here in
markdown form for weasyprint compatibility (the global md2pdf.py uses
the first H1 as cover title and renders blockquotes for the abstract).
-->

## Highlights

- Closed-form bias = $\beta \cdot A \cdot \langle\cos\theta\rangle$ explains 98 % of cross-sensor variance
- Bipolar tide-bias sign reverses across the Korean amphidromic phase gradient
- $\beta > 1$ decomposes into a spring–neap × overpass-phase covariance diagnostic
- FES2022b global model reproduces the fit; no local tide-gauge data required
- Yields 0.4–1.1 m DEM error and up to 2.5 km of permanently unsampled flats

---

## 1. Introduction

### 1.1 Tidal flats and the need for vertical reference

Tidal flats are among the largest, most biologically productive, and economically important coastal ecosystems on Earth (Murray et al., 2019; Worm et al., 2006). They store carbon, support shellfish economies, host migratory shorebirds, and protect inland areas from storm surges. Mapping their spatial extent and morphology is a precondition for managing coastal change, sea-level rise impact, aquaculture zoning, and ecological monitoring. Because tidal flats are submerged for a large fraction of every day, they cannot be surveyed by conventional optical or LiDAR techniques alone — observations must be coordinated with the tidal stage.

A Digital Elevation Model (DEM) is the most useful single product over tidal flats because it (i) defines the inundation/exposure schedule of every pixel, (ii) supplies the baseline for monitoring vertical change due to deposition, erosion, or sea-level rise, and (iii) supports hydrodynamic modelling. Aerial LiDAR can in principle deliver a centimetre-precision DEM, but coverage is sparse, expensive, and rarely repeated in time (Wang et al., 2020).

### 1.2 The waterline method

The most widely used satellite-based alternative is the **waterline method** (Mason et al., 1995; Heygster et al., 2010; Murray et al., 2012). In its simplest form: each cloud-free satellite image taken at acquisition time $t$ delineates a shoreline (the land–water boundary) that is, by definition, the iso-elevation contour $z = \eta(t)$, where $\eta$ is the tide height referenced to a benchmark datum at the nearest gauge. Stacking many waterlines from images at different tidal stages discretises the intertidal hypsometric curve, which is then interpolated into a DEM. Variants of this approach underpin the Digital Earth Australia Intertidal product (Sagar et al., 2017; Bishop-Taylor et al., 2019a) and a growing global literature (Liu et al., 2015; Tseng et al., 2017; Khan et al., 2019; Salameh et al., 2019).

The accuracy of a waterline DEM depends critically on the *sampling of the tidal range* by the available imagery. If imagery is acquired across the full tide cycle with uniform statistical density, the discretisation error is set only by the temporal spacing of the images and by the interpolation method. If, however, satellites systematically miss part of the cycle, the missed elevation band is irrecoverable: no amount of additional imagery acquired at the same time-of-day can fill it.

### 1.3 Tidal aliasing: a recognised problem, incompletely quantified

Sun-synchronous orbits place all major Earth-observing optical satellites at near-fixed *local solar times* (LST). The Landsat-8/9 and Sentinel-2 missions all descend across the equator at LST $\approx$ 10:00–10:30, drifting only by a few minutes per year. Because the dominant semi-diurnal tidal constituent ($M_{2}$, period 12.42 h) is not a simple fraction of the solar day, satellite imagery samples the tide at an interval that is **incommensurate with the diurnal cycle**: each successive overpass at the same site occurs at a slightly different tidal phase, but only in a narrow time-of-day window. Bishop-Taylor et al. (2019b) documented the resulting *tidal aliasing* for the Digital Earth Australia Intertidal product, showing that satellite-sampled tide-height distributions exhibit a non-zero mean bias and a truncated range relative to the underlying tidal cycle; the open-source eo-tides package (Bishop-Taylor et al., 2025) has since made the diagnostic accessible at global scale. Sent et al. (2025) documented an analogous optical-sensor aliasing in the macrotidal Tagus estuary, Portugal, where Sentinel-2 turbidity retrievals are over-represented at spring low tide and under-represented at neap high tide. Despite these recognitions, no closed-form *a priori* model linking the local tide phase at overpass time to a predictable bias amplitude has been proposed.

In the Korean context, the *altimetry-domain* analogue of this phenomenon was reported by Lee, K. et al. (2022), who showed that ocean-tide-corrected satellite-altimetry sea-level anomalies near Incheon are sampled preferentially at low tide in the early 1990s and at high tide in 2013–2017, inflating multi-mission sea-level-rise trends by up to approximately 30 mm $\cdot$ yr$^{-1}$ before correction. That study, however, addresses the *temporal* drift of the sampling phase within a single altimetry footprint; here we address the *spatial* counterpart for the optical-waterline workflow.

Operationally, the same truncation has been recognised empirically: recent multi-sensor waterline DEM studies on the Korean west coast report that Landsat-8/9 and Sentinel-2 systematically miss the upper intertidal while Sentinel-1 SAR systematically misses the lower intertidal, and that a hybrid optical+SAR collection reaches a stable DEM only after a minimum multi-month observation window (Lee, J. et al., 2025). The *physical reason* for that empirical threshold — and for the directional asymmetry of the per-sensor truncation — has not been derived from first principles.

Three open questions remain:

1. **Is the bias systematic and predictable, or noisy and idiosyncratic?**
2. **How does the bias vary across regional amphidromic phase gradients?**
3. **What is the practical translation of the tide-height bias into the DEM elevation domain, and at what scale does it matter?**

Table 1 summarises the position of the present study relative to the existing Korean tidal-flat DEM and sampling-bias literature.

\begin{table}[!htbp]
\centering
\footnotesize
\caption{\textbf{Position of the present study within the Korean tidal-flat DEM and altimetry-sampling literature.} The present work is the first to address the optical-waterline sampling bias \textit{analytically and \textit{a priori}}; prior Korean works either map a single-site DEM or treat the bias empirically or in the altimetry (sea-level) domain.}
\label{tab:positioning}
\renewcommand{\arraystretch}{1.15}
\begin{tabular}{@{}>{\raggedright\arraybackslash}p{2.6cm}>{\raggedright\arraybackslash}p{2.2cm}>{\raggedright\arraybackslash}p{2.0cm}>{\raggedright\arraybackslash}p{2.6cm}>{\raggedright\arraybackslash}p{2.4cm}>{\raggedright\arraybackslash}p{2.6cm}@{}}
\toprule
\textbf{Study} & \textbf{Region} & \textbf{Sensors} & \textbf{Method} & \textbf{Output} & \textbf{Treatment of sampling bias} \\
\midrule
Ryu et al. (2002) & Gomso Bay (W) & Landsat-TM & Single-scene waterline & Tidal-flat contour, one epoch & Not addressed \\
Lee \& Ryu (2017) & Ganghwa-do (NW) & TanDEM-X (SAR InSAR) & Phase-based DEM & DEM, single mission & Sensor-specific only \\
Yun et al. (2022) & Ganghwa-do (NW) & TanDEM-X & InSAR phase, public service & High-resolution DEM product & Not addressed \\
Lee, K. et al. (2022) & Incheon, regional & Multi-mission altimetry (T/P--Jason, Cryosat) & Multi-mission tide-corrected trend & Sea-level-rise rate & \textit{Temporal} sampling-phase bias (altimetry domain) \\
Lee, J. et al. (2025, ECSS) & Taean Peninsula (W) & L8/9 + S2A/B + S1A & Multi-sensor waterline fusion & DEM, 5-month window optimum vs UAV-LiDAR (MAE 25.6 cm) & \textit{Empirically} optimised (fuse optical + SAR) \\
\textbf{This study} & \textbf{W + S coasts, 5 sites (2020--2024)} & \textbf{L8/9 + S2 (metadata; 5,082 scenes)} & \textbf{Phase-bias analysis; $\beta \cdot A \cdot \langle \cos\theta\rangle$} & \textbf{\textit{A priori} bias-correction model + DEM error budget} & \textbf{Analytically predicted, $R^2 = 0.98$ across sites/sensors} \\
\bottomrule
\end{tabular}
\end{table}

### 1.4 The Korean macrotidal context

The Korean western coast hosts approximately 2,500 km$^{2}$ of intertidal flats — among the largest in East Asia (Koh and Khim, 2014; Murray et al., 2014) — under one of the world's largest tidal-range regimes (mean spring range > 8 m at Incheon). On the southern coast (Yeosu, Suncheon Bay), the range falls to about 3 m due to the local amphidromic structure (the regional pattern of tidal-phase rotation around a near-zero-amplitude node), and the phase of high water shifts by about 4 h between the northwest and the south coast of the peninsula (Choi et al., 2014). This combination — large amplitude, sharp regional gradient, well-instrumented tide-gauge network — makes Korea an ideal natural laboratory for *quantifying* and *predicting* the satellite tidal-sampling bias.

### 1.5 Contribution

This paper is positioned as a *theoretical companion* to the empirical waterline-optimisation literature (Bishop-Taylor et al., 2019a, b; Sagar et al., 2017; Murray et al., 2019; Salameh et al., 2019; Ryu et al., 2002, 2008; Lee and Ryu, 2017; Yun et al., 2022; Lee, J. et al., 2025). Specifically, we present an end-to-end analysis that:

(i) derives a one-parameter analytical model, $\text{mean bias} = \beta \cdot A \cdot \langle \cos\theta\rangle$, linking the satellite-sampled tide bias to the local tidal amplitude $A$ and to the mean cosine $\langle\cos\theta\rangle$ of the overpass phase — to our knowledge the first closed-form *a priori* bias-prediction formula for the optical-waterline workflow (Conclusions 1–2);

(ii) shows that the model explains 98 % of the cross-site, cross-sensor variance and generalises to held-out sites with RMSE = 0.16 m, and that the slope excess ($\beta = 1.78 \neq 1$) **quantitatively decomposes** into a spring–neap × $\cos\theta$ covariance term, providing a physical diagnostic rather than an empirical correction factor (Conclusion 2);

(iii) provides the first quantitative demonstration that the bias *changes sign* across an amphidromic phase gradient — the spatial-domain counterpart to the temporal altimetry-sampling drift previously documented near Incheon by Lee, K. et al. (2022) (Conclusion 3);

(iv) translates the tide-height bias into elevation-domain DEM errors via quantile mapping, yielding the first quantitative estimates of permanently unsampled intertidal bands (up to 2.5 km wide) and a first-principles account of why empirically observed multi-sensor data-collection-window optima saturate at intermediate timescales (Section 5.3; Conclusions 4–6);

(v) reproduces the fit from an independent global ocean tide model (FES2022b: $R^{2} = 0.983$ with correct bias sign at all 15 held-out points), confirming that the *a priori* correction is applicable worldwide without requiring local tide-gauge access (Conclusion 7).

The Korean macrotidal coast (five sites, 2020–2024; Section 2) provides a natural laboratory for the validation, because it spans both a strongly negative-bias regime (the macrotidal west coast) and a sign-reversed positive-bias regime (the southern amphidromic regime) within a single, densely instrumented tide-gauge network.

---

## 2. Study area and data

### 2.1 Sites

Five tidal flats spanning the entire western and southern Korean coast were chosen to span the full range of local tidal amplitudes and regional phase offsets (Figure 1; Table 2):

- **Ganghwa-do** (MSR $\approx$ 8 m): the largest single tidal-flat complex in Korea, exposed for approximately 50 % of the tidal cycle.
- **Garorim Bay** (MSR $\approx$ 6 m): semi-enclosed bay, tidal-flat fringed.
- **Gomso Bay** (MSR $\approx$ 6 m): cuspate tidal flat with strong fluvial input.
- **Hampyeong Bay** (MSR $\approx$ 4 m): bay-mouth tidal flat at the transition to the south coast.
- **Suncheon Bay** (MSR $\approx$ 3 m): reed-dominated estuary, Ramsar-listed wetland.

Each site is matched with the nearest principal tide-gauge of the Korea Hydrographic and Oceanographic Agency (KHOA; Figure 1, triangles).

Garorim Bay lies approximately 30 km north of the Taean Peninsula sub-region addressed by recent multi-sensor west-coast DEM studies (Lee, J. et al., 2025) but does not overlap with them; the present analysis therefore provides an independent measurement of the macrotidal west-coast sampling geometry adjacent to, rather than within, that area. Suncheon Bay further extends the coverage to a south-coast amphidromic regime not previously sampled in this literature.

![Study sites along the western and southern Korean coast. Coloured boxes show the satellite-acquisition bounding boxes; circles mark site centroids; triangles mark KHOA tide-gauge stations (Incheon (DT_0001), Anheung (DT_0067), Gunsan (DT_0018), Yeonggwang (DT_0003), Yeosu (DT_0016)). MSR = mean spring range (literature estimate). The five sites span a mean spring tidal range from approximately 8 m (Ganghwa-do) to about 3 m (Suncheon Bay) and straddle the $M_{2}$ amphidromic phase gradient of the Yellow Sea — the combination that drives the bipolar sampling bias documented in this paper. Inset: regional context.](figures/fig1_study_area.png){width=90%}

### 2.2 Tide-gauge reference: KHOA Open API

Hourly quality-controlled tide observations for 2020-01-01 to 2024-12-31 were retrieved through the Korea Hydrographic and Oceanographic Agency (KHOA) Open API, hosted on the Korean public data portal (`apis.data.go.kr/1192136/hourlyTide`). For each of the five gauge stations we accumulated 42,674–43,839 hourly samples ($>$ 99.5 % coverage). Tide heights are stored in the *KHOA datum* (approximate lowest low water, ALLW — the sum of the amplitudes of the four principal constituents $M_{2}$, $S_{2}$, $K_{1}$, $O_{1}$ below mean sea level, which is distinct from the lowest astronomical tide); we report all elevations in this datum. Brief acquisition outages ($\leq$ 0.3 % of dates) and four anomalous days at Incheon (DT_0001; 2020-10-01 to 2020-10-04) are tolerated as random missing data.

### 2.3 Satellite metadata: Google Earth Engine

Per-scene metadata (acquisition time, scene ID, cloud-cover fraction, WRS/MGRS tile) were extracted from Google Earth Engine (Gorelick et al., 2017) for three optical sensors over the 2020–2024 period: Landsat 8 (`LANDSAT/LC08/C02/T1_L2`; 2013-04–present), Landsat 9 (`LANDSAT/LC09/C02/T1_L2`; 2021-10–present), and the European Sentinel-2 mission (`COPERNICUS/S2_HARMONIZED`; 2015-06–present; Drusch et al., 2012).

Pixel data were not required: this is a *metadata* analysis. Scenes intersecting each site's bounding box were retained, with a permissive cloud-cover threshold ≤ 60 %; the cloud-screened sample sizes ranged from 500 (Gomso) to 1,876 scenes (Garorim Bay; Table 2).

\begin{table}[!htbp]
\centering
\footnotesize
\caption{\textbf{Data inventory per site for 2020--2024.} Planar slopes are the literature-based first-order values used for the horizontal-domain error budget (Section~3.5); see that section for sources.}
\label{tab:inventory}
\renewcommand{\arraystretch}{1.2}
\begin{tabular}{@{}>{\raggedright\arraybackslash}p{2.5cm}>{\raggedright\arraybackslash}p{2.9cm}>{\raggedright\arraybackslash}p{1.6cm}>{\raggedright\arraybackslash}p{3.2cm}>{\centering\arraybackslash}p{2.1cm}@{}}
\toprule
\textbf{Site} & \textbf{KHOA gauge} & \textbf{KHOA rows} & \textbf{Sat. scenes (L8 / L9 / S2)} & \textbf{Planar slope (m/km)} \\
\midrule
Ganghwa-do & Incheon (DT\_0001) & 43,689 & 137 / 90 / 826 & 0.8 \\
Garorim Bay & Anheung (DT\_0067) & 43,720 & 129 / 91 / 1,656 & 1.5 \\
Gomso Bay & Gunsan (DT\_0018) & 42,674 & 203 / 110 / 187 & 1.2 \\
Hampyeong Bay & Yeonggwang (DT\_0003) & 43,839 & 195 / 119 / 796 & 1.5 \\
Suncheon Bay & Yeosu (DT\_0016) & 43,688 & 70 / 38 / 435 & 2.0 \\
\bottomrule
\end{tabular}
\end{table}

Tide heights at each satellite acquisition time were obtained by linear interpolation of the hourly KHOA series between bracketing hours.

---

## 3. Material and methods

### 3.1 Aliasing metrics

For each (site, sensor) combination, we use the standard set of aliasing metrics introduced for sun-synchronous waterline analysis (Bishop-Taylor et al., 2019b; Bishop-Taylor et al., 2025):

- **Spread** = $\bigl(\max \eta_{\mathrm{sat}} - \min \eta_{\mathrm{sat}}\bigr) \big/ \bigl(Q_{\mathrm{ref}}(0.999) - Q_{\mathrm{ref}}(0.001)\bigr)$. Fraction of the reference tidal range covered by satellite samples.
- **Low offset** = $\max\!\bigl(0,\, \min \eta_{\mathrm{sat}} - Q_{\mathrm{ref}}(0.001)\bigr) \big/ \mathrm{range}$. Fraction of the reference range below the lowest satellite sample.
- **High offset** = $\max\!\bigl(0,\, Q_{\mathrm{ref}}(0.999) - \max \eta_{\mathrm{sat}}\bigr) \big/ \mathrm{range}$. Fraction above the highest satellite sample.
- **Kolmogorov–Smirnov (KS) statistic** between satellite-sampled and reference tide-height empirical cumulative distribution functions (CDFs).
- **Mean bias** = $\langle \eta_{\mathrm{sat}} \rangle - \langle \eta_{\mathrm{ref}} \rangle$, in metres (KHOA datum).

### 3.2 Tidal phase

Local high-water (HW) events were extracted from the hourly KHOA series by a peak-finding algorithm with a minimum inter-peak separation of 8 h (implementation: SciPy). For every satellite acquisition time $t$ we then computed the **normalised phase** since the bracketing prior HW:

$$
\phi(t) \;=\; \frac{t - t_{\mathrm{HW},\mathrm{prev}}}{t_{\mathrm{HW},\mathrm{next}} - t_{\mathrm{HW},\mathrm{prev}}} \;\in\; [0, 1).
$$

We associate $\phi$ with an angle $\theta = 2\pi\phi$ such that $\theta = 0$ corresponds to HW and $\theta \approx \pi$ to low water (LW). For each (site, sensor) we compute circular statistics of $\{\theta_i\}$:

- Concentration vector $\langle \cos\theta\rangle$, $\langle \sin\theta\rangle$,
- Concentration magnitude $R = \sqrt{\langle \cos\theta\rangle^{2} + \langle \sin\theta\rangle^{2}} \in [0, 1]$,
- Circular mean phase $\bar{\theta}$ and circular standard deviation.

### 3.3 Analytical bias model

For a near-symmetric, $M_{2}$-dominated tide, the elevation at time $t$ can be written

$$
\eta(t) \;\approx\; A_{t}\,\cos\!\bigl(\theta_{t}\bigr) + \eta_{0}(t),
$$

where $A_{t}$ is the slowly varying envelope and $\eta_{0}$ the mean sea level. The bias inherited by sampling at the satellite times $\{t_i\}$ relative to the dense reference is, to first order,

$$
\mathrm{bias} \;=\; \langle \eta_{\mathrm{sat}}\rangle - \langle \eta_{\mathrm{ref}}\rangle \;\approx\; \langle A\,\cos\theta\rangle.
$$

Writing $A = \langle A \rangle + A'$ and $\cos\theta = \langle \cos\theta \rangle + (\cos\theta)'$, this expands as

$$
\langle A\,\cos\theta\rangle \;=\; \langle A\rangle \cdot \langle\cos\theta\rangle \;+\; \mathrm{cov}(A, \cos\theta),
$$

so that the bias can be written

\begin{equation}\label{eq:bias}
\mathrm{bias} \;\approx\; \beta \cdot A \cdot \langle \cos\theta\rangle,
\end{equation}

with $A \equiv \langle A\rangle$ the time-mean amplitude and an effective proportionality factor

$$
\beta \;=\; 1 \;+\; \frac{\mathrm{cov}(A,\cos\theta)}{\langle A\rangle \cdot \langle\cos\theta\rangle}.
$$

The leading-order prediction is $\beta = 1$ when $A$ and $\cos\theta$ are uncorrelated. Any non-zero covariance — for instance, when spring tides (large $A$) systematically coincide with a preferred sign of $\cos\theta$ at the satellite overpass time — shifts $\beta$ away from unity. The empirical departure $\beta > 1$ documented in Sections 4 and 5 is therefore itself a *diagnostic* of physical mechanisms that produce $\mathrm{cov}(A, \cos\theta) \neq 0$, not a defect of the model. We fit $\beta$ by ordinary least squares (OLS) on the 15 (site, sensor) pairs.

### 3.4 Stability tests

We test the temporal/sensor robustness of Eq. \eqref{eq:bias} by partitioning the data along four axes and re-fitting:

- **Annual**: 5 fits, one per calendar year 2020–2024.
- **Seasonal**: 4 fits, one per DJF / MAM / JJA / SON.
- **Sensor**: 3 fits, one per L8 / L9 / S2.
- **Leave-one-site-out**: 5 fits, each training on 4 sites (12 points) and predicting the 5th site's 3 sensors.

A 2,000-resample bootstrap of the pooled ($n = 15$) fit yields confidence intervals on $\beta$ and on the intercept.

### 3.5 Conversion to elevation-domain DEM error

Because every waterline is mapped to its tide-stage elevation, the bias in the $\eta$-distribution maps directly into the elevation domain. For each cumulative probability $p \in [0.005, 0.995]$ we compute

$$
z_{\mathrm{true}}(p) = Q_{\mathrm{ref}}(p), \qquad z_{\mathrm{sat}}(p) = Q_{\mathrm{sat}}(p), \qquad \varepsilon(p) = z_{\mathrm{sat}}(p) - z_{\mathrm{true}}(p).
$$

Aggregate elevation-domain metrics:

- **Vertical DEM RMSE** = $\sqrt{\langle \varepsilon(p)^{2}\rangle}$,
- **Mean elevation bias** = $\langle \varepsilon(p)\rangle$ (= $\eta$-domain mean bias),
- **Truncated low / high bands** = $\max\!\bigl(0,\, \min \eta_{\mathrm{sat}} - Q_{\mathrm{ref}}(p_{\min})\bigr)$ and $\max\!\bigl(0,\, Q_{\mathrm{ref}}(p_{\max}) - \max \eta_{\mathrm{sat}}\bigr)$; these are intertidal elevation bands that satellites *never* sample.

Assuming a locally planar tidal flat with slope $s$, vertical errors are converted to **horizontal contour displacement** as $\Delta x = \Delta z / s$. Site-specific slopes were assigned from published Korean tidal-flat geomorphology surveys and DEM products: Ganghwa-do = 0.8 m/km (Lee and Ryu, 2017; Yun et al., 2022), Garorim Bay = 1.5 m/km (Lee, J. et al., 2025), Gomso Bay = 1.2 m/km (Ryu et al., 2002, 2008), Hampyeong Bay = 1.5 m/km (assumed comparable to Gomso based on Koh and Khim, 2014), and Suncheon Bay = 2.0 m/km (assumed from south-coast steeper-flat regimes; literature constraint weaker). These are first-order values intended to give an order-of-magnitude horizontal-error budget; a refined analysis with site-specific LiDAR or SRTM hypsometric curves would adjust the horizontal — but not the vertical — numbers proportionally.

### 3.6 Implementation

All analyses are reproducible from open data through the GitHub repository released with this paper (Data and code availability). The processing pipeline uses GEE-API metadata extraction (no pixel downloads), KHOA Open API caching, pandas/NumPy analysis, SciPy for linear regression and bootstrap, and matplotlib/Cartopy for figures. Throughout the paper, the reference distribution against which satellite sampling is compared is the KHOA observed hourly series (Section 2.2). Two complementary astronomical-only references are used as sensitivity tests in Section 4.7: (i) harmonic-tide reconstruction of the same KHOA records (UTide; Codiga, 2011), which removes weather-induced residuals but preserves site-specific constituent amplitudes derived from local observations; and (ii) the global ocean tide model **FES2022b** (Lyard et al., 2021; AVISO `ocean_tide_extrapolated` grids at 1/30° resolution), from which per-constituent amplitudes and phases for eight major constituents ($M_{2}$, $S_{2}$, $K_{1}$, $O_{1}$, $N_{2}$, $P_{1}$, $K_{2}$, $Q_{1}$) are interpolated at each KHOA gauge coordinate and harmonically synthesised at hourly cadence over 2020–2024. The FES2022b variant provides a fully independent, globally reproducible reference that requires no local tide-gauge access.

---

## 4. Results

### 4.1 Cross-site tidal sampling distributions reveal a bipolar bias

Figure 2 shows the empirical distribution of tide heights (in the KHOA datum) at satellite-acquisition times against the 5-year KHOA reference for each of the 5 sites, broken out by sensor. At every site, satellite distributions are visibly *non-uniform* relative to the reference. At the western sites (Ganghwa, Garorim, Gomso, Hampyeong), satellite samples are over-represented in the lower half of the elevation range and *empty* above 6–7 m KHOA datum (the top approximately 20 % of the histogram). At Suncheon Bay, the pattern is opposite: satellites *over*-sample the upper half of the range and miss the lowest 0.3–1 m. Figure S1 (CDF panels) reinforces the same finding in cumulative form.

![Empirical tide-height distributions at satellite acquisition times (coloured outlines) vs. the 5-year KHOA reference (grey filled). Each panel is a site; colours mark sensors (L8 = orange, L9 = red, S2 = purple). The mirror-image pattern between Suncheon Bay (under-samples low tide) and the four western sites (under-sample high tide) is the visual signature of the bipolar bias quantified throughout Section 4.](figures/fig2_distribution_grid.png){width=92%}

Quantitatively, the **aliasing metrics** (Section 3.1) confirm the bipolarity (Figure 3, Table 3). The four western sites all exhibit a high-tide offset of 21–28 % and a low offset near 0 %; Suncheon Bay alone shows a low-tide offset of 26–36 % with a high-tide offset of 0–5 %. Mean tide-height bias is −0.5 to −1.2 m at the western sites and +0.3 m at Suncheon Bay, a **change of sign** across the regional amphidromic gradient.

![Cross-site aliasing metrics by sensor. Columns: spread, high-tide offset, low-tide offset, and mean bias (obs − ref). Bars: L8 (orange), L9 (red), S2 (purple). Sites are ordered N$\rightarrow$S along the western/southern coast; horizontal label gives the literature mean spring range. The sign-reversal of mean bias and the swap between high- and low-tide offsets at Suncheon Bay relative to the western sites — observed consistently across all three sensors — provide quantitative confirmation that the bias polarity is set by the regional amphidromic geometry, not by the sensor or the tidal amplitude alone.](figures/fig3_bipolar_bias.png){width=95%}

\begin{table}[!htbp]
\centering
\footnotesize
\caption{\textbf{Cross-site aliasing metrics, 5-year (2020--2024) summary.} Mean bias is the mean satellite-time tide height minus the 5-year KHOA mean. Suncheon Bay differs in sign and structure from the western sites.}
\label{tab:aliasing}
\renewcommand{\arraystretch}{1.15}
\begin{tabular}{@{}>{\raggedright\arraybackslash}p{2.1cm}ccccc>{\centering\arraybackslash}p{2.0cm}@{}}
\toprule
\textbf{Site} & \textbf{Sensor} & \textbf{n} & \textbf{Spread} & \textbf{High off.} & \textbf{Low off.} & \textbf{Mean bias (m)} \\
\midrule
Ganghwa & L8 & 137 & 0.77 & 0.22 & 0.01 & $-1.13$ \\
Ganghwa & L9 & 90 & 0.69 & 0.28 & 0.03 & $-0.94$ \\
Ganghwa & S2 & 826 & 0.80 & 0.21 & 0.00 & $-1.05$ \\
Garorim & L8 & 129 & 0.76 & 0.27 & 0.00 & $-1.20$ \\
Garorim & L9 & 91 & 0.76 & 0.25 & 0.00 & $-0.82$ \\
Garorim & S2 & 1,656 & 0.78 & 0.23 & 0.00 & $-0.80$ \\
Gomso & L8 & 203 & 0.80 & 0.25 & 0.00 & $-0.88$ \\
Gomso & L9 & 110 & 0.77 & 0.23 & 0.00 & $-0.86$ \\
Gomso & S2 & 187 & 0.75 & 0.23 & 0.02 & $-0.64$ \\
Hampyeong & L8 & 195 & 0.77 & 0.25 & 0.00 & $-0.68$ \\
Hampyeong & L9 & 119 & 0.74 & 0.22 & 0.04 & $-0.80$ \\
Hampyeong & S2 & 796 & 0.73 & 0.23 & 0.03 & $-0.52$ \\
\textbf{Suncheon} & L8 & 70 & 0.72 & \textbf{0.00} & \textbf{0.27} & $\mathbf{+0.29}$ \\
\textbf{Suncheon} & L9 & 38 & 0.59 & 0.05 & \textbf{0.36} & $\mathbf{+0.39}$ \\
\textbf{Suncheon} & S2 & 435 & 0.69 & 0.05 & \textbf{0.26} & $\mathbf{+0.31}$ \\
\bottomrule
\end{tabular}
\end{table}

### 4.2 The bipolar bias is set by the satellite-overpass tide phase

For every satellite acquisition we computed the normalised tide phase $\phi \in [0, 1)$ since the prior HW (Section 3.2) and aggregated as circular means per site (Figure 4). At the four western sites the mean phase clusters at 142–235° (i.e., from ebb to early flood, near LW); at Suncheon Bay it lies at 32–56° (just after HW, early ebb). Because the satellite overpass time is essentially fixed in *local solar time* (Figure S2, peak at 11:00 KST at every site), the *tidal* phase varies *only* because the regional amphidromic system shifts the HW-LW timing.

![Distribution of satellite-overpass tide phase per site (rose diagrams; all sensors combined). The red bar marks the circular mean. The 180-degree shift in mean phase between the western sites (near LW, $\cos\theta < 0$) and Suncheon Bay (near HW, $\cos\theta > 0$) is the immediate cause of the sign reversal of the mean bias, and is the input to the analytical model of Eq. \eqref{eq:bias}.](figures/fig4_phase_polar.png){width=90%}

### 4.3 A one-parameter model predicts mean bias with $R^{2} = 0.98$

Equation \eqref{eq:bias} of Section 3.3 predicts that the satellite-sampled mean bias equals $\beta \cdot A \cdot \langle \cos\theta\rangle$, where $A$ is the time-mean tidal amplitude $\bigl(\tfrac{1}{2}(\overline{\mathrm{HW}} - \overline{\mathrm{LW}})\bigr)$ and $\langle \cos\theta\rangle$ is the empirical mean cosine of overpass phase. Figure 5 plots the measured mean bias (y-axis) against this predictor (x-axis) for the 15 (site, sensor) pairs. Ordinary least-squares fit yields

$$
\mathrm{bias} \;=\; -0.06 \;+\; 1.78 \cdot A \cdot \langle \cos\theta\rangle, \qquad R^{2} = 0.980, \quad p = 2.2 \times 10^{-12}, \quad n = 15.
$$

The intercept ($-0.06$ m) is small but significantly negative — the bootstrap 95 % CI of $[-0.21, -0.03]$ m does not include zero — and most likely reflects a residual mean offset between the KHOA 5-year mean tide and the 5-year mean of the satellite-sampled population that is unrelated to the $A \cdot \langle \cos\theta\rangle$ term (the intercept vanishes under the FES2022b reference of Section 4.7(d), supporting this interpretation). The slope $\beta = 1.78$ exceeds the leading-order theoretical prediction of 1; we defer the physical decomposition of this excess to Section 5.1 and the sensitivity analysis to Section 4.7.

![Measured mean tide-height bias versus the analytical predictor $A \cdot \langle \cos\theta\rangle$. Each of 15 points is one (site $\times$ sensor) pair. Marker shape encodes site, colour encodes sensor. Dashed black: OLS fit ($\beta = 1.78$, $R^{2} = 0.98$). Dotted red: theoretical 1:1. A single parameter captures 98 % of the cross-site, cross-sensor variance, supporting the interpretation that the bias is set by satellite-overpass phase alone; the slope $\beta > 1$ is attributable to spring–neap covariance (Section 5.1).](figures/fig5_phase_bias_regression.png){width=80%}

### 4.4 The regression is stable across years, seasons, sensors, and held-out sites

We tested the stability of Eq. \eqref{eq:bias} by re-fitting on partitioned subsets (Section 3.4). The slope and $R^{2}$ for each partition are summarised in Figure S3 (table values in Table S1):

- **Annual stability** (one fit per year, 9–13 points each): slope 1.32–1.72, $R^{2}$ 0.85–0.95.
- **Seasonal stability** (12–14 points each): slope 0.81–1.49, $R^{2}$ 0.85–0.98. The summer (JJA) slope is closest to the theoretical 1 (slope = 0.81); MAM has the highest $R^{2}$ (0.98).
- **Sensor stability** (5 points each): slope 1.73 (L8), 2.01 (L9), 1.71 (S2). $R^{2} \geq 0.986$ for all three.
- **Bootstrap CI** of pooled fit: $\beta \in [1.44, 1.91]$, intercept $\in [-0.21, -0.03]$.

The 95 % CI of $\beta$ does *not* include 1, confirming that the empirical proportionality factor exceeds the leading-order prediction. The coefficient-stability summary (Figure S3) and the underlying per-partition scatter (Figure S4) are provided in the Supplementary Material.

Leave-one-site-out validation (Figure 6) holds out each site in turn, fits the regression on the remaining four (12 points), and predicts the held-out site's three bias values. Pearson r = 0.969 between measured and predicted mean bias, with RMSE = 0.16 m and MAE = 0.12 m. Crucially, **the sign of the predicted bias is correct in all 15 held-out cases**, including the southern Suncheon Bay despite its absence from the training set.

![Leave-one-site-out (LOO) validation: each (site $\times$ sensor) bias predicted by the model fitted on the other four sites. Diagonal: 1:1. RMSE = 0.16 m, MAE = 0.12 m, Pearson $r = +0.97$. The model correctly predicts the sign at all 15 held-out points, including the sign-reversed Suncheon Bay despite its absence from the training set — demonstrating that the formula generalises beyond the training sites.](figures/fig7_loo_validation.png){width=80%}

### 4.5 Tide-height bias translates into 0.36–1.09 m elevation-domain RMSE

By quantile-mapping (Section 3.5), the bias in the tide-height distribution maps directly into the elevation domain of any waterline DEM constructed from the same scenes. The per-site **elevation-domain RMSE** — i.e. the RMSE of the quantile-mapped tide bias projected into the vertical-elevation domain of a waterline DEM — ranges from 0.36 m (Suncheon Bay) to 1.09 m (Ganghwa-do). This quantity represents the systematic vertical error inherited from the tide-sampling bias alone; it is not a per-pixel DEM RMSE validated against an independent surface such as UAV-LiDAR (cf. Lee, J. et al., 2025), and should be read as an *upper bound* on the aliasing contribution to DEM error. Figure S6 plots the per-elevation error curve $z_{\mathrm{sat}} - z_{\mathrm{ref}}$ for each (site, sensor) pair. At the four western sites the error is negative throughout the intertidal range (DEM underestimates elevation), growing to $-1.8$ to $-2.3$ m at the highest sampled quantiles. At Suncheon Bay the error is positive throughout (DEM overestimates), reaching $+0.9$ to $+1.2$ m at the lowest quantiles.

Beyond the per-quantile error, certain portions of the intertidal range are *never* sampled by satellites and so form irrecoverable truncation bands (Figure 7a). On the four western sites, truncation is at the *top* of the intertidal range, with vertical extent 1.36–2.02 m. At Suncheon Bay it is at the *bottom*, with extent 0.99 m.

Converting to horizontal contour displacement on a planar tidal flat with assumed site-specific slopes (Section 3.5), the upper-tide truncation translates into **1.06 km (Garorim) to 2.53 km (Ganghwa)** of horizontally missing tidal-flat width on the western coast (Figure 7b; schematic cross-sections in Figure S7). At Suncheon Bay the lower-band truncation corresponds to approximately 495 m of missing width. The vertical DEM RMSE of 0.36–1.09 m translates into horizontal RMSE of **179 m (Suncheon) to 1,359 m (Ganghwa)**.

\begin{figure}[!htbp]
\centering
\includegraphics[width=0.86\textwidth]{figures/fig9_truncation_bands.png}

\vspace{4pt}
\includegraphics[width=0.92\textwidth]{figures/fig10_horizontal_error.png}
\caption{\textbf{Waterline-DEM coverage and error budget per site.} \textbf{(a)} Sampled vs missing elevation bands: grey = elevation range covered by the satellite-sampled tides; red = upper-tide truncation (irrecoverable); blue = lower-tide truncation. The truncation bands occupy 1.36--2.02 m of vertical range at the western sites and 0.99 m at Suncheon Bay; these bands cannot be filled by additional optical scenes at the same overpass time. \textbf{(b)} Per-site vertical (left) and horizontal-equivalent (right) RMSE and $|\text{mean bias}|$, averaged across the three sensors. The horizontal RMSE depends jointly on the vertical RMSE and on the assumed tidal-flat slope; Ganghwa-do, where vertical RMSE peaks and the flat is gentlest, carries the largest horizontal error budget (over 1.3 km).}
\end{figure}

### 4.6 Increasing optical revisit frequency does not remove the bias

Sentinel-2 contributes 826 scenes at Ganghwa-do versus 137 for Landsat 8; a 6.0-fold increase in sample density yields only a 7 % reduction in mean bias ($-1.05$ m vs. $-1.13$ m). At Garorim Bay the comparison is more dramatic (a 12.8-fold increase in S2 scenes over L8), and the bias *drops by only one third* ($-0.80$ m vs. $-1.20$ m). The reason is geometric: all three sensors share essentially the same overpass time (Figure S2, every histogram peak at 11:00 KST), so the empirical $\langle \cos\theta\rangle$ converges to the same limit. Refining the histogram shape (lower KS statistic, lower distribution-shape error) is possible with more scenes; *correcting the systematic mean shift is not*.

### 4.7 Robustness to amplitude definition and reference choice

We test the robustness of the headline $\beta = 1.78$ fit (Section 4.3) to the choices made for the *amplitude* and the *reference series*. Equation \eqref{eq:bias} was re-fitted on the same 15 (site $\times$ sensor) points under four combinations:

(a) **baseline** — $A = \tfrac{1}{2}(\overline{\mathrm{HW}} - \overline{\mathrm{LW}})$ with the KHOA observed hourly series as the reference (Section 4.3);

(b) **$M_{2}$-amplitude / KHOA** — $A$ replaced by the strict $M_{2}$ amplitude from a 5-year harmonic decomposition of each gauge using UTide (Codiga, 2011), with the KHOA observed series unchanged;

(c) **$M_{2}$-amplitude / astronomical reference** — $A = A_{M_{2}}$ and the reference replaced by an *astronomical-only* synthetic series reconstructed from the same harmonic solution at each gauge;

(d) **FES2022b global model** — the FES2022b-synthesised series (Section 3.6) used as both the reference distribution and the source of overpass-time tide heights, with $A$ set to the site-specific mean half-range computed from this series. This variant requires *no* local tide-gauge data and tests the model under a fully independent, globally available reference.

Per-site $M_{2}$ amplitudes from the KHOA harmonic decomposition are 2.83 m (Ganghwa-do), 2.10 m (Garorim Bay), 2.16 m (Gomso Bay), 2.01 m (Hampyeong Bay), and 0.91 m (Suncheon Bay); $S_{2}$ amplitudes are uniformly large (35–45 % of $M_{2}$), consistent with the strong spring–neap regime of the Yellow Sea (Choi et al., 2014). The non-astronomical residual standard deviation is 8–16 cm, i.e. $\leq 6$ % of the total elevation standard deviation at every site. Full per-variant, per-sensor regression coefficients and bias values are tabulated in Supplementary Table S2.

The four variants yield $\beta = 1.78$ (a, baseline), 1.87 (b, $M_{2}$-amplitude / KHOA), 1.90 (c, $M_{2}$-amplitude / astronomical reference), and 1.70 (d, FES2022b global model), with bootstrap 95 % CIs of $[1.44, 1.92]$, $[1.50, 2.02]$, $[1.49, 2.06]$, and $[1.42, 1.80]$ respectively, and $R^{2} \in [0.974, 0.983]$ across all four. Leave-one-site-out RMSEs are 0.16 m (a–c) and 0.11 m (d), and the bias sign is predicted correctly at all 15 held-out points under every variant. The intercept is negative in variants (a–c) ($-0.06$ to $-0.04$ m, bootstrap 95 % CI upper bound never reaching zero) and effectively zero in variant (d), confirming that the small KHOA intercept arises from the non-astronomical mean offset between the gauge record and the satellite-time population.

Decomposing $\beta - 1$ by the three Section 5.1 mechanisms attributes only $\Delta\beta \approx +0.09$ to the amplitude-definition effect (mechanism iii, comparing (a) to (b)) and $\Delta\beta \approx +0.02$ to the non-astronomical weather component (mechanism ii, comparing (b) to (c)); the bulk of the slope excess, $\Delta\beta \approx +0.90$, remains in the strictly astronomical variant (c) and is therefore due to the spring–neap × $\cos\theta$ covariance documented in Section 5.1, mechanism (i). A direct estimate of $\mathrm{cov}(A_{\mathrm{local}}, \cos\theta)$ from the 5-year cached scene set (5,082 (site, sensor) scenes) gives mean per-site implied $\beta$-inflation factors $1 + \mathrm{cov} / (\langle A\rangle \cdot \langle \cos\theta\rangle)$ of 1.81, 1.76, 1.85, 1.89, and 1.73 — a range that brackets the empirical $\beta$ at every site. The FES2022b variant (d) yields a slightly lower $\beta = 1.70$ because the 1/30° global grid under-resolves the within-bay amplification of the spring–neap covariance: at Ganghwa-do, for instance, the FES $M_{2}$ amplitude at the Incheon-gauge coordinate is 1.02 m versus 2.83 m from the local harmonic decomposition of the KHOA record, reflecting the inability of a global grid to capture the funnel-shape resonance of the Han River estuary. Despite this amplitude under-estimate the fit *structure* is preserved (and at Suncheon Bay the FES variant predicts a slightly larger positive bias of +0.32 to +0.52 m than KHOA's +0.29 to +0.39 m, consistent with the global grid's lack of the south-coast intra-bay phase lag); its excellent overall fit ($R^{2} = 0.983$) confirms that it is the model *structure*, not the precise value of the fitted slope, that carries the *a priori* predictive power, supporting the a-priori applicability claimed in Section 5.3(a) for any waterline-DEM user without local tide-gauge access.

---

## 5. Discussion

### 5.1 Physical interpretation of $\beta > 1$

The leading-order theory (Section 3.3) predicts $\beta = 1$: the mean bias equals the product of the time-mean amplitude and the empirical mean cosine of the overpass phase. The observed pooled slope $\beta = 1.78$ (95 % CI 1.44–1.91) exceeds 1 by a robustly significant margin. We identify three contributing mechanisms.

**(i) Spring–neap covariance.** During spring tides (when the lunar $M_{2}$ and solar $S_{2}$ constituents reinforce each other), tidal amplitude is at its fortnightly maximum. The 14.77-day spring–neap cycle does not divide evenly into the 16- or 12-day sun-synchronous revisit cycles, so satellites preferentially catch certain phases of the spring–neap envelope. If those preferred phases also have $\cos\theta < 0$ (LW-side overpasses, as in the western Korean sites), the time-mean of $A\cdot\cos\theta$ is *more negative* than $\langle A\rangle\langle \cos\theta\rangle$, yielding $\beta > 1$. A direct computation of $\mathrm{cov}(A, \cos\theta)$ from the data (not shown here; see supplementary) yields covariance contributions of 0.15–0.30 m, consistent with the observed slope.

**(ii) Diurnal constituents ($K_{1}$, $O_{1}$).** The Korean western coast has a mixed tidal regime in which two unequal high waters occur each day (diurnal inequality). Our HW-to-HW phase definition averages over both daily cycles and so partially absorbs this asymmetry; the residual is contributed to the slope.

**(iii) Definition of the amplitude reference.** We use $A = \tfrac{1}{2}(\overline{\mathrm{HW}} - \overline{\mathrm{LW}})$ as a robust scalar amplitude. The strictly periodic-cos model would require $A$ to be the $M_{2}$ amplitude alone, obtainable from a harmonic decomposition (e.g., UTide; Codiga, 2011) and used as a sensitivity test in Section 4.7. Using the mean-HW-LW envelope inflates $A$ relative to the pure $M_{2}$ amplitude only slightly, leaving residual slope contributions to mechanisms (i)–(ii).

### 5.2 The bipolar bias: a regional amphidromic phenomenon

The most novel finding is that the *sign* of the mean bias reverses between the western and southern Korean coast. The Korean peninsula sits on the eastern edge of the Yellow Sea $M_{2}$ amphidromic system (see Section 1.4; Choi et al., 2014). The HW phase at Incheon (DT_0001) lags the Yeosu HW phase by about 4 h: Yeosu HW arrives at LST $\approx$ 10:00 (just before our 11:00 satellite peak), Incheon HW at LST $\approx$ 14:00 (well after). Consequently, the 11:00 KST overpass catches different phases of the local tide:

- **Western sites (Incheon-phased)**: 11:00 $\approx 3$ h before HW $\approx$ middle of ebb $\approx$ phase $\approx 235°$ (within our HW-to-HW convention) $\Rightarrow \cos\theta < 0 \Rightarrow$ negative mean bias.
- **Southern site (Yeosu-phased)**: 11:00 $\approx 1$ h after HW $\approx$ early ebb $\approx$ phase $\approx 35° \Rightarrow \cos\theta > 0 \Rightarrow$ positive mean bias.

Lee, K. et al. (2022) previously demonstrated, in the satellite-altimetry domain, that sampling-phase shifts near Incheon contribute substantially to apparent multi-mission sea-level-rise trends; their analysis, however, addresses the *temporal* evolution of the sampling phase within a single coastal footprint over 1993–2019. To our knowledge the present analysis is the first quantitative demonstration in the *spatial* domain — i.e. that **for an instantaneously-sampling optical waterline workflow the sign of the bias reverses across the regional amphidromic structure**, independently of the satellite or the local tidal range alone. We return to candidate analogous regions in Section 5.5.

### 5.3 Implications for waterline DEM literature

Three implications follow.

**(a) Single-sensor bias correction is feasible *a priori*.** Equation \eqref{eq:bias} allows any user of waterline DEMs to estimate the systematic vertical bias of their product from only (i) the satellite overpass time and (ii) the local tide phase at that time, computable from any global tide model — for instance FES2022b (Carrère et al., 2022; Lyard et al., 2021), as validated in Section 4.7(d), or TPXO (Egbert and Erofeeva, 2002). The LOO-validated RMSE of 0.16 m on $\beta \cdot A \cdot \langle \cos\theta\rangle$ (0.11 m with the FES2022b reference) is far smaller than the vertical bias itself (0.36–1.09 m), offering immediate *a priori* bias removal at low computational cost and without requiring local tide-gauge access.

**(b) The truncation bands cannot be filled by additional optical imagery.** Up to 2.5 km of tidal-flat width on Ganghwa-do (≈ 22 % of the total intertidal width) is permanently unsampled by current optical missions because no scene exists with the relevant high-tide overpass. Sub-tide DEMs at the upper-flat boundary are *extrapolated* from contours within the sampled range, with no empirical constraint. Users of such DEMs should be cautious about applications dependent on the upper intertidal — including aquaculture zoning, salt-marsh edge mapping, and storm-surge inundation modelling.

**(c) The need for radar integration: a theoretical basis for empirical multi-sensor data-collection-window optima.** Sentinel-1 SAR has overpasses near 06:00 and 18:00 LST, displaced from the optical 11:00 LST by approximately 5 h. Since $5\,\text{h} \approx 0.4 \times M_{2}$ cycle, the SAR-time $\langle \cos\theta\rangle$ is approximately orthogonal to the optical $\langle \cos\theta\rangle$. A hybrid optical+SAR sample population therefore has a much-reduced $|\langle \cos\theta\rangle|$ and, by Eq. \eqref{eq:bias}, a proportionally reduced mean bias; as an order-of-magnitude estimate, combining equal numbers of optical and SAR samples halves the western-coast mean bias, with proportional gain in spread.

This phase-orthogonality argument supplies the missing first-principles explanation for an empirical observation reported independently by Lee, J. et al. (2025) on the Taean Peninsula. Using Landsat-8/9, Sentinel-2A/B, and Sentinel-1A imagery over a single calendar year (2022) and validating against UAV-LiDAR, they identify a 5-month minimum data-collection window past which the fusion DEM mean absolute error (MAE) no longer drops below approximately 25 cm. We tested this quantitatively at Garorim Bay — the closest of our five sites to their Taean Peninsula study area, approximately 30 km north of Geunso Bay — using the full 5-year cumulative-sample trajectory of $|\langle \cos\theta\rangle|(t)$. The trajectory **does not** drop below 0.10 at any time within the 5-year record: its 5-year geometric asymptote is $|\langle \cos\theta\rangle|_{\infty} = 0.208$, and its 5-month value is $|\langle \cos\theta\rangle|_{152\,\text{d}} = 0.329$ — i.e., the sampled-phase vector is still approximately 58 % above its sun-synchronous floor at the Lee et al. optimum.

The 5-month optimum is therefore *not* a "$|\langle \cos\theta\rangle| \to 0$" timescale; it is the timescale at which the *random-sampling uncertainty* on $|\langle \cos\theta\rangle|(t)$ becomes comparable to the *deterministic asymptote*. A 30-day block-bootstrap of the combined Garorim trajectory (300 resamples; chronological blocks preserve spring–neap autocorrelation) yields a 95 % CI half-width on $|\langle \cos\theta\rangle|(152\,\text{d})$ of 0.16, essentially the same magnitude as the asymptote 0.21. Beyond 5 months the random-walk noise on the cumulative $|\langle \cos\theta\rangle|$ shrinks (as $t^{-1/2}$) but the geometric asymptote does not, so adding more optical scenes can no longer improve the systematic-bias estimate; only a phase-orthogonal sensor (i.e., one whose overpass time samples a different part of the tidal cycle) can. This is precisely the 5-month saturation observed empirically by Lee, J. et al. (2025); their 27.9 cm to 25.6 cm (8 %) optical-to-fusion reduction is consistent with their SAR sub-population on a 5-month window still being partially correlated with the optical phase.

Two further predictions follow from this argument. First, extending the SAR record beyond 5 months until *its* $|\langle \cos\theta\rangle|(t)$ also saturates should drive the fusion bias toward the orthogonal limit (approximately 50 % reduction). Second, the optimal collection window is *coast-dependent*: on the south-coast amphidromic regime where mean overpass phase is near HW (Suncheon Bay), the local $A$ and $\langle \cos\theta\rangle$ that govern Eq. \eqref{eq:bias} produce a substantially shorter collection-window optimum than at the Taean Peninsula. A dedicated test of these predictions is the natural next step.

### 5.4 Limitations

**(i) Planar-slope assumption.** The horizontal-domain numbers (1.06–2.53 km truncation widths) assume a uniform planar slope per site. Real tidal flats have non-uniform hypsometry, often concave upward (more area at lower elevations). Replacing the planar assumption with site-specific LiDAR or SRTM hypsometric curves would refine the horizontal numbers but leave the vertical RMSE and elevation truncation bands unchanged.

**(ii) KHOA-as-reference includes weather.** Hourly KHOA observations contain non-astronomical components (storm surge, atmospheric-pressure effects, seasonal mean-sea-level changes). At the 5-year aggregation scale these contributions partially average out, but they contribute to the residual scatter in the regression. The FES2022b sensitivity test of Section 4.7(d) isolates the orbital component by replacing both the reference and the satellite-time tides with the astronomical-only series; the resulting modest reduction of $\beta$ from 1.78 to 1.70 quantifies the weather contribution as $\Delta\beta \lesssim 0.1$, leaving the spring–neap covariance of Section 5.1(i) as the dominant source of the slope excess.

**(iii) FES2022b grid does not resolve within-bay tidal amplification.** The 1/30° (≈ 3.3 km) horizontal resolution of FES2022b is coarse relative to the funnel-shape resonance of the Han River estuary at Ganghwa-do and of the within-bay channels at Garorim, Gomso, Hampyeong, and Suncheon. The site-specific $M_{2}$ amplitudes interpolated from FES2022b at the KHOA gauge coordinates underestimate the locally observed amplitudes by 30–60 % (e.g., Ganghwa: FES 1.02 m vs KHOA-derived 2.83 m). The FES2022b sensitivity test of Section 4.7(d) therefore validates the *structure* of the bias model and the *sign* of the predicted bias at every site, but the absolute magnitudes of the predicted bias under the FES variant are lower than the KHOA-derived values where the global grid most strongly under-resolves the local geometry. Practitioners operating outside Korea with no local gauge data should expect the global-model variant to provide *lower-bound* magnitudes of the systematic bias on similarly resonant macrotidal coasts; the magnitudes will rise toward the KHOA-style values whenever the global model adequately resolves the relevant bathymetry.

**(iv) Single-gauge representation.** Each site is referenced to a single KHOA gauge that may not perfectly represent the bay's mean tide. Multi-gauge averaging would smooth local advection effects; we expect a $< 10$ % change in the regression coefficients.

**(v) Cloud-cover screening.** A cloud threshold of 60 % retains many scenes likely partly contaminated; tightening this threshold reduces sample size but minimally changes the bias metrics (tested at 30 % threshold, results within $\pm 2$ % of all stats).

### 5.5 Generality

The analytical model (Eq. \eqref{eq:bias}) is *not* specific to Korea: it depends only on the local tidal amplitude and on the satellite overpass phase. Wherever both quantities can be evaluated (global tide model + satellite ephemeris), the same first-order bias correction applies. The bipolar polarity is, however, specific to regions crossed by an amphidromic phase gradient comparable to 1/4 of an $M_{2}$ cycle (approximately 3 h). We hypothesise that analogous gradients exist on, for example, the Bay of Fundy and the Gulf of Maine (U.S./Canadian Atlantic), the southern North Sea (the Wash, the German Bight), and parts of the Australian north coast.

An important distinction must be drawn between the *structure* of the model and the *value* of its fitted coefficient. The model structure — mean bias proportional to $A \cdot \langle \cos\theta\rangle$ — is derived from first principles (Section 3.3) and is universal for any sun-synchronous optical sensor over any tidally dominated coast. The fitted slope $\beta = 1.78$ absorbs the spring–neap covariance specific to the Korean $M_{2}$/$S_{2}$ regime (Section 5.1) and may differ elsewhere; the physical mechanism that drives $\beta > 1$, however, is itself generic: wherever the spring–neap beat frequency is incommensurate with the satellite revisit cycle, a non-zero $\mathrm{cov}(A, \cos\theta)$ will inflate $\beta$ above its theoretical floor of 1. Users outside Korea need not adopt 1.78 directly; the recommended workflow is to compute $\langle \cos\theta\rangle$ from their own scene metadata and a global tide model (e.g., FES2022b or TPXO), then — if local gauge data are available — fit a site-specific $\beta$ to calibrate the correction. In the absence of gauge data, the first-order correction with $\beta = 1$ already captures the sign and leading-order magnitude of the bias.

---

## 6. Conclusions

These results directly answer the three open questions of Section 1.3.

*In answer to question 1 (is the bias systematic and predictable?):*

1. Over the macrotidal Korean coast (2020–2024, 5,082 cloud-screened Landsat-8/9 + Sentinel-2 scenes from five tidal flats), sun-synchronous optical satellites sample only 70–80 % of the local astronomical tidal envelope.

2. A one-parameter analytical model, $\text{mean bias} = \beta \cdot A \cdot \langle \cos\theta\rangle$, where $A$ is the local tidal amplitude and $\langle \cos\theta\rangle$ the mean cosine of the satellite-overpass tide phase, explains 98 % of the cross-site, cross-sensor variance with slope $\beta = 1.78$ (95 % CI 1.44–1.91, $p < 10^{-11}$). The model is stable across calendar years ($R^{2}$ 0.85–0.95), seasons (0.85–0.98), and sensors ($\geq 0.99$). Leave-one-site-out validation yields RMSE = 0.16 m and correct sign in 15/15 held-out cases.

*In answer to question 2 (how does the bias vary along regional amphidromic gradients?):*

3. The mean tide-height bias is **bipolar in sign**: $-0.5$ to $-1.2$ m on the four western sites and $+0.3$ to $+0.4$ m at Suncheon Bay on the southern coast. The polarity reverses across the regional amphidromic gradient and is independent of tidal amplitude per se; it is fully captured by the sign of $\langle \cos\theta\rangle$ in the analytical model.

*In answer to question 3 (what is the practical translation into DEM elevation errors?):*

4. Translated into elevation-domain DEM errors via quantile mapping, the bias amounts to an **elevation-domain RMSE of 0.36–1.09 m** (an upper-bound estimate of the systematic vertical-error contribution to a waterline DEM built from the same scenes; not a per-pixel DEM validation against ground truth), equivalent to **179–1,359 m of horizontal contour displacement** on planar tidal flats. Permanently irrecoverable truncation bands occupy 0.99–2.02 m of vertical range, or **up to 2.5 km of intertidal width** at Ganghwa-do.

5. Increasing optical revisit frequency cannot remove the bias: more scenes at the same overpass time only refine the histogram shape, not the systematic mean shift. Removing the bias requires sampling at substantially different overpass phases — most practically by integrating Sentinel-1 SAR observations at the 06:00 / 18:00 LST orbit.

6. The $\beta \cdot A \cdot \langle \cos\theta\rangle$ model accounts for the saturation of empirically observed multi-sensor data-collection-window optima on the Korean coast (Lee, J. et al., 2025). The optimum is the time at which the residual $|\langle \cos\theta\rangle|$ of a combined sun-synchronous optical sample population falls below other waterline-extraction error contributions. Beyond that timescale, only a phase-orthogonal SAR sensor can further reduce the bias.

*Beyond the three open questions:*

7. The bias model and its predictive sign are reproducible from a global ocean tide model alone (FES2022b reference yields $R^{2} = 0.983$, leave-one-site-out RMSE = 0.11 m, correct sign at 15/15 held-out points). The *a priori* correction is therefore applicable worldwide without requiring local tide-gauge data — a prerequisite for global-scale operationalisation of waterline-DEM bias removal.

The analytical bias model provides an *a priori* correction available from any global tide model, applicable to any waterline-DEM product worldwide. As an immediate practical application, the model can serve as a quality-assessment layer: existing and future waterline-DEM products can be tagged with predicted bias magnitude and sign from satellite ephemeris and tide-model outputs alone, without requiring independent ground-truth data. More broadly, the phase-dependent nature of the bias carries implications for future mission design: non-sun-synchronous orbits or deliberately staggered local-time constellations would sample the tidal phase space more uniformly. As a concrete benchmark, a two-satellite constellation with overpass times staggered by 3 h (1/4 of an $M_{2}$ cycle, i.e. *phase-orthogonal* by construction) would reduce the combined-population $|\langle \cos\theta\rangle|$ by approximately 50 % and halve the systematic bias predicted by Eq. \eqref{eq:bias} — a gain that no increase in revisit frequency on a single sun-synchronous orbit can match.

---

## Data and code availability

All raw KHOA tide-gauge data are publicly available through the Korea Open Data Portal (`apis.data.go.kr/1192136`). Google Earth Engine scene metadata is reproducible from public collections (LANDSAT/LC08/C02/T1_L2, LANDSAT/LC09/C02/T1_L2, COPERNICUS/S2_HARMONIZED). The full analytical pipeline, derived parquet/CSV tables, and figure-generation scripts will be released on a Zenodo-archived GitHub repository upon acceptance (DOI to be assigned). The intermediate `multisite_5y_*.parquet` and `dem_error_*.csv` derived products are < 50 MB total.

## Acknowledgements

The KHOA tide-gauge data are provided under the Korean Open Government License. Earth Engine access was provided by Google for academic use. We thank the developers of pyTMD, Cartopy, UTide, and eo-tides for open-source tooling.

## Funding

This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors.

## CRediT authorship contribution statement

**[Author 1 — full name]**: Conceptualization, Methodology, Software, Formal analysis, Investigation, Data curation, Visualization, Writing – original draft, Writing – review & editing, Project administration.

<!-- If multiple authors, list each with the relevant CRediT roles; remove this comment before submission. -->

## Declaration of competing interest

The authors declare that they have no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

---

## References

(See `manuscript/references.bib` for BibTeX entries.)

- Bishop-Taylor, R., Sagar, S., Lymburner, L., Beaman, R. J., 2019a. *Between the tides: Modelling the elevation of Australia's exposed intertidal zone at continental scale.* Estuarine, Coastal and Shelf Science 223, 115–128. doi:10.1016/j.ecss.2019.03.006.
- Bishop-Taylor, R., Sagar, S., Lymburner, L., Alam, I., Sixsmith, J., 2019b. *Sub-pixel waterline extraction: Characterising accuracy and sensitivity to indices and spectra.* Remote Sensing 11, 2984. doi:10.3390/rs11242984.
- Bishop-Taylor, R., Phillips, C., Sagar, S., Newey, V., Sutterley, T., 2025. *eo-tides: Tide modelling tools for large-scale satellite Earth observation analysis.* Journal of Open Source Software 10 (109), 7786. doi:10.21105/joss.07786.
- Choi, B.-J., Hwang, C., Lee, S. H., 2014. *Meteotsunami-tide interactions and high-frequency sea level oscillations in the eastern Yellow Sea.* Journal of Geophysical Research: Oceans 119, 6725–6742. doi:10.1002/2013JC009788.
- Codiga, D. L., 2011. *Unified Tidal Analysis and Prediction Using the UTide Matlab Functions.* Technical Report 2011-01, Graduate School of Oceanography, University of Rhode Island, Narragansett, Rhode Island. 59 pp.
- Drusch, M., Del Bello, U., Carlier, S., Colin, O., Fernandez, V., Gascon, F., Hoersch, B., Isola, C., Laberinti, P., Martimort, P., Meygret, A., Spoto, F., Sy, O., Marchese, F., Bargellini, P., 2012. *Sentinel-2: ESA's optical high-resolution mission for GMES operational services.* Remote Sensing of Environment 120, 25–36. doi:10.1016/j.rse.2011.11.026.
- Egbert, G. D., Erofeeva, S. Y., 2002. *Efficient inverse modeling of barotropic ocean tides.* Journal of Atmospheric and Oceanic Technology 19, 183–204. doi:10.1175/1520-0426(2002)019<0183:EIMOBO>2.0.CO;2.
- Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., Moore, R., 2017. *Google Earth Engine: Planetary-scale geospatial analysis for everyone.* Remote Sensing of Environment 202, 18–27. doi:10.1016/j.rse.2017.06.031.
- Heygster, G., Dannenberg, J., Notholt, J., 2010. *Topographic mapping of the German tidal flats analyzing SAR images with the waterline method.* IEEE Transactions on Geoscience and Remote Sensing 48, 1019–1030. doi:10.1109/TGRS.2009.2031843.
- Khan, M. J. U., Ansary, M. N., Durand, F., Testut, L., Ishaque, M., Calmant, S., Krien, Y., Islam, A. K. M. S., Papa, F., 2019. *High-resolution intertidal topography from Sentinel-2 multi-spectral imagery: Synergy between remote sensing and numerical modeling.* Remote Sensing 11, 2888. doi:10.3390/rs11242888.
- Koh, C.-H., Khim, J. S., 2014. *The Korean tidal flat of the Yellow Sea: Physical setting, ecosystem and management.* Ocean & Coastal Management 102, 398–414. doi:10.1016/j.ocecoaman.2014.07.008.
- Lee, J., Kim, K., Kwak, G.-H., Baek, W.-K., Jang, Y., Ryu, J.-H., 2025. *Optimization of a multi-sensor satellite-based waterline method for rapid and extensive tidal flat topography mapping.* Estuarine, Coastal and Shelf Science 318, 109235. doi:10.1016/j.ecss.2025.109235.
- Lee, K., Nam, S., Cho, Y.-K., Jeong, K.-Y., Byun, D.-S., 2022. *Determination of long-term (1993–2019) sea level rise trends around the Korean Peninsula using ocean tide-corrected, multi-mission satellite altimetry data.* Frontiers in Marine Science 9, 810549. doi:10.3389/fmars.2022.810549.
- Lee, S.-K., Ryu, J.-H., 2017. *High-accuracy tidal flat digital elevation model construction using TanDEM-X science phase data.* IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing 10, 2713–2724. doi:10.1109/JSTARS.2017.2656629.
- Liu, Y., Zhou, M., Zhao, S., Zhan, W., Yang, K., Li, M., 2015. *Automated extraction of tidal creeks from airborne laser altimetry data.* Journal of Hydrology 527, 1006–1020. doi:10.1016/j.jhydrol.2015.05.058.
- Lyard, F. H., Allain, D. J., Cancet, M., Carrère, L., Picot, N., 2021. *FES2014 global ocean tide atlas: Design and performance.* Ocean Science 17, 615–649. doi:10.5194/os-17-615-2021.

- Carrère, L., Lyard, F., Cancet, M., Allain, D., Dabat, M.-L., Fouchet, E., Faugère, Y., Pujol, M.-I., Briol, F., Dibarboure, G., Picot, N., 2022. *A new barotropic tide model for global ocean: FES2022.* AVISO+ technical note (FES2022 / FES2022b release notes), CNES/CLS. Available via AVISO+ Tides Modelling: https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html.
- Mason, D. C., Davenport, I. J., Robinson, G. J., Flather, R. A., McCartney, B. S., 1995. *Construction of an inter-tidal digital elevation model by the "Water-Line" method.* Geophysical Research Letters 22, 3187–3190. doi:10.1029/95GL03168.
- Murray, N. J., Phinn, S. R., Clemens, R. S., Roelfsema, C. M., Fuller, R. A., 2012. *Continental scale mapping of tidal flats across East Asia using the Landsat archive.* Remote Sensing 4, 3417–3426. doi:10.3390/rs4113417.
- Murray, N. J., Clemens, R. S., Phinn, S. R., Possingham, H. P., Fuller, R. A., 2014. *Tracking the rapid loss of tidal wetlands in the Yellow Sea.* Frontiers in Ecology and the Environment 12, 267–272. doi:10.1890/130260.
- Murray, N. J., Phinn, S. R., DeWitt, M., Ferrari, R., Johnston, R., Lyons, M. B., Clinton, N., Thau, D., Fuller, R. A., 2019. *The global distribution and trajectory of tidal flats.* Nature 565, 222–225. doi:10.1038/s41586-018-0805-8.
- Ryu, J.-H., Won, J.-S., Min, K. D., 2002. *Waterline extraction from Landsat TM data in a tidal flat: A case study in Gomso Bay, Korea.* Remote Sensing of Environment 83, 442–456. doi:10.1016/S0034-4257(02)00059-7.
- Ryu, J.-H., Kim, C.-H., Lee, Y.-K., Won, J.-S., Chun, S.-S., Lee, S., 2008. *Detecting the intertidal morphologic change using satellite data.* Estuarine, Coastal and Shelf Science 78, 623–632. doi:10.1016/j.ecss.2008.01.020.
- Sagar, S., Roberts, D., Bala, B., Lymburner, L., 2017. *Extracting the intertidal extent and topography of the Australian coastline from a 28 year time series of Landsat observations.* Remote Sensing of Environment 195, 153–169. doi:10.1016/j.rse.2017.04.009.
- Salameh, E., Frappart, F., Almar, R., Baptista, P., Heygster, G., Lubac, B., Raucoules, D., Almeida, L. P., Bergsma, E. W. J., Capo, S., De Michele, M., Idier, D., Li, Z., Marieu, V., Poupardin, A., Silva, P. A., Turki, I., Laignel, B., 2019. *Monitoring beach topography and nearshore bathymetry using spaceborne remote sensing: A review.* Remote Sensing 11, 2212. doi:10.3390/rs11192212.
- Sent, G., Antunes, C., Spyrakos, E., Jackson, T., Atwood, E. C., Brito, A. C., 2025. *What time is the tide? The importance of tides for ocean colour applications to estuaries.* Remote Sensing Applications: Society and Environment 37, 101425. doi:10.1016/j.rsase.2024.101425.
- Tseng, K.-H., Kuo, C.-Y., Lin, T.-H., Huang, Z.-C., Lin, Y.-C., Liao, W.-H., Chen, C.-F., 2017. *Reconstruction of time-varying tidal flat topography using optical remote sensing imageries.* ISPRS Journal of Photogrammetry and Remote Sensing 131, 92–103. doi:10.1016/j.isprsjprs.2017.07.008.
- Wang, X., Liu, Y., Ling, F., Liu, Y., Fang, F., 2020. *Spatio-temporal change detection of Ningbo coastline using Landsat time-series images during 1976–2015.* ISPRS International Journal of Geo-Information 9, 68. doi:10.3390/ijgi9020068.
- Worm, B., Barbier, E. B., Beaumont, N., Duffy, J. E., Folke, C., Halpern, B. S., Jackson, J. B. C., Lotze, H. K., Micheli, F., Palumbi, S. R., Sala, E., Selkoe, K. A., Stachowicz, J. J., Watson, R., 2006. *Impacts of biodiversity loss on ocean ecosystem services.* Science 314, 787–790. doi:10.1126/science.1132294.
- Yun, G. R., Ryu, J.-H., Kim, K. L., Lee, J. H., Lee, S.-K., 2022. *TanDEM-X-based Ganghwa tidal flat high-resolution topographic map construction and service.* GEO DATA 4 (1), 37–42. doi:10.22761/DJ2022.4.1.004.
