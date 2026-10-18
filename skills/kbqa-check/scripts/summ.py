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
line = "   %s: %s · scanned %s · %s" % (v.get("gate"), state, scanned, found)
# The mapping passes' own totals, counted here — the mappers no longer count by hand.
for letter, m in sorted((v.get("counts", {}).get("per_mapper") or {}).items()):
    line += " · %s: mapped %s, needs-human %s" % (letter, m.get("mapped"), m.get("needs_human"))
print(line)
# The operator's questions: one per rule or open pattern the needs-human notes name.
for q in v.get("counts", {}).get("questions") or []:
    passes = ", ".join("%s %d" % (k, len(ids)) for k, ids in sorted(q["per_pass"].items()))
    print("     question [%s]: %d rows (%s)" % (q["pattern"], len(q["rows"]), passes))
