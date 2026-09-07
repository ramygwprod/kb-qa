# Agent definitions — role separation by capability

These are the canonical, version-controlled copies. They are **not** active in
this repository: `kb-qa/` is the checker, and these define the *collector's*
roles.

## Install

Copy both into the data estate, not here:

```
<estate>/.claude/agents/fetcher.md
<estate>/.claude/agents/row-writer.md
```

## Why they exist

Attestation is not proof. A prompt saying "do not fetch your own sources" is an
instruction that can be forgotten under pressure — and §7 of the spec records
what happens when checks depend on good intentions.

**The row-writer has no `WebFetch`.** Role separation becomes a fact about the
environment rather than a rule the agent is asked to remember. `G6` still checks
the `fetched_by_this_agent` attestation, but that check is a backstop for a
collapse that the tool list should have made impossible in the first place.

## The limit

An agent definition is a file on disk in the estate the collector can write to.
Like every other level 1–3 mechanism in this project, it is tamper-**evident**,
not tamper-proof. Only CI running the gates from a pinned version closes that.
