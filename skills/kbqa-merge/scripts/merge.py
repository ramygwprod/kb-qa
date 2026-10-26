#!/usr/bin/env python3
"""/kbqa-merge — append a CLEAR staging batch to its subject's feature tree.

    merge.py --vendor-dir <subject dir> --batch <name> [--dry-run] [--new-tree]

Run by the operator, after /kbqa-check reported the batch CLEAR. Nothing else
merges. This script:

  1. refuses unless the batch is CLEAR on the bytes the staging file holds NOW:
     `_qa/<batch>.report.json` says CLEAR for this staging sha256, and the
     G1/G2/G3 verdicts are PASS on that sha256 from the installed gate code
  2. refuses if any staging row is unreadable, repeats an id, or carries an id
     the tree already has — ids are never renumbered to make room
  3. takes the tree's sha256 BEFORE anything is written
  4. appends the rows unchanged — same objects, same key order, same order —
     as a new ```json block at the end of the tree; nothing above it moves
  5. rewrites the tree's `proof:` line from a parse of the merged file
  6. proves, before writing, that the merged file parses to exactly old rows +
     batch rows, and that removing the block and restoring the old proof line
     gives back the pre-merge bytes (same sha256) — so the merge is reversible
     from the log alone, without a backup copy
  7. writes atomically and durably — temp file, fsync, rename, fsync the
     folder — and appends one fsynced line to `<subject>/_merge-log.jsonl`
  8. runs G6 on the subject and reports what it says about this tree and batch

    merge.py --vendor-dir <subject dir> --batch <name> --undo [--dry-run]

undoes the batch's merge from the log alone (PIPELINE-SPEC §1 step 5): only
when that merge is the tree's latest change (its sha256 is still the logged
"after"), by removing the merged block and restoring the logged proof line,
and only if the result has exactly the logged "before" sha256. The rows stay
in the staging file; nothing is lost.

It never edits a row, a capture, a denominator, a verdict or the staging file.
    merge.py --vendor-dir <subject dir> --all-clear [--dry-run] [--new-tree]

merges every batch of the subject that is CLEAR on its current staging bytes
and has no row in the tree yet — selected by the ledger's own code (`kbqa
status`) — one at a time, each through the single-batch path above (its own
checks, pre-merge hash, log line and proof line). Order: by batch name, except
that a batch whose rows name, in `same_feature_as`, an anchor only another
selected batch holds merges after that batch; batches that wait on each other
are refused before anything merges. It stops at the first refusal: the
batches already merged stay merged (each is undone on its own, the latest
first), and it prints them, the refused batch with its reason word for word,
and the batches not attempted. G6 runs once, after the last merge. With
`--dry-run` each batch's checks run on the tree as the merges before it would
leave it, and nothing is written. Every other batch is listed with why it is
left out. `--all-clear` with `--batch` or `--undo` is refused.

Exit 0 = merged / undone (or dry run clean, or nothing to merge) · 1 = refused
(with --all-clear: the batches merged before the refusal stay merged).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from kbqa import __version__ as KBQA_VERSION
    from kbqa.manifest import MANIFEST_SHA256
    from kbqa.parsing import parse_staging
    from kbqa.gates import g6_integrity
    from kbqa import ledger
except ImportError as exc:  # pragma: no cover
    print(f"REFUSED: kbqa is not importable ({exc}). Run the pre-flight first.")
    sys.exit(1)

PROOF_LINE_RE = re.compile(
    r'^(?P<head>proof:\s*")(?P<body>.*?)(?P<tail> \(derived by parsing this file — never typed\)")[ \t]*$',
    re.M,
)
BATCH_GATES = ("g1_capture", "g2_conformance", "g3_grounding")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def proof_body(objs) -> str:
    """The estate's proof shape, recomputed. Reproduces all 63 existing proof
    lines byte-for-byte (checked 2026-10-05) — so it adds no key and drops none."""
    g = lambda *v: sum(1 for o in objs if o.get("evidence_grade") in v)  # noqa: E731
    novel = sum(1 for o in objs if o.get("canonical", "NOVEL") == "NOVEL")
    return ("rows=%d · unique_ids=%d · canonical NOVEL=%d · mapped=%d · official-doc=%d · "
            "marketing=%d · verify=%d · broken_source=%d" % (
                len(objs), len({o.get("id") for o in objs}), novel, len(objs) - novel,
                g("official-doc"), g("marketing"), g("verify", "[verify]"),
                sum(1 for o in objs if o.get("broken_source") is True)))


def rows_of_text(text: str):
    """Parse text with the gates' own parser, via a system temp file — never
    a file inside the subject folder."""
    fd, name = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        return parse_staging(Path(name))
    finally:
        os.unlink(name)


def refuse(msg: str) -> int:
    print(f"REFUSED: {msg}\nNothing was written.")
    return 1


def write_durably(target: Path, text: str, expect_sha) -> bool:
    """Replace `target` so a crash leaves either the old file or the new one.

    Temp file in the same folder, fsync it, re-check the target is still the
    bytes we read (None: still absent), rename over it, fsync the folder so the
    rename itself is on disk. Returns False, writing nothing, if the target
    changed meanwhile.
    """
    tmp = target.parent / f".kbqa-merge-{os.getpid()}.tmp.md"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    now = sha256_bytes(target.read_bytes()) if target.exists() else None
    if now != expect_sha:
        tmp.unlink()
        return False
    os.replace(tmp, target)
    dfd = os.open(str(target.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return True


def append_log(d: Path, entry: dict) -> None:
    with open(d / "_merge-log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def g6_on(d: Path, tree: Path, *stagings: Path):
    """G6's findings about THIS tree or THESE batches, and the count of the rest.

    Matched by where each finding points. A `clear_not_merged` for another
    batch of the subject is that batch's business, not this merge's.
    """
    v, _ = g6_integrity.run(["--root", str(d)])
    mine = [f for f in v.findings if f.where and (str(tree) in f.where
                                                   or any(s.name in f.where for s in stagings))]
    return mine, len(v.findings) - len(mine)


def undo(d: Path, b: str, dry_run: bool) -> int:
    staging = d / f"_collect-{b}-staging.md"
    tree = d / "feature-tree.md"
    entries = []
    logf = d / "_merge-log.jsonl"
    if logf.exists():
        entries = [json.loads(line) for line in logf.read_text(encoding="utf-8").splitlines() if line.strip()]
    mine = [e for e in entries if e.get("batch") == b]
    if not mine:
        return refuse(f"the log has no merge of {b} — nothing to undo")
    last = mine[-1]
    if last.get("action") == "undo":
        return refuse(f"the latest merge of {b} was already undone ({last.get('ts')})")
    if last.get("tree_sha256_before") is None:
        return refuse("this merge created the tree (--new-tree). Undoing it means removing "
                      "feature-tree.md, which this script never does — the operator decides")
    if not tree.exists():
        return refuse("there is no feature-tree.md to undo the merge on")
    now_sha = sha256_bytes(tree.read_bytes())
    if now_sha != last["tree_sha256_after"]:
        return refuse(f"the tree has changed since this merge (now {now_sha[:12]}…, the merge left "
                      f"{last['tree_sha256_after'][:12]}…). Only a tree's latest change can be undone: "
                      "undo later merges first, or a human looks")
    text = tree.read_text(encoding="utf-8")
    marker = f"\n<!-- merged by /kbqa-merge: batch {b} · staging sha256 {last['staging_sha256']} ·"
    if text.count(marker) != 1:
        return refuse("the merged block for this batch is not in the tree exactly once")
    cut = text.index(marker)
    removed = text[cut:]
    block_ids = [str(r.obj.get("id")) for r in rows_of_text(removed).rows if r.obj]
    if (len(block_ids) != last["rows_appended"] or block_ids[:1] != [last["first_id"]]
            or block_ids[-1:] != [last["last_id"]]):
        return refuse("the block in the tree is not the rows the log says were merged")
    head = text[:cut]
    m = PROOF_LINE_RE.search(head)
    if not m or m.group("body") != last["proof_after"]:
        return refuse("the tree's proof line is not the one this merge wrote")
    head = head[:m.start("body")] + last["proof_before"] + head[m.end("body"):]
    # The merge added "\n" before its block only when the tree did not end in one.
    for candidate in (head, head[:-1] if head.endswith("\n") else None):
        if candidate is not None and sha256_bytes(candidate.encode("utf-8")) == last["tree_sha256_before"]:
            restored = candidate
            break
    else:
        return refuse("removing the block does not give back the logged pre-merge bytes")
    print(f"  undo {b}: {len(block_ids)} rows out · tree back to {last['tree_sha256_before']}")
    print(f"  proof: {last['proof_after']}\n      -> {last['proof_before']}")
    if dry_run:
        print("DRY RUN — the undo would restore the pre-merge tree. Nothing was written.")
        return 0
    if not write_durably(tree, restored, now_sha):
        return refuse("the tree changed while undoing")
    append_log(d, {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": "undo", "batch": b, "undoes": last["ts"],
        "staging_sha256": last["staging_sha256"], "rows_removed": len(block_ids),
        "tree_sha256_before": now_sha, "tree_sha256_after": last["tree_sha256_before"],
        "proof_before": last["proof_after"], "proof_after": last["proof_before"],
        "kbqa": KBQA_VERSION, "manifest": MANIFEST_SHA256,
    })
    print(f"UNDONE — tree sha256 {last['tree_sha256_before']}; logged to {d.name}/_merge-log.jsonl")
    found, others = g6_on(d, tree, staging)
    print("G6 after undo: " + ", ".join(sorted({f.code for f in found})) if found
          else "G6 after undo: nothing on this tree or batch")
    return 0


@dataclass
class Result:
    """One batch through the single-batch path: its exit code, the refusal
    word for word (None when it merged, or its dry run was clean), whether the
    tree was written, and the merged text (what a dry run would write)."""
    code: int
    reason: Optional[str] = None
    merged: bool = False
    text: Optional[str] = None


def refused(msg: str) -> Result:
    refuse(msg)
    return Result(1, reason=msg)


def merge_batch(d: Path, b: str, dry_run: bool, new_tree: bool,
                tree_text: Optional[str] = None, run_g6: bool = True) -> Result:
    """Steps 1–8 for one batch — the only path that merges.

    `tree_text`, in a dry run only, is the tree as the merges planned before
    this one would leave it (`--all-clear --dry-run`); every check runs on it
    as on the file. `run_g6=False` leaves G6 to the caller (`--all-clear` runs
    it once, at the end)."""
    if tree_text is not None and not dry_run:
        return refused("internal: a supplied tree is for a dry run only")
    staging = d / f"_collect-{b}-staging.md"
    tree = d / "feature-tree.md"
    qa = d / "_qa"

    # 1 · CLEAR, on these bytes, from this code ---------------------------------
    if not staging.exists():
        return refused(f"no staging file {staging.name}")
    st_bytes = staging.read_bytes()
    st_sha = sha256_bytes(st_bytes)
    rpt = qa / f"{b}.report.json"
    if not rpt.exists():
        return refused(f"no {rpt} — run /kbqa-check on this subject first")
    report = json.loads(rpt.read_text(encoding="utf-8"))
    if report.get("status") != "CLEAR":
        return refused(f"the report says {report.get('status')!r}, not CLEAR")
    if report.get("staging_sha256") != st_sha:
        return refused("the CLEAR report was for different staging bytes "
                       f"({str(report.get('staging_sha256'))[:12]}… vs now {st_sha[:12]}…) — "
                       "re-run /kbqa-check")
    for gate in BATCH_GATES:
        vf = qa / f"{b}.{gate}.json"
        if not vf.exists():
            return refused(f"no {gate} verdict")
        v = json.loads(vf.read_text(encoding="utf-8"))
        vsha = (v.get("inputs", {}).get("staging") or {}).get("sha256")
        if v.get("verdict") != "PASS" or vsha != st_sha:
            return refused(f"{gate} is {v.get('verdict')} on staging {str(vsha)[:12]}…, "
                           f"not PASS on {st_sha[:12]}…")
        if v.get("manifest_sha256") != MANIFEST_SHA256:
            return refused(f"{gate} verdict came from gate code {v.get('manifest_sha256')}, "
                           f"installed is {MANIFEST_SHA256} — re-run /kbqa-check")
    print(f"  CLEAR on staging sha256 {st_sha}")

    # 2 · rows, readable and new ------------------------------------------------
    sp = parse_staging(staging)
    bad = [r for r in sp.rows if r.obj is None or not r.obj.get("id")]
    if bad or not sp.rows:
        return refused(f"{len(bad)} unreadable row(s), {len(sp.rows)} parsed")
    new_objs = [r.obj for r in sp.rows]
    new_ids = [str(o["id"]) for o in new_objs]
    if len(set(new_ids)) != len(new_ids):
        return refused("the batch repeats an id")

    # 3 · the tree, before ------------------------------------------------------
    if tree_text is not None:
        old_text = tree_text
        old_bytes = tree_text.encode("utf-8")
        print("  the tree as the merges planned before this one would leave it:")
    elif tree.exists():
        old_bytes = tree.read_bytes()
        old_text = old_bytes.decode("utf-8")
    elif new_tree:
        old_bytes = b""
        old_text = (f"---\nentity:       {d.name}\n"
                    f"schema:       kbqa vendor-catalogue profile v{KBQA_VERSION}\n"
                    f'proof:        "{proof_body([])} (derived by parsing this file — never typed)"\n'
                    f"---\n\n# {d.name} — Feature Tree (Layer 1)\n")
    else:
        return refused("the subject has no feature-tree.md; pass --new-tree only if the operator chose to start one")
    pre_sha = sha256_bytes(old_bytes) if old_bytes else None
    print(f"  pre-merge tree sha256 {pre_sha or '(new tree)'}")

    m = PROOF_LINE_RE.search(old_text)
    if not m or len(PROOF_LINE_RE.findall(old_text)) != 1:
        return refused("the tree has no single `proof:` line in the estate's shape")
    old_objs = [r.obj for r in rows_of_text(old_text).rows if r.obj is not None]
    if m.group("body") != proof_body(old_objs):
        return refused("the tree's proof line already disagrees with its own rows — a human looks first")
    clash = sorted(set(new_ids) & {str(o.get("id")) for o in old_objs})
    if clash:
        return refused(f"{len(clash)} id(s) already in the tree, e.g. {clash[:5]} — ids are never renumbered")
    # Another source of a feature points at that feature's anchor; the anchor
    # must be in the tree already, or in this batch, so the tree never holds a
    # row pointing at nothing. The anchor's batch merges first.
    anchors = {str(o.get("id")) for o in old_objs + new_objs if not o.get("same_feature_as")}
    dangling = sorted({str(o["same_feature_as"]) for o in new_objs
                       if o.get("same_feature_as") and str(o["same_feature_as"]) not in anchors})
    if dangling:
        return refused(f"{len(dangling)} same_feature_as target(s) are not an anchor in the tree or this batch, "
                       f"e.g. {dangling[:5]} — merge the batch holding the anchor first")

    # 4–5 · append unchanged, recompute proof -----------------------------------
    lines = []
    for o in new_objs:
        s = json.dumps(o, ensure_ascii=False)
        back = json.loads(s)
        if back != o or list(back) != list(o):
            return refused(f"row {o['id']!r} does not round-trip unchanged")
        lines.append(s)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = (f"\n<!-- merged by /kbqa-merge: batch {b} · staging sha256 {st_sha} · "
             f"{len(lines)} rows · {today} -->\n```json\n[\n" + ",\n".join(lines) + "\n]\n```\n")
    all_objs = old_objs + new_objs
    new_proof = proof_body(all_objs)
    sep = "" if old_text.endswith("\n") else "\n"
    new_text = (old_text[:m.start("body")] + new_proof + old_text[m.end("body"):]) + sep + block

    # 6 · prove it --------------------------------------------------------------
    parsed = [r.obj for r in rows_of_text(new_text).rows]
    if parsed != all_objs:
        return refused("the merged file does not parse to exactly old rows + batch rows")
    if not new_text.endswith(block):
        return refused("internal: block not at end")
    rebuilt = new_text[: len(new_text) - len(block) - len(sep)]
    rebuilt = rebuilt.replace(f'{m.group("head")}{new_proof}{m.group("tail")}',
                              f'{m.group("head")}{m.group("body")}{m.group("tail")}', 1)
    if old_bytes and sha256_bytes(rebuilt.encode("utf-8")) != pre_sha:
        return refused("removing the block does not give back the pre-merge bytes")
    post_sha = sha256_bytes(new_text.encode("utf-8"))
    print(f"  rows: tree {len(old_objs)} + batch {len(new_objs)} = {len(all_objs)}")
    print(f"  proof: {m.group('body')}\n      -> {new_proof}")

    if dry_run:
        print(f"DRY RUN — would write tree sha256 {post_sha}. Nothing was written.")
        return Result(0, text=new_text)

    # 7 · write --------------------------------------------------------------------
    if not write_durably(tree, new_text, pre_sha):
        return refused("the tree changed while merging")
    append_log(d, {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": "merge", "batch": b, "staging_sha256": st_sha, "rows_appended": len(new_objs),
        "first_id": new_ids[0], "last_id": new_ids[-1],
        "tree_sha256_before": pre_sha, "tree_sha256_after": post_sha,
        "proof_before": m.group("body"), "proof_after": new_proof,
        "kbqa": KBQA_VERSION, "manifest": MANIFEST_SHA256,
    })
    print(f"MERGED — tree sha256 {post_sha}; logged to {d.name}/_merge-log.jsonl")
    if not run_g6:
        return Result(0, merged=True, text=new_text)

    # 8 · G6 says -------------------------------------------------------------------
    mine, others = g6_on(d, tree, staging)
    if mine:
        print("G6 AFTER MERGE — FINDINGS ON THIS TREE OR BATCH:")
        for f in mine:
            print(f"  {f.code}: {f.message}")
        return Result(1, reason="G6 found something on this tree or batch after the merge",
                      merged=True, text=new_text)
    print(f"G6 after merge: nothing on this tree or batch"
          + (f"; {others} other finding(s) in the subject, unrelated to this merge — see /kbqa-check" if others else ""))
    return Result(0, merged=True, text=new_text)


# ── --all-clear: every CLEAR batch, one at a time, through merge_batch ─────────

class Cycle(Exception):
    pass


def all_clear_selection(d: Path) -> Tuple[List[str], List[Tuple[str, str]], Optional[set]]:
    """The batches to merge — CLEAR on their current staging bytes, no row in
    the tree yet — read by the ledger's own code (`kbqa status`), and every
    other batch of the subject with why it is left out."""
    ids = ledger.tree_ids(d)
    selected, left_out = [], []
    for b in ledger.batches_of(d):
        bl = ledger.batch_ledger(d, b, ids)
        check, merged = bl["check"], bl["merged"]
        if check["status"] != "CLEAR":
            why = f"check: {check['status']}"
            if check.get("why"):
                why += f" — {check['why']}"
            left_out.append((b, why))
        elif merged["state"] != ledger.NOT_MERGED:
            why = merged["state"]
            if merged["state"] == ledger.PARTLY:
                why += (f" ({merged['ids_in_tree']} of {merged['ids']} ids in the tree) — "
                        "a human compares before any merge; never renumber")
            elif merged.get("why"):
                why += f" — {merged['why']}"
            left_out.append((b, why))
        else:
            selected.append(b)
    return selected, left_out, ids


def merge_order(d: Path, selected: List[str], tree_ids: Optional[set]) -> Tuple[List[str], Dict[str, set]]:
    """Batch-name order, except that a batch whose rows name in
    `same_feature_as` an anchor only another selected batch holds merges after
    that batch. Raises Cycle, naming the batches that wait on each other."""
    rows = {b: ledger._staging_rows(d / f"_collect-{b}-staging.md")[0] or [] for b in selected}
    anchors = {b: {str(r.get("id")) for r in rows[b] if r.get("id") and not r.get("same_feature_as")}
               for b in selected}
    after: Dict[str, set] = {b: set() for b in selected}
    for b in selected:
        for r in rows[b]:
            target = r.get("same_feature_as")
            if not target or str(target) in (tree_ids or set()) or str(target) in anchors[b]:
                continue
            holders = [o for o in selected if o != b and str(target) in anchors[o]]
            if len(holders) == 1:
                after[b].add(holders[0])
    order: List[str] = []
    waiting = sorted(selected)
    while waiting:
        ready = [b for b in waiting if after[b] <= set(order)]
        if not ready:
            raise Cycle("; ".join(f"{b} waits on {', '.join(sorted(after[b] - set(order)))}" for b in waiting))
        order.append(ready[0])
        waiting.remove(ready[0])
    return order, after


def all_clear(d: Path, dry_run: bool, new_tree: bool) -> int:
    tree = d / "feature-tree.md"
    selected, left_out, ids = all_clear_selection(d)
    try:
        order, after = merge_order(d, selected, ids)
    except Cycle as exc:
        return refuse(f"the batches' same_feature_as anchors wait on each other — {exc}. "
                      "No order merges them; a human looks")
    for b, why in left_out:
        print(f"  left out: {b} — {why}")
    if not order:
        print(f"Nothing to merge: no batch of {d.name} is CLEAR on its current bytes with its rows "
              "not yet in the tree. Nothing was written.")
        return 0
    print(f"  plan: {len(order)} batch(es) CLEAR on their current bytes, not yet in the tree, in this order:")
    for k, b in enumerate(order, 1):
        print(f"    {k}. {b}" + (f" — after {', '.join(sorted(after[b]))}, which holds its anchors"
                                  if after[b] else ""))
    merged: List[str] = []
    text: Optional[str] = None
    for k, b in enumerate(order, 1):
        print(f"── {k} of {len(order)} · {b}")
        r = merge_batch(d, b, dry_run, new_tree, tree_text=text if dry_run else None, run_g6=False)
        if r.code != 0:
            done = ", ".join(merged) if merged else "none"
            if dry_run:
                print(f"DRY RUN — the run would stop at this refusal. Nothing was written."
                      f"\n  would merge first: {done}")
            else:
                print(f"STOPPED at the first refusal.\n  merged: {done}"
                      + (" — they stay merged; each is undone on its own, the latest first" if merged else ""))
            print(f"  refused: {b} — {r.reason}"
                  f"\n  not attempted: {', '.join(order[k:]) if order[k:] else 'none'}")
            if merged and not dry_run:
                all_clear_g6(d, tree, merged)
            return 1
        merged.append(b)
        text = r.text
    if dry_run:
        print(f"DRY RUN — all {len(order)} batch(es) would merge, in the order above. Nothing was written.")
        return 0
    print(f"ALL MERGED — {len(merged)} batch(es): {', '.join(merged)}")
    return all_clear_g6(d, tree, merged)


def all_clear_g6(d: Path, tree: Path, merged: List[str]) -> int:
    """G6 once, after the last merge: anything on the tree or a batch merged
    by this run is a stop for a human."""
    mine, others = g6_on(d, tree, *[d / f"_collect-{b}-staging.md" for b in merged])
    if mine:
        print("G6 AFTER MERGE — FINDINGS ON THIS TREE OR THE BATCHES MERGED:")
        for f in mine:
            print(f"  {f.code}: {f.message}")
        return 1
    print(f"G6 after merge: nothing on this tree or the batches merged"
          + (f"; {others} other finding(s) in the subject, unrelated to these merges — see /kbqa-check"
             if others else ""))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa-merge")
    ap.add_argument("--vendor-dir", required=True)
    ap.add_argument("--batch")
    ap.add_argument("--all-clear", action="store_true",
                    help="merge every batch CLEAR on its current bytes and not yet in the tree, "
                         "one at a time, anchors' batches first; stops at the first refusal")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--new-tree", action="store_true",
                    help="create feature-tree.md when the subject has none (operator's explicit choice)")
    ap.add_argument("--undo", action="store_true",
                    help="undo this batch's merge from the log — only if it is the tree's latest change")
    args = ap.parse_args(argv)
    if not args.all_clear and not args.batch:
        ap.error("give --batch <name>, or --all-clear")

    d = Path(args.vendor_dir).resolve()
    b = args.batch
    print(f"kbqa-merge · {d.name} / {'--all-clear' if args.all_clear else b} · kbqa {KBQA_VERSION} · "
          f"manifest {MANIFEST_SHA256[:16]}…")
    if args.all_clear:
        if args.batch:
            return refuse("--all-clear merges every CLEAR batch; --batch merges one — give one of them, not both")
        if args.undo:
            return refuse("--undo undoes one batch: give --batch <name>, the latest merge first")
        return all_clear(d, args.dry_run, args.new_tree)
    if args.undo:
        return undo(d, b, args.dry_run)
    return merge_batch(d, b, args.dry_run, args.new_tree).code


if __name__ == "__main__":
    sys.exit(main())
