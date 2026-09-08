# kbqa — the validator package

Validation gates for evidence-grounded data collection: every collected row
must be traceable to a verbatim quote in a stored page capture, or it fails.

Built to be a validation layer a collecting agent **cannot pass by editing the
validator**. Implements a private commissioning specification, which is not
published — nothing here requires it at runtime.

📖 **[docs/MANUAL.md](docs/MANUAL.md)** — full manual: structure, workflows for
operators and agents, command and findings reference, trust model, release
process.
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
.venv/bin/pip install -e ".[test]"
```

## Run

```bash
python -m kbqa g3 --staging _collect-widgets-staging.md --capture _capture-widgets.raw.txt
```

Gate runs are **side-effect-free by default** — the verdict goes to stdout and
nothing is written. Add recording flags to persist:

```bash
python -m kbqa g3 --staging <f> --capture <f> \
  --vendor-dir Competitors/Acme --batch widgets --vendor Acme --log _qa-log.jsonl
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

## Report — the checker's output to the maker

```bash
python -m kbqa report --vendor-dir Competitors/Acme --batch widgets --vendor Acme \
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

The staging format the gates read is **inferred from a specification, not
observed** — this package was built with no access to the estate it validates.
The probe closes that gap without reopening it: it reports field names, value
types, string lengths, and marker syntax, then says whether the shipped parser
agrees with the file.

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

51 tests. Every blocking gate is proven to **fail** on a fixture built to break
it — a gate that has never failed has not been tested.

Fixtures are **generated, not hand-edited**:

```bash
.venv/bin/python tests/build_fixtures.py
```

CI regenerates them and fails if the committed copies differ. Editing a fixture
to make a gate pass is the exact failure mode this package exists to catch.

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
