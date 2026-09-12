# kbqa — product manual

**Version 5.0.0** · for operators and for agents

---

## 1 · What this is

A validation layer for evidence-grounded data collection. It checks that every
collected row is traceable to a verbatim quote in a stored page capture.

It exists because **a feature-tree cannot be told apart from invention by
reading it.** A paraphrase presented as a quote looks exactly like a quote; an
invented field looks like a field. So the purpose is narrower and harder than
"validate the data":

> Make invention detectable **without a human re-reading every source.**

### What a PASS means, precisely

A PASS is worth something only when three things hold together:

| condition | how it is met |
|---|---|
| the gates catch what they claim | 189 tests; every blocking gate proven to fail on a purpose-built fixture |
| the gates could not have been edited to pass | installed from a pinned tag of a repo whose CI is enforced |
| the gates ran against the real files | the parser is confirmed against collector output |

If any is false, a PASS means only "nothing complained", which is a much weaker
claim and easy to mistake for the strong one.

### What it does NOT claim

- It does not say a row is **true**. It says the quote appears on the page cited.
- It does not say an unverifiable row is **wrong**. It says no one can check it.
- A gate that did not run has found nothing — which is not the same as having
  found nothing wrong.

---

## 2 · Install

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[test]"
```

> **Requires pip ≥ 21.3.** Older pip cannot read PEP 621 metadata and will
> silently install an empty package named `UNKNOWN-0.0.0`, reporting
> `Successfully installed`. If `python -m kbqa --version` errors after an
> install that looked fine, that is what happened:
> `pip uninstall UNKNOWN`, upgrade pip, reinstall.


For an estate or CI, install from the pinned tag rather than a branch:

```bash
pip install "git+https://github.com/ramygwprod/kb-qa.git@v5.0.0"
```

**Always a tag, never a branch.** A branch would let the gates and the data they
judge change in the same push, which is the failure mode the whole design exists
to prevent.

Verify what you installed:

```bash
python -m kbqa --version
python -m kbqa --manifest      # SHA-256 of every gate module
```

---

## 3 · Concepts

### The three tiers of data

| tier | meaning |
|---|---|
| **Bronze** | raw, immutable — captures, robots.txt, denominators. **Never edited.** Not to fix a typo, not to normalise whitespace. If it is wrong, re-fetch into a new dated file |
| **Silver** | staging rows written from Bronze |
| **Gold** | `feature-tree.md`, written only by the merge step |

### The seven gates

| gate | checks | exit codes |
|---|---|---|
| **G0** permission | robots.txt allows our agent | 0 allowed · **2 DECLINED** · 1 unreachable |
| **G1** capture integrity | capture exists, markers balanced, hash matches, capture predates staging | 0 / 1 |
| **G2** conformance | every row validates against the contract; no duplicate ids; **zero rows is a FAIL** | 0 / 1 |
| **G3** grounding | every quote is a substring of **its own page's block** | 0 / 1 |
| **G4** completeness | every index item is covered by a row or a reasoned stop-condition | 0 only when `without_row == 0` |
| **G5** bundles | same term at multiple URLs | **always 0** — advisory |
| **G6** integrity | manifest match, Bronze untouched, proof counts, role collapse, **skipped checks** | 0 / 1 |

**G3 is the correctness gate.** It is the only one whose ground truth is the
vendor's page rather than our plan, so it is the only one that can catch a wrong
specification. Everything else tests conformance to what we decided.

**Exit 2 means DECLINED and nothing else.** A usage error exits 1, never 2 — a
typo must never be readable as a permission decision.

### The contract has three layers

Subjects differ in structure, naming, depth and scale — genuinely. So the row
contract is split by **owner**, and the outer split is by **domain**:

| layer | rule | who owns it |
|---|---|---|
| **universal core** | strict | everyone. `id`, `source_url`, `source_quote`, `access_date`, `broken_source` — what makes *any* claim checkable |
| **profile** | strict, but swappable | one programme's analytical framework. For `vendor-catalogue`: `mechanism`, `outcome`, `depth_level`, `evidence_grade`, `confidence` |
| **extensions** | NAME registered, VALUE never constrained | the subject's own vocabulary |

`extra="forbid"` did not go away — it **moved**. A collector inventing a field
still fails on the first row, and the message names the profile to register it
in. What no longer happens is rejecting a subject for using a word the subjects
collected first did not use.

**Nothing is renamed.** Rows keep the exact keys the collector wrote.
`alias_of` records how an extension relates to a core field without touching
either. Renaming would itself be the editing this package exists to prevent.

§G3 already settles the principle for text: *never normalise spelling, because
a subject's typos are evidence.* Structure is evidence by the same argument.

### Profiles

```bash
python -m kbqa --profiles                    # list
python -m kbqa --profile <name> <command>    # select
```

A profile bundles the analytical framework, the extension registry, and the
**conventions** — file naming, capture marker syntax, id pattern. All are one
programme's choices, not facts about the world: a corpus that delimits pages
differently would otherwise parse to zero blocks, and zero blocks reads as
"nothing to check against", not "wrong syntax".

Adding a domain is a new module under `src/kbqa/profiles/`. No gate changes;
the gates work against parsed structures and a row model.

### Findings: kind and nature

Every finding carries two orthogonal classifications, and the maker needs both.

**Kind — whose work is it:**

| kind | meaning |
|---|---|
| `structural` | **not repairable by editing rows.** A missing capture is an absent Bronze artifact, not a defect in the staging file. Editing rows to clear it would be fabrication |
| `planner` | scope or fetch-list work — an uncovered index item, a cited page nobody fetched |
| `fixable` | the rows disagree with the contract or their own evidence; correcting them is legitimate |

**Nature — is something missing or wrong:**

| nature | meaning |
|---|---|
| `gap` | something is **absent**. It has to be produced, or its absence recorded as a decision |
| `issue` | something is **present and wrong**, correctable in place |

Conflating these is how "fix the failures" becomes "edit rows until green".

---

## 4 · Structure

```
kb-qa/
├── pyproject.toml
├── CHANGELOG.md                    release history, SemVer
├── README.md
├── src/kbqa/
│   ├── __init__.py                 __version__
│   ├── __main__.py                 python -m kbqa
│   ├── models.py                   the UNIVERSAL core — domain-neutral
│   ├── extensions.py               extension-field type and kinds
│   ├── conventions.py              file naming, markers, id pattern
│   ├── profile.py                  profile registry and activation
│   ├── profiles/                   one module per analytical framework
│   ├── parsing.py                  readers for staging / capture / denominator
│   ├── manifest.py                 SHA-256 of every module, computed at import
│   ├── verdict.py                  Verdict + Finding + JSON writer + log writer
│   ├── cli.py                      command dispatch
│   ├── probe.py                    format diagnostic — shape without content
│   ├── report.py                   remediation report for the maker
│   ├── sweep.py                    estate audit — what can be checked at all
│   └── gates/
│       ├── g0_permission.py … g6_integrity.py
├── tests/
│   ├── build_fixtures.py           fixtures are GENERATED, never hand-edited
│   ├── conftest.py
│   ├── fixtures/                   21 fixtures: 1 good, 20 purpose-built failures
│   ├── test_gates.py  test_cli.py  test_probe.py  test_report.py
│   ├── test_sweep.py  test_parsing.py  test_models.py
├── agents/                         role definitions — INSTALL INTO THE ESTATE
│   ├── fetcher.md                  tools: WebFetch, Write, Read
│   └── row-writer.md               tools: Read, Write, Bash — NO WebFetch
├── ci/
│   ├── estate-qa.yml               copy to <estate>/.github/workflows/qa.yml
│   └── estate-pre-push             copy to <estate>/.git/hooks/pre-push
└── docs/
    ├── MANUAL.md                   this file
    ├── DECISIONS.md                contract changes, with evidence
    └── STAGING-FORMAT.md           on-disk formats the gates read
```

### The estate it validates

The container directory's name varies by estate (`Competitors/`, `kk/`, …).
Every tool discovers batches recursively and derives the vendor from position
under the root — `--vendor-depth` adjusts that for other layouts. Nothing
hardcodes a container name, because a discovery pattern that matches no files
looks exactly like a clean estate.

```
<estate>/
├── <container>/<Vendor>/
│   ├── _robots-<host>-<date>.txt          BRONZE  immutable
│   ├── _capture-<batch>.raw.txt           BRONZE  immutable
│   ├── _denominator-<surface>-<date>.md   BRONZE  immutable
│   ├── _collect-<batch>-staging.md        SILVER
│   ├── _stop-conditions.md                SILVER
│   ├── feature-tree.md                    GOLD
│   └── _qa/                               verdicts + reports, append-only
│       ├── <batch>.<gate>.json
│       ├── <batch>.report.md
│       └── <batch>.report.json
├── _qa-log.jsonl                          one line per gate run, append-only
└── _qa-estate-audit.md / .json            written by `kbqa sweep`
```

---

## 5 · Workflows

### 5.1 · Operator — auditing what you already have

Start here on an unfamiliar estate. Needs no captures and changes nothing.

```bash
python -m kbqa sweep --root "<estate>" --field-values
```

Produces `_qa-estate-audit.md` and `.json`, answering one question per batch:
**can a reader check this against the vendor's own words?**

Read the split first. Three tiers, and the difference decides what to do:

| tier | meaning | recoverable? |
|---|---|---|
| `verifiable` | capture splits into pages; every quote checkable | — |
| `unassessable-no-page-markers` | text stored but no page boundaries | **yes** — re-fetch with a marker-writing fetcher, no need to re-collect rows |
| `unverifiable-no-capture` | page text never stored | no |

None of these says a row is wrong. Unverifiable rows are *uncheckable*:
re-fetching returns today's page, not the page the claim came from. That is a
property of how the batch was collected, not a defect to repair.

`--field-values` lists every field the collector emits, flagging those outside
the contract. That is the evidence for the next schema version.

### 5.2 · Operator — checking one batch

```bash
python -m kbqa report \
  --vendor-dir "<estate>/Competitors/Acme" \
  --batch widgets \
  --vendor Acme \
  --denominator "<estate>/Competitors/Acme/_denominator-docs-2026-08-23.md" \
  --stops "<estate>/Competitors/Acme/_stop-conditions.md" \
  --log "<estate>/_qa-log.jsonl"
```

Runs G1–G3 (and G4 with a denominator), writes each verdict to `_qa/`, appends
to the log, and renders `_qa/<batch>.report.md`.

**Exit 0** = every gate that ran is green. **Exit 1** = something failed.

Read the **Coverage** section before the findings. It names the gates that did
*not* run and why, so a short findings list is never mistaken for broad
coverage.

### 5.3 · Operator — resuming collection

1. `kbqa sweep` — know which trees rest on checkable evidence
2. Collect a batch with the fetcher/row-writer split (§5.5)
3. `kbqa report` for that batch
4. Act on the report, or route it to the maker
5. Re-run the report — a finding is resolved when it stops appearing
6. Merge to Gold, then `kbqa g6 --root <estate>`

### 5.4 · Maker agent — consuming a report

You are being handed work. The report is at `_qa/<batch>.report.md`, and
`_qa/<batch>.report.json` carries the same plan in machine-readable form.

**Read `gates_not_run` first.** A gate that did not run found nothing, which is
not the same as having found nothing wrong.

**Work the action plan in order.** It is sequenced so nothing depends on work
further down the list: structural → planner → fixable, gaps before issues.

**Respect the classification. This is the important part.**

- `structural` — **do not edit rows.** The remedy is to produce a missing
  artifact, re-collect, or record a decision. Editing rows to clear a structural
  finding is fabrication, not repair.
- `planner` — scope work. Add a page to the fetch list, plan a batch, record a
  reasoned stop-condition. Do not lower the denominator to close a gap.
- `fixable` — correct the rows.

**Never edit the checker.** Every finding names the gate module and its SHA-256.
If you believe a gate is wrong, say so and cite that hash. A verdict from edited
code is distinguishable from a verdict from approved code — that is what
recording the hash is for, and editing a gate to make a batch pass leaves a
trace rather than hiding one.

**The specific trap.** `quote_not_in_capture` is the most gameable finding in
the set. Legitimate fixes: replace the quote with text the page actually
contains, or drop the row. Illegitimate: editing the quote until it matches
something, anything, elsewhere in the capture. If the page does not support the
claim, the claim is not supported.

**Verify by re-running the same command.** A finding is resolved when it stops
appearing — not when it is explained.

### 5.5 · Role separation — enforced by capability

Attestation is not proof. **Deny the tool instead.** Copy both definitions into
the estate:

```
<estate>/.claude/agents/fetcher.md      tools: WebFetch, Write, Read
<estate>/.claude/agents/row-writer.md   tools: Read, Write, Bash
```

The row-writer has **no `WebFetch`**. Role separation becomes a fact about the
environment rather than an instruction that can be forgotten under pressure. Its
only input is a capture file, so no capture means no rows — which is what stops
ungroundable rows being produced in the first place.

G6 still checks the `fetched_by_this_agent` attestation, but that check is a
backstop for a collapse the tool list should have made impossible.

### 5.6 · Confirming a format without disclosing data

When the checker must not read the estate — a separate session, a reviewer, a
support conversation:

```bash
python -m kbqa probe --staging <f> --capture <f>
```

Reports field names, value types, string lengths, marker syntax, and whether the
shipped parser agrees with the file. **Never** quotes, URLs, vendor terms, or
free text. That boundary is enforced by tests, not by care: `tests/test_probe.py`
fails if row content reaches the report.

The output is designed to be pasted to someone who must not see the data.

---

## 6 · Command reference

| command | purpose | exit |
|---|---|---|
| `g0 --host <host> --out <vendor-dir>` | permission | 0 · **2 DECLINED** · 1 |
| `g1 --staging <f> --capture <f>` | capture integrity | 0 / 1 |
| `g2 --staging <f>` | conformance | 0 / 1 |
| `g3 --staging <f> --capture <f>` | grounding | 0 / 1 |
| `g4 --denominator <f> --rows <f>... [--stops <f>]` | completeness | 0 / 1 |
| `g5 --rows <f>...` | bundles | **always 0** |
| `g6 --root <project>` | integrity | 0 / 1 |
| `report --vendor-dir <d> --batch <n>` | remediation report | 0 / 1 |
| `sweep --root <estate>` | estate audit | 0 / 1 |
| `probe --staging <f>` | format diagnostic | 0 / 1 |
| `--manifest` · `--version` | provenance | 0 |

**Recording flags** apply to any gate: `--vendor-dir`, `--batch`, `--vendor`,
`--log`. Without them a gate run is **side-effect-free** — the verdict goes to
stdout and nothing is written.

**`sweep` flags:** `--field-values` collects value distributions; `--out` sets
the output path.

---

## 7 · Findings reference

46 codes. Every one carries a remedy, enforced by `tests/test_report.py` — a
report that falls back to "see the message" for its most important findings is
not a report.

| code | kind | nature | remedy summary |
|---|---|---|---|
| `batch_known_failing` | planner | issue | A current FAIL verdict, still in the estate |
| `batch_unchecked` | fixable | gap | No verdict records this file — the gates never ran |
| `bronze_missing` | structural | gap | A Bronze artifact is absent; re-fetch, never reconstruct |
| `bronze_modified` | structural | issue | Bronze changed after it was written |
| `bronze_touched_after_verdict` | structural | issue | Every verdict citing it is void |
| `capture_empty` | structural | gap | Capture holds no text; re-fetch |
| `capture_hash_absent` | fixable | gap | Add `source_capture_sha256` to frontmatter |
| `capture_hash_mismatch` | structural | issue | Rows written from different bytes; re-run the row-writer |
| `capture_has_no_page_blocks` | structural | gap | Text stored, no page boundaries. Rows are **unassessable, not ungrounded** — re-fetch with markers |
| `capture_missing` | structural | gap | Nothing to check against. Re-collect or record as unverifiable |
| `capture_not_before_staging` | structural | issue | Rows cannot have been written from this capture |
| `denominator_missing` | structural | gap | Coverage unmeasurable |
| `duplicate_id` | fixable | issue | Two rows share an id; establish which is which |
| `duplicate_page_block` | structural | issue | A URL captured twice; re-fetch cleanly |
| `empty_denominator` | structural | gap | Re-capture the index surface |
| `frontmatter_unparseable` | fixable | issue | Correct the frontmatter |
| `index_item_without_row` | planner | gap | Plan a batch, or record a reasoned stop |
| `manifest_mismatch` | structural | issue | **Tamper-evidence firing.** Verdicts came from other code |
| `marker_unbalanced` | structural | issue | Capture is corrupt; re-fetch, do not hand-repair |
| `no_declared_pages` | fixable | gap | Add the `pages:` list |
| `no_source_quote` | fixable | gap | Add a verbatim quote, or drop the row |
| `no_source_url` | fixable | gap | Cite the page the quote is on |
| `nothing_checked` | structural | gap | An empty check is not a pass |
| `page_not_in_capture` | planner | issue | Fetch the page, or the row is unsupported |
| `pages_not_a_list` | fixable | issue | `pages:` must be a list |
| `parser_disagrees_with_naive_count` | structural | issue | **Tooling fault.** Fix `parsing.py`, not the rows |
| `proof_count_mismatch` | fixable | issue | Correct the GOLD proof count |
| `proof_unparseable` | fixable | issue | Restore a readable `proof:` line |
| `quote_from_wrong_page` | fixable | issue | Correct `source_url`; the row is misattributed |
| `quote_not_in_capture` | fixable | issue | **Most gameable.** Replace the quote or drop the row — never quote-shop |
| `robots_unreachable` | structural | gap | Not permission to proceed. Retry; if persistent, treat as closed |
| `role_collapse` | structural | issue | One agent fetched and wrote. Re-collect with separated roles |
| `root_missing` | structural | gap | Nothing was inspected |
| `row_unparseable` | fixable | issue | Invalid JSON; it was never checked |
| `row_unparseable_not_checked` | structural | issue | Unchecked rows are not sound rows |
| `rows_file_missing` | structural | gap | Run-configuration fault |
| `schema_violation` | fixable | issue | Correct the row, or bump the contract deliberately |
| `site_wide_disallow` | structural | issue | **Terminal.** No retry, no alternate fetcher |
| `staging_missing` | structural | gap | Wrong batch name, or the row-writer never ran |
| `stop_condition_without_reason` | fixable | gap | "We stopped" is not a reason |
| `stops_file_missing` | structural | gap | Wrong path, or no stops recorded — not the same thing |
| `term_at_multiple_urls` | planner | issue | Advisory. An R2 naming question; resolve nothing by guessing |
| `url_not_in_capture` | planner | issue | Page never fetched, or the URL is invented |
| `verdict_stale` | fixable | issue | Checked, then edited. Re-run the gates |
| `verdict_unreadable` | structural | issue | Re-run the gate; do not assume it was green |
| `zero_rows` | structural | gap | A parser seeing nothing and a file holding nothing look identical |

---

## 8 · Trust model

From spec §0, and stated honestly:

| level | mechanism | status |
|---|---|---|
| 1 · tamper-evident | SHA-256 manifest in every verdict | built |
| 2 · out-of-scope | gates outside the collector's folder | built |
| 3 · capability-denied | row-writer has no `WebFetch` | built |
| 4 · **tamper-proof** | CI re-runs gates from a pinned tag | **enforced on `kb-qa`** |

### The validator: level 4

`kb-qa` is public, its ruleset enforces, required status checks block merges to
`main`. Proven, not assumed — a direct push was rejected with `GH013`.

### The estate: level 3½

A private repo on a free GitHub plan cannot enforce rulesets, so estate CI
reports without blocking. §0 permits this: levels 1–3 *"make tampering visible
and inconvenient, which is enough when a human reads the verdicts."*

Three controls keep that clause true:

1. **G6 detects skipped checks** — `batch_unchecked`, `verdict_stale`. This
   check lives inside the pinned gates, where level 4 already holds, so whoever
   skips a check cannot edit the check that notices. Enforcement moved out of
   git, where it is unavailable, into the gates, where it is not.
2. **`ci/estate-pre-push`** refuses a push on a failing sweep. Level 2 —
   bypassable with `--no-verify` by design, making a skip deliberate.
3. **CI job summary**, so an unenforced red X is not scrolled past.

⛔ **The estate is not tamper-proof and must not be described as such.** The
accurate statement: *the gates cannot be edited; running them can be skipped;
skipping is recorded.*

**Revisit if the maker agent ever gets push access to the estate** — at that
point no human sits between the collector and the repository, §0's clause stops
holding, and GitHub Team becomes the cheap answer. See DECISIONS.md D-003.

---

## 9 · Versioning and release

### Scheme

[Semantic Versioning 2.0.0](https://semver.org/), with one project rule:

> **The row contract is part of the public API.** Any change to `models.py` that
> could make a previously valid row invalid is a MAJOR bump, even if no Python
> signature changed. A batch that passed yesterday and fails today without the
> data changing is a breaking change to its consumers.

| bump | when |
|---|---|
| MAJOR | contract change; a gate becomes stricter; a finding code is removed or reclassified |
| MINOR | a new gate, command, or finding code; a gate becomes more precise without rejecting previously valid rows |
| PATCH | a fix that changes no verdict on valid data; docs; tests |

### Release process

1. Land all changes on `main` through a PR with both `gates` checks green
2. Update `CHANGELOG.md` — Keep a Changelog format, newest first, with the
   evidence for anything breaking
3. Record contract changes in `docs/DECISIONS.md` with the observation behind
   them and a reversal condition
4. Bump `pyproject.toml` and `src/kbqa/__init__.py` together
5. `pytest tests/ -q` — all green, fixtures regenerate byte-identically
6. Tag `vMAJOR.MINOR.PATCH` and push the tag
7. Confirm CI is green **on the tag**, not just on `main` — that is the artifact
   estates will pin
8. Move estate pins deliberately, one estate at a time

### Pinning

Estates install from a **tag**. Never a branch. A branch would let the gates and
the data they judge change in the same push.

Moving a pin is a deliberate act: read the CHANGELOG, expect new findings on
data that previously passed, and re-run `kbqa sweep` before and after so the
difference is attributable to the version rather than to the data.

### Compatibility

`manifest_sha256` in every verdict identifies the exact gate code that produced
it. Verdicts from different versions are distinguishable, and G6's
`manifest_mismatch` fires when recorded verdicts came from code other than what
is installed. That is tamper-evidence, not a version check — treat it as a
signal to establish which version is approved and re-run, never to reconcile by
editing the recorded manifest.

---

## 10 · Troubleshooting

**Every batch fails G1 with `capture_hash_absent` / `no_declared_pages`.**
The collector does not write `source_capture_sha256` or a `pages:` list, both
required by §G1. This is a real gap in the collector's output, not a checker
defect — but it means no batch can be fully CLEAR until the collector emits
them.

**Every row fails G2 with `schema_violation`.**
The collector emits a field the contract does not name. Confirm with
`kbqa sweep --field-values`, then either extend `models.py` by a deliberate
version bump with a DECISIONS.md entry, or remove the field from the collector.
Do not silence it.

**G3 fails on rows that look correct.**
Check `quote_from_wrong_page` versus `quote_not_in_capture`. The first is a
misattributed `source_url`, the second means the text is not on the cited page
at all. Normalisation folds Unicode quotes, dashes and whitespace only — **never
spelling.** A vendor typo is evidence; correcting it breaks the match correctly.

**`manifest_mismatch` from G6.**
Recorded verdicts came from different gate code than is installed. Establish
which version is approved, then re-run the gates from it.

**The probe says `DOES NOT MATCH`.**
The sections above the verdict say where — a missing `---`, different marker
syntax, fields outside the contract, rows that do not parse. Only
`src/kbqa/parsing.py` needs correcting; gate logic is written against parsed
structures and does not move.

**A gate reported FAIL with no findings.**
That is a defect in the gate, not a clean batch. Do not read it as a pass.

---

## 11 · Rules that are not negotiable

- **Bronze is never edited.** Not for a typo, not for whitespace. Re-fetch into
  a new dated file.
- **A failed gate returns to the planner**, never to the executor as "try
  again". That is the retry loop, and it is where gaming begins.
- **Zero rows is a FAIL.** A parser that sees nothing and a file that holds
  nothing look identical; treat the ambiguity as a defect.
- **A missing capture is a FAIL**, never a warning.
- **Exit 2 means DECLINED and nothing else.**
- **Never normalise spelling** when matching quotes.
- **A gate that has never failed has not been tested.**
- **Fixtures are generated, not hand-edited.** Editing a fixture to make a gate
  pass is the exact failure mode this package exists to catch.
