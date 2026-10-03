#!/bin/bash
# pii_sweep.sh - find ID-shaped and card-shaped numbers in the text sidecars
# written by extract_all.sh and ocr_queue.sh. Use it to check a redaction.
#
#   usage: bash pii_sweep.sh <archive-root>      (or set ARCHIVE_ROOT)
#
# Three rules built in:
#   1. Numbers are printed with spaces and hyphens, so separators are removed
#      before a candidate is measured.
#   2. Separators are removed inside one candidate only, never across the
#      whole file. A candidate is a run of digits joined by single spaces or
#      single hyphens. Stripping a whole file glues unrelated table columns
#      together and invents long numbers that are nowhere in the document;
#      about one random digit string in ten passes the card checksum, so that
#      mistake reports "valid cards" that do not exist. Two columns that sit
#      exactly one space apart are still joined: look at a hit before acting.
#   3. The length window is 13 to 19 digits. A narrower window (13 to 16, the
#      usual card pattern) cannot see a 17-digit account number.
#
# Every run starts with a positive canary: a file known to contain three hits.
# If the canary does not fire, the script stops instead of reporting clean.
#
# Reads sidecars only. A scanned page that was never OCR'd has no sidecar text
# and is not covered: run ocr_queue.sh first.
# Needs: python3 (for the card checksum).

set -uo pipefail

ROOT="${1:-${ARCHIVE_ROOT:-}}"
[ -n "$ROOT" ] && [ -d "$ROOT" ] || { echo "usage: bash pii_sweep.sh <archive-root>   (or set ARCHIVE_ROOT)"; exit 2; }
GIVEN="$ROOT"
case "$ROOT" in /*) ;; *) ROOT="./$ROOT" ;; esac      # so a folder named - or -x is a path, not an option
ROOT="$(CDPATH= cd -- "$ROOT" 2>/dev/null && pwd -P)"
[ -n "$ROOT" ] || { echo "ABORT: cannot enter the archive root: $GIVEN"; exit 2; }
DERIVED="$ROOT/_DERIVED/text"
OUT="$ROOT/_DERIVED/_pii_sweep_$(date +%Y-%m-%d).txt"

[ -d "$DERIVED" ] || { echo "FATAL: no sidecars. Run extract_all.sh first."; exit 1; }

# ---------------------------------------------------------------- canary ---
# The test values are assembled at run time so that this source file does not
# itself contain an ID-shaped or card-shaped number.
CANARY="$DERIVED/.__canary__.txt"
q=1111
{
  printf 'id %s-%s-%s\n' 123 45 6789
  printf 'card 4%s %s %s %s\n' 111 "$q" "$q" "$q"
  printf 'long %s%s\n' "$(printf '%s' {1..9})" "$(printf '%s' {0..7})"
} > "$CANARY"

luhn_check() {  # exit 0 when the digit string passes the card checksum
  python3 -c "
import sys
d = sys.argv[1]
if not d.isdigit() or not (13 <= len(d) <= 19): sys.exit(1)
t = 0
for i, c in enumerate(reversed(d)):
    n = int(c)
    if i % 2:
        n *= 2
        n = n - 9 if n > 9 else n
    t += n
sys.exit(0 if t % 10 == 0 else 1)" "$1" 2>/dev/null
}

scan() {  # $1 = file ; prints "TYPE<TAB>value" per hit
  local f="$1"
  # nine digits printed in the hyphenated 3-2-4 layout: cut the text into tokens of digit groups joined by hyphens and
  # keep the tokens of exactly that shape, so two IDs side by side are both found and a longer
  # hyphenated number is not mistaken for one
  grep -oE '[0-9]+(-[0-9]+)*' "$f" 2>/dev/null | grep -xE '[0-9]{3}-[0-9]{2}-[0-9]{4}' \
    | sort -u | while read -r d; do printf 'ID_3_2_4\t%s\n' "$d"; done
  # a run of digits joined by single spaces or hyphens, 13 to 19 digits once the separators are removed
  grep -oE '[0-9](([ -]?[0-9]){11,18})' "$f" 2>/dev/null \
    | sed 's/[ -]//g' | grep -E '^[0-9]{13,19}$' | sort -u | while read -r d; do
        if luhn_check "$d"; then printf 'CARD_CHECKSUM_VALID\t%s\n' "$d"; else printf 'LONGNUM_%sD\t%s\n' "${#d}" "$d"; fi
      done
}

echo "=== canary self-test ==="
CH=$(scan "$CANARY" | wc -l | tr -d ' ')
rm -f "$CANARY"
if [ "$CH" -lt 3 ]; then
  echo "ABORT: the canary produced $CH hits, expected at least 3. The sweep is broken."
  echo "A zero from a broken sweep looks the same as a clean archive."
  exit 1
fi
echo "canary fired ($CH hits)"

echo "=== sweeping ===" | tee "$OUT"
echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT"
n_files=0; n_dirty=0
while IFS= read -r f; do
  n_files=$((n_files+1))
  hits=$(scan "$f")
  if [ -n "$hits" ]; then
    n_dirty=$((n_dirty+1))
    src="${f#$DERIVED/}"; src="${src%.txt}"
    { echo "--- $src"; echo "$hits" | sort -u | sed 's/^/    /'; } >> "$OUT"
  fi
done < <(find "$DERIVED" -name '*.txt' -type f 2>/dev/null)

echo "scanned $n_files sidecars, $n_dirty carry ID-shaped or card-shaped digits" | tee -a "$OUT"
echo
echo "A long digit run is not always an account number: reference numbers and"
echo "run-together dates match too. CARD_CHECKSUM_VALID is the high-confidence"
echo "class; look at the rest before acting on them."
echo "The report holds the matched numbers in full. Keep it private: $OUT"
