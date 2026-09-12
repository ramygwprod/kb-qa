# kbqa — developer guide

**Version 5.0.0** · for anyone extending or maintaining the package

For *using* the tool, see [MANUAL.md](MANUAL.md). This document covers
architecture, how to extend it, what must not break, and how to release.

---

## 1 · The one idea

This package validates claims about subjects using the subjects' own published
words. Everything in the architecture follows from one constraint:

> **Nothing the tool has already seen may constrain what it can see next.**

A checker whose rules are inferred from its first corpus will reject the second
corpus for being different, and will do so confidently. That failure is
invisible from inside the first corpus — every test passes. Most of the design,
and every hard-won test in `test_domain_agnostic.py`, exists to hold that line.

---

## 2 · Architecture

### Three layers, three owners

```
┌─ universal core ──────────── models.CoreRow ────────────────────┐
│  id · source_url · source_quote · access_date · broken_source   │
│  What makes ANY claim checkable. Strict. Domain-neutral.        │
└────────────────────────────────────────────────────────────────┘
┌─ profile ───────────────── profiles/<name>.py ──────────────────┐
│  The analytical framework + conventions + extension registry.   │
│  Strict, but swappable. One programme's way of analysing.       │
└────────────────────────────────────────────────────────────────┘
┌─ extensions ─────────── profile.extensions ─────────────────────┐
│  The subject's own vocabulary. NAME registered, VALUE free.     │
└────────────────────────────────────────────────────────────────┘
```

The test for which layer something belongs in:

| question | layer |
|---|---|
| Does a software vendor, a labour market **and** a regulator all have this? | core |
| Is this how *we* choose to analyse this sector? | profile |
| Is this the *subject's* word for something? | extension |

### Module map

| module | responsibility |
|---|---|
| `models.py` | `CoreRow` — the universal fields and the extension gate |
| `profile.py` | `Profile` type, registry, `activate()` / `active()` |
| `profiles/` | one module per analytical framework; importing registers it |
| `conventions.py` | file naming, capture delimiters, fence syntax, id pattern |
| `extensions.py` | `ExtensionField` type and the four kinds |
| `parsing.py` | readers for staging / capture / denominator. Parse only — never write, never repair |
| `manifest.py` | SHA-256 of every module, computed at import |
| `verdict.py` | `Verdict`, `Finding`, JSON writer, log writer |
| `gates/g0…g6` | the checks. Read-only, write only a verdict |
| `report.py` | remediation report for the maker |
| `sweep.py` | corpus-wide audit |
| `probe.py` | shape-only diagnostic |
| `cli.py` | dispatch, `--profile`, recording flags |

### Why gates never see a profile

A gate takes parsed structures and a row model. It never imports a profile
directly, never names a framework field, and never reads a convention except
through `profile.conventions()`. That is what let v4 move `mechanism`,
`outcome` and `depth_level` out of the core with **zero gate changes**.

If you find yourself importing from `profiles/` inside `gates/`, stop — the
thing you want belongs in `CoreRow`, in `Conventions`, or in the verdict.

---

## 3 · Adding a domain (a profile)

A new sector is a new module under `src/kbqa/profiles/`. No gate changes.

```python
from enum import Enum
from pydantic import Field

from ..conventions import Conventions
from ..extensions import PROVENANCE, VERBATIM, ext
from ..models import CoreRow
from ..profile import Profile, register


class Obligation(str, Enum):
    mandatory = "mandatory"
    advisory = "advisory"


class Row(CoreRow):
    obligation: Obligation
    jurisdiction: str = Field(min_length=1)
    source_authority: str          # how THIS domain grades sources


EXTENSIONS = {
    "regulator_term": ext(VERBATIM, None,
                          "The regulator's own name for the obligation."),
}

CONVENTIONS = Conventions(
    staging_glob="**/rows-*.md",
    staging_prefix="rows-",
    staging_suffix=".md",
    capture_template="pages-{batch}.txt",
    begin_pattern=r"^<<< PAGE (?P<url>.+?) >>>$",
    end_pattern=r"^<<< END (?P<url>.+?) >>>$",
)

PROFILE = register(Profile(
    name="compliance-posture",
    description="Regulatory obligations by jurisdiction and instrument.",
    row_model=Row,
    extensions=EXTENSIONS,
    conventions=CONVENTIONS,
))
```

Then add `from . import compliance_posture` to `profiles/__init__.py`.

**Do not** add grading vocabulary to `CoreRow` because your domain needs it.
`evidence_grade` and `confidence` were in the core until v5; they are one
programme's scale, and a core that fixes them makes its own first corpus the
standard for every corpus after it.

`tests/test_domain_agnostic.py` is a worked example — it builds a profile,
a corpus with different file names and markers, and runs the real gates.

---

## 4 · Adding an extension field

An extension is a field the *subject* uses that the contract does not name.
Registering it is deliberate, in a commit, with a note:

```python
"plan_gating": ext(VERBATIM, None,
                   "Which plan or tier gates the feature, in the subject's "
                   "words."),
```

| kind | meaning |
|---|---|
| `VERBATIM` | the subject's own structure or vocabulary |
| `PROVENANCE` | how we came to record something |
| `BATCH_LEVEL` | a fact about the batch, repeated on each row |
| `ANNOTATION` | a one-off note — a candidate for consolidation |

`alias_of` records how the field relates to a core or profile field
(`mechanism_raw` → `mechanism`) **without renaming anything**. Rows keep the
exact keys the collector wrote; renaming would be the editing this package
exists to prevent.

**Never constrain an extension's values.** Not with an enum, not with a
pattern. The registry gates the name so the schema cannot grow silently; the
value is the subject's business.

Workflow when a new subject arrives:

```bash
python -m kbqa sweep --root <corpus> --field-values   # names not in the contract
# register what appears, with a note on what the subject means by it
python -m kbqa sweep --root <corpus>                  # re-run
```

---

## 5 · Adding a gate

1. New module in `gates/`, exporting `run(argv) -> (Verdict, exit_code)`
2. Register it in `cli.GATES`
3. **Write the failing fixture first.** A gate that has never failed has not
   been tested
4. Add a remedy for every finding code in `report.REMEDIES`, and classify it
   `structural` / `planner` / `fixable` — `tests/test_report.py` fails if a code
   has no remedy
5. Add the code to `report.GAP_CODES` if it describes an absence

### Exit codes

| code | meaning |
|---|---|
| 0 | PASS |
| 1 | FAIL, or a usage error |
| **2** | **DECLINED, and nothing else** |

Exit 2 means a subject is closed to us. A typo must never be readable as a
permission decision, so usage errors exit 1.

---

## 6 · Invariants — things that must not break

These are enforced by tests. If one fails, the question is not "update the
test" — it is whether the change is right.

**The core stays universal.** `test_the_core_contains_only_universal_fields`
pins the exact field set. Adding one costs nothing today and breaks the *next*
domain, which nobody is testing when they add it.

**No profile vocabulary in `models.py`.** No `Mechanism`, `Outcome`,
`EvidenceGrade` importable from the shared module.

**Registries do not leak between profiles.** A field registered for one domain
is refused in another, so the first corpus cannot set what later ones may say.

**The probe never discloses content.** `tests/test_probe.py` extracts quotes
and URLs from a fixture and fails if any reach the report, prefixes included.
Redaction is key-aware, not length-based — a product name is usually short.

**Fixtures are generated, never hand-edited.** CI regenerates and fails on any
diff. Editing a fixture to make a gate pass is the exact failure mode this
package exists to catch.

**Every finding code has a remedy.** A report that falls back to "see the
message" for its most important findings is not a report.

**Gates are read-only.** They write a verdict and nothing else. `report` and
`sweep` write their own artifacts; no gate mutates collected data, ever.

---

## 7 · Known traps

Ten defects were found by running this tool against a real corpus. Every one
produced findings that were **untrue of the data**. They share one shape:
*a constraint invented from a specification or a single sample, then applied as
if it were a law.*

| what happened | cost | lesson |
|---|---|---|
| Parser assumed one row serialisation | 181 rows read as zero | A decode failure in one shape is a signal to try another, not a verdict |
| `id` pattern rejected `_` | 857 rows | Check whether a character is *actually* invalid or merely unfamiliar |
| `id` pattern required 2 segments | 47 rows | Top-level nodes have one-word ids |
| `id` pattern allowed `_` but not `-` in segment one | 47 rows | Arbitrary asymmetries are bugs |
| `depth_level: str` vs collector's integers | 170 rows | Declare the type the data has, not the type you imagined |
| Frontmatter rejected folded scalars | whole batches | A strict parser must still read what the format allows |
| Pages read only from frontmatter | false `no_declared_pages` | Two conventions can both be legitimate |
| Marker-less capture → per-row findings | 181 false findings | Impossible is not the same as failing |
| G6 counted rows with the wrong pattern | every tree would fail | Count through the parser, never a regex |
| `field_distribution` hid long values | 9 unregistered fields | A diagnostic that omits what it cannot summarise is worse than one that says "too long to show" |

**The base rate matters:** every batch failing 100% turned out to be a checker
defect. Before concluding a corpus is bad, check whether the rule it breaks is
one you can justify.

### The redaction trap

The probe exists so a format can be confirmed by someone who must not read the
data. Two ways it has broken:

- **length-based redaction** let short values through — fixed by making it
  key-aware
- **new output sections** bypass redaction unless routed through `_line_shape`

Any new probe output must go through `_line_shape`, and any new field-level
disclosure must be justified as schema rather than data.

---

## 8 · Testing

```bash
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest tests/ -q
```

189 tests.

| file | covers |
|---|---|
| `test_gates.py` | every gate proven to fail on a purpose-built fixture |
| `test_parsing.py` | all three row serialisations, naive cross-check per format |
| `test_models.py` | the contract: core strict, extensions registered, values free |
| `test_probe.py` | **confidentiality** — fails if row content reaches the report |
| `test_report.py` | every finding code has a remedy; classification is right |
| `test_sweep.py` | the audit is honest about what it cannot know |
| `test_domain_agnostic.py` | the gates work in a second domain; anti-drift guards |
| `test_cli.py` | dispatch, exit codes, recording flags |

Fixtures are built by `tests/build_fixtures.py`, deterministically. Ground
truth is authored, so `good/` is *known*-good rather than assumed-good, and
each `bad_*` fails for exactly one known reason.

---

## 9 · Release

### Versioning

[SemVer](https://semver.org/), with one project rule:

> **The row contract is part of the public API.** Any change that could make a
> previously valid row invalid is a MAJOR bump, even if no Python signature
> changed. A batch that passed yesterday and fails today without the data
> changing is a breaking change to its consumers.

| bump | when |
|---|---|
| MAJOR | contract change; a gate becomes stricter; a finding code removed or reclassified |
| MINOR | a new gate, command, profile, or finding code; a gate becomes more precise without rejecting previously valid rows |
| PATCH | a fix that changes no verdict on valid data; docs; tests |

### Process

1. Branch. `main` requires a PR — direct pushes are rejected with `GH013`
2. Update `CHANGELOG.md` (Keep a Changelog), and `docs/DECISIONS.md` for any
   contract change, with evidence and a reversal condition
3. Bump `pyproject.toml` **and** `src/kbqa/__init__.py` together
4. `pytest tests/ -q` green; fixtures regenerate byte-identically
5. Update pins in `ci/estate-qa.yml` and `ci/estate-pre-push`
6. **Put `Co-Authored-By` in the PR *body*** — squash merges use the body, not
   the commit message. A trailer only in the commit is lost on merge
7. Merge, wait for the **Merged** badge, *then* resync locally. Resetting before
   the merge lands silently leaves you on the old commit, and everything after
   operates on the wrong one
8. Tag `vMAJOR.MINOR.PATCH`, push the tag
9. Confirm CI is green **on the tag** — that is what corpora pin, not `main`

### Pinning

Corpora install from a **tag, never a branch**. A branch would let the gates and
the data they judge change in the same push.

`manifest_sha256` in every verdict identifies the exact gate code that produced
it. After a version bump, G6 reports `manifest_mismatch` once per gate against
verdicts recorded under the old code — that is tamper-evidence working. Re-run
the gates; never reconcile by editing a recorded manifest.

### Packaging note

`pip < 21.3` cannot read this project's PEP 621 metadata and installs an empty
package named `UNKNOWN-0.0.0`, printing `Successfully installed`. Always
upgrade pip first.

---

## 10 · Trust model for maintainers

The package's own repository is the only part at level 4 (spec §0): public, with
required status checks that block a merge. The corpus it validates typically
cannot be — a private repo on a free plan cannot enforce rulesets.

That asymmetry is deliberate and documented in `DECISIONS.md` D-003. It means:

- **Anything that must not be editable belongs in the gates**, not in the
  corpus's CI. G6's `batch_unchecked` and `verdict_stale` live here for exactly
  that reason: whoever skips a check cannot edit the check that notices
- Never describe a corpus as tamper-proof. The accurate statement is *the gates
  cannot be edited; running them can be skipped; skipping is recorded*

If a maker agent ever gets push access to a corpus, §0's "enough when a human
reads the verdicts" stops holding, and that decision must be revisited.
