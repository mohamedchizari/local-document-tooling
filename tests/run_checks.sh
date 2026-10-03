#!/bin/bash
# run_checks.sh - checks for the PDF text pipeline and for the amount patterns of scan_intake.py.
#
#   usage: bash tests/run_checks.sh [work-dir]
#
# Generates made-up fixtures (tests/make_fixtures.py), runs extract_all.sh and ocr_queue.sh on them
# with real OCR, and prints one PASS or FAIL line per assertion and a total. Exit status 0 when
# nothing failed, 1 when something did, 2 when a tool is missing.
# Writes under the work folder: the one you name, or a new temporary folder. It prints where that
# is and leaves it in place. Name a folder that does not exist yet; an old one gives wrong counts.
# The pipeline also uses its OCR staging folder (~/.ocrtmp, or OCR_TMPDIR; see local_pipeline/env.sh).
# Runs on macOS bash 3.2 and Linux. Takes a minute or two (it OCRs a 210-page scan).
# Needs: poppler, ocrmypdf and tesseract (see local_pipeline/env.sh), and a python3 with Pillow for
# the fixtures. PYTHON names the interpreter (default python3).
TREE="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
W="${1:-$(mktemp -d "${TMPDIR:-/tmp}/ldt_checks.XXXXXX")}"
EX="$TREE/local_pipeline/extract_all.sh"; OQ="$TREE/local_pipeline/ocr_queue.sh"
PY="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1      # no __pycache__ in the repository
pass=0; fail=0
ok(){ if eval "$2"; then pass=$((pass+1)); echo "PASS  $1"; else fail=$((fail+1)); echo "FAIL  $1"; fi; }
nb(){ LC_ALL=C tr -d '[:space:]' < "$1" 2>/dev/null | wc -c | tr -d ' '; }      # bytes of non-blank text
queue(){ ls -t "$1/_DERIVED"/_image_only_*.txt 2>/dev/null | head -1; }         # newest image-only list
qn(){ q=$(queue "$1"); [ -n "$q" ] && wc -l < "$q" | tr -d ' ' || echo 0; }     # lines in it
inq(){ grep -c -F -- "$2" "$(queue "$1")" 2>/dev/null; }                        # lines that hold a path
num(){ sed -n "s/^ *$1 \([0-9][0-9]*\).*/\1/p" | head -1; }                    # a count from the summary
sum(){ if command -v md5sum >/dev/null; then md5sum < "$1" | cut -c1-32; else md5 -q "$1"; fi; }
old(){ touch -t 202601010000 "$@"; }                                            # a source older than any output

# the same tools the pipeline will use
if [ -n "${PDFTOOLS_BIN:-}" ]; then PATH="$PDFTOOLS_BIN:$PATH"; fi
for t in pdftotext pdfimages ocrmypdf tesseract; do
  command -v "$t" >/dev/null || { echo "MISSING: $t (see local_pipeline/env.sh)"; exit 2; }
done
mkdir -p "$W" || exit 2
W="$(CDPATH= cd -- "$W" && pwd -P)"; FX="$W/fixtures"
"$PY" "$TREE/tests/make_fixtures.py" "$FX" || { echo "MISSING: fixtures could not be made (Pillow is needed; PYTHON names the interpreter)"; exit 2; }
echo "work folder: $W"
echo "bash $BASH_VERSION | $(uname -s) | ocrmypdf: $( . "$TREE/local_pipeline/env.sh" 2>/dev/null; command -v ocrmypdf || echo none)"
ok "syntax extract_all.sh" 'bash -n "$EX"'
ok "syntax ocr_queue.sh" 'bash -n "$OQ"'

R="$W/arch [1] a*b?"; mkdir -p "$R/sub"
cp "$FX/text.pdf" "$FX/short_text.pdf" "$FX/scan_text.pdf" "$FX/scan_blank.pdf" "$R/"; cp "$FX/long_scan_210.pdf" "$R/sub/"
old "$R"/*.pdf "$R"/sub/*.pdf
RP="$(cd "$R" && pwd -P)"; T="$RP/_DERIVED/text"; O="$RP/_DERIVED/ocr_pdf"

echo "=== 1 extract_all, root name with [ ] * ?"
out=$(bash "$EX" "$R" 2>&1); rc=$?
ok "1a exit 0" '[ $rc -eq 0 ]'
ok "1b extracted 5" '[ "$(echo "$out" | num extracted)" = 5 ]'
ok "1c image-only 3" '[ "$(echo "$out" | num image-only)" = 3 ] && [ "$(qn "$R")" = 3 ]'
ok "1d the 210-page scan is listed" '[ "$(inq "$R" sub/long_scan_210.pdf)" = 1 ]'
ok "1e scan_text and scan_blank listed" '[ "$(inq "$R" /scan_text.pdf)" = 1 ] && [ "$(inq "$R" /scan_blank.pdf)" = 1 ]'
ok "1f text.pdf and short_text.pdf not listed" '[ "$(inq "$R" /text.pdf)" = 0 ] && [ "$(inq "$R" short_text.pdf)" = 0 ]'
ok "1g short_text logged SHORT_BUT_COMPLETE" 'grep -q "SHORT_BUT_COMPLETE.*short_text.pdf" "$RP/_DERIVED"/_extract_log_*.txt'
ok "1h five sidecars, at the expected paths" '[ "$(find "$T" -name "*.txt" | wc -l | tr -d " ")" = 5 ] && [ -f "$T/sub/long_scan_210.pdf.txt" ] && [ -f "$T/text.pdf.txt" ]'
ok "1i second run: skipped 5, still image-only 3" 'o2=$(bash "$EX" "$R" 2>&1); [ "$(echo "$o2" | num "skipped(current)")" = 5 ] && [ "$(echo "$o2" | num image-only)" = 3 ]'

echo "=== 2 ocr_queue: no keyboard, standard input closed, then a 'no'"
out=$(bash "$OQ" "$R" < /dev/null 2>&1); rc=$?
ok "2a no keyboard: exit 1 and says so" '[ $rc -eq 1 ] && echo "$out" | grep -q "OCR_YES=1"'
out=$(ok=y bash "$OQ" "$R" 2>&1 <&-); rc=$?
ok "2b standard input closed: exit 1, says so, nothing OCRd" '[ $rc -eq 1 ] && echo "$out" | grep -q "OCR_YES=1" && [ ! -d "$O" ]'
out=$(printf 'n\n' | bash "$OQ" "$R" 2>&1); rc=$?
ok "2c answer n: exit 0, nothing OCRd" '[ $rc -eq 0 ] && echo "$out" | grep -q "Nothing was OCR" && [ ! -d "$O" ]'

echo "=== 3 a failing OCR that leaves partial files behind"
FAKE="$W/fakebin"; mkdir -p "$FAKE"
cat > "$FAKE/ocrmypdf" <<'EOS'
#!/bin/bash
# stand-in that fails after writing partial outputs
side=""; last=""
while [ $# -gt 0 ]; do case "$1" in --sidecar) side="$2"; shift;; esac; last="$1"; shift; done
[ -n "$side" ] && echo "partial text" > "$side"
echo "partial pdf" > "$last"
exit 1
EOS
chmod +x "$FAKE/ocrmypdf"
out=$(PDFTOOLS_BIN="$FAKE" OCR_YES=1 bash "$OQ" "$R" 2>&1); rc=$?
ok "3a exit 1, failed 3" '[ $rc -eq 1 ] && echo "$out" | grep -q "OCR.d 0, already done 0, failed 3, missing 0"'
ok "3b no OCR copy and no .part file left" '[ "$(find "$RP/_DERIVED" \( -name "*_OCR.pdf" -o -name "*.part*" \) | wc -l | tr -d " ")" = 0 ]'
ok "3c sidecar not overwritten by the failed run" '[ -f "$T/scan_text.pdf.txt" ] && ! grep -q "partial text" "$T/scan_text.pdf.txt"'
ok "3d still listed on the next extract run" 'o=$(bash "$EX" "$R" 2>&1); [ "$(echo "$o" | num image-only)" = 3 ]'

echo "=== 4 real OCR (OCR_YES=1)"
out=$(OCR_YES=1 bash "$OQ" "$R" 2>&1); rc=$?
echo "$out" | tail -3
ok "4a exit 0; OCR'd 3, already done 0, failed 0, missing 0" '[ $rc -eq 0 ] && echo "$out" | grep -q "OCR.d 3, already done 0, failed 0, missing 0"'
ok "4b OCR copies carry the full file name" '[ -f "$O/scan_text.pdf_OCR.pdf" ] && [ -f "$O/scan_blank.pdf_OCR.pdf" ] && [ -f "$O/sub/long_scan_210.pdf_OCR.pdf" ]'
ok "4c scan_text sidecar now has 200+ bytes of non-blank text and the word Balance" '[ "$(nb "$T/scan_text.pdf.txt")" -ge 200 ] && grep -q "Balance" "$T/scan_text.pdf.txt"'
ok "4d scan_blank sidecar has under 200" '[ "$(nb "$T/scan_blank.pdf.txt")" -lt 200 ]'
ok "4e no .part file left" '[ "$(find "$RP/_DERIVED" -name "*.part*" | wc -l | tr -d " ")" = 0 ]'
out=$(bash "$EX" "$R" 2>&1)
ok "4f extract again: image-only 0 (the blank scan and the long scan are not queued twice)" '[ "$(echo "$out" | num image-only)" = 0 ] && [ "$(qn "$R")" = 0 ]'
ok "4g extract again: skipped 5, extracted 0" '[ "$(echo "$out" | num "skipped(current)")" = 5 ] && [ "$(echo "$out" | num extracted)" = 0 ]'
out=$(OCR_YES=1 bash "$OQ" "$R" 2>&1); rc=$?
ok "4h ocr_queue with an empty queue: exit 1, says nothing queued" '[ $rc -eq 1 ] && echo "$out" | grep -q "No image-only PDFs queued"'

echo "=== 5 a sidecar that has to be rebuilt after OCR"
mkdir -p "$W/moved"; mv "$T/scan_text.pdf.txt" "$W/moved/a.txt"; mv "$T/scan_blank.pdf.txt" "$W/moved/b.txt"
out=$(bash "$EX" "$R" 2>&1)
ok "5a extracted 2, image-only 0" '[ "$(echo "$out" | num extracted)" = 2 ] && [ "$(echo "$out" | num image-only)" = 0 ]'
ok "5b scan_text sidecar rebuilt WITH its text (from the OCR copy)" '[ "$(nb "$T/scan_text.pdf.txt")" -ge 200 ] && grep -q "Balance" "$T/scan_text.pdf.txt"'
ok "5c scan_blank logged OCR_DONE_LITTLE_TEXT" 'grep -q "OCR_DONE_LITTLE_TEXT.*scan_blank.pdf" "$RP/_DERIVED"/_extract_log_*.txt'

echo "=== 6 a PDF that changes after it was OCR'd"
sleep 1; touch "$R/scan_text.pdf"; sleep 1
out=$(bash "$EX" "$R" 2>&1)
ok "6a re-extracted from the PDF and listed again" '[ "$(echo "$out" | num image-only)" = 1 ] && [ "$(inq "$R" /scan_text.pdf)" = 1 ] && [ "$(nb "$T/scan_text.pdf.txt")" -lt 200 ]'
cp "$(queue "$R")" "$W/queue_with_scan_text.txt"
out=$(OCR_YES=1 bash "$OQ" "$R" 2>&1); rc=$?
ok "6b OCR'd 1 again, exit 0" '[ $rc -eq 0 ] && echo "$out" | grep -q "OCR.d 1, already done 0, failed 0, missing 0"'
ok "6c then not listed" 'o=$(bash "$EX" "$R" 2>&1); [ "$(echo "$o" | num image-only)" = 0 ]'

echo "=== 7 a stale queue: one file already done, one file gone"
{ cat "$W/queue_with_scan_text.txt"; echo "$RP/gone.pdf"; } > "$(queue "$R")"
out=$(OCR_YES=1 bash "$OQ" "$R" 2>&1); rc=$?
ok "7a OCR'd 0, already done 1, failed 0, missing 1; exit 1" '[ $rc -eq 1 ] && echo "$out" | grep -q "OCR.d 0, already done 1, failed 0, missing 1"'

echo "=== 8 sources unchanged"
ok "8a every PDF in the archive equals its fixture" '[ "$(sum "$R/scan_text.pdf")" = "$(sum "$FX/scan_text.pdf")" ] && [ "$(sum "$R/scan_blank.pdf")" = "$(sum "$FX/scan_blank.pdf")" ] && [ "$(sum "$R/sub/long_scan_210.pdf")" = "$(sum "$FX/long_scan_210.pdf")" ] && [ "$(sum "$R/text.pdf")" = "$(sum "$FX/text.pdf")" ] && [ "$(sum "$R/short_text.pdf")" = "$(sum "$FX/short_text.pdf")" ]'
ok "8b nothing but the 5 PDFs outside _DERIVED" '[ "$(cd "$R" && find . -type f ! -path "./_DERIVED/*" | wc -l | tr -d " ")" = 5 ]'

echo "=== 9 two files whose names differ only in the case of the extension"
R2="$W/twins"; mkdir -p "$R2"; cp "$FX/scan_text.pdf" "$R2/twin.pdf"; cp "$FX/scan_text_b.pdf" "$R2/twin.PDF"
if [ "$(ls "$R2" | wc -l | tr -d ' ')" = 2 ]; then
  old "$R2"/twin.*
  out=$(bash "$EX" "$R2" 2>&1); ok "9a both listed" '[ "$(echo "$out" | num image-only)" = 2 ]'
  out=$(OCR_YES=1 bash "$OQ" "$R2" 2>&1); ok "9b OCR'd 2" 'echo "$out" | grep -q "OCR.d 2, already done 0, failed 0, missing 0"'
  ok "9c two OCR copies" '[ -f "$R2/_DERIVED/ocr_pdf/twin.pdf_OCR.pdf" ] && [ -f "$R2/_DERIVED/ocr_pdf/twin.PDF_OCR.pdf" ]'
  ok "9d each sidecar has its own text" 'grep -q "VARIANT" "$R2/_DERIVED/text/twin.PDF.txt" && [ "$(nb "$R2/_DERIVED/text/twin.pdf.txt")" -ge 200 ] && ! grep -q "VARIANT" "$R2/_DERIVED/text/twin.pdf.txt"'
  out=$(bash "$EX" "$R2" 2>&1); ok "9e then neither is listed" '[ "$(echo "$out" | num image-only)" = 0 ]'
else
  echo "SKIP  9 (this file system does not tell twin.pdf from twin.PDF)"
fi

echo "=== 10 zero PDFs"
mkdir -p "$W/empty"; out=$(bash "$EX" "$W/empty" 2>&1); rc=$?
ok "10a aborts with exit 1" '[ $rc -eq 1 ] && echo "$out" | grep -q "ABORT"'

echo "=== 11 scan_intake.py amounts"
"$PY" - "$TREE" <<'EOP'
import sys, importlib.util
spec = importlib.util.spec_from_file_location('si', sys.argv[1] + '/scan_intake/scan_intake.py'); si = importlib.util.module_from_spec(spec); spec.loader.exec_module(si)
def g(k, t):
    return si.amount(k, t) or None
cases = [
 ('new_balance', 'New Balance 1,234.56', '1,234.56'),
 ('new_balance', 'New Balance $1,234.56', '1,234.56'),
 ('new_balance', 'New Balance: $0.00', '0.00'),
 ('new_balance', 'New Balance 5.00', '5.00'),
 ('new_balance', 'New Balance\n1,234.56', '1,234.56'),
 ('new_balance', 'New Balance\n$1,234.56', None),
 ('new_balance', 'New Balance' + ' ' * 40 + '$1,234.56', '1,234.56'),
 ('new_balance', 'New Balance (APR 21.99%) $1,234.56', '1,234.56'),
 ('new_balance', 'New Balance (APR 21.99 %) $1,234.56', '1,234.56'),
 ('new_balance', 'New Balance 21.99 % APR', None),
 ('new_balance', 'New Balance $1,234.56/Minimum Due $35.00', '1,234.56'),
 ('new_balance', 'New Balance Total ............1,234.56', None),
 ('new_balance', 'New Balance ........ $1,234.56', '1,234.56'),
 ('new_balance', 'New Balance 12/31 1,234.56', '1,234.56'),
 ('new_balance', 'New Balance   Minimum Payment Due\n$1,234.56   $25.00', None),
 ('min_due', 'New Balance   Minimum Payment Due\n$1,234.56   $25.00', None),
 ('min_due', 'Minimum Payment Due (includes 29.00 late fee) $64.00', '64.00'),
 ('min_due', 'Minimum Payment Due by 5.00 pm ET 02/10/2030 $35.00', '35.00'),
 ('min_due', 'New Balance $1,234.56/Minimum Due $35.00', '35.00'),
 ('new_balance', 'New Balance summary\nPage 2\nNew Balance $77.10', '77.10'),
 ('new_balance', 'New Balance on 15.01.2030 $500.00', '500.00'),
 ('new_balance', 'New Balance as of 01/15/2030 $1,234.56', '1,234.56'),
 ('new_balance', 'Previous Balance $100.00 New Balance 1,234.56 Minimum Payment Due $25.00', '1,234.56'),
 ('new_balance', 'New Balance 1,234.567', None),
 ('new_balance', 'New Balance none', None),
 ('new_balance', 'New Balance -$50.00', '50.00'),
 ('new_balance', 'New Balance' + ' ' * 40 + '1,234.56', '1,234.56'),
 ('new_balance', 'New Balance   Minimum Payment Due\n1,234.56   25.00', '1,234.56'),
 ('min_due', 'New Balance   Minimum Payment Due\n1,234.56   25.00', '1,234.56'),
 ('min_due', 'Minimum Payment Due 35.00', '35.00'),
 ('min_due', 'Minimum Due $35.00', '35.00'),
 ('min_due', 'Minimum Payment Due 1,035.00', '1,035.00'),
 ('min_due', 'Previous Balance $100.00 New Balance 1,234.56 Minimum Payment Due $25.00', '25.00'),
]
bad = 0
for k, t, want in cases:
    got = g(k, t)
    if got != want: bad += 1
    print(('  ok   ' if got == want else '  BAD  ') + '%-11s %-74r -> %r' % (k, t, got))
sys.exit(1 if bad else 0)
EOP
ok "11a every amount case" '[ $? -eq 0 ]'
D="$W/idx"; mkdir -p "$D"
printf 'Made-up issuer Chase\nPage 1 of 1\nAccount ending in 4321\nStatement Closing Date 01/15/2030\nNew Balance 1,234.56\nMinimum Payment Due 35.00\n' > "$D/typed.txt"
"$PY" "$TREE/scan_intake/scan_intake.py" index "$D" "$W/idx_out.csv" >/dev/null 2>&1
ok "11z index row: Chase,4321,01/15/2030,\"1,234.56\",35.00" 'grep -q "typed.txt,1,Chase,4321,01/15/2030,\"1,234.56\",35.00,1" "$W/idx_out.csv"'

echo
echo "TOTAL: pass $pass, fail $fail"
[ "$fail" -eq 0 ]
