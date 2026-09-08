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

# §G2 requires a naive cross-check that a broken parser cannot also get wrong.
# Which naive count is meaningful depends on how rows are serialised, so there
# is one per format and the verdict records which was used.
#
# jsonl        — one object per line at column 0, as the spec's `grep -c '^{"id"'`
#                describes.
# fenced-array — a pretty-printed JSON array inside a ```json block, which is
#                what the collector actually writes. `^{"id"` matches nothing
#                here, so counting `"id":` keys at any indent is the equivalent.
NAIVE_ROW_RE = re.compile(r'^\{"id"')
NAIVE_KEY_RE = re.compile(r'^\s*"id"\s*:')

FENCE_OPEN_RE = re.compile(r"^\s*```+\s*json\s*$", re.IGNORECASE)
FENCE_CLOSE_RE = re.compile(r"^\s*```+\s*$")

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
    row_format: str = "unknown"
    declared_pages: Tuple[str, ...] = ()
    pages_source: str = "none"


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
    current_scalar_key: Optional[str] = None
    for i, line in enumerate(lines[1:], start=2):
        if line.strip() == FRONTMATTER_DELIM:
            return out, None
        if not line.strip():
            continue

        list_item = re.match(r"^\s+-\s+(?P<item>.+?)\s*$", line)
        if list_item and current_list_key:
            out[current_list_key].append(_parse_scalar(list_item.group("item")))
            continue

        # Indented continuation of the previous scalar — a folded value:
        #
        #   scope: |
        #     The 8 pages under
        #     https://example/..., fetched as .md.
        #
        # Real collector frontmatter uses these for prose. Rejecting them made
        # the whole frontmatter unparseable, which cascaded into false
        # `no_declared_pages` and `capture_hash_absent` findings on batches
        # whose frontmatter was fine.
        if line[:1] in (" ", "\t"):
            if current_scalar_key is not None:
                out[current_scalar_key] = (
                    f"{out[current_scalar_key]} {line.strip()}".strip()
                )
                continue
            # `key:` with nothing after it, then indented prose rather than
            # list items — a block scalar whose shape only became clear here.
            if current_list_key is not None and out.get(current_list_key) == []:
                current_scalar_key, current_list_key = current_list_key, None
                out[current_scalar_key] = line.strip()
                continue

        kv = re.match(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<val>.*)$", line)
        if not kv:
            return out, f"unparseable frontmatter at line {i}: {line!r}"
        key, val = kv.group("key"), kv.group("val").strip()
        if val == "" or val in ("|", ">", "|-", ">-"):
            # Either a list about to follow, or a block scalar. Which it is
            # only becomes clear on the next line, so allow both.
            out[key] = [] if val == "" else ""
            current_list_key = key if val == "" else None
            current_scalar_key = None if val == "" else key
        else:
            out[key] = _parse_scalar(val)
            current_list_key = None
            current_scalar_key = key
    return out, "frontmatter is not terminated by '---'"


MD_TABLE_URL_RE = re.compile(r"^\s*\|[^|]*?(?P<url>https?://[^\s|]+)")


def _declared_pages(fm: dict, lines: List[str], fences) -> Tuple[Tuple[str, ...], str]:
    """The batch's per-page declaration — §G1's "staging per-page declaration".

    Two conventions exist in the estate and both are legitimate:

      frontmatter   `pages:` as a YAML list
      table         a markdown table whose first cell is the page URL

    G1 originally read only the frontmatter, so a batch declaring its pages in a
    table was reported `no_declared_pages` — a finding that was simply untrue of
    it, and which would have sent a maker looking for a list that was never the
    convention there.

    Rows inside a ```json fence are excluded: a `source_url` in a row is a
    citation, not a declaration, and counting it would make the declaration
    agree with the rows by construction.
    """
    fm_pages = fm.get("pages")
    if isinstance(fm_pages, list) and fm_pages:
        return tuple(str(p).strip() for p in fm_pages), "frontmatter"

    in_fence = {
        n for open_at, close_at in fences for n in range(open_at, close_at + 1)
    }
    urls: List[str] = []
    for n, line in enumerate(lines, start=1):
        if n in in_fence:
            continue
        m = MD_TABLE_URL_RE.match(line)
        if m:
            url = m.group("url").rstrip(",.;")
            if url not in urls:
                urls.append(url)
    if urls:
        return tuple(urls), "table"
    return (), "none"


def _find_json_fences(lines: List[str]) -> List[Tuple[int, int]]:
    """Return (open_line, close_line) 1-based pairs for ```json blocks."""
    spans: List[Tuple[int, int]] = []
    open_at: Optional[int] = None
    for i, line in enumerate(lines, start=1):
        if open_at is None:
            if FENCE_OPEN_RE.match(line):
                open_at = i
            continue
        if FENCE_CLOSE_RE.match(line):
            spans.append((open_at, i))
            open_at = None
    if open_at is not None:
        spans.append((open_at, len(lines)))  # unterminated; G2 will see the error
    return spans


def _parse_jsonl_lines(lines: List[str], start: int, stop: int) -> List[RowParse]:
    """Parse a line range as one JSON object per line."""
    rows: List[RowParse] = []
    for n in range(start, stop):
        line = lines[n - 1]
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            rows.append(RowParse(n, line, None, f"invalid JSON: {exc.msg}"))
            continue
        if not isinstance(obj, dict):
            rows.append(RowParse(n, line, None, "row is not a JSON object"))
            continue
        rows.append(RowParse(n, line, obj, None))
    return rows


def _parse_fences(lines: List[str]) -> Tuple[List[RowParse], List[str], str]:
    """Parse every ```json fence. Returns (rows, errors, format).

    A fence holds one of two things, and the estate contains both:

      fenced-array  a pretty-printed JSON array — the whole body is one value
      fenced-jsonl  one JSON object per line, concatenated inside the fence

    The second is not valid JSON as a whole: `json.loads` on the body fails with
    "Extra data" at the second object. Treating that as an unreadable fence
    reported 181 real rows as zero — silently, on the only batches in the estate
    that had captures and could therefore be grounded at all.

    So a decode failure is a signal to try the other shape, not a verdict. Only
    when neither yields a row is the fence genuinely unreadable.
    """
    rows: List[RowParse] = []
    errors: List[str] = []
    shapes: List[str] = []

    for open_at, close_at in _find_json_fences(lines):
        body = "\n".join(lines[open_at:close_at - 1])
        if not body.strip():
            continue

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            jsonl_rows = _parse_jsonl_lines(lines, open_at + 1, close_at)
            if any(r.obj is not None for r in jsonl_rows):
                rows.extend(jsonl_rows)
                shapes.append("fenced-jsonl")
                continue
            errors.append(
                f"```json fence at line {open_at} parses as neither a JSON array "
                f"nor one object per line: {exc.msg} "
                f"(line {open_at + exc.lineno}, col {exc.colno})"
            )
            continue

        items = payload if isinstance(payload, list) else [payload]
        # Line numbers are approximated from each object's `"id"` key so a
        # finding points somewhere useful in a 4,000-line file, not at the fence.
        id_lines = [
            n for n in range(open_at, close_at) if NAIVE_KEY_RE.match(lines[n - 1])
        ]
        for idx, obj in enumerate(items):
            line_no = id_lines[idx] if idx < len(id_lines) else open_at
            if not isinstance(obj, dict):
                rows.append(RowParse(line_no, "", None, "row is not a JSON object"))
                continue
            rows.append(RowParse(line_no, "", obj, None))
        shapes.append("fenced-array")

    fmt = "fenced-array"
    if shapes:
        fmt = "fenced-jsonl" if all(s == "fenced-jsonl" for s in shapes) else (
            "fenced-mixed" if len(set(shapes)) > 1 else shapes[0]
        )
    return rows, errors, fmt


def parse_staging(path: Path) -> StagingParse:
    """Parse a staging file in any serialisation the estate contains.

    Three exist, written by different collector eras:

      jsonl         one object per line at column 0 — what the spec describes
      fenced-array  a pretty-printed JSON array inside a ```json fence
      fenced-jsonl  one object per line, inside a ```json fence

    `row_format` records which was found. A silent fallback between formats is
    how a parser starts disagreeing with the file it claims to have read, so the
    format is reported rather than inferred and forgotten.

    The naive cross-check (§G2) is per-format: `^{"id"` counts nothing in a
    pretty-printed array, and `^\\s*"id":` counts nothing in JSONL. Using the
    wrong one would make the cross-check disagree with a correct parse and fail
    the batch for a reason that is not true of it.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    fm, fm_err = _parse_frontmatter(text)

    fences = _find_json_fences(lines)
    if fences:
        rows, fence_errors, fmt = _parse_fences(lines)
        pages, pages_src = _declared_pages(fm, lines, fences)
        naive_re = NAIVE_ROW_RE if fmt == "fenced-jsonl" else NAIVE_KEY_RE
        naive_count = sum(
            1
            for open_at, close_at in fences
            for n in range(open_at, close_at)
            if naive_re.match(lines[n - 1])
        )
        if fence_errors and not rows:
            rows = [RowParse(fences[0][0], "", None, e) for e in fence_errors]
        return StagingParse(fm, rows, naive_count, fm_err, fmt, pages, pages_src)

    rows = []
    naive_count = 0
    for line_no, line in enumerate(lines, start=1):
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

    pages, pages_src = _declared_pages(fm, lines, [])
    return StagingParse(fm, rows, naive_count, fm_err, "jsonl", pages, pages_src)


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
