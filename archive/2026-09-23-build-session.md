# Session record — 2026-09-13 to 2026-09-23

The build of kbqa from v2.1.0 to v6.14.1, written for whoever picks this up
next. Not a transcript: the decisions are in `docs/DECISIONS.md` and the changes
in `CHANGELOG.md`. This is the context those two cannot carry.

---

## What exists at close

**kbqa v6.14.1** — seven gates (G0–G6), plus `freeze` and `mappings` for the
interpretation round, `sweep` for estate audit, `probe` for shape-only
diagnosis. 379 tests. Public at `github.com/ramygwprod/kb-qa`, installed from a
pinned tag, CI enforced on `main`.

**Two skills**, separated by capability rather than instruction:
`kbqa-collect` holds `Task`, `Agent`, `Read` — no `WebFetch`, no `Write`, no
`Bash`, so it cannot collect and must delegate. `kbqa-check` holds `Bash` and
`Read` — no `Edit`, no `Write`, so it cannot make a failing batch pass.

**Two agent definitions**, `fetcher` and `row-writer`, holding complementary
halves: network without reason to interpret, capture without network.

**The operating model:** `/kbqa-collect <Subject>` → human → `/kbqa-check
<folder>`. The human between them is load-bearing, not temporary — a collecting
context that sees the verdict on its own work will edit toward it.

---

## The estate, as measured 2026-09-23

Reported by `kbqa sweep`, run by the operator. Never observed from this repo.

| | rows |
|---|---|
| verifiable — quote checkable against a stored capture | 2,034 |
| recoverable — capture exists, no page markers | 424 |
| unverifiable — staging file with citations, no capture | 11,232 |
| no batch — rows only in a merged tree | 2,313 |
| **total across 64 subjects** | **16,003** |

**13% of the corpus rests on checkable evidence.** That figure was not
computable at the start of this session — 1,196 rows were unreadable and 2,079
appeared in no total at all.

---

## What the work actually was

Almost none of it was implementing the specification. The gates were written in
the first days. Everything after was **finding out what the specification got
wrong about real files**, and the two patterns below are the reason.

### Pattern one — silence renders as success

Six times, something the package could not see was indistinguishable from
something it had checked and found clean:

- staging discovery matched on filename, counting rulings as batches (D-006)
- the denominator glob matched 2 files in 20, so G4 never ran for 18 of 19
  subjects — reported accurately, in the place a reader skims (D-009)
- G4 with no denominator simply did not run (D-010)
- `sweep` never looked at merged trees, so 54 subjects were absent from an audit
  that reported percentages (D-012)
- ten finding codes and two commands were missing from the manual
- 962 unreadable rows sat in no tier and no total

**For any check you add, ask what its silence looks like.**

### Pattern two — a constraint about someone else's files is a hypothesis

Five times, a rule invented from the specification or a single sample was wrong
against the corpus: the fenced-JSONL parser reading 181 rows as zero; the id
pattern rejecting `_` across 857 rows, then rejecting `-`; `depth_level` typed
as string against integers; the denominator glob; and finally two ordinary JSON
writing styles that hid 962 rows (D-016).

**When a whole batch fails one narrow rule, suspect the rule.** The tests cannot
catch these — fixtures are authored by the same hand that wrote the constraint,
which is deliberate (`tests/build_fixtures.py` says why) and is exactly the
limit of that choice.

### The sharpest instance of both

A manifest was pinned at **65 hex characters** for six releases while its test
passed, because the test and the re-pin script shared a regex and therefore a
blind spot. Found by a reader who had written neither. A test passing is not
evidence when the test and the code were written together.

---

## Decisions that shape everything downstream

Full records in `docs/DECISIONS.md`. The load-bearing ones:

- **D-005** the subject's structure is evidence, not variance to be normalised
- **D-007** the checker stores structure, never identity
- **D-008** a source must be re-fetchable — no `doc:` references
- **D-011** a window declares *why* it stopped; exhaustion is never inferred
- **D-013** the subject's words are frozen; our reading is not
- **D-014** a mapping keys on `id`, never on the term — keying on the name folds
  81% of a real corpus, and `g5_bundles` already refused to do by inference what
  the proposal would have done by schema
- **D-015** a guard carries its own recovery material — `freeze` told operators
  to restore from version control the estate does not have

---

## Open at close — none of it in this repo

**Estate side**, for the collection regime:
- `roles-and-run-contract.md` defines one Collector that fetches *and* extracts,
  contradicting the two-agent split everything else rests on. Replacement
  wording was supplied and not yet applied
- two Step 5 texts exist; the one sessions load points at retired checkers
- two one-line edits to `field-schema.md` and the rounds table, making
  `canonical` read-only in rows
- a handoff, unwritten, holding the estate at exit 1 on a correct D6

**Operator side:**
- the subagent test: whether a subagent keeps its declared tools when the parent
  session is restricted. Nobody has run it, and the enforcement design rests on
  it
- a 30-row sample against the giants before R2 encodes those rows as the
  standard

**Tool side:** nothing. The advice at close was to stop, and to resume only when
a real run produces something to fix.

---

## For whoever reads this next

**Every defect worth fixing came from running against real data, not from
reading the code.** No review produced anything this week; the corpus produced
everything.

**Biases of the session that built this**, from its own account, so a reader can
discount appropriately: toward this tool over the pre-existing collection regime
it duplicated without knowing it existed; toward shipping code when a sentence
would have answered the question (24 releases in 10 days); toward inflating a
finding's severity while justifying its fix; toward stating second-hand facts
about an estate it has never read, with the confidence of someone who had.

**The estate is unreadable from this repo by design.** A checker that has read
the collector's output is not independent. Every number here was reported by a
command run elsewhere — treat them as reported, not observed.
