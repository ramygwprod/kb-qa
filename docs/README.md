# Documentation index

Organised by the [Diátaxis](https://diataxis.fr/) framework: four kinds of
document, each answering a different kind of question. The framework's central
claim is that documentation becomes confusing when the kinds are mixed — a
reader looking up a finding code does not want an argument about evidence, and a
reader deciding whether to trust a verdict is not helped by a table of flags.

**Everything in `docs/` is listed here.** `tests/test_docs_track_the_code.py`
fails the build if a file exists and this index does not name it, because a
document nobody can find is a document nobody reads.

---

## Start here

| you are | read |
|---|---|
| running the pipeline day to day | [MANUAL §0 and §5](MANUAL.md) |
| an agent about to check a batch | the `kbqa-check` skill, not these docs |
| deciding whether to trust a verdict | [MANUAL §8 · Trust model](MANUAL.md) |
| extending the package | [DEVELOPMENT.md](DEVELOPMENT.md) |
| wondering why something is the way it is | [DECISIONS.md](DECISIONS.md) |

---

## Tutorial — learning by doing

*Take me through it once so I understand the shape.*

- **[MANUAL §0 · Quickstart](MANUAL.md)** — install, verify, first commands.
  The two commands the pipeline is driven by, then what they do underneath.

## How-to guides — achieving a goal

*I know what I want; tell me the steps.*

- **[MANUAL §5 · Workflows](MANUAL.md)** — ten procedures. §5.1 one collection
  round, §5.2 a mapping round, §5.3–§5.10 auditing, checking, resuming,
  adopting a hash, confirming a format, and the full pipeline runbook.
- **[MANUAL §10 · Troubleshooting](MANUAL.md)** — thirty entries, grouped by
  symptom rather than by gate, each saying cause, fix, and where it matters,
  what is *not* a fix.
- **[DEVELOPMENT §3–§5](DEVELOPMENT.md)** — adding a domain, an extension
  field, a gate.

## Reference — information you look up

*What is the exact value, name, code, exit status?*

- **[MANUAL §6 · All available actions](MANUAL.md)** — every command, what it
  reads, what it writes, its acceptance criterion and exit codes.
- **[MANUAL §7 · Findings reference](MANUAL.md)** — every finding code with its
  class, nature and remedy. Guarded by a test: a code with a remedy and no entry
  here fails the build.
- **[MANUAL §4 · The corpus](MANUAL.md)** — the three tiers, and what a
  well-formed row, batch, subject and corpus are.
- **[DEVELOPMENT §2 · Architecture](DEVELOPMENT.md)** — module map, data flow,
  gate anatomy, on-disk contract, key structures.
- **[MAPPING-CONTRACT.md](MAPPING-CONTRACT.md)** — the shape of a mapping
  statement, the SKOS relation vocabulary, the status vocabulary.
- **[STAGING-FORMAT.md](STAGING-FORMAT.md)** — the on-disk format of a staging
  file, capture and denominator, and the open questions against it.

## Explanation — understanding why

*Why is it built this way, and what does it not do?*

- **[MANUAL §8 · Trust model](MANUAL.md)** — the four levels, and why only the
  fourth is tamper-proof.
- **[MANUAL §11 · Do / Don't](MANUAL.md)** — the boundary between satisfying a
  gate with data and satisfying it by changing the gate, and the three things
  no gate can see.
- **[DECISIONS.md](DECISIONS.md)** — fifteen decision records, each with the
  evidence that forced it and the condition under which it would be reversed.
  Closest thing here to an ADR log, and the place to look before proposing that
  something be changed back.
- **[DEVELOPMENT §7 · Known traps](DEVELOPMENT.md)** — defects found by running
  this package against real data, and the pattern they share.
- **[pipeline.html](pipeline.html)** — the pipeline drawn: four role lanes, the
  isolation boundary, the window loop, the mapping round, and where the
  guarantees stop. Open it in a browser; it is self-contained.

---

## For an AI session

**[`/llms.txt`](../llms.txt)** at the repository root is the machine-readable
index, following the [llms.txt convention](https://llmstxt.org/).

**Read the docs for the version you have installed.** Replace `main` with your
tag in any raw URL:

```
https://raw.githubusercontent.com/ramygwprod/kb-qa/v6.13.1/docs/MANUAL.md
```

`main` moves. A session reading tomorrow's manual while running today's package
is the same drift this package spends its time catching elsewhere — and the
version is printed by `python3 -m kbqa --version`.

**If you are running the pipeline rather than reasoning about it, the skills are
the source, not these documents.** `kbqa-collect` and `kbqa-check` carry the
procedure and the boundary; they are versioned with the package and pinned to a
manifest. These docs explain and record. The skill is what binds.
