---
name: kbqa-check
description: Run the kbqa validation gates over a collected batch or a whole estate, read the verdict, and route failures. Use when a capture and staging file exist and need checking, when a gate has failed and the next step is unclear, or when asked whether a batch is grounded. Read-only with respect to the validator — it never modifies kbqa, and never edits rows to make a gate pass.
allowed-tools: Bash, Read
---

# Checking a subject with kbqa

**Invoked as:** `/kbqa-check <subject folder path>`

You are the **checker**. Run the gates over every batch in that folder, read
what they say, and tell the operator what happens next. You do not repair data,
and you do not touch the tool.

## 0 · Establish which validator you are about to trust

```bash
PINNED=v6.14.1
LATEST=$(git ls-remote --tags https://github.com/ramygwprod/kb-qa.git 2>/dev/null \
         | grep -o 'v[0-9][0-9.]*$' | sort -V | tail -1)
[ -n "$LATEST" ] && [ "$LATEST" != "$PINNED" ] \
  && echo "STALE SKILL: this copy pins $PINNED but $LATEST exists"
python3 -m pip install --force-reinstall --quiet \
  "git+https://github.com/ramygwprod/kb-qa.git@$PINNED" \
  && echo "reinstalled from $PINNED"
python3 -m kbqa --version && python3 -m kbqa --manifest | head -1
```

Expected for this copy's pin:

```
6.14.1
manifest_sha256 3ccb77fe2b40995af2fdd6ae25b600c0491a90eb7b62fd72ce35b02d1e23cfd5
```

Reinstalling first is deliberate. The authoritative copy is on GitHub, so a
tampered local package has a lifetime of one session — **do not protect a
derived artifact, re-derive it.**

Four outcomes, and they are not the same:

| what you see | what it means | what to do |
|---|---|---|
| version and manifest match | the validator is the approved one | proceed |
| `STALE SKILL` | a newer release exists; this copy was not refreshed | **proceed**, and report that you checked against `$PINNED` rather than the newest release. Tell the operator to refresh the skill |
| manifest differs, but the reinstall succeeded | the skill's pinned SHA is out of date relative to its own tag | report both values and proceed — the code came from the tag seconds ago |
| manifest differs and the reinstall **could not run** | provenance is unestablished | **stop.** A verdict from unknown gate code is not a verdict |

Only the last is a halt. An earlier version of this skill stopped on any
mismatch, which meant it halted after every release until someone hand-copied
it — training a false alarm into the one check that detects a swapped
validator. A check that cries wolf on routine events stops being read.

Never install `$LATEST` instead of `$PINNED` to clear the warning. That would
run gate code whose manifest this copy cannot vouch for, which is the opposite
of the point.

## 1 · The boundary

| | |
|---|---|
| **You may read** | captures, staging files, denominators, stop-conditions, `_qa/` verdicts and reports |
| **You may write** | nothing directly. `kbqa` writes `_qa/` and the log when you pass recording flags |
| **You may never touch** | anything under the kbqa install path — `gates/`, `models.py`, `profiles/`, `conventions.py`, `report.py`, tests, fixtures |

A gate is satisfied by the data, never by changing what the gate says. If you
believe a gate is wrong, say so and cite the module and its SHA from the
finding — that is a legitimate dispute. Editing it is not.

## 2 · Check every batch in the folder

A subject is collected in windows, so it has many batches. Check all of them:

```bash
D="<subject folder path>"
DEN=$(find "$D" -maxdepth 1 -name '_denominator*.md' | sort | head -1)
STOPS="$D/_stop-conditions.md"
[ -n "$DEN" ]   && DARG="--denominator $DEN" || { DARG=""; echo "NOTE: no denominator — G4 will not run"; }
[ -f "$STOPS" ] && SARG="--stops $STOPS"     || SARG=""
find "$D" -maxdepth 1 -name '_collect-*-staging.md' | sort | while read -r s; do
  b=$(basename "$s"); b=${b#_collect-}; b=${b%-staging.md}
  echo "=== $b"
  python3 -m kbqa report --vendor-dir "$D" --batch "$b" $DARG $SARG --log _qa-log.jsonl
done
```

Each pass runs G1–G3 (and G4 with a denominator), writes verdicts to `_qa/`, and
renders `_qa/<batch>.report.md` plus a `.report.json`.

`find` rather than a glob, and the flags built conditionally, both for reasons
worth keeping. A bare `_denominator*.md` glob expands to several filenames when
a subject has more than one, and the extra arguments are rejected — so the loop
would fail on exactly the subjects with the most collection behind them. And an
unmatched glob is a fatal error in zsh, which would read as the check failing
rather than as a folder with nothing in it. When there is no denominator at all the run still
proceeds, and **the NOTE goes in your report**: G4 did not run, so the subject's
coverage is unmeasured rather than complete.

Then check the windows form an unbroken chain that reached the end of the list:

```bash
python3 -m kbqa g4 --rows "$D"/_collect-*-staging.md
```

`collection_parked` means the collector stopped safely with more to collect —
correct behaviour, and the subject is simply unfinished. `no_exhaustion_evidence`
means nothing establishes the list ever ended.

**If the loop printed nothing, no batch was checked.** An empty folder and a
folder full of clean batches produce the same silent output, so say explicitly
that zero batches were found rather than reporting the subject clean. A sweep
matching no files looks exactly like a clean estate — that confusion has
produced real defects in this pipeline more than once.

**Read each report's Coverage section first.** It names the gates that did not
run. A gate that did not run has found nothing, which is not the same as having
found nothing wrong — never report a batch as clean without checking it.

To check one thing in isolation, without writing anything:

```bash
python3 -m kbqa g1 --staging <f> --capture <f>     # capture integrity
python3 -m kbqa g2 --staging <f>                   # conformance
python3 -m kbqa g3 --staging <f> --capture <f>     # grounding
```

Bare gate runs are side-effect-free. Exit 0 = PASS, 1 = FAIL. **Exit 2 means
DECLINED and appears only from `g0`** — a usage error exits 1, never 2.

## 3 · Check the estate## 3 · Check the estate

```bash
python3 -m kbqa g6 --root .        # verdicts, manifests, merged trees agree
python3 -m kbqa sweep --root .     # which batches can be checked at all
```

`sweep` sorts every batch into `verifiable`, `unassessable-no-page-markers`
(recoverable by re-fetch), or `unverifiable-no-capture` (not recoverable). A
corpus is in good order when each batch is in the tier it ought to be — not when
all of them are verifiable.

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

Do not assume version control exists — on the estate this was built for there is
none, so "revert it" has no referent and the tempting alternative is to
re-freeze. Re-freezing records the edit as the new truth, which is the one thing
the command exists to prevent. **If you are asked to re-freeze after a drift
report, say no and explain why.**

And where mapping statements exist:

```bash
python3 -m kbqa mappings --file <estate>/_mappings.jsonl --root <estate>
```

Statements live **outside** rows and key on `id`. `canonical` in a row is not a
mapping and must not be treated as one — see §5.

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

## 4b · What to tell the operator

They are the loop between maker and checker, so give them what they need to act
without opening a file:

- per batch: CLEAR or BLOCKED, and the finding count by class
- the **structural** and **planner** findings, which go back to planning
- the **fixable** findings, the only ones a row-writer should ever receive
- whether the subject reached the end of its list, or is parked at an offset
- **every gate that did not run, and why** — state this even when everything
  else is clean

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
- Re-freeze after a drift report, or advise anyone else to
- Treat a `canonical` value in a row as a mapping. Mappings live in their own
  file; a value written into a row is an edit to the row

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
