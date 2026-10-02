#!/usr/bin/env python3
"""app_census.py - turn `system_profiler SPApplicationsDataType -json` into a Markdown census.

Lists the apps under /Applications and ~/Applications with architecture, version and source.
On Apple Silicon an Intel-only app runs under Rosetta, so those are listed first.

Usage:
  system_profiler SPApplicationsDataType -json > apps.json
  python3 app_census.py apps.json > APPS.md
"""
import collections
import datetime
import json
import os
import subprocess
import sys


def stamp():
    """Timestamp from tools/stamp.sh when it is there, else today's date."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'stamp.sh')
    try:
        out = subprocess.run(['bash', script], capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        out = ''
    return out or datetime.date.today().isoformat()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    data = json.load(open(os.path.expanduser(sys.argv[1])))['SPApplicationsDataType']
    roots = ('/Applications/', os.path.expanduser('~/Applications') + '/')
    apps = [a for a in data if a.get('path', '').startswith(roots)]
    arch = collections.Counter(a.get('arch_kind', '?') for a in apps)

    print(f"# Mac application census, {stamp()}")
    print(f"Source: `system_profiler SPApplicationsDataType -json`. {len(apps)} apps under /Applications and ~/Applications. "
          "Architecture: " + ', '.join(f"{k.replace('arch_', '')}={v}" for k, v in arch.most_common()) +
          ". `i64` = Intel-only (Rosetta on Apple Silicon); `arm_i64` = universal; `arm` = native.\n")

    intel = sorted((a for a in apps if a.get('arch_kind') == 'arch_i64'), key=lambda x: x['_name'].lower())
    print(f"## Intel-only apps ({len(intel)})\n")
    print("| app | version | last modified | source |")
    print("|---|---|---|---|")
    for a in intel:
        print(f"| {a['_name']} | {a.get('version', '')} | {a.get('lastModified', '')[:10]} | {a.get('obtained_from', '')} |")

    print("\n## All apps\n")
    print("| app | version | arch | source | last modified |")
    print("|---|---|---|---|---|")
    for a in sorted(apps, key=lambda x: x['_name'].lower()):
        print(f"| {a['_name']} | {a.get('version', '')} | {a.get('arch_kind', '?').replace('arch_', '')} | "
              f"{a.get('obtained_from', '')} | {a.get('lastModified', '')[:10]} |")


if __name__ == '__main__':
    main()
