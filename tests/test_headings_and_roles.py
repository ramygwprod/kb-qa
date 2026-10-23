"""v6.20.0 — heading coverage (#7) and the role-row candidates (#14).

#7: every heading of a captured page is a place the subject put something; the
check lists the headings no row's quote begins under, on pages no stop line
explains — advisory, never a failure. Rows are one row per feature (the
operator's ruling of 2026-10-18), so a heading's coverage is how row
granularity is seen.

#14: the mapper's role sources reach rows of the subject that name a role for
the same feature. The patterns that mark such rows are the estate's (its
`kbqa-estate.json`), never this tool's; the list only finds candidates.
"""

import json
import shutil
from pathlib import Path

import pytest

from kbqa import fetch, headings, roles

from test_capture import DAY, HOST, SeqWeb, _cap, _den

HERE = Path(__file__).resolve().parent

DOC = """<html><body><nav aria-label="Breadcrumb"><a href="/">Docs</a> <a href="/q">Queues</a></nav>
<main><h1>Queues</h1><p>Queues hold callers until an agent is free.</p>
<h2>Callback</h2><p>Callers can request a callback instead of waiting.</p><p>It is on by default.</p>
<h2>Service level</h2><p>Supervisors are alerted when the service level drops.</p>
<h2>Limits</h2>
<h3>Hold time</h3><p>The longest a caller waits is ten minutes.</p>
</main></body></html>"""


@pytest.fixture
def captured(tmp_path, monkeypatch):
    d = tmp_path / "Subjects" / "Example-Co"
    d.mkdir(parents=True)
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb({f"https://{HOST}/p1": (200, DOC.encode(), "text/html")}))
    code, r = _cap(d, "--surface", "docs", "--denominator", str(_den(d, n=1)))
    assert code == 0
    return d, r


def _rows(d, batch, quotes):
    objs = [{"id": f"x.q.{i}", "source_url": f"https://{HOST}/p1", "source_quote": q, "vendor_term": f"T{i}"}
            for i, q in enumerate(quotes)]
    (d / f"_collect-{batch}-staging.md").write_text(
        f"---\nbatch: {batch}\n---\n```json\n" + "\n".join(json.dumps(o) for o in objs) + "\n```\n")


# ── #7 heading coverage ──────────────────────────────────────────────────────

def test_the_receipt_gives_each_heading_its_capture_line(captured):
    d, r = captured
    page = r["pages"][0]
    lines = (d / f"_capture-{r['batch']}.raw.txt").read_text().split("\n")
    assert [h["text"] for h in page["headings"]] == ["Queues", "Callback", "Service level", "Limits", "Hold time"]
    for h in page["headings"]:
        assert lines[h["line"] - 1] == h["text"]
    assert [h["level"] for h in page["headings"]] == [1, 2, 2, 2, 3]


def test_a_heading_no_quote_begins_under_is_listed(captured):
    d, r = captured
    _rows(d, r["batch"], ["Callers can request a callback instead of waiting."])
    c = headings.coverage(d, r["batch"])
    assert c["measured"] and c["headings"] == 4 and c["headings_without_text"] == 1  # "Limits" holds nothing
    assert c["with_row"] == 1
    assert [h["text"] for h in c["headings_without_row"]] == ["Queues", "Service level", "Hold time"]


def test_a_quote_counts_for_the_section_it_begins_in(captured):
    d, r = captured
    # one quote running from the Callback section into the next heading
    _rows(d, r["batch"], ["It is on by default. Service level"])
    c = headings.coverage(d, r["batch"])
    assert "Callback" not in [h["text"] for h in c["headings_without_row"]]
    assert "Service level" in [h["text"] for h in c["headings_without_row"]]


def test_a_page_a_stop_line_explains_is_not_a_question(captured):
    d, r = captured
    _rows(d, r["batch"], [])
    (d / "_stop-conditions.md").write_text(f"- https://{HOST}/p1 | no feature: overview page\n")
    c = headings.coverage(d, r["batch"])
    assert c["without_row"] == 0 and c["page_stopped"] == 4


def test_a_batch_captured_before_heading_lines_is_not_measured(captured):
    d, r = captured
    rec = d / "_raw" / r["batch"] / "RECEIPT.json"
    data = json.loads(rec.read_text())
    for p in data["pages"]:
        p.pop("headings")
    rec.write_text(json.dumps(data))
    c = headings.coverage(d, r["batch"])
    assert c["measured"] is False and "6.20.0" in c["why"]
    assert headings.summary_line(c).startswith("headings: not measured")


def test_the_check_prints_heading_coverage(captured, capsys):
    from kbqa import cli
    d, r = captured
    _rows(d, r["batch"], ["Callers can request a callback instead of waiting."])
    cli.main(["report", "--vendor-dir", str(d), "--batch", r["batch"]])
    out = capsys.readouterr().out
    assert "headings=4  with_row=1  page_stopped=0  without_row=3" in out
    md = (d / "_qa" / f"{r['batch']}.report.md").read_text()
    assert "## Headings no row speaks for (advisory)" in md and ": ### Hold time" in md


# ── #14 role-row candidates ──────────────────────────────────────────────────

PATTERNS = [{"pattern": r"\b(custom roles?|permission sets?)\b", "fields": ["vendor_term", "source_quote"]},
            {"pattern": r"roles?\s*(and|&)\s*permissions?", "fields": ["parent_path"]}]


def _estate(root: Path, spec=PATTERNS):
    (root / "kbqa-estate.json").write_text(json.dumps({"subjects_dir": "Subjects", "role_rows": spec}))


def _tree(d):
    shutil.copy(HERE / "fixtures" / "merge" / "clear" / "_collect-docs-2026-01-31-staging.md",
                d / "_collect-docs-2026-01-31-staging.md")


def test_rows_matching_the_estates_patterns_are_listed(captured):
    d, _ = captured
    _estate(d.parent.parent)
    _tree(d)
    text, why = roles.role_rows_list(d)
    assert why is None
    assert "example.docs.roles | Roles | Docs > Settings > Roles | \"custom roles\" (source_quote)" in text
    assert "example.docs.inbox" not in text and "1 rows" in text


def test_without_patterns_nothing_is_guessed(captured):
    d, _ = captured
    _tree(d)
    text, why = roles.role_rows_list(d)
    assert text is None and "no kbqa-estate.json" in why
    _estate(d.parent.parent, spec=[])
    text, why = roles.role_rows_list(d)
    assert text is None and "names no `role_rows`" in why


def test_a_bad_pattern_is_refused_never_half_applied(captured):
    d, _ = captured
    _estate(d.parent.parent, spec=[PATTERNS[0], {"pattern": "(unclosed", "fields": ["id"]}])
    text, why = roles.role_rows_list(d)
    assert text is None and "entry 1" in why


# Writing the list moved to `kbqa stage --lists` in v6.22.0: tests/test_stage.py.


def test_patterns_match_without_case(captured):
    d, _ = captured
    _estate(d.parent.parent, spec=[{"pattern": r"\bCUSTOM ROLES\b", "fields": ["source_quote"]}])
    _tree(d)
    text, _ = roles.role_rows_list(d)
    assert "example.docs.roles" in text
