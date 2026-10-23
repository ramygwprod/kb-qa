"""v6.22.0 — the whole chain, every step by its own command, on a simulated web.

`kbqa collect-surface` captures the windows; per window `kbqa stage --lists`
writes the lists, the row-writer's drafts are written as its agent text says,
`kbqa stage` writes the staging file, the mappers' drafts are written and
`kbqa mapstage` writes the map files; then the real `/kbqa-check` script, `kbqa
autofix`, the check again, the real merge, and G6 over the estate. The agents
are instructions, not code, so their files are written here exactly as those
instructions say; everything else is the code the collector runs.

A second test runs the same steps against a subject in the shape kbqa 6.21.0
left it: a staging file written by an agent, map files with no sidecar.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kbqa import autofix, collect_surface, fetch, mapstage, stage, stops
from kbqa.parsing import parse_staging
from test_capture import DAY, HOST, SeqWeb

REPO = Path(__file__).resolve().parent.parent
CHECK = REPO / "skills" / "kbqa-check" / "scripts" / "check_subject.sh"
MERGE = REPO / "skills" / "kbqa-merge" / "scripts" / "merge.py"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


def _page(crumb, *paras):
    items = "".join(f"<li>{c}</li>" for c in crumb.split(" > "))
    body = "".join(f"<p>{p}</p>" for p in paras)
    return (200, (f'<html><body><nav aria-label="Breadcrumb"><ol>{items}</ol></nav><main>'
                  f'<h1>{crumb.split(" > ")[-1]}</h1>{body}</main></body></html>').encode(), "text/html")


U = {i: f"https://{HOST}/p{i}" for i in range(1, 5)}
HOOKS = "Webhooks notify your server when a message is delivered."
WEB = {
    U[1]: _page("Docs > Webhooks", HOOKS, "Signing secrets let you verify each webhook call."),
    U[2]: _page("Docs > Webhooks > Retries", "Failed webhook calls are retried for up to 24 hours.",
                "A dead-letter queue keeps calls that never succeeded."),
    U[3]: _page("Docs > Templates", "Templates let you reuse approved message layouts.",
                "Variables fill a template with each customer's data.",
                "Approvals send a template to review before use.",
                "Languages give one template several translations.", HOOKS),
    U[4]: _page("Docs > Pricing", "See our plans on the pricing page."),
}
ELEMENTS = [{"pcf_id": f"1000{i}", "hierarchy_id": f"1.{i}", "name": n}
            for i, n in enumerate(["Deliver messages", "Retry delivery", "Manage templates",
                                   "Translate content"], start=1)]


def _run(mod, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mod.run(list(args))
    return code, json.loads(out.getvalue())


def _estate(root):
    (root / "ref").mkdir(parents=True)
    (root / "kbqa-estate.json").write_text(json.dumps({
        "subjects_dir": "Subjects", "logic_sheet": "ref/LOGIC-SHEET.md",
        "themes_codebook": "ref/codebook.md", "apqc_elements": "ref/elements.jsonl"}))
    (root / "ref" / "LOGIC-SHEET.md").write_text("# Logic sheet (synthetic)\n")
    (root / "ref" / "codebook.md").write_text("| code | theme |\n|---|---|\n| I01 | Messaging |\n")
    (root / "ref" / "elements.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ELEMENTS))
    d = root / "Subjects" / "Example-Co"
    d.mkdir(parents=True)
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    (d / f"_denominator-docs-{DAY}.md").write_text(
        f"Index: docs, rung 1 — https://{HOST}/llms.txt\n" + "".join(f"- [P{i}]({U[i]})\n" for i in U))
    for line in ("- https://www.example.test/ | surface product not published: the site lists only docs",
                 "- https://www.example.test/ | surface help not published: no help centre is linked"):
        assert _run(stops, "add", str(d), line)[0] == 0
    return d


def _j(term, grade="official-doc"):
    """The row-writer's judgement of one row."""
    return {"vendor_term": term, "what_it_does": f"{term} does one thing.", "evidence_grade": grade,
            "confidence": "high", "mechanism": "Native", "outcome": "yes"}


def _draft(page, quote, term, **kw):
    return {"page": page, "part": 0, "quote": quote, **_j(term, **kw)}


def _write_drafts(d, batch, objs):
    (d / stage.draft_name(batch)).write_text("".join(json.dumps(o) + "\n" for o in objs))


def _mapline(rid, k):
    """One mapper's reading of one anchor: each anchor of a batch on its own element."""
    return {"id": rid, "article": "an", "role": "operator", "role_source": "apqc-closest", "actor": "B",
            "want": "to handle messages", "so_that": "messages are handled", "theme": "I01", "theme_links": [],
            "pcf_ids": [f"1000{k % 4 + 1}"], "confidence": "low", "status": "mapped", "note": ""}


def _map_both(d, batch, els):
    ids = mapstage._anchors(d / f"_collect-{batch}-staging.md")[0]
    for letter in "AB":
        (d / mapstage.draft_name(batch, letter)).write_text(
            "".join(json.dumps(_mapline(i, k)) + "\n" for k, i in enumerate(ids)))
        code, m = _run(mapstage, "--subject", str(d), "--batch", batch, "--pass", letter, "--elements", els)
        assert code == 0 and m["map"], m
    return ids


def _env():
    return {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '/usr/bin:/bin')}"}


def _check(d, root):
    p = subprocess.run(["bash", str(CHECK), str(d), str(root)], capture_output=True, text=True, env=_env())
    return p.stdout + p.stderr


def _merge(d, batch, *extra):
    p = subprocess.run([sys.executable, str(MERGE), "--vendor-dir", str(d), "--batch", batch, *extra],
                       capture_output=True, text=True, env=_env())
    return p.returncode, p.stdout + p.stderr


def test_the_chain_from_capture_to_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb(dict(WEB)))
    root = tmp_path / "estate with spaces"
    d = _estate(root)
    els = str(root / "ref" / "elements.jsonl")
    den = str(d / f"_denominator-docs-{DAY}.md")

    # collect-surface: two windows of two pages, then the selection is exhausted
    code, cs = _run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator", den,
                    "--select", "2-5", "--max-pages", "2", "--date", DAY)
    assert code == 0 and cs["end"] == "exhausted", cs
    b1, b2 = [w["batch"] for w in cs["windows"]]
    assert [(u["batch"], u["state"]) for u in cs["unstaged"]] == [
        (b1, collect_surface.NO_DRAFTS), (b2, collect_surface.NO_DRAFTS)]

    # window 1: the lists, the drafts (one grade respelt), the staging file, the two passes
    code, lists1 = _run(stage, "--subject", str(d), "--batch", b1, "--lists")
    assert code == 0, lists1
    _write_drafts(d, b1, [
        _draft(U[1], HOOKS, "Webhooks"),
        _draft(U[1], "Signing secrets let you verify each webhook call.", "Signing secrets"),
        _draft(U[2], "A dead-letter queue keeps calls that never succeeded.", "Dead-letter queue"),
        _draft(U[2], "Failed webhook calls are retried for up to 24 hours.", "Retries", grade="Help")])
    code, s1 = _run(stage, "--subject", str(d), "--batch", b1)
    assert code == 0 and s1["staging"] and s1["rows"] == 4, s1
    assert [(e["field"], e["before"], e["after"]) for e in s1["respelt_by_code"]] == [
        ("evidence_grade", "Help", "help")]
    code, again = _run(stage, "--subject", str(d), "--batch", b1, "--lists")
    assert code == 1 and "never after it is staged" in again["refused"]
    assert len(_map_both(d, b1, els)) == 4

    # window 2: the lists hold window 1's rows; a page left without a reason is
    # rejected, the correction round gives it one; an exact repeat is linked by code
    code, lists2 = _run(stage, "--subject", str(d), "--batch", b2, "--lists")
    assert code == 0 and f"example-co.docs.webhooks.webhooks | Webhooks" in (d / lists2["features"]).read_text()
    rows2 = [_draft(U[3], "Templates let you reuse approved message layouts.", "Templates"),
             _draft(U[3], "Variables fill a template with each customer's data.", "Variables"),
             _draft(U[3], "Approvals send a template to review before use.", "Approvals"),
             _draft(U[3], "Languages give one template several translations.", "Languages"),
             _draft(U[3], HOOKS, "Webhooks")]
    _write_drafts(d, b2, rows2)
    code, s2 = _run(stage, "--subject", str(d), "--batch", b2)
    assert code == 1 and s2["round"] == 1 and s2["rejected_lines"] == [
        {"page": U[4], "reason": f"no row and no reason: no draft line names the page {U[4]}"}], s2
    _write_drafts(d, b2, rows2 + [{"page": U[4], "no_row": "pricing page"}])
    code, s2 = _run(stage, "--subject", str(d), "--batch", b2)
    assert code == 0 and s2["round"] == 2 and s2["rows"] == 5, s2
    [link] = s2["linked_by_code"]
    assert link["line"] == 5 and link["anchor"] == "example-co.docs.webhooks.webhooks"
    for line in s2["stop_lines_to_add"]:
        assert _run(stops, "add", str(d), line)[0] == 0
    assert len(_map_both(d, b2, els)) == 4  # the linked repeat takes its anchor's classification

    # nothing is left unstaged
    code, cs = _run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator", den,
                    "--select", "2-5", "--date", DAY)
    assert code == 0 and cs["already_exhausted"] and cs["unstaged"] == [], cs

    # a hand edit spoils a grade after staging: the check blocks window 1
    stg1 = d / f"_collect-{b1}-staging.md"
    stg1.write_text(stg1.read_text().replace('"evidence_grade": "help"', '"evidence_grade": "Help"'))
    out = _check(d, root)
    assert "surfaces: PASS" in out and out.count("mapcheck: PASS") == 2, out
    assert f"-- {b1}\n    status=BLOCKED  round=1" in out and f"-- {b2}\n    status=CLEAR  round=1" in out, out

    # autofix fixes the respelling; run again on its own bytes, it is no dead end
    code, af = _run(autofix, "--subject", str(d), "--batch", b1)
    assert code == 0 and af["fixed"] == {"evidence_grade_spelling": 1} and af["left_findings"] == [], af
    code, again = _run(autofix, "--subject", str(d), "--batch", b1)
    assert code == 0 and "already applied" in again["note"] and again["files_written"] == [], again
    assert again["next_step"].startswith("/kbqa-check")
    # autofix gave back the very bytes the mappers read: nothing to re-map
    code, ret = _run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--retire")
    assert code == 1 and "is unchanged since" in ret["refused"], ret

    out = _check(d, root)
    assert f"-- {b1}\n    status=CLEAR  round=2" in out and f"-- {b2}\n    status=CLEAR  round=1" in out, out
    assert "NOT CHECKED" not in out, out

    # merge both batches, then G6 over the estate
    code, txt = _merge(d, b1, "--new-tree")
    assert code == 0 and "MERGED" in txt, txt
    code, txt = _merge(d, b2)
    assert code == 0 and "MERGED" in txt, txt
    tree = d / "feature-tree.md"
    ids = [rp.obj["id"] for rp in parse_staging(tree).rows]
    assert len(ids) == len(set(ids)) == 9, ids
    g6 = subprocess.run([sys.executable, "-m", "kbqa", "g6", "--root", str(root)], capture_output=True,
                        text=True, env=_env())
    verdict = json.loads(g6.stdout)
    assert g6.returncode == 0 and verdict["verdict"] == "PASS", g6.stdout + g6.stderr
    assert verdict["counts"]["batches_clear"] == 2 and verdict["counts"]["clear_not_merged"] == 0


def test_a_subject_left_by_kbqa_6_21_goes_through_the_same_steps(tmp_path):
    """A staging file written by an agent, a receipt with no parts, map files
    with no sidecar: nothing is rewritten under it, and the operator's word
    retires a map file code cannot vouch for."""
    import test_pipeline_end_to_end as e2e
    root = tmp_path / "estate"
    d = e2e._estate(root)
    b, els = e2e.B, str(root / "ref" / "elements.jsonl")
    raw = d / "_raw" / b
    raw.mkdir(parents=True)
    (raw / "RECEIPT.json").write_text(json.dumps({
        "batch": b, "capture": f"_capture-{b}.raw.txt", "sha256": "0" * 64,
        "pages": [{"url": f"{e2e.HOST}/{p}"} for p, _, _ in e2e.PAGES],
        "features": f"_raw/{b}/FEATURES.md", "role_rows": None, "access_date": "2026-10-16"}))
    staged = (d / f"_collect-{b}-staging.md").read_bytes()

    out = _check(d, root)
    assert "status=BLOCKED  round=1" in out and "fixable=1" in out, out
    # the staging file exists: neither the lists nor the staging are made again
    code, r = _run(stage, "--subject", str(d), "--batch", b, "--lists")
    assert code == 1 and "never after it is staged" in r["refused"], r
    code, r = _run(stage, "--subject", str(d), "--batch", b)
    assert code == 1 and "never overwritten" in r["refused"], r
    # autofix cannot vouch for the breadcrumb from this receipt: left for the row-writer
    code, af = _run(autofix, "--subject", str(d), "--batch", b)
    assert code == 0 and af["fixed"] == {} and af["files_written"] == [], af
    assert [f["code"] for f in af["left_findings"]] == ["parent_path_empty"]
    assert "receipt cannot vouch" in af["left_findings"][0]["why_not_by_code"]
    assert (d / f"_collect-{b}-staging.md").read_bytes() == staged

    e2e._staging(d, fixed=True)  # the row-writer's fix round
    # the map files have no record: retired only on the operator's word
    code, r = _run(mapstage, "--subject", str(d), "--batch", b, "--pass", "A", "--retire")
    assert code == 1 and "cannot be told" in r["refused"] and "--no-record" in r["next_step"], r
    code, r = _run(mapstage, "--subject", str(d), "--batch", b, "--pass", "A", "--retire", "--no-record")
    assert code == 0 and Path(r["without_record"]).is_file() and r["anchor_set_changed"] is False, r
    ids = mapstage._anchors(d / f"_collect-{b}-staging.md")[0]
    (d / mapstage.draft_name(b, "A")).write_text("".join(json.dumps(_mapline(i, k)) + "\n"
                                                         for k, i in enumerate(ids)))
    code, m = _run(mapstage, "--subject", str(d), "--batch", b, "--pass", "A", "--elements", els)
    assert code == 0 and m["map"], m

    out = _check(d, root)
    assert "status=CLEAR  round=2" in out and "mapcheck: PASS" in out, out
    code, txt = _merge(d, b, "--new-tree")
    assert code == 0 and "MERGED" in txt, txt


def test_a_page_captured_by_the_retry_is_staged_like_any_window(tmp_path, monkeypatch):
    """A page that failed is captured by collect-surface's --retry-failed run in
    a window of its own; it is listed unstaged and goes through the same steps."""
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    web = dict(WEB)
    web[U[2]] = [(500, b"", "")] * 4 + [WEB[U[2]]]
    monkeypatch.setattr(fetch, "_open", SeqWeb(web))
    root = tmp_path / "estate"
    d = _estate(root)
    els = str(root / "ref" / "elements.jsonl")
    code, cs = _run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator",
                    str(d / f"_denominator-docs-{DAY}.md"), "--select", "2-5", "--date", DAY)
    assert code == 0 and cs["retried_failed"] and [w["kind"] for w in cs["windows"]] == ["window", "retry"], cs
    b1, b2 = [u["batch"] for u in cs["unstaged"]]
    drafts = {b1: [_draft(U[1], HOOKS, "Webhooks"),
                   _draft(U[3], "Templates let you reuse approved message layouts.", "Templates"),
                   {"page": U[4], "no_row": "pricing page"}],
              b2: [_draft(U[2], "Failed webhook calls are retried for up to 24 hours.", "Retries")]}
    for b in (b1, b2):
        assert _run(stage, "--subject", str(d), "--batch", b, "--lists")[0] == 0
        _write_drafts(d, b, drafts[b])
        code, s = _run(stage, "--subject", str(d), "--batch", b)
        assert code == 0 and s["staging"], s
        for line in s["stop_lines_to_add"]:
            assert _run(stops, "add", str(d), line)[0] == 0
        _map_both(d, b, els)
    out = _check(d, root)
    assert f"-- {b1}\n    status=CLEAR  round=1" in out and f"-- {b2}\n    status=CLEAR  round=1" in out, out
    assert "NOT CHECKED" not in out, out
