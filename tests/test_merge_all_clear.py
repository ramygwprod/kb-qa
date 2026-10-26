"""v6.23.0 — `/kbqa-merge <subject> --all-clear`: every CLEAR batch, one at a time.

Every batch CLEAR on its current staging bytes whose rows are not yet in the
tree — selected by the ledger's own code — goes through the single-batch merge
path, so each has its own checks, pre-merge hash, log line and proof line. A
batch whose rows point (`same_feature_as`) at an anchor another selected batch
holds merges after that batch; otherwise batch-name order. The run stops at the
first refusal and the merges before it stay, each undoable on its own.
"""

import importlib.util
import json
import shutil
from types import SimpleNamespace

from test_merge import B, MERGE, checked, ids, log, merge, sha
from test_same_feature import _edit_rows

B2, B3 = "docs-2026-02-01", "docs-2026-02-02"


def another_batch(d, batch, tag):
    """Another CLEAR batch in the subject: the fixture's pages, ids under `tag`."""
    src = d / f"_collect-{B}-staging.md"
    text = src.read_text().replace(f"batch: {B}", f"batch: {batch}") \
        .replace(f"_capture-{B}.raw.txt", f"_capture-{batch}.raw.txt") \
        .replace(f"# Staging — {B}", f"# Staging — {batch}") \
        .replace('"example.docs.', f'"example.{tag}.')
    shutil.copy(d / f"_capture-{B}.raw.txt", d / f"_capture-{batch}.raw.txt")
    (d / f"_collect-{batch}-staging.md").write_text(text)
    return checked(d.parent, d.name, batch)


def merge_all(d, *args):
    import subprocess
    import sys
    p = subprocess.run([sys.executable, str(MERGE), "--vendor-dir", str(d), "--all-clear", *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def dependent(tmp_path):
    """B's last row is another source of a feature whose anchor only B2 holds:
    B2 merges first, though B sorts first by name."""
    d = another_batch(checked(tmp_path, "clear"), B2, "docs2")
    _edit_rows(d / f"_collect-{B}-staging.md", lambda o: o[3].update(same_feature_as="example.docs2.inbox"))
    return checked(tmp_path, "clear")


def _merged_batches(d):
    return [e["batch"] for e in log(d) if e["action"] == "merge"]


# ── the run ─────────────────────────────────────────────────────────────────

def test_the_anchors_batch_merges_first_each_with_its_own_hash_log_and_proof(tmp_path):
    d = dependent(tmp_path)
    tree = d / "feature-tree.md"
    before, old_ids = sha(tree), ids(tree)
    code, out = merge_all(d)
    assert code == 0 and "ALL MERGED — 2 batch(es)" in out, out
    assert f"2. {B} — after {B2}, which holds its anchors" in out
    assert _merged_batches(d) == [B2, B]
    first, second = log(d)
    assert first["tree_sha256_before"] == before and second["tree_sha256_before"] == first["tree_sha256_after"]
    assert second["tree_sha256_after"] == sha(tree)
    assert first["proof_after"] == second["proof_before"] and "rows=9 ·" in second["proof_after"]
    assert out.count("MERGED — tree sha256") == 2
    assert out.count("G6 after merge") == 1, "G6 runs once, after the last merge"
    assert len(ids(tree)) == len(old_ids) + 8


def test_a_dry_run_shows_the_plan_and_writes_nothing(tmp_path):
    d = dependent(tmp_path)
    before = sha(d / "feature-tree.md")
    code, out = merge_all(d, "--dry-run")
    assert code == 0, out
    assert f"1. {B2}" in out and f"2. {B} — after {B2}" in out
    # the second batch is checked on the tree as the first merge would leave it
    assert "rows: tree 1 + batch 4 = 5" in out and "rows: tree 5 + batch 4 = 9" in out, out
    assert "all 2 batch(es) would merge" in out
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()


def test_the_run_stops_at_the_first_refusal_and_keeps_the_merges_before_it(tmp_path):
    d = another_batch(another_batch(checked(tmp_path, "clear"), B2, "docs2"), B3, "docs3")
    vf = d / "_qa" / f"{B2}.g3_grounding.json"  # the report stays CLEAR; the evidence does not
    v = json.loads(vf.read_text())
    v["verdict"] = "FAIL"
    vf.write_text(json.dumps(v))
    before = sha(d / "feature-tree.md")
    code, out = merge_all(d, "--dry-run")
    assert code == 1 and f"would merge first: {B}" in out and f"not attempted: {B3}" in out, out
    assert "G6" not in out, "a dry run runs no G6"
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()
    code, out = merge_all(d)
    assert code == 1, out
    assert _merged_batches(d) == [B], "the merge before the refusal stays, logged"
    assert ids(d / "feature-tree.md")[-4:] == [
        "example.docs.inbox", "example.docs.reports", "example.docs.roles", "example.docs.api"]
    reason = next(ln for ln in out.splitlines() if ln.startswith("REFUSED: "))[len("REFUSED: "):]
    assert "g3_grounding is FAIL" in reason
    assert f"  merged: {B} — they stay merged" in out
    assert f"  refused: {B2} — {reason}\n" in out, "the reason word for word"
    assert f"  not attempted: {B3}" in out
    assert out.count("G6 after merge") == 1
    assert not any("docs3" in i for i in ids(d / "feature-tree.md"))


def test_nothing_clear_is_said_plainly_and_writes_nothing(tmp_path):
    d = checked(tmp_path, "blocked")
    before = sha(d / "feature-tree.md")
    code, out = merge_all(d)
    assert code == 0 and "Nothing to merge" in out, out
    assert f"left out: {B} — check: BLOCKED" in out
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()


def test_a_batch_already_in_the_tree_is_left_out_not_merged_again(tmp_path):
    d = another_batch(checked(tmp_path, "clear"), B2, "docs2")
    assert merge(d)[0] == 0
    code, out = merge_all(d)
    assert code == 0, out
    assert f"left out: {B} — merged" in out
    assert _merged_batches(d) == [B, B2]


def test_a_batch_partly_in_the_tree_is_left_out_for_a_human(tmp_path):
    d = checked(tmp_path, "id-clash")
    before = sha(d / "feature-tree.md")
    code, out = merge_all(d)
    assert code == 0 and "Nothing to merge" in out, out
    assert f"left out: {B} — partly merged (1 of 4 ids in the tree) — a human compares" in out
    assert sha(d / "feature-tree.md") == before


def test_batches_that_wait_on_each_other_are_refused_before_anything_merges(tmp_path):
    d = another_batch(checked(tmp_path, "clear"), B2, "docs2")
    _edit_rows(d / f"_collect-{B}-staging.md", lambda o: o[3].update(same_feature_as="example.docs2.inbox"))
    _edit_rows(d / f"_collect-{B2}-staging.md", lambda o: o[3].update(same_feature_as="example.docs.reports"))
    checked(tmp_path, "clear")
    checked(tmp_path, "clear", B2)
    before = sha(d / "feature-tree.md")
    code, out = merge_all(d)
    assert code == 1 and "wait on each other" in out and f"{B} waits on {B2}" in out, out
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()


# ── the forms ───────────────────────────────────────────────────────────────

def test_all_clear_and_one_batch_together_are_refused(tmp_path):
    d = checked(tmp_path, "clear")
    before = sha(d / "feature-tree.md")
    code, out = merge(d, "--all-clear")
    assert code == 1 and "not both" in out, out
    code, out = merge_all(d, "--undo")
    assert code == 1 and "--undo undoes one batch" in out, out
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()


def test_neither_a_batch_nor_all_clear_is_a_usage_error(tmp_path):
    import subprocess
    import sys
    p = subprocess.run([sys.executable, str(MERGE), "--vendor-dir", str(checked(tmp_path, "clear"))],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "--all-clear" in p.stderr


def test_each_merge_of_the_run_is_undone_on_its_own_latest_first(tmp_path):
    d = dependent(tmp_path)
    tree = d / "feature-tree.md"
    before = sha(tree)
    assert merge_all(d)[0] == 0
    code, out = merge(d, "--undo", batch=B2)
    assert code == 1 and "changed since" in out, "only the latest merge is undone"
    assert merge(d, "--undo", batch=B)[0] == 0
    assert merge(d, "--undo", batch=B2)[0] == 0
    assert sha(tree) == before
    assert [e["action"] for e in log(d)] == ["merge", "merge", "undo", "undo"]


# ── G6, once, over every batch the run merged ───────────────────────────────

def _module():
    spec = importlib.util.spec_from_file_location("kbqa_merge_all_clear", MERGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_supplied_tree_is_for_a_dry_run_only(tmp_path, capsys):
    d = checked(tmp_path, "clear")
    before = sha(d / "feature-tree.md")
    r = _module().merge_batch(d, B, False, False, tree_text=(d / "feature-tree.md").read_text())
    assert r.code == 1 and "for a dry run only" in r.reason
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()


def test_g6_runs_once_and_a_finding_on_an_earlier_batch_of_the_run_stops(tmp_path, monkeypatch, capsys):
    d = another_batch(checked(tmp_path, "clear"), B2, "docs2")
    mod = _module()
    calls = []
    where = str(d / f"_collect-{B}-staging.md")  # the first batch the run merges

    def fake(argv):
        calls.append(argv)
        f = SimpleNamespace(code="tree_same_feature_dangling", message="planted", where=where)
        return SimpleNamespace(findings=[f]), 1
    monkeypatch.setattr(mod.g6_integrity, "run", fake)
    assert mod.main(["--vendor-dir", str(d), "--all-clear"]) == 1
    out = capsys.readouterr().out
    assert len(calls) == 1 and "FINDINGS ON THIS TREE OR THE BATCHES MERGED" in out, out
    assert "tree_same_feature_dangling: planted" in out
