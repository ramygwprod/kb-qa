# Skills — the pipeline as capability, not instruction

Canonical, version-controlled copies of the two skills that run the pipeline.
Like `agents/`, they are **not active in this repository** — `kb-qa/` is the
validator, and these are for the sessions that collect into an estate and check
it.

## The principle

A markdown file that says "delegate to the fetcher" is a request. Under time
pressure, in a long context, or when delegating is inconvenient, it is skipped —
and nothing notices, because the output looks the same either way.

So the roles are separated by **what each session can do**, not by what it is
asked to do. Every rule below that matters is enforced by an absent tool or a
denied permission. Where something cannot be enforced, it is named as a limit
rather than rewritten as a stronger instruction.

## The two roles

| | `kbqa-collect` | `kbqa-check` |
|---|---|---|
| tools | `Task`, `Agent`, `Read` | `Bash`, `Read` |
| can fetch | **no** — must delegate to `fetcher` | no |
| can write | **no** — must delegate to `row-writer` | no |
| can run commands | **no** | yes, to run the gates |
| can read verdicts | **no** — denied | yes |

`kbqa-collect` holds no `WebFetch`, no `Write` and no `Bash`. It physically
cannot collect; it can only delegate to the `fetcher` and `row-writer`
subagents, which hold complementary halves of the job — the fetcher has the
network and no reason to interpret, the row-writer has the capture and no
network. Role separation stops being a rule the orchestrator must remember and
becomes a fact about its tool list.

`kbqa-check` holds no `Edit` and no `Write`. It cannot modify a gate, a capture
or a row.

## Install

```
<estate>/.claude/skills/kbqa-collect/SKILL.md
<estate>/.claude/skills/kbqa-check/SKILL.md
<estate>/.claude/agents/fetcher.md
<estate>/.claude/agents/row-writer.md
```

## Settings — the two snippets are mutually exclusive

Each skill ships a `settings-snippet.json`, and **they cannot both be active in
one settings file**: the collecting role is denied reading `_qa/`, and the
checking role must read it.

Permission denies are session-wide, so pick per session:

- a machine or checkout used for collecting merges
  `kbqa-collect/settings-snippet.json`
- one used for checking merges `kbqa-check/settings-snippet.json`

**Substitute the checkout placeholder.** Both snippets carry

```
Edit(/ABSOLUTE/PATH/TO/YOUR/kb-qa/CHECKOUT/**)
Write(/ABSOLUTE/PATH/TO/YOUR/kb-qa/CHECKOUT/**)
```

Replace it with the real path of your local kb-qa working copy. The generic
`**/kb-qa/**` rules beside it only match a directory literally named `kb-qa`,
and a checkout can be called anything — so without this substitution a session
can edit the gates through your working copy while every other route is closed.
A placeholder left unsubstituted denies a path that does not exist, which is
harmless and useless.

Both deny the same bypass classes — writes into an installed `kbqa`, `pip` in
any form, `.git/hooks`, `.github/workflows`, and `--no-verify` — plus the
settings file itself, so the boundary cannot rewrite itself. The collecting
snippet adds the `_qa/` read denies.

If you keep one settings file and a human carries findings between sessions,
use the **checking** snippet and rely on the human. Say that is what you are
doing; do not describe the read-deny as being in force when it is not.

## What capability cannot reach

Three limits, named so the enforcement is not mistaken for completeness.

**A subagent's tools are its own.** The `fetcher` holds `WebFetch` because its
definition grants it. Whether a session-level restriction also suppresses a
subagent's declared tools depends on the runtime, not on this package. **Verify
once** on your setup: ask a collecting session to fetch a URL directly and
confirm it cannot, then confirm the `fetcher` subagent still can.

**The capture is what the fetcher's tool returned, not necessarily what the
server sent.** A fetch tool that converts or summarises produces a capture whose
text differs from the page. Quotes then match the capture, G3 passes, and the
text is not what a reader sees. Verify once per fetch mechanism by comparing one
captured sentence against the live page. No gate can detect this.

**Nothing checks that a quote supports its claim.** G3 verifies the quote is
real and on the page it cites. That is all it verifies.

## Trust level

This is **level 3** — capability-denied: tamper-evident and inconvenient to
bypass, not tamper-proof. `settings.json` is a file a human can edit, and the
pinned manifest check in the checking skill detects a swapped validator after
the fact rather than before. Only CI re-running the gates from a pinned tag, on
infrastructure the collecting session cannot reach, closes that — and on a free
plan a private repo cannot require that check, which is why the estate sits at
level 3½ and why a human reading the verdicts is load-bearing.

## Keeping the pins current

`kbqa-check/SKILL.md` pins the version and the manifest SHA.
`tests/test_skill_pin.py` fails the release if either goes stale, if either
skill gains a writing tool, or if a deny rule is dropped.

```bash
python3 -m kbqa --version
python3 -m kbqa --manifest | head -1
```
