# kbqa — user manual

**Version 5.0.0** · for operators and for maker agents

Extending or maintaining the package? See [DEVELOPMENT.md](DEVELOPMENT.md).

---

## 0 · Quickstart

```bash
pip install --upgrade pip
pip install "git+https://github.com/ramygwprod/kb-qa.git@v5.0.0"
python -m kbqa --version          # must print 5.0.0
```

**Audit a corpus** — needs no captures, changes nothing, answers "what here can
be checked at all?"

```bash
python -m kbqa sweep --root <corpus> --field-values
```

**Check one batch** and produce a report a maker can act on:

```bash
python -m kbqa report --vendor-dir <corpus>/<Subject> --batch <name> \
  --vendor <Subject> --log <corpus>/_qa-log.jsonl
```

Exit 0 means every gate that ran is green. Exit 1 means something failed — read
`_qa/<batch>.report.md`, starting with the **Coverage** section, which names the
gates that did *not* run.

**Confirm a file's format without disclosing its contents:**

```bash
python -m kbqa probe --staging <f> --capture <f>
```

Everything else in this manual is detail on those four commands.

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

## 4 · The corpus

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

### 5.7 · Pipeline runbook

`$C` = corpus root · `$D` = `$C/<container>/<Subject>` · `$B` = batch name.

```bash
C=/path/to/corpus; D=$C/Competitors/Example; B=widgets
```

**Who acts** — `P` planner session · `F` fetcher subagent · `R` row-writer
subagent · `H` human decision.

| # | Action | Accept when | Error | Fix |
|---|---|---|---|---|
| 1 | **P** `python3 -m kbqa g0 --host <host> --out $D` | exit 0 | `site_wide_disallow` (exit 2) | → **A** |
| | | | `robots_unreachable` (exit 1) | Wait, re-run step 1. If it persists, → **A** |
| 2 | **F** → **B**, targeting the subject's index page | `_denominator-*.md` exists, non-empty | no file | Re-run **B** |
| 3 | **P** list URLs **from the denominator only** | a fixed list per batch | — | No link-following, no URL construction |
| 4 | **F** → **C** | receipt has path, bytes, sha256, URL list | partial/failed fetch | Re-run **C** |
| 5 | **R** → **D** | `$D/_collect-$B-staging.md` exists | R asks to fetch | R has no `WebFetch`. Add the URL to step 3's list, re-run **C**, then **D** |
| 6 | **P** `python3 -m kbqa report --vendor-dir $D --batch $B --vendor <S> --log $C/_qa-log.jsonl` | prints `CLEAR`, exit 0 | anything below | Open `$D/_qa/$B.report.md` |
| 7 | ↳ G1 | `capture_blocks` > 0 | `capture_missing` · `capture_empty` · `marker_unbalanced` · `duplicate_page_block` | Re-run **C**, then step 6 |
| | | | `capture_hash_absent` · `no_declared_pages` | → **E** |
| | | | `capture_hash_mismatch` · `capture_not_before_staging` | Re-run **D** (rows came from different bytes), then step 6 |
| | | | `page_not_in_capture` | Add that URL to step 3's list → **C** → **D**; *or* delete the rows citing it |
| 8 | ↳ G2 | `rows` == `naive_rows`, `failed` 0 | `schema_violation` | → **F** |
| | | | `non_row_object` | Move that object's keys into the frontmatter block; delete the line |
| | | | `duplicate_id` | → **G** |
| | | | `row_unparseable` | Fix the JSON on the line the report names |
| | | | `zero_rows` · `parser_disagrees_with_naive_count` | → **H** (tooling, not data) |
| 9 | ↳ G3 | `grounded` == `rows` | `quote_not_in_capture` · `quote_from_wrong_page` | → **I** |
| | | | `capture_has_no_page_blocks` | Re-run **C** with a marker-writing fetcher, then step 6 |
| | | | `url_not_in_capture` | Same as `page_not_in_capture`, row 7 |
| | | | `no_source_quote` · `no_source_url` | → **D** for those rows; if the page does not support the claim, delete the row |
| 10 | **P** `python3 -m kbqa g4 --denominator $D/_denominator-*.md --rows $D/_collect-*-staging.md --stops $D/_stop-conditions.md` | exit 0, `without_row` 0 | `index_item_without_row` | Add to step 3's list and collect it, *or* → **A** for that URL |
| | | | `stop_condition_without_reason` | → **A** |
| 11 | **P** `python3 -m kbqa g5 --rows $D/_collect-*-staging.md` | always exit 0 | `term_at_multiple_urls` | Advisory. Record as an open question; do **not** infer a relationship |
| 12 | **P** merge rows into `$D/feature-tree.md` | `proof:` count == rows in file | `proof_count_mismatch` | Set `proof:` to the actual count |
| 13 | **P** `python3 -m kbqa g6 --root $C` | exit 0 | `batch_unchecked` · `verdict_stale` | Run step 6 for each batch named |
| | | | `role_collapse` | → **J** |
| | | | `bronze_modified` · `bronze_touched_after_verdict` | Re-run **C** into a new dated file; re-run step 6 |
| | | | `manifest_mismatch` | → **K** |

---

#### Procedures

**A · Record a stop**

```bash
cat >> "$D/_stop-conditions.md" <<EOF
- <url or label>: <why, specifically — 404 on 2026-09-12, login wall, superseded by X>
EOF
```

"We stopped" fails G4. State what was observed.

**B · Fetcher — denominator**

Spawn the `fetcher` subagent:

> Fetch `<index URL>`. Write it verbatim to `$D/_denominator-<surface>-<today>.md`
> as markdown links, one index item per line. Return a receipt only: path,
> bytes, item count.

**C · Fetcher — batch capture**

> Fetch exactly these URLs: `<list>`. Write verbatim page text to
> `$D/_capture-$B.raw.txt`, each page wrapped in
> `=====BEGIN <url>=====` … `=====END <url>=====`. Never fix typos, normalise
> whitespace, unwrap lines, or omit sections. Return a receipt only: capture
> path, bytes, `shasum -a 256` of the capture, the URLs actually fetched, and
> any failures.

**D · Row-writer — staging**

> Your only source is `$D/_capture-$B.raw.txt`. You cannot fetch. Write
> `$D/_collect-$B-staging.md`: frontmatter with `batch`, `vendor`,
> `source_capture`, `source_capture_sha256: <sha from the receipt>`,
> `pages:` listing `<URLs from the receipt>`, `fetched_by_this_agent: false`.
> Then one JSON object per line, `id` first. Quote character-for-character from
> the capture including typos. Where the capture does not say, write `unknown`.
> Return a receipt only: path, row count.

**E · Add the capture hash and page list**

```bash
shasum -a 256 "$D/_capture-$B.raw.txt" | cut -d' ' -f1
grep -oE '^=====BEGIN (.+)=====$' "$D/_capture-$B.raw.txt" | sed 's/=====BEGIN //; s/=====$//'
```

Put the first into frontmatter as `source_capture_sha256:` and the second as a
`pages:` list (or a markdown table of page URLs — both are read).

⚠ Do this from the **fetcher's receipt** when collecting. Deriving them from the
capture afterwards makes G1 ask whether the capture matches itself.

**F · A schema violation**

Find the field and error type:

```bash
python3 -c "
import json,sys
sys.path.insert(0,'src')
from pathlib import Path
from kbqa.parsing import parse_staging
from kbqa.profile import row_model
from pydantic import ValidationError
M=row_model()
for r in parse_staging(Path('$D/_collect-$B-staging.md')).rows:
    if not r.obj: continue
    try: M(**r.obj)
    except ValidationError as e:
        for x in e.errors(): print(r.line_no, x['type'], '.'.join(map(str,x['loc'])))
" | sort -k2 | uniq -c -f1
```

Then **one** of:

- **the row is wrong** → correct it at the line number given
- **the field is the subject's own** → register it in the profile:

  ```python
  # src/kbqa/profiles/<profile>.py, in EXTENSIONS
  "their_field": ext(VERBATIM, None,
                     "What the subject means by it, in one sentence."),
  ```

  Then bump `SCHEMA_VERSION`, add a `DECISIONS.md` entry, and release.
- **the contract is wrong** → same, but change `models.py` or the profile's Row

**G · A duplicate id**

```bash
grep -n '"id": *"<the id>"' "$D/_collect-$B-staging.md"
```

Compare the two rows' `source_url`. Different pages describing the same node →
delete one. Different nodes → give the second a distinct id reflecting its
position, not a numeric suffix.

**H · Parser disagrees with the file**

```bash
python3 -m kbqa probe --staging "$D/_collect-$B-staging.md"
```

Read the final `VERDICT:` line. `DOES NOT MATCH` means `parsing.py` needs
correcting — not the rows. Output is shape-only and safe to share.

**I · An ungrounded quote**

The report names the row id and line. Then:

```bash
U='<the row\'s source_url>'
awk -v u="$U" 'index($0,"=====BEGIN "u"=====")==1,/^=====END /' "$D/_capture-$B.raw.txt"
```

(Literal string match, not a regex — a URL contains `/` and `.`, which an awk
pattern would interpret rather than match.)

Read that block and do **one** of:

- replace `source_quote` with text that appears in it verbatim
- `quote_from_wrong_page` → correct `source_url` to the page the text is on
- the page does not support the claim → **delete the row**

⛔ Do not search the whole capture for something the quote matches. Scoping to
the cited page is the entire point of the gate.

**J · Role collapse**

`fetched_by_this_agent: true` means one agent both fetched and wrote rows.
Clearing the flag hides it. Instead:

```bash
rm "$D/_collect-$B-staging.md"
```

Re-run **C** then **D** with the two separate subagents, then step 6.

**K · Manifest mismatch**

```bash
python3 -m kbqa --version && python3 -m kbqa --manifest | head -1
grep -h manifest_sha256 "$D"/_qa/*.json | sort -u
```

Verdicts were produced by different gate code than is installed. Decide which
version is approved, install it, re-run step 6 for every affected batch. Never
edit a recorded manifest.

---

**Routing.** A failed gate goes back to the **planner**, never to the executor
as "try again". The row-writer has `Bash` to write files, not to grade its own
output.

**Read Coverage first.** The report names gates that did *not* run. A gate that
did not run has found nothing — not the same as having found nothing wrong.

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

## 9 · Versions

Corpora install from a **tag, never a branch** — a branch would let the gates
and the data they judge change in the same push.

```bash
pip install --upgrade pip
pip install "git+https://github.com/ramygwprod/kb-qa.git@v5.0.0"
```

> `pip < 21.3` cannot read this project's metadata and installs an empty package
> named `UNKNOWN-0.0.0` while printing `Successfully installed`. If
> `python -m kbqa --version` errors after an install that looked fine, that is
> why: `pip uninstall UNKNOWN`, upgrade pip, reinstall.

**Moving a pin is a deliberate act.** Read the CHANGELOG, expect new findings on
data that previously passed, and run `kbqa sweep` before and after so any
difference is attributable to the version rather than to the data.

After a version bump, G6 reports `manifest_mismatch` once per gate against
verdicts recorded under the old code. That is tamper-evidence working: re-run
the gates. Never reconcile by editing a recorded manifest.

Release process, versioning rules and how to extend the package are in
[DEVELOPMENT.md](DEVELOPMENT.md).

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
