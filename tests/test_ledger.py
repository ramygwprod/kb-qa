"""v6.23.0 — `kbqa status`, the subject ledger: what is left and what is done.

Read-only, computed by code from the subject's files. The subjects here are
built by the chain's own commands (`collect-surface`, `stage`, `mapstage`,
`report`, `autofix`, the real merge — `tests/test_chain_end_to_end.py`'s
helpers), and one is left in the shape kbqa 6.21.0 left subjects: a staging file
written by an agent, no window records, no drafts, no sidecars. What the files
cannot tell is `unknown`, never 0.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path

import pytest

import test_chain_end_to_end as chain
import test_pipeline_end_to_end as e2e
from kbqa import autofix, cli, collect_surface, fetch, ledger, mapstage, report, stage, stops
from test_capture import DAY, SeqWeb

U = chain.U


def _status(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ledger.run([str(a) for a in args])
    return code, out.getvalue()


def _ledger(*args):
    code, text = _status(*args, "--json")
    return code, json.loads(text)


def _report(d, b, log=True):
    with contextlib.redirect_stdout(io.StringIO()):
        report.run(["--vendor-dir", str(d), "--batch", b] + (["--log", str(d / "_qa-log.jsonl")] if log else []))


def _backdate_captures(d):
    """A capture comes well before its rows (G1); a coarse clock could tie them."""
    for p in d.glob("_capture-*.raw.txt"):
        t = p.stat().st_mtime - 60
        os.utime(p, (t, t))


def _maps(d, batch, els, humans):
    """Both passes; `humans` = {letter: {anchor index: note}} — a needs-human
    line, or ("mapped", note) for a mapped line that carries a note."""
    ids = mapstage._anchors(d / f"_collect-{batch}-staging.md")[0]
    for letter in "AB":
        lines = []
        for k, rid in enumerate(ids):
            line = chain._mapline(rid, k)
            h = humans.get(letter, {}).get(k)
            if isinstance(h, tuple):
                line["note"] = h[1]
            elif h:
                line.update(status="needs-human", note=h)
            lines.append(line)
        (d / mapstage.draft_name(batch, letter)).write_text("".join(json.dumps(x) + "\n" for x in lines))
        code, m = chain._run(mapstage, "--subject", str(d), "--batch", batch, "--pass", letter, "--elements", els)
        assert code == 0 and m["map"], m
    return ids


def _snapshot(root):
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def chained(tmp_path, monkeypatch):
    """Two windows of the docs surface, staged and mapped by the chain's own
    commands; window 2 through a check, autofix and a second check; window 1
    merged."""
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb(dict(chain.WEB)))
    root = tmp_path / "estate"
    d = chain._estate(root)
    els = str(root / "ref" / "elements.jsonl")
    code, cs = chain._run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator",
                          str(d / f"_denominator-docs-{DAY}.md"), "--select", "2-5", "--max-pages", "2", "--date", DAY)
    assert code == 0 and cs["end"] == "exhausted", cs
    b1, b2 = [w["batch"] for w in cs["windows"]]
    _backdate_captures(d)

    assert chain._run(stage, "--subject", str(d), "--batch", b1, "--lists")[0] == 0
    chain._write_drafts(d, b1, [
        chain._draft(U[1], chain.HOOKS, "Webhooks"),
        chain._draft(U[1], "Signing secrets let you verify each webhook call.", "Signing secrets"),
        chain._draft(U[2], "A dead-letter queue keeps calls that never succeeded.", "Dead-letter queue"),
        chain._draft(U[2], "Failed webhook calls are retried for up to 24 hours.", "Retries")])
    code, s1 = chain._run(stage, "--subject", str(d), "--batch", b1)
    assert code == 0 and s1["rows"] == 4, s1
    ids1 = _maps(d, b1, els, {"A": {0: ("mapped", "[new category] considered; I01 fits"),
                                    2: "[NEW CATEGORY] fit is outside the current list"},
                              "B": {3: "[new category] fit is outside the current list"}})

    assert chain._run(stage, "--subject", str(d), "--batch", b2, "--lists")[0] == 0
    chain._write_drafts(d, b2, [
        chain._draft(U[3], "Templates let you reuse approved message layouts.", "Templates"),
        chain._draft(U[3], "Variables fill a template with each customer's data.", "Variables"),
        chain._draft(U[3], "Approvals send a template to review before use.", "Approvals"),
        chain._draft(U[3], "Languages give one template several translations.", "Languages"),
        chain._draft(U[3], chain.HOOKS, "Webhooks"), {"page": U[4], "no_row": "pricing page"}])
    code, s2 = chain._run(stage, "--subject", str(d), "--batch", b2)
    assert code == 0 and s2["rows"] == 5 and len(s2["linked_by_code"]) == 1, s2
    for line in s2["stop_lines_to_add"]:
        assert chain._run(stops, "add", str(d), line)[0] == 0
    ids2 = _maps(d, b2, els, {"A": {0: "[New  Category] fit is outside the current list",
                                    1: "[role unclear] the page names no user"}})

    # window 2: a grade spoilt by hand, the check, autofix, the check again
    stg2 = d / f"_collect-{b2}-staging.md"
    good = stg2.read_bytes()
    stg2.write_text(stg2.read_text().replace('"evidence_grade": "official-doc"', '"evidence_grade": "Official-Doc"', 1))
    _report(d, b1)
    _report(d, b2)
    code, af = chain._run(autofix, "--subject", str(d), "--batch", b2)
    assert code == 0 and af["fixed"] == {"evidence_grade_spelling": 1}, af
    assert stg2.read_bytes() == good
    _report(d, b2)
    code, txt = chain._merge(d, b1, "--new-tree")
    assert code == 0 and "MERGED" in txt, txt
    return {"root": root, "d": d, "b1": b1, "b2": b2, "ids1": ids1, "ids2": ids2, "els": els}


def test_the_ledger_of_a_chain_built_subject(chained):
    d, b1, b2 = chained["d"], chained["b1"], chained["b2"]
    code, out = _ledger(d)
    assert code == 0 and out["read_only"] is True
    docs = next(s for s in out["surfaces"] if s["surface"] == "docs")
    assert docs["denominator"] == f"_denominator-docs-{DAY}.md" and docs["state"] == "denominator"
    assert (docs["items"], docs["items_captured"], docs["items_staged"]) == (4, 4, 4), docs
    assert (docs["rows"], docs["features"], docs["other_sources"]) == (9, 8, 1), docs
    assert docs["stop_lines"]["items_stopped"] == 1 and docs["open_items"] == 0 and docs["open_item_urls"] == []
    w = docs["windows"]
    assert w["recorded"] == 2 and w["exhausted"] is True and w["parked"] is None and w["unstaged"] == [], w
    assert docs["retryable_pages"] == [] and docs["given_up_pages"] == []
    for s in out["surfaces"]:
        if s["surface"] != "docs":  # closed by a stop line: no items, which is not "unknown"
            assert s["state"] == "stop-condition" and s["items"] is None and s["open_items"] is None, s

    by = {b["batch"]: b for b in out["batches"]}
    assert set(by) == {b1, b2}
    assert by[b1]["check"]["status"] == "CLEAR" and by[b1]["check"]["round"] == 1
    assert by[b2]["check"]["status"] == "CLEAR" and by[b2]["check"]["round"] == 2, by[b2]["check"]
    assert by[b1]["autofix"] == []
    [rec] = by[b2]["autofix"]
    assert rec["changes"] == 1 and rec["left_findings"] == 0 and rec["on_current_staging"] is True, rec
    for b in (b1, b2):
        for letter in "AB":
            m = by[b]["maps"][letter]
            assert m["map"] and m["from_current_staging"] is True and m["draft"] and m["retired"] == 0, m
    assert by[b1]["merged"]["state"] == "merged" and by[b2]["merged"]["state"] == "not merged"

    # one question per pattern for the whole subject, names joined without case
    qs = {q["pattern"].casefold(): q for q in out["open_questions"]}
    assert set(qs) == {"new category", "role unclear"}, out["open_questions"]
    nc = qs["new category"]
    assert nc["rows"] == 3 and [b["batch"] for b in nc["batches"]] == [b1, b2], nc
    assert nc["batches"][0]["per_pass"] == {"A": [chained["ids1"][2]], "B": [chained["ids1"][3]]}
    assert nc["batches"][1]["per_pass"] == {"A": [chained["ids2"][0]]}
    assert qs["role unclear"]["rows"] == 1
    assert out["open_questions"][0]["pattern"].casefold() == "new category"  # the most rows first


def test_the_rows_to_re_map_after_a_ruling(chained):
    d, b1, b2 = chained["d"], chained["b1"], chained["b2"]
    code, out = _ledger(d, "--pattern", "[NEW CATEGORY]")
    assert code == 0 and out["scope"] == "subject" and out["pattern"] == "NEW CATEGORY"
    # exactly the needs-human rows that name it: never a mapped line whose note mentions it
    assert out["rows"] == [{"batch": b1, "id": chained["ids1"][2], "pass": "A"},
                           {"batch": b1, "id": chained["ids1"][3], "pass": "B"},
                           {"batch": b2, "id": chained["ids2"][0], "pass": "A"}], out["rows"]
    assert [(p["batch"], p["pass"]) for p in out["passes"]] == [(b1, "A"), (b1, "B"), (b2, "A")]
    p = out["passes"][0]
    assert p["reopen"].endswith(f'--batch {b1} --pass A --reopen "NEW CATEGORY"') and f'--subject "{d}"' in p["reopen"]
    assert chained["els"] in p["then"] and mapstage.draft_name(b1, "A") in p["then"]
    # the rows did not change, and still every pass can be reopened for the ruling
    assert all("reopen_refused" not in x for x in out["passes"]), out
    assert _ledger(d, "--pattern", "new category")[1]["rows"] == out["rows"]
    code, none = _ledger(d, "--pattern", "nothing like it")
    assert code == 0 and none["rows"] == [] and none["passes"] == []
    code, text = _status(d, "--pattern", "role unclear")
    assert code == 0 and "# Rows to re-map" in text and chained["ids2"][1] in text and "--reopen" in text
    assert "refused" not in text


def test_changed_bytes_make_the_check_stale_and_the_maps_other_bytes(chained):
    d, b2 = chained["d"], chained["b2"]
    stg2 = d / f"_collect-{b2}-staging.md"
    stg2.write_text(stg2.read_text().replace('"confidence": "high"', '"confidence": "medium"', 1))
    code, out = _ledger(d)
    b = next(x for x in out["batches"] if x["batch"] == b2)
    assert b["check"]["status"] == "stale" and b["check"]["report_status"] == "CLEAR", b["check"]
    assert b["check"]["round"] is None
    assert b["maps"]["A"]["from_current_staging"] is False and b["autofix"][0]["on_current_staging"] is False


def test_the_ledger_writes_nothing(chained):
    root, d = chained["root"], chained["d"]
    before = _snapshot(root)
    for args in ([d], [d, "--json"], [d, "--pattern", "new category"], ["--estate", root],
                 [d, "--estate", root, "--json"], ["--estate", root, "--pattern", "role unclear", "--json"]):
        assert _status(*args)[0] == 0, args
    assert _snapshot(root) == before


def test_the_markdown_summary_and_the_cli(chained):
    d, b1 = chained["d"], chained["b1"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["status", str(d)])
    text = out.getvalue()
    assert code == 0 and text.startswith("# Ledger — Example-Co")
    assert "| docs | denominator |" in text and "2, exhausted" in text
    assert f"| {b1} | 4 (4 / 0) | CLEAR | 1 | 0 | current | current | merged |" in text, text
    assert "## Open questions — 2 pattern(s), 4 row(s)" in text


def test_a_parked_surface_with_a_page_to_retry(tmp_path, monkeypatch):
    """One window of two pages, one of them failing: parked where the next
    window resumes, the window unstaged, its failed page retryable, and every
    item still open — counted by g4 with no batch staged yet."""
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    web = dict(chain.WEB)
    web[U[2]] = [(500, b"", "")] * 10
    monkeypatch.setattr(fetch, "_open", SeqWeb(web))
    d = chain._estate(tmp_path / "estate")
    code, cs = chain._run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator",
                          str(d / f"_denominator-docs-{DAY}.md"), "--select", "2-5", "--max-pages", "2",
                          "--max-windows", "1", "--date", DAY)
    assert cs["end"] == "window_limit", cs
    code, out = _ledger(d)
    docs = next(s for s in out["surfaces"] if s["surface"] == "docs")
    w = docs["windows"]
    assert w["exhausted"] is False and w["parked"]["resume_from"] == 2 and w["parked"]["remaining"] == 2, w
    assert w["unstaged"] == [{"batch": cs["windows"][0]["batch"], "state": collect_surface.NO_DRAFTS}]
    assert docs["retryable_pages"] == [U[2]] and docs["given_up_pages"] == []
    assert (docs["items"], docs["items_captured"], docs["items_staged"], docs["rows"]) == (4, 1, 0, 0), docs
    assert docs["open_items"] == 4 and sorted(docs["open_item_urls"]) == sorted(U.values())
    [b] = out["batches"]
    assert b["staged"] is False and b["check"]["status"] == "not staged" and b["merged"]["state"] == "not staged"
    code, text = _status(d)
    assert code == 0 and "parked at 2" in text and "unstaged" in text


def _old_subject(root):
    """A subject in the shape kbqa 6.21.0 left it (tests/test_pipeline_end_to_end.py)."""
    d = e2e._estate(root)
    return d, e2e.B


def test_a_subject_left_by_kbqa_6_21_is_summarised_with_unknowns(tmp_path):
    d, b = _old_subject(tmp_path / "estate")
    code, out = _ledger(d)
    assert code == 0
    docs = next(s for s in out["surfaces"] if s["surface"] == "docs")
    assert (docs["items"], docs["items_captured"], docs["items_staged"]) == (5, 5, 5), docs
    assert (docs["rows"], docs["features"], docs["other_sources"]) == (4, 4, 0)
    assert docs["stop_lines"]["items_stopped"] == 1 and docs["open_items"] == 0
    # no window records: whether it was exhausted, and what failed, cannot be told
    assert docs["windows"]["exhausted"] == "unknown" and docs["windows"]["parked"] == "unknown", docs["windows"]
    assert docs["retryable_pages"] == "unknown" and docs["given_up_pages"] == "unknown"
    [bl] = out["batches"]
    assert bl["drafts"] is False and bl["check"]["status"] == "not checked"
    assert bl["maps"]["A"]["from_current_staging"] == "unknown" and "sidecar" in bl["maps"]["A"]["why"]
    assert bl["merged"]["state"] == "not merged"
    [q] = out["open_questions"]
    assert q["pattern"] == "new category" and q["batches"] == [
        {"batch": b, "rows": ["example.docs.reports"], "per_pass": {"B": ["example.docs.reports"]}}]
    code, pat = _ledger(d, "--pattern", "new category")
    [p] = pat["passes"]
    assert "has no _map-" in p["reopen_refused"] and "--reopen" in p["reopen"], p
    assert "refused now:" in _status(d, "--pattern", "new category")[1]
    code, text = _status(d)
    assert code == 0 and "exhausted: unknown" in text and "| unknown | unknown |" in text, text

    # a report made without a log names no round: unknown, never 0
    _report(d, b, log=False)
    bl = _ledger(d)[1]["batches"][0]
    assert bl["check"]["status"] == "BLOCKED" and bl["check"]["round"] == "unknown", bl["check"]


def test_old_and_unreadable_files_never_crash_it(tmp_path):
    d, b = _old_subject(tmp_path / "estate")
    shutil.copy(d / f"_collect-{b}-staging.md", d / "_collect-legacy-run-staging.md")  # a legacy batch name
    (d / "_qa").mkdir()
    (d / "_qa" / f"{b}.report.json").write_text("{ not json")
    with open(d / f"_map-{b}-A.jsonl", "a") as fh:
        fh.write("not json\n")
    code, out = _ledger(d)
    assert code == 0 and out["legacy_batches"] == ["legacy-run"], out["legacy_batches"]
    by = {x["batch"]: x for x in out["batches"]}
    assert by[b]["check"]["status"] == "unknown" and "cannot be read" in by[b]["check"]["why"]
    assert by[b]["maps"]["A"]["unreadable_lines"] == 1
    assert by["legacy-run"]["surface"] is None and by["legacy-run"]["rows"] == 4
    assert _status(d)[0] == 0


def test_staged_pages_that_cannot_be_told_are_unknown(tmp_path):
    """A staging file that declares no pages, with no receipt: which items it
    staged cannot be told."""
    d, b = _old_subject(tmp_path / "estate")
    stg = d / f"_collect-{b}-staging.md"
    stg.write_text(re.sub(r"pages:\n(?:  - .*\n)+", "", stg.read_text()))
    assert "pages:" not in stg.read_text()
    docs = next(s for s in _ledger(d)[1]["surfaces"] if s["surface"] == "docs")
    assert docs["items_staged"] == "unknown" and docs["staged_pages_unknown_in"] == [b], docs
    assert docs["items_captured"] == 5


def test_merged_is_read_from_the_tree_by_id():
    assert ledger.merged_state(["a", "b"], {"a", "b", "c"})["state"] == "merged"
    assert ledger.merged_state(["a", "b"], {"a"})["state"] == "partly merged"
    assert ledger.merged_state(["a", "b"], set())["state"] == "not merged"
    assert ledger.merged_state(["a"], None)["state"] == "not merged"
    assert ledger.merged_state([], {"a"})["state"] == "unknown"


def test_open_questions_across_the_estate(tmp_path):
    root = tmp_path / "estate"
    d, b = _old_subject(root)
    other = d.parent / "Other-Co"
    shutil.copytree(d, other)
    mp = other / f"_map-{b}-B.jsonl"
    mp.write_text(mp.read_text().replace("[new category]", "[New Category]"))
    code, out = _ledger("--estate", root)
    assert code == 0 and "surfaces" not in out and out["estate"]["subjects"] == ["Example-Co", "Other-Co"]
    [q] = out["estate"]["open_questions"]
    assert q["pattern"] == "new category" and q["rows"] == 2 and q["subjects"] == 2, q
    assert [(x["subject"], x["batch"]) for x in q["batches"]] == [("Example-Co", b), ("Other-Co", b)]
    code, pat = _ledger("--estate", root, "--pattern", "NEW CATEGORY")
    assert pat["scope"] == "estate" and pat["rows"] == [
        {"subject": "Example-Co", "batch": b, "id": "example.docs.reports", "pass": "B"},
        {"subject": "Other-Co", "batch": b, "id": "example.docs.reports", "pass": "B"}], pat
    code, both = _ledger(d, "--estate", root)
    assert code == 0 and both["surfaces"] and both["estate"]["open_questions"][0]["rows"] == 2
    code, text = _status("--estate", root)
    assert code == 0 and "# Estate — " in text and "Other-Co / " in text


def test_refusals_exit_1(tmp_path):
    def refused(*args):
        code, text = _status(*args)
        assert code == 1, (args, text)
        return json.loads(text)["refused"]
    assert "give a subject folder" in refused()
    assert "no subject folder" in refused(tmp_path / "nowhere")
    (tmp_path / "e").mkdir()
    assert "no kbqa-estate.json" in refused("--estate", tmp_path / "e")
    (tmp_path / "e" / "kbqa-estate.json").write_text("{ not json")
    assert "cannot be read" in refused("--estate", tmp_path / "e")
    (tmp_path / "e" / "kbqa-estate.json").write_text(json.dumps({"logic_sheet": "x"}))
    assert "names no `subjects_dir`" in refused("--estate", tmp_path / "e")
    (tmp_path / "e" / "kbqa-estate.json").write_text(json.dumps({"subjects_dir": "Subjects"}))
    assert "is not a folder" in refused("--estate", tmp_path / "e")
    (tmp_path / "s").mkdir()
    assert "needs a name" in refused(tmp_path / "s", "--pattern", "  ")
    code, out = _ledger(tmp_path / "s")  # an empty subject is a ledger of nothing, not a refusal
    assert code == 0 and out["batches"] == [] and out["open_questions"] == []


# --------------------------------------------------------------------------
# mapstage --reopen: mapping again after the operator's ruling, rows unchanged
# --------------------------------------------------------------------------

def _mapstage(d, batch, letter, *extra):
    return chain._run(mapstage, "--subject", str(d), "--batch", batch, "--pass", letter, *extra)


def test_reopen_sends_back_only_the_rows_the_ruling_names(chained):
    d, b1, els, ids = chained["d"], chained["b1"], chained["els"], chained["ids1"]
    mp = d / mapstage.map_name(b1, "A")
    old = mp.read_text().splitlines()
    code, r = _mapstage(d, b1, "A", "--reopen", "[new category]")
    assert code == 0 and r["reopened"] == [ids[2]] and r["carried_over"] == 3 and r["pattern"] == "NEW CATEGORY", r
    dest = Path(r["retired_to"])
    assert dest.name == f"retired-{b1}-A-1" and not mp.exists()
    assert {p.name for p in dest.iterdir()} == {mp.name, mapstage.meta_name(b1, "A"), mapstage.draft_name(b1, "A"),
                                                 mapstage.REOPEN_NOTE}
    note = (dest / mapstage.REOPEN_NOTE).read_text()
    assert "[NEW CATEGORY]" in note and ids[2] in note and re.search(r"\d{4}-\d{2}-\d{2}", note)
    draft = [json.loads(x) for x in (d / mapstage.draft_name(b1, "A")).read_text().splitlines()]
    assert draft[2] == {"id": ids[2], "reopened": "NEW CATEGORY"}
    # a mapped line whose note mentions the pattern is carried over, never reopened
    assert draft[0]["status"] == "mapped" and draft[0]["note"].startswith("[new category]")
    assert [list(x) for i, x in enumerate(draft) if i != 2] == [list(mapstage.DRAFT_FIELDS)] * 3

    # the placeholder blocks the map file until the mapper replaces it
    code, m = _mapstage(d, b1, "A", "--elements", els)
    assert code == 1 and m["round"] == 1 and m["map"] is None, m
    assert m["rejected_lines"] == [{"line": 3, "id": ids[2], "reason":
                                    "not yet re-mapped after the ruling on [NEW CATEGORY]: the line is still the "
                                    "placeholder --reopen wrote"}], m
    draft[2] = chain._mapline(ids[2], 2)  # the mapper, applying the ruling
    (d / mapstage.draft_name(b1, "A")).write_text("".join(json.dumps(x) + "\n" for x in draft))
    code, m = _mapstage(d, b1, "A", "--elements", els)
    assert code == 0 and m["round"] == 2 and m["map"], m
    new = mp.read_text().splitlines()
    assert [x for i, x in enumerate(new) if i != 2] == [x for i, x in enumerate(old) if i != 2]  # byte-identical
    assert json.loads(new[2])["status"] == "mapped"
    # the ledger: that question is answered for pass A of window 1
    code, pat = _ledger(d, "--pattern", "new category")
    assert [(p["batch"], p["pass"]) for p in pat["passes"]] == [(b1, "B"), (chained["b2"], "A")]
    assert _ledger(d)[1]["batches"][0]["maps"]["A"]["retired"] == 1


def test_placeholders_left_after_the_correction_round_become_needs_human(chained):
    d, b1, els, ids = chained["d"], chained["b1"], chained["els"], chained["ids1"]
    assert _mapstage(d, b1, "B", "--reopen", "new category")[0] == 0
    assert _mapstage(d, b1, "B", "--elements", els)[0] == 1          # round 1
    code, m = _mapstage(d, b1, "B", "--elements", els)               # the correction round left it
    assert code == 1 and "--leave-out-rejects" in m["next_step"], m
    code, m = _mapstage(d, b1, "B", "--elements", els, "--leave-out-rejects")
    assert code == 0 and m["map"], m
    lines = [json.loads(x) for x in Path(m["map"]).read_text().splitlines()]
    assert [x["id"] for x in lines] == ids  # one line per anchor
    assert lines[3]["status"] == "needs-human" and lines[3]["note"].startswith("[no rule] not yet re-mapped"), lines[3]


def test_reopen_refusals_move_nothing(chained, tmp_path):
    d, b1, b2 = chained["d"], chained["b1"], chained["b2"]
    before = _snapshot(d)
    for letter, pattern, why in (("A", "role unclear", "no needs-human line"),        # not in this pass
                                 ("B", "role unclear", "no needs-human line"),
                                 ("A", "   ", "needs the name")):
        code, r = _mapstage(d, b1, letter, "--reopen", pattern)
        assert code == 1 and why in r["refused"], r
    code, r = _mapstage(d, b2, "B", "--reopen", "new category")   # every line of that pass is mapped
    assert code == 1 and "no needs-human line" in r["refused"], r
    code, r = _mapstage(d, b1, "A", "--reopen", "new category", "--retire")
    assert code == 1 and "a run of its own" in r["refused"]
    assert _snapshot(d) == before

    # a map file of the kbqa 6.21 era: no sidecar, so not reopened line by line
    old, b = _old_subject(tmp_path / "old")
    code, r = _mapstage(old, b, "B", "--reopen", "new category")
    assert code == 1 and "has no" in r["refused"] and "--no-record" in r["next_step"], r
    # with a sidecar, a story that is not the built story refuses the whole reopen, naming the line
    (old / mapstage.meta_name(b, "B")).write_text(json.dumps({"staging_sha256": "0" * 64}))
    mp = old / mapstage.map_name(b, "B")
    mp.write_text(mp.read_text().replace("As an operator (APQC-closest), I want", "As a operator, I want", 1))
    before = _snapshot(old)
    code, r = _mapstage(old, b, "B", "--reopen", "new category")
    assert code == 1 and "line 1 (example.docs.webhooks) cannot be carried over" in r["refused"], r
    assert _snapshot(old) == before


def _line(**kw):
    base = {"id": "x.1", "user_story": "", "role": "operator", "role_source": "rbac-row", "actor": "B",
            "theme": "I01", "theme_links": [], "pcf_ids": [{"pcf_id": "10001", "hierarchy_id": "1.1", "name": "N"}],
            "confidence": "high", "status": "mapped", "note": ""}
    base.update(kw)
    return {k: base[k] for k in mapstage.FIELDS}


@pytest.mark.parametrize("article,role,source,want,so_that,theme", [
    ("an", "operator", "apqc-closest", "to send", "it arrives", "I01"),
    ("a", "manager", "rbac-row", "to approve", "", "I01"),
    ("", "admins", "rbac-vendor:x.2", "to see it, so they know", "", "I01"),
    ("", "", "", "", "", "NO-FUNCTION"),
    ("a", "clerk", "rbac-row", "to file, so that it is kept", "it is found", "I01"),
])
def test_a_map_line_reads_back_as_its_draft_exactly(article, role, source, want, so_that, theme):
    draft = {"id": "x.1", "article": article, "role": role, "role_source": source, "actor": "B", "want": want,
             "so_that": so_that, "theme": theme, "theme_links": [], "pcf_ids": ["10001"], "confidence": "high",
             "status": "mapped", "note": ""}
    line = _line(user_story=mapstage.story_of(draft), role=role, role_source=source, theme=theme)
    back, why = mapstage.draft_of(line)
    if want and ", so that " in want:  # the story holds the joining words twice: never guessed
        assert back is None and "more than once" in why
        return
    assert why == "" and mapstage.story_of(back) == line["user_story"] and back["pcf_ids"] == ["10001"]
    assert {k: back[k] for k in ("article", "want", "so_that")} == {"article": article, "want": want,
                                                                     "so_that": so_that}


def test_a_map_line_that_cannot_be_read_back_is_named():
    assert mapstage.draft_of(_line(user_story="As an operator, I want x"))[0] is not None
    assert "cannot be read back" in mapstage.draft_of(_line(user_story="As the operator, I want x"))[1]
    assert "cannot be read back" in mapstage.draft_of(_line(user_story="", theme="I01"))[1]
    bad = dict(_line(user_story="As an operator, I want x"))
    bad = {"user_story": bad.pop("user_story"), **bad}
    assert "keys" in mapstage.draft_of(bad)[1]
    assert "[<name>]" in mapstage.draft_of(_line(user_story="As an operator, I want x", status="needs-human",
                                                 note="no pattern"))[1]
