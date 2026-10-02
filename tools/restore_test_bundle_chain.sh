#!/bin/bash
# restore_test_bundle_chain.sh - does a backup made of `git bundle` files actually restore to today's commit?
#
# Why: `git bundle verify`, run inside the live repo, only asks whether a bundle's prerequisite commits exist in
# that repo, and they always do. So a chain of one full bundle plus many incremental bundles can have a hole (one
# commit that was never bundled) while every bundle still verifies, and nothing after the hole can be restored.
# A bundle that verifies is not a backup that restores. This script runs the restore.
#
# What it does (read-only on the backup folder and on the repo): clones the newest full bundle into a scratch folder,
# applies every incremental whose prerequisites are present (whatever ref name it carries, HEAD or a branch), repeats
# until the tip stops moving, and compares the tip it reached with the live branch tip. Prints one RESULT line and,
# when the chain is short, the one command that bridges the gap.
#
# Usage:  REPO=/path/to/repo BACKUP_DIR="/path/to/synced/backups" bash restore_test_bundle_chain.sh
# Optional: BRANCH (default: the branch checked out in REPO)   SCRATCH (default: $TMPDIR or /tmp)
#           FULL_GLOB='*UTC.bundle'  INC_GLOB='*INCREMENTAL*.bundle'   file name patterns for the two kinds of bundle.
#           The defaults fit full bundles named like backup_repo_bundle.sh names them and incrementals whose name
#           contains INCREMENTAL, made with:  git bundle create <name> <old-tip>..<branch>
# Exit status: 0 restores to the live tip; 1 broken or behind; 2 could not run the test (no full bundle, no branch).
# Needs: git.
set -u
REPO="${REPO:?set REPO to the repo path}"; D="${BACKUP_DIR:?set BACKUP_DIR to the folder holding the bundles}"
BRANCH="${BRANCH:-$(git -C "$REPO" symbolic-ref --quiet --short HEAD 2>/dev/null || echo main)}"; FULL_GLOB="${FULL_GLOB:-*UTC.bundle}"; INC_GLOB="${INC_GLOB:-*INCREMENTAL*.bundle}"
T="$(mktemp -d "${SCRATCH:-${TMPDIR:-/tmp}}/restore_test_$(date '+%Y-%m-%d_%H%M%S').XXXXXX")" || { echo "RESULT: NO SCRATCH FOLDER"; exit 2; }; G="$T/repo.git"
full=$(ls -t "$D"/$FULL_GLOB 2>/dev/null | grep -v -e "INCREMENTAL" | head -1)
[ -n "$full" ] || { echo "RESULT: NO FULL BUNDLE FOUND in $D (pattern $FULL_GLOB)"; exit 2; }
echo "full bundle: $(basename "$full")"
git clone --quiet --bare "$full" "$G" || { echo "RESULT: THE FULL BUNDLE DOES NOT CLONE"; exit 2; }
tip=$(git -C "$G" rev-parse --verify -q "refs/heads/$BRANCH" || git -C "$G" rev-parse --verify -q HEAD) || { echo "RESULT: THE FULL BUNDLE HAS NO USABLE TIP"; exit 2; }
ls -tr "$D"/$INC_GLOB 2>/dev/null > "$T/inc.txt"; pass=0; used=0
while :; do
  pass=$((pass+1)); moved=0
  while IFS= read -r b; do
    [ -f "$T/ok_$(basename "$b")" ] && continue
    git -C "$G" bundle verify "$b" >/dev/null 2>&1 || continue      # prerequisites not here yet; try again next pass
    while read -r sha ref; do
      git -C "$G" fetch --quiet "$b" "$ref" 2>/dev/null || continue
      if [ "$sha" != "$tip" ] && git -C "$G" merge-base --is-ancestor "$tip" "$sha" 2>/dev/null; then
        git -C "$G" update-ref "refs/heads/$BRANCH" "$sha"; tip=$sha; moved=1; used=$((used+1))
      fi
    done < <(git bundle list-heads "$b" 2>/dev/null)
    : > "$T/ok_$(basename "$b")"
  done < "$T/inc.txt"
  [ "$moved" = 1 ] && [ "$pass" -lt 50 ] || break
done
live=$(git -C "$REPO" rev-parse --verify -q "refs/heads/$BRANCH") || { echo "RESULT: NO BRANCH $BRANCH IN $REPO (set BRANCH)"; exit 2; }
echo "incrementals found: $(wc -l < "$T/inc.txt" | tr -d ' ') | moved the tip: $used | restored tip: $(git -C "$G" rev-parse --short=9 "$tip") | live tip: $(git -C "$REPO" rev-parse --short=9 "$live")"
echo "scratch clone left at $T (remove it when you have looked at it)"
if [ "$tip" = "$live" ]; then
  echo "RESULT: OK, the backup restores to the live tip ($(git -C "$G" ls-tree -r --name-only "$tip" | wc -l | tr -d ' ') files)"; exit 0
fi
s_tip=$(git -C "$REPO" rev-parse --short=8 "$tip" 2>/dev/null); s_live=$(git -C "$REPO" rev-parse --short=8 "$live")
echo "RESULT: BROKEN OR BEHIND, $(git -C "$REPO" rev-list --count "$tip..$live" 2>/dev/null || echo '?') commits after the restored tip are not in the backup."
echo "bridge it:  git -C \"$REPO\" bundle create \"$D/INCREMENTAL_${s_tip}..${s_live}_BRIDGE.bundle\" ${s_tip}..$BRANCH   # then run this test again"
exit 1
