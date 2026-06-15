#!/usr/bin/env python3
"""Build a Word .docx styled with the official MDPI *Remote Sensing* template.

Plain ``build_docx.py mdpi`` produces correct content but with pandoc's generic
Word styles (Title, Heading 2, Body Text, ...). MDPI's editorial template
(manuscript/remotesensing-template.dot) instead expects its own named styles
(MDPI_1.2_title, MDPI_2.1_heading1, MDPI_3.1_text, ...).

This script bridges the two:
  1. Reuse build_docx.preprocess() to turn the raw-LaTeX tables/figures/equations
     in draft_mdpi.md into docx-friendly markdown.
  2. Run pandoc with --reference-doc=<the MDPI template>, so the output inherits
     the template's styles.xml, headers/footers, page geometry and line numbering.
  3. Post-process word/document.xml to remap each pandoc paragraph style onto the
     corresponding MDPI named style, and prepend the obligatory "Article" type line.

Output: manuscript/draft_mdpi_styled.docx

Limitations (need a final pass in Word): the running-head front-matter blocks the
template renders in its sidebar (Citation / Copyright / Academic Editor) and the
exact affiliation footnote layout are editorial-filled; this script maps the
body, headings, abstract, keywords and references to MDPI styles but does not
synthesise that sidebar.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MS = ROOT / "manuscript"
sys.path.insert(0, str(ROOT / "scripts"))
from build_docx import preprocess  # noqa: E402

TEMPLATE = MS / "remotesensing-template.dot"
SRC = MS / "draft_mdpi.md"
OUT = MS / "draft_mdpi_styled.docx"

# pandoc paragraph style  ->  MDPI template style id
STYLE_MAP = {
    "Title": "MDPI12title",
    "Author": "MDPI13authornames",
    "Date": "MDPI14history",
    "AbstractTitle": "MDPI17abstract",
    "Abstract": "MDPI17abstract",
    "Heading2": "MDPI21heading1",   # our top sections are markdown '##'
    "Heading3": "MDPI22heading2",   # subsections are '###'
    "Heading4": "MDPI23heading3",
    "BodyText": "MDPI31text",
    "FirstParagraph": "MDPI32textnoindent",
    "Compact": "MDPI31text",
    "Bibliography": "MDPI81references",
}

ARTICLE_PARA = (
    '<w:p><w:pPr><w:pStyle w:val="MDPI11articletype"/></w:pPr>'
    '<w:r><w:t>Article</w:t></w:r></w:p>'
)


def main() -> None:
    if not TEMPLATE.exists():
        sys.exit(f"template not found: {TEMPLATE}")

    md = preprocess(SRC.read_text())
    tmp_md = MS / ".draft_mdpi_styled.md"
    tmp_md.write_text(md)

    # pandoc needs a .docx reference; the template is .dot (still OOXML).
    ref = MS / ".mdpi_ref.docx"
    shutil.copyfile(TEMPLATE, ref)

    cmd = [
        "pandoc", tmp_md.name,
        "--from=markdown-implicit_figures+raw_tex+tex_math_dollars+pipe_tables+yaml_metadata_block",
        "--to=docx", f"--reference-doc={ref.name}", "-o", OUT.name,
    ]
    if "[@" in md and (MS / "references.bib").exists():
        cmd += ["--citeproc", "--bibliography=references.bib"]
        if (MS / "mdpi.csl").exists():
            cmd += ["--csl=mdpi.csl"]
    subprocess.run(cmd, cwd=MS, check=True)
    tmp_md.unlink()
    ref.unlink()

    # --- post-process: remap styles + prepend the Article type line ----------
    with zipfile.ZipFile(OUT) as zin:
        names = zin.namelist()
        blobs = {n: zin.read(n) for n in names}
    doc = blobs["word/document.xml"].decode("utf-8")

    def remap(m: re.Match) -> str:
        sid = m.group(1)
        return f'w:pStyle w:val="{STYLE_MAP.get(sid, sid)}"'

    doc = re.sub(r'w:pStyle w:val="([^"]+)"', remap, doc)

    # Front-matter paragraphs that pandoc can't distinguish from body text, but
    # which carry a unique signature, get their dedicated MDPI style.
    def para_text(p: str) -> str:
        return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.DOTALL)).strip()

    def fix_para(m: re.Match) -> str:
        p = m.group(0)
        t = para_text(p)
        target = None
        if t.startswith("Keywords"):
            target = "MDPI18keywords"
        elif ("Correspondence:" in t or t.startswith("ORCID")
              or "Republic of Korea; tysong@haebomdata.com" in t):
            target = "MDPI16affiliation"
        if target and "w:pStyle" in p:
            p = re.sub(r'w:pStyle w:val="[^"]+"',
                       f'w:pStyle w:val="{target}"', p, count=1)
        return p

    doc = re.sub(r"<w:p\b.*?</w:p>", fix_para, doc, flags=re.DOTALL)
    # Insert the Article type as the first body paragraph.
    doc = re.sub(r"(<w:body>)", r"\1" + ARTICLE_PARA, doc, count=1)
    blobs["word/document.xml"] = doc.encode("utf-8")

    tmp = OUT.with_suffix(".docx.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, blobs[n])
    tmp.replace(OUT)
    print(f"  -> {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
