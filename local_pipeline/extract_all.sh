#!/bin/bash
# extract_all.sh - write a greppable text sidecar for every PDF under a folder.
#
#   usage: bash extract_all.sh <archive-root>      (or set ARCHIVE_ROOT)
#
# Why: reading is the expensive part of working through a large archive. Run
# this once, locally, and afterwards a search is a grep over text files.
#
# Resumable: a PDF whose sidecar is newer than the PDF is skipped.
# A PDF with fewer than 200 bytes of non-blank text and at least one raster image is listed as
# image-only, until ocr_queue.sh has left an OCR copy of it that is newer than the PDF.
# "Newer" is by modification time. To force a re-read, delete the sidecar and the OCR copy.
# Read-only on sources: never modifies, moves or deletes a source file.
# Output goes under <archive-root>/_DERIVED/. Runs on macOS bash 3.2 and Linux.
# Needs: poppler (pdftotext, pdfimages). PDFTOOLS_BIN and OCR_TMPDIR are read by env.sh.

. "$(dirname "$0")/env.sh" 2>/dev/null || true
set -uo pipefail

ROOT="${1:-${ARCHIVE_ROOT:-}}"
[ -n "$ROOT" ] && [ -d "$ROOT" ] || { echo "usage: bash extract_all.sh <archive-root>   (or set ARCHIVE_ROOT)"; exit 2; }
GIVEN="$ROOT"
case "$ROOT" in /*) ;; *) ROOT="./$ROOT" ;; esac      # so a folder named - or -x is a path, not an option
ROOT="$(CDPATH= cd -- "$ROOT" 2>/dev/null && pwd -P)"   # one spelling of the root, so sidecar paths match between runs and scripts
[ -n "$ROOT" ] || { echo "ABORT: cannot enter the archive root: $GIVEN"; exit 2; }
DERIVED="$ROOT/_DERIVED/text"
LOG="$ROOT/_DERIVED/_extract_log_$(date +%Y-%m-%d).txt"
IMAGEONLY="$ROOT/_DERIVED/_image_only_$(date +%Y-%m-%d).txt"
OCRPDF="$ROOT/_DERIVED/ocr_pdf"
MINCHARS=200          # below this many bytes of non-blank text, check whether the file is a scan

command -v pdftotext >/dev/null || { echo "FATAL: pdftotext missing (install poppler; see env.sh)."; exit 1; }

mkdir -p "$DERIVED"
: > "$IMAGEONLY"

# A sweep that finds nothing must prove that it ran. -iname, because a
# case-sensitive *.pdf misses .PDF. bash 3.2 has no mapfile, so fill the
# array with a read loop.
FILES=()
# find runs from inside the root, so the root's own name is never part of a -path pattern.
while IFS= read -r -d '' p; do FILES+=("$ROOT/${p#./}"); done < <(cd "$ROOT" && find . -iname '*.pdf' -type f ! -path './_DERIVED/*' ! -path '*/.git/*' -print0 2>/dev/null)
TOTAL=${#FILES[@]}
if [ "$TOTAL" -eq 0 ]; then
  echo "ABORT: zero PDFs found under $ROOT. That is a broken sweep, not a clean result."
  exit 1
fi
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)  START  $TOTAL PDFs under $ROOT" | tee -a "$LOG"

done_n=0; skip_n=0; img_n=0; fail_n=0
for f in "${FILES[@]}"; do
  rel="${f#"$ROOT"/}"             # the root is quoted: a [, * or ? in its name is not a pattern
  out="$DERIVED/${rel}.txt"
  mkdir -p "$(dirname "$out")"

  # The OCR copy that ocr_queue.sh writes. The name keeps the PDF's own extension, so a.pdf and a.PDF
  # do not share one copy. ocr_queue.sh builds the same name; change both together.
  ocrcopy="$OCRPDF/${rel}_OCR.pdf"
  ocrd=0
  if [ -f "$ocrcopy" ] && [ "$ocrcopy" -nt "$f" ]; then ocrd=1; fi

  fresh=0
  if [ -f "$out" ] && [ "$out" -nt "$f" ]; then
    skip_n=$((skip_n+1))          # resumable: the sidecar is newer than the PDF
  else
    # A sidecar that has to be rebuilt for a PDF already OCR'd is rebuilt from the OCR copy, which
    # has the text layer. The scan itself would give an empty sidecar.
    src="$f"; [ "$ocrd" = 1 ] && src="$ocrcopy"
    if pdftotext -layout -q "$src" "$out" 2>/dev/null; then
      fresh=1
    else
      echo "FAIL_EXTRACT  $rel" >> "$LOG"; fail_n=$((fail_n+1)); continue
    fi
  fi

  # The image-only test runs for skipped files too: the queue file is rebuilt on every run, and a
  # scan that was extracted earlier but not yet OCR'd must stay in it.
  # Count the bytes that are not white space, not all bytes: pdftotext writes one form feed per
  # page, so the sidecar of a long scan is hundreds of bytes with nothing in them. The count stops
  # at MINCHARS. (LC_ALL=C: bytes, so a damaged character cannot stop tr.)
  chars=$(LC_ALL=C tr -d '[:space:]' < "$out" 2>/dev/null | head -c "$MINCHARS" | wc -c | tr -d ' '); chars=${chars:-0}
  if [ "$chars" -lt "$MINCHARS" ]; then
    # Little or no text does not always mean a scan:
    #   raster images and no text    -> a scan; it needs OCR
    #   no raster images and no text -> a short document, already fully read
    # Without this test, every short cover page lands in the OCR queue.
    rasters=$(pdfimages -list "$f" 2>/dev/null | tail -n +3 | wc -l | tr -d ' ')
    if [ "${rasters:-0}" -gt 0 ] && [ "$ocrd" = 1 ]; then
      # OCR has been run since the PDF last changed. A page with almost nothing on it has been read
      # once it has been OCR'd; it is not queued again.
      [ "$fresh" = 1 ] && echo "OCR_DONE_LITTLE_TEXT  ${chars} chars  ${rasters} rasters  $rel" >> "$LOG"
    elif [ "${rasters:-0}" -gt 0 ]; then
      echo "$f" >> "$IMAGEONLY"; img_n=$((img_n+1))
      [ "$fresh" = 1 ] && echo "IMAGE_ONLY  ${chars} chars  ${rasters} rasters  $rel" >> "$LOG"
    elif [ "$fresh" = 1 ]; then
      echo "SHORT_BUT_COMPLETE  ${chars} chars  0 rasters  $rel" >> "$LOG"
    fi
  fi
  [ "$fresh" = 1 ] || continue
  done_n=$((done_n+1))
  if [ $((done_n % 250)) -eq 0 ]; then
    echo "  ... $done_n extracted / $skip_n skipped / $img_n image-only" | tee -a "$LOG"
  fi
done

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)  DONE" | tee -a "$LOG"
printf "  extracted %d\n  skipped(current) %d\n  image-only %d  -> %s\n  failed %d\n" \
  "$done_n" "$skip_n" "$img_n" "$IMAGEONLY" "$fail_n" | tee -a "$LOG"
echo
echo "Image-only files carry no searchable text. Until they are OCR'd, a search"
echo "that finds nothing has not looked inside those $img_n documents."
echo "Next: bash ocr_queue.sh \"$ROOT\""
