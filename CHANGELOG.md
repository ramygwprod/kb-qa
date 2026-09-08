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
