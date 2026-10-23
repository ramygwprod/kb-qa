"""v6.22.0 — the staging file written by code, from the row-writer's drafts.

The row-writer judges (which words, what they say, which grade); `kbqa stage`
copies everything a code can copy: the frontmatter from the receipt, the exact
capture text of each quote, the page, the breadcrumb and its depth, the id. A
quote that is not in its part's own lines, or is there more than once, is
rejected and listed — never guessed. And the lists the row-writer reads are
built when it is about to read them (`kbqa stage --lists`), so they hold the
rows of the windows before it.
"""

import contextlib
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

from kbqa import capture, fetch, features, stage
from kbqa.gates import g1_capture, g2_conformance, g3_grounding
from kbqa.parsing import parse_staging
from test_capture import DAY, HOST, SeqWeb, _cap, _den

HERE = Path(__file__).resolve().parent

RETRIES = """<html><body><nav aria-label="Breadcrumb"><ol><li><a href="/">Docs</a></li>
<li><a href="/hooks">Webhooks</a></li><li>Retries</li></ol></nav>
<main><h1>Retries</h1><p>Failed webhook calls are retried   for up to <b>24 hours</b>.</p>
<p>Admins can’t change the limit — only owners can.</p>
<h2>Logs</h2><p>Every retry is logged.</p><p>Every retry is logged.</p></main></body></html>"""
REPORTS = "# Delivery reports\n\nDelivery reports show every message's final status.\n"
PRICING = "<html><body><main><h1>Pricing</h1><p>See our plans.</p></main></body></html>"

P1, P2, P3 = (f"https://{HOST}/p{i}" for i in (1, 2, 3))


def _run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = stage.run(list(args))
    return code, json.loads(out.getvalue())


@pytest.fixture
def window(tmp_path, monkeypatch):
    """One window of three pages captured by code: a page with a breadcrumb,
    a markdown page without one, and a page with no feature."""
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb({
        P1: (200, RETRIES.encode(), "text/html"),
        P2: (200, REPORTS.encode(), "text/markdown"),
        P3: (200, PRICING.encode(), "text/html")}))
    code, r = _cap(d, "--surface", "docs", "--denominator", str(_den(d, n=3)))
    assert code == 0 and len(r["pages"]) == 3, r
    return d, r


def _drafts(d, batch, *objs):
    (d / stage.draft_name(batch)).write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs))


def _judgement(term, **extra):
    return {"vendor_term": term, "what_it_does": f"{term} does one thing.", "evidence_grade": "official-doc",
            "confidence": "high", "mechanism": "Native", "outcome": "yes", **extra}


def _row(page, quote, term, part=0, **extra):
    return {"page": page, "part": part, "quote": quote, **_judgement(term, **extra)}


GOOD = [
    # the draft's own spacing, straight apostrophe and hyphen: the capture's words are copied
    _row(P1, "Failed webhook calls are retried for up to 24 hours", "Retries"),
    _row(P1, "Admins can't change the limit - only owners can.", "Retry limit"),
    _row(P2, "Delivery reports show every message's final status.", "Delivery reports"),
    {"page": P3, "no_row": "pricing page"},
]


# ── a full window: capture → drafts → stage → G1, G2, G3 ─────────────────────

def test_a_staged_window_passes_g1_g2_and_g3(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["rows"] == 3 and out["rejected"] == 0, out
    stg, cap = Path(out["staging"]), d / f"_capture-{b}.raw.txt"
    assert stg == d / f"_collect-{b}-staging.md"
    for gate in (g1_capture, g3_grounding):
        v, c = gate.run(["--staging", str(stg), "--capture", str(cap)])
        assert c == 0, v.to_json()
    v, c = g2_conformance.run(["--staging", str(stg)])
    assert c == 0 and v.counts["strict_rules"] == "applied", v.to_json()
    assert out["stop_lines_to_add"] == [f"- {P3} | no feature: pricing page"]
    assert out["pages_without_row_or_no_row"] == []


def test_the_quote_is_the_captures_exact_text_never_the_drafts(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    _, out = _run("--subject", str(d), "--batch", b)
    rows = [rp.obj for rp in parse_staging(Path(out["staging"])).rows]
    assert rows[0]["source_quote"] == "Failed webhook calls are retried for up to 24 hours"
    assert rows[1]["source_quote"] == "Admins can’t change the limit — only owners can."
    assert all(o["source_quote"] in (d / f"_capture-{b}.raw.txt").read_text() for o in rows)


def test_the_page_fields_are_filled_by_code(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD, _row(P2, "# Delivery reports", "Delivery reports", interface_type="API",
                              operation="list reports"))
    _, out = _run("--subject", str(d), "--batch", b)
    rows = [rp.obj for rp in parse_staging(Path(out["staging"])).rows]
    assert [o["id"] for o in rows] == ["example-co.docs.retries.retries", "example-co.docs.retries.retry-limit",
                                       "example-co.docs.delivery-reports", "example-co.docs.delivery-reports-2"]
    assert rows[0]["parent_path"] == "Docs > Webhooks > Retries" and rows[0]["depth_level"] == "3"
    assert rows[2]["parent_path"] == "unknown" and rows[2]["depth_level"] == "unknown"  # no breadcrumb
    assert all(o["source_url"] == p and o["access_date"] == DAY and o["canonical"] == "NOVEL"
               for o, p in zip(rows, (P1, P1, P2, P2)))
    assert rows[3]["interface_type"] == "API" and rows[3]["operation"] == "list reports"
    assert list(rows[0])[0] == "id"


def test_the_frontmatter_is_the_receipts(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    _, out = _run("--subject", str(d), "--batch", b)
    fm = parse_staging(Path(out["staging"])).frontmatter_raw
    cap = d / f"_capture-{b}.raw.txt"
    assert fm == {"batch": b, "source_capture": cap.name,
                  "source_capture_sha256": hashlib.sha256(cap.read_bytes()).hexdigest(),
                  "pages": [p["url"] for p in r["pages"]], "fetched_by_this_agent": False,
                  "window_offset": str(r["window_offset"]), "window_requested": str(r["window_requested"]),
                  "window_returned": str(r["window_returned"]), "window_end": r["window_end"],
                  "access_date": DAY}
    assert fm["source_capture_sha256"] == r["sha256"]


def test_the_same_drafts_give_the_same_staging(window, tmp_path):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    _, out = _run("--subject", str(d), "--batch", b)
    first = Path(out["staging"]).read_text()
    Path(out["staging"]).unlink()
    _, out = _run("--subject", str(d), "--batch", b)
    assert Path(out["staging"]).read_text() == first


# ── rejected, listed, never guessed ──────────────────────────────────────────

def _rejects(d, b, round_no=1):
    return [json.loads(ln) for ln in (d / stage.rejects_name(b, round_no)).read_text().splitlines()]


def test_a_quote_not_in_the_part_is_rejected_and_listed(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, GOOD[0], _row(P1, "Failed webhooks are retried for a day.", "Paraphrase"),
            _row(P1, "Delivery reports show every message's final status.", "Wrong page"), *GOOD[2:])
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and out["rejected"] == 2, out
    rej = _rejects(d, b)
    assert [x["line"] for x in rej] == [2, 3]
    assert "quote not found" in rej[0]["reason"] and "not on this page" in rej[0]["reason"]
    assert "on another page of the capture" in rej[1]["reason"]
    assert rej[0]["draft"]["vendor_term"] == "Paraphrase", "the rejected draft is kept whole"


def test_a_quote_found_twice_in_the_part_is_rejected(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, GOOD[0], _row(P1, "Every retry is logged.", "Retry log"), *GOOD[2:])
    code, out = _run("--subject", str(d), "--batch", b)
    assert out["rows"] == 2 and out["rejected"] == 1
    assert "found 2 times" in _rejects(d, b)[0]["reason"]


def test_a_quote_is_looked_for_in_the_parts_own_lines_only(tmp_path, monkeypatch):
    """A long page in parts: words from part 1 drafted as part 0 are refused,
    though they are on the page — the part is what the row-writer read."""
    from test_capture import _long_page
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb({P1: (200, _long_page(), "text/html")}))
    code, r = _cap(d, "--surface", "docs", "--denominator", str(_den(d, n=1)), "--part-chars", "4000")
    parts = r["pages"][0]["parts"]
    assert len(parts) > 2
    words = "Section 5 paragraph 3 explains one more thing about it in plain words."
    _drafts(d, r["batch"], _row(P1, words, "Five", part=0), _row(P1, words, "Five", part=len(parts) - 1))
    code, out = _run("--subject", str(d), "--batch", r["batch"])
    assert out["rows"] == 1 and out["rejected"] == 1, out
    rej = _rejects(d, r["batch"])[0]
    assert rej["line"] == 1 and "outside the part's own lines" in rej["reason"]


def test_a_draft_that_is_not_a_row_is_rejected_with_its_reason(window):
    d, r = window
    b = r["batch"]
    (d / stage.draft_name(b)).write_text("\n".join([
        json.dumps(GOOD[0]),
        "{not json",
        json.dumps(_row("https://elsewhere.test/x", "x", "X")),
        json.dumps(_row(P1, "Retries", "X", part=5)),
        json.dumps({**GOOD[0], "invented_field": "y"}),
        json.dumps({k: v for k, v in GOOD[0].items() if k != "mechanism"}),
        json.dumps({"page": P1, "no_row": "a page with rows"}),
    ]) + "\n")
    code, out = _run("--subject", str(d), "--batch", b)
    rej = _rejects(d, b)
    reasons = [x["reason"] for x in rej]
    assert out["rows"] == 1 and len(reasons) == 8, out
    assert reasons[0].startswith("not JSON")
    assert "is not a page of the receipt" in reasons[1]
    assert "part 5 is not a part" in reasons[2]
    assert "fields no row carries: invented_field" in reasons[3]
    assert "missing or empty: mechanism" in reasons[4]
    assert "drafted `no_row` but has rows" in reasons[5]
    # the pages no draft line names: each a reject of its own, by page
    assert [(x.get("line"), x.get("page")) for x in rej[6:]] == [(None, P2), (None, P3)]
    assert all(x.startswith("no row and no reason") for x in reasons[6:])
    assert out["stop_lines_to_add"] == []
    assert out["pages_without_row_or_no_row"] == [P2, P3]


def test_no_staging_is_written_when_every_draft_is_rejected(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, _row(P1, "words that are nowhere", "X"), *GOOD[3:], {"page": P2, "no_row": "a report"})
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and out["staging"] is None and out["rejected"] == 1
    assert not (d / f"_collect-{b}-staging.md").exists()


# ── ids ──────────────────────────────────────────────────────────────────────

def test_an_id_the_subject_already_has_is_never_reused(window):
    d, r = window
    b = r["batch"]
    tree = (HERE / "fixtures" / "merge" / "clear" / "feature-tree.md").read_text()
    (d / "feature-tree.md").write_text(tree.replace('"example.product.overview"',
                                                    '"example-co.docs.retries.retries"'))
    (d / "_collect-docs-2026-01-31-staging.md").write_text(
        (HERE / "fixtures" / "merge" / "clear" / "_collect-docs-2026-01-31-staging.md").read_text()
        .replace('"example.docs.inbox"', '"example-co.docs.retries.retries-2"'))
    _drafts(d, b, *GOOD)
    _, out = _run("--subject", str(d), "--batch", b)
    ids = [rp.obj["id"] for rp in parse_staging(Path(out["staging"])).rows]
    assert ids[0] == "example-co.docs.retries.retries-3"
    v, c = g2_conformance.run(["--staging", out["staging"]])
    assert "duplicate_id" not in [f.code for f in v.findings]


# ── refusals ─────────────────────────────────────────────────────────────────

def test_a_staging_file_is_never_overwritten(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    (d / f"_collect-{b}-staging.md").write_text("by hand\n")
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and "never overwritten" in out["refused"]
    assert (d / f"_collect-{b}-staging.md").read_text() == "by hand\n"


def test_a_capture_changed_since_its_receipt_is_refused(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    cap = d / f"_capture-{b}.raw.txt"
    cap.write_text(cap.read_text().replace("24 hours", "48 hours"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and "does not hash to the receipt's sha256" in out["refused"]
    assert not (d / f"_collect-{b}-staging.md").exists()


def test_no_drafts_or_no_receipt_is_refused(window):
    d, r = window
    code, out = _run("--subject", str(d), "--batch", r["batch"])
    assert code == 1 and "no drafts" in out["refused"]
    code, out = _run("--subject", str(d), "--batch", f"docs-{DAY}-w09")
    assert code == 1 and "no receipt" in out["refused"]


# ── the lists, built when the row-writer is about to read them ───────────────
# (moved here from capture: v6.19.0's FEATURES.md and v6.20.0's ROLE-ROWS.md)

def test_capture_no_longer_writes_the_lists(window):
    d, r = window
    assert "features" not in r and "role_rows" not in r
    assert not (d / "_raw" / r["batch"] / stage.FEATURES).exists()


def test_stage_lists_writes_the_subjects_features_beside_the_receipt(window):
    d, r = window
    shutil.copy(HERE / "fixtures" / "merge" / "clear" / "feature-tree.md", d / "feature-tree.md")
    code, out = _run("--subject", str(d), "--batch", r["batch"], "--lists")
    assert code == 0 and out["features"] == f"_raw/{r['batch']}/FEATURES.md"
    text = (d / out["features"]).read_text()
    assert "example.product.overview" in text and text == features.features_list(d)


def test_the_lists_include_the_rows_of_earlier_windows(tmp_path, monkeypatch):
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb({P1: (200, RETRIES.encode(), "text/html"),
                                                P2: (200, REPORTS.encode(), "text/markdown")}))
    den = _den(d, n=2)
    _, w1 = _cap(d, "--surface", "docs", "--denominator", str(den), "--max-pages", "1")
    assert _run("--subject", str(d), "--batch", w1["batch"], "--lists")[0] == 0
    _drafts(d, w1["batch"], GOOD[0])
    assert _run("--subject", str(d), "--batch", w1["batch"])[0] == 0
    _, w2 = _cap(d, "--surface", "docs", "--denominator", str(den), "--resume")
    code, out = _run("--subject", str(d), "--batch", w2["batch"], "--lists")
    assert code == 0
    assert "example-co.docs.retries.retries | Retries" in (d / out["features"]).read_text()


def test_stage_lists_writes_the_role_rows_or_says_why_not(tmp_path, monkeypatch):
    from test_headings_and_roles import DOC, _estate, _tree
    for with_patterns in (True, False):
        root = tmp_path / str(with_patterns)
        d = root / "Subjects" / "Example-Co"
        d.mkdir(parents=True)
        if with_patterns:
            _estate(root)
        _tree(d)
        (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
        monkeypatch.setattr(fetch, "_sleep", lambda s: None)
        monkeypatch.setattr(fetch, "_open", SeqWeb({P1: (200, DOC.encode(), "text/html")}))
        code, r = _cap(d, "--surface", "docs", "--denominator", str(_den(d, n=1)))
        assert code == 0
        code, out = _run("--subject", str(d), "--batch", r["batch"], "--lists")
        assert code == 0
        if with_patterns:
            assert out["role_rows"] == f"_raw/{r['batch']}/ROLE-ROWS.md"
            assert "example.docs.roles" in (d / out["role_rows"]).read_text()
        else:
            assert out["role_rows"] is None and out["role_rows_note"].startswith("not written: no kbqa-estate.json")


def test_the_cli_dispatches_stage(window, capsys):
    from kbqa import cli
    d, r = window
    assert cli.main(["stage", "--subject", str(d), "--batch", r["batch"], "--lists"]) == 0
    assert json.loads(capsys.readouterr().out)["features"].endswith("FEATURES.md")


# ── rejects block the staging file: one correction round, then the operator ──

def test_rejected_drafts_block_the_staging_file(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, GOOD[0], _row(P1, "Failed webhooks are retried for a day.", "Paraphrase"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and out["staging"] is None and out["round"] == 1, out
    assert not (d / f"_collect-{b}-staging.md").exists()
    assert out["rejects"] == str(d / f"_draft-{b}.rejects-1.jsonl")
    assert "correction round" in out["next_step"] and "rewrites only the rejected lines" in out["next_step"]


def test_one_correction_round_then_the_staging_file(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, GOOD[0], _row(P1, "Failed webhooks are retried for a day.", "Paraphrase"), *GOOD[1:])
    assert _run("--subject", str(d), "--batch", b)[0] == 1
    lines = (d / stage.draft_name(b)).read_text().splitlines()  # the row-writer rewrites line 2 only
    lines[1] = json.dumps(_row(P1, "Failed webhook calls are retried for up to 24 hours.", "Paraphrase"))
    (d / stage.draft_name(b)).write_text("\n".join(lines) + "\n")
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["round"] == 2 and out["rejected"] == 0 and out["rows"] == 4, out
    assert (d / f"_draft-{b}.rejects-1.jsonl").exists(), "each round's rejects are kept"
    v, c = g3_grounding.run(["--staging", out["staging"], "--capture", str(d / f"_capture-{b}.raw.txt")])
    assert c == 0, v.to_json()


def test_after_the_correction_round_rejects_are_left_out_only_on_the_flag_and_listed(window):
    d, r = window
    b = r["batch"]
    bad = [_row(P1, "Failed webhooks are retried for a day.", "Paraphrase"),
           _row(P1, "Every retry is logged.", "Retry log")]
    _drafts(d, b, *GOOD, *bad)
    code, out = _run("--subject", str(d), "--batch", b, "--leave-out-rejects")
    assert code == 1 and "correction round" in out["refused"], "never before the correction round"
    assert _run("--subject", str(d), "--batch", b)[1]["round"] == 1
    code, out = _run("--subject", str(d), "--batch", b)  # the correction round fixed nothing
    assert code == 1 and out["round"] == 2 and "--leave-out-rejects" in out["next_step"], out
    code, out = _run("--subject", str(d), "--batch", b)  # a third run without the flag
    assert code == 1 and "no second" in out["refused"] and "--leave-out-rejects" in out["next_step"], out
    assert not (d / f"_collect-{b}-staging.md").exists()
    code, out = _run("--subject", str(d), "--batch", b, "--leave-out-rejects")
    assert code == 0 and out["rows"] == 3 and out["round"] == 3, out
    left = out["needs_operator"]
    assert [x["line"] for x in left] == [5, 6] and [x["draft"]["vendor_term"] for x in left] == ["Paraphrase",
                                                                                                "Retry log"]
    assert all(x["reason"] and x["next_step"] for x in left)
    assert "capture lines" in left[0]["next_step"]
    assert len(_rejects(d, b, 3)) == 2 and len(_rejects(d, b, 1)) == 2 and len(_rejects(d, b, 2)) == 2
    for gate in (g1_capture, g3_grounding):
        assert gate.run(["--staging", out["staging"], "--capture", str(d / f"_capture-{b}.raw.txt")])[1] == 0


# ── same_feature_as: draft:<line> names another draft of this batch ──────────

def test_a_draft_link_resolves_to_the_id_given_that_draft(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD, _row(P2, "Delivery reports show", "Report retries", same_feature_as="draft:1"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0, out
    rows = [rp.obj for rp in parse_staging(Path(out["staging"])).rows]
    assert rows[-1]["same_feature_as"] == rows[0]["id"] == "example-co.docs.retries.retries"
    v, c = g2_conformance.run(["--staging", out["staging"]])
    assert c == 0, v.to_json()


def test_a_draft_link_must_name_an_anchor_that_is_staged(window):
    d, r = window
    b = r["batch"]
    shutil.copy(HERE / "fixtures" / "merge" / "clear" / "_collect-docs-2026-01-31-staging.md",
                d / "_collect-docs-2026-01-31-staging.md")  # holds the anchor example.docs.inbox
    other = _row(P2, "Delivery reports show", "Report", same_feature_as="example.docs.inbox")
    _drafts(d, b,
            GOOD[0],                                                          # 1 anchor
            _row(P1, "words that are nowhere", "Gone"),                        # 2 rejected
            {"page": P3, "no_row": "pricing page"},                            # 3 no row
            other,                                                             # 4 another source
            _row(P1, "Admins can't change", "A", same_feature_as="draft:2"),   # 5 -> rejected
            _row(P1, "only owners can", "B", same_feature_as="draft:3"),       # 6 -> no_row
            _row(P1, "webhook calls", "C", same_feature_as="draft:7"),         # 7 -> itself
            _row(P1, "up to 24 hours", "D", same_feature_as="draft:4"),        # 8 -> a source
            _row(P1, "Failed webhook", "E", same_feature_as="draft:99"),       # 9 -> nothing
            _row(P1, "are retried", "F", same_feature_as="draft:x"))           # 10 malformed
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1, out
    by_line = {x["line"]: x["reason"] for x in _rejects(d, b)}
    assert sorted(by_line) == [2, 5, 6, 7, 8, 9, 10], by_line
    assert "draft line 2, which is rejected: quote not found" in by_line[5]
    assert "a page with no row" in by_line[6]
    assert "own line" in by_line[7]
    assert "itself another source" in by_line[8]
    assert "holds no draft" in by_line[9]
    assert "draft:<line number>" in by_line[10]


# ── every page has a row or a reason (v6.22.0, review S5) ────────────────────

def test_a_page_with_no_row_and_no_reason_blocks_the_staging_file(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD[:3])  # P3 is named by no draft line
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and out["staging"] is None and out["round"] == 1, out
    [rej] = _rejects(d, b)
    assert rej["page"] == P3 and "line" not in rej and rej["reason"].startswith("no row and no reason")
    assert out["rejected_lines"] == [{"page": P3, "reason": rej["reason"]}]
    assert "drafts each page listed with no row and no reason" in out["next_step"]
    _drafts(d, b, *GOOD)  # the correction round gives the page its reason
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["round"] == 2 and out["staging"], out


def test_a_page_left_without_a_reason_is_listed_for_the_operator(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD[:3])
    assert _run("--subject", str(d), "--batch", b)[0] == 1
    assert _run("--subject", str(d), "--batch", b)[0] == 1
    code, out = _run("--subject", str(d), "--batch", b, "--leave-out-rejects")
    assert code == 0 and out["rows"] == 3, out
    assert [(x.get("page"), x["reason"][:20]) for x in out["needs_operator"]] == [(P3, "no row and no reason")]


# ── stage checks what it can before the check (v6.22.0) ──────────────────────

def test_same_feature_as_must_name_an_anchor_of_the_subject(window):
    from test_exact_repeats_and_shortlist import _anchor, _staged
    d, r = window
    b = r["batch"]
    _staged(d, _anchor("x.anchor", "Webhooks", "Webhooks"),
            _anchor("x.a-source", "Hooks", "Hooks", same_feature_as="x.anchor"))
    _drafts(d, b, *GOOD,
            _row(P1, "Every retry is logged.", "Log", part=0, same_feature_as="x.nowhere"),
            _row(P1, "only owners can", "Owners", same_feature_as="x.a-source"),
            _row(P1, "Failed webhook calls", "Calls", same_feature_as="x.anchor"))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1, out
    by_line = {x["line"]: x["reason"] for x in _rejects(d, b)}
    assert sorted(by_line) == [5, 6], by_line
    assert "'x.nowhere' is not an anchor of the subject" in by_line[5] and "names no row" in by_line[5]
    assert "'x.a-source' is not an anchor" in by_line[6] and "itself another source" in by_line[6]


def test_an_enumerated_value_outside_the_profile_is_rejected_in_the_draft_round(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, GOOD[0], _row(P1, "Admins can't change the limit", "Limit", mechanism="native"),
            _row(P1, "only owners can", "Owners", confidence="very high", outcome="maybe"),
            _row(P1, "Failed webhook calls", "Calls", interface_type="REST API", operation="retry"),
            *GOOD[2:])
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1, out
    by_line = {x["line"]: x["reason"] for x in _rejects(d, b)}
    assert sorted(by_line) == [2, 3, 4], by_line
    assert "mechanism 'native' is not one of Native | Composed" in by_line[2]
    assert "confidence 'very high'" in by_line[3] and "outcome 'maybe'" in by_line[3]
    assert "interface_type 'REST API' is not one of API | SDK" in by_line[4]


def test_a_known_grade_respelling_is_written_in_the_schemas_spelling(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, _row(P1, "Failed webhook calls are retried for up to 24 hours", "Retries", evidence_grade="Help"),
            _row(P1, "Admins can't change the limit", "Limit", evidence_grade="verify"),
            _row(P1, "only owners can", "Owners", evidence_grade="rumour"), *GOOD[2:])
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 1 and [x["line"] for x in _rejects(d, b)] == [3], out
    assert "evidence_grade 'rumour' is not one of" in _rejects(d, b)[0]["reason"]
    lines = (d / stage.draft_name(b)).read_text().splitlines()
    (d / stage.draft_name(b)).write_text("\n".join(lines[:2] + lines[3:]) + "\n")
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0, out
    assert [x["evidence_grade"] for x in (rp.obj for rp in parse_staging(Path(out["staging"])).rows)] == \
        ["help", "[verify]", "official-doc"]
    assert out["respelt_by_code"] == [{"line": 1, "field": "evidence_grade", "before": "Help", "after": "help"},
                                      {"line": 2, "field": "evidence_grade", "before": "verify",
                                       "after": "[verify]"}]
    v, c = g2_conformance.run(["--staging", out["staging"]])
    assert c == 0 and "evidence_grade_spelling" not in [f.code for f in v.findings], v.to_json()


# ── the lists, the role rows refreshed, and a batch with no rows ─────────────

def test_the_lists_are_refused_once_the_batch_is_staged(window):
    d, r = window
    b = r["batch"]
    assert _run("--subject", str(d), "--batch", b, "--lists")[0] == 0
    features_md = (d / "_raw" / b / stage.FEATURES).read_bytes()
    _drafts(d, b, *GOOD)
    assert _run("--subject", str(d), "--batch", b)[0] == 0
    code, out = _run("--subject", str(d), "--batch", b, "--lists")
    assert code == 1 and "never after it is staged" in out["refused"], out
    assert (d / "_raw" / b / stage.FEATURES).read_bytes() == features_md


def test_stage_refreshes_the_role_rows_with_the_batchs_own_rows(window):
    from test_headings_and_roles import _estate
    d, r = window
    b = r["batch"]
    _estate(d.parent)
    code, out = _run("--subject", str(d), "--batch", b, "--lists")
    assert code == 0 and "example-co.docs" not in (d / out["role_rows"]).read_text()
    _drafts(d, b, GOOD[0], _row(P1, "Admins can't change the limit", "Custom roles"), *GOOD[2:])
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["role_rows_refreshed"] == f"_raw/{b}/{stage.ROLE_ROWS}", out
    assert "example-co.docs.retries.custom-roles | Custom roles" in (d / out["role_rows_refreshed"]).read_text()


def test_stage_says_why_the_role_rows_are_not_refreshed(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *GOOD)
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["role_rows_refreshed"] is None
    assert out["role_rows_note"].startswith("not written: no kbqa-estate.json")


def test_a_batch_drafted_no_row_throughout_skips_mapping(window):
    d, r = window
    b = r["batch"]
    _drafts(d, b, *({"page": p["url"], "no_row": "an overview"} for p in r["pages"]))
    code, out = _run("--subject", str(d), "--batch", b)
    assert code == 0 and out["staging"] is None and out["rows"] == 0, out
    assert out["next_step"] == "no rows — skip mapping for this batch"
    assert len(out["stop_lines_to_add"]) == 3
