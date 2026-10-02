#!/usr/bin/env python3
"""check_field_fit.py - after filling a PDF form, report every text field whose value does not fit its box.

Single-line fields: the value's width at the field's font size against the box width.
Multi-line fields: the number of wrapped lines against the box height.

The font size is read from the field's /DA string, whatever font it names. Widths are measured in
Helvetica, so the result is an estimate for other fonts. A size of 0 (auto) or a missing /DA is
measured as 8 pt.

Usage: python3 check_field_fit.py filled.pdf [more.pdf ...]
Exit status: 0 no overflow, 1 at least one overflow. Needs: pypdf, reportlab.
"""
import re
import sys

from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth

AUTO_SIZE = 8


def inherited(widget, key, default=None):
    """A widget that is a kid of a field keeps /FT, /Ff, /DA and /V on the parent."""
    node = widget
    for _ in range(8):
        if key in node:
            return node[key]
        if '/Parent' not in node:
            break
        node = node['/Parent'].get_object()
    return default


def font_size(da):
    m = re.search(r'/\S+\s+([\d.]+)\s+Tf', str(da or ''))
    size = float(m.group(1)) if m else 0
    return size if size > 0 else AUTO_SIZE


def lines_needed(value, width, size):
    """Lines the value takes when wrapped at spaces; a word wider than the box counts for every line it spills over."""
    need = 0
    for para in value.split('\n'):
        cur = ''
        for word in para.split(' '):
            t = (cur + ' ' + word).strip()
            if cur and stringWidth(t, 'Helvetica', size) > width:
                need += 1
                cur = word
            else:
                cur = t
            spill = int(stringWidth(word, 'Helvetica', size) // width) if width > 0 else 0
            if spill:
                need += spill
                cur = ''
        need += 1
    return need


def check(path):
    bad = n = 0
    for pi, page in enumerate(PdfReader(path).pages, 1):
        for a in page.get('/Annots') or []:
            a = a.get_object()
            if a.get('/Subtype') != '/Widget' or inherited(a, '/FT') != '/Tx':
                continue
            v = str(inherited(a, '/V', ''))
            if not v.strip():
                continue
            n += 1
            x0, y0, x1, y1 = [float(x) for x in a['/Rect']]
            w, h = x1 - x0 - 4, y1 - y0
            fs = font_size(inherited(a, '/DA'))
            name = inherited(a, '/T')
            if int(inherited(a, '/Ff', 0)) & 4096:
                need = lines_needed(v, w, fs)
                if need * fs * 1.15 > h + 1:
                    bad += 1
                    print(f'  OVERFLOW-H p{pi} [{name}] {need} lines at {fs} pt = {round(need * fs * 1.15)} > height {round(h)} :: {v[:70]!r}')
            else:
                sw = stringWidth(v, 'Helvetica', fs)
                if sw > w:
                    bad += 1
                    print(f'  OVERFLOW-W p{pi} [{name}] {round(sw)} > width {round(w)} at {fs} pt :: {v[:70]!r}')
    print(f'{path}: {n} filled text fields, {bad} overflow')
    return bad


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(1 if sum(check(f) for f in sys.argv[1:]) else 0)
