#!/bin/bash
# stamp.sh - print a timestamp read from the clock, for log lines and report headers.
# A time typed from memory is a guess; a log line should carry one that was read.
#   usage: bash tools/stamp.sh                     -> "HH:MM UTC / HH:MM ZZZ Day D Mon YYYY"
#          STAMP_TZ=Europe/Berlin bash tools/stamp.sh   (default: the system time zone)
u=$(date -u '+%H:%M UTC')
if [ -n "${STAMP_TZ:-}" ]; then l=$(TZ="$STAMP_TZ" date '+%H:%M %Z %a %-d %b %Y'); else l=$(date '+%H:%M %Z %a %-d %b %Y'); fi
echo "$u / $l"
