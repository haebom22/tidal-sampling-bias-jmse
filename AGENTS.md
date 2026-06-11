# Project rules for AI agents (`tidalflat`)

These are mandatory project-level rules. Honour them before reaching for any
generic skill or default workflow.

## 1. Manuscript PDFs are LaTeX-only

The files

- `manuscript/draft.pdf`
- `manuscript/cover_letter.pdf`

are submission artefacts for *Remote Sensing of Environment* (RSE). RSE
requires **continuous line numbering, double spacing, and 2.5 cm margins** in
the manuscript PDF. These are encoded as LaTeX directives in the YAML front
matter of `manuscript/draft.md` (`\usepackage{lineno} \linenumbers`,
`linestretch: 2.0`, `geometry: margin=2.5cm`). They are honoured only by a
real LaTeX engine.

**Rules**:

- **DO** use `bash scripts/build_manuscript_pdf.sh` (pandoc + tectonic) to
  rebuild any `manuscript/*.pdf` after editing the corresponding `*.md`.
- **DO NOT** invoke `~/.cursor/tools/md2pdf.py`, `weasyprint`, `playwright`,
  or any HTML/CSS-based renderer on `manuscript/*.md`. These silently drop
  the LaTeX header-includes; the resulting PDF will be missing line numbers
  and will fail the RSE pre-flight check.
- **DO NOT** activate the `markdown-pdf-export` skill for files under
  `manuscript/`. That skill is fine for ad-hoc reports elsewhere in the repo.
- If `pandoc` or `tectonic` is not installed, install them
  (`brew install pandoc tectonic`) rather than falling back to weasyprint.

## 2. Manuscript source of truth

`manuscript/draft.md` is the single source of truth for the paper body.
`manuscript/cover_letter.md` is the source for the cover letter. Always edit
these and then rebuild the PDF; never edit the PDF directly or treat it as
authoritative.

## 3. Reviewer-mode tasks

When the user asks for a "reviewer review" or "journal format check" of the
manuscript, validate against the target journal's *Guide for Authors* (the
target journal is stated in the YAML `date:` field — currently
*Remote Sensing of Environment*).
