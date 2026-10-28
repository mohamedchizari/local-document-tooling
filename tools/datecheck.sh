#!/bin/bash
# datecheck.sh - print the HTTP Date header of several public sites next to the local clock,
# so a wrong system clock can be seen. It prints; it does not compute a difference.
#   usage: bash tools/datecheck.sh [url ...]
# Cache markers (Age, X-Cache, CF-Cache-Status) are printed beside each Date: a cached response
# carries an old Date, so do not count it as an independent source.
# Needs: curl and a network connection.
if [ "$#" -gt 0 ]; then SITES=("$@"); else SITES=(https://www.iana.org https://www.nist.gov https://www.w3.org https://www.kernel.org); fi
failed=0
echo "=== HTTP Date headers ==="
for H in "${SITES[@]}"; do
  echo "--- $H"
  # no -f: an error status (403, 404, 500) still carries a Date; only a failed transfer is an error
  if ! headers=$(curl -sSI --max-time 12 -H 'Cache-Control: no-cache' "$H"); then
    echo "ERROR: request failed: $H" >&2
    failed=1
    continue
  fi
  status=$(printf '%s\n' "$headers" | grep -E '^HTTP/' | tail -1 | tr -d '\r')
  [ -z "$status" ] || echo "$status"
  markers=$(printf '%s\n' "$headers" | grep -iE '^(date|age|cf-cache-status|x-cache):' || true)
  if ! printf '%s\n' "$markers" | grep -qi '^date:'; then
    echo "ERROR: response had no Date header: $H" >&2
    failed=1
  fi
  [ -z "$markers" ] || printf '%s\n' "$markers"
done
echo
echo "=== local clock ==="
date -u '+%a %Y-%m-%d %H:%M:%S UTC'
exit "$failed"
