---
name: kbqa-check
description: Run the kbqa validation gates over a collected batch or a whole estate, read the verdict, and route failures. Use when a capture and staging file exist and need checking, when a gate has failed and the next step is unclear, when a mapping file needs checking, or when asked whether a batch is grounded. Read-only with respect to the validator — it never modifies kbqa, never installs it, never merges, and never edits rows to make a gate pass.
allowed-tools: Bash, Read
---

# Checking a subject with kbqa

**Invoked as:** `/kbqa-check <subject folder path>` — one subject.
**Or:** `/kbqa-check estate` — the whole estate (§3).

You are the **checker**. Run the gates over every batch in that folder, read
what they say, and tell the operator what happens next. You do not repair data,
you do not touch the tool, and you do not merge — merge is the operator's
`/kbqa-merge`.

## 0 · Pre-flight — PASS or STOP, before any gate

```bash
bash "$HOME/.claude/skills/kbqa-check/scripts/preflight.sh"
```

It prints **PASS** or **STOP** and never installs anything. Its first line names
the `python3` it used — the interpreter every gate below runs under. It checks,
in order:

1. the installed kbqa is the version this copy pins (`v6.15.0`)
2. its manifest is the one this copy expects
3. the installed skill is the tagged skill: every file matches
   `INSTALLED-FROM-kbqa-check`, the record `skills/install.sh` wrote — none changed,
   added or removed
4. every copy of this skill a session can load is byte-identical to the
   canonical copy, `~/.claude/skills/kbqa-check/SKILL.md`

Report the `python3:` and `kbqa:` lines with the result. If they name an
interpreter the operator did not expect, say so before running any gate.

**On STOP, stop.** Give the operator the exact command it printed. `pip` is denied
in this project's settings on purpose; the operator installs the pinned tag in
their own terminal, then you run the pre-flight again. A verdict from unknown
gate code is not a verdict.

A `NOTE: vX exists` line is not a stop. Proceed, and report that you checked
against the pinned version, not the newest. Never ask anyone to install the
newest release instead of the pinned one: this copy cannot vouch for its manifest.

The authoritative gate code is the pinned tag on GitHub. A tampered local
package has a lifetime of one reinstall — **do not protect a derived artifact,
re-derive it.**

## 1 · The boundary

| | |
|---|---|
| **You may read** | captures, staging files, denominators, stop-conditions, mapping files, `_qa/` verdicts and reports |
| **You may write** | nothing directly. `kbqa` writes `<subject>/_qa/`, `<subject>/_qa-log.jsonl`, and the estate audit files |
| **You may never touch** | anything under the kbqa install path — `gates/`, `models.py`, `profiles/`, `conventions.py`, `report.py`, tests, fixtures — or a feature tree |

A gate is satisfied by the data, never by changing what the gate says. If you
believe a gate is wrong, say so and cite the module and its SHA from the
finding — that is a legitimate dispute. Editing it is not.

## 2 · Check the subject

```bash
bash "$HOME/.claude/skills/kbqa-check/scripts/check_subject.sh" "<subject folder path>" .
```

Run it from the project root. It runs, in order:

| step | command | level |
|---|---|---|
| surfaces | `kbqa surfaces` — `product`, `docs`, `help`: each has `_denominator-<surface>-<date>.md` or a stop-condition `<url> \| surface <slug> not published: …` | subject |
| every batch | `kbqa report` — G1 capture, G2 conformance (incl. K1 rules on new batches), G3 grounding; round number; operator sample | batch |
| mappings | `kbqa mapcheck` — when `_map-<batch>-A/B.jsonl` exist | batch |
| coverage | `kbqa g4 --denominator <surface denominator> --rows <every batch of that surface>` | surface |
| windows | `kbqa g4 --rows <every batch of that surface>` — did the chain reach `exhausted`? | surface |
| legacy | batches whose name has no surface: coverage against the legacy denominator | subject |

**Coverage is measured per surface, never per batch.** A batch that holds
window 2 of 5 cites a fifth of the index by design; judged alone against the
whole denominator it could never be CLEAR. So each batch report says G4 did
not run there, and the coverage line for its surface is where coverage is read.

**Read each report's Coverage section first.** It names every gate that did not
run, and a `scanned` count for every gate that did. A gate that did not run has
found nothing, which is not the same as having found nothing wrong.

**Scanned 0 is NOT CHECKED, never clean.** A batch whose capture or rows are
empty reports status `NOT CHECKED`. If the script prints `ZERO batches found`,
say that zero batches were checked; never report the subject clean.

`collection_parked` on a surface's windows means the collector stopped safely
with more to collect — the surface is unfinished, not failed.
`no_exhaustion_evidence` means nothing establishes that the list ever ended.

**K1 rules apply to new batches only** — batches named
`<surface>-<YYYY-MM-DD>[-wNN]`. The report says `applied` or
`not applied (legacy batch name)`. A legacy batch is never edited to meet them;
its gaps go on the re-collection list (§3).

To check one thing in isolation, without writing anything:

```bash
python3 -m kbqa g1 --staging <f> --capture <f>     # capture integrity
python3 -m kbqa g2 --staging <f>                   # conformance (+ K1 on new batches)
python3 -m kbqa g3 --staging <f> --capture <f>     # grounding
python3 -m kbqa surfaces --subject <dir>           # mandatory surfaces
```

Bare gate runs are side-effect-free. Exit 0 = PASS, 1 = FAIL. **Exit 2 means
DECLINED and appears only from `g0`** — a usage error exits 1, never 2.

## 3 · Check the estate

```bash
python3 -m kbqa g6 --root .
python3 -m kbqa sweep --root . --exclude '_Archive/*' --exclude '_Delete/*' --exclude '*/_to_delete/*' \
  --recollect _recollect-list.jsonl
```

`g6`: verdicts, manifests and merged trees agree, and **no batch is CLEAR but
missing from its tree** (`clear_not_merged`, `clear_partially_merged`). Report
every such batch to the operator as ready for `/kbqa-merge`.
Report a partially merged batch as a stop for a human, never as a merge to retry.

`sweep` sorts every batch into `verifiable`, `unassessable-no-page-markers`
(recoverable by re-fetch) or `unverifiable-no-capture` (not recoverable). With
`--recollect` it writes **the re-collection list** `_recollect-list.jsonl` (+ `.md`
summary) for the planner: those tiers, batches whose rows the parser cannot
read, merged trees with no batch, and **merged rows with an empty
`parent_path`, by id**. Rows on that list are re-collected, never edited.

The excludes are not optional: `_Archive/` and `_Delete/` are never current,
and a tree there would be listed as if it were. Excluded files are named in the
audit, never silently dropped.

## 3b · Guards for the mapping round

Two commands that are not gates. They answer a question no gate asks: **did
interpreting the data change it?**

Before a mapping pass, and again after:

```bash
python3 -m kbqa freeze --root <estate> --out _qa/verbatim.freeze.json
# … the mapping pass happens …
python3 -m kbqa freeze --root <estate> --check _qa/verbatim.freeze.json
```

`freeze` fingerprints the fields that are the **subject's own words** — for a
product catalogue, `id`, `source_url`, `source_quote`, `access_date`,
`vendor_term`, `parent_path`. A changed or disappeared row fails. A new row is
reported and does not, because collection legitimately adds rows.

**A drifted row is restored from the snapshot's own frozen values, never
re-frozen.** The drift report prints what each field held; put it back.
If you are asked to re-freeze after a drift report, say no and explain why.

`mapcheck` (run by §2 when mapping files exist) checks the files the mappers
wrote, `_map-<batch>-<A|B>.jsonl`:

- every staging id exactly once, `id` first, exactly the mapper's fields, none null
- theme codes exist in the codebook; APQC ids exist in the v8.0 list **and** carry
  that list's hierarchy id and name
- `role_source` filled; `needs-human` rows listed and never counted as mapped
- A/B agreement on **ALL** rows — a missing or needs-human row is a disagreement
- `element_dominates`: one element on more than 30 % of the batch

It checks form and existence, never whether a mapping is right. Agreement is
consistency, not correctness.

## 4 · Routing a failure — one fix round, then park

Every finding in the report carries a class. Route by it, and say which:

| class | goes to | meaning |
|---|---|---|
| **structural** | re-fetch / re-collect | no edit to the rows can make this true |
| **planner** | the planner | scope, surfaces, fetch-list work |
| **fixable** | the row-writer, **once** | the rows disagree with their own evidence |

**One round (RamyGW 2026-10-04).** The report prints the round, derived from the
staging hashes in `<subject>/_qa-log.jsonl`:

| report says | what happens |
|---|---|
| round 1, BLOCKED | `fixable` findings go to the row-writer — the specific findings, not the gate name |
| round 2, CLEAR | done; the batch is ready for mapping, then merge |
| round 2+, **PARKED** | stop. The batch and its finding list go to the operator. Nothing goes back to the row-writer without the operator |

Re-running on unchanged bytes is the same round. **Never hand a failure back as
"try again"** — that retry loop is where gaming begins. `structural` and
`planner` findings go to planning; only `fixable` findings ever reach a row-writer.

Mapping findings go to the operator. `element_dominates` is cleared only by a
human reading the sampled rows, never by editing the mapping file.

A finding is resolved when it stops appearing on a re-run — not when it has been
explained.

## 4b · What to tell the operator

They are the loop between maker and checker, so give them what they need to act
without opening a file:

- pre-flight: PASS line (version, manifest)
- **surfaces**: per surface — denominator, stop-condition, or MISSING
- per batch: **CLEAR / BLOCKED / PARKED / NOT CHECKED**, the round, and the finding count by class
- the **structural** and **planner** findings, which go back to planning
- the **fixable** findings — the only ones a row-writer may receive, in round 1 only
- **PARKED** batches with their finding lists
- per surface: coverage, and whether its windows reached the end or are parked at an offset
- mappings: per mapper rows / mapped / needs-human (with ids), agreement rates on all rows, `element_dominates`
- **the operator sample**: each report's "Operator sample" section — quote, claim and mapping for a fixed-seed sample of rows, with the seed. Show it; the gates cannot see whether a quote supports its claim
- **ready for merge**: CLEAR batches that `g6` reports as not merged
- **every gate that did not run or scanned 0, and why** — state this even when everything else is clean

## 5 · Never

- Edit a gate, `models.py`, a profile, or a convention so a batch passes
- Install, upgrade or reinstall kbqa yourself — the operator does, from the pinned tag
- Switch `--profile` to one that accepts what the current profile rejects
- Lower or delete a denominator entry to close a G4 gap
- Clear `fetched_by_this_agent` to silence `role_collapse`
- Edit a capture, a robots artifact, or a denominator — Bronze is immutable,
  not even for a typo. A vendor typo is evidence; correcting it breaks the
  match correctly
- Rewrite a `source_quote` to match the page. If the quote is not on the page,
  the row is wrong — drop it or re-source it
- Edit a legacy row to meet a K1 rule — it goes on the re-collection list
- Send a batch to a second fix round without the operator
- Merge, or edit a feature tree — that is `/kbqa-merge`, run by the operator
- Regenerate or hand-edit a test fixture
- Report only the gates that passed, or report NOT CHECKED as clean
- Re-freeze after a drift report, or advise anyone else to
- Treat a `canonical` value in a row as a mapping. Mappings live in their own
  file; a value written into a row is an edit to the row

## 6 · What the gates cannot see

Say this when reporting a clean run, so it is not read as more than it is:

- **G3 checks a quote is real and on the cited page. It does not check that the
  quote supports the claim.** The operator sample exists for this; it is a
  sample, not a check.
- **G4 measures coverage against the denominator we captured.** A selective
  index goes unnoticed.
- **`mapcheck` checks that codes exist, not that they are right.** Two mappers
  agreeing proves consistency only.
- **Nothing checks `unknown` avoidance.** No gate asks whether a confident value
  was supported by anything on the page.

These are human judgement. The gates make invention detectable; they do not make
review unnecessary.

## 7 · This file is a rule, not a wall

An instruction can be forgotten under pressure. Make the boundary a fact about
the environment instead — see `settings-snippet.json` next to this file, which
denies writes to the validator and blocks `pip install`. Only CI running the
gates from a pinned tag, on a machine this agent cannot reach, is tamper-**proof**.

Full reference: [MANUAL.md](https://github.com/ramygwprod/kb-qa/blob/main/docs/MANUAL.md)
— §6 every action, §7 every finding, §10 troubleshooting, §11 the boundary.
