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

## Five row shapes, not one

The estate contains all of them, written by different collector eras. The parser
reads each and records which container it found in `row_format`; a silent
fallback between formats is how a parser starts disagreeing with the file it
claims to have read.

| `row_format` | shape |
|---|---|
| `jsonl` | one object per line at column 0 |
| `fenced-array` | a pretty-printed JSON array inside a ```` ```json ```` fence |
| `fenced-jsonl` | one object per line **inside** a fence |

Within any of those, two **writing styles** are read, in a fence or out of one:

| style | shape | what used to happen |
|---|---|---|
| trailing comma | `{"id": …},` — an array written one object per line | `json.loads` read the object, met the comma, and reported *"Extra data"*. 905 real rows |
| multi-line object | `{` alone, then the fields, then `}` | the opening brace parsed alone failed with *"Expecting property name"* at column 2. 57 real rows |

Rows are accumulated by **brace depth** rather than by line, tracking strings and
escapes so a brace inside a quote does not end an object, and a single trailing
comma is stripped before decoding.

The reader for a block is chosen **before** parsing, by majority vote: where most
objects close on their own line it stays line-at-a-time, so one corrupt row costs
one row. Accumulating unconditionally would let a single unclosed object swallow
every good row after it.

The specification describes only the first. **The second and third are what the
collector actually writes**, and the third cost 181 real rows: the fence body is
not valid JSON as a whole, so `json.loads` failed with "Extra data" and the
batch was reported as zero rows — silently, on batches that had captures and
could therefore be grounded.

§G2's naive cross-check is **one count for every format** (v6.15.0): every
`"id":` key in the row region — inside the ```` ```json ```` fences, or after the
frontmatter when there is no fence — at any position on a line. A `\"id\":`
escaped inside a string value is not a key and is not counted. Until v6.14.1 the
count was chosen per format (`^{"id"` or `^\s*"id":`), and an array written one
object per line inside a fence matched neither, so correctly parsed rows read as
"naive count 0" and failed G2 for a reason untrue of them.

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

- **`id` serialises first.** For a batch named under the current convention
  (`<surface>-<YYYY-MM-DD>[-wNN]`) G2 reports a row that starts with another key
  as `id_not_first_key`; a legacy-named batch is not held to it, and the verdict
  says the strict rules were not applied. The naive count itself no longer
  depends on key order.
- `id` is a lowercase dotted path. Underscores are allowed and a single segment
  is valid; v1 permitted `-` but not `_`, which cost 857 rows over an arbitrary
  distinction, and required two segments, which cost another 47 top-level nodes.
- `depth_level` accepts the named levels **or** the vendor's own numeric depth,
  as an integer or a string. Some hierarchies do not fit five names. It accepts
  `unknown` only for a page that shows no hierarchy: in a current-convention
  batch, `unknown` beside a real `parent_path` is `depth_unknown_with_breadcrumb`,
  because a breadcrumb's levels can be counted.
- Fields outside the core contract must be registered in `vendor_fields.py` by
  name. Their values are never constrained — see docs/DECISIONS.md D-005.

### One feature, several sources, and the ways in (since v6.19.0)

An interface — an API operation, an SDK method, a webhook, a CLI command, a
settings screen — is a way in to a feature, never a feature itself (the
operator's ruling of 2026-10-18; standard terms: ArchiMate's *application
interface* and *application service*, OpenAPI's *operation* and *parameter*).
Four registered fields record it on an ordinary row, so every gate reads it as
it reads any row and every source keeps its own grounded quote:

| field | value |
|---|---|
| `same_feature_as` | the `id` of the feature's **anchor** — its first row, wherever it was seen first. Present on every later source of the feature; absent on the anchor. Only anchors are classified. |
| `interface_type` | `API` · `SDK` · `webhook` · `CLI` · `user interface` |
| `operation` | the operation, method, command or screen, as printed |
| `parameter` | the setting or field inside it that delivers this row's function, as printed |

An interface's whole picture is the rows that share its `source_url` and
`operation`: the module is their `parent_path`, its functions are their
`what_it_does`, and the features it exposes are their `same_feature_as` (or the
row itself, when it is an anchor). Nothing is folded: the tree is append-only,
so a source found later is a new row pointing at the anchor, and
`/kbqa-merge` refuses a row whose anchor is not yet in the tree. G2 checks that
`same_feature_as` names an anchor of the subject (`same_feature_unknown`,
`same_feature_not_anchor`); G6 that no tree row points at nothing
(`tree_same_feature_dangling`); `mapcheck` that only anchors have mapping lines
(`map_line_for_another_source`); G5 counts a repeated term whose rows are one
feature apart from its naming questions. `kbqa stage --lists` writes the
subject's anchors to `_raw/<batch>/FEATURES.md` for the row-writer (`kbqa
capture` did, before v6.22.0), and, since v6.22.0, the same-feature shortlist
`_raw/<batch>/SAME-FEATURE.md` (below).

### Beside each receipt (since v6.20.0)

- **Heading lines.** Each page in `RECEIPT.json` lists its `headings`, each with
  its `line` in the capture, `level` and `text`. `/kbqa-check` reads them for
  **heading coverage** — advisory, never a failure: the headings under which no
  row's quote begins, on pages no stop line explains, are listed for a human
  (a missed feature, or a section rightly not a row). A batch captured before
  v6.20.0 is reported as not measured.
- **Role-row candidates.** When the estate's `kbqa-estate.json` has a
  `role_rows` key — a list of `{"pattern": <regex>, "fields": [<row fields>]}`,
  matched without case, the union of all — `kbqa stage --lists` writes
  `_raw/<batch>/ROLE-ROWS.md` (`kbqa capture` did, before v6.22.0): every row
  of the subject a pattern matches, with the words and field matched, for the
  mapper's role sources. The patterns are the estate's vocabulary, never this
  tool's; without them nothing is written and the result's `role_rows_note`
  says why.
- **Same-feature shortlist** (since v6.22.0). `kbqa stage --lists` writes
  `_raw/<batch>/SAME-FEATURE.md` and names it in its result (`same_feature`):
  one section per page of the window, in the receipt's order, listing up to 10
  of the subject's anchors that share at least 2 words with the page. Words are
  normalised alike on both sides — lowercase, runs of letters and digits, minus
  a short fixed stop-word list (`kbqa.shortlist.STOP_WORDS`) and words of 2
  characters or fewer. An anchor's words come from its `vendor_term`,
  `parameter` and `what_it_does`; a page's from its headings (the receipt's)
  and its parameter-like tokens — identifiers containing `_` or written in
  camelCase — in its parts' own lines. The score is the number of words in
  common; order is score (highest first), then id. One line per candidate:
  `id | score | words in common | vendor_term | parent_path | what_it_does`.
  Candidates only: the row-writer judges sameness. When the capture cannot be
  read (none written, or no longer the receipt's), the shortlist is not
  written and `same_feature_note` says why; the other lists are still written.

## `_draft-<batch>.jsonl` and `kbqa stage` (since v6.22.0)

The row-writer no longer writes the staging file. It writes **drafts** — what
only it can judge — and `kbqa stage` writes `_collect-<batch>-staging.md` from
them, copying everything else by code.

One JSON object per line, in `<subject folder>/_draft-<batch>.jsonl`:

```
{"page": "https://docs.example.test/hooks/retries", "part": 0, "quote": "Failed webhook calls are retried for up to 24 hours.", "vendor_term": "Retries", "what_it_does": "Retries a failed webhook call for up to a day.", "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes"}
{"page": "https://docs.example.test/pricing", "no_row": "pricing page"}
```

| key | value |
|---|---|
| `page` | the page's `url`, exactly as in the receipt |
| `part` | the index of the part in that page's `parts`, from 0 — the part the row-writer read the words in |
| `quote` | the words chosen, from that part's own lines |
| `vendor_term`, `what_it_does`, `evidence_grade`, `confidence`, `mechanism`, `outcome` | the row-writer's judgement, as in the row table; every draft carries all six |
| `same_feature_as` | when the feature already has a row: the anchor's `id` (from `FEATURES.md`), or `draft:<line>` — another draft of this batch, by its 1-based line in the drafts file, which code replaces with the id it gives that draft |
| `interface_type`, `operation`, `parameter`, `source_typo`, `mechanism_raw`, `outcome_raw`, `mechanism_via` | only when they apply; copied to the row as written |
| `no_row` | instead of all the above: a page read that holds no row, in a few words (`{"page": …, "no_row": …}` and nothing else) |

`kbqa stage --subject <d> --batch <b>`:

- **Frontmatter from the receipt.** `batch`, `source_capture`,
  `source_capture_sha256`, `pages` (every page, in capture order),
  `fetched_by_this_agent: false`, the window fields the receipt has
  (`window_offset`, `window_requested`, `window_returned`, `window_end`) and
  `access_date`. It refuses when the capture no longer hashes to the receipt's
  sha256, or its pages are not the receipt's.
- **The quote is the capture's.** The draft's quote is looked for in the part's
  own lines only, folded as G3 folds (NFKC, quotes, dashes, whitespace — never
  spelling); the capture's exact text of the one span found becomes
  `source_quote`. Not found, or found more than once (overlaps included), the
  draft is rejected: never the nearest match, never the draft's own wording.
- **The rest by code.** `source_url` (the page), `access_date`, `parent_path`
  (the part's breadcrumb as captured, else `unknown`), `depth_level` (the
  breadcrumb's levels counted, else `unknown`), `canonical: NOVEL`, and `id`:
  `<subject folder>.<surface>.<breadcrumb's last item>.<vendor_term>`, each
  segment a slug (lowercase ASCII letters and digits, other runs as `-`); a page
  with no breadcrumb has no breadcrumb segment. An id the subject already has —
  in the feature tree or any staging file — or that an earlier draft of the
  batch took gets `-2`, `-3`…; the same drafts on the same subject give the same
  ids. `id` is the first key of every row.
- **A link inside the batch.** `same_feature_as: "draft:<line>"` must name a
  line that holds a row draft — not a `no_row` line, not the draft itself — and
  that draft must be the anchor: it carries no `same_feature_as` of its own
  (one step, never a chain). A link to a rejected draft is rejected with that
  draft's reason. Otherwise the row gets the id given to the named draft.
- **Exact repeats, linked by code.** A draft whose `parameter` (when it has
  one, else its `vendor_term`, as written) and whose quote — the capture's
  exact text, folded as G3 folds — are identical, on the same host, to those
  of an anchor of the subject (feature tree or a staging file) or of an
  earlier anchor draft of this batch gets `same_feature_as` set by code to
  that anchor (a draft anchor as `draft:<line>`, resolved as above). Each link
  is listed under `linked_by_code`: the draft's `line`, the `anchor` id (and
  `anchor_line` for a draft anchor) and what `matched` (`host`, the name
  compared, `quote`). A row that carries `same_feature_as` is never a target.
  Nothing is changed, and the draft is listed under `link_conflicts` with a
  `reason`, when it already names another anchor, when it repeats several
  anchors of the subject at once, or when other drafts name it as their
  anchor (`draft:<line>`), since linking it would leave them pointing at a
  row that is not an anchor. A draft that already names the same anchor is
  left as it is and not listed.
- **Rejected drafts block the staging file.** Also rejected: a page or part the
  receipt does not have, a field no row carries, a missing judgement field, a
  line that is not a JSON object, and a page drafted `no_row` that also has
  rows. While any draft is rejected, stage writes no staging file: it writes
  `_draft-<batch>.rejects-<n>.jsonl` — one line per reject: the draft's line,
  the reason, a suggested next step and the draft itself — and exits 1. `n` is
  the run (`round` in the result); each round's file is kept, never
  overwritten.
- **One correction round.** After round 1 the row-writer rewrites only the
  rejected lines of its drafts file, in place, and stage runs again. Drafts
  still rejected in round 2 are left out only by
  `kbqa stage … --leave-out-rejects`, which writes the staging file without
  them, writes that round's rejects file, and prints each under
  `needs_operator` with its reason and next step — never silently. A third run
  without the flag is refused, its `next_step` naming the flag; the flag
  before the correction round is refused too. There is no second correction
  round.
- **No row.** Each page drafted `no_row` comes back as a suggested stop line,
  `- <url> | no feature: <words>`, under `stop_lines_to_add`, for the fetcher to
  add with `kbqa stop add`; pages with neither a row nor a `no_row` line are
  listed under `pages_without_row_or_no_row`.
- It never overwrites a staging file. When no draft became a row it writes no
  staging file. The result is printed as JSON: the round, counts, the staging
  and rejects paths, the rejected lines and reasons, `linked_by_code`,
  `link_conflicts`, and the `next_step`.

### `kbqa autofix` — the fix round's mechanical part (since v6.22.0)

Before the row-writer's one fix round, `kbqa autofix --subject <d> --batch <b>`
fixes in the staging file the findings that have one right answer computed from
the evidence. It reads `_qa/<batch>.report.json` and refuses unless that report
was made on the staging file's current bytes (`staging_sha256`), refuses a
report of round 2 or later (the round from `_qa-log.jsonl` when the report
names none: autofix is part of the one fix round, and a round-2 batch is the
operator's), and it never edits a batch whose name is not
`<surface>-<YYYY-MM-DD>-wNN`.

| finding | fixed when | to |
|---|---|---|
| `evidence_grade_spelling` | the value is a known respelling of one schema grade: another case or spaces, or bare `verify` | the schema's spelling (`official-doc`, `help`, `marketing`, `verified`, `[verify]`) |
| `parent_path_empty` | the row's `source_url` is a page of the receipt, the parts of it whose own lines hold the row's `source_quote` give one breadcrumb, the receipt and capture agree, and the staging file names that capture's sha256 | that breadcrumb, else `unknown` — as `kbqa stage` writes it; and its levels counted as `depth_level` when that was `unknown` |
| `depth_unknown_with_breadcrumb` | as above, and the row's `parent_path` is exactly that breadcrumb | the breadcrumb's levels counted |
| `id_not_first_key` | the row has an `id` | the same row with `id` first; no value changes |

Only a row whose line reads exactly as `kbqa stage` writes it is rewritten, so
nothing but the fixed fields changes; every other line keeps its bytes and its
place, and the line numbers in the report stay true. When a fix applies it
writes `_qa/<batch>.staging-before-autofix-<n>.md` (the old bytes) and
`_qa/<batch>.autofix-<n>.json` (each change: `code`, `id`, `line`, `field`,
`before`, `after`; the staging sha256 before and after), then the staging file
atomically; `n` counts the batch's runs, and no earlier file is overwritten.
Everything else — and each of these findings the evidence does not settle,
with `why_not_by_code` — is printed under `left_findings` for the row-writer's
fix round; structural and planner findings under `not_for_row_writer`.

## `_mapdraft-<batch>-<A|B>.jsonl` and `kbqa mapstage` (since v6.22.0)

The mapper no longer writes the map file. Each pass writes a **draft** — its
judgement only — and `kbqa mapstage` writes `_map-<batch>-<A|B>.jsonl` from
it, the file `mapcheck` reads (its format is the mapper's §2, unchanged).

One JSON object per anchor row of the staging file (a row without
`same_feature_as`), in `<subject folder>/_mapdraft-<batch>-<A|B>.jsonl`, with
exactly these keys:

```
{"id": "example.docs.reports", "article": "", "role": "admins", "role_source": "rbac-row", "actor": "B", "want": "reports of the conversations each team closed", "so_that": "each team's week is seen", "theme": "I06", "theme_links": [], "pcf_ids": ["90002"], "confidence": "low", "status": "mapped", "note": ""}
```

| key | value |
|---|---|
| `id` | the anchor row's `id` |
| `article` | `"a"`, `"an"` (before a singular role) or `""` — the mapper's choice |
| `role`, `role_source`, `actor`, `theme`, `theme_links`, `confidence`, `status`, `note` | as in the map file |
| `want`, `so_that` | the story's words after `I want` and after `so that`; `so_that` is `""` when the story has none |
| `pcf_ids` | element ids only, as text (`["90002"]`), `[]` when none |

`kbqa mapstage --subject <d> --batch <b> --pass <A|B> --elements <list>`:

- **The story by code.** `user_story` = `"As " + article + " " + role +
  " (APQC-closest)" + ", I want " + want + ", so that " + so_that` — the article
  and its space only when `article` is not `""`, the tag only when
  `role_source` is `apqc-closest`, the "so that" part only when `so_that` is
  not empty: `As admins, I want …`, `As a marketer (APQC-closest), I want …`.
  A `NO-FUNCTION` or `NOT-FEATURE` line with an empty `want` has no story
  (`""`).
- **Elements from the list.** Each id becomes
  `{"pcf_id", "hierarchy_id", "name"}`, all three copied from the element list.
- **The rest as drafted**, in the mapper's key order, one line per anchor in the
  staging file's order. `mapcheck` judges the values.
- **Rejected lines block the map file.** A line that is not a JSON object, a key
  missing or extra (`user_story` included), a `null`, a text key that is not
  text, an `id` that is not a row of the staging file, a row with
  `same_feature_as`, or an id with a line already, an `article` other than the
  three, an element id not on the list, a `want` without a `role`, no `want`
  outside `NO-FUNCTION`/`NOT-FEATURE`, a `needs-human` note that does not open
  with `[<name>]`; and an anchor with no line. While any is rejected no map file
  is written: `_mapdraft-<batch>-<A|B>.rejects-<n>.jsonl` — one line per reject:
  the draft's `line` (none for a missing anchor), `id`, `reason`, `next_step`
  and the draft — and exit 1. Each round's file is kept, never overwritten.
- **One correction round.** The mapper rewrites only the rejected lines, then
  mapstage runs again. Lines still rejected in round 2 are settled only by
  `--leave-out-rejects`: every anchor still gets exactly one line — an anchor
  whose line is rejected or missing is written `needs-human`, its note
  `[no rule] <the reason>`, keeping what its draft gave that can be copied (the
  story when it can be built, the element ids on the list) — and each reject is
  listed under `needs_operator`, with whether it was written. A rejected line
  that is no anchor's is not written, only listed. A third run without the flag
  is refused, and so is the flag before the correction round.
- **The passes stay independent.** A run reads and counts only its own pass's
  draft and rejects files; the other pass's files are never opened.
- It never overwrites a map file. When the staging file has no anchor, nothing
  is written and the result says so.
- **The sidecar.** Beside the map file it writes `_map-<batch>-<A|B>.meta.json`:
  `batch`, `pass`, `map`, `map_sha256`, `staging`, `staging_sha256` — the
  staging bytes the map file was written from (also `staging_sha256` in the
  result). `mapcheck` never reads it.
- **Classifying again** (the fix round, when the row-writer changed rows):
  `kbqa mapstage --subject <d> --batch <b> --pass <A|B> --retire` moves this
  pass's map file, sidecar, draft and every rejects file into a new
  `_qa/retired-<batch>-<A|B>-<n>/` (`n` from 1, one past every earlier folder of
  that batch and pass; nothing deleted, nothing overwritten), prints each move
  and the next step — the mapper writes a fresh draft for this pass, whose
  rounds start again at 1. It refuses while the staging file still hashes to
  the sidecar's `staging_sha256` (unchanged rows are not classified twice), and
  for a map file with no sidecar. It touches only the given pass.

A left-out line whose draft gave no role source, actor or theme — an anchor
that had no line, say — carries none: `mapcheck` fails it
(`role_source_empty`, `actor_invalid`, `theme_unknown`) until the operator
rules on that row. Code never invents a reading to make the check pass.

## `_capture-<batch>.raw.txt` (BRONZE, immutable)

```
=====BEGIN https://docs.acme.test/widgets/overview=====
…verbatim page text, typos and all…
=====END https://docs.acme.test/widgets/overview=====
```

Marker lines are excluded from the block text: a quote must be found in the
vendor's own words, not in scaffolding we wrote.

Since v6.17.0 `kbqa capture` writes it: each page's text is a fixed rendering of
the served HTML (`kbqa.htmltext` — visible text in document order, whitespace
collapsed as a browser collapses it, table cells joined by ` | `, a breadcrumb
as one line joined by ` > `), keyed by the URL that served it. The raw bytes sit
beside it in `_raw/<batch>/`, listed with their sha256 in `MANIFEST.tsv`, so any
block can be re-derived and any quote re-checked against what was served.

Since v6.21.0:
- **Site chrome once.** A run of lines that opens (or closes) most pages of a
  host, identically, is kept once in `_chrome/<host>/<header|footer>-<sha12>.txt`
  (named by its content's sha256, so written once and never overwritten), and
  taken off each page's block. Only lines at the very start or end; never the
  breadcrumb or anything after it; never the whole page. The receipt records
  per page `chrome` — which file and how many lines from each end — so a page's
  full rendering is its header + its block + its footer, exactly.
- **No page twice.** A page whose rendered text equals a page already captured
  for the subject (this window or an earlier one; receipts carry each page's
  `text_sha256`) is not captured again: the receipt lists it under `duplicates`
  with a `no feature: same text as <url>` stop line to approve.
- **Image descriptions.** An image's `alt` text is rendered where the image
  stood as `[image: <alt>]`; decorative images (empty `alt`, `aria-hidden`,
  `role="presentation"`) are not.
- **English is enough** (in the denominator): `kbqa index` leaves out a page's
  other-language copies when the index lists it in English — by the sitemap's
  own `hreflang` links, or a language path segment (ISO 639-1) covering at least
  three such pairs — and lists them in `_raw/index-…/LANGUAGE-COPIES.tsv`.
  `--all-languages` keeps them.

## `_denominator-<surface>-<date>.md` (BRONZE, immutable)

Markdown links, one index item per line. Bare URLs on their own line also count,
and take their label from the last path segment.

```
- [Widgets Overview](https://docs.acme.test/widgets/overview)
- [Syntax Reference](https://docs.acme.test/widgets/syntax-reference)
```

Since v6.17.0 `kbqa index` writes it, under a first line naming the surface,
rung and source URL: `llms.txt` link lines unchanged, a sitemap's `<loc>` URLs as
bare lines, an HTML index page's same-host links as markdown links. The raw
index bytes are kept in `_raw/index-<surface>-<date>/`.

## `_stop-conditions.md` (SILVER)

Keyed by URL **or** label. Two forms are read, the pipe first:

| form | where it comes from |
|---|---|
| `<url> \| <reason>` | the form the estate writes, **as reported** by the operator's handover (`Incomming/2026-10-07/PIPELINE-SPEC.md` §2, `qa-diffs/README.md` defect 2). Whitespace on both sides of the pipe |
| `<url-or-label>: <reason>` | this repo's earlier form. A colon followed by whitespace — never the colon in `https://` |

An **entry** is a `-` or `*` list item, a line inside a ```` ``` ```` fence, or a
line that starts with `http://` or `https://`. Everything else — frontmatter,
headings, prose, other list markers such as `+` or `1.` — is not read. The G4
verdict does not report how many lines were not read. A line not read can only
leave an index item uncovered, which G4 reports; it cannot make G4 pass.

````
---
code: <subject>-stops
---

# Stop conditions

```
https://docs.acme.test/widgets/never-fetched | 404 at fetch time on 2026-08-23
```

- Legacy Widgets: superseded, vendor removed the page
````

An entry without a reason FAILs G4 (`stop_condition_without_reason`) — so do
`<url> |` with nothing after the pipe, and `<url> |reason` with no space after
it. "We stopped" is not a reason.

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
