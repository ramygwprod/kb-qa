---
name: kbqa-collect
description: Collect one subject into the estate — permission, capture, rows — by delegating to the fetcher and row-writer subagents, window by window until the source runs out. Use when the operator names a subject to collect, resumes a parked subject, or re-fetches one that has no capture. Cannot fetch, cannot write, cannot read verdicts; every step happens in a subagent.
allowed-tools: Task, Agent, Read
---

# Collecting a subject

**Invoked as:** `/kbqa-collect <Subject Name>`

You orchestrate. You do not collect.

Notice what you have: `Task`/`Agent` and `Read`. **No `WebFetch`, no `Write`, no
`Bash`.** You cannot fetch a page, create a file, or run a command. That is the
design, not an obstacle — a session that can both fetch and write will do both,
and rows written from the same context that fetched them are grounded in a
memory of a page rather than in a stored capture.

Every step below is a delegation. If a step seems blocked, the answer is always
*delegate it* — never *do it directly*, and never *ask for the tool*.

## What a finished subject looks like

Aim at this. Do not aim at "the gates stop complaining" — the gates are a floor,
and a batch can clear them while being poor work.

- **Every page a row cites is in the capture, verbatim**, including the
  subject's typos, spacing and section order.
- **Every row's quote comes from the page that row is about** — not from
  elsewhere in the capture that happens to contain the words.
- **Every row's claim is no larger than its quote supports.** No gate checks
  this. It is the single most common way a clean-looking batch is wrong.
- **Where the page is silent, the row says `unknown`** — not the industry-typical
  value, not what the subject probably means.
- **The subject's own vocabulary survives.** Their names for their things, their
  nesting, their categories. Aliases are added later by someone else; nothing
  here renames anything.
- **The denominator is the subject's own index**, captured before scope was
  decided, and not pruned to match what was fetched.
- **The windows form an unbroken chain ending in `exhausted`** — or a deliberate
  park with an offset, which is an honest stopping point and not a failure.

## 1 · Locate the subject

One directory per subject, under the estate's existing container — the same
layout every other subject uses. Read the estate to confirm it before delegating
anything; if the subject has no directory yet, say so and ask rather than
inventing a location.

Batch names carry a date: `<surface>-<YYYY-MM-DD>`. A capture's filename is
derived from the batch name, so re-using one overwrites a stored capture, which
destroys evidence rather than updating it.

## 2 · Permission and the index — delegate to `fetcher`

Spawn the **fetcher** subagent. It holds `WebFetch`, `Write`, `Read`, `Bash`;
you hold none of those.

It checks `robots.txt` first (G0). On a refusal it stops for that host — no
retry, no alternate fetcher, no rendering service — and records a stop-condition.

Before scope is decided, it captures the subject's **own index** as the
denominator. That is what coverage is later measured against, so it must be the
subject's list rather than a list of what anyone intends to fetch.

## 3 · Loop the windows until the source runs out

This is the body of the job. Repeat until done:

1. Delegate one window to the **fetcher**. It captures pages and returns a
   receipt: capture path, **sha256**, page list, per-page item counts, failures,
   and `window_end`.
2. Delegate that capture to the **row-writer**, passing the receipt values —
   above all the sha256, which it must **copy, never recompute**. It holds
   `Read`, `Write`, `Bash` and no network tool, so the capture on disk is its
   only possible source.
3. Read the `window_end`:
   - **`exhausted`** — the source returned nothing. The subject is done. Stop.
   - **`budget`** — the fetcher stopped while healthy and more remains. Loop
     again from the next offset.
   - **`error`** — the attempt failed partway. That range is unattempted, not
     absent. Report it and stop; the operator decides whether to retry.

**Keep looping.** You can sustain many windows because the page content lives in
the subagents' contexts, not yours — you hold only receipts and counts. Do not
stop after one window because it felt like a complete unit of work.

**Never write `exhausted` yourself, and never infer it.** It comes from the
fetcher, and only after it asked again and got nothing. A short window is not
the end of a list.

## 4 · Report and stop

Return:

- subject and directory
- one line per window: offset, requested, returned, `window_end`, row count
- the capture paths and their sha256 values
- total pages, total rows
- fetch failures, redirects, stop-conditions
- **whether the subject reached `exhausted`, or is parked at an offset**

**Do not run the gates and do not report a verdict.** You cannot — you have no
`Bash` — and you should not want to. A collecting context that sees its own
verdict will iterate against it, and *edit until green* is the loop this
separation exists to break. The operator runs `/kbqa-check` when ready.

## 5 · Never

- Ask for `WebFetch`, `Write` or `Bash`, or suggest the operator grant them
- Reconstruct a page from memory, training data, or another session
- Pass a page's *content* to the row-writer — pass the capture **path**, because
  content routed through you has been through a summarising context
- Compute a capture's sha256 anywhere but in the fetcher
- Read `_qa/` verdicts or reports
- Re-use a batch name that already has a capture
- Prune the denominator to match what was fetched
- Declare a subject complete on anything but `exhausted`

## The limits, so a clean run is not read as more than it is

**Nothing checks that a quote supports its claim.** G3 verifies the quote is
real and on the cited page. That is all it verifies.

**The capture is what the fetch tool returned**, not necessarily what the server
sent. A tool that converts or summarises yields quotes matching the capture and
differing from the page.

**Coverage is measured against the index we captured.** A selective index goes
unnoticed, which is why the fetcher captures it before scope is decided.
