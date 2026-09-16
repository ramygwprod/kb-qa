# Decisions

Changes to the row contract are recorded here with the evidence behind them.
Spec §2: *"Changing this file is a version bump, a commit, and a note. Never
mid-run."* This is that note.

A decision belongs here when a later reader would otherwise have to guess why
the contract says what it says.

---

## D-001 · Schema v2 admits five collector fields

**Date** 2026-09-08 · **Status** decided · **Affects** `models.py`, `SCHEMA_VERSION`

### What was found

`kbqa probe` against a real batch (222 rows) showed five fields present in every
row and absent from the v1 contract:

| field | distinct values in that batch | reading |
|---|---|---|
| `node_kind` | 6 | varies — carries information |
| `deployment` | 2 | varies — carries information |
| `vendor_category` | **1** | constant across all 222 rows |
| `vendor_category_source` | **1** | constant across all 222 rows |
| `plan_gating` | **1** | constant across all 222 rows |

Two contract fields appeared in no row: `schema_version` and `usecase_of`.

### The decision

All five are admitted to the contract as `Optional[str]`. `SCHEMA_VERSION` moves
to 2.

### Why not simply forbid them

`extra="forbid"` exists because 91 annotation fields once accumulated unnoticed
(§2). The purpose is that the field set is *decided deliberately*, not that it
never changes. Under v1 every real row failed conformance on five fields that
were never in dispute — which does not enforce the contract, it just makes the
gate useless and trains its reader to ignore it.

Naming five known fields does not weaken the guarantee. A sixth invented field
still fails on the first row.

### Why `Optional[str]` and not enums

Their value sets were observed in **one batch**. An enum inferred from one sample
rejects legitimate values found in the next — inventing a constraint and calling
it a contract, which is the same error as inventing a quote and calling it
evidence.

`kbqa sweep --field-values` collects the real distributions estate-wide.
Constrain them in v3 from that evidence.

### Open, deliberately

**Three fields hold one value across 222 rows.** That is what an unexercised
default looks like. `vendor_category` also duplicates `canonical` — both were
`NOVEL` for every row, which is the same fact stored twice.

This is a question for the collector, not a validation failure, so it is not
resolved here. Two possibilities, and the sweep distinguishes them:

- the fields are genuinely single-valued so far, and will vary later
- they are defaults nothing ever sets, and should be removed from the collector

Until the sweep says which, forbidding them would fail real rows over an
unanswered question.

### Reversal condition

If the estate-wide sweep confirms a field never varies across any vendor,
remove it from the collector and from the contract in v3. A field that cannot
take a second value is not carrying information.

---

## D-002 · `doc:` sources currently fail G3

**Date** 2026-09-08 · **Status** OPEN — needs a ruling

`models.py` permits `source_url` of the form `doc:...`. §G3 requires every
`source_url` to appear as a `=====BEGIN=====` marker in the capture. A `doc:`
reference cannot, by construction. So a `doc:` row fails G3 today.

The three coherent resolutions:

1. **Forbid `doc:`** — every row cites a fetched page. Simplest, and consistent
   with grounding meaning "checkable against stored text".
2. **Capture `doc:` sources too** — a downloaded PDF or spec gets a capture like
   any page, and G3 works unchanged. Most faithful to the intent.
3. **Exempt `doc:` from G3** — records the citation without checking it.
   ⚠ This creates a class of row that is exempt from the only gate whose ground
   truth is the vendor's own words. Any row could then be made to pass by
   relabelling its source as `doc:`. **Not recommended.**

No default has been chosen: whichever is picked changes what a G3 PASS means,
and that is not a decision to make silently inside a gate.

---

## D-003 · Estate enforcement stays at level 3½

**Date** 2026-09-08 · **Status** decided · **Affects** deployment, not code

A private repo on a free GitHub plan cannot enforce rulesets, and the estate
must stay private. Its CI therefore reports without blocking.

§0 permits this: levels 1–3 *"make tampering visible and inconvenient, which is
enough when a human reads the verdicts."* The decision is to rely on that clause
and to build controls that keep it true:

- **G6 detects skipped checks** (`batch_unchecked`, `verdict_stale`). Placed
  inside the pinned gates, where level 4 already holds — so whoever skips a
  check cannot edit the check that notices.
- **`ci/estate-pre-push`** refuses a push on a failing sweep. Level 2,
  bypassable with `--no-verify` on purpose: skipping becomes a decision.
- **CI job summary**, so an unenforced red X is not scrolled past.

⛔ The estate is **not** tamper-proof and must not be described as such. The
accurate statement: *the gates cannot be edited; running them can be skipped;
skipping is recorded.*

### Reversal condition

**If the maker agent ever gets push access to the estate**, no human sits
between the collector and the repository, §0's clause stops holding, and this
decision must be revisited. GitHub Team (~$4/user/month) is then the cheap
answer.

---

## D-004 · Schema v3 evidence — estate-wide field distribution

> ⛔ **SUPERSEDED IN PART, 2026-09-09.** The recommendations below treated
> variety across vendors as a defect to be constrained. That is wrong, and
> acting on it would have destroyed evidence. See **D-005**, which replaces
> recommendations 1, 4 and 5. The observations remain accurate; the conclusions
> drawn from them did not.


**Date** 2026-09-09 · **Status** OPEN — needs rulings · **Evidence** `kbqa sweep --field-values` over 183 batches / 12,728 rows

D-001 typed five fields `Optional[str]` rather than as enums, reasoning that a
value set observed in ONE batch would reject the next batch's legitimate values.
The estate-wide sweep settles it — and shows that caution was right twice and
wrong once.

### Where the one-batch inference was WRONG

| field | seen in 1 batch | seen estate-wide | verdict |
|---|---|---|---|
| `vendor_category` | 1 value | **622 distinct** | free text, not an enum |
| `plan_gating` | 1 value | **133 distinct** | free text, not an enum |

Had these been frozen as single-value enums from the first batch observed, they would
now reject ~750 legitimate values. Keep them `Optional[str]`.

### Where they ARE enums, and can be constrained in v3

| field | distinct | values |
|---|---|---|
| `node_kind` | 11 | short, enum-like tokens |
| `deployment` | 8 | mostly short tokens, **plus** one free-text elaboration |
| `vendor_category_source` | 8 | method names, **plus** one free-text elaboration |

Both marked entries are free text where the others are tokens — one row
elaborating where the others classify.

⚠ Values are described, not listed. Writing down one collection's vocabulary
would anchor it as canonical, which is the error D-005 rules against.

### Two defects in fields ALREADY in the contract

**`depth_level` is being written two ways.** Observed:
`2, 3, 4, 5, 6, feature, module, product-line, sub-feature, sub-module`. Some
batches record a numeric depth, others the named level. The contract permits
only the names, so every numeric row fails G2 today. One convention has to win,
and the other has to be migrated — this is not a contract question but a
collector question.

**`evidence_grade` records `verify`; the contract expects `[verify]`.** Every
such row fails. Either the brackets are dropped from the enum or the collector
stops emitting the bare form. Trivial, but it is currently a silent source of
violations.

### The accumulation §2 warned about, in progress

**32 fields appear in rows and not in the contract. Seventeen of them hold two
or fewer distinct values across the entire estate:**

`id_prefix` · `vendor` · `round` (1a) · `region` (eu1, us1) ·
`language_count_observed` (89) · `undisclosed_amount` (True) ·
`prior_tree_mechanism` · `locale_scope` (*"en-in only — no English original"*) ·
`limit` (*"values true/false; default value true"*) · `node_count` ·
`children_enumerated` · `real_href` · `regulator` · `tagline_for` · `version` ·
`mechanism_third_party` · `batch`

Several are not fields at all but prose stuffed into a key — `limit` and
`locale_scope` hold sentences. Others are batch-level facts recorded per row:
`vendor`, `batch` and `id_prefix` belong in frontmatter, not repeated on every
row of a batch.

A separate cluster shadows two contract fields with raw and reported variants:
`mechanism_raw` (78), `mechanism_reported` (45), `mechanism_via` (148),
`outcome_raw` (179), `outcome_reported` (48). That may be deliberate provenance
— keeping the vendor's own wording alongside the normalised value is defensible
— but it is five fields carrying it, and nothing records that intent.

### What is NOT decided here

Which of the 32 are schema and which are cruft is a judgement about the data
model, not about validation. Admitting all 32 would make `extra="forbid"`
decorative; forbidding all 32 would fail most of the estate.

Recommended shape for v3, pending rulings:

1. Constrain `node_kind`, `deployment`, `vendor_category_source` as enums
2. Keep `vendor_category`, `plan_gating` as `Optional[str]` — proven free text
3. Fix `evidence_grade` to accept what the collector writes, or change the collector
4. Rule on `depth_level`: numeric or named, then migrate the other
5. Admit the `*_raw` / `*_reported` cluster **only if** its purpose is recorded here
6. Move `vendor`, `batch`, `id_prefix` to frontmatter; drop the single-value
   annotations, or name them deliberately

### Reversal condition

Re-run `kbqa sweep --field-values` after any collector change. A field that
gains a second value was real; one still at distinct=1 after another collection
round is an unexercised default and should go.

---

## D-005 · Vendor structure is evidence, not variance to be normalised

**Date** 2026-09-09 · **Status** decided in principle, implementation open
**Supersedes** D-004 recommendations 1, 4 and 5

### The correction

D-004 read 622 distinct `vendor_category` values, 133 `plan_gating`, and two
`depth_level` conventions as a data-quality problem, and proposed constraining
them. That reasoning was backwards.

Vendors differ in product structure, naming, depth and scale — genuinely, not
accidentally. A vendor with a six-level hierarchy and one with three are not two
encodings of the same tree. `vendor_category`'s 622 values are 622 real
categories that vendors actually use. Forcing them into an enum drawn from
whichever vendors we collected first would **edit the evidence to fit our
model**, and the next vendor's legitimate vocabulary would be rejected as
invalid.

§G3 already settles this for text: *never normalise spelling, because vendor
typos are evidence.* Structure is evidence by the same argument, and for the
same reason — the estate exists to record what vendors say about themselves, not
what our taxonomy can accommodate.

Read that way, several things D-004 called defects are the design working:

- **`vendor_category` (622), `plan_gating` (133)** — the vendor's own
  vocabulary, preserved. Correct as `Optional[str]`; constraining them would be
  the error.
- **`depth_level` numeric AND named** — not two conventions where one must win.
  A numeric depth records a node's position in *that vendor's own* tree; the
  named levels impose ours. The numeric form may be the more honest record for
  vendors the five-name taxonomy does not fit.
- **`mechanism_raw` / `mechanism_reported` / `mechanism_via` / `outcome_raw` /
  `outcome_reported`** — D-004 called this "shadowing" and hinted at
  accumulation. It is the opposite: the vendor's own wording kept beside our
  normalisation, each recoverable. That is verbatim preservation done properly,
  and it should be named in the contract rather than tolerated outside it.

### The real problem this exposes

`extra="forbid"` and verbatim vendor structure are in direct tension. A single
flat field set cannot be both strict enough to catch invention and open enough
to record what vendors actually publish. Today the contract loses that argument
by failing legitimate rows.

The resolution is not to relax the contract but to split it, because the two
kinds of field answer to different owners:

**Core — ours, strict, `extra="forbid"`.** Provenance and grounding: `id`,
`vendor_term`, `what_it_does`, `source_url`, `source_quote`, `access_date`,
`evidence_grade`, `confidence`, `broken_source`. These exist so a claim can be
checked. Nobody may invent a new one, and inventing one is exactly what §2
exists to catch.

**Vendor-verbatim — theirs, open, recorded not judged.** The vendor's own
taxonomy, depth, node kinds, raw mechanism and outcome wording. Namespaced
explicitly so it is visibly a different kind of field, e.g. a `vendor_fields`
mapping or a reserved prefix. Validated for *presence and type*, never for
membership of an enum we authored.

This keeps both guarantees intact. Invention is still caught — the quote must
still ground, the core is still closed. And vendor structure survives contact
with the checker, which is the point of collecting it.

### Still a genuine defect, unaffected by any of this

`evidence_grade` is **our** field with **our** enum, and rows record `verify`
where the contract says `[verify]`. That is a straightforward mismatch to fix in
one place or the other. It is not vendor structure and gets no protection from
this decision.

### Open

- Which namespace shape: nested `vendor_fields` mapping, or a reserved prefix?
- Do the ~17 single-value fields belong in the vendor namespace, or are some of
  them genuinely one-off notes that should not be fields at all? A sentence
  stored under `limit` is not obviously either.
- `vendor`, `batch`, `id_prefix` repeat a batch-level fact on every row. Harmless
  redundancy, or move to frontmatter?

None of these is a validation question. They are all questions about what the
estate is for, and they are the operator's to answer.


## D-006 · A filename is a convention; provenance is evidence

**Date:** 2026-09-13 · **Version:** 5.1.0

Discovery — in `sweep`, in `ci/estate-qa.yml`, and in the probe's verdict —
identified a collection batch by matching `_collect-*-staging.md`. The first
probe run against a real estate landed on a ruling document that carried that
name: document-control frontmatter, 745 lines of prose, zero rows.

Three things followed from that, all of them wrong:

1. The estate totals counted it as a batch, so every figure derived from them
   was inflated by an unknown amount.
2. CI would run G1–G3 against it and report failures about a file nobody had
   ever collected into.
3. The probe reported `parser DOES NOT MATCH`, sending the reader to
   `parsing.py` to correct something that was not wrong.

**Ruling.** A file is a batch when it declares batch frontmatter — any of
`batch`, `source_capture`, `source_capture_sha256`, `pages`,
`fetched_by_this_agent` — **or** holds rows. A file with neither is classified
`not-a-batch`: excluded from every total, and named in the report and the
terminal summary rather than silently dropped.

Rows without provenance remain a batch. That is a G1 finding about missing
provenance, owned by a different gate, and the sweep pre-empting it would be
the same category error in the other direction.

**Evidence.** One estate file, probed 2026-09-13: frontmatter keys `code`,
`nature`, `stage`, `type`, `status`, `read_when`, `rule`, `ruling`, `owner`,
`last_updated`; 943 lines; 0 rows parsed; 0 naive matches.

**Reversal condition.** If a collector emits batches carrying none of those
keys and no rows — an empty batch with a bare name — this rule would classify a
real batch as a document. `zero_rows` already treats an empty batch as a defect,
so such a file should not exist; if one legitimately does, identification must
move to an explicit marker the collector writes.


## D-007 · The checker stores structure, never identity

**Date:** 2026-09-13 · **Version:** 6.0.0

The tool is a structural and schema check. Whether a quote is verbatim on the
page it cites, whether a row satisfies the contract, whether an index item is
covered — none of these depend on who the subject is, and no gate reads a
subject name. `--vendor` existed only to label a log line.

That made the QA layer a second place identity accumulates, in exactly the
artifacts most likely to travel: a verdict pasted into a message, a report
attached to a review, a log shipped with a bug. The estate is private; its QA
sidecar should not quietly become a roster of who is in it.

**Ruling.** The checker stores no subject name. `--vendor` is removed, and
rejected rather than ignored — a caller who keeps passing it is entitled to
learn it no longer means anything.

**What identity necessarily remains, and why.** A remediation report must name
the row and the page that failed, or it cannot be acted on. Findings therefore
carry `id`s and URLs, and verdicts carry the paths of their inputs. These are
the estate's own filesystem and its own rows, inside the estate. The rule is
not that identity never appears — it is that the checker never keeps a
**separate copy** of it, and that anything designed to leave the estate carries
none. `probe` is the artifact designed to travel, and D-006's companion fix
made it structural-only.

**Reversal condition.** If a gate is ever written whose check genuinely depends
on the subject's identity — none is foreseen, since identity is not a
structural property — this rule would have to be revisited rather than worked
around by re-adding a metadata field.


## D-008 · A source must be re-fetchable by someone who does not trust us

**Date:** 2026-09-13 · **Version:** 6.1.0

`CoreRow.source_url` accepted `doc:` references. §G3 requires every
`source_url` to appear as a BEGIN marker in the capture, and a `doc:` reference
by construction never can — so every such row failed G3 while looking like a
legitimate citation. The failure was the lesser problem. The obvious remedy —
exempting `doc:` from G3 — would have created a class of claim nobody outside
the collecting session can check, which is the single thing the contract exists
to prevent.

**Ruling.** `source_url` must begin `http://` or `https://`. There is no
unfetchable reference class. An internal document is not exempt from evidence:
it is captured like any other page, and cited by whatever stable URL serves it.

**Evidence.** The one verifiable batch probed on 2026-09-13 carried 221 rows
across 22 distinct `source_url` values, every one an `http(s)` URL, against a
capture of 23 balanced page blocks. No row in the estate's checkable corpus
relies on the permission being removed.

**Cost.** Any existing row citing `doc:` now fails G2 rather than G3. That is
the correct place for it to fail — the citation is malformed, not ungrounded —
and such a row must be re-sourced against a captured page.

**Reversal condition.** If a subject publishes material that is genuinely
retrievable but not over HTTP, the rule needs a new scheme with a **capture
mechanism attached**, never an exemption from grounding.


## D-009 · Discovery patterns are inferred until a corpus contradicts them

**Date:** 2026-09-15 · **Version:** 6.3.0

`Conventions.denominator_glob` was `_denominator-*.md`, taken from the shape of
the other Bronze artifacts (`_capture-<batch>.raw.txt`,
`_robots-<host>-<date>.txt`) rather than from any observation. The collecting
regime's own instruction is *"Write `_denominator.md`"* — no suffix.

**Measured, 2026-09-15**, across one estate's live subjects:

| filename | count |
|---|---|
| `_denominator.md` | 18 |
| `_denominator-<surface>-<date>.md` | 1 |
| `_denominator-<surface>.md` | 1 |

The glob matched 2 of 20. Because G4 only runs when a denominator is supplied,
18 of 19 subjects had **no coverage check at all**, and the report said so in
the Coverage section — accurately, quietly, and in the place a reader skims.

**Ruling.** The glob is `_denominator*.md`. It still excludes
`_denominator.md.superseded-<date>` tombstones and files without the leading
underscore.

**Why this keeps happening.** This is the fourth defect of the same shape: a
pattern invented from a specification or a single sample, then applied as law —
after the id pattern rejecting `_`, the id pattern requiring two segments, and
the staging discovery matching on filename alone (D-006). The lesson is not
"widen the patterns". It is that a convention this package asserts about someone
else's files is a hypothesis until a corpus confirms it, and the cost of a wrong
one is silence rather than an error.

**Reversal condition.** If a corpus emerges where `_denominator*.md` matches a
file that is not a denominator, discovery must move to content — a declared key
inside the file — rather than to a narrower name.


## D-010 · Exhaustion must be evidenced, not inferred from a short return

**Date:** 2026-09-16 · **Version:** 6.4.0

Large surfaces — an alphabetical feature list running to hundreds of items —
cannot be collected in one pass; the run is killed partway and what it finished
is unknowable from the output. The answer is windows: ask for twenty, save what
comes back, ask for the next twenty, and stop when a window returns nothing.

That protocol has a property worth checking. **A window returning fewer items
than requested is not proof the list ended.** Fifteen returned against twenty
asked is equally consistent with:

- the list genuinely ending at fifteen,
- a run that stopped early because the task was long,
- a fetch that failed partway and reported what it had.

Only a subsequent window returning **zero** separates the first from the others,
and only if it is recorded. An unrecorded probe is a memory, not evidence.

**Ruling.** Where a subject has a captured denominator, G4 measures coverage
against it as before — that remains the preferred answer, because an index is a
statement by the subject about what exists, and a window count is a statement by
us about what we received. Where no index is published, a batch may declare
`window_requested` and `window_returned`, and the subject is complete only when
some window returned 0.

**The cross-check.** `window_returned` counts items the source returned; the
gate counts rows in the batch itself. Fewer rows than items returned means items
came back that no row records — the signature of a truncated write. Neither side
computes both numbers, which is what keeps this from being arithmetic about
itself (the tautology principle, D-003).

The check is one-directional on purpose: rows exceeding items returned is
normal, since one index item can yield several rows.

**Also changed:** a G4 run with neither a denominator nor windows now FAILs with
`completeness_unassessable` instead of not running. Previously it surfaced as a
Coverage line — accurate, quiet, and in the place a reader skims. That is the
same failure shape as D-009, and it is worth stating as a rule: **when this
package cannot assess something, it says so loudly rather than staying silent.**
Silence and success must never render identically.

**Reversal condition.** If a surface emerges where a zero-return is impossible
to obtain — an endpoint that errors rather than returning empty — the terminal
condition needs a second recordable form (a recorded error at offset N), not an
exemption from evidencing exhaustion.


## D-011 · A window declares why it ended, because a count cannot

**Date:** 2026-09-16 · **Version:** 6.5.0 · **Supersedes part of D-010**

D-010 treated a zero-return as the evidence of exhaustion. Correct as far as it
went, and too weak for the case that motivated it.

A collector working a five-thousand-item index must stop **before** it is
killed, not when the list ends. So the ordinary healthy outcome is a window that
returns everything it asked for and then stops anyway. And a window returning 12
of 20 requested carries no information about which happened:

- the source had 12 and the list is finished, or
- the collector took 12 and stopped while still healthy, or
- the fetch failed partway and reported what it had.

Three situations, three different next actions, one number.

**Ruling.** A window declares `window_end`: `exhausted`, `budget`, or `error`.
A subject is complete only when some window reports `exhausted` — never on a
budget stop, however clean the sequence looks. `exhausted` may be written only
after asking again and receiving nothing; inferring it from a short return is
the specific failure this field exists to prevent.

**Parked is a legitimate state.** A subject whose last window stopped on budget
is incomplete, and reported as such with an offset to resume from — not as a
failure of collection. The collector that stops while healthy is doing better
than the one that dies trying to finish, and the report says so, because a
finding that reads as blame for correct behaviour teaches the collector to hide
it.

**On window size.** The package has no opinion, and should not: the binding
constraint is bytes captured, not items seen, and it varies by subject. A fixed
number in a contract would be exactly the kind of invented constant that
produced D-006 and D-009. What is checked is that whatever was used is recorded.

**Reversal condition.** If a surface cannot produce an empty response —
erroring instead at the end of the list — `error` at a known offset would need
promoting to a second terminal form. It is not one today: an errored window is
unattempted, not finished.


## D-012 · An audit names what it did not look at

**Date:** 2026-09-16 · **Version:** 6.6.0

`sweep` discovers batches by staging file and sorts them into three tiers. It
never looked at `feature-tree.md`. On the estate it was built to audit that
meant:

| artifact | directories holding one |
|---|---|
| `feature-tree*.md` | 63 |
| `_collect-*-staging.md` | 11 |
| `_capture-*.raw.txt` | 2 |

The audit reported 178 batches, 12,728 rows and "15% verifiable" — all true of
the 11, and silent about the other 52 subjects. A reader would take those
percentages as describing the corpus.

**Ruling.** A subject holding a tree with no staging file anywhere is counted,
named in the report, and printed in the terminal summary as `NO BATCH`. It is
kept out of the tier figures: the tiers answer *how checkable is this batch*,
and a subject with no batch is not a badly-checkable batch — it is a different
question, and blending them would produce a number meaning neither.

**Why it is worse than `unverifiable-no-capture`, despite sounding similar.** An
unverifiable batch has a staging file whose rows cite pages; the trail exists
and a re-fetch can restore it. Rows that exist only in a merged tree never
passed through a capture, and `G6` checks such a tree's `proof:` count against
its own contents — self-consistency, not grounding.

**The pattern, stated for the fifth time.** D-006 (discovery by filename),
D-009 (a glob matching 2 files in 20), D-010 (`completeness_unassessable`),
D-011 (a short return read as the end of a list), and now this. Every one is the
same defect: **something this package could not see rendered identically to
something it had checked and found clean.** The rule is not "add more checks" —
it is that any scope this package draws around itself must be stated in its own
output.

**Reversal condition.** If an estate legitimately keeps trees and batches in
separate directory structures, subject attribution by path depth would flag
every subject. Attribution would then need to move to a declared key inside the
tree rather than to its location.


## D-013 · The subject's words are frozen; our reading is not

**Date:** 2026-09-16 · **Version:** 6.9.0

Every gate so far answers *is this claim grounded*. None answers *did we edit
the evidence while interpreting it* — and the mapping round is where that
pressure is highest. Two terms that nearly match map more cleanly if one is
tidied first, and the edit is invisible downstream: the row parses, conforms,
and its quote still matches the capture, because the quote is not what changed.

**Ruling.** A profile declares `verbatim_fields` — the fields that are the
subject's own words. `kbqa freeze` fingerprints them and compares across a pass.

For the catalogue profile that is `id`, `source_url`, `source_quote`,
`access_date`, `vendor_term`, `parent_path`. `vendor_term` is what the subject
calls the thing; `parent_path` is where the subject puts it. Both are evidence
of how the subject organises itself, which is the difference this programme
exists to preserve.

**What is deliberately NOT frozen**: `canonical`, `canonical_label`,
`confidence`, `mechanism`, `outcome`, `evidence_grade`. Those are our reading.
Freezing the whole row would block the round this exists to protect, and a
guard that prevents the work is not a guard.

**Why it is a profile field and not a constant.** A domain whose hierarchy is
our analytical frame rather than the subject's would freeze a different set.
Hardcoding it in `freeze.py` would bake one programme's shape into the
machinery — the thing the three-layer contract exists to prevent.

**Two limits, stated so the snapshot is not over-read.** It compares a corpus
against its own earlier self: a term already wrong when frozen is certified only
as untouched since. And a drifted row must be restored from version control,
never re-frozen — re-freezing records the edit as the new truth, which is the
single thing the command exists to prevent.

**Reversal condition.** If a subject legitimately republishes under a new name
and the corpus should follow, that is a re-collection producing new rows with a
new `access_date`, not an edit to frozen ones. If that becomes common enough to
be burdensome, the answer is a superseding-row mechanism — never relaxing the
freeze.
