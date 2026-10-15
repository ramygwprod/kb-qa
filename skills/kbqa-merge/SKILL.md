---
name: kbqa-merge
description: Merge one CLEAR staging batch into its subject's feature tree — refuses anything not CLEAR on its current bytes, takes a pre-merge hash, appends the rows unchanged, recomputes the tree's proof line, then runs g6. Use only when the operator runs /kbqa-merge on a batch /kbqa-check reported CLEAR. Never edits a row, never renumbers an id, never merges on its own initiative.
allowed-tools: Bash, Read
disable-model-invocation: true
---

# Merging a CLEAR batch

**Invoked as:** `/kbqa-merge <subject folder path> <batch>` — by the operator, only.

A merge is the one step that changes a feature tree, so it is a separate
command, run by a person, after a separate check said CLEAR (RamyGW 2026-10-04).
The collector lists batches as *ready for merge*; `/kbqa-check` reports CLEAR
batches `g6` sees as not merged. Neither merges. You run the script below, read
what it prints, and report it. You do not merge by hand, and you do not edit
the tree.

## 0 · Pre-flight

```bash
bash "$HOME/.claude/skills/kbqa-check/scripts/preflight.sh" kbqa-check kbqa-merge
```

On STOP, stop and give the operator the printed command. The merge reads
verdicts, and a verdict is only worth the gate code that wrote it — and this
skill is only worth the tagged text, so its own install record is checked too.
Report the `python3:` line: the merge runs under that interpreter.

## 1 · Dry run, then merge

```bash
S="$HOME/.claude/skills/kbqa-merge/scripts/merge.py"
python3 "$S" --vendor-dir "<subject folder path>" --batch "<batch>" --dry-run
python3 "$S" --vendor-dir "<subject folder path>" --batch "<batch>"
```

Show the operator the dry run's output — rows before + rows added = rows after,
and the old and new proof line — before running the merge.

The script **refuses, writing nothing**, unless all of these hold:

| check | why |
|---|---|
| `_qa/<batch>.report.json` says CLEAR **for the staging file's current sha256** | a CLEAR for other bytes is not a CLEAR for these |
| G1, G2, G3 verdicts are PASS on that sha256, from the installed manifest | the report is a summary; the verdicts are the evidence |
| every staging row parses, and no id repeats | a merge cannot repair what the check did not read |
| no staging id is already in the tree | ids are never renumbered to make room |
| the tree's `proof:` line already agrees with its own rows | never stack a merge on a tree that is already inconsistent |

When it merges, it:

1. records the tree's sha256 **before** writing
2. appends the rows **unchanged** — same objects, same key order, same order — as a
   new fenced block at the end of the tree, headed with the batch name and the
   staging sha256. Nothing above the block moves
3. recomputes the `proof:` line from a parse of the merged file (same shape as
   every existing tree)
4. proves, before writing, that the merged file parses to exactly the old rows
   plus the batch rows, **and** that removing the block and restoring the old proof
   line gives back the pre-merge bytes — so the merge can be undone from the log alone
5. writes atomically and durably (temp file, fsync, rename, fsync the folder),
   appends one line to `<subject>/_merge-log.jsonl` (both hashes, both proof
   lines, row count, first and last id)
6. runs `g6` on the subject and prints what it says about this tree and batch.
   Findings about *other* batches — another CLEAR batch not merged yet — are
   counted, not treated as this merge's failure

Exit 0 = merged. Exit 1 = refused (or `g6` objected to this tree or batch after
the merge — report it as a stop for a human).

## 1b · Undo — only when the operator asks

```bash
python3 "$S" --vendor-dir "<subject folder path>" --batch "<batch>" --undo --dry-run
python3 "$S" --vendor-dir "<subject folder path>" --batch "<batch>" --undo
```

Undo works from the log alone. It refuses, writing nothing, unless the batch's
latest log entry is a merge (not already undone), the tree is still exactly
what that merge left — so only a tree's latest merge can be undone, later ones
first — and removing the merged block and restoring the logged proof line gives
back the logged pre-merge sha256. The rows stay in the staging file; nothing is
lost. A merge that created the tree (`--new-tree`) is never undone by the
script: removing `feature-tree.md` is the operator's call.

A subject with no `feature-tree.md` is refused. `--new-tree` starts one, with
only derived frontmatter; use it only when the operator says so for that
subject.

## 2 · Report

- MERGED or REFUSED, and the reason line verbatim
- pre-merge and post-merge tree sha256
- rows before, added, after; old and new proof line
- `g6` after the merge: anything on this tree or batch (should be nothing), and
  the count of unrelated findings in the subject

## 3 · Never

- Merge a batch that is not CLEAR on its current bytes, or "fix" one so it is
- Edit, re-sort, re-key or drop a row; renumber an id
- Edit the tree by hand, before or after — including the proof line
- Merge without a dry run shown to the operator
- Retry a refused merge or undo by changing anything; report the refusal
- Undo a merge on your own initiative, or "fix" a tree by hand instead of undoing
- Merge on your own initiative, or because a list said "ready for merge"
- Delete or rewrite `_merge-log.jsonl`
