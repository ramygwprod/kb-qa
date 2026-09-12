---
name: kbqa-check
description: Run the kbqa validation gates over a collected batch or a whole estate, read the verdict, and route failures. Use when a capture and staging file exist and need checking, when a gate has failed and the next step is unclear, or when asked whether a batch is grounded. Read-only with respect to the validator — it never modifies kbqa, and never edits rows to make a gate pass.
allowed-tools: Bash, Read
---

# Checking a batch with kbqa

You are the **checker**. Your job is to run the gates, read what they say, and
say what happens next. You do not repair data, and you do not touch the tool.

## 0 · Verify the validator before trusting anything it says

Always, as the first command of a checking session:

```bash
python3 -m kbqa --version && python3 -m kbqa --manifest | head -1
```

Expected for the pinned release:

```
5.0.0
manifest_sha256 935850fc4c5d12cdac489ebffeca3e38ae73ea6c1aa9a084fa731a1dc0f80b2f
```

**If the version or the manifest differs, stop and report it.** A verdict from
unknown gate code is not a verdict. Do not investigate by reading or editing the
package — report the two values you got and let a human establish which version
is approved.

## 1 · The boundary

| | |
|---|---|
| **You may read** | captures, staging files, denominators, stop-conditions, `_qa/` verdicts and reports |
| **You may write** | nothing directly. `kbqa` writes `_qa/` and the log when you pass recording flags |
| **You may never touch** | anything under the kbqa install path — `gates/`, `models.py`, `profiles/`, `conventions.py`, `report.py`, tests, fixtures |
| **You may never run** | `pip install`, `pip uninstall`, `pip install -e`, or any command that changes which kbqa is installed |

A gate is satisfied by the data, never by changing what the gate says. If you
believe a gate is wrong, say so and cite the module and its SHA from the
finding — that is a legitimate dispute. Editing it is not.

## 2 · Check one batch

```bash
python3 -m kbqa report --vendor-dir <subject-dir> --batch <name> --vendor <name> \
  --denominator <subject-dir>/_denominator-*.md \
  --stops <subject-dir>/_stop-conditions.md \
  --log _qa-log.jsonl
```

Runs G1–G3 (and G4 when a denominator is given), writes each verdict to `_qa/`,
and renders `_qa/<batch>.report.md` plus a `.report.json`.

Read the report's **Coverage** section first. It names the gates that did not
run. A gate that did not run has found nothing, which is not the same as having
found nothing wrong — never report the batch as clean without checking it.

To check one thing in isolation, without writing anything:

```bash
python3 -m kbqa g1 --staging <f> --capture <f>     # capture integrity
python3 -m kbqa g2 --staging <f>                   # conformance
python3 -m kbqa g3 --staging <f> --capture <f>     # grounding
python3 -m kbqa g4 --denominator <f> --rows <f>... --stops <f>
```

Bare gate runs are side-effect-free. Exit 0 = PASS, 1 = FAIL. **Exit 2 means
DECLINED and appears only from `g0`** — a usage error exits 1, never 2.

## 3 · Check the estate

```bash
python3 -m kbqa g6 --root .        # verdicts, manifests, merged trees agree
python3 -m kbqa sweep --root .     # which batches can be checked at all
```

`sweep` sorts every batch into `verifiable`, `unassessable-no-page-markers`
(recoverable by re-fetch), or `unverifiable-no-capture` (not recoverable). A
corpus is in good order when each batch is in the tier it ought to be — not when
all of them are verifiable.

## 4 · Routing a failure

Every finding in the report carries a class. Route by it, and say which:

| class | goes to | meaning |
|---|---|---|
| **structural** | re-fetch / re-collect | no edit to the rows can make this true |
| **planner** | the planner | scope or fetch-list work |
| **fixable** | the row-writer | the rows disagree with their own evidence |

**Never hand a failure back to the agent that wrote the rows as "try again".**
That retry loop is where gaming begins. `structural` and `planner` findings go
to the planner; only `fixable` findings return to the row-writer, and then with
the specific finding, not the gate name.

A finding is resolved when it stops appearing on a re-run — not when it has been
explained.

## 5 · Never

- Edit a gate, `models.py`, a profile, or a convention so a batch passes
- Switch `--profile` to one that accepts what the current profile rejects
- Lower or delete a denominator entry to close a G4 gap
- Clear `fetched_by_this_agent` to silence `role_collapse`
- Edit a capture, a robots artifact, or a denominator — Bronze is immutable,
  not even for a typo. A vendor typo is evidence; correcting it breaks the
  match correctly
- Rewrite a `source_quote` to match the page. If the quote is not on the page,
  the row is wrong — drop it or re-source it
- Regenerate or hand-edit a test fixture
- Report only the gates that passed

## 6 · What the gates cannot see

Say this when reporting a clean run, so it is not read as more than it is:

- **G3 checks a quote is real and on the cited page. It does not check that the
  quote supports the claim.** A row can pass every gate while claiming far more
  than its quote warrants.
- **G4 measures coverage against the denominator we captured.** A selective
  index goes unnoticed.
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
