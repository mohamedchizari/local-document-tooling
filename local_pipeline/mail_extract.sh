#!/bin/bash
# mail_extract.sh - list every message in the local Apple Mail store whose raw file contains a term,
# by reading the .emlx files themselves. Read-only.
#
#   usage: bash mail_extract.sh <search-term> <outdir>
#   e.g.:  bash mail_extract.sh example.org ~/mail_reports
#
# Why read the files and not only the index: Mail's "Envelope Index" is a metadata database, not the
# mail. A mailbox can look empty in the index while the messages sit in another mailbox's folder (with
# Gmail, sent mail usually lives under All Mail). Reading the .emlx files finds them.
#
# .partial.emlx files hold headers only: the body and attachments were never downloaded. A partial
# file proves a message exists and says nothing about what it carried, so they are counted separately.
#
# Limits: the match is on the raw bytes of each file, ignoring case. An address in a header is found.
# Text inside a base64 or quoted-printable body is not, and neither is anything in an attachment.
# The term may contain letters, digits and @ . _ + - only (it is also used in a file name and a query).
#
# The report lists senders, subjects and attachment names. Write it somewhere private.
#
# Environment:
#   MAIL_ROOT   mail store (default: the newest ~/Library/Mail/V* folder)
#   MAIL_KEY    text that marks the correspondent in To/Cc (default: the term); when To/Cc contains it
#               the row shows the recipients, otherwise the sender
# Needs: python3, the sqlite3 command-line tool, and Full Disk Access for the terminal.

set -uo pipefail
SEARCH="${1:-}"; OUT="${2:-}"
[ -n "$SEARCH" ] && [ -n "$OUT" ] || { echo "usage: bash mail_extract.sh <search-term> <outdir>"; exit 2; }
CLEAN="$(printf '%s' "$SEARCH" | tr -cd 'A-Za-z0-9@._+-')"
[ "$CLEAN" = "$SEARCH" ] || { echo "the term may contain only letters, digits and @ . _ + -   (got: $SEARCH)"; exit 2; }

# newest store version: the V<number> folder with the highest number
MAILROOT="${MAIL_ROOT:-$(ls -d "$HOME"/Library/Mail/V* 2>/dev/null | awk -F/ '{print substr($NF, 2) "\t" $0}' | sort -n | tail -1 | cut -f2-)}"
IDX="$MAILROOT/MailData/Envelope Index"
export MAIL_KEY="${MAIL_KEY:-$SEARCH}"

[ -f "$IDX" ] || { echo "FATAL: no Envelope Index at $IDX (the terminal needs Full Disk Access)"; exit 1; }
mkdir -p "$OUT"
REPORT="$OUT/mail_${SEARCH}_$(date +%Y-%m-%d).md"

echo "# Mail extract: '$SEARCH'" > "$REPORT"
echo "_Generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Read-only. Nothing sent, moved or marked read._" >> "$REPORT"

# ---- 1: the index --------------------------------------------------------
# mode=ro, not immutable=1: immutable ignores the -wal file and so misses the most recent mail.
echo "" >> "$REPORT"; echo "## 1. Envelope Index" >> "$REPORT"
if N=$(sqlite3 -readonly "file:${IDX}?mode=ro" "SELECT COUNT(*) FROM addresses WHERE address LIKE '%${SEARCH}%';" 2>/dev/null); then
  echo "address rows matching: $N" >> "$REPORT"
else
  echo "index query failed (is sqlite3 installed?)" >> "$REPORT"
fi

# ---- 2: the files --------------------------------------------------------
echo "" >> "$REPORT"; echo "## 2. .emlx files on disk" >> "$REPORT"
count_files() {
  local pattern="$1" n=0
  while IFS= read -r -d '' _mail_file; do n=$((n+1)); done \
    < <(find "$MAILROOT" -type f -name "$pattern" -print0 2>/dev/null)
  echo "$n"
}
TOTAL=$(count_files '*.emlx')
PARTIAL=$(count_files '*.partial.emlx')
echo "- store: **$TOTAL** .emlx, of which **$PARTIAL** are \`.partial\` (headers only)" >> "$REPORT"

# the store must be non-empty, or this sweep is broken rather than clean
if [ "$TOTAL" -eq 0 ]; then
  echo "ABORT: zero .emlx found. Broken sweep, not an empty mailbox." | tee -a "$REPORT"; exit 1
fi

echo "" >> "$REPORT"
echo "| date | from/to | subject | attachments | complete? |" >> "$REPORT"
echo "|---|---|---|---|---|" >> "$REPORT"

while IFS= read -r -d '' m; do
  if grep -qiF -e "$SEARCH" "$m" 2>/dev/null; then
  python3 - "$m" <<'PY' >> "$REPORT"
import email
import email.header
import os
import re
import sys

p = sys.argv[1]
key = os.environ.get('MAIL_KEY', '').lower()


def text(value, width):
    """A header as one line of readable text: encoded words decoded, folding and pipes removed."""
    value = str(value or '')
    try:
        value = str(email.header.make_header(email.header.decode_header(value or '')))
    except Exception:
        value = str(value or '')
    return re.sub(r'\s+', ' ', value).replace('|', '/').strip()[:width]


try:
    raw = open(p, 'rb').read()
    nl = raw.find(b'\n')                      # .emlx: a byte count line, then the RFC 822 message
    msg = email.message_from_bytes(raw[nl + 1:])
    to = str(msg.get('To') or '') + ' ' + str(msg.get('Cc') or '')   # include Cc: a message can reach someone only there
    who = to if key and key in to.lower() else str(msg.get('From') or '')
    # every part that has a file name, whatever its disposition: a real attachment can travel as an inline part
    att = [text(x.get_filename(), 40) for x in msg.walk() if x.get_filename()]
    comp = 'partial' if p.endswith('.partial.emlx') else 'full'
    print(f"| {text(msg.get('Date') or '?', 31)} | {text(who, 58)} | {text(msg.get('Subject'), 58)} | {', '.join(att) or '-'} | {comp} |")
except Exception:
    name = os.path.basename(p).replace('|', '/').replace('\r', ' ').replace('\n', ' ')
    print(f"| ? | ? | PARSE FAIL {name} | - | - |")
PY
  fi
done < <(find "$MAILROOT" -type f -name '*.emlx' -print0 2>/dev/null)

echo "" >> "$REPORT"
echo "**What this did not search:** encoded message bodies (base64, quoted-printable), attachments," >> "$REPORT"
echo "the bodies of \`.partial\` messages, the provider's web mailbox, and any account with no local" >> "$REPORT"
echo "copy. A report with no rows means \"not found in the raw local files\", not \"none\"." >> "$REPORT"

echo "Report: $REPORT"
