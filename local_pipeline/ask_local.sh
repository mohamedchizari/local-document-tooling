#!/bin/bash
# ask_local.sh - send one narrowed question, with stdin as the text, to a local Ollama model.
#
#   usage: bash ask_local.sh 'question'  < input.txt
#          cat snippets.txt | bash ask_local.sh 'label each line yes/no: ...'
#
#   OLLAMA_MODEL   model tag (default: gemma4:e4b; a name without a tag means <name>:latest)
#   NUM_CTX        context window in tokens (default: 4096)
#   OLLAMA_URL     server (default: http://localhost:11434)
#   OLLAMA_ALLOW_REMOTE=1 allows sending text to a non-loopback HTTP Ollama server (HTTPS needs no opt-in)
#
# Pick a model that fits in memory. A model larger than the machine's RAM pages its weights off
# disk on every inference and is unusable; as a rule of thumb, keep the model to about half of RAM.
# Check sizes with:  ollama list
#
# Good for: bulk yes/no classification over text that was already extracted, for example
# "is this paragraph about topic X" across thousands of snippets.
# Not for: anything that decides a date, an amount or a name. A small local model states a wrong
# number as confidently as a right one. Its output tells you which documents to open; it is not a finding.
#
# Exit status: 0 an answer was printed; 1 the model is missing or the request failed; 2 usage.
# Needs: ollama running, python3.

set -u
MODEL="${OLLAMA_MODEL:-gemma4:e4b}"
case "$MODEL" in *:*) ;; *) MODEL="$MODEL:latest" ;; esac
NUM_CTX="${NUM_CTX:-4096}"
URL="${OLLAMA_URL:-http://localhost:11434}"

PROMPT="${1:-}"
[ -n "$PROMPT" ] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
command -v ollama >/dev/null || { echo "FATAL: ollama not on PATH" >&2; exit 1; }

LIST="$(ollama list 2>&1)" || { echo "FATAL: ollama list failed: $LIST" >&2; exit 1; }
if ! printf '%s\n' "$LIST" | awk '{print $1}' | grep -Fx -e "$MODEL" >/dev/null; then
  echo "Model '$MODEL' is not pulled. Installed models:" >&2
  printf '%s\n' "$LIST" >&2
  echo "Pull one that fits in memory:   ollama pull $MODEL" >&2
  exit 1
fi
echo "# model=$MODEL size=$(printf '%s\n' "$LIST" | awk -v m="$MODEL" '$1==m {print $3, $4}') ctx=$NUM_CTX" >&2

# The HTTP API is used, not `ollama run`, because the context size is a per-request option there.
# The text on stdin is read by python directly, so its size is not limited by the argument list.
PY='
import json, os, sys, urllib.request
from urllib.parse import urlsplit
e = os.environ
try:
    parsed = urlsplit(e["ASK_URL"])
    hostname = parsed.hostname
except ValueError:
    sys.exit("request failed: OLLAMA_URL must be a valid http(s) URL")
if parsed.scheme not in ("http", "https") or not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
    sys.exit("request failed: OLLAMA_URL must be an http(s) URL without credentials, query, or fragment")
if parsed.scheme == "http" and hostname.lower() not in ("localhost", "127.0.0.1", "::1") and e.get("ASK_ALLOW_REMOTE") != "1":
    sys.exit("request failed: remote HTTP Ollama may expose document text; use HTTPS or set OLLAMA_ALLOW_REMOTE=1 to accept the risk")
text = "" if sys.stdin.isatty() else sys.stdin.read()
body = json.dumps({"model": e["ASK_MODEL"], "prompt": e["ASK_PROMPT"] + "\n\n" + text, "stream": False,
                   "options": {"num_ctx": int(e["ASK_CTX"])}}).encode()
req = urllib.request.Request(e["ASK_URL"].rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        print(json.loads(r.read())["response"])
except Exception as err:
    sys.exit("request failed: %s" % err)
'
ASK_MODEL="$MODEL" ASK_CTX="$NUM_CTX" ASK_URL="$URL" ASK_PROMPT="$PROMPT" \
ASK_ALLOW_REMOTE="${OLLAMA_ALLOW_REMOTE:-0}" python3 -c "$PY"
status=$?
echo >&2
echo "# Local output is a filter, not a finding. Open the source document before relying on it." >&2
exit $status
