#!/usr/bin/env python3
"""scam_sweep.py - phishing and lookalike-sender sweep over the Apple Mail Envelope Index. Read-only.

Scores every received message (sender address, display name, subject) on cheap signals, then opens
the headers of the top hits that are not already in Junk for a Reply-To mismatch and SPF/DKIM/DMARC results.

Usage:
  python3 scam_sweep.py --out <report-dir> [--since 2025-01-01] [--mail-root ~/Library/Mail/V10] [--brands brands.json]

Writes candidates.tsv, senders.tsv and headers_top_not_in_junk.tsv into --out.
Never moves, labels or deletes mail. The terminal needs Full Disk Access to read the mail store.

--brands points at a JSON object {"brand name": ["domain.com", ...]} that replaces the built-in list.
List every domain a brand really sends from, country domains included; anything else counts as off-domain.
Needs: Python 3.9+ only.
"""
import argparse
import collections
import csv
import datetime
import glob
import json
import os
import re
import sqlite3
import sys

# Widely impersonated brands and the domains their real mail comes from. Extend or replace with --brands.
BRAND_DOMAINS = {
    'paypal': ['paypal.com'], 'chase': ['chase.com', 'jpmorgan.com', 'jpmchase.com'], 'wells fargo': ['wellsfargo.com'],
    'american express': ['americanexpress.com', 'aexp.com'], 'amex': ['americanexpress.com', 'aexp.com'],
    'citi': ['citi.com', 'citibank.com', 'citicards.com'], 'capital one': ['capitalone.com'],
    'bank of america': ['bankofamerica.com'], 'discover': ['discover.com'],
    'apple': ['apple.com', 'icloud.com'], 'icloud': ['apple.com', 'icloud.com'],
    'microsoft': ['microsoft.com', 'microsoftonline.com'], 'outlook': ['microsoft.com', 'outlook.com', 'live.com'],
    'google': ['google.com', 'googlemail.com'], 'gmail': ['google.com', 'gmail.com'],
    'amazon': ['amazon.com', 'amazonses.com', 'amazon.ca', 'amazon.co.uk', 'amazon.de', 'amazon.fr', 'amazon.it', 'amazon.es',
               'amazon.nl', 'amazon.in', 'amazon.co.jp', 'amazon.com.au', 'amazon.com.mx', 'amazon.com.br'], 'netflix': ['netflix.com'],
    'usps': ['usps.com', 'usps.gov'], 'ups': ['ups.com'], 'fedex': ['fedex.com'], 'dhl': ['dhl.com'],
    'irs': ['irs.gov'], 'social security': ['ssa.gov'],
    'norton': ['norton.com', 'nortonlifelock.com', 'gendigital.com'], 'mcafee': ['mcafee.com'],
    'geek squad': ['bestbuy.com'], 'best buy': ['bestbuy.com'],
    'docusign': ['docusign.net', 'docusign.com'], 'quickbooks': ['intuit.com'], 'intuit': ['intuit.com'],
    'zelle': ['zellepay.com'], 'venmo': ['venmo.com'], 'coinbase': ['coinbase.com'], 'linkedin': ['linkedin.com'],
    'experian': ['experian.com'], 'equifax': ['equifax.com'], 'transunion': ['transunion.com'],
    'att': ['att.com', 'att-mail.com', 'att.net'], 'verizon': ['verizon.com', 'verizonwireless.com'], 't-mobile': ['t-mobile.com'],
    'costco': ['costco.com'], 'walmart': ['walmart.com'], 'target': ['target.com'], 'home depot': ['homedepot.com'],
    'dropbox': ['dropbox.com', 'dropboxmail.com'], 'adobe': ['adobe.com'],
}
FREEMAIL = ('gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com', 'aol.com', 'protonmail.com',
            'proton.me', 'mail.com', 'gmx.com', 'live.com', 'yandex.com', 'zoho.com')
URGENT = re.compile(
    r"(suspend|verify|verification|unusual (sign|activ)|unauthori[sz]ed|locked|deactivat|expire|action (needed|required)|immediately|"
    r"final (notice|warning)|payment (failed|declined|method)|update (your )?(payment|billing|account)|confirm (your )?(identity|account)|"
    r"wire|w-?9|tax refund|refund (is|has)|package (is )?(held|waiting|on hold)|delivery (failed|attempt)|invoice|payment request|you paid|"
    r"receipt|order (has been|is)|congratulations|you('ve| have) (won|been selected)|inheritance|beneficiary|claim your|gift card|prize|"
    r"lottery|job offer|work from home|earn \$|per week|check (will be|has been) (mailed|sent)|cash app|bitcoin|crypto|reset your password|"
    r"password (reset|expir)|storage (is )?full|mailbox (is )?full|voicemail|fax received|shared (a )?(document|file) with you|"
    r"sign(ature)? (request|required)|e-?sign)", re.I)
# letters and digits mixed in both the local part and the domain
RANDOMISH = re.compile(r"^(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{7,}@(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{15,}", re.I)


def domain(addr):
    return addr.rsplit('@', 1)[-1].lower() if '@' in addr else ''


def looks_random(addr):
    """True when the sender looks machine-generated.

    Domain length alone is not a signal: many honest senders use long domains made of ordinary words.
    Random means the local part and the domain both mix letters and digits, or the domain has no dot,
    or its main label is long with very few vowels or with several long consonant runs.
    """
    d = domain(addr)
    if not d:
        return False
    if RANDOMISH.match(addr):
        return True
    if '.' not in d:
        return True
    core = d.split('.')[-2]
    if len(core) < 14:
        return False
    vowels = sum(c in 'aeiou' for c in core)
    if vowels / len(core) < 0.22:
        return True
    return len(re.findall(r'[bcdfghjklmnpqrstvwxz]{4,}', core)) >= 3


def brands_in(text, brands):
    """Brand names that appear in the text as whole words ("ups" must not match "groups")."""
    t = text.lower()
    return [b for b in brands if re.search(r'(?<![a-z0-9])' + re.escape(b) + r'(?![a-z0-9])', t)]


def on_brand_domain(d, names, brands):
    """True when d is one of the brand's listed domains or a subdomain of one. A lookalike is neither."""
    return any(d == bd or d.endswith('.' + bd) for b in names for bd in brands.get(b, []))


def score_row(addr, name, subj, brands):
    s, why = 0, []
    d = domain(addr)
    if looks_random(addr):
        s += 4; why.append('random-domain')
    b_name = brands_in(name, brands)
    if b_name and not on_brand_domain(d, b_name, brands):
        if d in FREEMAIL:
            s += 5; why.append(f'brand-name "{name[:25]}" from free-mail')
        else:
            s += 3; why.append(f'brand-name "{name[:25]}" off-domain {d}')
    b_subj = brands_in(subj, brands)
    if b_subj and not b_name and not on_brand_domain(d, b_subj, brands) and (d in FREEMAIL or looks_random(addr)):
        s += 3; why.append('brand in subject, sender unrelated')
    m = URGENT.search(subj)
    if m:
        s += 2; why.append('urgent:' + m.group(0)[:20])
        if d in FREEMAIL:
            s += 1; why.append('free-mail+urgent')
        if re.search(r'\b\d{6,}\b', subj):
            s += 1; why.append('ticket-number')
    if re.search(r'[☀-➿\U0001F300-\U0001FAFF]', subj):
        s += 1; why.append('emoji')
    return s, '; '.join(why)


def default_mail_root():
    found = sorted(glob.glob(os.path.expanduser('~/Library/Mail/V*')), key=lambda p: int(re.sub(r'\D', '', os.path.basename(p)) or 0))
    return found[-1] if found else os.path.expanduser('~/Library/Mail/V10')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='directory for the three TSV reports')
    ap.add_argument('--since', default=(datetime.date.today() - datetime.timedelta(days=365)).isoformat(), help='YYYY-MM-DD (default: one year back)')
    ap.add_argument('--mail-root', default=default_mail_root())
    ap.add_argument('--brands', help='JSON file {"brand": ["domain", ...]} replacing the built-in list')
    ap.add_argument('--top', type=int, default=150, help='how many top candidates get a header check')
    a = ap.parse_args()

    brands = {k.lower(): [d.lower() for d in v] for k, v in json.load(open(a.brands)).items()} if a.brands else BRAND_DOMAINS
    mail_root = os.path.expanduser(a.mail_root)
    idx = os.path.join(mail_root, 'MailData', 'Envelope Index')
    if not os.path.exists(idx):
        sys.exit(f'no Envelope Index at {idx}')
    os.makedirs(a.out, exist_ok=True)

    # mode=ro, not immutable=1: immutable ignores the -wal file and so misses the most recent rows
    con = sqlite3.connect(f'file:{idx}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    q = """SELECT m.ROWID rid, m.date_received dr, a.address addr, a.comment name, s.subject subj, mb.url url
           FROM messages m JOIN mailboxes mb ON m.mailbox=mb.ROWID JOIN addresses a ON m.sender=a.ROWID JOIN subjects s ON m.subject=s.ROWID
           WHERE m.date_received > strftime('%s',?) AND mb.url NOT LIKE '%Sent%' AND mb.url NOT LIKE '%Drafts%'"""
    rows = con.execute(q, (a.since,)).fetchall()
    print('messages scanned:', len(rows))

    cands = []
    per_sender = collections.defaultdict(lambda: {'n': 0, 'max': 0, 'why': set(), 'first': None, 'last': None, 'name': '', 'junk': 0, 'sample': ''})
    for r in rows:
        addr, name, subj, url = r['addr'] or '', r['name'] or '', r['subj'] or '', r['url'] or ''
        sc, why = score_row(addr, name, subj, brands)
        day = datetime.datetime.fromtimestamp(r['dr'], datetime.timezone.utc).date().isoformat()
        acct = re.search(r'imap://([0-9A-F]{8})', url)
        store = acct.group(1) if acct else url[-12:]
        folder = url.rsplit('/', 1)[-1]
        in_junk = 'Junk' in folder or 'Spam' in folder
        ps = per_sender[addr]
        ps['n'] += 1
        ps['max'] = max(ps['max'], sc)
        ps['name'] = ps['name'] or name
        ps['first'] = min(ps['first'] or day, day)
        ps['last'] = max(ps['last'] or day, day)
        ps['junk'] += int(in_junk)
        if why:
            ps['why'].update(why.split('; '))
        if sc >= 4:
            cands.append((sc, day, r['rid'], addr, name, subj[:100], store, folder, why))
            ps['sample'] = ps['sample'] or subj[:80]
    cands.sort(key=lambda x: (-x[0], x[1]))

    with open(os.path.join(a.out, 'candidates.tsv'), 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['score', 'date', 'rowid', 'sender', 'display_name', 'subject', 'store', 'folder', 'signals'])
        w.writerows(cands)
    with open(os.path.join(a.out, 'senders.tsv'), 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['max_score', 'msgs', 'in_junk', 'first', 'last', 'sender', 'display_name', 'signals', 'sample_subject'])
        for addr, ps in sorted(per_sender.items(), key=lambda kv: (-kv[1]['max'], -kv[1]['n'])):
            if ps['max'] >= 4:
                w.writerow([ps['max'], ps['n'], ps['junk'], ps['first'], ps['last'], addr, ps['name'], '; '.join(sorted(ps['why'])), ps['sample']])
    print('candidates (score>=4):', len(cands), ' distinct senders flagged:', sum(1 for p in per_sender.values() if p['max'] >= 4))

    # header check on the top candidates that are NOT already in Junk: those are the ones that got through
    top = [c for c in cands if not ('Junk' in c[7] or 'Spam' in c[7])][:a.top]
    hdr_rows = []
    for c in top:
        rid = c[2]
        hits = glob.glob(os.path.join(mail_root, '*', '**', 'Messages', f'{rid}.emlx'), recursive=True) or \
               glob.glob(os.path.join(mail_root, '*', '**', 'Messages', f'{rid}.partial.emlx'), recursive=True)
        if not hits:
            hdr_rows.append([c[0], c[1], rid, c[3], c[5], 'NO_FILE', '', '']); continue
        try:
            raw = open(hits[0], 'rb').read(60000).decode('utf-8', 'ignore')
        except Exception as e:
            hdr_rows.append([c[0], c[1], rid, c[3], c[5], f'ERR {e}', '', '']); continue
        head = re.split(r'\r?\n\r?\n', raw, maxsplit=1)[0]
        rt = re.search(r'^Reply-To:\s*(.+)$', head, re.M | re.I)
        rt = rt.group(1).strip() if rt else ''
        spf, dkim, dmarc = (re.search(k + r'=(\w+)', head, re.I) for k in ('spf', 'dkim', 'dmarc'))
        auth = f"spf={spf.group(1) if spf else '?'} dkim={dkim.group(1) if dkim else '?'} dmarc={dmarc.group(1) if dmarc else '?'}"
        flag = ''
        if rt:
            rtd = domain(re.sub(r'.*<([^>]+)>.*', r'\1', rt).strip())
            if rtd and rtd != domain(c[3]):
                flag = 'REPLY-TO-MISMATCH' + (' (free-mail)' if rtd in FREEMAIL else '')
        hdr_rows.append([c[0], c[1], rid, c[3], c[5], rt[:80], flag, auth])
    with open(os.path.join(a.out, 'headers_top_not_in_junk.tsv'), 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t')
        w.writerow(['score', 'date', 'rowid', 'sender', 'subject', 'reply_to', 'reply_to_flag', 'auth'])
        w.writerows(hdr_rows)
    print('header check rows:', len(hdr_rows), ' reply-to mismatches:', sum(1 for h in hdr_rows if h[6]),
          ' spf/dkim/dmarc fail:', sum(1 for h in hdr_rows if 'fail' in h[7]))
    print('OUT', a.out)


if __name__ == '__main__':
    main()
