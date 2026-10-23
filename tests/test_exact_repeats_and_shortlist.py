"""v6.22.0 — exact repeats linked by code, and the same-feature shortlist.

An exact repeat — the same `parameter` (else `vendor_term`) and the same quote,
on the same host, as an anchor of the subject or an earlier anchor draft of the
batch — is linked by `kbqa stage` and listed under `linked_by_code`; a draft
that names another anchor is never changed, only listed under
`link_conflicts`. And `kbqa stage --lists` writes, per page of the window, a
short list of anchors that share words with the page's headings and
parameter-like tokens: candidates only, scored, each with the words in common.
"""

import json
from pathlib import Path

import pytest

from kbqa import fetch, shortlist, stage
from kbqa.gates import g2_conformance, g3_grounding
from kbqa.parsing import parse_staging
from test_capture import DAY, HOST, SeqWeb, _cap, _den
from test_stage import GOOD, P1, P2, _drafts, _row, _run, window  # noqa: F401  (a fixture)

API_A = """<html><body><nav aria-label="Breadcrumb"><ol><li><a href="/">Docs</a></li>
<li><a href="/api">API</a></li><li>Create invoice</li></ol></nav>
<main><h1>Create invoice</h1><p>Creates an invoice and sends reminders before payment.</p>
<h2>Parameters</h2><ul><li>due_date: The date the invoice is due.</li>
<li>customerId: The customer the invoice is for.</li></ul></main></body></html>"""
API_B = """<html><body><nav aria-label="Breadcrumb"><ol><li><a href="/">Docs</a></li>
<li><a href="/api">API</a></li><li>Update invoice</li></ol></nav>
<main><h1>Update invoice</h1><p>Changes an invoice that is not paid yet.</p>
<h2>Parameters</h2><ul><li>due_date: The date the invoice is due.</li>
<li>memo_text: A note printed on the invoice.</li></ul></main></body></html>"""
DUE = "The date the invoice is due."


def _anchor(rid, term, quote, url=f"https://{HOST}/old", **extra):
    return {"id": rid, "vendor_term": term, "what_it_does": f"{term} does one thing.",
            "parent_path": "Docs > Old", "source_url": url, "source_quote": quote, "access_date": "2026-01-30",
            "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes",
            "depth_level": "2", "canonical": "NOVEL", **extra}


def _staged(d, *rows, batch="docs-2026-01-30-w01"):
    """An earlier batch's staging file: the subject's rows before this window."""
    (d / f"_collect-{batch}-staging.md").write_text(
        f"---\nbatch: {batch}\nsource_capture: _capture-{batch}.raw.txt\nsource_capture_sha256: {'0' * 64}\n"
        f"fetched_by_this_agent: false\npages:\n  - https://{HOST}/old\n---\n\n```json\n[\n"
        + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n```\n")


def _rows(out):
    return [rp.obj for rp in parse_staging(Path(out["staging"])).rows]


@pytest.fixture
def api(tmp_path, monkeypatch):
    """One window of two API operation pages that print the same parameter."""
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb({P1: (200, API_A.encode(), "text/html"),
                                                P2: (200, API_B.encode(), "text/html")}))
    code, r = _cap(d, "--surface", "docs", "--denominator", str(_den(d, n=2)))
    assert code == 0 and len(r["pages"]) == 2, r
    return d, r


def _due(page, **extra):
    return _row(page, DUE, "Due date", parameter="due_date", interface_type="API",
                operation="create invoice" if page == P1 else "update invoice", **extra)


# ── exact repeats ────────────────────────────────────────────────────────────

def test_an_exact_repeat_of_a_subject_anchor_is_linked_by_code(window):
    d, r = window
    b = r["batch"]
    # the anchor's quote has a straight apostrophe and hyphen: compared folded
    _staged(d, _anchor("example-co.docs.old.retry-limit", "Retry limit",
                       "Admins can't change the limit - only owners can."))
    _drafts(d, b, *GOOD)
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0, out
    assert out["linked_by_code"] == [{"line": 2, "anchor": "example-co.docs.old.retry-limit", "matched": {
        "host": HOST, "vendor_term": "Retry limit", "quote": "Admins can’t change the limit — only owners can."}}]
    assert out["link_conflicts"] == []
    rows = _rows(out)
    assert rows[1]["same_feature_as"] == "example-co.docs.old.retry-limit"
    assert "same_feature_as" not in rows[0] and "same_feature_as" not in rows[2]
    v, c = g2_conformance.run(["--staging", out["staging"]])
    assert c == 0, v.to_json()


def test_only_the_same_name_the_same_quote_and_the_same_host_is_a_repeat(window):
    d, r = window
    b = r["batch"]
    quote = "Failed webhook calls are retried for up to 24 hours"
    _staged(d,
            _anchor("x.other-host", "Retries", quote, url="https://other.example.test/old"),  # another host
            _anchor("x.other-quote", "Retries", "Failed webhook calls are retried"),         # another quote
            _anchor("x.other-name", "Retry", quote),                                         # another name
            _anchor("x.anchor", "Webhooks", "Webhooks"),
            _anchor("x.a-source", "Retries", quote, same_feature_as="x.anchor"))             # not an anchor
    _drafts(d, b, *GOOD)
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["linked_by_code"] == [] and out["link_conflicts"] == [], out
    assert all("same_feature_as" not in o for o in _rows(out))


def test_the_parameter_is_compared_when_the_draft_has_one(api):
    d, r = api
    b = r["batch"]
    _staged(d, _anchor("x.due-param", "Invoice due", DUE, parameter="due_date"),  # the parameter matches
            _anchor("x.due-term", "Due date", DUE))                                # only the term does
    _drafts(d, b, _due(P1), {"page": P2, "no_row": "another operation"})
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0, out
    assert [(e["line"], e["anchor"], e["matched"]["parameter"]) for e in out["linked_by_code"]] == \
        [(1, "x.due-param", "due_date")]
    assert _rows(out)[0]["same_feature_as"] == "x.due-param"


def test_an_exact_repeat_of_an_earlier_draft_is_linked_to_it(api):
    d, r = api
    b = r["batch"]
    _drafts(d, b, _due(P1), _due(P2))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0, out
    rows = _rows(out)
    assert "same_feature_as" not in rows[0], "the first is the anchor"
    assert rows[1]["same_feature_as"] == rows[0]["id"] == "example-co.docs.create-invoice.due-date"
    assert out["linked_by_code"] == [{"line": 2, "anchor": rows[0]["id"], "anchor_line": 1,
                                      "matched": {"host": HOST, "parameter": "due_date", "quote": DUE}}]
    for gate in (g2_conformance, g3_grounding):
        args = ["--staging", out["staging"]] + ([] if gate is g2_conformance else
                                               ["--capture", str(d / f"_capture-{b}.raw.txt")])
        v, c = gate.run(args)
        assert c == 0, v.to_json()


def test_a_draft_that_names_the_same_anchor_is_left_as_it_is(api):
    d, r = api
    b = r["batch"]
    _drafts(d, b, _due(P1), _due(P2, same_feature_as="draft:1"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["linked_by_code"] == [] and out["link_conflicts"] == [], out
    rows = _rows(out)
    assert rows[1]["same_feature_as"] == rows[0]["id"]


def test_a_draft_that_names_another_anchor_is_never_changed_only_listed(api):
    d, r = api
    b = r["batch"]
    _staged(d, _anchor("x.due", "Due date", DUE, parameter="due_date"), _anchor("x.other", "Other", "Other"))
    _drafts(d, b, _due(P1, same_feature_as="x.other"), {"page": P2, "no_row": "another operation"})
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["linked_by_code"] == [], out
    assert _rows(out)[0]["same_feature_as"] == "x.other"
    [c] = out["link_conflicts"]
    assert c["line"] == 1 and c["anchor"] == "x.due" and c["same_feature_as"] == "x.other"
    assert c["matched"]["parameter"] == "due_date" and "nothing changed" in c["reason"]


def test_a_draft_that_is_another_source_is_never_the_anchor_of_a_repeat(api):
    d, r = api
    b = r["batch"]
    _staged(d, _anchor("x.invoices", "Invoices", "Invoices"))
    _drafts(d, b, _due(P1, same_feature_as="x.invoices"), _due(P2))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["linked_by_code"] == [], out
    rows = _rows(out)
    assert rows[0]["same_feature_as"] == "x.invoices" and "same_feature_as" not in rows[1]


def test_a_draft_other_drafts_name_as_their_anchor_is_not_linked(api):
    d, r = api
    b = r["batch"]
    _staged(d, _anchor("x.due", "Due date", DUE, parameter="due_date"))
    _drafts(d, b, _due(P1), _row(P2, "A note printed on the invoice.", "Memo", same_feature_as="draft:1"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["linked_by_code"] == [], out
    [c] = out["link_conflicts"]
    assert c["line"] == 1 and c["anchor"] == "x.due" and "draft line(s) 2 name this draft" in c["reason"]
    rows = _rows(out)
    assert "same_feature_as" not in rows[0] and rows[1]["same_feature_as"] == rows[0]["id"]
    v, code = g2_conformance.run(["--staging", out["staging"]])
    assert code == 0, v.to_json()


def test_a_repeat_of_several_anchors_is_listed_not_linked(api):
    d, r = api
    b = r["batch"]
    _staged(d, _anchor("x.due-1", "Due date", DUE, parameter="due_date"),
            _anchor("x.due-2", "Due date", DUE, parameter="due_date"))
    _drafts(d, b, _due(P1), _due(P2, same_feature_as="x.due-2"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["linked_by_code"] == [], out
    [c] = out["link_conflicts"]
    assert c["line"] == 1 and c["anchor"] == ["x.due-1", "x.due-2"] and "2 anchors" in c["reason"]
    rows = _rows(out)
    assert "same_feature_as" not in rows[0] and rows[1]["same_feature_as"] == "x.due-2"


# ── the shortlist: words in common ───────────────────────────────────────────

PAGE = {"url": P1, "headings": [{"line": 2, "level": 1, "text": "Create invoice"},
                                {"line": 4, "level": 2, "text": "Log in with an API key"}],
        "parts": [{"lines": [1, 4]}]}
LINES = ["Creates an invoice and sends reminders before payment.",
         "due_date: The date the invoice is due.",
         "customerId: The customer the invoice is for.",
         "Log in to it."]


def test_a_pages_words_are_its_headings_and_its_parameter_like_tokens():
    assert shortlist.parameter_like("due_date: x, customerId; Plain words and API") == ["due_date", "customerId"]
    assert shortlist.page_words(PAGE, LINES) == {"create", "invoice", "log", "api", "key", "due", "date",
                                                          "customerid"}


def test_words_are_lowercase_without_stop_words_or_words_of_two_characters():
    assert shortlist.words("About the API-key, in 2 Steps: log_in") == {"api", "key", "steps", "log"}


def _pick(anchors):
    return shortlist.candidates({rid: shortlist.anchor_words(r) for rid, r in anchors.items()},
                                shortlist.page_words(PAGE, LINES))


def test_an_anchor_needs_two_words_in_common_and_is_scored_by_them():
    found = _pick({
        "a.due": {"vendor_term": "Due date", "parameter": "due_date", "what_it_does": "Sets when an invoice is due."},
        "b.customer": {"vendor_term": "Customer", "parameter": "customerId", "what_it_does": "Names who pays the invoice."},
        "c.one-word": {"vendor_term": "Invoice templates", "what_it_does": "Templates shape a PDF."},
        "d.headings": {"vendor_term": "API key", "what_it_does": "Creates a key."},
        "e.prose": {"vendor_term": "Reminders", "what_it_does": "Sends reminders before payment."},
        "f.stop-words": {"vendor_term": "Invoice with", "what_it_does": "Works with an invoice."},
        "g.short-words": {"vendor_term": "Log in", "what_it_does": "Log in to it."},
    })
    assert found == [("a.due", 3, ["date", "due", "invoice"]), ("b.customer", 2, ["customerid", "invoice"]),
                     ("d.headings", 2, ["api", "key"])]


def test_at_most_ten_anchors_a_page_highest_score_first_then_id():
    anchors = {f"x.{i:02d}": {"vendor_term": "Due date", "what_it_does": "Set it."} for i in range(12)}
    anchors["z.best"] = {"vendor_term": "Due date", "what_it_does": "For an invoice."}
    found = _pick(anchors)
    assert len(found) == 10
    assert [f[0] for f in found] == ["z.best"] + [f"x.{i:02d}" for i in range(9)]


def test_stage_lists_writes_the_shortlist_per_page_and_names_it(api):
    d, r = api
    b = r["batch"]
    _staged(d,
            _anchor("x.due", "Due date", DUE, parameter="due_date", what_it_does="Sets when an invoice is due."),
            _anchor("x.memo", "Memo", "A note.", parameter="memo_text", what_it_does="Prints a note."),
            _anchor("x.source", "Due date", DUE, parameter="due_date", same_feature_as="x.due"))
    code, out = _run("--subject", str(d), "--batch", b, "--lists")
    assert code == 0 and out["same_feature"] == f"_raw/{b}/SAME-FEATURE.md", out
    text = (d / out["same_feature"]).read_text()
    sections = text.split("\n## ")[1:]
    assert [s.splitlines()[0] for s in sections] == [P1, P2]
    assert sections[0].splitlines()[1:] == [
        "- x.due | 3 | date, due, invoice | Due date | Docs > Old | Sets when an invoice is due."]
    assert "x.memo | 2 | memo, text" in sections[1] and "x.source" not in text, "anchors only"
    assert "Candidates only" in text


def test_stage_lists_says_why_there_is_no_shortlist(api):
    d, r = api
    b = r["batch"]
    cap = d / f"_capture-{b}.raw.txt"
    cap.write_text(cap.read_text().replace("invoice", "bill"))
    code, out = _run("--subject", str(d), "--batch", b, "--lists")
    assert code == 0 and out["same_feature"] is None, out
    assert "does not hash to the receipt's sha256" in out["same_feature_note"]
    assert out["features"] and (d / out["features"]).exists()
    assert not (d / "_raw" / b / shortlist.NAME).exists()
