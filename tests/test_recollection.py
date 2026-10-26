"""v6.23.0 — change detection for re-collection (package D).

A subject collected again gets a new dated denominator and new windows; the
rows of the first collection are never edited. A page whose text hash equals
its latest earlier capture is marked `unchanged_since` in the receipt, listed
for the row-writer with the rows already recorded for it, and drafted as one
`unchanged` line — accepted by `kbqa stage` only when the hash matches, turned
into nothing new in the staging file and one stop line. `kbqa compare` then
says, per page and per feature, what was added, removed, changed or unchanged —
added or removed only when the other side's coverage is complete, otherwise
unknown, with why.
"""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from kbqa import capture, cli, collect_surface, compare, fetch, stage, stops
from kbqa.gates import g4_completeness
from kbqa.parsing import parse_staging
from test_capture import HOST, SeqWeb

DAY1, DAY2, DAY3 = "2026-10-18", "2026-10-25", "2026-11-01"
U = {i: f"https://{HOST}/p{i}" for i in range(1, 8)}


def _md(title: str, sentence: str) -> bytes:
    return f"# {title}\n\n{sentence}\n".encode()


FIRST = {1: _md("Digest", "Page one sends a daily digest to every member."),
         2: _md("Reports", "Page two exports reports as CSV."),
         3: _md("Pricing", "See our plans."),
         5: _md("Fax", "Page five sends a fax from any record.")}
SECOND = {1: FIRST[1],                                            # unchanged
          2: _md("Reports", "Page two exports reports as CSV and PDF."),  # changed
          3: FIRST[3],                                            # unchanged, drafted no_row before
          4: _md("Webhooks", "Page four calls a webhook on every change.")}  # new


def _judgement(term, **extra):
    return {"vendor_term": term, "what_it_does": f"{term} does one thing.", "evidence_grade": "official-doc",
            "confidence": "high", "mechanism": "Native", "outcome": "yes", **extra}


def _row(n, quote, term, **extra):
    return {"page": U[n], "part": 0, "quote": quote, **_judgement(term, **extra)}


def _run(mod, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mod.run(list(args))
    text = out.getvalue()
    try:
        return code, json.loads(text)
    except ValueError:
        return code, text


def _den(subject, day, nums, source=f"https://{HOST}/llms.txt"):
    den = subject / f"_denominator-docs-{day}.md"
    den.write_text(f"Index: docs, rung 1 — {source}\n" + "".join(f"- [P{i}]({U[i]})\n" for i in nums))
    return den


def _collect(subject, monkeypatch, day, pages, nums, **den_kw):
    """One collection's capture: its own denominator and one window of it."""
    (subject / f"_robots-{HOST}-{day}.txt").write_text("User-agent: *\nAllow: /\n")
    monkeypatch.setattr(fetch, "_open", SeqWeb({U[i]: (200, body, "text/markdown") for i, body in pages.items()}))
    den = _den(subject, day, nums, **den_kw)
    code, r = _run(capture, "--out", str(subject), "--surface", "docs", "--date", day, "--denominator", str(den))
    assert "refused" not in r, r
    cap = r.get("capture")
    if cap:  # the rows come well after the capture (G1's order), as test_capture._cap does
        t = Path(cap).stat().st_mtime - 60
        os.utime(cap, (t, t))
    return r


def _drafts(subject, batch, *objs):
    (subject / stage.draft_name(batch)).write_text("".join(json.dumps(o) + "\n" for o in objs))


def _stage(subject, batch, *extra):
    return _run(stage, "--subject", str(subject), "--batch", batch, *extra)


def _add_stops(subject, lines):
    for ln in lines:
        stops.add(subject, ln)


def _page(receipt, n):
    return next(p for p in receipt["pages"] if p["url"] == U[n])


@pytest.fixture
def first(tmp_path, monkeypatch):
    """The first collection, staged, its no-row page stopped."""
    d = tmp_path / "Example-Co"
    d.mkdir()
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    r1 = _collect(d, monkeypatch, DAY1, FIRST, (1, 2, 3, 5))
    b1 = r1["batch"]
    assert _stage(d, b1, "--lists")[0] == 0
    _drafts(d, b1, _row(1, "Page one sends a daily digest to every member.", "Daily digest"),
            _row(2, "Page two exports reports as CSV.", "Report export"),
            {"page": U[3], "no_row": "pricing page"},
            _row(5, "Page five sends a fax from any record.", "Fax"))
    code, out = _stage(d, b1)
    assert code == 0, out
    _add_stops(d, out["stop_lines_to_add"])
    return d, b1


def _snapshot(d):
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture
def second(first, monkeypatch):
    """The subject collected again: a new dated denominator and its window."""
    d, b1 = first
    r2 = _collect(d, monkeypatch, DAY2, SECOND, (1, 2, 3, 4))
    return d, b1, r2


# ── the receipt ─────────────────────────────────────────────────────────────

def test_a_page_with_the_same_text_hash_is_marked_unchanged_since_its_earlier_batch(second):
    d, b1, r2 = second
    assert _page(r2, 1)["unchanged_since"] == b1
    assert _page(r2, 3)["unchanged_since"] == b1
    assert "unchanged_since" not in _page(r2, 2), "a changed page is drafted again"
    assert "unchanged_since" not in _page(r2, 4), "a new page has no earlier capture"
    # still captured, bytes and text: the evidence of this collection is whole
    assert {p["url"] for p in r2["pages"]} == {U[1], U[2], U[3], U[4]} and r2["capture"]
    on_disk = json.loads((d / "_raw" / r2["batch"] / capture.RECEIPT).read_text())
    assert _page(on_disk, 1)["unchanged_since"] == b1


def test_unchanged_is_against_the_latest_earlier_capture(second, monkeypatch):
    """Changed in the second collection, back to the first text in the third:
    changed since the latest capture, so drafted again."""
    d, b1, r2 = second
    third = dict(SECOND)
    third[2] = FIRST[2]
    r3 = _collect(d, monkeypatch, DAY3, third, (1, 2, 3, 4))
    assert "unchanged_since" not in _page(r3, 2)
    assert _page(r3, 1)["unchanged_since"] == r2["batch"]


def test_a_receipt_without_text_hashes_marks_nothing(first, monkeypatch):
    d, b1 = first
    rec = d / "_raw" / b1 / capture.RECEIPT
    data = json.loads(rec.read_text())
    for p in data["pages"]:
        p.pop("text_sha256")
    rec.write_text(json.dumps(data))
    r2 = _collect(d, monkeypatch, DAY2, SECOND, (1, 2, 3, 4))
    assert not any(p.get("unchanged_since") for p in r2["pages"])


# ── the row-writer's list ───────────────────────────────────────────────────

def test_stage_lists_writes_the_unchanged_pages_with_the_rows_recorded_for_them(second):
    d, b1, r2 = second
    code, out = _stage(d, r2["batch"], "--lists")
    assert code == 0 and out["unchanged"] == f"_raw/{r2['batch']}/{stage.UNCHANGED}", out
    text = (d / out["unchanged"]).read_text()
    assert f"- {U[1]} | unchanged since {b1} | rows recorded in {b1}: example-co.docs.daily-digest" in text
    assert f"- {U[3]} | unchanged since {b1} | no row; stop line: no feature: pricing page" in text
    assert U[2] not in text and U[4] not in text
    by_page = {e["page"]: e for e in out["unchanged_pages"]}
    assert by_page[U[1]]["ids"] == ["example-co.docs.daily-digest"] and by_page[U[1]]["rows_in"] == b1


def test_stage_lists_says_why_no_unchanged_list_is_written(first):
    d, b1 = first
    os.remove(d / stage.conventions().staging_for(b1))  # the lists are refused once staged; a fresh look
    code, out = _stage(d, b1, "--lists")
    assert code == 0 and out["unchanged"] is None and "no page" in out["unchanged_note"]


# ── stage: the unchanged line ───────────────────────────────────────────────

SECOND_DRAFTS = [
    {"page": U[1], "unchanged": None},  # filled with the first batch
    _row(2, "Page two exports reports as CSV and PDF.", "Report export",
         same_feature_as="example-co.docs.report-export"),
    {"page": U[3], "unchanged": None},
    _row(4, "Page four calls a webhook on every change.", "Webhook"),
]


def _second_drafts(b1, **replace):
    out = []
    for o in SECOND_DRAFTS:
        o = dict(o)
        if "unchanged" in o:
            o["unchanged"] = b1
        out.append(replace.get(o["page"], o))
    return out


def test_an_unchanged_page_adds_nothing_to_the_staging_file_and_is_accounted_for(second):
    d, b1, r2 = second
    b2 = r2["batch"]
    before = _snapshot(d)
    _drafts(d, b2, *_second_drafts(b1))
    code, out = _stage(d, b2)
    assert code == 0 and out["rejected"] == 0, out
    rows = [r.obj for r in parse_staging(Path(out["staging"])).rows]
    assert {r["source_url"] for r in rows} == {U[2], U[4]}, "an unchanged page is never staged again"
    assert {e["page"]: e["unchanged_since"] for e in out["unchanged_pages"]} == {U[1]: b1, U[3]: b1}
    assert next(e for e in out["unchanged_pages"] if e["page"] == U[1])["ids"] == ["example-co.docs.daily-digest"]
    assert f"- {U[1]} | no feature: unchanged since {b1}" in out["stop_lines_to_add"]
    assert f"- {U[3]} | no feature: unchanged since {b1}" in out["stop_lines_to_add"]
    assert out["pages_without_row_or_no_row"] == []
    # nothing earlier is edited
    after = _snapshot(d)
    assert {k: v for k, v in after.items() if k in before} == before


def test_g4_counts_an_unchanged_page_once_its_stop_line_is_added(second):
    d, b1, r2 = second
    b2 = r2["batch"]
    _drafts(d, b2, *_second_drafts(b1))
    _, out = _stage(d, b2)
    staging = out["staging"]
    den2 = d / f"_denominator-docs-{DAY2}.md"
    stops_f = d / stops.STOPS_NAME
    v, _ = g4_completeness.coverage(den2, [staging], stops_f)
    # before the lines: the unchanged page with rows earlier is open (p3's earlier stop line still covers it)
    assert [f.where for f in v.findings if f.code == "index_item_without_row"] == [U[1]], v.counts
    _add_stops(d, out["stop_lines_to_add"])
    v, _ = g4_completeness.coverage(den2, [staging], stops_f)
    assert v.verdict == "PASS" and v.counts["existence_stopped"] == 2, v.counts
    findings = []
    w = g4_completeness.read_windows([staging], findings, g4_completeness.stopped_urls(stops_f))
    assert w[0]["rows"] + w[0]["stopped_pages"] >= w[0]["returned"] and not any(
        f.code == "window_underwritten" for f in findings)


def test_an_unchanged_line_for_a_changed_page_is_rejected(second):
    d, b1, r2 = second
    b2 = r2["batch"]
    _drafts(d, b2, *_second_drafts(b1, **{U[2]: {"page": U[2], "unchanged": b1}}))
    code, out = _stage(d, b2)
    assert code == 1 and out["staging"] is None
    (rej,) = out["rejected_lines"]
    assert rej["line"] == 2 and "not unchanged by text hash" in rej["reason"], rej


def test_an_unchanged_line_naming_another_batch_is_rejected(second, monkeypatch):
    d, b1, r2 = second
    r3 = _collect(d, monkeypatch, DAY3, SECOND, (1, 2, 3, 4))
    b3 = r3["batch"]
    assert _page(r3, 1)["unchanged_since"] == r2["batch"]
    # The first batch has the same text hash too, but it is not the latest capture.
    _drafts(d, b3, {"page": U[1], "unchanged": b1}, {"page": U[2], "unchanged": "docs-2026-10-01-w01"},
            {"page": U[3], "no_row": "pricing page"}, {"page": U[4], "unchanged": b3})
    code, out = _stage(d, b3)
    reasons = {r["line"]: r["reason"] for r in out["rejected_lines"]}
    assert code == 1 and set(reasons) == {1, 2, 4}, reasons
    assert f"marks the page unchanged since {r2['batch']}, not since {b1}" in reasons[1]
    assert "has no receipt listing" in reasons[2]
    assert "names no earlier batch" in reasons[4]


def test_an_unchanged_line_with_nothing_recorded_to_stand_is_rejected(tmp_path, monkeypatch):
    d = tmp_path / "Example-Co"
    d.mkdir()
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    r1 = _collect(d, monkeypatch, DAY1, FIRST, (1, 2, 3, 5))  # captured, never staged
    r2 = _collect(d, monkeypatch, DAY2, SECOND, (1, 2, 3, 4))
    assert _page(r2, 1)["unchanged_since"] == r1["batch"]
    _drafts(d, r2["batch"], *_second_drafts(r1["batch"]))
    code, out = _stage(d, r2["batch"])
    reasons = {r["line"]: r["reason"] for r in out["rejected_lines"]}
    assert code == 1 and set(reasons) == {1, 2, 3}, reasons
    assert "nothing is recorded for the page" in reasons[1]


def test_an_unchanged_line_is_exactly_its_two_keys_and_not_beside_rows(second):
    d, b1, r2 = second
    b2 = r2["batch"]
    _drafts(d, b2, {"page": U[1], "unchanged": b1, "note": "x"}, {"page": U[3], "unchanged": b1},
            _row(3, "See our plans.", "Plans"), *_second_drafts(b1)[1:2], *_second_drafts(b1)[3:])
    code, out = _stage(d, b2)
    reasons = {r["line"]: r["reason"] for r in out["rejected_lines"]}
    assert code == 1 and set(reasons) == {1, 2}, reasons
    assert "exactly" in reasons[1]
    assert "drafted `unchanged` but also has rows" in reasons[2]


def test_a_window_unchanged_throughout_writes_no_staging_file(first, monkeypatch):
    d, b1 = first
    r2 = _collect(d, monkeypatch, DAY2, {1: FIRST[1], 3: FIRST[3]}, (1, 3))
    b2 = r2["batch"]
    _drafts(d, b2, {"page": U[1], "unchanged": b1}, {"page": U[3], "unchanged": b1})
    code, out = _stage(d, b2)
    assert code == 0 and out["staging"] is None and out["next_step"] == stage.NO_ROWS_STEP, out
    assert [u["state"] for u in collect_surface.unstaged(d, "docs") if u["batch"] == b2] == [
        collect_surface.ALL_NO_ROW]


def test_recorded_rows_are_followed_back_through_an_unchanged_collection(second, monkeypatch):
    d, b1, r2 = second
    _drafts(d, r2["batch"], *_second_drafts(b1))
    _, out = _stage(d, r2["batch"])
    _add_stops(d, out["stop_lines_to_add"])
    r3 = _collect(d, monkeypatch, DAY3, SECOND, (1, 2, 3, 4))
    rec = stage.recorded(d, U[1], _page(r3, 1)["unchanged_since"])
    assert rec["rows_in"] == b1 and rec["ids"] == ["example-co.docs.daily-digest"] and rec["via"] == [r2["batch"]]
    # a stop line that says "unchanged since" never vouches for itself
    rec3 = stage.recorded(d, U[3], r2["batch"])
    assert rec3["stop_line"] == "no feature: pricing page"
    stops.add(d, f"- {U[6]} | no feature: unchanged since {b1}")
    rec6 = stage.recorded(d, U[6], b1)
    assert "stop_line" not in rec6 and "nothing is recorded" in rec6["why"], rec6


# ── compare ─────────────────────────────────────────────────────────────────

def _compare(d, frm=DAY1, to=DAY2):
    code, out = _run(compare, str(d), "--from", frm, "--to", to, "--json")
    assert code == 0, out
    (s,) = out["surfaces"]
    return s


def _states(entries, key):
    return {e[key]: e["state"] for e in entries}


@pytest.fixture
def both(second):
    """Both collections staged and accounted for: coverage complete on each side."""
    d, b1, r2 = second
    _drafts(d, r2["batch"], *_second_drafts(b1))
    code, out = _stage(d, r2["batch"])
    assert code == 0, out
    _add_stops(d, out["stop_lines_to_add"])
    return d, b1, r2


def test_compare_with_both_sides_complete_says_added_removed_changed_unchanged(both):
    d, b1, r2 = both
    s = _compare(d)
    assert s["from"]["coverage"]["complete"] and s["to"]["coverage"]["complete"], s
    assert _states(s["pages"], "url") == {U[1]: "unchanged", U[2]: "changed", U[3]: "unchanged",
                                          U[4]: "added", U[5]: "removed"}
    assert _states(s["features"], "id") == {
        "example-co.docs.daily-digest": "unchanged",   # its page unchanged: the rows stand
        "example-co.docs.report-export": "changed",    # linked again from its changed page
        "example-co.docs.webhook": "added",
        "example-co.docs.fax": "removed"}              # its page left a complete index
    assert s["page_counts"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 2, "unknown": 0}


def test_compare_with_incomplete_coverage_says_unknown_with_why(second):
    """The later collection not yet accounted for (no staging, no stop lines):
    nothing can be called removed; the earlier one is complete, so added stands."""
    d, b1, r2 = second
    s = _compare(d)
    assert not s["to"]["coverage"]["complete"] and s["from"]["coverage"]["complete"]
    pages = {e["url"]: e for e in s["pages"]}
    assert pages[U[5]]["state"] == "unknown" and "later collection's coverage is not complete" in pages[U[5]]["why"]
    assert pages[U[4]]["state"] == "added"
    assert pages[U[2]]["state"] == "changed", "two captures compare by hash whatever the coverage"
    feats = {e["id"]: e for e in s["features"]}
    assert feats["example-co.docs.fax"]["state"] == "unknown"
    assert feats["example-co.docs.report-export"]["state"] == "unknown"


def test_compare_never_infers_a_feature_removed_from_a_page_not_captured(first, monkeypatch):
    """The page stays in the later index but could not be fetched (a stop line
    accounts for it): coverage is complete, and still its feature is unknown."""
    d, b1 = first
    pages = dict(SECOND)
    r2 = _collect(d, monkeypatch, DAY2, pages, (1, 2, 3, 4, 5))  # p5 answers 404 now
    assert U[5] not in {p["url"] for p in r2["pages"]}
    _drafts(d, r2["batch"], *_second_drafts(b1))
    _, out = _stage(d, r2["batch"])
    _add_stops(d, out["stop_lines_to_add"] + [f"- {U[5]} | unreachable: HTTP 404"])
    s = _compare(d)
    assert s["to"]["coverage"]["complete"]
    p5 = next(e for e in s["pages"] if e["url"] == U[5])
    assert p5["state"] == "unknown" and "not captured (stop line: unreachable: HTTP 404)" in p5["why"]
    fax = next(e for e in s["features"] if e["id"] == "example-co.docs.fax")
    assert fax["state"] == "unknown" and f"its page {U[5]} is not accounted for" in fax["why"], fax


def test_compare_with_the_earlier_side_incomplete_says_unknown_for_added(tmp_path, monkeypatch):
    d = tmp_path / "Example-Co"
    d.mkdir()
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    r1 = _collect(d, monkeypatch, DAY1, FIRST, (1, 2, 3, 5))  # captured, never staged: coverage open
    r2 = _collect(d, monkeypatch, DAY2, SECOND, (1, 2, 3, 4))
    s = _compare(d)
    pages = {e["url"]: e for e in s["pages"]}
    assert pages[U[4]]["state"] == "unknown" and "earlier collection's coverage is not complete" in pages[U[4]]["why"]
    assert pages[U[1]]["state"] == "unchanged"


def test_denominators_read_from_different_indexes_never_say_added_or_removed(first, monkeypatch):
    d, b1 = first
    r2 = _collect(d, monkeypatch, DAY2, SECOND, (1, 2, 3, 4), source=f"https://{HOST}/sitemap.xml")
    _drafts(d, r2["batch"], *_second_drafts(b1))
    _, out = _stage(d, r2["batch"])
    _add_stops(d, out["stop_lines_to_add"])
    s = _compare(d)
    assert not s["index_comparable"] and "different indexes" in s["index_why"]
    st = _states(s["pages"], "url")
    assert st[U[4]] == "unknown" and st[U[5]] == "unknown" and st[U[2]] == "changed"


def test_compare_writes_nothing(both):
    d, _, _ = both
    before = _snapshot(d)
    _compare(d)
    _run(compare, str(d), "--from", DAY1, "--to", DAY2)  # the markdown too
    assert _snapshot(d) == before


def test_compare_takes_denominator_names_and_refuses_what_it_cannot_compare(both):
    d, _, _ = both
    den1, den2 = f"_denominator-docs-{DAY1}.md", f"_denominator-docs-{DAY2}.md"
    code, out = _run(compare, str(d), "--from", den1, "--to", str(d / den2), "--json")
    assert code == 0 and out["surfaces"][0]["to"]["denominator"] == den2
    for frm, to, words in ((den1, den1, "on both sides"), ("yesterday", DAY2, "neither a date"),
                           ("2026-01-01", DAY2, "no denominator"),
                           (den1, f"_denominator-help-{DAY2}.md", "no denominator")):
        code, out = _run(compare, str(d), "--from", frm, "--to", to)
        assert code == 1 and words in out["refused"], (frm, to, out)
    (d / f"_denominator-help-{DAY2}.md").write_text(f"Index: help, rung 1 — https://{HOST}/h\n")
    code, out = _run(compare, str(d), "--from", den1, "--to", f"_denominator-help-{DAY2}.md")
    assert code == 1 and "different surfaces" in out["refused"]
    code, out = _run(compare, str(d), "--from", DAY1, "--to", DAY2, "--json")
    assert out["surfaces_not_compared"] == [{"surface": "help", "why": f"no denominator of help on the earlier "
                                                                        f"side ({DAY1})"}]


def test_the_cli_dispatches_compare(both, capsys):
    d, _, _ = both
    assert cli.main(["compare", str(d), "--from", DAY1, "--to", DAY2]) == 0
    text = capsys.readouterr().out
    assert text.startswith("# Compare — Example-Co") and "| added | 1 | 1 |" in text
