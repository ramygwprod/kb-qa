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


# --------------------------------------------------------------------------
# D-009 — the denominator glob, corrected against a real corpus
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "_denominator.md",                      # 18 of 20 in the real estate
    "_denominator-llmstxt-2026-08-23.md",   # 1 of 20
    "_denominator-docs.md",                 # 1 of 20
])
def test_denominator_glob_matches_the_forms_that_exist(name):
    """`_denominator-*.md` was inferred from a spec and matched 2 files in 20.

    G4 runs only when a denominator is given, so the 18 bare `_denominator.md`
    files meant G4 quietly did not run for 18 of 19 subjects — reported as a
    Coverage line rather than a failure. Zero findings and zero visibility
    looking identical is the failure this package exists to prevent.
    """
    import fnmatch

    from kbqa.conventions import DEFAULT

    assert fnmatch.fnmatch(name, DEFAULT.denominator_glob)


@pytest.mark.parametrize("name", [
    "_denominator.md.superseded-2026-08-01",  # a tombstone is not a denominator
    "denominator.md",                          # no leading underscore
    "_capture-x.raw.txt",                      # a different artifact entirely
])
def test_denominator_glob_stays_narrow_enough(name):
    """Widening a glob until it matches everything is not a fix."""
    import fnmatch

    from kbqa.conventions import DEFAULT

    assert not fnmatch.fnmatch(name, DEFAULT.denominator_glob)


# --------------------------------------------------------------------------
# Two shapes that cost 962 rows their visibility
# --------------------------------------------------------------------------

def _staging(tmp_path, body, name="_collect-x-staging.md"):
    f = tmp_path / name
    f.write_text("---\nbatch: x\n---\n\n" + body, encoding="utf-8")
    return f


ROW_A = '{"id": "acme.a", "vendor_term": "A", "source_url": "https://d.test/a"}'
ROW_B = '{"id": "acme.b", "vendor_term": "B", "source_url": "https://d.test/b"}'


def test_an_array_written_one_object_per_line_parses(tmp_path):
    """`{...},` — the trailing comma made every line "Extra data".

    797 rows in one batch and 108 in another. Not malformed data: an ordinary
    JSON array, written the way a human writes one.
    """
    body = "```json\n[\n" + ROW_A + ",\n" + ROW_B + "\n]\n```\n"
    p = parse_staging(_staging(tmp_path, body))
    assert [r.obj["id"] for r in p.rows if r.obj] == ["acme.a", "acme.b"]
    assert not [r for r in p.rows if r.error]


def test_a_pretty_printed_object_spanning_lines_parses(tmp_path):
    """`{` alone on a line failed with "Expecting property name" at column 2.

    41, 11 and 5 rows across three batches — all of them ordinary JSON.
    """
    body = (
        '{\n  "id": "acme.a",\n  "vendor_term": "A"\n}\n'
        '{\n  "id": "acme.b",\n  "vendor_term": "B"\n}\n'
    )
    p = parse_staging(_staging(tmp_path, body))
    assert [r.obj["id"] for r in p.rows if r.obj] == ["acme.a", "acme.b"]


def test_a_brace_inside_a_string_does_not_end_the_object(tmp_path):
    """A quote is evidence and may contain anything, braces included."""
    body = '{\n  "id": "acme.a",\n  "source_quote": "use {curly} braces \\" here"\n}\n'
    p = parse_staging(_staging(tmp_path, body))
    ok = [r for r in p.rows if r.obj]
    assert len(ok) == 1
    assert "{curly}" in ok[0].obj["source_quote"]


def test_a_broken_row_in_a_one_per_line_block_still_costs_one_row(tmp_path):
    """The resilience brace-accumulation would have destroyed.

    Accumulating by depth lets one unclosed object swallow every good row after
    it, turning a single corrupt row into a lost block. The shape is chosen by
    majority vote before parsing so this case keeps its old behaviour.
    """
    body = "```json\n" + ROW_A + '\n{"id": "broken",\n' + ROW_B + "\n```\n"
    p = parse_staging(_staging(tmp_path, body))
    assert len([r for r in p.rows if r.obj]) == 2
    assert len([r for r in p.rows if r.error]) == 1


def test_an_unclosed_object_in_a_pretty_block_is_reported_not_silent(tmp_path):
    body = '{\n  "id": "acme.a",\n  "vendor_term": "A"\n'
    p = parse_staging(_staging(tmp_path, body))
    assert any(r.error and "never closed" in r.error for r in p.rows)


def test_the_reported_line_is_where_the_object_started(tmp_path):
    """A finding must point at something a reader can find."""
    body = '{\n  "id": "acme.a",\n  "vendor_term": "A"\n}\n'
    p = parse_staging(_staging(tmp_path, body))
    ok = [r for r in p.rows if r.obj][0]
    assert ok.line_no == 5, f"object starts on line 5, reported {ok.line_no}"
