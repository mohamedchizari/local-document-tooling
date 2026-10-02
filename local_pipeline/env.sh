#!/bin/bash
# env.sh - shared setup for extract_all.sh and ocr_queue.sh. Source it; do not run it.
#
# 1. PATH. The pipeline needs poppler (pdftotext, pdfimages) and, for OCR, tesseract and ocrmypdf.
#    If they are not already on PATH, set PDFTOOLS_BIN to the directory that holds them, for example
#    the bin directory of a conda environment:
#      conda create -n pdftools -c conda-forge poppler tesseract ocrmypdf
#      export PDFTOOLS_BIN="$(conda info --base)/envs/pdftools/bin"
if [ -n "${PDFTOOLS_BIN:-}" ]; then export PATH="$PDFTOOLS_BIN:$PATH"; fi

# 2. TMPDIR. ocrmypdf stages pages in $TMPDIR. Launched from a non-login shell (osascript, launchd),
#    tesseract may be unable to read files under /tmp, so the staging directory is moved under the
#    home folder. Note that this changes TMPDIR for the calling script. Override with OCR_TMPDIR.
export TMPDIR="${OCR_TMPDIR:-$HOME/.ocrtmp}"; mkdir -p "$TMPDIR"
