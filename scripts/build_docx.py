#!/usr/bin/env python3
"""Build a Word (.docx) version of a manuscript markdown file.

The PDF pipeline (build_manuscript_pdf.sh) embeds raw-LaTeX tables and a
raw-LaTeX composite figure that pandoc's docx writer silently drops.  This
script preprocesses those LaTeX blocks into docx-friendly markdown
(native pipe tables, embedded images, Word equations) and then calls
pandoc, so the .docx contains every table, figure and equation.

Usage:
    python scripts/build_docx.py [draft|ko|supp|cover]   # default: draft
Outputs manuscript/<stem>.docx
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MS = ROOT / "manuscript"

STEMS = {
    "draft": "draft",
    "mdpi": "draft_mdpi",
    "ko": "draft_ko",
    "supp": "supplementary",
    "cover": "cover_letter",
}


def clean_cell(s: str) -> str:
    """Convert a LaTeX table cell to markdown inline text."""
    s = s.strip()
    s = s.replace(r"\&", "&").replace(r"\_", "_").replace(r"\%", "%")
    s = s.replace("--", "–")  # en dash
    # innermost emphasis first; underscore italic so it nests inside **bold**
    for _ in range(4):
        new = re.sub(r"\\mathbf\{([^{}]*)\}", r"\1", s)  # bold-math -> plain in cell
        new = re.sub(r"\\textit\{([^{}]*)\}", r"_\1_", new)
        new = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", new)
        if new == s:
            break
        s = new
    # simple numeric math cells -> plain unicode (no Word equation object)
    s = re.sub(r"\$\s*([+\-]?\d[\d.,]*)\s*\$",
               lambda m: m.group(1).replace("-", "−"), s)
    return s.strip()


def clean_caption(s: str) -> str:
    s = s.strip()
    s = s.replace(r"\&", "&").replace(r"\_", "_").replace(r"\%", "%")
    s = s.replace("--", "–")
    # flatten a doubly-nested \textit so we never emit italic-within-italic
    s = re.sub(r"\\textit\{([^{}]*)\\textit\{([^{}]*)\}([^{}]*)\}", r"_\1\2\3_", s)
    for _ in range(4):
        new = re.sub(r"\\textit\{([^{}]*)\}", r"_\1_", s)
        new = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", new)
        if new == s:
            break
        s = new
    return s.strip()


def convert_table(block: str, number: int, prefix: str = "", label: str = "Table") -> str:
    lines = block.splitlines()
    caption = ""
    for ln in lines:
        m = re.search(r"\\caption\{(.*)\}\s*$", ln.strip())
        if m:
            caption = clean_caption(m.group(1))
            break
    # rows
    body = block.split(r"\toprule", 1)[1]
    header_part, rest = body.split(r"\midrule", 1)
    rows_part = rest.split(r"\bottomrule", 1)[0]

    def parse_row(rtext: str):
        rtext = rtext.strip()
        if rtext.endswith(r"\\"):
            rtext = rtext[:-2]
        cells = re.split(r"(?<!\\)&", rtext)
        return [clean_cell(c) for c in cells]

    header = parse_row(header_part.strip().rstrip("\\"))
    rows = []
    for raw in re.split(r"\\\\", rows_part):
        if raw.strip():
            rows.append(parse_row(raw))

    ncol = len(header)
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * ncol) + "|"]
    for r in rows:
        r = (r + [""] * ncol)[:ncol]
        out.append("| " + " | ".join(r) + " |")
    out.append("")
    out.append(f"**{label} {prefix}{number}.** {caption}")
    return "\n".join(out)


def convert_figure(block: str, number: int, prefix: str = "", label: str = "Figure") -> str:
    imgs = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", block)
    m = re.search(r"\\caption\{(.*)\}\s*\\end\{figure\}", block, re.DOTALL)
    caption = clean_caption(m.group(1).strip()) if m else ""
    out = []
    for im in imgs:
        out.append(f"![]({im}){{width=85%}}")
        out.append("")
    out.append(f"**{label} {prefix}{number}.** {caption}")
    return "\n".join(out)


def preprocess(md: str, fig_prefix: str = "",
               fig_label: str = "Figure", tab_label: str = "Table") -> str:
    # equation environment -> display math (drop the label)
    md = re.sub(r"\\begin\{equation\}\s*\\label\{[^}]*\}(.*?)\\end\{equation\}",
                lambda m: "$$" + m.group(1).strip() + "$$", md, flags=re.DOTALL)
    md = md.replace(r"Equation \eqref{eq:bias}", "Equation (1)")
    md = md.replace(r"Eq. \eqref{eq:bias}", "Eq. (1)")
    md = md.replace(r"식 \eqref{eq:bias}", "식 (1)")
    md = re.sub(r"\\eqref\{eq:bias\}", "Eq. (1)", md)  # fallback

    tbl = re.compile(r"\\begin\{table\}.*?\\end\{table\}", re.DOTALL)
    figL = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL)
    figM = re.compile(r"!\[(.*?)\]\((figures/[^)]+)\)(\{[^}]*\})?", re.DOTALL)
    combined = re.compile(
        r"(\\begin\{table\}.*?\\end\{table\})"
        r"|(\\begin\{figure\}.*?\\end\{figure\})"
        r"|(!\[.*?\]\(figures/[^)]+\)(?:\{[^}]*\})?)", re.DOTALL)

    counters = {"fig": 0, "tab": 0}

    def repl(m: re.Match) -> str:
        chunk = m.group(0)
        if chunk.startswith(r"\begin{table}"):
            counters["tab"] += 1
            return convert_table(chunk, counters["tab"], fig_prefix, tab_label)
        if chunk.startswith(r"\begin{figure}"):
            counters["fig"] += 1
            return convert_figure(chunk, counters["fig"], fig_prefix, fig_label)
        # markdown image -> numbered figure (empty alt so pandoc adds no caption)
        counters["fig"] += 1
        im = figM.match(chunk)
        cap = clean_caption(im.group(1).strip())
        path = im.group(2)
        opts = im.group(3) or "{width=85%}"
        return f"![]({path}){opts}\n\n**{fig_label} {fig_prefix}{counters['fig']}.** {cap}"

    return combined.sub(repl, md)


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else "draft"
    stem = STEMS.get(key, key)
    src = MS / f"{stem}.md"
    fig_prefix = "S" if stem == "supplementary" else ""
    if stem == "draft_ko":
        md = preprocess(src.read_text(), fig_prefix, fig_label="그림", tab_label="표")
    else:
        md = preprocess(src.read_text(), fig_prefix)
    tmp = MS / f".{stem}.docx.md"
    tmp.write_text(md)
    out = MS / f"{stem}.docx"
    cmd = [
        "pandoc", tmp.name,
        "--from=markdown-implicit_figures+raw_tex+tex_math_dollars+pipe_tables+yaml_metadata_block",
        "--to=docx", "-o", out.name,
    ]
    # MDPI-style drafts use pandoc [@key] citations; resolve them to the
    # numeric MDPI style so the .docx carries inline [n] and a numbered
    # reference list (the RSE draft has hand-typed citations and is untouched).
    if "[@" in md and (MS / "references.bib").exists():
        cmd += ["--citeproc", "--bibliography=references.bib"]
        if (MS / "mdpi.csl").exists():
            cmd += ["--csl=mdpi.csl"]
    subprocess.run(cmd, cwd=MS, check=True)
    tmp.unlink()
    print(f"  -> {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
