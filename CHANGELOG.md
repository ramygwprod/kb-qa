# Changelog

All notable changes to `kbqa` are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html),
with one project-specific rule:

> **The row contract is part of the public API.** Any change to `models.py`
> that could make a previously valid row invalid is a MAJOR bump, even if no
> Python signature changed. A batch that passed yesterday and fails today
> without the data changing is a breaking change to its consumers.

Estate CI pins a tag, never a branch, so a release here never changes what an
estate is validated against until that pin is moved deliberately.

---

## [6.0.0] — 2026-09-13

### Removed

- **`--vendor`, and the subject name it stored.** No gate reads it. It existed
  only to label a line in `_qa-log.jsonl`, which made the QA layer a second
  place a subject's identity accumulates — in the artifacts most likely to be
  pasted into a message or attached to a review. A structural check has no use
  for who the subject is: the path locates the file, and a name stored beside it
  is a copy, not information.

  The flag is **rejected**, not ignored. A caller still passing it learns it no
  longer means anything rather than believing the name was recorded.

  `write_verdict()` and `report.build()` lose their `vendor` parameter.
  `_qa/<batch>.<gate>.json`, `_qa/<batch>.report.json` and the log line lose the
  `vendor` key. Reports title themselves from the directory name.

### Fixed

- Two real product identifiers had reached the public repository in test data —
  one in an id fixture, one in a leak-test fixture added the same day. Replaced
  with invented names. `tests/test_report.py` now asserts no verdict or log line
  carries a subject name.

## [5.1.0] — 2026-09-13

Both changes were found by running `probe` against a real estate for the first
time. Neither was a data problem.

### Fixed

- **`probe` printed prose verbatim.** `_line_shape` redacts by removing the
  value of a quoted `"key": "value"` pair. Markdown prose is not quoted, so
  nothing matched and the "other body lines" section reproduced headings, list
  items and sentences — vendor names and ids among them — beneath a banner
  promising that none of it appears. A line outside the frontmatter and outside
  a fence is not a row, so none of its text is schema: `_prose_shape` now
  reports the line's KIND and length, never a character of it. The existing
  leak tests covered row content only, which is why this survived.

### Added

- **`not-a-batch`, a fourth sweep classification.** Discovery matched on the
  filename alone, so a session log or a ruling named `_collect-*-staging.md`
  was audited as a batch — inflating every estate total and producing gate
  failures about files nobody ever collected into. A file that declares no
  batch frontmatter *and* holds no rows is now classified `not-a-batch`,
  excluded from every figure, and named in both the report and the terminal
  summary. Rows without provenance still count as a batch: that is a G1
  finding, owned by a different gate.
- **`probe` says "this file is NOT a collection batch"** in that case, instead
  of `parser DOES NOT MATCH` — which sent the reader to `parsing.py` to correct
  something that was not wrong, and hid the real finding.

### Changed

- `skills/kbqa-check/SKILL.md` pins `5.1.0` and the new manifest.

## [5.0.0] — 2026-09-12

An audit for the one failure v4 could not have caught: **is anything from the
corpus already collected acting as a limit on what can be collected next?**

Three candidates were examined. Two were already safe — extension registries are
per-profile, so a new domain starts clean; and `manifest_mismatch` fires at most
once per gate on a version bump, not per verdict. The third was real.

### Changed — BREAKING

- **`evidence_grade` and `confidence` moved out of the universal core.**
  Every domain grades its sources, but `official-doc / help / marketing /
  verified` is one programme's vocabulary, and `high / medium / low` is one
  programme's scale. A core that fixed them made its own first corpus the
  standard for every corpus after it. Both now live in the profile.

- **The `id` pattern became a convention.** It was inferred from one corpus's
  identifiers. A programme addressing nodes by UUID, or whose subjects use
  uppercase, is not malformed — it is different, and was being rejected by a
  rule derived from whoever happened to be collected first.

The universal core is now six fields, each answerable without knowing what is
being studied: `schema_version`, `id`, `source_url`, `source_quote`,
`access_date`, `broken_source`.

### Added

Four anti-drift guards in `tests/test_domain_agnostic.py`:

- the core contains **only** those six fields — pinned, because adding one costs
  nothing today and breaks the next domain, which nobody is testing when they
  add it
- no profile vocabulary is importable from `models.py`
- the id pattern is overridable
- registries do not leak between profiles — a field registered for one domain is
  refused in another, so the first corpus cannot quietly set what later ones may
  say

### Migration

None for rows. `schema_version` moves to 5; rows that omit it take the default.
Existing rows validate unchanged — `evidence_grade` and `confidence` are still
required by the vendor-catalogue profile, under the same names.

185 tests.

---

## [4.0.0] — 2026-09-12

The tool must collect market intelligence in **any** domain, with nothing about
the subjects already collected constraining what can be collected next. v3 was
vendor-agnostic but methodology-bound: `mechanism`, `outcome` and `depth_level`
were in the core, which asserted one analytical framework as how the world is.

### Changed — BREAKING

- **The contract is split by domain.** Three layers now, not two:

  | layer | scope |
  |---|---|
  | `models.CoreRow` | universal — `id`, `source_url`, `source_quote`, `access_date`, `evidence_grade`, `confidence`, `broken_source`. What makes ANY claim checkable |
  | profile | one programme's framework — `mechanism`, `outcome`, `depth_level`, `vendor_term`… swappable |
  | extensions | the subject's own vocabulary (unchanged from v3) |

  A gate verifying that a quote appears on the page it cites does not care
  whether the subject is a software vendor, a labour market or a regulator. The
  gates see a row model and parsed structures; **no gate logic changed.**

- **File naming and capture delimiters are conventions, not constants.**
  `conventions.py` carries the staging glob, capture template, verdict
  directory, `=====BEGIN=====` syntax and fence patterns. Compiling these in had
  a specific consequence: a corpus that delimited pages differently parsed to
  zero blocks, and **zero blocks reads as "nothing to check against", not as
  "wrong syntax"** — a green sweep over nothing.

- `vendor_fields.py` → `extensions.py`. The *type* is universal; the *entries*
  are one programme's schema and moved into its profile.

### Added

- `--profile <name>` and `--profiles` on every command.
- `kbqa.profiles.vendor_catalogue` — the existing framework, unchanged in
  behaviour. Existing rows validate exactly as before.
- **`tests/test_domain_agnostic.py`** — the proof, not the claim. Defines a
  compliance-posture profile (obligations, jurisdictions, instruments — no
  feature or mechanism anywhere), with different file names and `<<< PAGE … >>>`
  markers, and runs the real G1/G2/G3 against it. Asserts grounding still
  catches invention there, and that no field from the other profile leaked into
  the core.

  This class of failure is invisible from inside the original domain: every
  test passes and the tool only breaks when someone tries a second sector.

### Migration

None for rows. `schema_version` moves to 4; rows that omit it take the default.

181 tests.

---

## [3.0.0] — 2026-09-09

Vendors differ in product structure, naming, depth and scale — genuinely, not
accidentally. A strict flat field set cannot record that, and v2 was rejecting
legitimate rows for having the vendor's own vocabulary in them.

§G3 already settles the principle for text: *never normalise spelling, because
vendor typos are evidence.* Structure is evidence by the same argument.

### Changed — BREAKING

- **The contract is split by owner.**

  | half | rule |
  |---|---|
  | **core** | ours. Strict, enum-validated. Provenance and grounding — the fields that make a claim checkable |
  | **vendor fields** | theirs. The **name** must be registered in `vendor_fields.py`, deliberately, in a commit. The **value** is never constrained |

  `extra="forbid"` did not go away; it moved. A collector inventing
  `confidence_note` still fails on the first row, and the refusal says how to
  resolve it. What no longer happens is rejecting a vendor for using a word the
  vendors we collected first did not use.

  **Nothing is renamed.** Rows keep the exact keys the collector wrote.
  `alias_of` records how a field relates to a core one without touching either
  — `mechanism_raw` → `mechanism`, `vendor_category` → `canonical`. Renaming
  would itself be the editing this package exists to prevent.

- **`depth_level` accepts the vendor's own numbering as well as the named
  levels.** Some hierarchies do not fit five names. A numeric depth records
  position in *that vendor's* tree; the names impose ours. Forcing one
  convention would flatten a real structural difference into a false one.
  Nonsense is still rejected — open to two conventions is not open to anything.

- **`evidence_grade` accepts `verify` as well as `[verify]`.** Our field, our
  enum, and the collector writes the bare form. Rejecting rows over a pair of
  brackets taught nothing.

### Added

- `src/kbqa/vendor_fields.py` — 36 fields registered from
  `kbqa sweep --field-values` over 183 batches / 12,728 rows, each classified
  (`verbatim` / `provenance` / `batch-level`) with a note on what the vendor
  means by it. Tested: every entry documented, every alias resolves, no entry
  shadows a core field.
- `docs/DECISIONS.md` D-004 (the evidence) and D-005 (the ruling, which
  supersedes D-004's recommendations — they treated vendor variety as a defect
  to be constrained, and acting on them would have destroyed evidence).

### Migration

Rows need no change. A batch that failed v2 for carrying `node_kind` or a
numeric `depth_level` now passes unaltered. A batch carrying a field nobody has
registered fails, and the message names the file to register it in.

157 tests.

---

## [2.1.0] — 2026-09-08

Found by running 2.0.0 against the real estate for the first time. The audit
reported **0% of rows verifiable**; that figure was a parser defect, not a fact
about the data.

### Fixed

- **A third serialisation was unreadable: JSONL inside a ```` ```json ```` fence.**
  The parser recognised the fence, assumed the body was a JSON array, and
  `json.loads` failed with "Extra data" at the second object. The batch was then
  reported as **zero rows** — silently, and specifically on the only nine
  batches in the estate that have captures and can therefore be grounded at all.
  A decode failure in one shape is now a signal to try the other, not a verdict
  about the file. `row_format` reports `fenced-jsonl` when found.
- **The §G2 naive cross-check now follows the detected format.** `^{"id"` counts
  nothing in a pretty-printed array and `^\s*"id":` counts nothing in JSONL, so
  the wrong pattern would fail a batch for a reason that is not true of it.
- **`sweep` named a subfolder as a vendor.** Vendor was taken from the immediate
  parent directory, so `<root>/<container>/<Vendor>/_to_delete/` reported vendor
  `_to_delete` — and a folder plainly named for deletion was counted in the
  totals as live data. Vendor now comes from position under the estate root.

- **Frontmatter broke on folded scalars.** Real collector frontmatter uses
  indented continuation lines for prose (`scope:` spanning three lines). The
  minimal YAML subset rejected them, making the whole frontmatter unparseable —
  which cascaded into false `no_declared_pages` and `capture_hash_absent`
  findings on batches whose frontmatter was fine.
- **`no_declared_pages` fired on batches that declare their pages correctly.**
  G1 read only a frontmatter `pages:` list; some batches declare pages in a
  markdown table instead. Both are now read, and the verdict records which via
  `pages_source`. Row `source_url`s inside a ```` ```json ```` fence are
  excluded — a citation is not a declaration, and counting it would make the
  declaration agree with the rows by construction.

### Added

- **`capture_has_no_page_blocks`** (structural gap). A capture holding text but
  no `=====BEGIN <url>=====` markers cannot be split into pages, so grounding is
  *impossible* rather than failing. Previously this emitted one
  `url_not_in_capture` per row — on a real batch, **181 findings saying "this
  quote is not on its page" when the truth was "this file records no pages"**.
  Now one structural finding, and the counts report `unassessable` separately
  from `grounded`: nothing has been shown wrong with those rows.

  Deliberately **not** degraded to whole-capture matching. §G3 scopes to the
  row's own page precisely so a quote lifted from another page cannot pass, and
  `bad_quote_from_wrong_page` exists to keep that honest.
- `sweep --exclude <glob>` (repeatable). Excluded batches are **counted and
  named** in their own report section, never silently dropped — a batch that
  vanishes from a total without explanation is indistinguishable from one that
  was never collected. Nothing is excluded by default.
- `sweep --vendor-depth N` — which path component under the root names the
  vendor. Defaults to 2, for the common `<root>/<container>/<Vendor>/` layout.

### Notes

131 tests. `tests/test_parsing.py` covers all three serialisations and asserts
the naive count agrees with the parse in each, so this class of defect fails
loudly rather than reporting zero.

---

## [2.0.0] — 2026-09-08

First release reconciled with a real estate. v1 was written from the
specification alone and had never read a collector-produced file.

### Changed — BREAKING

- **Row contract is schema v2.** Five fields the collector has always emitted
  (`node_kind`, `deployment`, `plan_gating`, `vendor_category`,
  `vendor_category_source`) were absent from v1, so every real row failed
  conformance on fields that were never in dispute. They are now named and
  optional. Rows carrying `schema_version: 1` are rejected — see
  [docs/DECISIONS.md](docs/DECISIONS.md) for the evidence behind each field.
  `extra="forbid"` is unchanged: naming five known fields does not admit a sixth.
- **Staging parser accepts the serialisation the collector actually writes** —
  a pretty-printed JSON array inside a ```` ```json ```` fence. The spec's
  `grep -c '^{"id"'` describes JSONL, which no file in the estate uses. Both
  forms are read, and `row_format` records which was found, because a silent
  fallback between formats is how a parser starts disagreeing with the file it
  claims to have read.

### Added

- **`kbqa sweep`** — estate audit. Sorts every batch by whether its quotes can
  be checked at all (`verifiable` / `unverifiable-no-capture`), runs conformance
  everywhere, and runs grounding only where a capture exists. `--field-values`
  collects observed value distributions as evidence for constraining schema v3.
- **`kbqa report`** — the checker's output to the maker. Runs the batch gates
  and renders a remediation plan classified by **kind** (structural / planner /
  fixable) and **nature** (gap / issue), each with an explicit remedy including
  what is *not* a fix. Writes `_qa/<batch>.report.md` and a machine-readable
  `.json` sidecar. Every finding names the gate module and its SHA-256.
- **`kbqa probe`** — reports a file's structure without disclosing its content,
  so a format can be confirmed by someone who must not read the data. Field
  names, types, lengths and marker syntax only; never quotes, URLs, vendor terms
  or free text.
- **G6 detects skipped checks**, not only failed ones: `batch_unchecked`,
  `verdict_stale`, `batch_known_failing`. This is the control that stands in for
  a required status check where a private repo on a free plan cannot enforce
  one — and it lives inside the pinned gates, so whoever skips a check cannot
  edit away the check that notices.
- `ci/estate-pre-push` — local pre-push hook for the estate. Level 2:
  bypassable with `--no-verify` by design, so skipping is deliberate and
  recorded rather than silent.
- Estate CI writes a GitHub job summary, because an unenforced red X is easy to
  scroll past.

### Fixed

- **G6 counted feature-tree rows with the JSONL pattern `^{"id"`**, which
  matches nothing in the fenced-array format. Every real `feature-tree.md` would
  have been reported as 0 rows and failed `proof_count_mismatch` — a tooling
  fault that would have read as a data disaster on the first estate sweep.
- **`probe` leaked short values.** Redaction was length-based, so anything under
  25 characters passed through; on the pretty-printed format every value sits on
  its own line, so short product names reached the report verbatim. Redaction is
  now key-aware — the key of a JSON pair survives as schema, the value never
  does, at any length.

### Removed

- `models.StagingFrontmatter` — defined in v1, referenced by no gate, and
  disagreeing with both the spec and the collector's real output. G1 reads the
  frontmatter directly and reports each missing key as its own finding, which
  gives a specific remedy instead of one opaque validation error.

---

## [1.0.0] — 2026-08-25

Initial release. Seven gates built from `_QA-ARCHITECTURE-SPEC.md` alone, with
no access to the estate they validate — so that the checker's definition of
correct came from the specification rather than from the collector's output.

### Added

- `models.py` — the row contract as Pydantic, `extra="forbid"`
- Gates G0–G6: permission, capture integrity, conformance, grounding,
  completeness, bundles, integrity
- Verdicts carrying `manifest_sha256` of the gate code that produced them
- `_qa-log.jsonl` append-only compliance log
- `agents/fetcher.md` and `agents/row-writer.md` — role separation by capability;
  the row-writer has no `WebFetch`
- CI, with enforced required status checks on `main`
- 51 tests: every blocking gate proven to fail on a purpose-built fixture

### Known limitations at 1.0.0

- The staging format was **inferred from the specification, never observed**.
  It was wrong; 2.0.0 corrects it.
- Nothing had been run against real data.

[2.0.0]: https://github.com/ramygwprod/kb-qa/releases/tag/v2.0.0
[1.0.0]: https://github.com/ramygwprod/kb-qa/releases/tag/v1.0.0
