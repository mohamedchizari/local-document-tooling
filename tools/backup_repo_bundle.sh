#!/bin/bash
# backup_repo_bundle.sh - back up a git repo as one restorable `git bundle` (full history, all refs),
# prove that it restores, copy it to a backup folder and check the copy by checksum.
#
#   usage: REPO=/path/to/repo BACKUP_DEST=/path/to/backup/folder bash tools/backup_repo_bundle.sh
#   REPO must be the top folder of a work tree (a linked worktree is fine); a subfolder or a .git folder is refused.
#   SKIP_RESTORE=1 skips the restore test (a large repo can take minutes); the checksum check still runs.
#
# BACKUP_DEST can be any folder, for example one that a sync client uploads. If it is, the bundle
# (your whole history) leaves the machine: that is the point of a backup, but choose the folder knowingly.
# Keep bundles out of the repo they back up.
# A bundle covers committed work only; the script lists uncommitted paths at the end.
# Exit status: 0 backup written and verified; 1 anything else.
# Needs: git, and md5sum or md5.
set -u
REPO="${REPO:?set REPO to the repo path}"
DEST="${BACKUP_DEST:?set BACKUP_DEST to the backup folder}"
[ -d "$REPO" ] || { echo "FAIL: $REPO is not a folder"; exit 1; }
REPO="$(cd "$REPO" && pwd -P)" || exit 1
# Only the top folder of a work tree: from a subfolder or from .git, git would bundle the whole parent repo.
[ "$(git -C "$REPO" rev-parse --is-inside-work-tree 2>/dev/null)" = "true" ] \
  && [ "$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)" = "$REPO" ] \
  || { echo "FAIL: $REPO is not the top folder of a git work tree"; exit 1; }
[ -d "$DEST" ]      || { echo "FAIL: backup folder not found: $DEST"; exit 1; }

sum() {  # checksum with whichever tool this system has
  if command -v md5sum >/dev/null; then md5sum "$1" | awk '{print $1}'; else md5 -q "$1"; fi
}

STAMP="$(date -u +%Y-%m-%d_%H%M%S)UTC"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/repo_bundle.XXXXXX")" || exit 1
trap 'rm -rf "$WORK"' EXIT
TMP="$WORK/repo_${STAMP}.bundle"
OUT="$DEST/repo_${STAMP}.bundle"

echo "==> bundling $(git -C "$REPO" rev-list --count HEAD) commits"
git -C "$REPO" bundle create "$TMP" --all || { echo "FAIL: git bundle create"; exit 1; }

if [ "${SKIP_RESTORE:-0}" = "1" ]; then
  echo "==> restore test skipped (SKIP_RESTORE=1)"
else
  # A bundle that exists is not a bundle that works: clone it before trusting it.
  echo "==> restore test"
  git clone -q "$TMP" "$WORK/restore" || { echo "FAIL: the bundle does not clone"; exit 1; }
  N=$(git -C "$WORK/restore" rev-list --count HEAD)
  F=$(git -C "$WORK/restore" ls-files | wc -l | tr -d ' ')
  echo "    restored $N commits, $F files"
  [ "$N" -gt 0 ] || { echo "FAIL: the bundle restored 0 commits"; exit 1; }
fi

echo "==> copying to $DEST"
cp "$TMP" "$OUT" || { echo "FAIL: copy"; exit 1; }
SRC=$(sum "$TMP"); DST=$(sum "$OUT")
if [ "$SRC" = "$DST" ]; then
  echo "    OK  $(wc -c < "$OUT" | tr -d ' ') bytes  checksum $DST"
else
  echo "    MISMATCH: source $SRC, copy $DST"; exit 1
fi

echo
echo "To restore:  git clone \"$OUT\" <restore-path>"
U=$(git -C "$REPO" status --porcelain | wc -l | tr -d ' ')
if [ "$U" -gt 0 ]; then
  echo "NOTE: $U uncommitted path(s) are not in this bundle. Commit first if they matter:"
  git -C "$REPO" status --porcelain | head -5
fi
exit 0
