---
code:    Staging-Format
type:    inferred contract — NEEDS OPERATOR CONFIRMATION
status:  draft, 2026-08-25
---

# On-disk formats the gates read

⚠ **The staging format below is INFERRED from the spec, not observed.** This
session was built with no access to the data estate, deliberately, so that the
checker's definition of correct comes from `_QA-ARCHITECTURE-SPEC.md` and not
from the collector's output.

If the real collector writes something different, **this document and
`src/kbqa/parsing.py` change — the gate logic does not.** The gates are written
against parsed structures, not against bytes.

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

## What the inference rests on

| Inference | Evidence in the spec |
|---|---|
| Rows are JSON, one per line | §G2 cross-check `grep -c '^{"id"'` |
| `id` is the FIRST key in each row | same — `^{"id"` anchors at column 0 |
| Frontmatter is YAML-ish, `---` delimited | §G1 "staging frontmatter `source_capture_sha256`" |
| Pages are declared in frontmatter | §G1 "the staging per-page declaration" |
| Attestation lives in frontmatter | §G6 "staging file whose `fetched_by_this_agent` attestation is true" |

## `_collect-<batch>-staging.md` (SILVER)

```
---
batch: widgets
vendor: Acme
source_capture: _capture-widgets.raw.txt
source_capture_sha256: 9f2c…64 hex chars…
pages:
  - https://docs.acme.test/widgets/overview
  - https://docs.acme.test/widgets/syntax-reference
fetched_by_this_agent: false
---

# Free prose is allowed here and ignored by the parser.

{"id": "acme.widgets", "schema_version": 1, …}
{"id": "acme.widgets.syntax", "schema_version": 1, …}
```

Rules the parser enforces:

- **`id` must serialise first.** A row starting with any other key is invisible
  to the naive count, and G2 FAILs on parser/naive divergence. This is
  deliberate: it makes the cross-check meaningful.
- Row lines start at **column 0**. Indented JSON is not a row.
- The frontmatter parser is a deliberately small YAML subset — `key: value` and
  `key:` followed by `  - item`. A permissive YAML parser would accept files the
  contract does not.

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

1. Is the row serialisation actually JSONL-in-markdown, or a table?
2. Is `pages:` the real name of the per-page declaration G1 checks?
3. §G3 requires every row's `source_url` to appear as a BEGIN marker. `models.py`
   permits `doc:` references, which by definition cannot be in a capture. Today a
   `doc:` row **FAILs G3**. Is that intended, or should `doc:` rows be exempt?
4. Does `proof:` carry a bare integer, or a longer string the count is embedded in?
