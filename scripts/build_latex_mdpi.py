#!/usr/bin/env python3
"""Build the official MDPI LaTeX-template submission from draft_mdpi.md.

Unlike build_mdpi.sh (a generic ``article``-class PDF via tectonic), this
script targets MDPI's *Remote Sensing* LaTeX template (Definitions/mdpi.cls):
front matter goes into the MDPI macros (\\Title, \\Author, \\address,
\\corres, \\abstract, \\keyword) and the body is converted from the markdown
source with pandoc (--natbib so [@key] -> \\cite{key}; raw LaTeX tables,
figures and equations pass through). Output: manuscript/latex_mdpi/remotesensing.{tex,pdf}.

The assembled folder (Definitions/, references.bib, figures/, remotesensing.tex,
remotesensing.pdf) is exactly what MDPI SuSy expects for a LaTeX submission:
the compiled PDF plus the LaTeX source tree.

Usage:  python scripts/build_latex_mdpi.py [--no-compile]
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MS = ROOT / "manuscript"
SRC = MS / "draft_mdpi.md"
OUT = MS / "latex_mdpi"

# Back-matter headings that MDPI renders as special unnumbered sections.
UNNUMBERED = {
    "Highlights", "Supplementary Materials", "Author Contributions", "Funding",
    "Institutional Review Board Statement", "Informed Consent Statement",
    "Data Availability Statement", "Acknowledgments", "Acknowledgements",
    "Conflicts of Interest",
}


def ensure_eps_pdfs() -> None:
    """Make MDPI's EPS logos usable under tectonic (XeTeX/xdvipdfmx).

    Tectonic cannot read EPS and has no shell-escape, so epstopdf's on-the-fly
    conversion (and even its pre-converted-file substitution) does not fire.
    Instead we (a) rasterise/convert every EPS logo to a plain-basename PDF with
    Ghostscript and (b) strip the explicit ``.eps`` extension from the class's
    ``\\includegraphics{Definitions/...eps}`` calls in our *vendored* copy of
    mdpi.cls, so graphicx resolves ``logo-mdpi`` to ``logo-mdpi.pdf`` (XeTeX
    searches .pdf before .eps). This only affects local PDF generation; MDPI
    compiles the accepted paper from the original class at production.
    """
    defs = OUT / "Definitions"
    for eps in sorted(defs.glob("*.eps")):
        pdf = eps.with_suffix(".pdf")
        if not pdf.exists():
            subprocess.run(
                ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dEPSCrop",
                 "-sDEVICE=pdfwrite", f"-sOutputFile={pdf}", str(eps)],
                check=True,
            )
    cls = defs / "mdpi.cls"
    txt = cls.read_text()
    patched = re.sub(r"(\\includegraphics\b[^{}]*\{Definitions/[^{}]*?)\.eps\}",
                     r"\1}", txt)
    if patched != txt:
        cls.write_text(patched)


def pandoc(text: str, extra: list[str]) -> str:
    """Convert a markdown fragment to a LaTeX fragment."""
    cmd = [
        "pandoc", "-f",
        "markdown+raw_tex+tex_math_dollars+pipe_tables+raw_attribute",
        "-t", "latex", *extra,
    ]
    r = subprocess.run(cmd, input=text, capture_output=True, text=True, cwd=MS)
    if r.returncode != 0:
        sys.exit(f"pandoc failed:\n{r.stderr}")
    return r.stdout.strip()


def yaml_block(md: str, key: str) -> str:
    """Pull a ``key: |`` literal block out of the YAML front matter."""
    m = re.search(rf"^{key}: \|\n((?:  .*\n?)+)", md, flags=re.MULTILINE)
    if not m:
        sys.exit(f"YAML key '{key}' not found")
    return "\n".join(line[2:] for line in m.group(1).splitlines()).strip()


def strip_heading_number(line: str) -> str:
    """'## 2.1 Sites' -> '## Sites'; mark back-matter headings unnumbered."""
    m = re.match(r"^(#+)\s+(?:\d+(?:\.\d+)*\.?\s+)?(.*)$", line)
    if not m:
        return line
    hashes, title = m.group(1), m.group(2).strip()
    if title in UNNUMBERED:
        return f"{hashes} {title} {{-}}"
    return f"{hashes} {title}"


def main() -> None:
    md = SRC.read_text()
    body_start = md.index("## Highlights")
    body_end = md.index("## References")
    body = md[body_start:body_end]

    # Drop the keywords line (goes into the \keyword macro) and the cosmetic
    # thematic breaks ('---') that separated sections in the markdown PDF.
    kept = []
    for line in body.splitlines():
        if line.startswith("**Keywords:**"):
            continue
        if line.strip() == "---":
            continue
        if line.lstrip().startswith("#"):
            kept.append(strip_heading_number(line))
        else:
            kept.append(line)
    body_md = "\n".join(kept)

    title = " ".join(yaml_block(md, "title").split())
    abstract = yaml_block(md, "abstract")
    kw = re.search(r"^\*\*Keywords:\*\*\s*(.+)$", md, flags=re.MULTILINE).group(1).strip()

    # mdpi.cls loads inputenc[utf8] for pdfLaTeX; under tectonic (XeTeX) a few
    # stray non-ASCII glyphs that pandoc leaves in text mode trigger UTF-8
    # warnings/U+FFFD. Map the handful that occur to engine-agnostic LaTeX.
    UNI = {
        "−": r"\ensuremath{-}",      # minus sign
        "×": r"\ensuremath{\times}", # multiplication
        "≈": r"\ensuremath{\approx}",
        "≤": r"\ensuremath{\le}",
        "≥": r"\ensuremath{\ge}",
        "°": r"\ensuremath{^\circ}", # degree
        "—": "---",                  # em dash
        "–": "--",                   # en dash
    }

    def deunicode(s: str) -> str:
        for k, v in UNI.items():
            s = s.replace(k, v)
        return s

    title_tex = deunicode(pandoc(title, []))
    abstract_tex = deunicode(pandoc(abstract, []))
    body_tex = deunicode(pandoc(body_md, ["--natbib"]))

    preamble = rf"""%% MDPI Remote Sensing LaTeX submission -- generated by scripts/build_latex_mdpi.py
%% Do not edit by hand; edit manuscript/draft_mdpi.md and rebuild.
%% NB: the 'pdftex' class option from MDPI's template is intentionally omitted
%% so xcolor/graphicx auto-detect the driver -- we compile with tectonic (XeTeX),
%% under which the pdftex driver's \pdfcolorstack is undefined. MDPI compiles
%% the accepted paper with pdfLaTeX at production; the source remains valid there.
\documentclass[remotesensing,article,submit,moreauthors]{{Definitions/mdpi}}
\usepackage{{amssymb}} % \lesssim, \gtrsim etc. (mdpi.cls loads amsmath only)

\firstpage{{1}}
\makeatletter
\setcounter{{page}}{{\@firstpage}}
\makeatother
\pubvolume{{1}}
\issuenum{{1}}
\articlenumber{{0}}
\pubyear{{2026}}
\copyrightyear{{2026}}
\history{{Received: date; Accepted: date; Published: date}}

% pandoc emits these helpers in its standalone template; we paste fragments,
% so define them here (no-ops / minimal) to keep the body self-contained.
\providecommand{{\tightlist}}{{\setlength{{\itemsep}}{{0pt}}\setlength{{\parskip}}{{0pt}}}}
\providecommand{{\passthrough}}[1]{{#1}}

\newcommand{{\orcidauthorA}}{{0000-0002-4111-8959}}
\newcommand{{\orcidauthorB}}{{0000-0002-2534-3777}}

\Title{{{title_tex}}}

\Author{{Taeyoon Song $^{{1,}}$*\orcidA{{}} and Mirinae Kim $^{{1}}$\orcidB{{}}}}
\AuthorNames{{Taeyoon Song and Mirinae Kim}}

\address{{%
$^{{1}}$ \quad Haebom Data Inc., \#904, Gasan A1 Tower, 205-27 Gasan 1-ro, Geumcheon-gu, Seoul 08503, Republic of Korea; tysong@haebomdata.com (T.S.); mirinae@haebomdata.com (M.K.)}}

\corres{{Correspondence: tysong@haebomdata.com}}

\abstract{{{abstract_tex}}}

\keyword{{{kw}}}

\begin{{document}}

{body_tex}

\vspace{{6pt}}

\reftitle{{References}}
\externalbibliography{{yes}}
\bibliography{{references}}

\end{{document}}
"""

    OUT.mkdir(exist_ok=True)
    tex = OUT / "remotesensing.tex"
    tex.write_text(preamble)
    print(f"  -> {tex.relative_to(ROOT)}  ({len(preamble.splitlines())} lines)")

    # Sync figures/: keep exactly the images the manuscript body includes
    # (the file-name numbering does not match figure numbers, and figS*/unused
    # plots belong to the supplementary, not this main-text submission).
    used = set(re.findall(r"figures/([A-Za-z0-9_]+\.png)", body_tex))
    figdir = OUT / "figures"
    figdir.mkdir(exist_ok=True)
    for png in figdir.glob("*.png"):
        if png.name not in used:
            png.unlink()
    for name in sorted(used):
        src_png = MS / "figures" / name
        dst_png = figdir / name
        if src_png.exists():
            dst_png.write_bytes(src_png.read_bytes())
    print(f"  figures/: {len(used)} images (body-referenced only)")

    if "--no-compile" in sys.argv:
        return
    ensure_eps_pdfs()
    print("  compiling with tectonic (this fetches LaTeX packages on first run)...")
    r = subprocess.run(
        ["tectonic", "--keep-logs", "remotesensing.tex"],
        cwd=OUT, capture_output=True, text=True,
    )
    sys.stderr.write(r.stderr[-4000:])
    if r.returncode != 0:
        sys.exit("\n!! tectonic compile FAILED (see log above)")
    pdf = OUT / "remotesensing.pdf"
    print(f"  -> {pdf.relative_to(ROOT)}  ({pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
