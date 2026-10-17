"""kbqa elements --outline — the APQC element list in a page, for reading in parts.

    python3 -m kbqa elements --outline <elements.jsonl>

The element list the mapper copies from is about 2,000 objects and 670 KB —
far more than one pass should hold in context before it has read a single row,
and long inputs are where models lose what sits in the middle. So the mapper
reads this outline first: every top-level and second-level element, each with
the 1-based line range of its whole group in the list, then reads only the
groups that could fit its rows.

It writes `<list>.outline.md` beside the list, derived and deterministic (the
same list gives the same outline), with the list's sha256 and line count in its
first line so a stale outline is visible. It never changes the list.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


def _ranges(lines: List[int]) -> str:
    out, start, prev = [], None, None
    for n in lines:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ",".join(out)


def outline_path(elements: Path) -> Path:
    return elements.with_name(elements.stem + ".outline.md")


def build_outline(elements: Path) -> str:
    data = elements.read_bytes()
    rows = []
    for n, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        obj = json.loads(line)
        rows.append((n, str(obj["hierarchy_id"]).strip(), str(obj["name"]).strip()))
    groups: Dict[str, List[int]] = {}
    titles: Dict[str, str] = {}
    order: List[str] = []
    for n, hid, name in rows:
        segs = hid.split(".")
        top = segs[0]
        second = ".".join(segs[:2]) if len(segs) > 1 and segs[1] != "0" else None
        for key in (f"{top}.0", second):
            if key is None:
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(n)
        if hid == f"{top}.0" or (len(segs) == 1):
            titles[f"{top}.0"] = name
        if second and hid == second:
            titles[second] = name
    sha = hashlib.sha256(data).hexdigest()
    out = [f"APQC outline — from {elements.name} · sha256 {sha} · {len(rows)} elements · "
           "line ranges are 1-based lines of that file; read only the groups you need",
           "", "| hierarchy_id | name | lines in the list |", "|---|---|---|"]
    for key in order:
        out.append(f"| {key} | {titles.get(key, '(no element with this id)')} | {_ranges(groups[key])} |")
    return "\n".join(out) + "\n"


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa elements")
    ap.add_argument("--outline", required=True, help="the APQC element list (.jsonl)")
    args = ap.parse_args(argv)
    elements = Path(args.outline)
    if not elements.exists():
        print(f"no element list at {elements}", file=sys.stderr)
        return 1
    try:
        text = build_outline(elements)
    except (ValueError, KeyError) as exc:
        print(f"the element list is not one {{pcf_id, hierarchy_id, name}} object per line: {exc}",
              file=sys.stderr)
        return 1
    target = outline_path(elements)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} — {text.count(chr(10)) - 4} groups")
    return 0
