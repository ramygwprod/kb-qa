#!/usr/bin/env python3
"""One line per kbqa verdict on stdin: gate, verdict (NOT CHECKED when 0 scanned), finding codes."""
import collections
import json
import sys

t = sys.stdin.read()
try:
    v = json.loads(t[t.index("{"):])
except ValueError:
    print("   (no verdict) " + t.strip()[-200:])
    sys.exit(0)
codes = collections.Counter(f["code"] for f in v.get("findings", []))
scanned = v.get("counts", {}).get("scanned")
state = "NOT CHECKED" if scanned == 0 else v.get("verdict")
found = ", ".join("%s x%d" % kv for kv in sorted(codes.items())) or "no findings"
print("   %s: %s · scanned %s · %s" % (v.get("gate"), state, scanned, found))
