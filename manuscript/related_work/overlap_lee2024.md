# Overlap analysis: Lee et al. (2024 SSRN preprint → 2025 ECSS published)

> **Erratum (2026-05-24):** The "Park & Choi et al. 2022" citation
> referenced throughout this working note (doi `10.3389/fmars.2022.810549`)
> is in fact authored by **Lee, K., Nam, S., Cho, Y.-K., Jeong, K.-Y.,
> Byun, D.-S. (2022)** — verified directly from the Frontiers in Marine
> Science publisher page. The misattribution has been corrected
> throughout the submission-bound manuscript files
> (`draft.md`, `abstract_ko.md`, `cover_letter.md`, `references.bib`).
> The historical "Park & Choi" wording below is retained as a record of
> the pre-submission analysis and should be read as referring to that
> same DOI authored by Lee K. et al. (2022).

**Update (2026-05-23): both PDFs obtained and full-text verified.**
The author-provided files are stored in this folder:

- `lee2024_ssrn_preprint.pdf` (47 pp., SHA-256 `23f7befd...`,
  originally submitted to *Marine Pollution Bulletin* per the page header,
  posted to SSRN 2024-06-02)
- `lee2025_ecss_published.pdf` (12 pp., SHA-256 `994a6212...`,
  published in **Estuarine, Coastal and Shelf Science Vol. 318 (2025) Article 109235**,
  DOI `10.1016/j.ecss.2025.109235`, CC BY 4.0,
  Received 20 May 2024 · Revised 27 Feb 2025 · Accepted 4 March 2025 · Online 4 March 2025)

The published ECSS title is slightly different from the SSRN preprint:

| Version | Title |
|---|---|
| SSRN 2024 | *Optimization of Multisensor Satellite-Based Waterline Method for Detecting Topographic Changes in Tidal Flats Across a Wide Area* |
| ECSS 2025 | *Optimization of a multi-sensor satellite-based waterline method for **rapid and extensive** tidal flat topography mapping* |

Both PDFs were converted to plain text (`pypdf`) and grepped for the
problem-framing keywords central to our paper — `alias*`, `phase`,
`sampling bias`, `sun-synchronous`, `amphidromic`, `orthogonal`,
`cos θ`, `Suncheon`, `Park & Choi`, `Bishop-Taylor`. **Zero matches**
in either version (only one false positive: their citation to
Lee & Ryu 2017 "TanDEM-X *science phase data*", which is unrelated
to tidal-sampling phase). This confirms with full-text certainty
that Lee et al. (2024/2025) does not frame the problem in our
terms and does not pre-empt our analytical contribution.

---

## 1. Lee et al. 2025 ECSS in one paragraph (verified from full text)

- **Group**: KIOST (Korea Institute of Ocean Science & Technology), Korea Ocean
  Satellite Center, Busan. Senior author **Joo-Hyung Ryu** has led Korean
  tidal-flat waterline research since 2002.
- **Status (2026-05-23)**: **Now formally published in ECSS Vol. 318 (2025)
  109235, Open Access (CC BY 4.0)**. The SSRN preprint (4851337) was the
  pre-peer-review submission to *Marine Pollution Bulletin* (per its page
  header); after revision it was accepted by ECSS.
- **Goal**: *Operational optimization* of the multi-sensor waterline workflow
  for routine wide-area tidal-flat DEM updates on the Korean west coast.
- **Study area**: **Taean Peninsula** region only (one sub-region of the
  Korean west coast). Three sub-sites: **Geunso Bay** (semi-enclosed,
  6 m tidal range), **Hwangdo / Cheonsu Bay** (island type, 4.5 m),
  **Daecheon estuary** (estuarine, 3.9 m). Total area 179.6 km² ≈ 7.2 %
  of Korean tidal-flat area. **No south coast** (no Suncheon-type case).
- **Sensors & time span**: Landsat 8/9 + Sentinel-2A/B + **Sentinel-1A**.
  **Single calendar year only: 1 Jan 2022 – 31 Dec 2022**, 51 images total
  (9 L8/9 + 16 S2 + 26 S1).
- **Tide source**: **KHOA Boryeong tide station** + **TideBed** local
  propagation model (nearest-port time/height ratios per the formula
  `H_r = (H_s - Z_s) × H_o + Z_r`). NOT a global model (FES, TPXO).
- **Waterline detection**: NDWI (McFeeters 1996) for optical; VV backscatter
  + CWM filter + **Otsu thresholding** for SAR; TIN interpolation; KHOA
  1:5000 coastline used as land mask.
- **Validation reference**: **UAV-LiDAR DSM** acquired at Hwangdo on
  17 Aug 2022 (DJI M300-RTK + Zenmuse L1, 240 k pts/s, ±3 cm distance
  accuracy, flown at 150 m AGL). Resampled to 0.5 m; satellite DEMs
  resampled to 30 m for matched comparison.
- **Accuracy metric**: **MAE** (Mean Absolute Error) only — no RMSE,
  no R², no confidence intervals, no LOO.
- **Headline numerical results (ECSS Section 4.2, 5)**:

  | Collection window | Fusion MAE | Optical MAE | SAR MAE |
  |---|---|---|---|
  | 3 months | ~44 cm | 46.9 cm | 74.6 cm |
  | **5 months** | **25.6 cm** | 27.9 cm | 50.8 cm |
  | 6 months | ~27 cm | 28.8 cm | ~36 cm |
  | 7–12 months | 23.3–26.1 cm | **22.1 cm** (best) | 34.9–36.8 cm |

  → **5-month optimum** (defined as the point past which MAE no longer
  drops below an empirically chosen threshold). At 5 months the fusion
  DEM is 8.16 % more accurate than optical-only and 49.56 % more accurate
  than SAR-only.

- **Mean tidal-interval finding (ECSS Section 4.4)**: when imagery
  accumulates to ≥5 months, the mean tide-level spacing falls below 30 cm
  (SD ≈ 33 cm), which they treat as the empirical condition for a
  usable DEM. This is the closest the paper comes to acknowledging the
  sampling-physics issue our work formalises — but they only report
  it as an empirical descriptive statistic.

## 2. Full reference list of ECSS 2025 (verified from PDF p. 11–12)

The published ECSS paper has ~50 references (very similar to the SSRN
preprint's 49). All references confirmed by direct PDF reading.

### 2.1 Most-cited Korean tidal-flat tradition
- **Ryu, Won, Min (2002, RSE)** — foundational Gomso Bay waterline
- **Ryu et al. (2008, ECSS)** — intertidal morphologic change
- **Ryu, Choi, Lee (2014, OCM)** — Korean tidal-flat thematic mapping review
- **Lee, Ryu (2017, IEEE JSTARS)** — TanDEM-X Ganghwa DEM
- **Yun, Ryu, Kim, Lee, Lee (2022, Geodata)** — TanDEM-X Ganghwa service
- **Lee, Ryu, Choi, Soh, Eom, Won (2011, JCR)** — Ganghwa decadal waterline
- **Xu, Kim, Kim, Cho, Lee (2016, ECSS)** — Gomso & Hampyeong seasonal
- **Choi, Ryu (2011, EEG)** — sedimentary facies, Gomso
- **Woo et al. (2005, 2006, 2016)** — sedimentological context

### 2.2 International method anchors
- **Murray et al. (2019, Nature)** — global tidal-flat distribution
- **Sagar, Roberts, Bala, Lymburner (2017, RSE)** — 28-yr Landsat
  Australian intertidal (the methodological closest relative of DEA Intertidal)
- **Salameh, Frappart, Turki, Laignel (2020, ISPRS J Photogr)** — S1+S2
  fusion Arcachon/Veys France (cited as their main multi-sensor predecessor)
- **Liu, Li, Zhou, Yang, Mao (2013, RS)** — Dongsha Sandbank China
  optical+SAR fusion (the very first multi-sensor waterline fusion paper)
- **Khan et al. (2019, Remote Sensing)** — S2 + numerical modelling
- **Mason, Davenport, Flather, Gurney (1998)** — Wash, UK waterline
- **Mason, Scott, Dance (2010, ECSS)** — Morecambe Bay
- **Lohani, Mason (1999, IJRS)** — Holderness coast
- **Niedermeier, Hoja, Lehner (2005, Ocean Dyn)** — German Bight SAR
- **Heygster, Dannenberg, Notholt (2010, IEEE TGRS)** — Wadden Sea SAR
- **Li, Heyster, Notholt (2014, IEEE JSTARS)** — Wadden Sea morphological
- **Tong, Deroin, Pham (2020, ECSS)** — Vietnam, "optimal waterline"
- **Cao, Zhou, Li, Li (2020, RSE)** — Landsat full time series
- **Wang, Liu, Jin, Sun, Wei (2019, ISPRS)** — Jiangsu
- **Kang et al. (2017, ECSS; 2023, FMS)** — Jiangsu iterative waterline
- **Jia et al. (2021, RSE)** — China GEE Sentinel-2 tidal flats
- **Tseng et al. (2017, ISRS)** — time-varying waterline reconstruction
- **Zhang et al. (2019, RS); Zhao et al. (2008, ECSS)** — China case studies
- **Koopmans, Wang (1994); Wang, Koopmans (1996)** — Wadden Sea original SAR
- **Valenzuela (1978, BLM)** — Bragg scattering theory for SAR waterlines
- **McFeeters (1996, IJRS)** — NDWI definition

### 2.3 Critical absences (verified from full text — DECISIVE)

The following are central to our paper but are **NOT cited** in either
the SSRN preprint or the ECSS published version. **Verified by full-text grep.**

| Topic | Absent reference | Our paper uses |
|---|---|---|
| Tidal-aliasing of sun-synchronous optical sensors | Bishop-Taylor et al. 2019a/b (RSE), Doxaran et al. 2014, Sent et al. 2025 (Tagus) | Yes — all four |
| Korean satellite-tide aliasing (altimetry) | **Park & Choi et al. 2022 Frontiers** (Yellow Sea altimetry sampling) | Yes — central reference |
| Australian DEA Intertidal / phase metrics | Bishop-Taylor et al. 2019a (RSE) | Yes |
| Analytical bias models | (none in Lee's list) | Yes — `bias = β·A·⟨cosθ⟩` |
| Global tide-model physics | (Lee uses TideBed local interpolation only) | Yes — pyTMD + FES2014 |
| Long-term phase stability / LOO validation | (none — different framing) | Yes — bootstrap + LOO |
| Amphidromic structure of Korean seas | (none — but it explains their west-coast results) | Yes — Choi et al. 2014, Park & Choi 2022, Suh 1999/2008 |
| 5-site, 5-year, multi-coast climatology design | (Lee = 1 site, 1 year, west only) | Yes — Ganghwa, Yeongjong, Cheonsu, Gomso, **Suncheon** |

**Implication confirmed by full-text reading.** Lee et al. (2024/2025)
treats the waterline workflow as a black box to be optimized empirically.
They achieve their 5-month optimum by *trial-and-error on collection
windows*. They never write down `⟨cos θ⟩`, never compute spread/offset
metrics, and never compare west-coast vs south-coast samplings — none
of these concepts exist in their text.

In their own Discussion (ECSS § 5) they implicitly acknowledge the
*existence* of sampling bias —

> "In most studies, when collecting satellite data at the highest and
> lowest tidal levels, the data collection period often extends due to
> satellite images not being acquired under the spring tide conditions
> or being unavailable due to weather conditions and satellite imaging
> schedules, even during the spring tide period."

— but proposes only *operational* workarounds (link to nearest spring tide
period; supplement with airborne bathymetric LiDAR). They do not derive
the magnitude of the bias, predict its sign, or relate it to the
local tide phase. This is exactly the gap our manuscript fills.

## 3. Side-by-side overlap matrix (full-text verified)

| Dimension | **Lee et al. 2025 ECSS** (verified from PDF) | **Our paper** (in prep.) | Overlap |
|---|---|---|---|
| **Region** | **Taean Peninsula only** (3 sub-sites: Geunso Bay, Hwangdo/Cheonsu, Daecheon estuary). West coast only. 179.6 km² = 7.2 % of Korean tidal flats. | 5 sites along entire Korean coast — Ganghwa, Yeongjong, Cheonsu, Gomso, **Suncheon (south coast)** | Partial (Cheonsu overlap) |
| **Sensors** | Landsat 8/9 + Sentinel-2A/B + **Sentinel-1A** | Landsat 8/9 + Sentinel-2A/B (S1A modelled as a phase-orthogonal mechanism, not used for DEM) | Partial |
| **Time span** | **2022 only**, 1 calendar year, 51 images | **2020-01 → 2025-05** (≈5 yr × 5 sites) — long-term climatology | **Disjoint design intent** |
| **Tide source** | **KHOA Boryeong** observed + **TideBed** local-propagation model (nearest-port time/height ratios) | **KHOA 1-hr observed (5 yr) + pyTMD FES2014 reconstruction** for ⟨cos θ⟩ over satellite epoch | Different (local vs global tide framework) |
| **Primary output** | DEM raster of Hwangdo + cross-section profiles + topographic maps of Geunso/Daecheon | (a) per-site bias decomposition + (b) DEM-error envelope + (c) horizontal-equivalent ribbon + (d) `β·A·⟨cosθ⟩` analytical model | Different outputs |
| **Validation reference** | **UAV-LiDAR DSM @ Hwangdo, Aug 17 2022** (Zenmuse L1, 0.5 m grid resampled to 30 m) | TG climatology + LOO holdout per-site | Different |
| **Accuracy metric** | **MAE only** (cm) | **MAE + RMSE + R² + bootstrap CI + LOO** | Different metric system |
| **Headline numerical claim** | "5-month optimum; Fusion **MAE 25.6 cm**, Optical 27.9 cm, SAR 50.8 cm" | "bias = β·A·⟨cos θ⟩, **R² = 0.98**, LOO RMSE 0.16 m, horizontal error 178 m – 2.5 km" | Different metric system |
| **Conceptual contribution** | **Operational best practice** for routine mapping | **Analytical a-priori bias model** + correction tool | **Complementary** |
| **Cites tidal-aliasing literature?** | **No** (full-text grep: 0 hits) | Yes | Lee does not frame it as aliasing |
| **Mentions sun-synchronous limitation?** | Implicit only (Section 4.1: "no images at low tide / high tide" — descriptive, not modelled) | Yes — modelled explicitly via `⟨cos θ⟩` | Lee acknowledges but does not quantify |
| **Has analytical model?** | **No** (purely empirical optimization) | Yes (1-parameter β model) | **Major differentiator** |
| **Multi-coast sign-reversal demonstration?** | **No** (west coast only; Taean has 3.9–6 m tidal range, all positive cos θ) | **Yes** (west −1.2 m vs south +0.3 m, linked to amphidromic gradient) | **Unique to us** |
| **Predicts bias without imagery?** | No (needs to run the full DEM workflow to see the residual) | **Yes** (any pixel with TG / FES data) | **Unique to us** |
| **Open Access?** | **Yes (CC BY 4.0 since 2025-03-04)** — must cite carefully | (target also OA) | n/a |
| **Citation count** (2026-05-23) | 0 on Crossref / OpenAlex (paper only ~2 months old at index time) | n/a | n/a |

## 4. Concrete overlap zones — what we MUST address

### 4.1 SAR-needed conclusion
- **Lee 2025 (ECSS § 5)**: Empirically reports Fusion DEM (Optical + SAR)
  has MAE 25.6 cm at 5 months vs. Optical-only 27.9 cm and SAR-only 50.8 cm.
  The mechanism they offer is non-quantitative: optical misses high tide,
  SAR misses low tide, fusion fills both gaps.
- **Us**: Argues analytically that Sentinel-1 has ⟨cos θ⟩ near-orthogonal
  to Landsat/S2 (because 06:00 / 18:00 LST vs 10:30 / 11:00 LST), so it
  adds *new* phase information, not just *more* of the same.

**Risk**: A reviewer may say "Lee 2025 already showed SAR helps; what does
your analytical version add?"

**Differentiation language to add to Discussion**:
> "Lee, Kim, Kwak, Baek, Jang and Ryu (2025, *Estuarine, Coastal and
> Shelf Science* 318: 109235) recently demonstrated empirically that a
> 5-month optical+SAR fusion window achieves an MAE of 25.6 cm against
> UAV LiDAR on the Taean Peninsula tidal flats. Our work is complementary:
> using a 5-year multi-coast climatology we show that this empirical
> 5-month optimum can be predicted analytically from the time required
> for ⟨cos θ⟩ to fall below a threshold, that the residual bias after
> optical-only sampling is sign-determined by the local amphidromic
> phase (negative on the west coast, positive on the south coast), and
> that Sentinel-1 closes the gap because its 06:00/18:00 LST overpass
> populates a quadrant of (cos θ, sin θ) space that is nearly orthogonal
> to the 10:30/11:00 LST optical sampling. The closed-form bias model
> `bias = β · A · ⟨cos θ⟩` (R² = 0.98 across our five sites,
> leave-one-out RMSE = 0.16 m) provides the missing theoretical
> explanation for the Lee et al. (2025) empirical optimum and extends it
> to sites where UAV ground truth is unavailable."

### 4.2 Geographic adjacency, *not* overlap (corrected)
- Lee 2025 sites are all in the **Taean Peninsula** area: Geunso Bay
  (36.73°N), Hwangdo / Cheonsu Bay (36.58°N), Daecheon estuary (36.35°N).
- Our five sites *bracket* Lee 2025's Taean Peninsula coverage **without
  overlapping it**: **Garorim Bay (37.0°N)** is the nearest neighbour
  (~30 km north of Geunso Bay), and **Gomso Bay (35.6°N)** is the
  nearest neighbour ~80 km south of Daecheon. We do **not** include
  Cheonsu Bay or any Taean Peninsula site.

**This is favourable**: our paper does not re-do their DEM at the same
sites. Rather, our Garorim Bay site provides an *independent macrotidal
west-coast measurement* immediately adjacent to (but not coincident
with) Lee et al.'s area, while Suncheon Bay extends the analysis to a
south-coast amphidromic regime the Ryu group has not yet published on.

**Differentiation language to add to § 2.1**:

> "Of our five sites, Garorim Bay is the closest geographic neighbour
> (~30 km north) to the Taean Peninsula sites recently DEM-mapped by
> Lee et al. (2025); our analysis does not duplicate their UAV-validated
> DEM but complements it by characterising the sampling-phase geometry
> of the same macrotidal regime, and extends the analysis to a
> south-coast amphidromic site (Suncheon Bay) that lies outside their
> study region."

### 4.3 The 5-month optimum has a physical interpretation
- Lee 2025 finds 5 months empirically.
- We can show analytically that 5 months ≈ 10 spring-neap cycles, which
  is approximately the time required for ⟨cos θ⟩ on a Landsat 16-d cycle
  to fall to |⟨cos θ⟩| ≤ 0.1 at most Korean west-coast latitudes.

**This is the single strongest framing of our paper**: our model
*derives* their empirical rule from first principles. Reviewer will
read this as a major contribution.

### 4.4 Tide-model choice differentiator
- Lee 2025 uses **TideBed** (local linear interpolation between KHOA
  ports — formula in their Section 3.1.1, Eq. 1).
- We use **pyTMD + FES2014** (global harmonic constituents).

This means our results are **portable to any coast worldwide** where
FES is available, whereas Lee's TideBed approach is specific to coasts
with a dense KHOA-equivalent port network. Worth one sentence in the
methods to highlight portability.

### 4.5 What Lee 2025 Section 4.1 already says (free quote we can use)
The published Discussion already concedes the *existence* of the
sampling-phase asymmetry our paper formalises:

> "For the SAR data, the images for low tide were not collected
> (< 200 cm tidal height); the tidal flat area appeared to be reduced
> compared to the optical images, due to the influence of residual
> water on the tidal flats. For optical data, no images were collected
> at mid-to-high tide (> 600 cm tidal height); therefore, the images
> did not accurately reflect the upper topography of the tidal flat."
> — Lee et al. 2025, ECSS § 4.1

This is essentially an **English-prose statement of the bipolar bias
our `β·A·⟨cosθ⟩` model captures**. Use it in the Introduction (§ 1.3
Related Work) as evidence that the phenomenon is *operationally
recognised* even by leading practitioners but has not yet been
*analytically quantified*.

## 5. New citations the manuscript MUST add (high priority — UPDATED)

Replace the SSRN preprint citation with the **formally published ECSS
2025 version** (peer-reviewed, OA, citeable). Add the supporting
EGU conference items and the priority-threat Park & Choi 2022 paper.

```bibtex
@article{lee2025multisensor,
  author  = {Lee, Jingyo and Kim, Keunyong and Kwak, Geun-Ho and
             Baek, Won-Kyung and Jang, Yeongjae and Ryu, Joo-Hyung},
  title   = {Optimization of a multi-sensor satellite-based waterline
             method for rapid and extensive tidal flat topography mapping},
  journal = {Estuarine, Coastal and Shelf Science},
  volume  = {318},
  pages   = {109235},
  year    = {2025},
  doi     = {10.1016/j.ecss.2025.109235}
}

@misc{kim2025egu,
  author = {Kim, Keunyong and Lee, Jingyo and Kwak, Geun-Ho and Ryu, Joo-Hyung},
  title  = {An optimal approach for morphological changes of tidal
            flat using multi-satellite sensors},
  year   = {2025},
  howpublished = {EGU General Assembly 2025},
  doi    = {10.5194/egusphere-egu25-5013}
}

@misc{lee2025egu,
  author = {Lee, Jingyo and Kim, Keunyong and Lee, Donguk and
            Kwak, Geun-Ho and Ryu, Joo-Hyung},
  title  = {Long-Term Changes of Tidal Flat Areas in the Korean West
            Coast Using Time Series Satellite Imagery},
  year   = {2025},
  howpublished = {EGU General Assembly 2025},
  doi    = {10.5194/egusphere-egu25-16135}
}

@article{yun2022tandemx,
  author  = {Yun, Ga Ram and Ryu, Joo-Hyung and Kim, Kye Lim and
             Lee, Jin Hyung and Lee, Seung-Kuk},
  title   = {{TanDEM-X-based Ganghwa Tidal Flat High-resolution
             Topographic Map Construction and Service}},
  journal = {GEO DATA},
  volume  = {4},
  number  = {1},
  pages   = {37--42},
  year    = {2022},
  doi     = {10.22761/DJ2022.4.1.004}
}

@article{lee2022sealevel,
  author  = {Lee, Kyungman and Nam, SungHyun and Cho, Yang-Ki and Jeong, Kwang-Yeon and Byun, Do-Seong},
  title   = {Determination of Long-Term (1993–2019) Sea Level Rise
             Trends Around the Korean Peninsula Using Ocean
             Tide-Corrected, Multi-Mission Satellite Altimetry Data},
  journal = {Frontiers in Marine Science},
  volume  = {9},
  pages   = {810549},
  year    = {2022},
  doi     = {10.3389/fmars.2022.810549}
}
```

## 6. Bottom line (updated after full-text verification)

Lee et al. **2025 ECSS** is **complementary, not pre-emptive**. The
verdict from the full-text comparison is even *stronger* than the
metadata-only analysis suggested:

| Lee 2025 ECSS | Our paper |
|---|---|
| 1 region (Taean Peninsula, 3 sub-sites) | 5 sites across 2 coasts (west + south) |
| 1 year (2022) | 5 years (2020–2025) |
| MAE only | MAE + RMSE + R² + bootstrap + LOO |
| TideBed local interpolation | pyTMD + FES2014 global |
| UAV-LiDAR ground truth | TG climatology, no field campaign |
| Empirical 5-month rule | Closed-form `β·A·⟨cosθ⟩`, R² = 0.98 |
| Workflow optimization | Sampling-physics theory + a-priori correction |
| 0 mentions of "alias", "phase", "amphidromic" | Central framing |
| Concedes the asymmetry exists (§ 4.1, § 5) | Quantifies & predicts the asymmetry |
| Cited by 0 (as of 2026-05-23) | n/a |

The published ECSS Discussion explicitly says
*"satellite images not being acquired under the spring tide conditions
or being unavailable due to weather conditions and satellite imaging
schedules, even during the spring tide period"* — they describe our
phenomenon in prose, propose only operational workarounds (link
neighboring spring-tide imagery, supplement with bathymetric LiDAR),
and never write down a model. **This is the precise gap we fill.**

### Non-negotiable revisions to our manuscript

1. **Cite Lee et al. 2025 (ECSS, DOI 10.1016/j.ecss.2025.109235)** —
   *the formally published version, not the SSRN preprint* — in
   Section 1.3 (Related Work) and again in Discussion (§ 5).
2. **Move "first quantification" language out of the Abstract**.
   Replace with: *"the first analytical model that predicts
   sampling-induced waterline-DEM bias a priori from local tide phase
   and amplitude, complementing the recent empirical optimization of
   the multi-sensor waterline workflow by Lee et al. (2025)."*
3. **Add a paragraph** (Discussion subsection 5.X) explaining that our
   `β·A·⟨cosθ⟩` model provides the missing theoretical explanation
   for the empirical 5-month optimum of Lee et al. (2025), and use
   their published ECSS Section 4.1 quote as direct evidence that
   the bipolar low-vs-high tide asymmetry is operationally recognised
   but not yet analytically modelled.
4. **Add the priority-protection sentence** in Section 1.3:
   *"Park & Choi et al. (2022) quantified a temporally varying
   sampling-phase bias in altimetry data near Incheon; here we
   complement that altimetry-domain finding with the optical-domain
   sampling bias relevant to waterline-DEM construction."*
5. **Add the geographic-adjacency disclaimer** in Section 2.1
   (Study sites): *"Of our five sites, Garorim Bay is the closest
   geographic neighbour (~30 km north) to the Taean Peninsula sites
   recently DEM-mapped by Lee et al. (2025); our analysis does not
   duplicate their UAV-validated DEM but complements it by
   characterising the sampling-phase geometry of the same macrotidal
   regime, and extends the analysis to a south-coast amphidromic
   site (Suncheon Bay) that lies outside their study region."*

If we do these five things, the paper is positioned as the
**theoretical companion** to the KIOST empirical line of research —
which is exactly the framing reviewers reward. Without them, the
paper is at high risk of being asked to explain how it differs
from a 2025-Mar Open-Access ECSS paper from a Korean group that
overlaps our most prominent demonstration site.
