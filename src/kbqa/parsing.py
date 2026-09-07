"""Readers for the two Bronze/Silver file formats.

These parse. They never write, never repair, never normalise the files
themselves. Normalisation happens only in-memory, only for quote matching,
and never touches spelling.

The staging format this module reads is documented in docs/STAGING-FORMAT.md.
It is INFERRED from the spec (the `grep -c '^{"id"'` cross-check in §G2 and
the `source_capture_sha256` frontmatter key in §G1), not observed from a real
collector file. If the real format differs, this module changes — the gate
logic does not.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

BEGIN_RE = re.compile(r"^=====BEGIN (?P<url>.+?)=====\s*$")
END_RE = re.compile(r"^=====END (?P<url>.+?)=====\s*$")

# §G2: the naive cross-check. A row line starts at column 0 with {"id".
NAIVE_ROW_RE = re.compile(r'^\{"id"')

FRONTMATTER_DELIM = "---"


class RowParse(NamedTuple):
    line_no: int
    raw: str
    obj: Optional[dict]
    error: Optional[str]


class StagingParse(NamedTuple):
    frontmatter_raw: dict
    rows: List[RowParse]
    naive_count: int
    frontmatter_error: Optional[str]


class CaptureParse(NamedTuple):
    blocks: Dict[str, str]
    marker_errors: List[str]
    duplicate_urls: List[str]


def _parse_scalar(value: str):
    v = value.strip()
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def _parse_frontmatter(text: str) -> Tuple[dict, Optional[str]]:
    """Minimal YAML subset: `key: value` and `key:` followed by `  - item`.

    Deliberately not a full YAML parser. The frontmatter contract is small and
    fixed; a permissive parser would accept files the contract does not.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        return {}, "staging file does not open with '---' frontmatter"

    out: dict = {}
    current_list_key: Optional[str] = None
    for i, line in enumerate(lines[1:], start=2):
        if line.strip() == FRONTMATTER_DELIM:
            return out, None
        if not line.strip():
            continue
        list_item = re.match(r"^\s+-\s+(?P<item>.+?)\s*$", line)
        if list_item and current_list_key:
            out[current_list_key].append(_parse_scalar(list_item.group("item")))
            continue
        kv = re.match(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<val>.*)$", line)
        if not kv:
            return out, f"unparseable frontmatter at line {i}: {line!r}"
        key, val = kv.group("key"), kv.group("val").strip()
        if val == "":
            out[key] = []
            current_list_key = key
        else:
            out[key] = _parse_scalar(val)
            current_list_key = None
    return out, "frontmatter is not terminated by '---'"


def parse_staging(path: Path) -> StagingParse:
    text = path.read_text(encoding="utf-8")
    fm, fm_err = _parse_frontmatter(text)

    rows: List[RowParse] = []
    naive_count = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        if NAIVE_ROW_RE.match(line):
            naive_count += 1
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            rows.append(RowParse(line_no, line, None, f"invalid JSON: {exc}"))
            continue
        if not isinstance(obj, dict):
            rows.append(RowParse(line_no, line, None, "row is not a JSON object"))
            continue
        rows.append(RowParse(line_no, line, obj, None))

    return StagingParse(fm, rows, naive_count, fm_err)


def parse_capture(path: Path) -> CaptureParse:
    """Split a capture into per-URL blocks.

    Block text EXCLUDES the marker lines themselves — a quote must be found in
    the vendor's own page text, not in scaffolding we wrote.
    """
    text = path.read_text(encoding="utf-8")
    blocks: Dict[str, str] = {}
    errors: List[str] = []
    duplicates: List[str] = []

    open_url: Optional[str] = None
    open_line = 0
    buf: List[str] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        begin = BEGIN_RE.match(line)
        end = END_RE.match(line)
        if begin:
            url = begin.group("url").strip()
            if open_url is not None:
                errors.append(
                    f"line {line_no}: BEGIN {url!r} while {open_url!r} "
                    f"(opened line {open_line}) is still open"
                )
                open_url = None
                buf = []
            open_url, open_line, buf = url, line_no, []
            continue
        if end:
            url = end.group("url").strip()
            if open_url is None:
                errors.append(f"line {line_no}: END {url!r} with no matching BEGIN")
                continue
            if url != open_url:
                errors.append(
                    f"line {line_no}: END {url!r} does not match BEGIN {open_url!r} "
                    f"(opened line {open_line})"
                )
                open_url, buf = None, []
                continue
            if url in blocks:
                duplicates.append(url)
                blocks[url] = blocks[url] + "\n" + "\n".join(buf)
            else:
                blocks[url] = "\n".join(buf)
            open_url, buf = None, []
            continue
        if open_url is not None:
            buf.append(line)

    if open_url is not None:
        errors.append(f"BEGIN {open_url!r} (line {open_line}) is never closed")

    return CaptureParse(blocks, errors, duplicates)


_QUOTE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "′": "'", "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
}


def normalise_for_match(s: str) -> str:
    """NFKC + quote/dash/whitespace folding. NOTHING ELSE.

    Never normalise spelling. Vendor typos are evidence; correcting one breaks
    the match correctly. (spec §G3)
    """
    s = unicodedata.normalize("NFKC", s)
    s = "".join(_QUOTE_MAP.get(ch, ch) for ch in s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()
