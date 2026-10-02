#!/bin/bash
# ocr_queue.sh - OCR the PDFs that extract_all.sh found to have no text layer.
#
#   usage: bash ocr_queue.sh <archive-root>      (or set ARCHIVE_ROOT)
#
# Why: a text extractor returns nothing for a scanned page. An empty result
# from a scan is not "nothing there"; the page has not been read yet.
#
# Never modifies an original. The OCR text goes to the same sidecar path that
# extract_all.sh uses, and the OCR'd PDF copy goes under _DERIVED/ocr_pdf/.
# Resumable. Set OCR_YES=1 to skip the prompt.
# Needs: ocrmypdf and tesseract. PDFTOOLS_BIN and OCR_TMPDIR are read by env.sh.

. "$(dirname "$0")/env.sh" 2>/dev/null || true
set -uo pipefail

ROOT="${1:-${ARCHIVE_ROOT:-}}"
[ -n "$ROOT" ] && [ -d "$ROOT" ] || { echo "usage: bash ocr_queue.sh <archive-root>   (or set ARCHIVE_ROOT)"; exit 2; }
ROOT="$(cd "$ROOT" && pwd -P)"   # the same spelling of the root that extract_all.sh used
DERIVED="$ROOT/_DERIVED/text"
OCRPDF="$ROOT/_DERIVED/ocr_pdf"
QUEUE=$(ls -t "$ROOT/_DERIVED"/_image_only_*.txt 2>/dev/null | head -1)

command -v ocrmypdf >/dev/null || { echo "FATAL: ocrmypdf missing (see env.sh)."; exit 1; }
[ -n "${QUEUE:-}" ] && [ -s "$QUEUE" ] || { echo "No image-only PDFs queued. Run extract_all.sh first; if it reported 0 image-only, there is nothing to OCR."; exit 1; }

N=$(wc -l < "$QUEUE" | tr -d ' ')
echo "$N image-only PDFs queued (from $QUEUE)"
echo "OCR is slow: expect a few seconds per page."
if [ "${OCR_YES:-0}" = "1" ]; then ok=y; else read -r -p "Proceed? [y/N] " ok; fi
[ "$ok" = "y" ] || exit 0

ok_n=0; fail_n=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  rel="${f#$ROOT/}"
  side="$DERIVED/${rel}.txt"
  mkdir -p "$(dirname "$side")" "$OCRPDF/$(dirname "$rel")"
  # resumable: a sidecar that already holds text is done
  if [ -s "$side" ] && [ "$(wc -c < "$side")" -gt 200 ]; then ok_n=$((ok_n+1)); continue; fi
  if ocrmypdf --force-ocr --sidecar "$side" --output-type pdf \
        "$f" "$OCRPDF/${rel%.*}_OCR.pdf" >/dev/null 2>&1; then
    ok_n=$((ok_n+1)); echo "  OCR ok   $rel"
  else
    fail_n=$((fail_n+1)); echo "  OCR FAIL $rel"
  fi
done < "$QUEUE"

echo
echo "OCR'd $ok_n, failed $fail_n."
echo "The new text has never been checked. If you use pii_sweep.sh, run it again now."
