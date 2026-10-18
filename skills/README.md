# Skills — the pipeline as capability, not instruction

Canonical, version-controlled copies of the three skills that run the pipeline,
and (in `../agents/`) the collector's three subagents. They are **not active in
this repository** — `kb-qa/` is the validator, and these are for the sessions
that collect into an estate, check it and merge it.

| skill | the operator types | does |
|---|---|---|
| `kbqa-collect` | `/kbqa-collect <Subject>` | plan → approval → captures → rows → two classification passes |
| `kbqa-check` | `/kbqa-check <subject folder>` | the gates per batch and per surface; CLEAR · BLOCKED · PARKED · NOT CHECKED |
| `kbqa-merge` | `/kbqa-merge <subject folder> <batch>` | appends one CLEAR batch to `feature-tree.md` |

Each runs in its own session, in the estate.

## The principle

A markdown file that says "delegate to the fetcher" is a request. Under time
pressure, in a long context, or when delegating is inconvenient, it is skipped —
and nothing notices, because the output looks the same either way.

So the roles are separated by **what each can do**, not by what it is asked to
do, wherever the runtime allows it — and where it does not, the limit is named
rather than rewritten as a stronger instruction.

- **A subagent's `tools:` list is an allowlist.** The row-writer and the mapper
  hold `Read` and `Write` only: no network, no shell. The fetcher holds the
  network and writes captures, never rows.
- **A skill's `allowed-tools` is not.** It pre-approves tools and takes none
  away, so the collecting orchestrator's "delegate every step" is a rule it
  keeps, not a wall.
- **The collector never sees a verdict.** The check runs in a separate session;
  a collecting session can also be started with
  `kbqa-collect/collect-session-settings.json`, which denies reading `_qa/`.
- **`kbqa-check` holds no `Edit` and no `Write`.** It cannot modify a gate, a
  capture or a row. `kbqa-merge` is `disable-model-invocation`: only the
  operator runs it.

## Install

All three skills and the three agents, from one tag, by the operator in their
own terminal (PIPELINE-SPEC §5):

```bash
bash skills/install.sh v6.20.0
```

It clones the tag, copies each skill to `~/.claude/skills/<skill>/` and the
agents to `~/.claude/agents/`, and writes `INSTALLED-FROM-<skill>` in each
skill's folder — the tag, the commit and the sha256 of every installed file; the
collector's record also lists its agents as `agents/<file>`. Every installed file is made read-only, so a session — its scripts included —
can use the skills and agents but not overwrite them. Anything replaced is moved
to `~/.kbqa-check-backups/`, outside the skills folder, never deleted (made
writable only to move it; delete backups with `chmod -R u+w` first).
The script then prints the `pip` command for the validator itself, which the
operator also runs, and the pre-flight:

```bash
bash ~/.claude/skills/kbqa-check/scripts/preflight.sh kbqa-check kbqa-merge kbqa-collect
```

It STOPs on any installed file that differs from its record, and on an agent of
the same name in the project's own `.claude/agents/` (a project agent overrides
a user one). Each skill runs it for itself before anything else.

## Settings — one snippet for the estate, one file for a collecting session

- **`kbqa-check/settings-snippet.json`** goes into the estate's
  `.claude/settings.json`. It closes the bypass routes — writes into an
  installed `kbqa`, `pip` in any form, `.git/hooks`, `.github/workflows`,
  `--no-verify` — the settings file itself, the installed skills and agents
  (`~/.claude/skills/**`, `~/.claude/agents/**`) and the project's own
  `.claude/agents/**`.
- **`kbqa-collect/collect-session-settings.json`** denies reading `_qa/` and the
  QA logs. **Never merge it into the estate's settings**: the check runs in the
  same project and must read `_qa/`. Load it only for a collecting session:

  ```bash
  claude --settings ~/.claude/skills/kbqa-collect/collect-session-settings.json
  ```

**Substitute the checkout placeholder.** The snippet carries

```
Edit(//ABSOLUTE/PATH/TO/YOUR/kb-qa/CHECKOUT/**)
Write(//ABSOLUTE/PATH/TO/YOUR/kb-qa/CHECKOUT/**)
```

Replace it with the real path of your local kb-qa working copy, **keeping the
two leading slashes**: `//Users/you/…`, or `~/…` from your home folder. A rule
path with ONE leading slash is read relative to the settings file, not the
filesystem root (Claude Code docs, Permissions), so `Edit(/Users/you/…)` protects
nothing. Until v6.15.1 this placeholder had one slash. The generic
`**/kb-qa/**` rules beside it only match a directory literally named `kb-qa`,
and a checkout can be called anything — so without this substitution a session
can edit the gates through your working copy while every other route is closed.
A placeholder left unsubstituted denies a path that does not exist, which is
harmless and useless.

## What capability cannot reach

Three limits, named so the enforcement is not mistaken for completeness.

**The orchestrator can still fetch.** `allowed-tools` pre-approves; it does
not remove. A collecting session that ignores its skill can fetch and write
itself, and the rows would then be grounded in that context's memory of a page.
What catches it afterwards: the staging file must cite a capture whose sha256
the fetcher recorded, and every quote must be in that capture (G1, G3). What
cannot: a capture the orchestrator wrote itself, hashed by itself. **Verify
once** on your setup that the `kbqa-row-writer` subagent cannot fetch.

**A capture is the served HTML, not what a browser shows after JavaScript.**
`kbqa capture` keeps the raw bytes and renders them as text the same way every
time, so a quote can always be re-checked against the bytes. Text a page builds
with JavaScript after loading is not in the bytes: such a page is recorded
`js-only`. Until v6.17.0 captures went through WebFetch, which returns a model's
summary and refuses to reproduce more than a short quote — no capture through it
could be verbatim, and the first live collection captured nothing.

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

`kbqa-check/scripts/preflight.sh` pins the version (`PINNED`) and the manifest
SHA (`EXPECTED_MANIFEST`) — the values the pre-flight actually compares.
`tests/test_skill_pin.py` fails the release if either goes stale, if the
check skill gains a writing tool, if an agent's tools change, or if a deny rule
is dropped.

```bash
python3 -m kbqa --version
python3 -m kbqa --manifest | head -1
```
