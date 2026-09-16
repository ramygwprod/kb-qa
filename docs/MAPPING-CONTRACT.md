# The mapping layer — a proposal

**Status: proposed, not ruled.** This is kbqa's side of a decision that belongs
to the collection regime. It describes a shape kbqa can check and says what it
would check, so the proposal can be argued with rather than described.

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

## The shape

One record per mapping, appended, never rewritten in place:

```json
{
  "subject": "<subject key>",
  "vendor_term": "<the subject's own words, byte-identical to the rows>",
  "standard_concept": "<id in the standard>",
  "relation": "exactMatch",
  "by": "<who decided>",
  "date": "2026-09-16",
  "evidence": "<why — the observation, not the conclusion>"
}
```

**Map terms, not rows.** One batch carried 221 rows across 202 distinct
`vendor_term`s, and across a corpus the ratio collapses much further: the same
term recurs in every row that mentions it. Mapping a term once covers every row
using it, which is the difference between tens of thousands of decisions and a
few thousand.

**`relation` comes from SKOS**, and the vocabulary is the point rather than
decoration:

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

**Hub, not pairwise.** [ISO 25964-2](https://www.iso.org/standard/53658.html)
contrasts *hub* and *direct-linked* models. Every subject maps to the standard;
no subject maps to another subject. Across 64 subjects, direct-linked would mean
maintaining N² crosswalks and no two of them agreeing.

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

**Not built, pending this proposal being ruled on** — a check over the mapping
file itself:

- every mapping names a `relation` from the vocabulary and a non-empty
  `evidence`
- every `vendor_term` in a mapping exists **byte-identically** in the rows;
  a mapping whose term has been tidied to fit is the fold, spelled differently
- no term carries two mappings to different concepts without both being dated,
  so a revision is visible as a revision
- coverage: how many distinct terms are mapped, how many unmapped — the number
  that tells you whether a pass stalled

## What this does not solve

**Nothing checks that a mapping is correct.** `freeze` proves the words were not
edited; a mapping check would prove the record is well-formed. Whether
`broadMatch` was the right relation is judgement, and it stays judgement — the
same honest limit as G3, which proves a quote is real and cannot prove it
supports the claim.

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
