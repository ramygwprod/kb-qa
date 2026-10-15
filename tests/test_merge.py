"""/kbqa-merge — the one step that writes a feature tree, tested as the operator runs it.

`merge.py` appends a CLEAR batch to its subject's `feature-tree.md` (PIPELINE-SPEC
§1 step 5): only CLEAR batches, a pre-merge hash, rows appended unchanged, ids
never renumbered, the proof line recomputed, undo from the log. Each test copies
a fixture, runs the real checks to produce the verdicts a merge reads, then
runs the script as a subprocess.

Most cases are refusals: a merge that has never refused has not been tested.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kbqa import cli
from kbqa.gates import g6_integrity
from kbqa.parsing import parse_staging

HERE = Path(__file__).resolve().parent
MERGE = HERE.parent / "skills" / "kbqa-merge" / "scripts" / "merge.py"
FIXTURES = HERE / "fixtures" / "merge"
B = "docs-2026-01-31"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ids(p: Path):
    return [r.obj["id"] for r in parse_staging(p).rows if r.obj]


def checked(tmp_path, name, batch=B):
    """Copy a fixture and run the checks, as /kbqa-check would before a merge."""
    d = tmp_path / name
    if not d.exists():
        shutil.copytree(FIXTURES / name, d)
    stg = d / f"_collect-{batch}-staging.md"
    cap = d / f"_capture-{batch}.raw.txt"
    t = stg.stat().st_mtime
    os.utime(cap, (t - 60, t - 60))  # G1: the capture precedes the rows
    cli.main(["report", "--vendor-dir", str(d), "--batch", batch])
    return d


def merge(d, *args, batch=B):
    p = subprocess.run([sys.executable, str(MERGE), "--vendor-dir", str(d), "--batch", batch, *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def log(d):
    f = d / "_merge-log.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def second_batch(d, batch="docs-2026-02-01"):
    """Another CLEAR batch in the same subject: same pages, new ids."""
    src = d / f"_collect-{B}-staging.md"
    text = src.read_text().replace(f"batch: {B}", f"batch: {batch}") \
        .replace(f"_capture-{B}.raw.txt", f"_capture-{batch}.raw.txt") \
        .replace(f"# Staging — {B}", f"# Staging — {batch}") \
        .replace('"example.docs.', '"example.docs2.')
    shutil.copy(d / f"_capture-{B}.raw.txt", d / f"_capture-{batch}.raw.txt")
    (d / f"_collect-{batch}-staging.md").write_text(text)
    return checked(d.parent, d.name, batch)


# ── the merge ───────────────────────────────────────────────────────────────

def test_a_dry_run_writes_nothing(tmp_path):
    d = checked(tmp_path, "clear")
    before = sha(d / "feature-tree.md")
    code, out = merge(d, "--dry-run")
    assert code == 0, out
    assert "rows: tree 1 + batch 4 = 5" in out and "DRY RUN" in out
    assert sha(d / "feature-tree.md") == before and not (d / "_merge-log.jsonl").exists()


def test_a_clear_batch_is_appended_unchanged_and_logged(tmp_path):
    d = checked(tmp_path, "clear")
    tree = d / "feature-tree.md"
    before, old_ids = sha(tree), ids(tree)
    staging_objs = [r.obj for r in parse_staging(d / f"_collect-{B}-staging.md").rows]

    code, out = merge(d)
    assert code == 0 and "MERGED" in out, out
    merged = [r.obj for r in parse_staging(tree).rows]
    assert [o["id"] for o in merged] == old_ids + [o["id"] for o in staging_objs]
    assert merged[len(old_ids):] == staging_objs, "rows must be appended unchanged"
    assert 'proof:        "rows=5 · unique_ids=5' in tree.read_text()

    (entry,) = log(d)
    assert entry["tree_sha256_before"] == before and entry["tree_sha256_after"] == sha(tree)
    assert entry["rows_appended"] == 4

    v, _ = g6_integrity.run(["--root", str(d)])
    assert not {"clear_not_merged", "proof_count_mismatch"} & {f.code for f in v.findings}


def test_merging_one_of_two_clear_batches_is_not_reported_as_a_failure(tmp_path):
    """Found in review: any `clear_not_merged` in the subject failed the merge.

    With two CLEAR batches waiting, merging the first always "failed" because
    the second was still unmerged — a finding about another batch.
    """
    d = second_batch(checked(tmp_path, "clear"))
    code, out = merge(d)
    assert code == 0, out
    assert "1 other finding(s) in the subject" in out


# ── refusals ────────────────────────────────────────────────────────────────

def test_a_blocked_batch_is_refused(tmp_path):
    d = checked(tmp_path, "blocked")
    before = sha(d / "feature-tree.md")
    code, out = merge(d)
    assert code == 1 and "not CLEAR" in out
    assert sha(d / "feature-tree.md") == before


def test_an_id_already_in_the_tree_is_refused(tmp_path):
    code, out = merge(checked(tmp_path, "id-clash"))
    assert code == 1 and "already in the tree" in out


def test_a_second_merge_of_the_same_batch_is_refused(tmp_path):
    d = checked(tmp_path, "clear")
    assert merge(d)[0] == 0
    code, out = merge(d)
    assert code == 1 and "already in the tree" in out


def test_rows_edited_after_the_check_are_refused(tmp_path):
    """A CLEAR for other bytes is not a CLEAR for these."""
    d = checked(tmp_path, "clear")
    stg = d / f"_collect-{B}-staging.md"
    stg.write_text(stg.read_text().replace("one place.", "one place!", 1))
    code, out = merge(d)
    assert code == 1 and "different staging bytes" in out


def _edit_verdict(d, gate, **changes):
    vf = d / "_qa" / f"{B}.{gate}.json"
    v = json.loads(vf.read_text())
    v.update(changes)
    vf.write_text(json.dumps(v))


def test_a_clear_report_over_a_failing_gate_verdict_is_refused(tmp_path):
    """Found by mutation: the report is a summary; the verdicts are the evidence."""
    d = checked(tmp_path, "clear")
    _edit_verdict(d, "g3_grounding", verdict="FAIL")
    code, out = merge(d)
    assert code == 1 and "g3_grounding is FAIL" in out


def test_a_verdict_from_other_gate_code_is_refused(tmp_path):
    d = checked(tmp_path, "clear")
    _edit_verdict(d, "g1_capture", manifest_sha256="0" * 64)
    code, out = merge(d)
    assert code == 1 and "came from gate code" in out


def test_a_tree_whose_proof_already_disagrees_is_refused(tmp_path):
    d = checked(tmp_path, "clear")
    tree = d / "feature-tree.md"
    tree.write_text(tree.read_text().replace("rows=1 ·", "rows=7 ·", 1))
    code, out = merge(d)
    assert code == 1 and "already disagrees" in out


def test_a_subject_without_a_tree_is_refused(tmp_path):
    d = checked(tmp_path, "clear")
    (d / "feature-tree.md").unlink()
    code, out = merge(d)
    assert code == 1 and "no feature-tree.md" in out


# ── undo, from the log (PIPELINE-SPEC §1 step 5) ────────────────────────────

def test_undo_gives_back_the_pre_merge_bytes(tmp_path):
    d = checked(tmp_path, "clear")
    tree = d / "feature-tree.md"
    before = sha(tree)
    assert merge(d)[0] == 0

    code, out = merge(d, "--undo", "--dry-run")
    assert code == 0 and "DRY RUN" in out and sha(tree) != before, out

    code, out = merge(d, "--undo")
    assert code == 0 and "UNDONE" in out, out
    assert sha(tree) == before
    merged, undone = log(d)
    assert undone["action"] == "undo" and undone["tree_sha256_after"] == before
    assert undone["undoes"] == merged["ts"]

    v, _ = g6_integrity.run(["--root", str(d)])
    assert "clear_not_merged" in {f.code for f in v.findings}, "the batch is CLEAR and unmerged again"


def test_undo_restores_a_tree_that_did_not_end_in_a_newline(tmp_path):
    """The merge adds a newline before its block only then; the undo must take it back."""
    d = checked(tmp_path, "clear")
    tree = d / "feature-tree.md"
    tree.write_bytes(tree.read_bytes().rstrip(b"\n"))
    before = sha(tree)
    assert merge(d)[0] == 0
    code, out = merge(d, "--undo")
    assert code == 0, out
    assert sha(tree) == before


def test_an_undone_merge_cannot_be_undone_twice(tmp_path):
    d = checked(tmp_path, "clear")
    assert merge(d)[0] == 0 and merge(d, "--undo")[0] == 0
    code, out = merge(d, "--undo")
    assert code == 1 and "already undone" in out


def test_undo_refuses_when_the_tree_changed_after_the_merge(tmp_path):
    """Only the latest change to a tree can be undone: undo is never a guess."""
    d = second_batch(checked(tmp_path, "clear"))
    assert merge(d)[0] == 0
    assert merge(d, batch="docs-2026-02-01")[0] == 0
    before = sha(d / "feature-tree.md")
    code, out = merge(d, "--undo")
    assert code == 1 and "changed since" in out
    assert sha(d / "feature-tree.md") == before


def test_undo_refuses_a_batch_that_was_never_merged(tmp_path):
    code, out = merge(checked(tmp_path, "clear"), "--undo")
    assert code == 1 and "no merge" in out


# ── durability ──────────────────────────────────────────────────────────────

def test_the_tree_is_fsynced_before_and_after_it_is_renamed_into_place(tmp_path, monkeypatch, capsys):
    """Write, fsync, rename, fsync the folder: a crash leaves the old tree or the new one."""
    d = checked(tmp_path, "clear")
    spec = importlib.util.spec_from_file_location("kbqa_merge_script", MERGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    synced = []
    real = os.fsync
    monkeypatch.setattr(mod.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    assert mod.main(["--vendor-dir", str(d), "--batch", B]) == 0
    assert len(synced) >= 3, "the temp file, the folder after the rename, and the log line"
