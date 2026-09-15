# kbqa — the validator package

Validation gates for evidence-grounded data collection: every collected row
must be traceable to a verbatim quote in a stored page capture, or it fails.

Built to be a validation layer a collecting agent **cannot pass by editing the
validator**. Implements a private commissioning specification, which is not
published — nothing here requires it at runtime.

📖 **[docs/MANUAL.md](docs/MANUAL.md)** — user manual: quickstart, workflows for
operators and maker agents, the full action surface, what a well-formed dataset
is, findings reference, troubleshooting, and the **Do/Don't boundary** (§11)
that says what a maker agent may and may not do when a gate fails.
🔧 **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** — developer guide:
architecture, adding a domain, invariants, known traps, release process.
🗺️ **[docs/pipeline.html](docs/pipeline.html)** — the pipeline drawn: four
roles, the isolation boundary, the seven gates, and where the guarantees stop.
Open it in a browser; no build step.
📋 **[CHANGELOG.md](CHANGELOG.md)** · 🧾 **[docs/DECISIONS.md](docs/DECISIONS.md)**
— contract changes with the evidence behind them.

## The honest limit, stated first

| Level | Mechanism | Status |
|---|---|---|
| 1 · tamper-evident | SHA-256 manifest in every verdict | **built** |
| 2 · out-of-scope | gates live outside the collector's folder | **built** |
| 3 · capability-denied | row-writer spawned without network tools | **built** (`agents/`) |
| 4 · **tamper-proof** | CI re-runs gates from a pinned version | **enforced** — required status checks on `main` |

⛔ Levels 1–3 are **tamper-evident**, not uneditable. Only level 4 is a gate:
the gates run on infrastructure the collecting agent cannot reach, from a
pinned tag it cannot edit, and a red result blocks the merge rather than
merely reporting it.

## Install

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


## Run

```bash
python -m kbqa g3 --staging _collect-widgets-staging.md --capture _capture-widgets.raw.txt
```

Gate runs are **side-effect-free by default** — the verdict goes to stdout and
nothing is written. Add recording flags to persist:

```bash
python -m kbqa g3 --staging <f> --capture <f> \
  --vendor-dir Competitors/Acme --batch widgets --log _qa-log.jsonl
```

| gate | command | exit codes |
|---|---|---|
| G0 permission | `g0 --host <host> --out <vendor-dir>` | 0 allowed · **2 DECLINED** · 1 unreachable |
| G1 capture integrity | `g1 --staging <f> --capture <f>` | 0 / 1 |
| G2 conformance | `g2 --staging <f>` | 0 / 1 |
| G3 grounding | `g3 --staging <f> --capture <f>` | 0 / 1 |
| G4 completeness | `g4 --denominator <f> --rows <f>... [--stops <f>]` | 0 only when `without_row == 0` |
| G5 bundles | `g5 --rows <f>...` | **always 0** (advisory) |
| G6 integrity | `g6 --root <project>` | 0 / 1 |

Exit **2 means DECLINED and nothing else.** A usage error exits 1, never 2 — a
typo must not be readable as a permission decision.

## Profiles — one tool, any domain

```bash
python -m kbqa --profiles
python -m kbqa --profile <name> <command>
```

The contract is three layers: a **universal core** that makes any claim
checkable, a **profile** holding one programme's analytical framework, and an
**extension registry** for the subject's own vocabulary. File naming, capture
marker syntax and the id pattern are profile conventions, not constants.

Adding a domain is a new module under `src/kbqa/profiles/`. No gate changes —
`tests/test_domain_agnostic.py` proves it by running the real gates against a
compliance-posture profile with different fields, file names and markers.

## Report — the checker's output to the maker

```bash
python -m kbqa report --vendor-dir Competitors/Acme --batch widgets \
  [--denominator <f>] [--stops <f>] [--log _qa-log.jsonl]
```

Runs G1–G3 (and G4 with a denominator), writes each verdict to `_qa/`, appends
to the log, and renders `_qa/<batch>.report.md`.

A verdict says a batch failed. It does not say what may legitimately change, and
that distinction is the point. A maker agent handed *"G3 FAILED, 14 rows"* will
edit fourteen quotes until the gate goes green — which is the defect this
package exists to catch, not a repair of it. So every finding is classified:

| class | meaning |
|---|---|
| **structural** | not repairable by editing rows. A missing capture is an absent Bronze artifact, not a defect in the staging file |
| **planner** | scope or fetch-list work — an uncovered index item, a cited page nobody fetched |
| **fixable** | the rows disagree with the contract or their own evidence, and correcting them is legitimate |

Cutting across that, each finding is a **gap** (something absent — it has to be
produced, or its absence recorded as a decision) or an **issue** (something
present and wrong, correctable in place). Treating a gap as an issue is how
"fix the failures" becomes "edit rows until green".

Each carries an explicit remedy, including what is *not* a fix. Every finding
code a gate can emit has one, enforced by `tests/test_report.py` — a report that
falls back to "see the message" for its most important findings is not a report.

The report also states **what was not checked**. A gate that did not run has
found nothing, which is not the same as having found nothing wrong, and silence
about it reads as coverage the batch does not have.

Every finding names the gate module and its SHA-256, so a maker who disputes a
finding can cite the exact code rather than edit it. Alongside the markdown,
`_qa/<batch>.report.json` carries the same plan for a maker agent that consumes
it rather than reads it.

## Probe — confirm the format without disclosing the data

```bash
python -m kbqa probe --staging <f> [--capture <f>]
```

The gates were built with no access to the corpus they validate, so the formats
were first inferred from a specification and then corrected against reality. The
probe is how that correction happens without reopening the gap: it reports field
names, value types, string lengths and marker syntax, then says whether the
shipped parser agrees with the file.

It never reports quotes, URLs, vendor terms, or free text. That is a tested
guarantee, not an intention — `tests/test_probe.py` fails if row content reaches
the report. The output is meant to be pasted to someone who must not read
your data.

## Run sequence

```
G0 ──exit 2──> STOP. Vendor closed. No retry, no alternate fetcher.
 │ exit 0
 ▼
denominator (fetcher) ──> plan batches ──> per batch:
     fetcher ──> capture      row-writer ──> staging
     G1 ─ G2 ─ G3    any FAIL ──> back to the PLANNER, never the executor
 ▼
G4 ──exit 1──> unmatched groups to the planner
 │ exit 0
 ▼
G5 (advisory) ──> merge to GOLD ──> G6
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

189 tests. Every blocking gate is proven to **fail** on a fixture built to break
it — a gate that has never failed has not been tested.

Fixtures are **generated, not hand-edited**:

```bash
.venv/bin/python tests/build_fixtures.py
```

CI regenerates them and fails if the committed copies differ. Editing a fixture
to make a gate pass is the exact failure mode this package exists to catch.

## Skills — the pipeline as capability, not instruction

```
skills/kbqa-collect/SKILL.md   the collecting role
skills/kbqa-check/SKILL.md     the checking role
```

A markdown file saying "delegate to the fetcher" is a request, and a request is
skipped under pressure with nothing noticing. So each role is defined by what
its session **cannot** do.

| | `kbqa-collect` | `kbqa-check` |
|---|---|---|
| tools | `Task`, `Agent`, `Read` | `Bash`, `Read` |
| can fetch | **no** — must delegate | no |
| can write | **no** — must delegate | no |
| can read verdicts | **no** — denied | yes |

The collector holds no `WebFetch`, no `Write` and no `Bash`, so it cannot
collect — only delegate to the `fetcher` and `row-writer` subagents, which hold
complementary halves of the job. A session holding both the network and a
writing tool will use both, and rows written that way are grounded in a
context's memory of a page rather than in a capture.

Each ships a `settings-snippet.json` closing the routes around the boundary.
**They are mutually exclusive** — permission denies are session-wide, and the
checker must read the `_qa/` the collector must not. `tests/test_skill_pin.py`
fails the build if a skill gains a writing tool, a deny rule is dropped, or the
pinned manifest goes stale. See [skills/README.md](skills/README.md) for what
this does and does not close.

## How this was built

The gates were written from the spec alone. This session had **no read access
to the data estate** — enforced by permission denies plus an OS-level sandbox,
not by instruction. See [.claude/settings.example.json](.claude/settings.example.json);
the real file is machine-specific and not published.

That means:

- Nothing was ported from `validate_rows.py`, `completeness.py`, `bundles.py`,
  or `session_start.py`, overriding spec §8's "port as-is". Spec §7 records that
  five checkers in this project gave false results in one session; porting them
  would inherit those blind spots.
- No fixture was harvested from real vendor data. If a real batch contained an
  invented quote, a harvested `good/` fixture would certify it as correct.

The cost is in [docs/STAGING-FORMAT.md](docs/STAGING-FORMAT.md): the on-disk
staging format is **inferred**, and needs your confirmation. Gate logic is
written against parsed structures, so if the format differs only
`src/kbqa/parsing.py` changes.

## Open questions

See the end of [docs/STAGING-FORMAT.md](docs/STAGING-FORMAT.md). The one that
changes behaviour today: `models.py` permits `doc:` references, but §G3
requires every `source_url` to appear as a BEGIN marker in the capture — so a
`doc:` row currently **FAILs G3**.
