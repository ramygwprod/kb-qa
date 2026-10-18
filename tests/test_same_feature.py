"""v6.19.0 — one feature, several sources, and the ways in.

The operator's rulings of 2026-10-18: an interface (API operation, settings
screen …) is a way in, never a feature; one feature is classified once,
however many pages or operations print it; nothing is lost. A later source of
a feature is a row of its own, grounded like any row, carrying
`same_feature_as: <anchor id>` — the feature tree is append-only, so a source
found later can never be folded into an earlier row.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from kbqa import features
from kbqa.gates import g2_conformance, g5_bundles, g6_integrity, mapcheck
from kbqa.profiles.vendor_catalogue import strict_row_check

HERE = Path(__file__).resolve().parent
FX = HERE / "fixtures" / "contract"
B = "docs-2026-01-31"


def _codes(v):
    return [f.code for f in v.findings]


# ── the row rules ────────────────────────────────────────────────────────────

ROW = {"id": "x.docs.a", "parent_path": "Docs", "evidence_grade": "official-doc"}


def test_an_interface_type_is_one_of_the_standard_terms():
    assert "interface_type_unknown" in {c for c, _ in strict_row_check({**ROW, "interface_type": "endpoint"})}
    for t in ("API", "SDK", "webhook", "CLI", "user interface"):
        assert not strict_row_check({**ROW, "interface_type": t})


def test_an_operation_or_parameter_says_which_way_in():
    for k in ("operation", "parameter"):
        assert "interface_without_type" in {c for c, _ in strict_row_check({**ROW, k: "update queue"})}
    assert not strict_row_check({**ROW, "interface_type": "API", "operation": "update queue"})


def test_same_feature_as_names_another_row():
    for bad in ("", "x.docs.a", 7):
        assert "same_feature_as_invalid" in {c for c, _ in strict_row_check({**ROW, "same_feature_as": bad})}
    assert not strict_row_check({**ROW, "same_feature_as": "x.docs.b"})


# ── G2: the anchor exists and is an anchor ───────────────────────────────────

def _subject(tmp_path):
    d = tmp_path / "Example-Co"
    shutil.copytree(HERE / "fixtures" / "merge" / "clear", d)
    return d


def _edit_rows(stg: Path, edit):
    text = stg.read_text()
    head, rest = text.split("```json\n[\n", 1)
    body, tail = rest.split("\n]\n```", 1)
    objs = [json.loads(ln.rstrip(",")) for ln in body.splitlines()]
    edit(objs)
    stg.write_text(head + "```json\n[\n" + ",\n".join(json.dumps(o) for o in objs) + "\n]\n```" + tail)


def _g2(stg):
    return g2_conformance.run(["--staging", str(stg)])


def test_an_anchor_in_the_same_batch_passes(tmp_path):
    d = _subject(tmp_path)
    stg = d / f"_collect-{B}-staging.md"
    _edit_rows(stg, lambda o: o[3].update(same_feature_as="example.docs.inbox"))
    v, code = _g2(stg)
    assert code == 0, [(f.code, f.message) for f in v.findings]
    assert v.counts["same_feature_rows"] == 1


def test_an_anchor_in_the_tree_passes(tmp_path):
    d = _subject(tmp_path)
    stg = d / f"_collect-{B}-staging.md"
    _edit_rows(stg, lambda o: o[3].update(same_feature_as="example.product.overview"))
    v, code = _g2(stg)
    assert code == 0, [(f.code, f.message) for f in v.findings]


def test_an_anchor_the_subject_does_not_have_fails(tmp_path):
    d = _subject(tmp_path)
    stg = d / f"_collect-{B}-staging.md"
    _edit_rows(stg, lambda o: o[3].update(same_feature_as="example.docs.nowhere"))
    v, code = _g2(stg)
    assert code == 1 and _codes(v) == ["same_feature_unknown"]


def test_a_source_never_points_along_a_chain(tmp_path):
    d = _subject(tmp_path)
    stg = d / f"_collect-{B}-staging.md"
    def edit(o):
        o[2]["same_feature_as"] = "example.docs.inbox"
        o[3]["same_feature_as"] = "example.docs.roles"
    _edit_rows(stg, edit)
    v, code = _g2(stg)
    assert code == 1 and _codes(v) == ["same_feature_not_anchor"]


def test_an_anchor_in_another_staging_file_passes(tmp_path):
    d = _subject(tmp_path)
    other = d / "_collect-docs-2026-02-01-staging.md"
    shutil.copy(d / f"_collect-{B}-staging.md", other)
    _edit_rows(other, lambda o: [x.update(id=x["id"].replace("docs.", "docs2.")) for x in o])
    _edit_rows(other, lambda o: o[0].update(same_feature_as="example.docs.inbox"))
    v, code = _g2(other)
    assert code == 0, [(f.code, f.message) for f in v.findings]


# ── mapcheck: only anchors are classified ────────────────────────────────────

def _mapcheck(tmp_path, stg_edit, map_edit=lambda o: None):
    src = FX / "K5" / "pass"
    stg = tmp_path / f"_collect-{B}-staging.md"
    shutil.copy(src / f"_collect-{B}-staging.md", stg)
    stg.write_text(stg.read_text().replace(
        '"id": "example.docs.api"', '"id": "example.docs.api", "same_feature_as": "example.docs.inbox"')
        if stg_edit else stg.read_text())
    objs = [json.loads(x) for x in (src / f"_map-{B}-A.jsonl").read_text().splitlines() if x.strip()]
    map_edit(objs)
    m = tmp_path / f"_map-{B}-A.jsonl"
    m.write_text("".join(json.dumps(o) + "\n" for o in objs))
    return mapcheck.run(["--staging", str(stg), "--map", str(m),
                         "--codebook", str(FX / "ref" / "codebook.md"),
                         "--elements", str(FX / "ref" / "elements.jsonl")])


def test_another_source_has_no_mapping_line(tmp_path):
    v, code = _mapcheck(tmp_path, True, lambda o: o.pop(3))
    # three classified rows put every element over 30 % — the fixture's size, not this rule
    assert set(_codes(v)) <= {"element_dominates"}, [(f.code, f.message) for f in v.findings]
    assert v.counts["classified_rows"] == 3 and v.counts["other_sources_not_classified"] == 1


def test_a_mapping_line_for_another_source_is_a_finding(tmp_path):
    v, code = _mapcheck(tmp_path, True)
    assert code == 1 and "map_line_for_another_source" in _codes(v)
    assert "map_id_not_in_staging" not in _codes(v)


# ── G5: a term already linked to one feature is not a naming question ────────

def _rows_file(tmp_path, objs):
    p = tmp_path / "_collect-docs-2026-01-31-w01-staging.md"
    p.write_text("---\nbatch: x\n---\n```json\n" + "\n".join(json.dumps(o) for o in objs) + "\n```\n")
    return p


def test_a_term_whose_rows_are_one_feature_is_counted_apart(tmp_path):
    rows = _rows_file(tmp_path, [
        {"id": "x.a", "vendor_term": "Callback", "source_url": "https://x.test/1"},
        {"id": "x.b", "vendor_term": "Callback", "source_url": "https://x.test/2", "same_feature_as": "x.a"},
        {"id": "x.c", "vendor_term": "Routing", "source_url": "https://x.test/1"},
        {"id": "x.d", "vendor_term": "Routing", "source_url": "https://x.test/3"},
    ])
    v, _ = g5_bundles.run(["--rows", str(rows)])
    assert [f.where for f in v.findings] == ["Routing"]
    assert v.counts["terms_at_multiple_urls_one_feature"] == 1


# ── G6: a tree never points at nothing ───────────────────────────────────────

def test_a_tree_row_pointing_at_no_anchor_is_found(tmp_path):
    d = _subject(tmp_path)
    tree = d / "feature-tree.md"
    row = '{"id": "example.product.overview",'
    text = tree.read_text()
    assert row in text
    tree.write_text(text.replace(row, '{"id": "example.product.overview", "same_feature_as": "example.gone",'))
    v, _ = g6_integrity.run(["--root", str(d)])
    assert "tree_same_feature_dangling" in _codes(v)


# ── the list the row-writer reads ────────────────────────────────────────────

def test_the_features_list_holds_anchors_only_with_a_true_outline(tmp_path):
    d = _subject(tmp_path)
    stg = d / f"_collect-{B}-staging.md"
    _edit_rows(stg, lambda o: o[3].update(same_feature_as="example.docs.inbox"))
    text = features.features_list(d)
    lines = text.split("\n")
    assert "example.docs.api" not in text  # another source is not a feature
    for want in ("example.product.overview", "example.docs.inbox", "example.docs.roles"):
        assert sum(want in ln for ln in lines) == 1
    outline = [ln for ln in lines if ln.startswith("- ") and ": lines " in ln]
    assert outline, text
    for ln in outline:  # each range opens on its group's heading and ends on an item
        group, rng = ln[2:].rsplit(": lines ", 1)
        a, b = (int(x) for x in rng.split("–"))
        assert lines[a - 1] == f"## {group}"
        assert lines[b - 1].startswith("- ") and ": lines " not in lines[b - 1]
    assert "4 anchors" in lines[0]


def test_the_check_counts_features_sources_and_ways_in(tmp_path, capsys):
    from kbqa import cli
    d = _subject(tmp_path)
    stg = d / f"_collect-{B}-staging.md"
    def edit(o):
        o[3].update(same_feature_as="example.docs.inbox", interface_type="API", operation="send message")
    _edit_rows(stg, edit)
    cli.main(["report", "--vendor-dir", str(d), "--batch", B])
    assert "features=3  other_sources=1  interfaces=1" in capsys.readouterr().out


# ── merge: the anchor is merged first ────────────────────────────────────────

MERGE = HERE.parent / "skills" / "kbqa-merge" / "scripts" / "merge.py"


def _checked(d, batch):
    import os
    from kbqa import cli
    stg = d / f"_collect-{batch}-staging.md"
    cap = d / f"_capture-{batch}.raw.txt"
    t = stg.stat().st_mtime
    os.utime(cap, (t - 60, t - 60))
    cli.main(["report", "--vendor-dir", str(d), "--batch", batch])


def _merge(d, batch):
    p = subprocess.run([sys.executable, str(MERGE), "--vendor-dir", str(d), "--batch", batch],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_a_source_merges_only_after_its_anchor(tmp_path):
    d = _subject(tmp_path)
    b2 = "docs-2026-02-01"
    text = (d / f"_collect-{B}-staging.md").read_text().replace(f"batch: {B}", f"batch: {b2}") \
        .replace(f"_capture-{B}.raw.txt", f"_capture-{b2}.raw.txt").replace('"example.docs.', '"example.docs2.')
    shutil.copy(d / f"_capture-{B}.raw.txt", d / f"_capture-{b2}.raw.txt")
    (d / f"_collect-{b2}-staging.md").write_text(text)
    _edit_rows(d / f"_collect-{b2}-staging.md", lambda o: o[0].update(same_feature_as="example.docs.inbox"))
    _checked(d, B)
    _checked(d, b2)
    code, out = _merge(d, b2)
    assert code == 1 and "same_feature_as" in out and "merge the batch holding the anchor first" in out, out
    code, out = _merge(d, B)
    assert code == 0, out
    code, out = _merge(d, b2)
    assert code == 0, out


# ── capture writes the list beside its receipt ───────────────────────────────

def test_capture_writes_the_subjects_features_beside_the_receipt(tmp_path, monkeypatch):
    from kbqa import fetch
    from test_capture import DAY, HOST, OK, SeqWeb, _cap, _den
    d = tmp_path / "Example-Co"
    d.mkdir()
    (d / f"_robots-{HOST}-{DAY}.txt").write_text("User-agent: *\nAllow: /\n")
    shutil.copy(HERE / "fixtures" / "merge" / "clear" / "feature-tree.md", d / "feature-tree.md")
    monkeypatch.setattr(fetch, "_sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_open", SeqWeb({f"https://{HOST}/p1": OK}))
    code, r = _cap(d, "--surface", "docs", "--denominator", str(_den(d, n=1)))
    assert code == 0 and r["features"] == f"_raw/{r['batch']}/FEATURES.md"
    text = (d / r["features"]).read_text()
    assert "example.product.overview" in text and text == features.features_list(d)
