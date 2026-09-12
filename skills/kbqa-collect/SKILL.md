---
name: kbqa-collect
description: Collect one batch into the estate — permission, capture, rows — by delegating to the fetcher and row-writer subagents. Use when starting a new batch, resuming collection on a subject, or re-fetching a batch that has no capture. Cannot fetch, cannot write, and cannot read verdicts; every step happens in a subagent.
allowed-tools: Task, Agent, Read
---

# Collecting one batch

You orchestrate. You do not collect.

Notice what you have: `Task`/`Agent` and `Read`. **No `WebFetch`, no `Write`, no
`Bash`.** You cannot fetch a page, cannot create a file, and cannot run a
command. This is not a restriction to work around — it is the design. A session
that can both fetch and write will do both, and rows written from the same
context that fetched them are not grounded in a capture; they are grounded in
memory of a page, which is the failure this whole pipeline exists to prevent.

So every step below is a delegation. If a step seems blocked, the answer is
always "delegate it", never "do it directly" and never "ask for the tool".

## 1 · Permission and capture — delegate to `fetcher`

Spawn the **fetcher** subagent. Give it the host, the URLs, the batch name and
the subject directory. It holds `WebFetch`, `Write`, `Read` and `Bash`; you hold
none of those.

It returns a receipt: the capture path, the capture's **sha256**, every page URL
in file order, failures, and redirects.

**Carry that receipt forward verbatim.** It is the only thing that crosses from
the fetching context to the writing one.

If G0 returned exit 2 for a host, the fetcher stops and says so. That host is
closed: no retry, no alternate fetcher, no different user-agent. Record it as a
stop-condition through the fetcher and move on.

## 2 · Rows — delegate to `row-writer`

Spawn the **row-writer** subagent in a separate call. Give it:

- the capture path
- the sha256 **from the receipt** — it must copy this, never compute it
- the page list from the receipt
- the batch name and subject directory

It holds `Read`, `Write`, `Bash` and **no network tool**, so the capture is the
only thing it can draw on. That is what makes the rows grounded rather than
recalled.

## 3 · Report what happened

Return: batch name, capture path, page count, row count, and any failures or
stop-conditions the fetcher reported.

**Do not run the gates and do not report a verdict.** You cannot — you have no
`Bash` — and you should not want to. A collecting context that sees its own
verdict will iterate against it, and "edit until green" is precisely the loop
the separation exists to break. The gates are run by the human between the
maker and the checker.

## 4 · One batch, one session

Finish the batch and stop. Do not start a second batch in the same session:
the verbatim rule is followed perfectly at the start of a context and
imperfectly two hundred messages in, and a fresh session costs nothing.

Keep batches small. A batch is a handful of pages on one surface, not a
product.

## 5 · What you must never do

- Ask for `WebFetch`, `Write` or `Bash`, or suggest the user grant them
- Reconstruct a page from memory, training data, or another session
- Pass a page's *content* to the row-writer. Pass the capture **path** — the
  row-writer reads the file itself, and content passed through you has been
  through a summarising context
- Compute the capture's sha256 anywhere but in the fetcher
- Read `_qa/` verdicts or reports
- Start a second batch in this session

## The limit, stated honestly

Two things this skill cannot enforce, which the human in the loop must:

**The capture is what the fetcher's tool returned, not necessarily what the
page served.** If it fetched through a tool that converts or summarises,
`source_quote` will match the capture and G3 will pass while the text differs
from what a reader sees on the vendor's page. Verify this once per fetch
mechanism by comparing one captured sentence against the live page.

**Nothing checks that a quote supports its claim.** G3 verifies the quote is
real and on the cited page. A row claiming more than its quote warrants passes
every gate.
