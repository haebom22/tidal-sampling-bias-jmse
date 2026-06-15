#!/usr/bin/env python3
"""Convert the RSE-formatted manuscript (draft.md) into an MDPI Remote Sensing
draft (draft_mdpi.md).

What it does (content/structure level only; the LaTeX template swap to mdpi.cls
lives in the build script):
  1. Inline author-year citations -> pandoc [@key] so a numeric CSL renders [n].
  2. Compress the abstract to a single ~200-word paragraph (MDPI style).
  3. Drop the Elsevier "Highlights" block.
  4. Rename "Material and methods" -> "Materials and Methods".
  5. Re-order the back matter into MDPI's required sections
     (Supplementary Materials, Author Contributions, Funding, IRB,
      Informed Consent, Data Availability Statement, Acknowledgments,
      Conflicts of Interest).
  6. Replace the hand-built reference list with a citeproc {#refs} target.

Run:  PYTHONPATH=. python scripts/convert_to_mdpi.py
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path("manuscript/draft.md")
DST = Path("manuscript/draft_mdpi.md")

# ---------------------------------------------------------------------------
# 1. Citation replacements.  Ordered longest/most-specific first so that a
#    short string is never a substring of a not-yet-processed longer one.
# ---------------------------------------------------------------------------
CITES: list[tuple[str, str]] = [
    # --- the big "Contribution" multi-cite (must run before its substrings) ---
    ("(Bishop-Taylor et al., 2019a, b; Sagar et al., 2017; Murray et al., 2019; "
     "Salameh et al., 2019; Ryu et al., 2002, 2008; Lee and Ryu, 2017; "
     "Yun et al., 2022; Lee, J. et al., 2025)",
     "[@bishop_taylor_2019a; @bishop_taylor_2019b; @sagar_2017_australia; "
     "@murray_2019_global; @salameh_2019_review; @ryu_2002_gomso; "
     "@ryu_2008_intertidal; @lee_2017_tandemx; @yun_2022_ganghwa_tandemx; "
     "@lee_2025_multisensor]"),
    # --- other multi-key parentheticals ---
    ("(Mason et al., 1995; Heygster et al., 2010; Murray et al., 2012)",
     "[@mason_1995; @heygster_2010; @murray_2012]"),
    ("(Tseng et al., 2017; Khan et al., 2019; Salameh et al., 2019; Wang et al., 2020)",
     "[@tseng_2017; @khan_2019; @salameh_2019_review; @wang_2020_ningbo]"),
    ("(Sagar et al., 2017; Bishop-Taylor et al., 2019a)",
     "[@sagar_2017_australia; @bishop_taylor_2019a]"),
    ("(Bishop-Taylor et al., 2019a; Bishop-Taylor et al., 2025)",
     "[@bishop_taylor_2019a; @bishop_taylor_2025_eotides]"),
    ("(Zhang et al., 2022; Xin et al., 2025)",
     "[@zhang_2022_sar_waterline; @xin_2025_icesat2_combine]"),
    ("(Xu et al., 2022; Xin et al., 2025)",
     "[@xu_2022_icesat2_tidalflat; @xin_2025_icesat2_combine]"),
    ("(Murray et al., 2019; Worm et al., 2006)",
     "[@murray_2019_global; @worm_2006]"),
    ("(Koh and Khim, 2014; Murray et al., 2014)",
     "[@koh_khim_2014_korean_tidal_flat; @murray_2014_loss]"),
    ("(Lee and Ryu, 2017; Yun et al., 2022)",
     "[@lee_2017_tandemx; @yun_2022_ganghwa_tandemx]"),
    ("(Ryu et al., 2002, 2008)",
     "[@ryu_2002_gomso; @ryu_2008_intertidal]"),
    ("(Carrère et al., 2022; Lyard et al., 2021)",
     "[@carrere_2022_fes2022; @lyard_2021_fes2014]"),
    # --- parentheticals embedded in running parenthetical text ---
    ("(see Section 1.4; Choi et al., 2014)", "(see Section 1.4) [@choi_2014_yellowsea]"),
    ("(e.g., UTide; Codiga, 2011)", "(e.g., UTide; [@codiga_2011_utide])"),
    ("(UTide; Codiga, 2011)", "(UTide; [@codiga_2011_utide])"),
    ("(Lyard et al., 2021; AVISO", "([@lyard_2021_fes2014]; AVISO"),
    ("; Drusch et al., 2012)", "; [@drusch_2012_s2])"),
    ("(cf. Lee, J. et al., 2025)", "(cf. [@lee_2025_multisensor])"),
    ("TPXO (Egbert and Erofeeva, 2002)", "TPXO [@egbert_erofeeva_2002]"),
    # --- narrative (author-in-text) citations ---
    ("characterised by Bishop-Taylor et al. (2019b)",
     "characterised by Bishop-Taylor et al. [@bishop_taylor_2019b]"),
    ("Bishop-Taylor et al. (2019a) documented",
     "Bishop-Taylor et al. [@bishop_taylor_2019a] documented"),
    ("Sent et al. (2025) documented",
     "Sent et al. [@sent_2025_tagus_aliasing] documented"),
    ("reported by Lee, K. et al. (2022), who showed",
     "reported by Lee, K. et al. [@lee_2022_korean_altimetry], who showed"),
    ("previously documented near Incheon by Lee, K. et al. (2022)",
     "previously documented near Incheon by Lee, K. et al. [@lee_2022_korean_altimetry]"),
    ("Lee, K. et al. (2022) previously demonstrated",
     "Lee, K. et al. [@lee_2022_korean_altimetry] previously demonstrated"),
    ("reported independently by Lee, J. et al. (2025)",
     "reported independently by Lee, J. et al. [@lee_2025_multisensor]"),
    ("observed empirically by Lee, J. et al. (2025)",
     "observed empirically by Lee, J. et al. [@lee_2025_multisensor]"),
    # --- single-key parentheticals (run last; shortest) ---
    ("(Bishop-Taylor et al., 2025)", "[@bishop_taylor_2025_eotides]"),
    ("(Lee, J. et al., 2025)", "[@lee_2025_multisensor]"),
    ("(Gorelick et al., 2017)", "[@gorelick_2017_gee]"),
    ("based on Koh and Khim, 2014)", "based on [@koh_khim_2014_korean_tidal_flat])"),
    ("(Choi et al., 2014)", "[@choi_2014_yellowsea]"),
    ("(Xu et al., 2022)", "[@xu_2022_icesat2_tidalflat]"),
    ("(Codiga, 2011)", "[@codiga_2011_utide]"),
    ("(Heygster et al., 2010)", "[@heygster_2010]"),  # §4.8 standalone
]

NEW_ABSTRACT = (
    "abstract: |\n"
    "  The waterline method for mapping intertidal digital elevation models (DEMs) "
    "from optical satellite imagery assumes that scenes sample the local tidal cycle "
    "without systematic bias. We derive a closed-form model in which the "
    "satellite-sampled tide bias equals $\\beta \\cdot A \\cdot \\langle\\cos\\theta\\rangle$, "
    "where $A$ is the local tidal amplitude and $\\langle\\cos\\theta\\rangle$ the mean cosine "
    "of the overpass tide phase, and validate it over the macrotidal Korean coast "
    "using 5,082 cloud-screened Landsat-8/9 and Sentinel-2 acquisitions (2020–2024) at five "
    "tidal flats against hourly tide-gauge observations. Sun-synchronous satellites sample "
    "only 70–80 % of the astronomical tidal "
    "envelope, systematically missing one extremity. The resulting mean bias has opposite signs "
    "on the macrotidal west coast (low-tide bias) and the southern amphidromic coast "
    "(high-tide bias). A single slope $\\beta = 1.78$ reproduces the bias across five sites and "
    "three sensors ($R^{2} = 0.98$) and is "
    "recovered from the global FES2022b tide model alone ($R^{2} = 0.983$), enabling correction "
    "without local gauge data. The bias yields an elevation-domain RMSE of 0.36–1.09 m "
    "and unsampled intertidal bands up to 2.5 km wide; because all optical missions "
    "cluster near 10:30 local solar time, only phase-orthogonal radar — not higher "
    "optical revisit frequency — can close the gap.\n"
    "---\n"
)

# MDPI shows the keyword list as a visible line after the abstract.  (Kept out
# of the YAML to avoid pandoc's hyperxmp/\xmpquote pdfkeywords path, which is
# undefined under the tectonic toolchain.)
KEYWORDS_LINE = (
    "**Keywords:** tidal flat; intertidal DEM; waterline method; "
    "tidal aliasing; sun-synchronous orbit; amphidromic system\n\n"
)

# Author affiliations + corresponding-author line (MDPI shows this directly
# under the author list).  Rendered at the top of the body because the
# article-class abstract comes from the YAML block above it.
# TODO before submission: confirm M.K.'s e-mail and the full company address.
AFFILIATION_BLOCK = (
    "^1^ Haebom Data Inc., #904, Gasan A1 Tower, 205-27 Gasan 1-ro, "
    "Geumcheon-gu, Seoul 08503, Republic of Korea; "
    "tysong@haebomdata.com (T.S.); mirinae@haebomdata.com (M.K.)  \n"
    "ORCID: T.S. 0000-0002-4111-8959; M.K. 0000-0002-2534-3777  \n"
    "\\* Correspondence: tysong@haebomdata.com (T.S.)\n\n"
)

NEW_BACKMATTER = """## Supplementary Materials

The following supporting information can be downloaded at the journal website:
Figures S1–S7 (sampling-distribution CDFs, overpass-hour histograms,
coefficient-stability summaries, per-elevation error curves, and cross-section
schematics) and Tables S1–S2 (per-partition regression coefficients and the
amplitude/reference sensitivity tables).

## Author Contributions

Conceptualization, T.S.; methodology, T.S.; software, T.S.; validation, T.S. and
M.K.; formal analysis, T.S.; investigation, T.S.; data curation, T.S. and M.K.;
writing—original draft preparation, T.S.; writing—review and editing, T.S. and
M.K.; visualization, T.S.; supervision, T.S.; project administration, T.S. All
authors have read and agreed to the published version of the manuscript.
<!-- T.S. = Taeyoon Song; M.K. = Mirinae Kim. Adjust the role split to reflect
     each author's actual contribution before submission. -->

## Funding

This research received no external funding.
<!-- Or: "This research was funded by <FUNDER>, grant number <NUMBER>." -->

## Institutional Review Board Statement

Not applicable.

## Informed Consent Statement

Not applicable.

## Data Availability Statement

All raw KHOA tide-gauge data are publicly available through the Korea Open Data
Portal (`apis.data.go.kr/1192136`). Google Earth Engine scene metadata is
reproducible from the public collections LANDSAT/LC08/C02/T1_L2,
LANDSAT/LC09/C02/T1_L2, and COPERNICUS/S2_HARMONIZED. The full analytical
pipeline, derived parquet/CSV tables, and figure-generation scripts will be
released on a Zenodo-archived GitHub repository upon acceptance (DOI to be
assigned). The intermediate `multisite_5y_*.parquet` and `dem_error_*.csv`
derived products are < 50 MB total.

## Acknowledgments

The KHOA tide-gauge data are provided under the Korean Open Government License.
Earth Engine access was provided by Google for academic use. We thank the
developers of pyTMD, Cartopy, UTide, and eo-tides for open-source tooling.
Haebom Data Inc. has carried out the nationwide Blue Carbon Monitoring service
commissioned by the Korea Marine Environment Management Corporation (KOEM); the
present study was conducted independently of that contract.

## Declaration of Generative AI and AI-Assisted Technologies in the Writing Process

During the preparation of this manuscript, the authors used Claude (Anthropic) to
assist with formatting the manuscript to the journal template, condensing the
abstract, and language editing. After using this tool, the authors reviewed and
edited the content as needed and take full responsibility for the content of the
publication.

## Conflicts of Interest

The authors declare no conflicts of interest.

## References

::: {#refs}
:::
"""


def main() -> None:
    text = SRC.read_text(encoding="utf-8")

    # 2. Abstract -> compressed single paragraph + keywords (YAML).
    text, n = re.subn(r"abstract: \|\n.*?\n---\n", lambda _m: NEW_ABSTRACT, text,
                      count=1, flags=re.DOTALL)
    assert n == 1, "abstract block not matched"

    # Update the YAML date / target-journal line.
    text = text.replace(
        'date: "First draft v0.1 — 2026-05-21 · Target journal: '
        '*Remote Sensing of Environment* · ~6,900 words (incl. References)"',
        'date: "Manuscript for *Remote Sensing* (MDPI)"')

    # 3. KEEP the Highlights block — MDPI Remote Sensing now REQUIRES a
    #    Highlights section (author-guidelines update). Put the affiliation
    #    block immediately above it.
    assert "## Highlights" in text, "highlights block missing from source"
    text = text.replace("## Highlights", AFFILIATION_BLOCK + "## Highlights", 1)

    # 1. Citations.
    for old, new in CITES:
        assert old in text, f"citation source not found: {old[:50]!r}"
        text = text.replace(old, new)

    # Visible keywords just before the Introduction; drop the Highlights/Intro
    # divider so keywords sit cleanly between Highlights and Section 1.
    text = text.replace("---\n\n## 1. Introduction",
                        KEYWORDS_LINE + "## 1. Introduction", 1)

    # 4. Section rename.
    text = text.replace("## 3. Material and methods",
                        "## 3. Materials and Methods")

    # 5/6. Replace everything from the back matter onward with MDPI sections.
    marker = "## Data and code availability"
    idx = text.index(marker)
    text = text[:idx] + NEW_BACKMATTER

    DST.write_text(text, encoding="utf-8")
    print(f"wrote {DST} ({len(text.split())} words)")

    # sanity: flag any author-year citation that slipped through (ignore the
    # raw-LaTeX comparison tables, where author-year labels are intentional).
    leftover = re.findall(r"[A-Z][a-z]+ et al\.,? \(?\d{4}", text)
    if leftover:
        print("WARNING leftover author-year tokens:", sorted(set(leftover)))


if __name__ == "__main__":
    main()
