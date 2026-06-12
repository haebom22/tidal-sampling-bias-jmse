#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build_mdpi.sh
#
# LaTeX-based PDF build for the MDPI *Remote Sensing* manuscript
# (draft_mdpi.md), the MDPI-formatted sibling of draft.md.
#
# DIFFERENCE FROM build_manuscript_pdf.sh (the RSE build):
#   The MDPI draft uses pandoc [@key] citations instead of hand-typed
#   author-year text, so this build adds citeproc with the official MDPI
#   numeric citation style:
#       --citeproc
#       --bibliography=references.bib
#       --csl=mdpi.csl     (Multidisciplinary Digital Publishing Institute,
#                           citation-format="numeric"  -> inline [1], [4-6])
#   Everything else (XeLaTeX via tectonic, continuous line numbers, double
#   spacing, 2.5 cm margins from the YAML header-includes) is identical, so
#   the output is a clean line-numbered PDF suitable for initial SuSy
#   submission. MDPI re-typesets accepted papers into mdpi.cls at production.
#
# REQUIREMENTS (install once):
#   brew install pandoc tectonic
#   manuscript/mdpi.csl   (official MDPI CSL; fetched once from the
#                          citation-style-language repo, tracked in git)
#
# USAGE:
#   bash scripts/build_mdpi.sh            # draft_mdpi.pdf  (default)
#   bash scripts/build_mdpi.sh draft      # same as above
#   bash scripts/build_mdpi.sh cover      # cover_letter_mdpi.pdf (if present)
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MS_DIR="${MS_DIR:-${PROJECT_ROOT}/manuscript}"
case "${MS_DIR}" in
  /*) : ;;
  *)  MS_DIR="${PROJECT_ROOT}/${MS_DIR}" ;;
esac

PANDOC=$(command -v pandoc || true)
TECTONIC=$(command -v tectonic || true)
if [ -z "${PANDOC}" ] || [ -z "${TECTONIC}" ]; then
  echo "ERROR: pandoc and tectonic are required.  brew install pandoc tectonic"
  exit 1
fi

BIB="${MS_DIR}/references.bib"
CSL="${MS_DIR}/mdpi.csl"
if [ ! -f "${BIB}" ]; then echo "ERROR: ${BIB} not found."; exit 1; fi
if [ ! -f "${CSL}" ]; then
  echo "ERROR: ${CSL} not found.  Fetch once with:"
  echo "  curl -fsSL -o manuscript/mdpi.csl \\"
  echo "    https://raw.githubusercontent.com/citation-style-language/styles/master/multidisciplinary-digital-publishing-institute.csl"
  exit 1
fi

build_one() {
  local stem="$1"
  local src="${MS_DIR}/${stem}.md"
  local out="${MS_DIR}/${stem}.pdf"
  if [ ! -f "${src}" ]; then echo "  -- ${src} not found, skipping."; return 0; fi

  echo "  -> ${stem}.md  ==pandoc+citeproc+tectonic==>  ${stem}.pdf"
  (
    cd "${MS_DIR}"
    # Capture pandoc's real exit status (PIPESTATUS) so a LaTeX error fails
    # loudly instead of leaving a stale PDF behind the grep/`|| true` filter.
    "${PANDOC}" "${stem}.md" \
      --from=markdown+raw_tex+tex_math_dollars+pipe_tables+yaml_metadata_block \
      --citeproc \
      --bibliography="references.bib" \
      --csl="mdpi.csl" \
      --pdf-engine=tectonic \
      --variable=papersize:a4 \
      -o "${stem}.pdf" 2> >(grep -vE '^warning: accessing absolute path|^warning: .*hbox' >&2)
  ) || { echo "  !! BUILD FAILED for ${stem}.md (LaTeX/pandoc error above)"; return 1; }
  echo "     -> $(ls -lh "${out}" | awk '{print $5}')  generated."
}

target="${1:-draft}"
echo "Building MDPI Remote Sensing manuscript PDF (LaTeX + citeproc)..."
case "${target}" in
  draft) build_one draft_mdpi ;;
  cover) build_one cover_letter_mdpi ;;
  all)   build_one draft_mdpi; build_one cover_letter_mdpi ;;
  *)     echo "Unknown target: ${target}  (use draft|cover|all)"; exit 1 ;;
esac
echo "Done."
