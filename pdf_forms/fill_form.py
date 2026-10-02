#!/usr/bin/env python3
"""fill_form.py - fill a PDF form from a JSON values file, widget by widget.

Usage: python3 fill_form.py blank.pdf values.json out.pdf

values.json is a list of {"page": 1, "field_id": "<field name, the widget's /T>", "value": "..."}.

Checkboxes and radio buttons: the value is the on-state name of the widget to select (for example
"/Yes" or "/2"), or "/Off". Widgets that share the field name but do not have that state are switched
off, so choosing one radio button clears the others in its group.

Text: wrapped for multi-line fields; for single-line fields the font size is reduced until the value
should fit, down to 5 pt. A value that still does not fit at 5 pt is listed as TOO LONG.

Prints the entries of the values file that matched no widget (for a button: no widget has that state;
nothing is changed for such an entry). Needs: pypdf.
"""
import json
import sys
import textwrap

from pypdf import PdfReader, PdfWriter
from pypdf.generic import IndirectObject, NameObject, TextStringObject

MIN_SIZE = 5


def res(o):
    return o.get_object() if isinstance(o, IndirectObject) else o


def inherited(widget, key, default=None):
    """A widget that is a kid of a field keeps /FT, /Ff, /DA and /V on the parent."""
    node = widget
    for _ in range(8):
        if key in node:
            return node[key]
        if '/Parent' not in node:
            break
        node = res(node['/Parent'])
    return default


def field_name(widget):
    return str(widget.get('/T') or (res(widget['/Parent']).get('/T') if '/Parent' in widget else '') or '')


def on_states(widget):
    ap = res(widget.get('/AP'))
    return [str(s) for s in res(ap['/N']).keys() if str(s) != '/Off'] if ap and '/N' in ap else []


def fill(inp, valuesfile, outp, single=8, multi=7):
    vals = json.load(open(valuesfile))
    w = PdfWriter(clone_from=PdfReader(inp))
    want = {}
    for v in vals:
        want.setdefault(v['page'], {})[v['field_id']] = v['value']
    matched, too_long = set(), []

    for pi, page in enumerate(w.pages, 1):
        pv = want.get(pi, {})
        textvals = {}
        # the on-states that exist for each button field on this page, across all of its widgets
        states_of = {}
        for a in res(page.get('/Annots')) or []:
            a = res(a)
            if a.get('/Subtype') == '/Widget' and inherited(a, '/FT') == '/Btn':
                states_of.setdefault(field_name(a), set()).update(on_states(a))
        for a in res(page.get('/Annots')) or []:
            a = res(a)
            if a.get('/Subtype') != '/Widget':
                continue
            parent = res(a['/Parent']) if '/Parent' in a else None
            nm = field_name(a)
            if nm not in pv:
                continue
            val = pv[nm]
            ft = inherited(a, '/FT')
            if ft == '/Btn':
                holder = parent if parent is not None and '/T' not in a else a
                if val != '/Off' and val not in states_of.get(nm, ()):
                    continue        # not a state of any widget of this field: change nothing; reported as MISSING
                if val in on_states(a):
                    a[NameObject('/AS')] = NameObject(val)
                    holder[NameObject('/V')] = NameObject(val)
                else:
                    # "/Off", or the on-state of another widget in the same group: this widget goes off
                    a[NameObject('/AS')] = NameObject('/Off')
                    if val == '/Off':
                        holder[NameObject('/V')] = NameObject('/Off')
                matched.add((pi, nm))
            else:
                multiline = int(inherited(a, '/Ff', 0)) & 4096
                rect = [float(x) for x in res(a['/Rect'])]
                width = rect[2] - rect[0]
                fs = multi if multiline else single
                val = str(val)
                if multiline:
                    cpl = max(20, int(width / (fs * 0.48)))
                    lines = []
                    for para in val.split('\n'):
                        lines += textwrap.wrap(para, cpl) or ['']
                    val = '\n'.join(lines)
                else:
                    cpl = max(1, int(width / (fs * 0.56)))
                    if len(val) > cpl:
                        fs = int(fs * cpl / len(val))
                        if fs < MIN_SIZE:
                            fs = MIN_SIZE
                            too_long.append((pi, nm))
                a[NameObject('/DA')] = TextStringObject(f'/Helv {fs} Tf 0 g')
                textvals[nm] = val
                matched.add((pi, nm))
        if textvals:
            w.update_page_form_field_values(page, textvals, auto_regenerate=True)

    w.set_need_appearances_writer(True)
    with open(outp, 'wb') as fh:
        w.write(fh)
    miss = [(p, k) for p in want for k in want[p] if (p, k) not in matched]
    print('MISSING', miss) if miss else print('all', len(vals), 'entries matched a widget')
    if too_long:
        print('TOO LONG at', MIN_SIZE, 'pt:', too_long)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    fill(*sys.argv[1:4])
