"""Format diagnostic — reports a file's SHAPE, never its CONTENT.

Why this exists
---------------
The staging format in `parsing.py` is inferred from the spec, not observed. If
the inference is wrong, G1/G2/G3 fail every real batch for the wrong reason —
and the operator would be debugging their data while the fault is in the parser.

The obvious fix is to show the checker a real staging file. That would defeat
the isolation the whole design rests on: a checker that has read the collector's
output is no longer independent of it.

So this reports structure and withholds substance. Field *names*, value *types*,
string *lengths*, marker *syntax* — never a quote, a URL, a vendor term, or any
free-text value. The output is designed to be pasted into a conversation with
someone who must not see the data.

Redaction rules
---------------
- Enum-valued fields named in the contract: distinct values ARE shown. Those are
  schema ("yes"/"partial"/"no"), not data.
- Every other field: type, length range, and cardinality only.
- URLs: scheme and shape only, never the host or path.
- Free text: never, at any length.

If a value could identify a vendor, a product, or a claim, it does not appear.
"""

import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .models import Row

# Fields whose values are contract enums. Showing these is safe: they describe
# the schema, not the vendor. Everything else is reported by shape alone.
ENUM_FIELDS: Set[str] = {
    "schema_version", "evidence_grade", "confidence", "mechanism",
    "outcome", "depth_level", "canonical", "broken_source",
}

# Frontmatter keys safe to echo verbatim — structural, never descriptive.
# fetched_by_this_agent is included deliberately: G6 FAILs on `true` (role
# collapse), so its value is a safety signal and identifies no vendor.
SAFE_FM_VALUE_KEYS: Set[str] = {
    "schema_version", "row_count", "batch", "fetched_by_this_agent",
}

MAX_ENUM_DISTINCT = 20


def _shape_of(value: Any) -> str:
    """Classify a value without disclosing it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"object[{len(value)} keys]"
    s = str(value)
    if re.match(r"^https?://", s):
        return "url"
    if re.match(r"^doc:", s):
        return "doc-ref"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return "date(ISO)"
    if re.match(r"^[0-9a-f]{64}$", s):
        return "sha256"
    if re.match(r"^[a-z0-9]+(\.[a-z0-9\-]+)+$", s):
        return "dotted-id"
    return "str"


def _describe_field(name: str, values: List[Any]) -> str:
    shapes = sorted({_shape_of(v) for v in values})
    shape = "|".join(shapes)
    present = len(values)

    if name in ENUM_FIELDS:
        distinct = sorted({str(v) for v in values})
        if len(distinct) <= MAX_ENUM_DISTINCT:
            return f"{shape}  present={present}  values={distinct}"
        return f"{shape}  present={present}  distinct={len(distinct)} (too many to list)"

    strings = [str(v) for v in values if isinstance(v, str)]
    if strings:
        lengths = [len(s) for s in strings]
        return (
            f"{shape}  present={present}  "
            f"len min={min(lengths)} med={int(statistics.median(lengths))} max={max(lengths)}  "
            f"distinct={len(set(strings))}"
        )
    return f"{shape}  present={present}"


_JSON_PAIR_RE = re.compile(r'("(?:[^"\\]|\\.)*"\s*:\s*)"(?:[^"\\]|\\.)*"')


def _line_shape(line: str) -> str:
    """Describe a line's structure with its content stripped out.

    Redaction is key-aware, not length-based. An earlier version redacted only
    quoted strings of 25+ characters, which let short values through — a real
    leak on the pretty-printed array format, where every value sits on its own
    line as `"vendor_term": "REST API",`. Length is not a proxy for sensitivity:
    a product name is usually short.

    So: the KEY of a JSON pair survives (it is schema), the VALUE never does.
    """
    if not line.strip():
        return "(blank)"
    s = line.rstrip("\n")
    # Value of any "key": "value" pair — the key is kept, the value is not.
    s = _JSON_PAIR_RE.sub(r'\1"<redacted>"', s)
    s = re.sub(r"https?://[^\s\"']+", "<url>", s)
    s = re.sub(r"[0-9a-f]{64}", "<sha256>", s)
    # Any remaining quoted run, whatever its length or position.
    s = re.sub(r'"(?:[^"\\]|\\.){2,}"', '"<text>"', s)
    if len(s) > 90:
        s = s[:90] + f"… (+{len(line) - 90} chars)"
    return s


def probe_staging(path: Path) -> List[str]:
    out: List[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    out.append(f"== staging: {path.name}")
    out.append(f"bytes={path.stat().st_size}  lines={len(lines)}")
    out.append("")

    # --- opening / frontmatter -------------------------------------------
    out.append("-- opening --")
    if lines:
        out.append(f"line 1: {_line_shape(lines[0])!r}")
    opens_with_delim = bool(lines) and lines[0].strip() == "---"
    out.append(f"opens with '---': {opens_with_delim}")

    fm_end = None
    if opens_with_delim:
        for i, line in enumerate(lines[1:], start=2):
            if line.strip() == "---":
                fm_end = i
                break
    out.append(f"frontmatter closes at line: {fm_end}")
    out.append("")

    if fm_end:
        out.append("-- frontmatter keys (names only; values shown for structural keys) --")
        last_key: Optional[str] = None
        list_counts: Dict[str, int] = {}
        for line in lines[1:fm_end - 1]:
            item = re.match(r"^\s+-\s+(?P<item>.+?)\s*$", line)
            if item and last_key:
                list_counts[last_key] = list_counts.get(last_key, 0) + 1
                continue
            kv = re.match(r"^(?P<key>[^:\s][^:]*):\s*(?P<val>.*)$", line)
            if not kv:
                if line.strip():
                    out.append(f"  (non key:value line) {_line_shape(line)!r}")
                continue
            last_key = kv.group("key").strip()
            key, val = kv.group("key").strip(), kv.group("val").strip()
            if key in SAFE_FM_VALUE_KEYS:
                out.append(f"  {key}: {val}")
            elif val == "":
                out.append(f"  {key}: <list, see counts below>")
            else:
                out.append(f"  {key}: <{_shape_of(val)}>")
        for key, n in sorted(list_counts.items()):
            out.append(f"  {key}: {n} list item(s)")
        out.append("")

    # --- serialisation ----------------------------------------------------
    from .parsing import parse_staging

    out.append("-- row serialisation --")
    fences = [i for i, l in enumerate(lines, 1) if re.match(r"^\s*```+\s*json\s*$", l, re.I)]
    id_col0 = [i for i, l in enumerate(lines, 1) if re.match(r'^\{"id"', l)]
    id_any = [i for i, l in enumerate(lines, 1) if re.match(r'^\s*"id"\s*:', l)]
    out.append(f"```json fences opened          : {len(fences)}")
    out.append(f'lines matching ^{{"id"          : {len(id_col0)}   <- JSONL naive count')
    out.append(f'lines matching ^\\s*"id":        : {len(id_any)}   <- array naive count')

    sp = parse_staging(path)
    out.append(f"detected format               : {sp.row_format}")
    out.append(f"rows parsed                   : {len(sp.rows)}")

    parsed = [r.obj for r in sp.rows if r.obj is not None]
    bad = [f"line {r.line_no}: {r.error}" for r in sp.rows if r.obj is None]
    if bad:
        out.append(f"FAILED to parse               : {len(bad)}")
        for b in bad[:5]:
            out.append(f"  {_line_shape(b)}")
        if len(bad) > 5:
            out.append(f"  … and {len(bad) - 5} more")
    out.append("")

    # --- fields -----------------------------------------------------------
    if parsed:
        by_field: Dict[str, List[Any]] = {}
        for obj in parsed:
            for k, v in obj.items():
                by_field.setdefault(k, []).append(v)

        contract = set(Row.model_fields.keys())
        found = set(by_field)

        out.append(f"-- fields across {len(parsed)} rows --")
        for name in sorted(by_field):
            mark = " " if name in contract else "*"
            out.append(f" {mark} {name:<24} {_describe_field(name, by_field[name])}")
        out.append("")
        out.append("  * = not in the Row contract (would FAIL G2 under extra='forbid')")
        out.append("")

        missing = sorted(f for f in contract if f not in found)
        extra = sorted(f for f in found if f not in contract)
        out.append("-- contract diff --")
        out.append(f"in contract, absent from every row : {missing or 'none'}")
        out.append(f"in rows, absent from contract      : {extra or 'none'}")
        out.append("")

    # --- non-row, non-frontmatter content ---------------------------------
    from .parsing import _find_json_fences

    in_fence = {
        n
        for open_at, close_at in _find_json_fences(lines)
        for n in range(open_at, close_at + 1)
    }
    body_start = fm_end + 1 if fm_end else 1
    other = [
        i for i in range(body_start, len(lines) + 1)
        if lines[i - 1].strip() and i not in in_fence
    ]
    out.append("-- other body lines (outside frontmatter and outside ```json fences) --")
    out.append(f"count: {len(other)}")
    for i in other[:12]:
        out.append(f"  line {i}: {_line_shape(lines[i - 1])!r}")
    if len(other) > 12:
        out.append(f"  … and {len(other) - 12} more")
    out.append("")

    # --- verdict ----------------------------------------------------------
    out.append("-- shipped parser (src/kbqa/parsing.py) --")
    out.append(f"frontmatter_error : {sp.frontmatter_error}")
    out.append(f"frontmatter keys  : {sorted(sp.frontmatter_raw)}")
    out.append(f"row format        : {sp.row_format}")
    out.append(f"rows parsed       : {len(sp.rows)}")
    out.append(f"naive count       : {sp.naive_count}")
    agree = (
        bool(parsed)
        and not bad
        and sp.frontmatter_error is None
        and sp.naive_count == len(parsed)
    )
    out.append("")
    out.append(f"VERDICT: parser {'MATCHES' if agree else 'DOES NOT MATCH'} this file")
    if not agree:
        out.append("  -> src/kbqa/parsing.py needs correcting. Gate logic is unaffected.")

    return out


def probe_capture(path: Path) -> List[str]:
    out: List[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    out.append(f"== capture: {path.name}")
    out.append(f"bytes={path.stat().st_size}  lines={len(lines)}")
    out.append("")

    expected_begin = re.compile(r"^=====BEGIN (.+?)=====\s*$")
    expected_end = re.compile(r"^=====END (.+?)=====\s*$")
    loose = re.compile(r"^\s*=*\s*(BEGIN|END)\b", re.IGNORECASE)

    begins = [i for i, l in enumerate(lines, 1) if expected_begin.match(l)]
    ends = [i for i, l in enumerate(lines, 1) if expected_end.match(l)]
    loose_hits = [
        i for i, l in enumerate(lines, 1)
        if loose.match(l) and not expected_begin.match(l) and not expected_end.match(l)
    ]

    out.append("-- markers --")
    out.append(f"exact '=====BEGIN <url>=====' : {len(begins)}")
    out.append(f"exact '=====END <url>====='   : {len(ends)}")
    out.append(f"balanced                     : {len(begins) == len(ends)}")
    out.append(f"BEGIN/END-ish but non-matching: {len(loose_hits)}")
    for i in loose_hits[:8]:
        out.append(f"  line {i}: {_line_shape(lines[i - 1])!r}")
    if len(loose_hits) > 8:
        out.append(f"  … and {len(loose_hits) - 8} more")
    out.append("")

    from .parsing import parse_capture
    cp = parse_capture(path)
    out.append("-- shipped parser --")
    out.append(f"blocks found     : {len(cp.blocks)}")
    out.append(f"marker errors    : {len(cp.marker_errors)}")
    for e in cp.marker_errors[:5]:
        out.append(f"  {_line_shape(e)}")
    out.append(f"duplicate urls   : {len(cp.duplicate_urls)}")
    if cp.blocks:
        sizes = [len(b) for b in cp.blocks.values()]
        out.append(
            f"block sizes      : min={min(sizes)} "
            f"med={int(statistics.median(sizes))} max={max(sizes)} chars"
        )
    out.append("")
    ok = bool(cp.blocks) and not cp.marker_errors
    out.append(f"VERDICT: parser {'MATCHES' if ok else 'DOES NOT MATCH'} this file")
    return out


def run(argv: List[str]) -> int:
    staging: Optional[str] = None
    capture: Optional[str] = None
    i = 0
    while i < len(argv):
        if argv[i] == "--staging" and i + 1 < len(argv):
            staging = argv[i + 1]; i += 2; continue
        if argv[i] == "--capture" and i + 1 < len(argv):
            capture = argv[i + 1]; i += 2; continue
        print(f"probe: unexpected argument {argv[i]!r}")
        return 1

    if not staging and not capture:
        print("probe: need --staging <file> and/or --capture <file>")
        return 1

    report: List[str] = [
        "kbqa probe — structural report",
        "",
        "Reports SHAPE only: field names, types, lengths, marker syntax.",
        "No quotes, URLs, vendor terms, or free-text values appear below.",
        "Safe to share with someone who must not read the data.",
        "",
    ]
    for path_str, fn in ((staging, probe_staging), (capture, probe_capture)):
        if not path_str:
            continue
        p = Path(path_str)
        if not p.is_file():
            report.append(f"!! not a file: {path_str}")
            continue
        report.extend(fn(p))
        report.append("")

    print("\n".join(report))
    return 0
