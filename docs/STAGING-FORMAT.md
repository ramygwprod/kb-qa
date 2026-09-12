---
code:    Staging-Format
type:    confirmed against the estate, 2026-09-09
status:  current
---

# On-disk formats the gates read

The formats below were **inferred from the specification in v1 and corrected
against the real estate in v2 and v3.** Each correction is recorded here because
the inferences were wrong in ways worth remembering — every one produced
findings that were untrue of the data.

## Three row serialisations, not one

The estate contains all three, written by different collector eras. The parser
reads each and records which it found in `row_format`; a silent fallback between
formats is how a parser starts disagreeing with the file it claims to have read.

| format | shape | naive cross-check |
|---|---|---|
| `jsonl` | one object per line at column 0 | `^{"id"` |
| `fenced-array` | a pretty-printed JSON array inside a ```` ```json ```` fence | `^\s*"id":` |
| `fenced-jsonl` | one object per line **inside** a fence | `^{"id"` |

The specification describes only the first. **The second and third are what the
collector actually writes**, and the third cost 181 real rows: the fence body is
not valid JSON as a whole, so `json.loads` failed with "Extra data" and the
batch was reported as zero rows — silently, on batches that had captures and
could therefore be grounded.

§G2's naive cross-check is **per format**. `^{"id"` counts nothing in a
pretty-printed array and `^\s*"id":` counts nothing in JSONL, so the wrong
pattern would fail a batch for a reason untrue of it.

## Frontmatter

A minimal YAML subset — deliberately not a full parser, because a permissive one
would accept files the contract does not. It reads:

- `key: value`
- `key:` followed by `  - item` list entries
- **`key:` with indented continuation lines** — a folded scalar. Real collector
  frontmatter uses these for prose. Rejecting them made the whole frontmatter
  unparseable, which cascaded into false `no_declared_pages` and
  `capture_hash_absent` findings on batches whose frontmatter was fine.

Observed key sets differ between collector eras — `code, nature, stage, entity,
type, status, last_updated` in one, `code, entity, batch, scope, access_date,
status, capture_file` in another. Neither carries `source_capture_sha256`, which
§G1 requires; that gap is real and belongs to the collector.

## The per-page declaration

§G1 checks that what was cited is what was fetched. Two conventions exist, and
both are read:

- a frontmatter `pages:` list
- **a markdown table** whose first cell is the page URL

Reading only the first reported `no_declared_pages` against batches that declare
their pages perfectly well in a table — sending a maker hunting for a list that
was never that batch's convention. `pages_source` in the verdict records which
was found.

Row `source_url`s inside a ```` ```json ```` fence are excluded: a citation is
not a declaration, and counting one would make the declaration agree with the
rows by construction.

## Captures without page markers

Some captures hold the page text but no `=====BEGIN <url>=====` markers at all —
8 pages concatenated as markdown across 1,800 lines, with nothing recording
where one ends and the next begins.

Those rows are **unassessable, not ungrounded**. Grounding is impossible rather
than failing, and G3 reports one structural finding rather than one
`url_not_in_capture` per row. It is deliberately *not* degraded to whole-capture
matching: §G3 scopes to the row's own page precisely so a quote lifted from
another page cannot pass.

Recoverable — re-fetching with a marker-writing fetcher moves those rows into
the verifiable tier without re-collecting any of them.

## Confirming the format without disclosing the data

There is an obvious way to settle this and a correct one. The obvious way is to
show the checker a real staging file, which forfeits the independence the whole
design rests on: a checker that has read the collector's output is no longer
independent of it.

Instead, run the probe against a real file and share **its output**:

```bash
python -m kbqa probe --staging <real staging file> --capture <its capture>
```

It reports field *names*, value *types*, string *lengths*, marker *syntax*, and
whether the shipped parser agrees with the file. It does not report quotes,
URLs, vendor terms, or any free-text value — that boundary is enforced by tests
in `tests/test_probe.py`, which fail if row content reaches the report.

The last line is the answer:

```
VERDICT: parser MATCHES this file
VERDICT: parser DOES NOT MATCH this file
```

On a mismatch, the sections above it say where — a missing `---`, a different
marker syntax, fields outside the contract, rows that do not parse. That is
enough to correct `parsing.py` without anyone having read a row.

## `_collect-<batch>-staging.md` (SILVER)

As the collector writes it — fenced JSONL with a markdown-table page
declaration. The other two serialisations are equally valid; see above.

```
---
code: EX-1a
entity: <vendor>
batch: guides
scope: The 8 guide pages under
  https://docs.example.test/guides/, fetched as .md.
  Fixed URL list, no link-following.
access_date: 2026-08-23
status: draft
capture_file: _capture-guides.raw.txt
---

# <vendor> — guides batch

## Per-page declaration

| page | items emitted | complete? |
|---|---|---|
| https://docs.example.test/guides/a | 14 | yes |
| https://docs.example.test/guides/b | 18 | yes |

```json
{"id": "vendor.guides.a", "vendor_term": "…", …}
{"id": "vendor.guides.b", "vendor_term": "…", …}
```
```

Rules the parser enforces:

- **`id` serialises first** in the line-per-object formats. A row starting with
  another key is invisible to §G2's naive count, and G2 FAILs on
  parser/naive divergence — which is what makes the cross-check meaningful.
- `id` is a lowercase dotted path. Underscores are allowed and a single segment
  is valid; v1 permitted `-` but not `_`, which cost 857 rows over an arbitrary
  distinction, and required two segments, which cost another 47 top-level nodes.
- `depth_level` accepts the named levels **or** the vendor's own numeric depth,
  as an integer or a string. Some hierarchies do not fit five names.
- Fields outside the core contract must be registered in `vendor_fields.py` by
  name. Their values are never constrained — see docs/DECISIONS.md D-005.

## `_capture-<batch>.raw.txt` (BRONZE, immutable)

```
=====BEGIN https://docs.acme.test/widgets/overview=====
…verbatim page text, typos and all…
=====END https://docs.acme.test/widgets/overview=====
```

Marker lines are excluded from the block text: a quote must be found in the
vendor's own words, not in scaffolding we wrote.

## `_denominator-<surface>-<date>.md` (BRONZE, immutable)

Markdown links, one index item per line. Bare URLs on their own line also count,
and take their label from the last path segment.

```
- [Widgets Overview](https://docs.acme.test/widgets/overview)
- [Syntax Reference](https://docs.acme.test/widgets/syntax-reference)
```

## `_stop-conditions.md` (SILVER)

Keyed by URL **or** label. The separator is a colon followed by whitespace —
never the colon in `https://`.

```
- https://docs.acme.test/widgets/never-fetched: 404 at fetch time on 2026-08-23
- Legacy Widgets: superseded, vendor removed the page
```

A stop-condition without a reason FAILs G4. "We stopped" is not a reason.

## `feature-tree.md` (GOLD)

Frontmatter carries a `proof:` line containing the row count. G6 FAILs when the
claimed count disagrees with the file's own content.

```
---
vendor: Acme
proof: 2 rows
---
```

## Open questions for the operator

Questions 1 and 2 from earlier drafts are **answered**: the estate contains
three row serialisations (all read), and the per-page declaration appears as
either a frontmatter `pages:` list or a markdown table (both read). What remains:

1. ~~**`doc:` sources.**~~ **Closed 2026-09-13 by D-008** — `source_url` must
   be an `http(s)` URL. An internal document is captured like any other page
   and cited by the URL it was served from. Exempting a class of row from G3
   would have created claims nobody can check, which is the one thing the
   contract exists to prevent.

2. **`proof:` format.** Does it carry a bare integer, or a longer string with
   the count embedded? G6 currently extracts the first integer it finds.

3. **Two §G1 requirements the collector does not emit.** Neither can be supplied
   by the checker: computing them here would make G1's check a tautology that
   always passes.
   - `source_capture_sha256` in frontmatter — G1 asks whether the rows were
     written from the capture now on disk. Derive it at check time and the
     answer is always yes.
   - a per-page declaration on batches that have neither convention — G1 asks
     whether what was cited is what was *intended to be fetched*. Derive it from
     the capture's own markers and the capture merely matches itself.

4. **Nine annotation fields** (`duplicate_note`, `id_collision_with`,
   `contradiction`, `source_typo`…) each record something real, but nine
   separate "something was odd here" fields is the §2 accumulation pattern in
   miniature. Candidates for consolidation into one structured field.
