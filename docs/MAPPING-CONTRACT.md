# The mapping layer

**Status: ruled 2026-09-16 by the collection regime, on evidence measured
against the estate. The keying overturns this document's first proposal —
see "Keyed on `id`".**

kbqa's side of a decision owned by the collection regime: where mapping
statements live, what shape they take, and what this package will and will not
check about them.

## The problem it answers

`canonical` is a field on the row. That makes a mapping an attribute of the
subject's concept — and produces exactly the state one estate is now in:

- **1,014 rows** already carry a `canonical` tag written by an unidentified
  process, and **4,712** carry `canonical_label`, a field the schema defines no
  relationship for.
- `NOVEL` means *not yet mapped*, but nothing distinguishes *not yet examined*
  from *examined and genuinely unique*. Halfway through a mapping round, a
  stalled pass and a finished one produce the same number.
- Re-mapping means rewriting rows — the artifacts whose defining property is
  that they are never rewritten.

[SKOS](https://www.w3.org/TR/skos-reference/) draws the line the current shape
crosses: semantic relations hold **within** a concept scheme, mapping properties
link **between** schemes. Each subject's vocabulary is its own scheme. The
standard is a different scheme. A mapping is a link between two vocabularies,
not a property of one concept in one of them.

## The shape — ruled

One statement per line, appended, never rewritten in place. The namespace is
**estate-wide** — a category spans subjects, so coverage has one answer, not 64
— while the files are **sharded one per subject**, because one writer per file
is a standing constraint and a single estate-wide file is one nobody reads.
`kbqa mappings --file <f> [<f> …]` takes them all and reports one number.

```json
{
  "id": "<the row's id>",
  "scheme": "<which standard this maps into>",
  "status": "mapped",
  "concept": "<id in that standard>",
  "relation": "broadMatch",
  "date": "2026-09-16",
  "by": "<who decided>",
  "note": "<why — the observation, not the conclusion>"
}
```

### Keyed on `id`, not on the term

This document first proposed keying on `vendor_term` — map a term once, cover
every row using it. **Measured against a real corpus, that folds 81% of it.**

| | |
|---|---|
| `(subject, term)` pairs carrying more than one row | 9,238, covering **22,517 rows** |
| terms appearing in more than one subject | 434, one spanning **43 subjects** |
| distinct ids in the merged tree layer | 12,804 of 12,804 — **exactly unique** |

Rows sharing a term are not thereby the same concept. Bundles repeat a term on
purpose — which is exactly what `g5_bundles` reports and deliberately refuses to
resolve: *"a repeated name is an R2 question for a human. A `usecase_of` guessed
from string similarity is indistinguishable later from a sourced one, so this
gate never writes one."* Keying on the name would have done by schema what that
gate refuses to do by inference.

**Group by term to review; record per id.** The efficiency is in how a human
reads the work, not in what gets written down.

### Anchored to the merged layer

Ids are unique in the merged trees. They are **not** unique once staging is
unioned back in, and in 126 `(subject, id)` pairs the rows disagree on the
subject's own words depending on which layer you read — 49 differing on
`vendor_term`, 119 on `source_url`. That is the ambiguity keying on `id` was
chosen to avoid, arriving through the back door.

So a mapping statement attaches to a **merged** row. Staging is consulted for
membership only, which is safe. An id that exists only in staging is
`unexamined` until it merges, which is true regardless — and `kbqa mappings`
says so rather than accepting the statement.

The 126 are also a latent merge collision in their own right, reported by
`kbqa mappings --root` whether or not any statement touches one.

### `status` is not a relation

*Examined and genuinely unmatched* is the absence of a semantic link plus a
recorded review state. Encoding it as a sixth SKOS relation would make a
non-relation into a relation, which is why SKOS leaves it out.

| status | means |
|---|---|
| `unexamined` | nobody has looked |
| `examined-no-match` | looked, and not even a broader concept fits |
| `mapped` | a relation and a concept are recorded |

This also retires the `NOVEL` conflation without touching `canonical`: remaining
work is the count of `unexamined`, which falls monotonically, so a stalled pass
stops looking like a finished one.

Because `broadMatch` covers the ordinary "unique but related" case,
`examined-no-match` is a rare claim — and one asserted without a reason is where
*hard to classify* quietly becomes *unique*. It requires a note.

### `canonical` is read-only in rows, in every round

R1a leaves it. R2 does not write it either. Writing a mapping into the row *is*
an edit to the row, so in-row writes and the additive discipline cannot both
hold — and `kbqa freeze` would correctly report the write as drift.

### The relations

| relation | means | when |
|---|---|---|
| `exactMatch` | interchangeable across applications | the strong claim — the spec says use it sparingly |
| `closeMatch` | interchangeable in some applications | the honest default when the fit is good, not perfect |
| `broadMatch` | the standard concept is broader | **a unique feature that still relates to a category** |
| `narrowMatch` | the standard concept is narrower | the subject splits what the standard lumps |
| `relatedMatch` | associated, neither broader nor narrower | weakens comparison; use rarely and say why |

`broadMatch` is what makes "there may be unique features, but each still relates
to at least one standard category" expressible. Unique stops being an absence of
mapping and becomes a **kind** of mapping — which is what stops *unique* from
becoming a parking space for anything hard to classify, the way `unknown`
avoidance works one layer down.

## What kbqa would check

**Already built — `kbqa freeze`.** Records a fingerprint of the fields that are
the subject's own words, and compares after a mapping pass. Which fields those
are comes from `Profile.verbatim_fields`, not a constant: for a product
catalogue that is `id`, `source_url`, `source_quote`, `access_date`,
`vendor_term`, `parent_path`. Our reading — `canonical`, `confidence`,
`mechanism`, `outcome`, `evidence_grade` — stays revisable, or mapping would be
impossible.

```bash
kbqa freeze --root <estate> --out _qa/verbatim.freeze.json
# … mapping pass …
kbqa freeze --root <estate> --check _qa/verbatim.freeze.json
```

A changed or disappeared row fails. An appeared row is reported and does not,
because collection legitimately adds rows.

**Built — `kbqa mappings --file <f> [--root <estate>]`.** Checks that the file
is well-formed:

- `status: mapped` names a `concept` and a `relation` from the SKOS vocabulary
- `status: examined-no-match` names no concept and carries a `note` saying why
  no broader concept fits
- every `id` exists in the corpus — a statement about a row nobody holds is a
  statement about nothing, and a typo otherwise sits there looking like coverage
- no `id` carries two mappings to different concepts in one scheme without
  distinct dates: a revision is legitimate, a tie says nothing
- coverage: rows with a statement against rows in the corpus, and the count per
  status — the number that says whether a pass stalled

## What this does not solve

**Nothing checks that a mapping is correct.** `freeze` proves the words were not
edited; a mapping check would prove the record is well-formed. Whether
`broadMatch` was the right relation is judgement, and it stays judgement — the
same honest limit as G3, which proves a quote is real and cannot prove it
supports the claim.

**Quarantine is a property of the scheme, not of each record.** It is orthogonal
to `mapping_status`, which is monotonic review progress: a quarantined mapping
might be `unexamined` or fully `mapped`, and making quarantine a status would
erase whichever review state it replaced — losing information at the moment of
quarantining. Mark the scheme once in a register; every record carrying it
inherits the mark, and un-quarantining is one line rather than 1,014 edits.

**The pre-existing tags are not resolved by this**, only quarantined. Under this
shape they become one dated mapping set attributable to whatever wrote them,
reviewable on their own terms rather than indistinguishable from new work. That
is strictly better than the current state and is not the same as knowing what
they mean.

## Why this is worth the change

It makes the rule that already governs everything else structural instead of
remembered: **the subject's words are evidence and ours to preserve; the mapping
is our reading and ours to revise.** Today that separation is a promise. Put the
mapping in its own file and it becomes a fact about where the data lives — and
`freeze` makes breaking it detectable rather than invisible.


## The prior `canonical` values — quarantine, do not delete

The 1,014 existing tags were traced to a scheme documented in the estate's own
archive: `NOVEL` · `C#.M#` · `EA1–EA8`. The registry is **WideBot's own product
map**, still live in `widebot-own/`. Of 34 distinct tags in use, 19 are named
there and 15 are named nowhere.

So those values are not merely unprovenanced — they map competitors into *our*
module codes, which is the inversion `field-schema.md` forbids: we never invent
a list for a subject to match. That is the same error as a denominator taken
from our expectations rather than the subject's index, one layer up.

Per-row origin is unrecoverable: no `mapped_by`, no `mapped_date`. The only date
present is `access_date`, which records when the *page* was fetched.

**Move them to a mapping file keyed by `id`**, stamped `scheme: widebot-C-M`,
`status: quarantined`, dated, origin recorded as unrecoverable. Do not delete —
15 tags have no registry anywhere, so deleting destroys their only trace.

`quarantined` is not in the status vocabulary above and should not be: it
describes a *scheme*, not a review state. Carry it as a scheme-level attribute,
or simply use a scheme name nothing maps into going forward.

## What R2's standard must not be

Ruled 2026-09-16 by the programme owner: **the prior scheme carries a wrong
information architecture and invented names. Nothing relies on it.**

That makes the 1,014 tags more than a wrong denominator. A category name that
was invented is the same defect as a quote that was invented, one layer up — and
it is the first confirmed invention in this corpus. It did not come from a
subject. It came from us.

The direction of learning is the point and it runs one way:

> **We study the giants to improve our products.**

So our own product map is an *output* of the analysis, never an input to it.
Mapping competitors into our module codes runs the arrow backwards: it measures
the market against what we happen to sell, and a feature we have no code for
becomes invisible rather than interesting. The whole value of the exercise is
the features we would not have thought to look for.

A standard built from the giants' own published vocabulary measures them against
the market. Where our products sit in that standard is then a finding — possibly
an uncomfortable one, which is the sort worth having.

**Operationally:** keep the quarantined set as a trace, since 15 of its 34 tags
exist nowhere else. Map nothing into it. Do not seed R2's standard from it, and
do not use it to decide what a category should be called — the names are exactly
what is in question.
