"""v6.23.0 — `kbqa map`, the product map: the vendor's architecture as the rows show it.

Read-only, derived by code from the feature tree and every staging file. The
main subject here is built by the chain's own commands (`collect-surface`,
`stage`, `mapstage`, `report`, the real merge — `tests/test_chain_end_to_end.py`'s
helpers): two windows of a made-up vendor's docs, with ways in (an API, a
settings screen, a webhook), other sources in the same batch, in a later batch
and at an unknown position, and one page with no breadcrumb. A second subject
is written by hand, for what the chain never writes: modules that differ only
by case, a row with no position at all, links to no anchor, rows that cannot be
read.
"""

import contextlib
import hashlib
import io
import json
import os

import pytest

import test_chain_end_to_end as chain
from kbqa import cli, collect_surface, fetch, product_map, report, stage
from test_capture import DAY, SeqWeb

U = chain.U
REPORTS = "Delivery reports show every message's final status."
EVENTS = "Webhook events are listed in each delivery report."
HOOKS_ID = "example-co.docs.webhooks.webhooks"


def _map(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = product_map.run([str(a) for a in args])
    return code, out.getvalue()


def _json(*args):
    code, text = _map(*args, "--json")
    return code, json.loads(text)


def _snapshot(root):
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def _iface(d, itype, op, param=None, **kw):
    out = {**d, "interface_type": itype, "operation": op, **kw}
    if param is not None:
        out["parameter"] = param
    return out


def _modules(nodes):
    """{module path: node} over the whole tree."""
    out = {}
    for n in nodes:
        out[n["path"]] = n
        out.update(_modules(n["modules"]))
    return out


def _edit_row(path, rid, **changes):
    lines = path.read_text().splitlines(keepends=True)
    for i, ln in enumerate(lines):
        try:
            obj = json.loads(ln)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("id") == rid:
            obj.update(changes)
            lines[i] = json.dumps(obj, ensure_ascii=False) + "\n"
            path.write_text("".join(lines))
            return
    raise AssertionError(f"no row {rid} in {path}")


@pytest.fixture
def chained(tmp_path, monkeypatch):
    """Two windows staged by the chain's own commands; window 1 checked and merged."""
    web = dict(chain.WEB)
    web[U[4]] = (200, ("<html><body><main><h1>Overview</h1>"
                       f"<p>{REPORTS}</p><p>{EVENTS}</p></main></body></html>").encode(), "text/html")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb(web))
    root = tmp_path / "estate"
    d = chain._estate(root)
    els = str(root / "ref" / "elements.jsonl")
    code, cs = chain._run(collect_surface, "--out", str(d), "--surface", "docs", "--denominator",
                          str(d / f"_denominator-docs-{DAY}.md"), "--select", "2-5", "--max-pages", "2", "--date", DAY)
    assert code == 0 and cs["end"] == "exhausted", cs
    b1, b2 = [w["batch"] for w in cs["windows"]]
    for p in d.glob("_capture-*.raw.txt"):  # a capture comes well before its rows (G1)
        t = p.stat().st_mtime - 60
        os.utime(p, (t, t))

    assert chain._run(stage, "--subject", str(d), "--batch", b1, "--lists")[0] == 0
    chain._write_drafts(d, b1, [
        chain._draft(U[1], chain.HOOKS, "Webhooks"),
        _iface(chain._draft(U[1], "Signing secrets let you verify each webhook call.", "Signing secrets"),
               "user interface", "Webhook settings", "Signing secret", same_feature_as="draft:1"),
        _iface(chain._draft(U[2], "Failed webhook calls are retried for up to 24 hours.", "Retries"),
               "API", "POST /v1/hooks", "retry_hours"),
        _iface(chain._draft(U[2], "A dead-letter queue keeps calls that never succeeded.", "Dead-letter queue"),
               "API", "POST /v1/hooks", "dead_letter", same_feature_as="draft:3")])
    code, s1 = chain._run(stage, "--subject", str(d), "--batch", b1)
    assert code == 0 and s1["rows"] == 4, s1

    assert chain._run(stage, "--subject", str(d), "--batch", b2, "--lists")[0] == 0
    chain._write_drafts(d, b2, [
        chain._draft(U[3], "Templates let you reuse approved message layouts.", "Templates"),
        _iface(chain._draft(U[3], "Variables fill a template with each customer's data.", "Variables"),
               "API", "GET /v1/templates", "variables", same_feature_as="draft:1"),
        _iface(chain._draft(U[3], "Approvals send a template to review before use.", "Approvals"),
               "API", "GET /v1/templates", same_feature_as="draft:1"),
        chain._draft(U[3], "Languages give one template several translations.", "Languages"),
        chain._draft(U[3], chain.HOOKS, "Webhooks"),
        chain._draft(U[4], REPORTS, "Delivery reports"),
        _iface(chain._draft(U[4], EVENTS, "Webhook events"), "webhook", "message.delivered",
               same_feature_as=HOOKS_ID)])
    code, s2 = chain._run(stage, "--subject", str(d), "--batch", b2)
    assert code == 0 and s2["rows"] == 7 and [x["anchor"] for x in s2["linked_by_code"]] == [HOOKS_ID], s2

    chain._map_both(d, b1, els)
    with contextlib.redirect_stdout(io.StringIO()):
        report.run(["--vendor-dir", str(d), "--batch", b1, "--log", str(d / "_qa-log.jsonl")])
    code, txt = chain._merge(d, b1, "--new-tree")
    assert code == 0 and "MERGED" in txt, txt
    return {"root": root, "d": d, "b1": b1, "b2": b2}


def test_the_map_of_a_chain_built_subject(chained):
    d, b1, b2 = chained["d"], chained["b1"], chained["b2"]
    code, out = _json(d)
    assert code == 0 and out["read_only"] is True and out["complete"] is True and out["merged_only"] is False
    mods = _modules(out["modules"])
    # the vendor's breadcrumbs as printed, nested as they nest
    assert set(mods) == {"Docs", "Docs > Webhooks", "Docs > Webhooks > Retries", "Docs > Templates"}, set(mods)
    assert [n["module"] for n in out["modules"]] == ["Docs"]
    assert [c["module"] for c in mods["Docs"]["modules"]] == ["Templates", "Webhooks"]

    [hooks] = mods["Docs > Webhooks"]["features"]
    assert hooks["id"] == HOOKS_ID and hooks["vendor_term"] == "Webhooks" and hooks["source_url"] == U[1]
    assert (hooks["mechanism"], hooks["outcome"], hooks["evidence_grade"], hooks["depth_level"]) == (
        "Native", "yes", "official-doc", "2")
    assert hooks["file"] == "feature-tree.md"  # merged, and still staged: read as merged
    # its other sources: the same batch, a later batch (linked by code), a page with no breadcrumb
    others = {o["vendor_term"]: o for o in hooks["other_sources"]}
    assert set(others) == {"Signing secrets", "Webhooks", "Webhook events"}, others
    assert others["Webhooks"]["parent_path"] == "Docs > Templates"
    assert others["Webhooks"]["file"] == f"_collect-{b2}-staging.md"
    assert others["Webhook events"]["parent_path"] == "unknown"
    assert [(w["interface_type"], w["operation"], [p["parameter"] for p in w["parameters"]]) for w in hooks["ways_in"]] \
        == [("user interface", "Webhook settings", ["Signing secret"]), ("webhook", "message.delivered", [])]
    assert hooks["counts"] == {"features": 1, "other_sources": 3, "interfaces": 2, "interface_rows": 2}

    # an anchor that is itself a way in, and its other source through the same operation
    [retries] = mods["Docs > Webhooks > Retries"]["features"]
    [way] = retries["ways_in"]
    dlq = retries["other_sources"][0]["id"]
    assert way["interface_type"] == "API" and way["operation"] == "POST /v1/hooks"
    assert way["ids"] == sorted([retries["id"], dlq])
    assert way["parameters"] == [{"parameter": "dead_letter", "ids": [dlq]},
                                 {"parameter": "retry_hours", "ids": [retries["id"]]}]

    tpl = {f["vendor_term"]: f for f in mods["Docs > Templates"]["features"]}
    assert set(tpl) == {"Templates", "Languages"}
    [w] = tpl["Templates"]["ways_in"]
    assert w["operation"] == "GET /v1/templates" and len(w["ids"]) == 2 and len(w["parameters"]) == 1
    assert tpl["Languages"]["ways_in"] == [] and tpl["Languages"]["other_sources"] == []

    # counts per module, with sub-modules, and totals
    assert mods["Docs > Webhooks"]["counts"] == hooks["counts"]
    assert mods["Docs > Webhooks"]["with_sub_modules"] == {"features": 2, "other_sources": 4, "interfaces": 3,
                                                           "interface_rows": 4}
    assert mods["Docs"]["counts"] == {"features": 0, "other_sources": 0, "interfaces": 0, "interface_rows": 0}
    assert mods["Docs"]["with_sub_modules"] == {"features": 4, "other_sources": 6, "interfaces": 4, "interface_rows": 6}

    # the page with no breadcrumb: its feature under position unknown, never dropped
    pu = out["position_unknown"]
    [rep] = pu["features"]
    assert rep["vendor_term"] == "Delivery reports" and rep["parent_path"] == "unknown"
    assert pu["other_sources_listed_under_their_feature"] == [
        {"id": others["Webhook events"]["id"], "listed_under": HOOKS_ID}]
    t = out["totals"]
    assert t == {"features": 5, "other_sources": 6, "interfaces": 4, "interface_rows": 6, "rows": 11, "modules": 4,
                 "position_unknown": 2, "depth_unknown": 0, "links_to_no_anchor": 0, "unreadable_rows": 0,
                 "rows_without_id": 0, "ids_read_again": 0}, t
    assert t["rows"] == t["features"] + t["other_sources"] + t["links_to_no_anchor"]


def test_merged_only_reads_the_tree_alone(chained, tmp_path):
    code, out = _json(chained["d"], "--merged-only")
    assert code == 0 and out["merged_only"] is True and out["read_from"] == "the feature tree"
    assert [f["file"] for f in out["files"]] == ["feature-tree.md"]
    mods = _modules(out["modules"])
    assert set(mods) == {"Docs", "Docs > Webhooks", "Docs > Webhooks > Retries"}
    [hooks] = mods["Docs > Webhooks"]["features"]
    assert [o["vendor_term"] for o in hooks["other_sources"]] == ["Signing secrets"]
    assert out["totals"]["rows"] == 4 and out["position_unknown"]["features"] == []
    # no tree: nothing is merged — said, not refused
    (tmp_path / "bare").mkdir()
    code, out = _json(tmp_path / "bare", "--merged-only")
    assert code == 0 and out["tree"] is False and out["totals"]["rows"] == 0
    assert "has no feature-tree.md: nothing is merged" in _map(tmp_path / "bare", "--merged-only")[1]


def test_links_to_no_anchor_are_listed_with_the_ids(chained):
    d, b2 = chained["d"], chained["b2"]
    stg = d / f"_collect-{b2}-staging.md"
    _, before = _json(d)
    tpl = {f["vendor_term"]: f for f in _modules(before["modules"])["Docs > Templates"]["features"]}
    variables = next(o["id"] for o in tpl["Templates"]["other_sources"] if o["vendor_term"] == "Variables")
    approvals = next(o["id"] for o in tpl["Templates"]["other_sources"] if o["vendor_term"] == "Approvals")
    _edit_row(stg, variables, same_feature_as="example-co.docs.nowhere")
    _edit_row(stg, approvals, same_feature_as=variables)  # names a row that is not an anchor now
    code, out = _json(d)
    assert code == 0
    broken = {b["id"]: b for b in out["links_to_no_anchor"]}
    assert set(broken) == {variables, approvals}, broken
    assert broken[variables]["same_feature_as"] == "example-co.docs.nowhere"
    assert broken[variables]["why"] == "no row of the subject has that id"
    assert "itself another source (of 'example-co.docs.nowhere')" in broken[approvals]["why"]
    assert broken[variables]["operation"] == "GET /v1/templates" and broken[variables]["file"] == stg.name
    tpl = {f["vendor_term"]: f for f in _modules(out["modules"])["Docs > Templates"]["features"]}
    assert tpl["Templates"]["other_sources"] == [] and tpl["Templates"]["ways_in"] == []
    t = out["totals"]
    assert t["links_to_no_anchor"] == 2 and t["rows"] == t["features"] + t["other_sources"] + 2
    text = _map(d)[1]
    assert f"- `{variables}` names `example-co.docs.nowhere`: no row of the subject has that id" in text


def test_the_markdown_is_a_nested_list_and_the_cli_runs_it(chained):
    d = chained["d"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["map", str(d)])
    text = out.getvalue()
    assert code == 0 and text.startswith("# Product map — Example-Co"), text
    assert ("- **Docs** — 0 features, 0 other sources, 0 ways in; with sub-modules: 4 features, "
            "6 other sources, 4 ways in") in text
    assert "\n  - **Webhooks** — 1 feature, 3 other sources, 2 ways in; with sub-modules:" in text
    assert f"\n    - feature `{HOOKS_ID}` **Webhooks** — Webhooks does one thing. · Native / yes · official-doc" in text
    assert "\n      - other source `" in text and "at `Docs > Templates`" in text
    assert "\n      - way in: webhook · `message.delivered` — rows `" in text
    assert "parameters: `dead_letter` (`" in text
    assert "## Position unknown — 1 feature, 0 other sources, 0 ways in" in text
    assert f", listed under the feature `{HOOKS_ID}`" in text
    assert "## Links to no anchor — 0" in text and "Incomplete" not in text


def test_the_map_writes_nothing(chained):
    root, d = chained["root"], chained["d"]
    before = _snapshot(root)
    for args in ([d], [d, "--json"], [d, "--merged-only"], [d, "--merged-only", "--json"]):
        assert _map(*args)[0] == 0, args
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["map", str(d)]) == 0
    assert _snapshot(root) == before


# --------------------------------------------------------------------------
# A subject written by hand: what the chain never writes
# --------------------------------------------------------------------------

def _row(rid, **kw):
    base = {"id": rid, "source_url": "https://docs.example.test/x", "source_quote": "q", "access_date": DAY,
            "vendor_term": rid.split(".")[-1].title(), "what_it_does": "Does one thing.", "parent_path": "Docs",
            "evidence_grade": "help", "confidence": "high", "mechanism": "Native", "outcome": "yes",
            "depth_level": "1", "canonical": "NOVEL"}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not ...}


def _write(path, rows, extra=""):
    path.write_text("---\nbatch: docs\n---\n\n" + "".join(json.dumps(r) + "\n" for r in rows) + extra)


@pytest.fixture
def by_hand(tmp_path):
    d = tmp_path / "Made-Up-Co"
    d.mkdir()
    _write(d / "feature-tree.md", [_row("m.a", parent_path="Billing > Invoices")])
    _write(d / "_collect-docs-2026-10-20-w01-staging.md", [
        _row("m.b", parent_path="billing > Invoices"),                     # differs only by case: another module
        _row("m.c", parent_path=..., depth_level="unknown"),               # no parent_path at all
        _row("m.d", parent_path="Billing > Invoices", depth_level="unknown"),
        _row("m.e", same_feature_as="m.a", interface_type="CLI"),           # a way in with no operation named
        _row("m.f", same_feature_as="m.a", operation="invoice list"),       # an operation with no type
        _row("m.g", same_feature_as=["m.a"]),                               # not a row id
        _row("m.h", same_feature_as="m.e"),                                 # a row that is another source
        _row("m.a", vendor_term="Staged copy"),                             # merged and still staged
    ], extra="{ not json\n" + json.dumps({"vendor_term": "no id"}) + "\n")
    return d


def test_modules_are_the_vendors_words_exactly(by_hand):
    code, out = _json(by_hand)
    assert code == 0
    mods = _modules(out["modules"])
    assert set(mods) == {"Billing", "Billing > Invoices", "billing", "billing > Invoices"}, set(mods)
    assert [f["id"] for f in mods["Billing > Invoices"]["features"]] == ["m.a", "m.d"]
    assert [f["id"] for f in mods["billing > Invoices"]["features"]] == ["m.b"]
    a = mods["Billing > Invoices"]["features"][0]
    assert a["vendor_term"] == "A" and a["file"] == "feature-tree.md"  # the tree first
    assert [o["id"] for o in a["other_sources"]] == ["m.e", "m.f"]
    assert a["ways_in"] == [{"interface_type": None, "operation": "invoice list", "ids": ["m.f"], "parameters": []},
                            {"interface_type": "CLI", "operation": None, "ids": ["m.e"], "parameters": []}]
    # no position at all: under position unknown, as printed (missing)
    [c] = out["position_unknown"]["features"]
    assert c["id"] == "m.c" and c["parent_path"] is None
    # a depth that is unknown beside a breadcrumb is named; one with no breadcrumb is not
    assert out["depth_unknown"] == ["m.d"]
    broken = {b["id"]: b["why"] for b in out["links_to_no_anchor"]}
    assert broken == {"m.g": "same_feature_as is not a row id",
                      "m.h": "that row is itself another source (of 'm.a')"}, broken


def test_rows_that_cannot_be_read_are_listed_and_the_map_is_incomplete(by_hand):
    code, out = _json(by_hand)
    assert out["complete"] is False
    stg = "_collect-docs-2026-10-20-w01-staging.md"
    assert [(u["file"], u["line"]) for u in out["unreadable_rows"]] == [(stg, 13)], out["unreadable_rows"]
    assert out["rows_without_id"] == [{"file": stg, "line": 14}]
    assert out["totals"]["unreadable_rows"] == 1 and out["totals"]["rows_without_id"] == 1
    text = _map(by_hand)[1]
    assert "**Incomplete:**" in text and "## Not read" in text and f"{stg} line 14: a row with no id" in text
    assert out["ids_read_again"] == []  # m.a: merged and still staged, read as merged
    _write(by_hand / "_collect-docs-2026-10-21-w02-staging.md", [_row("m.b", vendor_term="Again"), _row("m.a")])
    code, out = _json(by_hand)
    assert out["ids_read_again"] == [{"id": "m.a", "mapped_from": "feature-tree.md",
                                      "not_mapped_from": ["_collect-docs-2026-10-21-w02-staging.md"]},
                                     {"id": "m.b", "mapped_from": stg,
                                      "not_mapped_from": ["_collect-docs-2026-10-21-w02-staging.md"]}], out
    assert out["totals"]["ids_read_again"] == 2 and "read again in" in _map(by_hand)[1]
    (by_hand / "_collect-docs-2026-10-21-w01-staging.md").write_bytes(b"\xff\xfe not text")
    code, out = _json(by_hand)
    assert code == 0 and out["unreadable_files"][0]["file"] == "_collect-docs-2026-10-21-w01-staging.md"


def test_an_empty_subject_is_a_map_of_nothing_and_refusals_exit_1(tmp_path):
    (tmp_path / "s").mkdir()
    code, out = _json(tmp_path / "s")
    assert code == 0 and out["modules"] == [] and out["totals"]["rows"] == 0 and out["complete"] is True
    for args in ((), (tmp_path / "nowhere",)):
        code, text = _map(*args)
        assert code == 1 and json.loads(text)["next_step"] == "operator", (args, text)
    assert "give a subject folder" in json.loads(_map()[1])["refused"]
    assert "no subject folder" in json.loads(_map(tmp_path / "nowhere")[1])["refused"]
