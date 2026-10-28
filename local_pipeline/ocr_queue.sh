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
# Resumable: a PDF whose OCR copy is newer than the PDF is not OCR'd again.
# Set OCR_YES=1 to skip the prompt (needed when there is no keyboard).
# Exit status: 0 all done or declined; 1 ocrmypdf missing, nothing queued, no answer, or at least one
# file failed or was missing; 2 usage, or the archive root cannot be entered.
# Needs: ocrmypdf and tesseract. PDFTOOLS_BIN and OCR_TMPDIR are read by env.sh.

. "$(dirname "$0")/env.sh" 2>/dev/null || true
set -uo pipefail

ROOT="${1:-${ARCHIVE_ROOT:-}}"
[ -n "$ROOT" ] && [ -d "$ROOT" ] || { echo "usage: bash ocr_queue.sh <archive-root>   (or set ARCHIVE_ROOT)"; exit 2; }
GIVEN="$ROOT"
case "$ROOT" in /*) ;; *) ROOT="./$ROOT" ;; esac      # so a folder named - or -x is a path, not an option
ROOT="$(CDPATH= cd -- "$ROOT" 2>/dev/null && pwd -P)"   # the same spelling of the root that extract_all.sh used
[ -n "$ROOT" ] || { echo "ABORT: cannot enter the archive root: $GIVEN"; exit 2; }
DERIVED="$ROOT/_DERIVED/text"
OCRPDF="$ROOT/_DERIVED/ocr_pdf"
QUEUE=$(ls -t "$ROOT/_DERIVED"/_image_only_*.txt 2>/dev/null | head -1)

command -v ocrmypdf >/dev/null || { echo "FATAL: ocrmypdf missing (see env.sh)."; exit 1; }
[ -n "${QUEUE:-}" ] && [ -s "$QUEUE" ] || { echo "No image-only PDFs queued. Run extract_all.sh first; if it reported 0 image-only, there is nothing to OCR."; exit 1; }

# Convert a queue written by older versions (one path per line) before reading it.
if LC_ALL=C tr -d '\000' < "$QUEUE" | cmp -s "$QUEUE" -; then
  tmp_queue="${QUEUE}.part.$$"
  while IFS= read -r f || [ -n "$f" ]; do
    [ -n "$f" ] && printf '%s\0' "$f"
  done < "$QUEUE" > "$tmp_queue"
  mv -f "$tmp_queue" "$QUEUE" || { rm -f "$tmp_queue"; echo "FATAL: could not convert the legacy image-only queue"; exit 1; }
fi

N=0
while IFS= read -r -d '' _queued_file; do [ -n "$_queued_file" ] && N=$((N+1)); done < "$QUEUE"
[ "$N" -gt 0 ] || { echo "FATAL: image-only queue has no valid paths; rerun extract_all.sh."; exit 1; }
echo "$N image-only PDFs queued (from $QUEUE)"
echo "OCR is slow: expect a few seconds per page."
ok=
if [ "${OCR_YES:-0}" = "1" ]; then
  ok=y
elif ! read -r -p "Proceed? [y/N] " ok && [ -z "$ok" ]; then
  echo; echo "No answer could be read (no keyboard?). Nothing was OCR'd. Set OCR_YES=1 to run without the question."
  exit 1
fi
[ "$ok" = "y" ] || { echo "Nothing was OCR'd."; exit 0; }

ok_n=0; done_n=0; fail_n=0; miss_n=0
while IFS= read -r -d '' f; do
  [ -n "$f" ] || continue
  rel="${f#"$ROOT"/}"             # the root is quoted: a [, * or ? in its name is not a pattern
  if [ ! -f "$f" ]; then miss_n=$((miss_n+1)); echo "  MISSING  $rel"; continue; fi
  side="$DERIVED/${rel}.txt"
  # The same name that extract_all.sh tests for; change both together.
  ocrcopy="$OCRPDF/${rel}_OCR.pdf"
  mkdir -p "$(dirname "$side")" "$(dirname "$ocrcopy")"
  # resumable: a file is done when its sidecar exists and its OCR copy is newer than the PDF
  if [ -f "$side" ] && [ -f "$ocrcopy" ] && [ "$ocrcopy" -nt "$f" ]; then done_n=$((done_n+1)); continue; fi
  # Write under temporary names and rename on success, so a failed run leaves nothing that looks done.
  tmp_side="${side}.part"; tmp_pdf="${ocrcopy%.pdf}.part.pdf"
  if ocrmypdf --force-ocr --sidecar "$tmp_side" --output-type pdf \
        "$f" "$tmp_pdf" >/dev/null 2>&1 </dev/null \
     && [ -f "$tmp_side" ] && [ -f "$tmp_pdf" ] \
     && mv -f "$tmp_side" "$side" && mv -f "$tmp_pdf" "$ocrcopy"; then
    ok_n=$((ok_n+1)); echo "  OCR ok   $rel"
  else
    rm -f "$tmp_side" "$tmp_pdf"
    fail_n=$((fail_n+1)); echo "  OCR FAIL $rel"
  fi
done < "$QUEUE"

echo
echo "OCR'd $ok_n, already done $done_n, failed $fail_n, missing $miss_n."
echo "The new text has never been checked. If you use pii_sweep.sh, run it again now."
[ "$fail_n" -eq 0 ] && [ "$miss_n" -eq 0 ] || exit 1
