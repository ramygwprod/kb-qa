# Agent definitions — the collector's three subagents

The canonical, version-controlled copies of the subagents `/kbqa-collect`
delegates to. They are **not** active in this repository.

| agent | tools | does |
|---|---|---|
| `kbqa-fetcher.md` | `WebFetch`, `Write`, `Read`, `Bash` | permission (G0), each surface's index, captures, stop-conditions, receipts |
| `kbqa-row-writer.md` | `Read`, `Write` | the staging file, from the capture on disk alone |
| `kbqa-mapper.md` | `Read`, `Write` | one classification pass (A or B) of one batch |

## Install

With the skills, from a tag, by the operator in their own terminal:

```bash
bash skills/install.sh <tag>
```

They go to `~/.claude/agents/`, and their sha256 values go into the collector's
install record (`INSTALLED-FROM-kbqa-collect`, as `agents/<file>`). The
pre-flight — `preflight.sh kbqa-check kbqa-collect`, which the fetcher runs
before anything else — STOPs when an installed agent differs from the record,
or when the project the session runs in has an agent of the same name in its
own `.claude/agents/`: a project agent overrides a user one, so the recorded
agent would silently not be the one used. Never copy these into a project.

## Why they exist

Attestation is not proof. A prompt saying "do not fetch your own sources" is an
instruction that can be forgotten under pressure. A subagent's `tools:` list is
an allowlist, so **the row-writer has no network and no shell**: its only
source is the capture, and it cannot run a gate on its own output. Role
separation becomes a fact about the environment rather than a rule an agent is
asked to remember. `G6` still checks the `fetched_by_this_agent` attestation,
as a backstop.

## The limit

`install.sh` makes the installed agents read-only, the deny rules stop a
session's file tools editing them, and the install record makes any change
**evident** at the next pre-flight. None is tamper-proof: a process running as
the operator can change a file's permissions back. Only the OS sandbox or CI
running the gates from a pinned version closes that.
