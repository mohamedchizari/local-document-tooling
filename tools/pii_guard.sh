#!/bin/bash
# pii_guard.sh - fail if a tracked file carries one of four generic personal-data patterns:
#   a user home path (/Users/<name>, /home/<name>/), a hyphenated 3-2-4 digit ID, a run of 13 to 19 digits
#   inside one token (separators removed within the token only), or an email address that is not an
#   example.com/.org/.net address or a GitHub noreply address.
# It is a tripwire, not a clearance. It does not see names, street addresses, phone numbers, IDs written
# without hyphens, or prose that says too much, and it skips any line that carries the allow marker
# 'pii-guard: allow' (for deliberate test values). Read the diff as well.
#   usage: bash tools/pii_guard.sh      (run from anywhere; it checks the repo that contains it)
# The report names the file and the kind of hit, not the value. Needs: git.
cd "$(dirname "$0")/.." || exit 2
# Refuse to run unless this folder is itself the repo root (otherwise git climbs to a parent repo and scans that).
[ "$(git rev-parse --show-toplevel 2>/dev/null)" = "$(pwd -P)" ] || { echo "pii_guard: not a repo root: $(pwd -P)"; exit 2; }
hits=0
while IFS= read -r -d '' f; do
  case "$f" in *.png|*.jpg|*.pdf|*.zip) continue;; esac
  body=$(grep -v 'pii-guard: allow' "$f")
  # each match is tested on its own, so a placeholder on the same line does not hide a real path
  if printf "%s\n" "$body" | grep -oE '/Users/[A-Za-z][A-Za-z0-9._-]*|/home/[A-Za-z][A-Za-z0-9._-]*' | grep -vxE '/Users/(you|USER|Shared)|/home/(runner|you|user)' | grep -q .; then echo "  ^ home path in $f"; hits=1; fi
  if printf "%s\n" "$body" | grep -oE '[0-9]+(-[0-9]+)*' | grep -qxE '[0-9]{3}-[0-9]{2}-[0-9]{4}'; then echo "  ^ 3-2-4 ID-shaped number in $f"; hits=1; fi
  if printf "%s\n" "$body" | grep -oE '[0-9](([ -]?[0-9]){12,18})' | sed 's/[ -]//g' | grep -qE '^[0-9]{13,19}$'; then echo "  ^ long digit run in $f"; hits=1; fi
  if printf "%s\n" "$body" | grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' | grep -viE '@([a-z0-9-]+\.)*example\.(com|org|net)$|@users\.noreply\.github\.com$' | grep -q .; then echo "  ^ email address in $f"; hits=1; fi
done < <(git ls-files -z)
[ $hits -eq 0 ] && echo "pii_guard: clean" || { echo "pii_guard: FAILED"; exit 1; }
