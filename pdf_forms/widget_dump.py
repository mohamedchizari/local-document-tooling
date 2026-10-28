#!/usr/bin/env python3
"""widget_dump.py - list every form widget in a PDF: page, field name, position, the printed label to
its left, the text just above it, its value and, for buttons, its appearance state.

It walks the widgets on each page rather than the field tree, so two widgets of one field show up as
two rows, each with its own state.

Usage: python3 widget_dump.py form.pdf [more.pdf ...]
       WIDGET_VALUE_CONTAINS=<text> python3 widget_dump.py form.pdf     (only widgets whose value contains the text)
Needs: pypdf, and pdftotext (poppler) on PATH for the labels. A file pdftotext cannot read is skipped
with a warning; the others are still listed, and the exit status is 1 if any file was skipped.
"""
import html
import os
import re
import subprocess
import sys

from pypdf import PdfReader

NEEDLE = os.environ.get('WIDGET_VALUE_CONTAINS', '')
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')


def inherited(widget, key, default=None):
    """A widget that is a kid of a field keeps /T and /V on the parent."""
    node = widget
    for _ in range(8):
        if key in node:
            return node[key]
        if '/Parent' not in node:
            break
        node = node['/Parent'].get_object()
    return default


def dump(path):
    reader = PdfReader(path)
    result = subprocess.run(['pdftotext', '-bbox', path, '-'], capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or f'exit status {result.returncode}'
        print(f"WARNING: pdftotext failed for {path}: {detail}; skipped", file=sys.stderr)
        return False
    xml = result.stdout
    pages = xml.split('<page ')[1:]
    print('#####', path, len(reader.pages), 'pp')
    for pi, page in enumerate(reader.pages, 1):
        pg = pages[pi - 1] if pi <= len(pages) else ''
        hm = re.search(r'height="([\d.]+)"', pg)
        height = float(hm.group(1)) if hm else float(page.mediabox.height)
        words = [(float(m.group(2)), float(m.group(1)), html.unescape(m.group(5))) for m in WORD.finditer(pg)]
        by_x = sorted(words, key=lambda t: t[1])
        for a in page.get('/Annots') or []:
            a = a.get_object()
            if a.get('/Subtype') != '/Widget':
                continue
            v = str(inherited(a, '/V', ''))
            if NEEDLE and NEEDLE not in v:
                continue
            x0, y0, x1, y1 = [float(x) for x in a['/Rect']]
            cy = height - (y0 + y1) / 2
            label = ' '.join(w for (wy, wx, w) in by_x if abs(wy + 4 - cy) < 7 and wx < x0)
            above = ' '.join(w for (wy, wx, w) in by_x if 8 <= (cy - (wy + 4)) < 20 and x0 - 20 < wx < x1)
            state = f" | AS: {a['/AS']}" if '/AS' in a else ''
            print(f"p{pi} [{inherited(a, '/T')}] {round(x0)},{round(y0)} w{round(x1 - x0)} | L: {label[-55:]} | A: {above[:45]} | V: {v[:60]}{state}")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ok = [dump(f) for f in sys.argv[1:]]
    # every file is tried; the exit status says whether any was skipped
    sys.exit(0 if all(ok) else 1)
