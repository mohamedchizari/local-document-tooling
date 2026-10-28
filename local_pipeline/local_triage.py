#!/usr/bin/env python3
"""local_triage.py - a local model builds a pointer index: one card per text file saying what the file is about.

The index tells a reader where to look. It is never a source of facts.

Runs against Ollama (default http://localhost:11434). Reads the .md and .txt files under one directory,
asks the model for a strict-JSON card per file, and writes one tab-separated index:
  <index_dir>/<dirname>_<YYYY-MM-DD>.tsv

Rules built in:
  - a canary file with a known answer runs first; if the model's card for it misses the expected tokens,
    nothing is indexed
  - a card holds pointers (topic, names, dates as written); it is not a summary and not a finding
  - read-only on sources
  - resumable: run again with the same --out (or on the same day) to continue; failed rows are retried

Usage: python3 local_triage.py <directory> [--model qwen3:8b] [--limit 200] [--out index.tsv]
  --limit is the number of new files to index in this run.
Environment: OLLAMA_URL (default http://localhost:11434); a server that is not on this machine, over
HTTP or HTTPS, requires OLLAMA_ALLOW_REMOTE=1.
TRIAGE_CONFIG selects another config file.
Needs: a pulled Ollama model and config.local.json beside this script (copy config.example.json).
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlsplit

OLLAMA = os.environ.get('OLLAMA_URL', 'http://localhost:11434')

PROMPT = """You are indexing one document from a personal archive. Return ONLY a JSON object with keys:
"answers": one sentence: what question would a reader open this file to answer?
"entities": list of up to 8 proper nouns that appear in it
"dates": list of up to 8 date strings exactly as they appear in the text
"kind": one of ["letter","note","worksheet","ledger","report","log","other"]
"needs_human": true if the file contains a decision, deadline or instruction a person must act on
Do not invent anything that is not in the text. Do not compute. Do not summarise.
TEXT:
"""
BAD_CARD = {'answers': '', 'entities': [], 'dates': [], 'kind': 'other', 'needs_human': True}
FAILED = ('ERROR ', 'UNPARSEABLE MODEL OUTPUT')   # rows that start like this are retried on resume


def validate_ollama_url(url):
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        sys.exit('OLLAMA_URL must be a valid http(s) URL without embedded credentials or query parameters')
    if parsed.scheme not in ('http', 'https') or not hostname or parsed.username or parsed.password \
            or parsed.query or parsed.fragment:
        sys.exit('OLLAMA_URL must be an http(s) URL without embedded credentials')
    local_hosts = ('localhost', '127.0.0.1', '::1')
    # Any server that is not on this machine receives the document text, over HTTPS as over HTTP.
    if hostname.lower() not in local_hosts and os.environ.get('OLLAMA_ALLOW_REMOTE') != '1':
        sys.exit('a non-local Ollama server would receive the document text; '
                 'set OLLAMA_ALLOW_REMOTE=1 to send it there (prefer HTTPS)')
    return url.rstrip('/')


def load_config():
    """Local values come from a git-ignored JSON file beside this script, never from this file.

    Keys: canary_file (path), triage_canary_tokens (list), triage_canary_min (int), index_dir (path).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for name in (os.environ.get('TRIAGE_CONFIG', ''), 'config.local.json'):
        path = name if os.path.isabs(name) else os.path.join(here, name)
        if name and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return json.load(f)
    sys.exit('config.local.json not found beside local_triage.py; copy config.example.json and fill it in')


def ollama(model, prompt, timeout=180):
    body = json.dumps({'model': model, 'prompt': prompt, 'format': 'json', 'stream': False,
                       'options': {'temperature': 0, 'num_ctx': 8192}}).encode()
    req = urllib.request.Request(f'{OLLAMA}/api/generate', data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())['response']


def models_present():
    try:
        with urllib.request.urlopen(f'{OLLAMA}/api/tags', timeout=10) as r:
            return [m['name'] for m in json.loads(r.read()).get('models', [])]
    except Exception as e:
        sys.exit(f'Ollama not reachable at {OLLAMA}: {e}')


def card(model, path, max_chars=12000):
    text = open(path, encoding='utf-8', errors='replace').read()[:max_chars]
    raw = ollama(model, PROMPT + text)
    try:
        c = json.loads(raw)
    except json.JSONDecodeError:
        c = None
    if not isinstance(c, dict):
        return dict(BAD_CARD, answers='UNPARSEABLE MODEL OUTPUT')
    return c


def cell(value):
    """One TSV cell: tabs and line breaks in model output would break the row."""
    return re.sub(r'\s+', ' ', str(value)).strip()


def as_list(value):
    return value if isinstance(value, list) else ([] if value in (None, '') else [value])


def has_model(model, present):
    return model in present or (':' not in model and model + ':latest' in present)


def wait_for_model_slot(model, max_wait=1800):
    """Wait until Ollama has nothing loaded, or has our model loaded.

    On a small machine Ollama serves one model at a time. If another model is loaded and busy, a request
    for ours queues until it times out and becomes an error row. Polling /api/ps avoids that.
    """
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            with urllib.request.urlopen(f'{OLLAMA}/api/ps', timeout=10) as r:
                loaded = [m['name'] for m in json.load(r).get('models', [])]
        except Exception:
            loaded = []
        if not loaded or has_model(model, loaded):
            return True
        print(f'waiting: {loaded} is loaded, not {model}; sleeping 60 s', flush=True)
        time.sleep(60)
    return False


def main():
    global OLLAMA
    OLLAMA = validate_ollama_url(OLLAMA)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('directory')
    ap.add_argument('--model', default='qwen3:8b')
    ap.add_argument('--limit', type=int, default=200, help='new files to index in this run')
    ap.add_argument('--out', default=None, help='TSV path; pass an existing one to resume it')
    a = ap.parse_args()

    cfg = load_config()
    canary_file = os.path.expanduser(cfg['canary_file'])
    if not os.path.isfile(canary_file):
        sys.exit(f'canary_file not found: {canary_file} (set it in config.local.json)')
    tokens = cfg.get('triage_canary_tokens') or []
    need = int(cfg.get('triage_canary_min', 2))   # require several tokens, any `need` of them: one exact token is brittle
    if len(tokens) < need:
        sys.exit('config.local.json needs triage_canary_tokens (at least triage_canary_min entries)')

    have = models_present()
    if not has_model(a.model, have):
        sys.exit(f'model {a.model} not pulled; present: {have}. Run: ollama pull {a.model}')

    # 1. canary first: a known file must yield a card that carries known tokens
    if not wait_for_model_slot(a.model):
        sys.exit('another model held the slot for 30 min; nothing indexed')
    c = card(a.model, canary_file)
    blob = json.dumps(c).lower()
    hits = [k for k in tokens if k.lower() in blob]
    if len(hits) < need:
        sys.exit(f'CANARY FAILED on {os.path.basename(canary_file)}: {c}. Nothing indexed; the model is not proven on this text.')
    print('canary ok', hits, '|', c.get('answers'), flush=True)

    # 2. index
    files = []
    for root, _, names in os.walk(a.directory):
        for n in sorted(names):
            if n.lower().endswith(('.md', '.txt')) and not n.startswith('.'):
                files.append(os.path.join(root, n))

    outdir = os.path.expanduser(cfg.get('index_dir', '~/local_index'))
    os.makedirs(outdir, exist_ok=True)
    out = a.out or os.path.join(outdir, f'{os.path.basename(os.path.abspath(a.directory))}_{datetime.date.today().isoformat()}.tsv')

    # resume: keep the good rows of an existing index, drop the failed ones so those files are tried again
    header = 'path\tkind\tneeds_human\tanswers\tentities\tdates'
    kept, failed_rows = [], {}
    if os.path.exists(out):
        with open(out, encoding='utf-8') as f0:
            for ln in f0.read().splitlines()[1:]:
                cols = ln.split('\t')
                if len(cols) >= 4 and not cols[3].startswith(FAILED):
                    kept.append(ln)
                elif cols and cols[0]:
                    failed_rows[cols[0]] = ln
    done = {ln.split('\t', 1)[0] for ln in kept}
    rels = [(os.path.relpath(p, a.directory), p) for p in files]
    new = [p for r, p in rels if r not in done and r not in failed_rows]
    retry = [p for r, p in rels if r in failed_rows and r not in done]
    todo = (new + retry)[:a.limit]   # files never tried come first, so a file that always fails cannot block the rest
    retried = {os.path.relpath(p, a.directory) for p in todo}
    kept += [ln for r, ln in failed_rows.items() if r not in done and r not in retried]   # failures not retried now stay on record

    n_ok = n_bad = 0
    with open(out, 'w', encoding='utf-8') as f:
        f.write(header + '\n')
        for ln in kept:
            f.write(ln + '\n')
        f.flush()
        for p in todo:
            rel = os.path.relpath(p, a.directory)
            if not wait_for_model_slot(a.model):
                print('gave up waiting for a model slot; rerun to resume', flush=True)
                break
            try:
                c = card(a.model, p)
            except Exception as e:
                c = dict(BAD_CARD, answers=f'ERROR {e}')
            if str(c.get('answers', '')).startswith(FAILED):
                n_bad += 1
            else:
                n_ok += 1
            f.write('\t'.join([cell(rel), cell(c.get('kind')), cell(c.get('needs_human')), cell(c.get('answers')),
                               '; '.join(cell(x) for x in as_list(c.get('entities'))),
                               '; '.join(cell(x) for x in as_list(c.get('dates')))]) + '\n')
            f.flush()
    print(f'indexed {n_ok} / failed {n_bad} / already indexed {len(done)} / {len(files)} text files under the directory -> {out}', flush=True)
    print('This index says where to look. Open the file before relying on any name or date in it.')


if __name__ == '__main__':
    main()
