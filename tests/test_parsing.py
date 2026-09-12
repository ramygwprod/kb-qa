"""Format detection across the three serialisations the estate contains.

These exist because of a real failure. The parser recognised a ```json fence
and assumed the body was a JSON array. One collector era writes one object per line inside
that fence, which is not valid JSON as a whole, so `json.loads` failed with
"Extra data" and the batch was reported as **zero rows** — silently, on the only
nine batches in the estate that had captures and could therefore be grounded at
all. An estate audit read 0% verifiable as a result.

The lesson these tests encode: a decode failure in one shape is a signal to try
the other, not a verdict about the file. And the naive cross-check must follow
the format, because `^{"id"` counts nothing in a pretty-printed array and
`^\\s*"id":` counts nothing in JSONL — using the wrong one fails a batch for a
reason that is not true of it.
"""

from pathlib import Path

import pytest

from kbqa.parsing import parse_staging

FM = "---\nbatch: widgets\nvendor: Acme\n---\n\n# Staging\n\n"

ROWS = [
    '{"id": "acme.a", "vendor_term": "A"}',
    '{"id": "acme.b", "vendor_term": "B"}',
    '{"id": "acme.c", "vendor_term": "C"}',
]


def _write(tmp_path, body) -> Path:
    p = tmp_path / "_collect-widgets-staging.md"
    p.write_text(FM + body, encoding="utf-8")
    return p


def _ok(parsed):
    return [r for r in parsed.rows if r.obj is not None]


# --------------------------------------------------------------------------
# The three formats
# --------------------------------------------------------------------------

def test_bare_jsonl(tmp_path):
    """What the spec describes: one object per line, column 0, no fence."""
    p = parse_staging(_write(tmp_path, "\n".join(ROWS) + "\n"))
    assert p.row_format == "jsonl"
    assert len(_ok(p)) == 3
    assert p.naive_count == 3


def test_fenced_array(tmp_path):
    """A pretty-printed JSON array inside a fence."""
    body = '```json\n[\n{\n  "id": "acme.a"\n},\n{\n  "id": "acme.b"\n}\n]\n```\n'
    p = parse_staging(_write(tmp_path, body))
    assert p.row_format == "fenced-array"
    assert len(_ok(p)) == 2
    assert p.naive_count == 2


def test_fenced_jsonl(tmp_path):
    """The regression: JSONL inside a ```json fence.

    Reported as zero rows before the fix, because the fence body is not one
    JSON value.
    """
    body = "```json\n" + "\n".join(ROWS) + "\n```\n"
    p = parse_staging(_write(tmp_path, body))
    assert p.row_format == "fenced-jsonl"
    assert len(_ok(p)) == 3, "fenced JSONL must not be reported as zero rows"
    assert p.naive_count == 3


# --------------------------------------------------------------------------
# The cross-check must follow the format
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body,fmt",
    [
        ("\n".join(ROWS) + "\n", "jsonl"),
        ("```json\n" + "\n".join(ROWS) + "\n```\n", "fenced-jsonl"),
        ('```json\n[\n{\n  "id": "a"\n},\n{\n  "id": "b"\n}\n]\n```\n', "fenced-array"),
    ],
)
def test_naive_count_agrees_with_the_parse(tmp_path, body, fmt):
    """§G2 FAILs when parser and naive count disagree.

    A per-format naive pattern is what stops that firing on a correct parse.
    """
    p = parse_staging(_write(tmp_path, body))
    assert p.row_format == fmt
    assert p.naive_count == len(_ok(p))


# --------------------------------------------------------------------------
# Genuine failure is still a failure
# --------------------------------------------------------------------------

def test_a_fence_that_is_neither_shape_is_reported(tmp_path):
    """Falling back must not become 'accept anything'."""
    body = "```json\nthis is not JSON at all\nnor is this\n```\n"
    p = parse_staging(_write(tmp_path, body))
    assert not _ok(p)
    assert any(r.error for r in p.rows), "an unreadable fence must produce a finding"


def test_one_bad_line_in_fenced_jsonl_does_not_discard_the_good_ones(tmp_path):
    body = "```json\n" + ROWS[0] + '\n{"id": "broken",\n' + ROWS[2] + "\n```\n"
    p = parse_staging(_write(tmp_path, body))
    assert p.row_format == "fenced-jsonl"
    assert len(_ok(p)) == 2
    assert len([r for r in p.rows if r.obj is None]) == 1


def test_fenced_jsonl_line_numbers_point_at_the_row(tmp_path):
    """A finding must point somewhere useful in a 4,000-line file."""
    body = "```json\n" + "\n".join(ROWS) + "\n```\n"
    path = _write(tmp_path, body)
    p = parse_staging(path)
    lines = path.read_text().splitlines()
    for r in p.rows:
        assert lines[r.line_no - 1].strip().startswith('{"id"')


def test_empty_fence_is_not_a_row(tmp_path):
    p = parse_staging(_write(tmp_path, "```json\n```\n"))
    assert not _ok(p)
