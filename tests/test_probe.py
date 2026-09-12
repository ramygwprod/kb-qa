"""The probe's contract is a confidentiality one, so that is what is tested.

`kbqa probe` exists to let an operator describe a real staging file to a checker
that must not read it. If any row content reaches the report, the probe has not
merely a bug but a hole in the isolation the whole design rests on.

So the load-bearing tests here are the leak tests. The format-reporting tests
are secondary: a probe that reports nothing is useless, but a probe that reports
too much is worse than none, because it looks safe.
"""

import json

import pytest

from kbqa import cli
from kbqa.parsing import parse_staging


def _probe(capsys, *args) -> str:
    code = cli.main(["probe", *args])
    assert code == 0
    return capsys.readouterr().out


# --------------------------------------------------------------------------
# Leak tests — the reason this module exists
# --------------------------------------------------------------------------

def test_no_source_quote_reaches_the_report(fx, capsys):
    """A quote in the report would hand the checker the evidence verbatim."""
    d = fx("good")
    staging = d / "_collect-widgets-staging.md"
    out = _probe(capsys, "--staging", str(staging))

    quotes = [r.obj["source_quote"] for r in parse_staging(staging).rows if r.obj]
    assert quotes, "fixture must contain quotes for this test to mean anything"
    for q in quotes:
        assert q not in out, f"source_quote leaked: {q!r}"
        # Also reject substantial fragments — a truncated quote still discloses.
        assert q[:25] not in out, f"source_quote prefix leaked: {q[:25]!r}"


def test_no_source_url_reaches_the_report(fx, capsys):
    d = fx("good")
    staging = d / "_collect-widgets-staging.md"
    out = _probe(capsys, "--staging", str(staging))

    urls = [r.obj["source_url"] for r in parse_staging(staging).rows if r.obj]
    assert urls
    for u in urls:
        assert u not in out, f"source_url leaked: {u!r}"


def test_no_free_text_field_reaches_the_report(fx, capsys):
    """vendor_term and what_it_does identify the product. Neither may appear."""
    d = fx("good")
    staging = d / "_collect-widgets-staging.md"
    out = _probe(capsys, "--staging", str(staging))

    for row in (r.obj for r in parse_staging(staging).rows if r.obj):
        for field in ("vendor_term", "what_it_does"):
            value = row.get(field)
            if value:
                assert value not in out, f"{field} leaked: {value!r}"


def test_capture_body_never_reaches_the_report(fx, capsys):
    """The capture is the vendor's own page text — the most sensitive input."""
    d = fx("good")
    capture = d / "_capture-widgets.raw.txt"
    out = _probe(capsys, "--capture", str(capture))

    for line in capture.read_text().splitlines():
        stripped = line.strip()
        if len(stripped) < 20 or stripped.startswith("====="):
            continue
        assert stripped not in out, f"capture body leaked: {stripped!r}"


def test_enum_values_are_disclosed_deliberately(fx, capsys):
    """Contract enums ARE shown — they describe the schema, not the vendor.

    Pinned so that narrowing the leak tests can never silently gut the probe's
    usefulness: these values must keep appearing.
    """
    d = fx("good")
    out = _probe(capsys, "--staging", str(d / "_collect-widgets-staging.md"))
    assert "official-doc" in out
    assert "outcome" in out


def _fenced(tmp_path, vendor_term="REST API", extra=""):
    """The serialisation the collector actually writes: a fenced JSON array."""
    f = tmp_path / "_collect-devdocs-staging.md"
    f.write_text(
        "---\n"
        "code: X-1\nnature: catalogue\nstage: silver\n"
        "entity: Acme\ntype: collect\nstatus: draft\n"
        "last_updated: 2026-08-02\n"
        "---\n\n"
        "```json\n"
        "[\n"
        "{\n"
        '  "id": "acme.rest",\n'
        f'  "vendor_term": "{vendor_term}",\n'
        '  "what_it_does": "Programmatic access to the platform.",\n'
        '  "source_url": "https://docs.acme.test/rest",\n'
        '  "source_quote": "The REST API accepts JSON payloads.",\n'
        '  "access_date": "2026-08-02"' + extra + "\n"
        "}\n"
        "]\n"
        "```\n",
        encoding="utf-8",
    )
    return f


def test_short_values_do_not_leak_from_the_fenced_format(tmp_path, capsys):
    """Regression: redaction was length-based and let short values through.

    On the pretty-printed array format every value sits on its own line, so a
    short product name reached the report verbatim. Length is not a proxy for
    sensitivity — a product name is usually short.
    """
    f = _fenced(tmp_path, vendor_term="REST API")
    out = _probe(capsys, "--staging", str(f))
    assert "REST API" not in out, "short vendor_term leaked from a fenced array"
    assert "Programmatic access" not in out
    assert "accepts JSON payloads" not in out
    assert "docs.acme.test" not in out


def test_fenced_array_is_detected_and_parsed(tmp_path, capsys):
    f = _fenced(tmp_path)
    out = _probe(capsys, "--staging", str(f))
    assert "detected format               : fenced-array" in out
    assert "rows parsed                   : 1" in out
    assert "VERDICT: parser MATCHES this file" in out


def test_fenced_array_reports_fields_outside_the_contract(tmp_path, capsys):
    f = _fenced(tmp_path, extra=',\n  "node_kind": "PLATFORM"')
    out = _probe(capsys, "--staging", str(f))
    assert "node_kind" in out, "an unknown field must be surfaced, not silently dropped"
    assert "in rows, absent from contract" in out


# --------------------------------------------------------------------------
# Format reporting
# --------------------------------------------------------------------------

def test_reports_naive_count_matching_the_spec_crosscheck(fx, capsys):
    d = fx("good")
    out = _probe(capsys, "--staging", str(d / "_collect-widgets-staging.md"))
    assert 'lines matching ^{"id"' in out
    assert "rows parsed" in out
    assert "detected format               : jsonl" in out


def test_flags_fields_outside_the_contract(fx, capsys):
    """An invented field is what §2's extra='forbid' exists to catch."""
    d = fx("bad_extra_field")
    out = _probe(capsys, "--staging", str(d / "_collect-widgets-staging.md"))
    assert "in rows, absent from contract" in out
    assert "'confidence_note'" in out or "confidence_note" in out


def test_verdict_reports_mismatch_when_frontmatter_is_absent(tmp_path, capsys):
    """The case this tool is built for: the inferred format is simply wrong."""
    f = tmp_path / "_collect-x-staging.md"
    f.write_text(
        "# Not the expected shape at all\n"
        '{"id": "a.b", "vendor_term": "x"}\n',
        encoding="utf-8",
    )
    out = _probe(capsys, "--staging", str(f))
    assert "DOES NOT MATCH" in out
    assert "opens with '---': False" in out


def test_verdict_matches_on_a_wellformed_file(fx, capsys):
    d = fx("good")
    out = _probe(capsys, "--staging", str(d / "_collect-widgets-staging.md"))
    assert "VERDICT: parser MATCHES this file" in out


def test_malformed_json_row_is_reported_without_echoing_the_row(tmp_path, capsys):
    secret = "Acme Turbo Widget Pro"
    f = tmp_path / "_collect-x-staging.md"
    f.write_text(
        "---\nbatch: x\n---\n"
        '{"id": "a.b", "vendor_term": "' + secret + '"\n',  # missing brace
        encoding="utf-8",
    )
    out = _probe(capsys, "--staging", str(f))
    assert "invalid JSON" in out
    assert secret not in out, "a broken row must not be echoed to show what broke"


# --------------------------------------------------------------------------
# CLI behaviour
# --------------------------------------------------------------------------

def test_probe_needs_a_target(capsys):
    assert cli.main(["probe"]) == 1


def test_probe_rejects_unknown_flags(capsys):
    assert cli.main(["probe", "--rows", "x"]) == 1


def test_probe_never_exits_2(tmp_path):
    """Exit 2 means DECLINED. A diagnostic must never be readable as one."""
    missing = tmp_path / "nope.md"
    assert cli.main(["probe", "--staging", str(missing)]) != 2


def test_probe_writes_no_files(fx, capsys):
    """Read-only, like every gate. A diagnostic that mutates is not a diagnostic."""
    d = fx("good")
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    _probe(capsys, "--staging", str(d / "_collect-widgets-staging.md"),
           "--capture", str(d / "_capture-widgets.raw.txt"))
    after = {p.name: p.read_bytes() for p in d.iterdir()}
    assert before == after
    assert sorted(before) == sorted(after), "probe created or removed a file"


# --------------------------------------------------------------------------
# Prose leak — found by running the probe against a real estate
# --------------------------------------------------------------------------

DOCUMENT = """---
code: D-014
nature: ruling
stage: phase-a
status: closed
owner: someone
last_updated: 2026-08-01
---

# Northwind Phase A — sitemap skeleton COMPLETE (9/9 surfaces)

The nine ids are present and untouched: `northwind.arabic-model` ·
`northwind.platform` · `northwind.datasphere`.

| surface | state |
|---|---|
| catalogue | closed |

> Corrected 2026-08-01: this previously read COMPLETE, which was an overclaim.

- Contoso's twenty workflow families were skipped entirely.
"""

SECRETS = [
    "Northwind", "northwind", "Contoso", "Datasphere", "datasphere",
    "arabic-model", "workflow families", "sitemap skeleton", "overclaim",
    "D-014", "catalogue",
]


def test_prose_body_lines_do_not_reach_the_report(tmp_path, capsys):
    """`_line_shape` redacts quoted values. Markdown prose has no quotes.

    Found by probing a real estate: the "other body lines" section printed
    headings, list items and sentences verbatim — vendor names and ids included
    — under a banner promising none of that appears. The line's KIND is
    structural; its text never is.
    """
    f = tmp_path / "_collect-phaseA-staging.md"
    f.write_text(DOCUMENT, encoding="utf-8")
    out = _probe(capsys, "--staging", str(f))

    leaked = [s for s in SECRETS if s in out]
    assert not leaked, f"prose reached the report: {leaked}"


def test_prose_lines_are_still_described(tmp_path, capsys):
    """Redaction that reports nothing is not safety, it is uselessness."""
    f = tmp_path / "_collect-phaseA-staging.md"
    f.write_text(DOCUMENT, encoding="utf-8")
    out = _probe(capsys, "--staging", str(f))

    assert "heading h1" in out
    assert "list item" in out
    assert "table row" in out
    assert "blockquote" in out


def test_a_document_is_not_reported_as_a_parser_failure(tmp_path, capsys):
    """No provenance and no rows means it is not a batch — not a broken parser.

    Saying "parser DOES NOT MATCH" here sends the reader to parsing.py to fix
    something that is not wrong, and hides the real finding: whatever matched
    this filename is a document.
    """
    f = tmp_path / "_collect-phaseA-staging.md"
    f.write_text(DOCUMENT, encoding="utf-8")
    out = _probe(capsys, "--staging", str(f))

    assert "VERDICT: this file is NOT a collection batch" in out
    assert "DOES NOT MATCH" not in out
    assert "parsing.py needs correcting" not in out
    assert "batch frontmatter : NONE" in out


def test_rows_without_provenance_are_still_a_batch(tmp_path, capsys):
    """Rows with no frontmatter are a G1 problem, not a reason to disown them."""
    f = tmp_path / "_collect-x-staging.md"
    f.write_text('{"id": "a.b", "vendor_term": "x"}\n', encoding="utf-8")
    out = _probe(capsys, "--staging", str(f))

    assert "NOT a collection batch" not in out
