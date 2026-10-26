"""v6.23.0 — fixes from the integration review (package V), each on the review's own case.

The review collected one subject three times end to end (`collect-surface`,
`stage`, `mapstage`, the real `/kbqa-check` script and merge — the chain's own
commands, `tests/test_chain_end_to_end.py`'s helpers) and found:

1. an `unchanged since` stop line of collection 2 closing the page in collection
   3, where it had changed and its new row was left out — g4 passed;
2. `compare` calling features removed whose text had only moved, or whose quote
   was still on the page;
3. `kbqa status` counting an earlier collection's captures as the new one's;
4. `--reopen` carrying a map made from other anchors over line by line;
5. a `[no rule]` line blocking every other reopen without naming the way out;
6. drafts written but `kbqa stage` never run shown as "nothing to stage";
7. a window whose drafts were all left out never ending;
8. the product map not saying where each row stands;
9. the texts that describe all of the above.
"""

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import test_chain_end_to_end as ch
from kbqa import (cli, collect_surface, compare, fetch, headings, ledger, mapstage, product_map, stage,
                  stops)
from kbqa.gates import g4_completeness
from test_capture import HOST, SeqWeb

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")

ROOT = Path(__file__).resolve().parent.parent
D1, D2, D3 = "2026-10-18", "2026-10-25", "2026-11-01"
U = {i: f"https://{HOST}/p{i}" for i in range(1, 7)}
HOOKS = ch.HOOKS
P = ch._page
WEB1 = {
    U[1]: P("Docs > Webhooks", HOOKS, "Signing secrets let you verify each webhook call."),
    U[2]: P("Docs > Webhooks > Retries", "Failed webhook calls are retried for up to 24 hours."),
    U[3]: P("Docs > Pricing", "See our plans on the pricing page."),
}
WEB2 = {
    U[1]: WEB1[U[1]],  # unchanged
    U[2]: P("Docs > Webhooks > Retries", "Failed webhook calls are retried for up to 48 hours."),  # changed
    U[3]: WEB1[U[3]],  # unchanged, no_row before
    U[4]: P("Docs > Templates", "Templates let you reuse approved message layouts."),  # new
}
WEB3 = {
    U[1]: P("Docs > Webhooks", "Webhooks notify your server when a message is read.",
            "Signing secrets let you verify each webhook call."),  # changed in the third
    U[2]: WEB2[U[2]], U[3]: WEB1[U[3]],
    U[4]: P("Docs > Templates", "Templates let you reuse approved message layouts.", "Variables fill a template."),
}
RETRIES_ID = "example-co.docs.retries.retries"
HOOKS_ID = "example-co.docs.webhooks.webhooks"
SECRETS_ID = "example-co.docs.webhooks.signing-secrets"
TEMPLATES_ID = "example-co.docs.templates.templates"


def run(mod, *a):
    return ch._run(mod, *a)


def text_of(mod, *a):
    """A command's markdown summary."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mod.run(list(a))
    return out.getvalue()


def den(d, day, nums):
    p = d / f"_denominator-docs-{day}.md"
    p.write_text(f"Index: docs, rung 1 — https://{HOST}/llms.txt\n" + "".join(f"- [P{i}]({U[i]})\n" for i in nums))
    (d / f"_robots-{HOST}-{day}.txt").write_text("User-agent: *\nAllow: /\n")
    return p


def collect(d, monkeypatch, day, web, nums):
    monkeypatch.setattr(fetch, "_open", SeqWeb(dict(web)))
    dn = den(d, day, nums)
    code, cs = run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator", str(dn),
                   "--select", f"2-{len(nums) + 1}", "--date", day)
    assert code == 0, cs
    [b] = [w["batch"] for w in cs["windows"]]
    return b, cs


def stage_window(d, b, drafts, add=True):
    code, lst = run(stage, "--subject", str(d), "--batch", b, "--lists")
    assert code == 0, lst
    ch._write_drafts(d, b, drafts)
    code, s = run(stage, "--subject", str(d), "--batch", b)
    if add:
        for ln in s.get("stop_lines_to_add", []):
            assert run(stops, "add", str(d), ln)[0] == 0, ln
    return code, s


def g4(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["g4", *map(str, args)])
    return code, json.loads(out.getvalue())


def codes(v):
    return [f["code"] for f in v["findings"]]


def estate(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    root = tmp_path / "estate"
    d = ch._estate(root)
    for p in d.glob("_denominator-*"):  # the chain's own denominator: these collections bring theirs
        p.unlink()
    return root, d, str(root / "ref" / "elements.jsonl")


def first_collection(d, monkeypatch):
    b1, _ = collect(d, monkeypatch, D1, WEB1, (1, 2, 3))
    code, s1 = stage_window(d, b1, [
        ch._draft(U[1], HOOKS, "Webhooks"),
        ch._draft(U[1], "Signing secrets let you verify each webhook call.", "Signing secrets"),
        ch._draft(U[2], "Failed webhook calls are retried for up to 24 hours.", "Retries"),
        {"page": U[3], "no_row": "pricing page"}])
    assert code == 0, s1
    return b1


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Collection 1 staged, mapped, checked CLEAR and merged; collection 2 (p1
    and p3 unchanged, p2 changed, p4 new) staged, mapped and checked CLEAR."""
    root, d, els = estate(tmp_path, monkeypatch)
    b1 = first_collection(d, monkeypatch)
    ch._map_both(d, b1, els)
    out = ch._check(d, root)
    assert f"-- {b1}\n    status=CLEAR" in out, out
    code, txt = ch._merge(d, b1, "--new-tree")
    assert code == 0, txt
    b2, _ = collect(d, monkeypatch, D2, WEB2, (1, 2, 3, 4))
    code, s2 = stage_window(d, b2, [
        {"page": U[1], "unchanged": b1},
        ch._draft(U[2], "Failed webhook calls are retried for up to 48 hours.", "Retries")
        | {"same_feature_as": RETRIES_ID},
        {"page": U[3], "unchanged": b1},
        ch._draft(U[4], "Templates let you reuse approved message layouts.", "Templates")])
    assert code == 0, s2
    ch._map_both(d, b2, els)
    out = ch._check(d, root)
    assert f"-- {b2}\n    status=CLEAR" in out, out
    return {"root": root, "d": d, "els": els, "b1": b1, "b2": b2, "s2": s2}


# ── 1 · the unchanged line is scoped to its window ──────────────────────────

def test_a_page_changed_later_and_left_out_is_never_closed_by_an_earlier_unchanged_line(two, monkeypatch, tmp_path):
    d, b1, b2 = two["d"], two["b1"], two["b2"]
    b3, _ = collect(d, monkeypatch, D3, WEB3, (1, 2, 3, 4))
    bad = [ch._draft(U[1], "Webhooks notify your server when a message is opened.", "Webhooks"),  # not on the page
           {"page": U[2], "unchanged": b2}, {"page": U[3], "unchanged": b2},
           ch._draft(U[4], "Variables fill a template.", "Variables")]
    assert stage_window(d, b3, bad, add=False)[0] == 1
    assert run(stage, "--subject", str(d), "--batch", b3)[0] == 1           # the correction round, still rejected
    code, s3 = run(stage, "--subject", str(d), "--batch", b3, "--leave-out-rejects")
    assert code == 0 and s3["rows"] == 1 and len(s3["needs_operator"]) == 1, s3
    for ln in s3["stop_lines_to_add"]:
        run(stops, "add", str(d), ln)
    sf = d / stops.STOPS_NAME
    st2, st3 = d / f"_collect-{b2}-staging.md", d / f"_collect-{b3}-staging.md"

    # g4 window mode: p1 is accounted for in b2's window only — b3's fails, b2's passes
    code, v = g4("--rows", st3, "--stops", sf)
    assert code == 1 and "window_underwritten" in codes(v), v
    code, v = g4("--rows", st2, "--stops", sf)
    assert code == 0 and v["verdict"] == "PASS", v
    # the unchanged line is scoped to the window that found the page unchanged
    assert f"- {U[1]} | unchanged since {b1}, in {b2}" in two["s2"]["stop_lines_to_add"], two["s2"]
    code, v = g4("--rows", st2, st3, "--stops", sf)   # as /kbqa-check runs it: every window of the surface
    assert [f["where"] for f in v["findings"] if f["code"] == "window_underwritten"] == [str(st3)], v
    # never looser: an unscoped line still counts in every window, a line scoped to b3 counts in b3
    for extra in (f"- {U[1]} | no feature: an overview", f"- {U[1]} | unchanged since {b2}, in {b3}"):
        more = tmp_path / "stops-more.md"
        more.write_text(sf.read_text() + extra + "\n")
        assert g4("--rows", st3, "--stops", more)[0] == 0, extra

    # g4 denominator mode: a scoped line counts only in its own window's collection
    code, v = g4("--denominator", d / f"_denominator-docs-{D3}.md", "--rows", st3, "--stops", sf)
    assert code == 1 and [f["where"] for f in v["findings"] if f["code"] == "index_item_without_row"] == [U[1]], v
    assert v["counts"]["stop_lines_of_other_collections"] >= 2, v["counts"]
    code, v = g4("--denominator", d / f"_denominator-docs-{D2}.md", "--rows", st2, "--stops", sf)
    assert code == 0, v

    # the ledger counts p1 open; the heading check no longer explains p1's headings in b3
    docs = next(s for s in run(ledger, str(d), "--json")[1]["surfaces"] if s["surface"] == "docs")
    assert docs["open_item_urls"] == [U[1]], docs
    hc = headings.coverage(d, b3)
    assert U[1] in {h["url"] for h in hc["headings_without_row"]}, hc
    assert U[1] not in {h["url"] for h in headings.coverage(d, b2)["headings_without_row"]}

    # compare must not call p1's features removed
    code, c = run(compare, str(d), "--from", D2, "--to", D3, "--json")
    feats = {e["id"]: e for e in c["surfaces"][0]["features"]}
    assert feats[HOOKS_ID]["state"] == "unknown" and feats[SECRETS_ID]["state"] == "unknown", feats
    assert "removed" not in {e["state"] for e in feats.values()}


def test_compare_counts_a_scoped_line_only_on_its_own_side():
    side = {"captures": {U[1]: {"batch": "docs-2026-11-01-w01", "url": U[1], "text_sha256": "x"}},
            "rows": {}, "_stops": {U[1]: ["unchanged since docs-2026-10-18-w01, in docs-2026-10-25-w01"]}}
    known, _, why = compare.features_of(Path("."), {**side, "batches": ["docs-2026-11-01-w01"]}, U[1])
    assert known is False and "no stop line names it" in why
    known, ids, _ = compare.features_of(Path("."), {**side, "batches": ["docs-2026-10-25-w01"]}, U[1])
    assert known is True and ids == set()


def test_the_scoped_reason_is_in_the_vocabulary():
    assert stops.unchanged_reason("docs-2026-10-18-w01", "docs-2026-10-25-w01") == \
        "unchanged since docs-2026-10-18-w01, in docs-2026-10-25-w01"
    url, reason, entry, surface = stops.parse_line(
        f"- {U[1]} | unchanged since docs-2026-10-18-w01, in docs-2026-10-25-w01")
    assert entry.closes_surface is False and surface is None
    assert stops.scoped_to(reason) == "docs-2026-10-25-w01"
    assert stops.scoped_to("no feature: unchanged since docs-2026-10-18-w01") is None
    with pytest.raises(stops.StopLineError):
        stops.parse_line(f"- {U[1]} | unchanged since docs-2026-10-18-w01, in docs-2026-10-25-w01 (surface docs)")


# ── 2 · removed only when the text is truly gone ────────────────────────────

def test_a_feature_whose_quote_is_still_on_the_page_is_never_removed_and_the_map_says_where_rows_stand(
        two, monkeypatch):
    d, b1, b2 = two["d"], two["b1"], two["b2"]
    b3, _ = collect(d, monkeypatch, D3, WEB3, (1, 2, 3, 4))
    code, s3 = stage_window(d, b3, [
        ch._draft(U[1], "Webhooks notify your server when a message is read.", "Webhooks"),
        ch._draft(U[1], "Signing secrets let you verify each webhook call.", "Signing secrets"),
        {"page": U[2], "unchanged": b2}, {"page": U[3], "unchanged": b2},
        ch._draft(U[4], "Variables fill a template.", "Variables")])  # Templates not drafted again
    assert code == 0, s3
    code, c = run(compare, str(d), "--from", D2, "--to", D3, "--json")
    s = c["surfaces"][0]
    assert s["from"]["coverage"]["complete"] and s["to"]["coverage"]["complete"], s
    feats = {e["id"]: e for e in s["features"]}
    t = feats[TEMPLATES_ID]
    assert t["state"] == "unknown" and "quote still on the page; no row records it" in t["why"], t
    assert feats[HOOKS_ID]["state"] == "removed", "its quote is gone from the page: truly removed"
    assert feats[SECRETS_ID]["state"] == "changed"

    # 8 · the map gives every row its access date and where it stands
    code, mp = run(product_map, str(d), "--json")
    assert code == 0, mp
    rows = {}

    def walk(n):
        for f in n["features"]:
            rows[f["id"]] = f
            for o in f["other_sources"]:
                rows[o["id"]] = o
        for m in n["modules"]:
            walk(m)
    for n in mp["modules"]:
        walk(n)
    assert (rows[HOOKS_ID]["state"], rows[HOOKS_ID]["access_date"]) == ("merged", D1), rows[HOOKS_ID]
    assert rows[TEMPLATES_ID]["state"] == "staged" and rows[TEMPLATES_ID]["access_date"] == D2
    assert rows[TEMPLATES_ID]["check"] == {"status": "CLEAR", "round": 1}, rows[TEMPLATES_ID]
    variables = next(r for r in rows.values() if r["vendor_term"] == "Variables")
    assert (variables["state"], variables["access_date"], variables["batch"]) == ("unchecked", D3, b3), variables
    assert mp["row_states"] == {"merged": 3, "staged": 2, "unchecked": 3}, mp["row_states"]
    assert mp["totals"]["rows"] == sum(mp["row_states"].values())
    text = text_of(product_map, str(d))
    assert f"accessed {D1} · merged" in text and f"staged in {b2} (CLEAR, round 1)" in text, text
    assert f"unchecked, in {b3}" in text
    # --merged-only stays as it is: the tree alone
    code, mo = run(product_map, str(d), "--merged-only", "--json")
    assert mo["totals"]["rows"] == 3 and mo["row_states"] == {"merged": 3, "staged": 0, "unchecked": 0}


def test_a_page_whose_text_moved_is_never_removed_and_drafts_not_staged_are_visible(tmp_path, monkeypatch):
    root, d, els = estate(tmp_path, monkeypatch)
    b1 = first_collection(d, monkeypatch)
    # collection 2: p2 moved to p5 (the same text), p1 and p3 unchanged
    b2, cs = collect(d, monkeypatch, D2, {U[1]: WEB1[U[1]], U[3]: WEB1[U[3]], U[5]: WEB1[U[2]]}, (1, 3, 5))
    for ln in cs["stop_lines_to_add"]:
        run(stops, "add", str(d), ln)
    assert run(stage, "--subject", str(d), "--batch", b2, "--lists")[0] == 0
    ch._write_drafts(d, b2, [{"page": U[1], "unchanged": b1}, {"page": U[3], "unchanged": b1}])

    # 6 · drafted, but kbqa stage has not run: never "nothing to stage"
    [u] = collect_surface.unstaged(d, "docs")
    assert (u["batch"], u["state"]) == (b2, collect_surface.STAGE_NOT_RUN), u
    code, s = run(stage, "--subject", str(d), "--batch", b2)
    assert code == 0 and s["next_step"] == stage.NO_ROWS_STEP, s
    [u] = collect_surface.unstaged(d, "docs")
    assert u["state"] == collect_surface.STAGE_NOT_RUN, "its stop lines are not added yet"
    for ln in s["stop_lines_to_add"]:
        run(stops, "add", str(d), ln)
    [u] = collect_surface.unstaged(d, "docs")
    assert u["state"] == collect_surface.ALL_NO_ROW, u

    # 2 · the earlier text is held under another URL: moved, not removed
    code, c = run(compare, str(d), "--from", D1, "--to", D2, "--json")
    s = c["surfaces"][0]
    assert s["to"]["coverage"]["complete"], s["to"]
    p2 = next(e for e in s["pages"] if e["url"] == U[2])
    assert p2["state"] == "unknown" and p2["why"] == f"moved to {U[5]}", p2
    r = next(e for e in s["features"] if e["id"] == RETRIES_ID)
    assert r["state"] == "unknown" and f"its page {U[2]} moved to {U[5]}" in r["why"], r
    assert s["page_counts"]["removed"] == 0 and s["feature_counts"]["removed"] == 0


# ── 3 · the ledger counts the current denominator's collection ──────────────

def test_the_ledger_counts_the_current_collection_and_every_collection_apart(tmp_path, monkeypatch):
    root, d, els = estate(tmp_path, monkeypatch)
    first_collection(d, monkeypatch)
    den(d, D2, (1, 2, 3, 4))  # the re-collection is planned: a new denominator, nothing captured from it yet
    code, st = run(ledger, str(d), "--json")
    docs = next(x for x in st["surfaces"] if x["surface"] == "docs")
    assert docs["denominator"] == f"_denominator-docs-{D2}.md" and docs["collection"]["batches"] == []
    assert (docs["items"], docs["items_captured"], docs["items_staged"]) == (4, 0, 0), docs
    assert docs["open_items"] == 3 and sorted(docs["open_item_urls"]) == [U[1], U[2], U[4]], docs  # p3: its stop line
    a = docs["all_collections"]
    assert (a["batches"], a["items_captured"], a["items_staged"], a["open_items"]) == (1, 3, 3, 1), a
    text = text_of(ledger, str(d))
    assert "docs all collections (1 batch(es)): captured 3, staged 3, open 1" in text, text


# ── 4, 5 · --reopen ─────────────────────────────────────────────────────────

def _snapshot(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*"))


def test_reopen_refuses_a_map_made_from_other_anchors(tmp_path, monkeypatch):
    root, d, els = estate(tmp_path, monkeypatch)
    b1 = first_collection(d, monkeypatch)
    ids = mapstage._anchors(d / f"_collect-{b1}-staging.md")[0]
    lines = [dict(ch._mapline(ids[0], 0), status="needs-human", note="[Pattern X] which role?")] + \
        [ch._mapline(i, k) for k, i in enumerate(ids[1:], start=1)]
    (d / mapstage.draft_name(b1, "A")).write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--elements", els)[0] == 0
    st = d / f"_collect-{b1}-staging.md"
    good = st.read_text()

    # the bytes changed, the anchors did not: the ruling still reopens the same reading
    st.write_text(good.replace("Retries does one thing.", "Retries does one thing well."))
    plan = mapstage.reopen_plan(d, b1, "A", "Pattern X")
    assert plan["reopened"] == [ids[0]]

    # the fix round changed an anchor's id: the map was made from other anchors
    st.write_text(good.replace(ids[-1], ids[-1] + "-2"))
    before = _snapshot(d)
    code, r = run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--reopen", "Pattern X")
    assert code == 1 and "made from other anchors" in r["refused"], r
    assert r["next_step"].endswith(f"--pass A --retire — then the whole pass is mapped again, the ruling applied")
    assert _snapshot(d) == before, "nothing moved"
    code, r = run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--retire")
    assert code == 0 and r["anchor_set_changed"] is True, r


def test_a_no_rule_line_names_the_way_out_of_a_reopen(tmp_path, monkeypatch):
    root, d, els = estate(tmp_path, monkeypatch)
    b1 = first_collection(d, monkeypatch)
    ids = mapstage._anchors(d / f"_collect-{b1}-staging.md")[0]
    nh = dict(ch._mapline(ids[0], 0), status="needs-human", note="[Pattern X] which role is it?")
    for r in range(3):  # the other anchors never get a line
        (d / mapstage.draft_name(b1, "A")).write_text(json.dumps(nh) + "\n")
        extra = ["--leave-out-rejects"] if r == 2 else []
        run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--elements", els, *extra)
    assert "[no rule]" in (d / mapstage.map_name(b1, "A")).read_text()
    before = _snapshot(d)
    code, r = run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--reopen", "Pattern X")
    assert code == 1 and 'reopen it first with --reopen "no rule"' in r["refused"], r
    assert '--pass A --reopen "no rule"' in r["next_step"], r
    assert _snapshot(d) == before
    code, pr = run(ledger, str(d), "--pattern", "Pattern X", "--json")
    [p] = pr["passes"]
    assert '--reopen "no rule"' in p["reopen_refused"] and '--reopen "no rule"' in p["reopen_next_step"], p
    assert '--reopen "no rule"' in text_of(ledger, str(d), "--pattern", "Pattern X")
    code, r = run(mapstage, "--subject", str(d), "--batch", b1, "--pass", "A", "--reopen", "no rule")
    assert code == 0 and r["reopened"] == ids[1:], r


# ── 7 · a window whose drafts were all left out ends ────────────────────────

def test_a_window_whose_drafts_were_all_left_out_is_closed_on_a_record(tmp_path, monkeypatch):
    root, d, els = estate(tmp_path, monkeypatch)
    b1, _ = collect(d, monkeypatch, D1, WEB1, (1, 2, 3))
    bad = [ch._draft(U[1], "Webhooks notify your server when a message is opened.", "Webhooks"),
           ch._draft(U[2], "Failed webhook calls are retried for up to 12 hours.", "Retries"),
           {"page": U[3], "no_row": "pricing page"}]
    assert stage_window(d, b1, bad, add=False)[0] == 1
    assert run(stage, "--subject", str(d), "--batch", b1)[0] == 1
    code, s = run(stage, "--subject", str(d), "--batch", b1, "--leave-out-rejects")
    assert code == 0 and s["rows"] == 0 and s["staging"] is None, s
    assert s["next_step"] == "no rows — skip mapping; the left-out pages are the operator's"
    rec_path = d / stage.closed_name(b1)
    assert s["closed"] == str(rec_path)
    rec = json.loads(rec_path.read_text())
    assert [x["draft"]["page"] for x in rec["left_out"]] == [U[1], U[2]], rec
    assert all(x["reason"] for x in rec["left_out"]) and rec["stop_lines_to_add"] == s["stop_lines_to_add"]
    raw = rec_path.read_bytes()

    # the window has ended: never unstaged, listed closed; stage refuses it; the record is never rewritten
    assert collect_surface.unstaged(d, "docs") == []
    [c] = collect_surface.closed(d, "docs")
    assert (c["batch"], c["left_out"], c["state"]) == (b1, 2, collect_surface.CLOSED)
    code, again = run(stage, "--subject", str(d), "--batch", b1, "--leave-out-rejects")
    assert code == 1 and "closed.json exists" in again["refused"], again
    assert rec_path.read_bytes() == raw
    code, cs = run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator",
                   str(d / f"_denominator-docs-{D1}.md"), "--select", "2-4", "--date", D1)
    assert cs["unstaged"] == [] and [x["batch"] for x in cs["closed"]] == [b1], cs
    docs = next(x for x in run(ledger, str(d), "--json")[1]["surfaces"] if x["surface"] == "docs")
    assert docs["windows"]["unstaged"] == [] and docs["windows"]["closed"][0]["batch"] == b1, docs["windows"]


# ── 9 · the texts follow ────────────────────────────────────────────────────

def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_texts_describe_the_fixes():
    manual, fmt = _read("docs/MANUAL.md"), _read("docs/STAGING-FORMAT.md")
    skill, writer, fetcher = (_read("skills/kbqa-collect/SKILL.md"), _read("agents/kbqa-row-writer.md"),
                              _read("agents/kbqa-fetcher.md"))
    scoped = "unchanged since <earlier batch>, in <this batch>"
    for name, text in (("MANUAL", manual), ("STAGING-FORMAT", fmt), ("SKILL", skill), ("fetcher", fetcher)):
        assert scoped in text, name
        assert "no feature: unchanged since" not in text, name
        assert "closed.json" in text, name
    assert "skipped when every page was drafted `no_row` or `unchanged`" in manual
    sec = manual[manual.index("### 5.12"):manual.index("### 5.13")]
    assert "collection" in sec and "all_collections" in sec and '--reopen "no rule"' in sec
    assert "quote still on the page; no row records it" in manual and "moved to <url>" in manual
    assert "read it whole and draft every feature still on it, not only the new ones" in " ".join(writer.split())
    assert "stage not run" in skill and "stage not run" in fetcher
    assert "`access_date`" in manual[manual.index("### 5.13"):]
