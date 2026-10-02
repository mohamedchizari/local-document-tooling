#!/bin/bash
# datecheck.sh - print the HTTP Date header of several public sites next to the local clock,
# so a wrong system clock can be seen. It prints; it does not compute a difference.
#   usage: bash tools/datecheck.sh [url ...]
# Cache markers (Age, X-Cache, CF-Cache-Status) are printed beside each Date: a cached response
# carries an old Date, so do not count it as an independent source.
# Needs: curl and a network connection.
if [ "$#" -gt 0 ]; then SITES=("$@"); else SITES=(https://www.iana.org https://www.nist.gov https://www.w3.org https://www.kernel.org); fi
echo "=== HTTP Date headers ==="
for H in "${SITES[@]}"; do
  echo "--- $H"
  curl -sI --max-time 12 -H 'Cache-Control: no-cache' "$H" | grep -iE '^(date|age|cf-cache-status|x-cache):'
done
echo
echo "=== local clock ==="
date -u '+%a %Y-%m-%d %H:%M:%S UTC'
