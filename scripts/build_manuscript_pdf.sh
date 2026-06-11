#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build_manuscript_pdf.sh
#
# LaTeX-based PDF build for the RSE manuscript (draft.md + cover_letter.md).
#
# WHY THIS EXISTS:
#   The global ~/.cursor/tools/md2pdf.py converter uses weasyprint, which
#   silently ignores LaTeX header-includes (\linenumbers, linestretch, etc.).
#   For RSE submission the manuscript MUST have:
#     - continuous line numbering   (required by RSE Guide for Authors)
#     - double spacing               (required by RSE Guide for Authors)
#     - 2.5 cm margins               (required by RSE Guide for Authors)
#   All three are honoured ONLY by a real LaTeX pipeline.
#
# PIPELINE:  pandoc  ->  XeLaTeX-flavoured .tex  ->  tectonic  ->  PDF
#   - pandoc reads the YAML frontmatter and translates header-includes.
#   - tectonic auto-downloads any missing LaTeX packages on first run.
#   - tectonic uses XeTeX, so unicode-math + STIX Two Text "just work".
#
# REQUIREMENTS (install once):
#   brew install pandoc tectonic
#
# USAGE:
#   bash scripts/build_manuscript_pdf.sh          # builds draft + cover + supp + ko PDFs
#   bash scripts/build_manuscript_pdf.sh draft    # builds only draft.pdf
#   bash scripts/build_manuscript_pdf.sh cover    # builds only cover_letter.pdf
#   bash scripts/build_manuscript_pdf.sh supp     # builds only supplementary.pdf
#   bash scripts/build_manuscript_pdf.sh ko       # builds only draft_ko.pdf (Korean translation)
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# MS_DIR defaults to manuscript/ but can be overridden to build a sibling
# manuscript directory, e.g.  MS_DIR=manuscript3 bash scripts/build_manuscript_pdf.sh draft
MS_DIR="${MS_DIR:-${PROJECT_ROOT}/manuscript}"
# Allow a relative override (resolve against PROJECT_ROOT).
case "${MS_DIR}" in
  /*) : ;;                                  # already absolute
  *)  MS_DIR="${PROJECT_ROOT}/${MS_DIR}" ;;  # make relative override absolute
esac

PANDOC=$(command -v pandoc || true)
TECTONIC=$(command -v tectonic || true)

if [ -z "${PANDOC}" ] || [ -z "${TECTONIC}" ]; then
  echo "ERROR: pandoc and tectonic are required."
  echo "Install with:  brew install pandoc tectonic"
  exit 1
fi

build_one() {
  local stem="$1"
  local src="${MS_DIR}/${stem}.md"
  local out="${MS_DIR}/${stem}.pdf"

  if [ ! -f "${src}" ]; then
    echo "  -- ${src} not found, skipping."
    return 0
  fi

  echo "  -> ${stem}.md  ==pandoc+tectonic==>  ${stem}.pdf"
  (
    cd "${MS_DIR}"
    "${PANDOC}" "${stem}.md" \
      --from=markdown+raw_tex+tex_math_dollars+pipe_tables+yaml_metadata_block \
      --pdf-engine=tectonic \
      --variable=papersize:a4 \
      -o "${stem}.pdf" 2>&1 | grep -vE '^warning: accessing absolute path' \
                            | grep -vE '^warning: .*hbox' || true
  )
  echo "     -> $(ls -lh "${out}" | awk '{print $5}')  generated."
}

target="${1:-all}"
echo "Building RSE manuscript PDFs (LaTeX pipeline)..."
case "${target}" in
  draft)  build_one draft ;;
  cover)  build_one cover_letter ;;
  supp)   build_one supplementary ;;
  ko)     build_one draft_ko ;;
  all)    build_one draft; build_one cover_letter; build_one supplementary; build_one draft_ko ;;
  *)      echo "Unknown target: ${target}  (use draft|cover|supp|ko|all)"; exit 1 ;;
esac
echo "Done."
