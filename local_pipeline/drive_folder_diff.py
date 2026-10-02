#!/usr/bin/env python3
"""drive_folder_diff.py - what exists only in a synced folder, only in a local folder, or in both.

Usage:
  python3 drive_folder_diff.py --drive <synced-folder> --folder <local-folder> --out <report-dir> [--md5] [--skip NAME ...]

Files are keyed by (basename, size). With --md5, pairs that share a key are hashed and sorted into
same / differ. Without it, a shared key counts as the same file.

Not compared: dot-files, dot-directories, .git, __pycache__, node_modules, .Trash, cloud placeholder files
(.icloud, .gdoc, .gsheet, .gslides: they are links, not the document), and any directory named with --skip
(use --skip for a copy of one tree kept inside the other, or it will match itself). A document that exists
only as a cloud placeholder is therefore not reported.

Writes drive_only.tsv, folder_only.tsv, same.tsv, differ.tsv and SUMMARY.md into --out.
Read-only on both trees.
"""
import argparse
import datetime
import hashlib
import os
import subprocess

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.Trash'}
PLACEHOLDER_SUFFIXES = ('.icloud', '.gdoc', '.gsheet', '.gslides')


def walk(root, skip):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip and not d.startswith('.')]
        for f in fn:
            if f.startswith('.') or f.endswith(PLACEHOLDER_SUFFIXES):
                continue
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.setdefault((f, st.st_size), []).append(os.path.relpath(p, root))
    return out


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def stamp():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'stamp.sh')
    try:
        out = subprocess.run(['bash', script], capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        out = ''
    return out or datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M UTC %Y-%m-%d (local clock)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--drive', required=True)
    ap.add_argument('--folder', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--md5', action='store_true', help='hash pairs that share a name and size (slower)')
    ap.add_argument('--skip', nargs='*', default=[], help='extra directory names to skip')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    skip = SKIP_DIRS | set(a.skip)

    D = walk(a.drive, skip)
    F = walk(a.folder, skip)
    donly = sorted(set(D) - set(F))
    fonly = sorted(set(F) - set(D))
    same, differ = [], []
    for k in sorted(set(D) & set(F)):
        if a.md5:
            hd = {md5(os.path.join(a.drive, p)) for p in D[k]}
            hf = {md5(os.path.join(a.folder, p)) for p in F[k]}
            (same if hd & hf else differ).append(k)
        else:
            same.append(k)

    def dump(name, keys, src):
        with open(os.path.join(a.out, name), 'w') as fh:
            fh.write('name\tbytes\tpaths\n')
            for k in keys:
                fh.write(f'{k[0]}\t{k[1]}\t{" | ".join(src[k])}\n')

    dump('drive_only.tsv', donly, D)
    dump('folder_only.tsv', fonly, F)
    dump('same.tsv', same, D)
    dump('differ.tsv', differ, D)

    summary = os.path.join(a.out, 'SUMMARY.md')
    with open(summary, 'w') as fh:
        fh.write(
            f"# Synced folder vs local folder, {stamp()}\n\n"
            f"Synced root: {a.drive} ({sum(len(v) for v in D.values())} files, {len(D)} distinct name+size)\n"
            f"Local root: {a.folder} ({sum(len(v) for v in F.values())} files, {len(F)} distinct name+size)\n\n"
            "| set | count | bytes |\n|---|---|---|\n"
            f"| synced only | {len(donly)} | {sum(k[1] for k in donly):,} |\n"
            f"| local only | {len(fonly)} | {sum(k[1] for k in fonly):,} |\n"
            f"| in both, same | {len(same)} | |\n"
            f"| in both, differ (md5) | {len(differ)} | |\n\n"
            f"Key = basename + byte size ({'md5 on shared keys' if a.md5 else 'no md5; pass --md5 to verify'}). "
            "A file moved to another directory still matches; a renamed file does not. Two different files with the same name and size are told apart only with --md5.\n")
    print(open(summary).read())


if __name__ == '__main__':
    main()
