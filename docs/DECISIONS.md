# Decisions

Changes to the row contract are recorded here with the evidence behind them.
Spec §2: *"Changing this file is a version bump, a commit, and a note. Never
mid-run."* This is that note.

A decision belongs here when a later reader would otherwise have to guess why
the contract says what it says.

---

## D-001 · Schema v2 admits five collector fields

**Date** 2026-09-08 · **Status** decided · **Affects** `models.py`, `SCHEMA_VERSION`

### What was found

`kbqa probe` against a real batch (222 rows) showed five fields present in every
row and absent from the v1 contract:

| field | distinct values in that batch | reading |
|---|---|---|
| `node_kind` | 6 | varies — carries information |
| `deployment` | 2 | varies — carries information |
| `vendor_category` | **1** | constant across all 222 rows |
| `vendor_category_source` | **1** | constant across all 222 rows |
| `plan_gating` | **1** | constant across all 222 rows |

Two contract fields appeared in no row: `schema_version` and `usecase_of`.

### The decision

All five are admitted to the contract as `Optional[str]`. `SCHEMA_VERSION` moves
to 2.

### Why not simply forbid them

`extra="forbid"` exists because 91 annotation fields once accumulated unnoticed
(§2). The purpose is that the field set is *decided deliberately*, not that it
never changes. Under v1 every real row failed conformance on five fields that
were never in dispute — which does not enforce the contract, it just makes the
gate useless and trains its reader to ignore it.

Naming five known fields does not weaken the guarantee. A sixth invented field
still fails on the first row.

### Why `Optional[str]` and not enums

Their value sets were observed in **one batch**. An enum inferred from one sample
rejects legitimate values found in the next — inventing a constraint and calling
it a contract, which is the same error as inventing a quote and calling it
evidence.

`kbqa sweep --field-values` collects the real distributions estate-wide.
Constrain them in v3 from that evidence.

### Open, deliberately

**Three fields hold one value across 222 rows.** That is what an unexercised
default looks like. `vendor_category` also duplicates `canonical` — both were
`NOVEL` for every row, which is the same fact stored twice.

This is a question for the collector, not a validation failure, so it is not
resolved here. Two possibilities, and the sweep distinguishes them:

- the fields are genuinely single-valued so far, and will vary later
- they are defaults nothing ever sets, and should be removed from the collector

Until the sweep says which, forbidding them would fail real rows over an
unanswered question.

### Reversal condition

If the estate-wide sweep confirms a field never varies across any vendor,
remove it from the collector and from the contract in v3. A field that cannot
take a second value is not carrying information.

---

## D-002 · `doc:` sources currently fail G3

**Date** 2026-09-08 · **Status** OPEN — needs a ruling

`models.py` permits `source_url` of the form `doc:...`. §G3 requires every
`source_url` to appear as a `=====BEGIN=====` marker in the capture. A `doc:`
reference cannot, by construction. So a `doc:` row fails G3 today.

The three coherent resolutions:

1. **Forbid `doc:`** — every row cites a fetched page. Simplest, and consistent
   with grounding meaning "checkable against stored text".
2. **Capture `doc:` sources too** — a downloaded PDF or spec gets a capture like
   any page, and G3 works unchanged. Most faithful to the intent.
3. **Exempt `doc:` from G3** — records the citation without checking it.
   ⚠ This creates a class of row that is exempt from the only gate whose ground
   truth is the vendor's own words. Any row could then be made to pass by
   relabelling its source as `doc:`. **Not recommended.**

No default has been chosen: whichever is picked changes what a G3 PASS means,
and that is not a decision to make silently inside a gate.

---

## D-003 · Estate enforcement stays at level 3½

**Date** 2026-09-08 · **Status** decided · **Affects** deployment, not code

A private repo on a free GitHub plan cannot enforce rulesets, and the estate
must stay private. Its CI therefore reports without blocking.

§0 permits this: levels 1–3 *"make tampering visible and inconvenient, which is
enough when a human reads the verdicts."* The decision is to rely on that clause
and to build controls that keep it true:

- **G6 detects skipped checks** (`batch_unchecked`, `verdict_stale`). Placed
  inside the pinned gates, where level 4 already holds — so whoever skips a
  check cannot edit the check that notices.
- **`ci/estate-pre-push`** refuses a push on a failing sweep. Level 2,
  bypassable with `--no-verify` on purpose: skipping becomes a decision.
- **CI job summary**, so an unenforced red X is not scrolled past.

⛔ The estate is **not** tamper-proof and must not be described as such. The
accurate statement: *the gates cannot be edited; running them can be skipped;
skipping is recorded.*

### Reversal condition

**If the maker agent ever gets push access to the estate**, no human sits
between the collector and the repository, §0's clause stops holding, and this
decision must be revisited. GitHub Team (~$4/user/month) is then the cheap
answer.
