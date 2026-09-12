# Skills — how an agent is meant to use the validator

The canonical, version-controlled copy of the checking skill. Like `agents/`,
it is **not active in this repository** — `kb-qa/` is the validator itself, and
this skill is for the sessions that *run* it against a data estate.

## Install

```
<estate>/.claude/skills/kbqa-check/SKILL.md
<estate>/.claude/skills/kbqa-check/settings-snippet.json
```

Then merge `settings-snippet.json` into `<estate>/.claude/settings.json`. If
that file already has a `permissions.deny` list, append the entries rather than
replacing it.

## What the skill does

It gives an agent the correct procedure — verify the validator, run the report
cycle, read the Coverage section, route findings by class — and the boundary it
must not cross. It also carries the three things the gates cannot see, so a
clean run is never reported as more than it is.

## Why the tool-list and the deny rules exist

The skill declares `allowed-tools: Bash, Read`. It has **no `Edit` and no
`Write`.** An agent working under it cannot modify the validator, a capture, or
a row, because the tools to do so are absent — not because the file asks it not
to.

That covers the skill's own execution. `settings-snippet.json` covers the rest
of the session, and it denies four classes of thing:

| denied | why |
|---|---|
| writes into `site-packages/kbqa`, `dist-packages/kbqa`, any `kb-qa/` checkout | editing the gate that is failing is the failure this package exists to catch |
| `pip` in any form | reinstalling or `pip install -e` swaps the pinned validator for an editable one, which is the same act by another route |
| `.git/hooks/**`, `.github/workflows/**` | the pre-push hook and the CI workflow are the enforcement. An agent that can edit them can switch the checking off |
| `--no-verify` on push and commit | bypassing the hook is meant to be a deliberate human act, not an agent's convenience |

`.claude/skills/**` and `.claude/settings.json` are denied too, so the boundary
cannot rewrite itself.

## The limit, stated plainly

This is **level 3** in the spec's §0 table — capability-denied, therefore
tamper-*evident* and inconvenient to bypass. It is not tamper-proof:

- `settings.json` is a file in the estate a human can edit, and an agent running
  outside this skill may have tools this skill does not.
- The pinned manifest check in §0 of the skill detects a swapped validator
  **after** the fact, not before.

Only level 4 closes it — CI re-running the gates from a pinned tag, on
infrastructure the collecting agent cannot reach. On a free GitHub plan a
private repo cannot require that status check, so the estate sits at level 3½:
the evidence is produced, and it works because a human reads it. See
`ci/estate-qa.yml` for what that costs and how to fix it.

## Keeping the pin current

The skill pins `6.0.0` and its manifest SHA. Both must be updated together on
every kbqa release, in the same commit that tags it — a stale pin makes the
§0 check fire on a legitimate upgrade, and an agent that learns to ignore that
check has lost the one signal that a validator was swapped.

```bash
python3 -m kbqa --version
python3 -m kbqa --manifest | head -1
```
