# SuSy Submission Guide — *Remote Sensing* (MDPI)

Step-by-step guide for submitting the first manuscript to MDPI *Remote Sensing*
via SuSy (`susy.mdpi.com`), with the exact values for this submission.

> Target: MDPI *Remote Sensing* (SCIE Q1, IF 4.1). Regular submission (no Special
> Issue). APC CHF 2700 on acceptance.

## 0. Have these ready before starting
- `draft_mdpi.docx` — **main manuscript** (MDPI requires an editable Word/LaTeX file as the main)
- `cover_letter_mdpi.pdf`
- `supplementary.docx`
- Suggested-reviewer **e-mails** (5; obtain before step 6)
- Both authors' ORCID + institutional e-mails (done)

## 1. Account & login
- Go to `susy.mdpi.com`, create/log in. Use the **corresponding author (Taeyoon Song)** account.
- Link **ORCID** to the profile (`0000-0002-4111-8959`). Fill affiliation/country.

## 2. New submission → journal & section
- "Submit Manuscript" → Journal: **Remote Sensing**
- **Section** (dropdown — pick the closest; editor may reassign):
  - *Ocean Remote Sensing* (tides/coastal), or
  - *Environmental Remote Sensing*, or
  - *Remote Sensing in Geology, Geomorphology and Hydrology* (DEM/topography)
- **Special Issue**: No / Not applicable
- **Article Type**: **Article**

## 3. Manuscript metadata
- **Title**: `Predicting Tidal-Sampling Bias of Sun-Synchronous Satellites from Overpass Phase: Theory and Validation on Macrotidal Coasts`
- **Abstract**: copy the ~200-word abstract from `draft_mdpi.md` (the YAML `abstract:` block)
- **Keywords**: `tidal flat; intertidal DEM; waterline method; tidal aliasing; sun-synchronous orbit; amphidromic system`

## 4. Authors (order and roles matter)
| # | Name | Affiliation | E-mail | ORCID | Corresponding |
|---|------|-------------|--------|-------|:---:|
| 1 | Taeyoon Song | Haebom Data Inc. (1) + Inha University (2) | tysong@haebomdata.com | 0000-0002-4111-8959 | ✅ |
| 2 | Mirinae Kim | Haebom Data Inc. (1) | mirinae@haebomdata.com | 0000-0002-2534-3777 | |

- **Affiliation 1**: `Haebom Data Inc., #904, Gasan A1 Tower, 205-27 Gasan 1-ro, Geumcheon-gu, Seoul 08503, Republic of Korea`
- **Affiliation 2** (T.S., Ph.D. candidate): `Department of Ocean Sciences, Inha University, Incheon 22212, Republic of Korea`
- Mark **Taeyoon Song** as Corresponding (affiliations 1 and 2).

## 5. File upload (assign each to its slot)

MDPI accepts **either** a Word **or** a LaTeX main manuscript — pick one route.

### Route A — Word (.docx)
| SuSy file type | File |
|----------------|------|
| **Manuscript** (main) | `draft_mdpi_styled.docx` — official MDPI template styles (`scripts/build_docx_mdpi_styled.py`); or `draft_mdpi.docx` (generic styles) |
| **Cover Letter** | `cover_letter_mdpi.pdf` |
| **Supplementary** | `supplementary.docx` |
| (if figures requested separately) | high-res PNGs in `manuscript/figures/` |

> `draft_mdpi_styled.docx` is built from `remotesensing-template.dot` as the
> pandoc reference doc, then each paragraph style is remapped to the MDPI named
> styles (MDPI_1.2_title, MDPI_2.1_heading1, MDPI_3.1_text, MDPI_8.1_references,
> …); it inherits the template's styles, headers/footers, page geometry and line
> numbering. **Final Word touch-up still needed**: the template's running-head
> sidebar (Citation / Copyright / Academic Editor) is editorial-filled, and the
> affiliation footnote/superscript layout should be eyeballed. The plain
> `draft_mdpi.docx` (generic styles, content-identical) remains as a fallback.

### Route B — LaTeX (official MDPI template, `Definitions/mdpi.cls`)
Built by `scripts/build_latex_mdpi.py` from `draft_mdpi.md` into
`manuscript/latex_mdpi/` and zipped as `remotesensing_latex_submission.zip`.
| SuSy file type | File |
|----------------|------|
| **Manuscript** (main) | `latex_mdpi/remotesensing.pdf` + the LaTeX source |
| LaTeX source (one ZIP) | `remotesensing_latex_submission.zip` (`.tex`, `Definitions/`, `references.bib`, `figures/`) |
| **Cover Letter** | `cover_letter_mdpi.pdf` |
| **Supplementary** | `supplementary.docx` |

> `\documentclass[remotesensing,article,submit,moreauthors]{Definitions/mdpi}`;
> numeric `\cite` via BibTeX/`mdpi.bst`; line numbers on (submit mode). The
> template files are the official **`mdpi.cls` dated 20/03/2024** (compiles
> cleanly; MDPI re-typesets at production). To refresh to a still-newer class,
> drop it into `Definitions/` from <https://www.mdpi.com/authors/latex> and
> rerun `python scripts/build_latex_mdpi.py`. Local build uses tectonic
> (XeTeX): the `pdftex` class option is omitted and EPS logos are
> auto-converted to PDF — both transparent to MDPI's pdfLaTeX.

## 6. Suggested / opposed reviewers
- **Suggested** (name, affiliation, e-mail):
  - Robbi Bishop-Taylor — Geoscience Australia
  - Stephen Sagar — Geoscience Australia
  - Nicholas J. Murray — James Cook University, Australia
  - Kuo-Hsin Tseng — National Central University, Taiwan
  - Nan Xu — Hohai University, China
- **Opposed**: none
- (These mirror the list in `cover_letter_mdpi.pdf`. All international, no prior
  collaboration. Ryu J.-H. deliberately excluded — the paper differentiates from
  that group.)

## 7. Declarations & checkboxes (must match the manuscript)
| Item | Answer |
|------|--------|
| Originality / not under consideration elsewhere | Yes |
| **Funding** | No external funding |
| **Conflicts of Interest** | None |
| **Generative AI use** | **Yes — used and disclosed in the manuscript** (Declaration section included) |
| **Data Availability** | Public data + Zenodo on acceptance (stated in manuscript) |
| Institutional Review Board / Informed Consent | Not applicable |
| All authors approved | Yes |

## 8. Review the auto-generated PDF → Submit
- SuSy merges the uploads into a single **review PDF** — **open and check it**
  (figures, tables, equations, references render correctly).
- If OK, click **Submit**. Status moves Submitted → With Editor.
- Expect a confirmation e-mail, then pre-check (a few days), then review.

## After submission → first decision
- **Pre-check** (Assistant + Academic Editor): a few days to ~1 week (format, scope, English).
- **Review**: usually 2–3 reviewers; median first decision ~24 days.
- On decision, prepare a **point-by-point response letter** quickly — fast,
  thorough revisions are the main lever on total time to acceptance.

---

### Package status (as built)
| Component | File | Status |
|-----------|------|--------|
| Manuscript | `draft_mdpi.pdf` / `draft_mdpi.docx` | ✅ authors, address, e-mails, ORCID, numeric citations, Funding, KOEM ack, AI declaration |
| Cover letter | `cover_letter_mdpi.pdf` | ✅ |
| References | citeproc, 32 refs | ✅ |
| Supplementary | `supplementary.pdf` / `.docx` | ✅ |

**Outstanding before submit:** suggested-reviewer e-mails (entered live in SuSy).

### Build commands
```bash
python scripts/convert_to_mdpi.py        # regenerate draft_mdpi.md from draft.md
bash   scripts/build_mdpi.sh draft        # -> draft_mdpi.pdf
bash   scripts/build_mdpi.sh cover         # -> cover_letter_mdpi.pdf
python scripts/build_docx.py mdpi          # -> draft_mdpi.docx
```
