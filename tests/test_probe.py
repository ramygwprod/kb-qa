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


# --------------------------------------------------------------------------
# Format reporting
# --------------------------------------------------------------------------

def test_reports_naive_count_matching_the_spec_crosscheck(fx, capsys):
    d = fx("good")
    out = _probe(capsys, "--staging", str(d / "_collect-widgets-staging.md"))
    assert 'lines matching ^{"id"' in out
    assert "parse as JSON objects" in out


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
