#!/usr/bin/env python3
"""scan_intake.py - zero-token intake for a large stack of paper statements.

Three steps, each re-runnable, none calls a language model:

  collate  FRONTS.pdf BACKS.pdf OUT.pdf [--backs-forward]
      Interleave a one-sided scan of the fronts with a one-sided scan of the backs.
      Default assumes you flipped the whole stack and fed it again, so the backs come out
      LAST-PAGE-FIRST (reversed). Use --backs-forward if your scanner kept the order.
      Refuses if the page counts differ (a double-feed or a jam shows up here, not later).

  ocr      IN.pdf [IN2.pdf ...]
      Runs `ocrmypdf --skip-text` (writes IN.ocr.pdf) and a text sidecar IN.txt with one
      form-feed per page. Returns nonzero if any input fails. Needs ocrmypdf on PATH. These two
      files hold the full text of the statements, account numbers included: keep them with the scans.

  index    DIR  OUT.csv  [--issuers issuers.txt]
      Reads every *.txt sidecar in DIR, finds statement first-pages, and writes one CSV row per
      statement: file, first_page, issuer, last4, closing_date, new_balance, min_due, pages.
      Pages with < 25 characters are counted as blank (the backs of most statements) and listed
      in a second CSV (OUT_blank_pages.csv) so they can be dropped. A count by issuer, last four and
      year prints at the end.

The index CSV holds only the last four digits of an account number.
Needs: pypdf for collate, ocrmypdf for ocr.
"""
import sys, os, re, csv, subprocess, collections


def collate(fronts, backs, out, backs_forward=False):
    from pypdf import PdfReader, PdfWriter
    f, b = PdfReader(fronts).pages, list(PdfReader(backs).pages)
    if len(f) != len(b):
        sys.exit(f'REFUSED: {len(f)} fronts vs {len(b)} backs - rescan the batch (double-feed or jam?)')
    if not backs_forward: b.reverse()
    w = PdfWriter()
    for x, y in zip(f, b): w.add_page(x); w.add_page(y)
    with open(out, 'wb') as fh: w.write(fh)
    print(f'{out}: {2*len(f)} pages ({len(f)} sheets), backs {"forward" if backs_forward else "reversed"}')

def ocr(paths):
    failed = 0
    for p in paths:
        base = os.path.splitext(p)[0]
        r = subprocess.run(['ocrmypdf', '--skip-text', '--sidecar', base + '.txt', '-q', p, base + '.ocr.pdf'])
        print(p, 'ocr exit', r.returncode)
        failed += r.returncode != 0
    return 1 if failed else 0

MONTHS = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
DATE = r'(?:\d{1,2}/\d{1,2}/\d{2,4}|(?:' + MONTHS + r')[a-z]*\.? \d{1,2},? \d{4})'
RX = {
 'closing_line': re.compile(r'(Closing Date|Statement (?:Closing )?Date|Billing Period)([^\n]{0,80})', re.I),
 'first_page': re.compile(r'(?:Page 1 of \d+|Payment Due Date|New Balance)', re.I),
 # used only to recognise a first page; amount() below reads the figure
 'balance_line': re.compile(r'New Balance[^\n$]{0,30}\$?\s*[\d,]+\.\d{2}', re.I),
}

# Amounts. A signed amount is a currency sign, then digits and commas, a point and two digits; a minus
# directly in front of the currency sign makes it negative. An unsigned amount is negative only when a
# minus is attached to its first digit: "New Balance - 50.00" reads the hyphen as a separator (50.00).
# An unsigned one has no sign to mark it, so it is guarded: it may not start inside another number
# or directly after a point or a slash, and it may not be followed by a digit, a slash, a percent sign
# (directly or after one white-space character) or a point and a digit. A rate ("21.99%") or a dotted date ("15.01.2030") is
# then not taken for an amount. A date written "15.01." with nothing after the last point still is.
SIGNED = r'(-?\$\s*\d[\d,]*\.\d{2})(?!\d)'
UNSIGNED = r'(?<![\d.,/-])(-?\d[\d,]*\.\d{2})(?![\d/]|\s?%|\.\d)'
LABEL = {
 'new_balance': re.compile(r'New Balance', re.I),
 'min_due': re.compile(r'Minimum (?:Payment )?Due', re.I),
}
# What may follow a label, tried in this order at each place the label occurs:
#   1. a signed amount directly after it, on the same line
#   2. an unsigned amount directly after it, with only white space or colons between, on the same
#      line or a line below
#   3. a signed amount after up to 30 characters of other text on the label's line
#   4. the nearest unsigned amount after up to 30 characters of other text on the label's line and
#      any white space after that, line breaks included
#      (the filler is lazy: a greedy one eats all but the last digit before the point)
AFTER_LABEL = [re.compile(x) for x in (
    r'[ \t:]*' + SIGNED,
    r'[\s:]*' + UNSIGNED,
    r'[^\n$]{0,30}' + SIGNED,
    r'[^\n$]{0,30}?\s*' + UNSIGNED,
)]


def amount(key, t):
    """The amount that goes with a label ('new_balance' or 'min_due'), or '' if none is found."""
    for m in LABEL[key].finditer(t):
        for rx in AFTER_LABEL:
            a = rx.match(t, m.end())
            if a:
                return ''.join(a.group(1).replace('$', '').split())
    return ''


# The last four digits of the account, tried in this order:
#   1. "Account ending in 1234", "Card number ending: 1234" (the word "ending" directly after the label)
#   2. a masked number after "Account" or "Account Number", on the same line or the next: "XXXX XXXX XXXX 1234"
#   3. a 4-4-4-4 number after the same label: the last group, and only when no fifth group follows
LAST4 = [
    re.compile(r'(?:account|card)(?: number| no\.?)?[ \t:#]*ending(?: in)?[ \t:]*(\d{4})\b', re.I),
    re.compile(r'Account(?: Number)?[ \t]*[:#]?[ \t]*\n?[ \t]*[Xx*\u2022][Xx*\u2022 -]{3,}[ \t]*(\d{4})\b', re.I),
    re.compile(r'Account(?: Number)?[ \t]*[:#]?[ \t]*\n?[ \t]*\d{4}[ -]\d{4}[ -]\d{4}[ -](\d{4})\b(?![ -]\d{4}\b)', re.I),
]


def last4(t):
    for rx in LAST4:
        m = rx.search(t)
        if m:
            return m.group(1)
    return ''


def closing_date(t):
    """The statement's closing date. A "Billing Period: start - end" line gives the end date."""
    for m in RX['closing_line'].finditer(t):
        dates = re.findall(DATE, m.group(2), re.I)
        if dates:
            return dates[-1] if m.group(1).lower().startswith('billing') else dates[0]
    return ''


# A starter list of large US card issuers. Pass --issuers FILE (one name per line) to use your own.
DEFAULT_ISSUERS = ['American Express', 'Bank of America', 'Barclays', 'Capital One', 'Chase', 'Citi', 'Discover',
                   'Goldman Sachs', 'Synchrony', 'U.S. Bank', 'Wells Fargo']

def index(d, out, issuers_file=None):
    issuers = [l.strip() for l in open(issuers_file) if l.strip()] if issuers_file else DEFAULT_ISSUERS
    rows, blanks = [], []
    for fn in sorted(x for x in os.listdir(d) if x.endswith('.txt')):
        pages = open(os.path.join(d, fn), errors='replace').read().split('\f')
        cur = None
        for i, t in enumerate(pages, 1):
            if len(t.strip()) < 25: blanks.append((fn, i)); continue
            if RX['first_page'].search(t) and (closing_date(t) or RX['balance_line'].search(t)):
                if cur: rows.append(cur)
                iss = next((s for s in issuers if re.search(r'\b' + re.escape(s) + r'\b', t, re.I)), '')
                cur = dict(file=fn, first_page=i, issuer=iss, last4=last4(t), closing_date=closing_date(t),
                           new_balance=amount('new_balance', t), min_due=amount('min_due', t), pages=1)
            elif cur: cur['pages'] += 1
        if cur: rows.append(cur)
    with open(out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['file', 'first_page', 'issuer', 'last4', 'closing_date', 'new_balance', 'min_due', 'pages'])
        w.writeheader(); w.writerows(rows)
    with open(os.path.splitext(out)[0] + '_blank_pages.csv', 'w', newline='') as fh:
        csv.writer(fh).writerows([('file', 'page')] + blanks)
    print(f'{len(rows)} statements, {len(blanks)} blank pages -> {out}')
    piv = collections.Counter((r['issuer'] or '?', r['last4'] or '?', (re.search(r'(\d{4})$', r['closing_date']) or re.search(r'/(\d{2})$', r['closing_date']) or [None, '?'])[1]) for r in rows)
    for k, n in sorted(piv.items()): print('  %-18s ...%-4s %-4s %d' % (k[0], k[1], k[2], n))
    unk = sum(1 for r in rows if not r['issuer'] or not r['last4'] or not r['closing_date'])
    print(f'  rows missing issuer/last4/date: {unk} - these are the only pages someone needs to look at')

if __name__ == '__main__':
    args = sys.argv[1:]
    pos = [x for x in args if not x.startswith('--')]
    flags = [x for x in args if x.startswith('--')]
    cmd = pos[0] if pos else ''
    if cmd == 'collate' and len(pos) == 4 and set(flags) <= {'--backs-forward'}:
        collate(pos[1], pos[2], pos[3], '--backs-forward' in flags)
    elif cmd == 'ocr' and len(pos) >= 2 and not flags:
        sys.exit(ocr(pos[1:]))
    elif cmd == 'index' and len(pos) == 3 and not flags:
        index(pos[1], pos[2])
    elif cmd == 'index' and len(pos) == 4 and flags == ['--issuers'] and args.index('--issuers') == len(args) - 2:
        index(pos[1], pos[2], pos[3])
    else:
        sys.exit(__doc__)
